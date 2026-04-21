from django.shortcuts import render, redirect
from django.contrib.auth.models import User
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from .models import *
from .chatbot import *
from .utils import *
from django.views.decorators.csrf import csrf_exempt
from datetime import datetime, timedelta
from django.utils import timezone
from django.core.cache import cache
from django.core.paginator import Paginator
import json
import time
import threading
import google.generativeai as genai
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Avg, Sum, Max, Min, Q, FloatField
from django.db.models.functions import TruncDate, TruncWeek, TruncMonth, Coalesce, Cast
from django.db import connection as db_connection

# ── Feature 2: Allowed test topics (canonical, lower-case) ──────────────────
ALLOWED_TOPICS = {'reasoning', 'aptitude', 'english'}

# Map display names / URL slugs → canonical topics
TOPIC_ALIAS_MAP = {
    'reasoning': 'reasoning',
    'aptitude': 'aptitude',
    'quantitative aptitude': 'aptitude',
    'quant': 'aptitude',
    'english': 'english',
    'verbal': 'english',
    'verbal ability': 'english',
}

def normalise_topic(raw_topic: str) -> str | None:
    """Return canonical topic name or None if not allowed."""
    return TOPIC_ALIAS_MAP.get(raw_topic.lower().strip())


# Create your views here.

def index(request):
    return render(request, 'index.html')

def user_login(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(username=username, password=password)
        if user:
            login(request, user)
            return redirect('dashboard')
        else:
            messages.error(request, 'Invalid credentials')
            return redirect('user_login')
    return render(request, 'user_login.html')

def user_signup(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        confirm_password = request.POST.get('confirm_password')
        password = request.POST.get('password')

        # Check if passwords match
        if password != confirm_password:
            messages.error(request, 'Passwords do not match!')
            return redirect('user_signup')

        # Check if the username already exists
        if User.objects.filter(username=username).exists():
            messages.error(request, 'Username already exists!')
            return redirect('user_signup')

        # Check if the email already exists
        if User.objects.filter(email=email).exists():
            messages.error(request, 'Email already exists!')
            return redirect('user_signup')
        
        # Create the user and save to the database
        User.objects.create_user(
            username=username,
            email=email,
            password=password
        )
        
        messages.success(request, 'User registered successfully')
        return redirect('user_login')
    
    return render(request, 'user_signup.html')

def dashboard(request):
    """Dashboard with user performance statistics based on StudentTestResult model"""
    
    # Get user's completed tests (finalized results only)
    completed_tests = StudentTestResult.objects.filter(
        user=request.user,
        status__in=['completed', 'auto_submitted']
    ).order_by('-created_at')
    
    # Include in-progress tests for recent tests display
    all_tests = StudentTestResult.objects.filter(
        user=request.user
    ).order_by('-created_at')
    
    total_tests = completed_tests.count()
    
    if total_tests > 0:
        # Basic statistics
        total_questions = completed_tests.aggregate(Sum('total_questions'))['total_questions__sum'] or 0
        total_correct = completed_tests.aggregate(Sum('correct_answers'))['correct_answers__sum'] or 0
        avg_score = completed_tests.aggregate(Avg('score_percentage'))['score_percentage__avg'] or 0
        best_score = completed_tests.aggregate(Max('score_percentage'))['score_percentage__max'] or 0
        
        # Calculate CI Score (weighted average of recent tests)
        weighted_scores = []
        weights = []
        for idx, test in enumerate(completed_tests[:10]):
            weight = 1.0 / (idx + 1)
            weighted_scores.append(float(test.score_percentage) * weight)
            weights.append(weight)
        
        ci_score = sum(weighted_scores) / sum(weights) if weighted_scores else avg_score
        
        # Calculate improvement (first vs last test)
        if total_tests >= 2:
            first_test = completed_tests.last()
            last_test = completed_tests.first()
            improvement = (last_test.score_percentage - first_test.score_percentage) if first_test and last_test else 0
        else:
            improvement = 0
    else:
        total_questions = 0
        total_correct = 0
        avg_score = 0
        best_score = 0
        ci_score = 0
        improvement = 0
    
    # Domain performance (based on topic field)
    domains = ['Aptitude', 'Reasoning', 'Verbal']
    domain_performance = {}
    
    for domain in domains:
        domain_tests = completed_tests.filter(topic__icontains=domain)
        domain_data = domain_tests.aggregate(
            total_tests=Count('id'),
            avg_score=Avg('score_percentage'),
            total_questions=Sum('total_questions'),
            total_correct=Sum('correct_answers')
        )
        
        domain_total_questions = domain_data['total_questions'] or 0
        domain_total_correct = domain_data['total_correct'] or 0
        
        domain_performance[domain] = {
            'total_tests': domain_data['total_tests'] or 0,
            'avg_score': round(domain_data['avg_score'] or 0, 1),
            'total_questions': domain_total_questions,
            'total_correct': domain_total_correct,
            'accuracy': round((domain_total_correct / domain_total_questions * 100) if domain_total_questions > 0 else 0, 1)
        }
    
    # Find weakest domain
    if total_tests > 0:
        weakest_domain = min(domains, key=lambda d: domain_performance[d]['avg_score'])
    else:
        weakest_domain = None
    
    # Weekly trend data (last 7 days)
    weekly_data = []
    week_labels = []
    
    for i in range(6, -1, -1):
        day = timezone.now() - timedelta(days=i)
        day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day.replace(hour=23, minute=59, second=59, microsecond=999999)
        day_tests = completed_tests.filter(created_at__range=[day_start, day_end])
        day_avg = day_tests.aggregate(Avg('score_percentage'))['score_percentage__avg'] or 0
        weekly_data.append(round(day_avg, 1))
        week_labels.append(day.strftime('%a'))
    
    # Recent tests (all tests including in-progress)
    recent_tests = all_tests[:5]
    for test in recent_tests:
        # Format time taken
        seconds = test.time_taken_seconds
        if seconds < 60:
            test.formatted_time = f"{seconds}s"
        else:
            minutes = seconds // 60
            remaining = seconds % 60
            test.formatted_time = f"{minutes}m {remaining}s" if remaining > 0 else f"{minutes}m"
        
        # Status badge
        status_badge_map = {
            'in_progress': ('In Progress', 'warning'),
            'completed': ('Completed', 'success'),
            'auto_submitted': ('Auto Submitted', 'info'),
            'expired': ('Expired', 'secondary')
        }
        test.status_badge, test.status_class = status_badge_map.get(test.status, ('Unknown', 'secondary'))
    
    # User rank (based on completed tests)
    all_users = User.objects.filter(
        test_results__status__in=['completed', 'auto_submitted']
    ).annotate(
        avg_score=Avg('test_results__score_percentage')
    ).filter(avg_score__isnull=False).order_by('-avg_score')
    
    user_rank = None
    for idx, user in enumerate(all_users, 1):
        if user.id == request.user.id:
            user_rank = idx
            break
    
    # AI Feedback
    in_progress_count = StudentTestResult.objects.filter(
        user=request.user,
        status='in_progress'
    ).count()
    
    if total_tests == 0:
        if in_progress_count > 0:
            ai_feedback = f"You have {in_progress_count} test(s) in progress. Complete them to see your performance metrics!"
            ai_feedback_icon = "fa-hourglass-half"
        else:
            ai_feedback = "Take your first assessment to unlock personalized insights."
            ai_feedback_icon = "fa-lightbulb"
    elif ci_score >= 85:
        ai_feedback = f"Excellent performance! Focus on advanced topics to maintain your edge."
        ai_feedback_icon = "fa-crown"
    elif ci_score >= 70:
        ai_feedback = f"Strong foundation! Practice {weakest_domain} to reach the next level."
        ai_feedback_icon = "fa-star"
    elif ci_score >= 50:
        ai_feedback = f"Good progress! Regular practice in {weakest_domain} will boost your score."
        ai_feedback_icon = "fa-chart-line"
    else:
        ai_feedback = f"Keep practicing! Start with {weakest_domain or 'Aptitude'} fundamentals."
        ai_feedback_icon = "fa-seedling"
    
    # Badges/Achievements
    badges = []
    if total_tests >= 10:
        badges.append({'name': 'Dedicated Learner', 'icon': 'fa-calendar-check', 'color': 'success'})
    if best_score >= 95:
        badges.append({'name': 'Perfect Score', 'icon': 'fa-star', 'color': 'warning'})
    if improvement > 20:
        badges.append({'name': 'Most Improved', 'icon': 'fa-chart-line', 'color': 'info'})
    if domain_performance.get('Aptitude', {}).get('avg_score', 0) >= 85:
        badges.append({'name': 'Aptitude Master', 'icon': 'fa-calculator', 'color': 'primary'})
    if domain_performance.get('Reasoning', {}).get('avg_score', 0) >= 85:
        badges.append({'name': 'Reasoning Expert', 'icon': 'fa-brain', 'color': 'primary'})
    if domain_performance.get('Verbal', {}).get('avg_score', 0) >= 85:
        badges.append({'name': 'Verbal Virtuoso', 'icon': 'fa-comment-dots', 'color': 'primary'})
    
    context = {
        'user': request.user,
        'total_tests': total_tests,
        'total_questions': total_questions,
        'total_correct': total_correct,
        'best_score': round(best_score, 1),
        'ci_score': round(ci_score, 1),
        'improvement': round(improvement, 1),
        'weekly_data': weekly_data,
        'week_labels': week_labels,
        'recent_tests': recent_tests,
        'user_rank': user_rank,
        'weakest_domain': weakest_domain,
        'ai_feedback': ai_feedback,
        'ai_feedback_icon': ai_feedback_icon,
        'badges': badges,
        'domain_performance': domain_performance,
        'has_tests': total_tests > 0,
        'in_progress_count': in_progress_count,
    }
    
    return render(request, 'user_dashboard.html', context)

def user_logout(request):
    # Log the user out
    logout(request)
    
    # Optionally, display a success message
    messages.success(request, 'You have been logged out successfully!')
    
    # Redirect to login page or home page
    return redirect('user_login')  # or 'home' or any other page

def view_categories(request):
    return render(request, 'assessment.html')


@csrf_exempt
def test_conduct(request, topic, difficulty):
    """Conduct test with 20 questions, one at a time.

    Feature 2 – topic validation: only reasoning / aptitude / english allowed.
    Feature 3 – if an existing session has been submitted/expired (e.g. the
                 beacon fired because the user left), start a completely fresh
                 test.  If the existing session is still actively in-progress
                 (e.g. JS called window.location.reload() to show the next
                 question), continue from where we left off.
    """
    import uuid

    # ── Feature 2: Validate & normalise topic ──────────────────────────────
    canonical_topic = normalise_topic(topic)
    if canonical_topic is None:
        messages.error(
            request,
            f"Invalid test topic '{topic}'. Allowed topics: Reasoning, Aptitude, English."
        )
        return redirect('view_categories')
    topic = canonical_topic  # use clean name from here on

    existing_session = request.session.get('test_session')

    # ── Task 2 + prev Feature 3: Continue ONLY if topic AND difficulty match
    # and the test has not been submitted/completed yet.
    should_continue = (
        existing_session is not None
        and not existing_session.get('test_submitted', False)
        and not existing_session.get('test_completed', False)
        and existing_session.get('topic') == topic
        and existing_session.get('difficulty') == difficulty  # Task 2: timer bleed fix
    )

    if not should_continue:
        # Expire any leftover in-progress DB record from a prior session
        if existing_session:
            old_id = existing_session.get('assessment_id')
            if old_id and not existing_session.get('test_submitted', False):
                try:
                    old_result = StudentTestResult.objects.get(
                        assessment_id=uuid.UUID(old_id)
                    )
                    if old_result.status == 'in_progress':
                        old_result.status = 'auto_submitted'
                        old_result.end_time = timezone.now()
                        old_result.save()
                except (StudentTestResult.DoesNotExist, ValueError):
                    pass
            del request.session['test_session']
            request.session.modified = True

        # Create a brand-new test session
        request.session['test_session'] = {
            'questions': [],
            'current_index': 0,
            'answers': [],
            'skipped_indices': [],          # Task 3: track skipped questions
            'time_left': 20 * 60,
            'start_time': timezone.now().isoformat(),
            'topic': topic,
            'difficulty': difficulty,
            'total_questions': 20,
            'test_completed': False,
            'test_submitted': False,
            'adaptive_analysis': [],
            'assessment_id': None
        }
        request.session.modified = True

    test_session = request.session['test_session']

    # ── Get or create the DB record ────────────────────────────────────────
    try:
        if test_session.get('assessment_id'):
            test_result = StudentTestResult.objects.get(
                assessment_id=uuid.UUID(test_session['assessment_id'])
            )
        else:
            raise StudentTestResult.DoesNotExist
    except (StudentTestResult.DoesNotExist, ValueError):
        test_result = StudentTestResult.objects.create(
            user=request.user if request.user.is_authenticated else None,
            session_key=request.session.session_key,
            topic=topic,
            difficulty=difficulty,
            total_questions=20,
            start_time=timezone.now(),
            status='in_progress'
        )
        test_session['assessment_id'] = str(test_result.assessment_id)
        request.session.modified = True

    # ── Timer check ────────────────────────────────────────────────────────
    try:
        start_time_str = test_session['start_time']
        # fromisoformat returns a naive datetime; make it timezone-aware so
        # it can be compared with timezone.now() (which is always aware).
        start_dt = datetime.fromisoformat(start_time_str)
        if start_dt.tzinfo is None:
            start_dt = timezone.make_aware(start_dt, timezone.get_current_timezone())
        elapsed = (timezone.now() - start_dt).total_seconds()
        time_left = max(0, (20 * 60) - elapsed)
        test_session['time_left'] = time_left
        request.session.modified = True
    except Exception:
        time_left = 20 * 60

    test_result.time_taken_seconds = int(20 * 60 - time_left)
    test_result.save()

    # Auto-submit if time is up
    if time_left <= 0 and not test_session.get('test_submitted', False):
        test_session['test_submitted'] = True
        test_session['test_completed'] = True
        test_result.status = 'auto_submitted'
        test_result.end_time = timezone.now()
        test_result.save()
        request.session.modified = True
        messages.warning(request, "Time's up! Test automatically submitted.")
        return redirect('test_history')

    current_index = test_session['current_index']
    total_questions = test_session['total_questions']

    # Check if all questions are answered (including skipped revisit)
    answered_count = len(test_session.get('answers', []))
    skipped_pending = [
        i for i in test_session.get('skipped_indices', [])
        if i not in {a['question_number'] - 1 for a in test_session.get('answers', [])}
    ]
    if answered_count >= total_questions or (current_index >= total_questions and not skipped_pending):
        test_session['test_completed'] = True
        test_result.status = 'completed'
        test_result.end_time = timezone.now()
        test_result.save()
        request.session.modified = True
        return redirect('test_ready_to_submit', topic=topic, difficulty=difficulty)

    # ── Generate or retrieve the current question ──────────────────────────
    questions_list = test_session['questions']
    if len(questions_list) <= current_index:
        try:
            current_difficulty = test_session.get('difficulty', difficulty)
            new_question = call_gemini_api(
                topic, current_difficulty, current_index + 1, total_questions
            )
            questions_list.append(new_question)
            test_session['questions'] = questions_list
            request.session.modified = True
        except Exception as e:
            messages.error(request, f"Error generating question: {str(e)}")
            return redirect('view_categories')

    current_question = questions_list[current_index]
    progress = int((len(test_session.get('answers', [])) / total_questions) * 100)
    skipped_indices = test_session.get('skipped_indices', [])

    context = {
        'topic': topic,
        'difficulty': difficulty,
        'question': current_question,
        'question_number': current_index + 1,
        'total_questions': total_questions,
        'time_left': int(time_left),
        'progress': progress,
        'is_last_question': (current_index + 1) == total_questions,
        'assessment_id': test_session['assessment_id'],
        'is_skipped_revisit': current_index in skipped_indices,   # Task 3
        'skipped_count': len(skipped_indices),                     # Task 3
    }

    return render(request, 'test_conduct.html', context)

@csrf_exempt
def save_answer(request):
    """Save answer and generate next question if needed.

    Feature 1 – Background CrewAI: the heavy AI analysis is offloaded to a
    daemon thread so the HTTP response is returned instantly.  The DB writes
    for QuestionPerformance and AdaptiveLearningHistory happen in that thread.
    """
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            selected_answer = data.get('answer')
            time_taken = data.get('time_taken', 30)

            test_session = request.session.get('test_session')
            if not test_session:
                return JsonResponse({'error': 'Session expired'}, status=400)

            import uuid
            try:
                if test_session.get('assessment_id'):
                    assessment_id = uuid.UUID(test_session['assessment_id'])
                    test_result = StudentTestResult.objects.get(assessment_id=assessment_id)
                else:
                    return JsonResponse({'error': 'No assessment found'}, status=400)
            except StudentTestResult.DoesNotExist:
                return JsonResponse({'error': 'Test record not found'}, status=400)

            current_index = test_session['current_index']
            questions = test_session['questions']
            total_questions = test_session['total_questions']

            current_question = questions[current_index]
            is_correct = (selected_answer == current_question['correct_answer'])

            # ── Immediately update score / timing (no AI needed) ────────────
            if is_correct:
                test_result.correct_answers += 1
            test_result.answered_questions = current_index + 1
            time_per_question = (
                test_result.time_per_question
                if isinstance(test_result.time_per_question, list) else []
            )
            time_per_question.append(time_taken)
            test_result.time_per_question = time_per_question
            test_result.save()

            # ── Use simple rule-based fallback difficulty for instant response
            curr_diff = test_session.get('difficulty', 'Medium')
            if is_correct:
                next_diff = {'Easy': 'Medium', 'Medium': 'Hard', 'Hard': 'Hard'}.get(curr_diff, 'Medium')
            else:
                next_diff = {'Hard': 'Medium', 'Medium': 'Easy', 'Easy': 'Easy'}.get(curr_diff, 'Medium')

            # Update session answer log immediately
            placeholder_analysis = {
                'current_difficulty': curr_diff,
                'next_difficulty': next_diff,
                'reasoning': 'AI analysis running in background…',
                'recommendation': ''
            }
            answer_data = {
                'question_number': current_index + 1,
                'question': current_question['question'],
                'selected': selected_answer,
                'correct': current_question['correct_answer'],
                'is_correct': is_correct,
                'explanation': current_question.get('explanation', ''),
                'time_taken': time_taken,
                'crew_analysis': placeholder_analysis
            }
            test_session['answers'].append(answer_data)
            test_session['adaptive_analysis'].append(placeholder_analysis)

            difficulty_progression = test_session.get('difficulty_progression', [])
            difficulty_progression.append({
                'question': current_index + 1,
                'current_difficulty': curr_diff,
                'next_difficulty': next_diff,
                'was_correct': is_correct
            })
            test_session['difficulty_progression'] = difficulty_progression
            test_session['difficulty'] = next_diff
            test_session['current_index'] += 1
            request.session.modified = True

            is_complete = test_session['current_index'] >= total_questions

            # ── Feature 1: fire CrewAI in a background daemon thread ────────
            def _run_crew_analysis(
                q_text, correct_ans, student_ans, t_taken,
                test_result_id, q_index, q_options, q_explanation,
                session_difficulty
            ):
                """Runs in a separate thread – closes its own DB connection when done."""
                try:
                    ai_result = analyze_answer_with_crew(
                        question=q_text,
                        correct_answer=correct_ans,
                        student_answer=student_ans,
                        time_taken=t_taken
                    )
                    result_obj = StudentTestResult.objects.get(pk=test_result_id)

                    QuestionPerformance.objects.create(
                        test_result=result_obj,
                        question_number=q_index + 1,
                        question_text=q_text,
                        options=q_options,
                        selected_answer=student_ans,
                        correct_answer=correct_ans,
                        is_correct=(student_ans == correct_ans),
                        time_taken_seconds=t_taken,
                        predicted_difficulty=ai_result.get('current_difficulty'),
                        next_difficulty=ai_result.get('next_difficulty'),
                        crew_reasoning=ai_result.get('reasoning', ''),
                        crew_recommendation=ai_result.get('recommendation', ''),
                        full_analysis=ai_result.get('full_analysis', ''),
                        explanation=q_explanation
                    )

                    AdaptiveLearningHistory.objects.create(
                        test_result=result_obj,
                        question_number=q_index + 1,
                        current_difficulty=ai_result.get('current_difficulty', session_difficulty),
                        next_difficulty=ai_result.get('next_difficulty', session_difficulty),
                        was_correct=(student_ans == correct_ans),
                        time_taken_seconds=t_taken,
                        reasoning=ai_result.get('reasoning', ''),
                        recommendation=ai_result.get('recommendation', '')
                    )

                    # Update final_difficulty if the AI changed it
                    ai_next = ai_result.get('next_difficulty')
                    if ai_next:
                        result_obj.final_difficulty = ai_next
                        result_obj.save(update_fields=['final_difficulty'])

                except Exception as exc:
                    # Never crash the thread silently – log to stdout
                    import traceback
                    print(f"[BackgroundCrewAI] Error: {exc}")
                    traceback.print_exc()
                finally:
                    # IMPORTANT: close the thread-local DB connection Django gave us
                    db_connection.close()

            t = threading.Thread(
                target=_run_crew_analysis,
                args=(
                    current_question['question'],
                    current_question['correct_answer'],
                    selected_answer,
                    time_taken,
                    test_result.pk,
                    current_index,
                    current_question.get('options', []),
                    current_question.get('explanation', ''),
                    curr_diff,
                ),
                daemon=True
            )
            t.start()
            # ────────────────────────────────────────────────────────────────

            # ── Embed next question in response so frontend never needs to reload ──
            next_q_data = None
            is_skipped_revisit_next = False
            if not is_complete:
                next_index = test_session['current_index']
                questions_list = test_session['questions']
                if len(questions_list) <= next_index:
                    try:
                        next_difficulty = test_session.get('difficulty', 'Medium')
                        nq = call_gemini_api(
                            test_session.get('topic', 'reasoning'),
                            next_difficulty,
                            next_index + 1,
                            total_questions
                        )
                        questions_list.append(nq)
                        test_session['questions'] = questions_list
                        request.session.modified = True
                    except Exception:
                        nq = None
                else:
                    nq = questions_list[next_index]

                if nq:
                    next_q_data = {
                        'question': nq.get('question', ''),
                        'options': nq.get('options', []),
                    }
                is_skipped_revisit_next = next_index in test_session.get('skipped_indices', [])

            return JsonResponse({
                'success': True,
                'is_complete': is_complete,
                'next_question_number': test_session['current_index'] + 1 if not is_complete else None,
                'total': total_questions,
                'progress': int((test_session['current_index'] / total_questions) * 100),
                'question_data': next_q_data,
                'is_skipped_revisit': is_skipped_revisit_next,
                'skipped_count': len(test_session.get('skipped_indices', [])),
            })

        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

    return JsonResponse({'error': 'Invalid request'}, status=400)


@csrf_exempt
def auto_submit_test(request):
    """Feature 3 & 4 – called by navigator.sendBeacon when the user leaves
    the page (tab close / ESC from fullscreen).  Marks the current in-progress
    test as auto_submitted so it is properly recorded.
    """
    import uuid
    if request.method == 'POST':
        test_session = request.session.get('test_session')
        if test_session and not test_session.get('test_submitted', False):
            try:
                assessment_id = uuid.UUID(test_session['assessment_id'])
                test_result = StudentTestResult.objects.get(assessment_id=assessment_id)
                test_result.status = 'auto_submitted'
                test_result.end_time = timezone.now()
                test_result.save()
            except (StudentTestResult.DoesNotExist, ValueError, TypeError):
                pass
            test_session['test_submitted'] = True
            request.session.modified = True
        return JsonResponse({'success': True})
    return JsonResponse({'error': 'Invalid request'}, status=400)


@csrf_exempt
def exit_test(request):
    """Task 4 – called when the user clicks the Exit button.
    Sets status to 'expired' (ended early by user choice) and redirects
    to test history so the record is never stuck as 'in_progress'.
    """
    import uuid
    if request.method == 'POST':
        test_session = request.session.get('test_session')
        if test_session and not test_session.get('test_submitted', False):
            try:
                assessment_id = uuid.UUID(test_session['assessment_id'])
                test_result = StudentTestResult.objects.get(assessment_id=assessment_id)
                test_result.status = 'expired'          # clearly ended by user
                test_result.end_time = timezone.now()
                test_result.save()
            except (StudentTestResult.DoesNotExist, ValueError, TypeError):
                pass
            test_session['test_submitted'] = True
            request.session.modified = True
        return JsonResponse({'success': True, 'redirect': '/test_history/'})
    return JsonResponse({'error': 'Invalid request'}, status=400)


@csrf_exempt
def skip_question(request):
    """Task 3 – Skip the current question without saving an answer.

    Logic:
    • Adds the current question index to skipped_indices.
    • Advances current_index to the next un-skipped question.
    • If we've gone through all N questions linearly, we loop back to
      skipped questions one at a time until they're all answered or time runs out.
    • Returns {success, is_complete, next_question, total, progress} so the
      frontend can reload exactly like save_answer does.
    """
    if request.method == 'POST':
        test_session = request.session.get('test_session')
        if not test_session:
            return JsonResponse({'error': 'Session expired'}, status=400)

        current_index  = test_session['current_index']
        total_questions = test_session['total_questions']
        skipped        = test_session.get('skipped_indices', [])

        # Record this index as skipped (if not already marked)
        if current_index not in skipped:
            skipped.append(current_index)
        test_session['skipped_indices'] = skipped

        # ── Find the next question to show ─────────────────────────────────
        # First try to continue linearly past the current position
        next_index = current_index + 1

        # If we've finished the linear pass, switch to revisiting skipped Qs
        if next_index >= total_questions:
            # Revisit mode: skipped questions that were never answered
            answered_indices = {a['question_number'] - 1 for a in test_session.get('answers', [])}
            remaining_skipped = [i for i in skipped if i not in answered_indices]

            if not remaining_skipped:
                # All questions answered – test complete
                test_session['test_completed'] = True
                request.session.modified = True
                return JsonResponse({'success': True, 'is_complete': True})

            next_index = remaining_skipped[0]   # revisit first unanswered skipped Q

        test_session['current_index'] = next_index
        request.session.modified = True

        answered_count = len(test_session.get('answers', []))
        progress = int((answered_count / total_questions) * 100)

        # ── Embed next question so frontend can update DOM without reload ──
        questions_list = test_session.get('questions', [])
        nq = None
        if len(questions_list) > next_index:
            nq = questions_list[next_index]
        else:
            try:
                next_difficulty = test_session.get('difficulty', 'Medium')
                nq = call_gemini_api(
                    test_session.get('topic', 'reasoning'),
                    next_difficulty,
                    next_index + 1,
                    total_questions
                )
                questions_list.append(nq)
                test_session['questions'] = questions_list
                request.session.modified = True
            except Exception:
                nq = None

        next_q_data = {
            'question': nq.get('question', '') if nq else '',
            'options': nq.get('options', []) if nq else [],
        } if nq else None

        is_skipped_revisit_next = next_index in skipped

        return JsonResponse({
            'success': True,
            'is_complete': False,
            'next_question_number': next_index + 1,
            'total': total_questions,
            'progress': progress,
            'skipped_count': len(skipped),
            'question_data': next_q_data,
            'is_skipped_revisit': is_skipped_revisit_next,
        })

    return JsonResponse({'error': 'Invalid request'}, status=400)

def test_ready_to_submit(request, topic, difficulty):
    """Show submit button page after all questions are answered"""
    test_session = request.session.get('test_session')

    if not test_session:
        return redirect('view_categories')

    # Allow access if test_completed flag is set OR all answers are in
    total_questions = test_session.get('total_questions', 20)
    answered_count  = len(test_session.get('answers', []))
    is_done = test_session.get('test_completed', False) or answered_count >= total_questions

    if not is_done:
        return redirect('test_conduct', topic=topic, difficulty=difficulty)

    # Calculate time taken
    try:
        start_time_str = test_session['start_time']
        start_dt = datetime.fromisoformat(start_time_str)
        if start_dt.tzinfo is None:
            start_dt = timezone.make_aware(start_dt, timezone.get_current_timezone())
        elapsed = (timezone.now() - start_dt).total_seconds()
    except Exception:
        elapsed = 0
    time_taken = min(20 * 60, elapsed)
    
    context = {
        'topic': topic,
        'difficulty': difficulty,
        'total_questions': test_session['total_questions'],
        'time_taken': f"{int(time_taken // 60)} minutes {int(time_taken % 60)} seconds",
        'time_left': max(0, (20 * 60) - time_taken),
        'assessment_id': test_session['assessment_id']
    }
    
    return render(request, 'test_ready_to_submit.html', context)

@csrf_exempt
def submit_test(request):
    """Final test submission"""
    if request.method == 'POST':
        test_session = request.session.get('test_session')

        if not test_session:
            return JsonResponse({'error': 'Session expired'}, status=400)

        # Calculate actual time taken from start_time (more reliable than stored time_left)
        try:
            start_time_str = test_session['start_time']
            start_dt = datetime.fromisoformat(start_time_str)
            if start_dt.tzinfo is None:
                start_dt = timezone.make_aware(start_dt, timezone.get_current_timezone())
            elapsed_secs = int((timezone.now() - start_dt).total_seconds())
            elapsed_secs = min(elapsed_secs, 20 * 60)  # cap at 20 min
        except Exception:
            elapsed_secs = int(20 * 60 - test_session.get('time_left', 0))

        try:
            import uuid
            test_result = StudentTestResult.objects.get(
                assessment_id=uuid.UUID(test_session['assessment_id'])
            )
            if not test_result.user and request.user.is_authenticated:
                test_result.user = request.user
            test_result.status = 'completed'
            test_result.end_time = timezone.now()
            test_result.time_taken_seconds = elapsed_secs
            test_result.save()
        except (StudentTestResult.DoesNotExist, Exception):
            pass

        test_session['test_submitted'] = True
        request.session.modified = True
        return JsonResponse({'success': True})

    return JsonResponse({'error': 'Invalid request'}, status=400)

def test_complete(request):
    """Show test results"""
    test_session = request.session.get('test_session')

    if not test_session or not test_session.get('test_submitted', False):
        return redirect('view_categories')

    try:
        test_result = StudentTestResult.objects.get(assessment_id=test_session['assessment_id'])
        question_performances = test_result.question_performances.all().order_by('question_number')
        adaptive_history = test_result.adaptive_history.all().order_by('question_number')
    except StudentTestResult.DoesNotExist:
        test_result = None
        question_performances = []
        adaptive_history = []

    answers = test_session.get('answers', [])
    total = len(answers)
    correct = sum(1 for ans in answers if ans['is_correct'])
    score_percentage = (correct / total * 100) if total > 0 else 0

    try:
        start_time_str = test_session['start_time']
        start_dt = datetime.fromisoformat(start_time_str)
        if start_dt.tzinfo is None:
            start_dt = timezone.make_aware(start_dt, timezone.get_current_timezone())
        elapsed = (timezone.now() - start_dt).total_seconds()
    except Exception:
        elapsed = 0
    time_taken = min(20 * 60, elapsed)
    time_taken_str = f"{int(time_taken // 60)} minutes {int(time_taken % 60)} seconds"
    
    context = {
        'topic': test_session['topic'],
        'difficulty': test_session['difficulty'],
        'total_questions': total,
        'correct_answers': correct,
        'score_percentage': round(score_percentage, 2),
        'answers': answers,
        'time_taken': time_taken_str,
        'adaptive_analysis': test_session.get('adaptive_analysis', []),
        'difficulty_progression': test_session.get('difficulty_progression', []),
        'test_result': test_result,
        'question_performances': question_performances,
        'adaptive_history': adaptive_history,
        'assessment_id': test_session['assessment_id']
    }

    # Clear session after building context
    del request.session['test_session']

    return render(request, 'test_complete.html', context)


def view_test_history(request):
    """View past test results for the current user or session"""

    # Bug fix: AnonymousUser is always truthy; must check is_authenticated
    if request.user.is_authenticated:
        test_results = StudentTestResult.objects.filter(
            user=request.user
        ).exclude(
            status='in_progress'
        ).order_by('-created_at')

        # Link any session-based results that haven't been tied to the user
        session_key = request.session.session_key
        if session_key:
            unlinked = StudentTestResult.objects.filter(
                session_key=session_key,
                user__isnull=True
            ).exclude(status='in_progress')
            if unlinked.exists():
                unlinked.update(user=request.user)
                test_results = StudentTestResult.objects.filter(
                    user=request.user
                ).exclude(status='in_progress').order_by('-created_at')
    else:
        # Non-authenticated: results by session key only
        session_key = request.session.session_key
        if session_key:
            test_results = StudentTestResult.objects.filter(
                session_key=session_key
            ).exclude(status='in_progress').order_by('-created_at')
        else:
            test_results = StudentTestResult.objects.none()


    # Add formatted data for each test result
    for test in test_results:
        # Format time taken
        seconds = int(test.time_taken_seconds)
        if seconds < 60:
            test.formatted_time = f"{seconds} seconds"
        elif seconds < 3600:
            minutes = seconds // 60
            remaining_seconds = seconds % 60
            if remaining_seconds > 0:
                test.formatted_time = f"{minutes} minutes {remaining_seconds} seconds"
            else:
                test.formatted_time = f"{minutes} minutes"
        else:
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            remaining_seconds = seconds % 60
            if minutes > 0 and remaining_seconds > 0:
                test.formatted_time = f"{hours} hours {minutes} minutes {remaining_seconds} seconds"
            elif minutes > 0:
                test.formatted_time = f"{hours} hours {minutes} minutes"
            elif remaining_seconds > 0:
                test.formatted_time = f"{hours} hours {remaining_seconds} seconds"
            else:
                test.formatted_time = f"{hours} hours"
        
        # Add wrong answers count
        test.wrong_answers = test.total_questions - test.correct_answers
        
        # Ensure score percentage is properly formatted
        if test.score_percentage:
            test.score_percentage = round(test.score_percentage, 1)
    
    # Calculate statistics
    total_tests = test_results.count()
    average_score = 0
    total_questions_answered = 0
    total_correct_answers = 0
    
    if total_tests > 0:
        total_score = sum(test.score_percentage for test in test_results if test.score_percentage)
        average_score = round(total_score / total_tests, 1)
        total_questions_answered = sum(test.total_questions for test in test_results)
        total_correct_answers = sum(test.correct_answers for test in test_results)
    
    context = {
        'test_results': test_results,
        'is_authenticated': request.user.is_authenticated,
        'user_name': request.user.get_full_name() or request.user.username if request.user.is_authenticated else None,
        'total_tests': total_tests,
        'average_score': average_score,
        'total_questions_answered': total_questions_answered,
        'total_correct_answers': total_correct_answers,
        'has_results': test_results.exists()
    }
    
    return render(request, 'test_history.html', context)


def view_test_detail(request, assessment_id):
    """View detailed results of a specific test"""
    try:
        # Get the test result
        test_result = StudentTestResult.objects.get(assessment_id=assessment_id)
        
        # Verify access (session or user)
        session_key = request.session.session_key
        if not session_key:
            request.session.create()
            session_key = request.session.session_key
            
        if (test_result.session_key != session_key and 
            (not request.user.is_authenticated or test_result.user != request.user)):
            messages.error(request, "You don't have permission to view this test result")
            return redirect('test_history')
        
        # Get all question performances for this test
        question_performances = test_result.question_performances.all().order_by('question_number')
        
        # Get adaptive learning history
        adaptive_history = test_result.adaptive_history.all().order_by('question_number')
        
        # Calculate additional statistics
        total_time = test_result.time_taken_seconds
        avg_time_per_question = test_result.calculate_average_time_per_question()
        
        # Calculate time distribution
        time_per_question_list = test_result.time_per_question if isinstance(test_result.time_per_question, list) else []
        
        # Get difficulty progression
        difficulty_progression = []
        for history in adaptive_history:
            difficulty_progression.append({
                'question': history.question_number,
                'from': history.current_difficulty,
                'to': history.next_difficulty,
                'correct': history.was_correct
            })
        
        # Analyze performance by difficulty level
        difficulty_breakdown = {}
        for perf in question_performances:
            diff = perf.predicted_difficulty or 'Unknown'
            if diff not in difficulty_breakdown:
                difficulty_breakdown[diff] = {'total': 0, 'correct': 0}
            difficulty_breakdown[diff]['total'] += 1
            if perf.is_correct:
                difficulty_breakdown[diff]['correct'] += 1
        
        # Calculate percentage for each difficulty
        for diff in difficulty_breakdown:
            if difficulty_breakdown[diff]['total'] > 0:
                difficulty_breakdown[diff]['percentage'] = (
                    difficulty_breakdown[diff]['correct'] / difficulty_breakdown[diff]['total'] * 100
                )
        
        # Get wrong answers for review
        wrong_answers = [
            {
                'question_number': perf.question_number,
                'question': perf.question_text,
                'selected': perf.selected_answer,
                'correct': perf.correct_answer,
                'explanation': perf.explanation,
                'time_taken': perf.time_taken_seconds
            }
            for perf in question_performances if not perf.is_correct
        ]
        
        context = {
            'test_result': test_result,
            'question_performances': question_performances,
            'adaptive_history': adaptive_history,
            'total_time': total_time,
            'avg_time_per_question': round(avg_time_per_question, 2),
            'time_per_question_list': time_per_question_list,
            'difficulty_progression': difficulty_progression,
            'difficulty_breakdown': difficulty_breakdown,
            'wrong_answers': wrong_answers,
            'total_questions': test_result.total_questions,
            'correct_answers': test_result.correct_answers,
            'score_percentage': test_result.score_percentage,
        }
        
        return render(request, 'test_detail.html', context)
        
    except StudentTestResult.DoesNotExist:
        messages.error(request, "Test result not found")
        return redirect('test_history')

from django.core.paginator import Paginator



def leaderboard(request):
    """Show competency leaderboard with all users' performance"""
    
    # Get all users with their test statistics (include all test statuses for accurate rankings)
    users_data = User.objects.filter(
        test_results__isnull=False
    ).annotate(
        total_tests=Count('test_results'),
        avg_score=Avg('test_results__score_percentage'),
        total_questions=Sum('test_results__total_questions'),
        total_correct=Sum('test_results__correct_answers'),
        best_score=Max('test_results__score_percentage'),
        latest_test=Max('test_results__created_at')
    ).filter(
        total_tests__gt=0
    ).order_by('-avg_score')
    
    # Get the rank of the current user
    current_user_rank = None
    for idx, user_data in enumerate(users_data, 1):
        if user_data.id == request.user.id:
            current_user_rank = idx
            break
    
    # Get current user's data
    current_user_data = users_data.filter(id=request.user.id).first()
    
    # Calculate user statistics
    if current_user_data:
        avg_score_value = float(current_user_data.avg_score) if current_user_data.avg_score else 0
        best_score_value = float(current_user_data.best_score) if current_user_data.best_score else 0
        
        user_stats = {
            'rank': current_user_rank,
            'total_tests': current_user_data.total_tests,
            'avg_score': int(round(avg_score_value, 0)),
            'best_score': int(round(best_score_value, 0)),
            'total_questions': current_user_data.total_questions or 0,
            'total_correct': current_user_data.total_correct or 0,
        }
    else:
        user_stats = {
            'rank': 'N/A',
            'total_tests': 0,
            'avg_score': 0,
            'best_score': 0,
            'total_questions': 0,
            'total_correct': 0,
        }
    
    # Add competency level and formatted data to each user
    user_list = []
    for idx, user in enumerate(users_data, 1):
        if user.avg_score:
            avg_score_int = int(round(float(user.avg_score), 0))
            if avg_score_int >= 85:
                competency_level = 'Expert'
                competency_icon = 'fa-crown'
                competency_color = 'expert'
            elif avg_score_int >= 70:
                competency_level = 'Advanced'
                competency_icon = 'fa-star'
                competency_color = 'advanced'
            elif avg_score_int >= 50:
                competency_level = 'Intermediate'
                competency_icon = 'fa-chart-line'
                competency_color = 'intermediate'
            else:
                competency_level = 'Beginner'
                competency_icon = 'fa-seedling'
                competency_color = 'beginner'
        else:
            competency_level = 'No Tests'
            competency_icon = 'fa-question'
            competency_color = 'no-tests'
        
        user_list.append({
            'id': user.id,
            'rank': idx,
            'username': user.username,
            'full_name': user.get_full_name(),
            'initials': (user.first_name[0] if user.first_name else user.username[0]).upper(),
            'total_tests': user.total_tests,
            'avg_score': avg_score_int if user.avg_score else 0,
            'best_score': int(round(float(user.best_score), 0)) if user.best_score else 0,
            'total_questions': user.total_questions or 0,
            'total_correct': user.total_correct or 0,
            'competency_level': competency_level,
            'competency_icon': competency_icon,
            'competency_color': competency_color,
        })
    
    # Get nearby users (3 above, 3 below current user)
    nearby_users = []
    if current_user_rank:
        start_idx = max(0, current_user_rank - 4)
        end_idx = min(len(user_list), current_user_rank + 3)
        nearby_users = user_list[start_idx:end_idx]
        # Add start_rank for proper numbering
        for idx, user in enumerate(nearby_users):
            user['nearby_rank'] = start_idx + idx + 1
    
    # Get top 10 performers
    top_performers = user_list[:10]
    
    # Pagination
    paginator = Paginator(user_list, 20)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    # Calculate overall statistics
    overall_avg_score = users_data.aggregate(Avg('avg_score'))['avg_score__avg']
    total_tests_sum = users_data.aggregate(Sum('total_tests'))['total_tests__sum']
    total_questions_sum = users_data.aggregate(Sum('total_questions'))['total_questions__sum']
    total_correct_sum = users_data.aggregate(Sum('total_correct'))['total_correct__sum']
    
    overall_stats = {
        'total_users': users_data.count(),
        'average_score': int(round(overall_avg_score or 0, 0)),
        'total_tests': int(total_tests_sum or 0),
        'total_questions': int(total_questions_sum or 0),
        'total_correct': int(total_correct_sum or 0),
        'expert_count': sum(1 for u in user_list if u['avg_score'] >= 85),
        'advanced_count': sum(1 for u in user_list if 70 <= u['avg_score'] < 85),
        'intermediate_count': sum(1 for u in user_list if 50 <= u['avg_score'] < 70),
        'beginner_count': sum(1 for u in user_list if u['avg_score'] < 50),
    }
    
    context = {
        'users_data': page_obj,
        'current_user': request.user,
        'current_user_rank': current_user_rank,
        'user_stats': user_stats,
        'top_performers': top_performers,
        'nearby_users': nearby_users,
        'overall_stats': overall_stats,
        'page_obj': page_obj,
    }
    
    return render(request, 'leaderboard.html', context)
