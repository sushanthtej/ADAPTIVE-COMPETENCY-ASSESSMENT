from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
import uuid

class StudentTestResult(models.Model):
    """Model to store student test results and performance"""
    
    # Difficulty level choices
    DIFFICULTY_CHOICES = [
        ('Easy', 'Easy'),
        ('Medium', 'Medium'),
        ('Hard', 'Hard'),
    ]
    
    # Test status choices
    STATUS_CHOICES = [
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('auto_submitted', 'Auto Submitted'),
        ('expired', 'Expired'),
    ]
    
    # Unique identifier for each assessment
    assessment_id = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True,
        verbose_name="Assessment ID"
    )
    
    # User information (if you have authentication)
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='test_results'
    )
    
    # Session information for non-authenticated users
    session_key = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name="Session Key"
    )
    
    # Test details
    topic = models.CharField(max_length=200, verbose_name="Test Topic")
    difficulty = models.CharField(
        max_length=10,
        choices=DIFFICULTY_CHOICES,
        verbose_name="Initial Difficulty"
    )
    final_difficulty = models.CharField(
        max_length=10,
        choices=DIFFICULTY_CHOICES,
        null=True,
        blank=True,
        verbose_name="Final Difficulty"
    )
    
    # Test performance
    total_questions = models.IntegerField(default=20, verbose_name="Total Questions")
    answered_questions = models.IntegerField(default=0, verbose_name="Questions Answered")
    correct_answers = models.IntegerField(default=0, verbose_name="Correct Answers")
    wrong_answers = models.IntegerField(default=0, verbose_name="Wrong Answers")
    score_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        verbose_name="Score Percentage"
    )
    
    # Time tracking
    start_time = models.DateTimeField(default=timezone.now, verbose_name="Test Start Time")
    end_time = models.DateTimeField(null=True, blank=True, verbose_name="Test End Time")
    time_taken_seconds = models.IntegerField(default=0, verbose_name="Time Taken (Seconds)")
    time_per_question = models.JSONField(
        default=list,
        blank=True,
        verbose_name="Time Per Question (Seconds)"
    )
    
    # Status
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='in_progress',
        verbose_name="Test Status"
    )
    
    # Detailed results (store all answers and analysis)
    answers_data = models.JSONField(
        default=list,
        blank=True,
        verbose_name="Answers Data"
    )
    
    adaptive_analysis = models.JSONField(
        default=list,
        blank=True,
        verbose_name="Adaptive Analysis Results"
    )
    
    difficulty_progression = models.JSONField(
        default=list,
        blank=True,
        verbose_name="Difficulty Progression"
    )
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created At")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated At")
    
    class Meta:
        db_table = 'student_test_results'
        verbose_name = 'Student Test Result'
        verbose_name_plural = 'Student Test Results'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['assessment_id']),
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['session_key', '-created_at']),
            models.Index(fields=['topic', 'difficulty']),
            models.Index(fields=['status']),
        ]
    
    def __str__(self):
        user_info = f"User: {self.user.username}" if self.user else f"Session: {self.session_key[:8]}"
        return f"{self.assessment_id} - {self.topic} - {self.score_percentage}% - {user_info}"
    
    def save(self, *args, **kwargs):
        # Calculate wrong answers automatically
        self.wrong_answers = self.total_questions - self.correct_answers
        
        # Calculate score percentage
        if self.total_questions > 0:
            self.score_percentage = (self.correct_answers / self.total_questions) * 100
        
        super().save(*args, **kwargs)
    
    def calculate_average_time_per_question(self):
        """Calculate average time per question in seconds"""
        if self.time_per_question and len(self.time_per_question) > 0:
            return sum(self.time_per_question) / len(self.time_per_question)
        return 0
    
    def get_performance_summary(self):
        """Get performance summary as dictionary"""
        return {
            'total_questions': self.total_questions,
            'answered': self.answered_questions,
            'correct': self.correct_answers,
            'wrong': self.wrong_answers,
            'score': float(self.score_percentage),
            'time_taken': self.time_taken_seconds,
            'avg_time_per_question': self.calculate_average_time_per_question()
        }


class QuestionPerformance(models.Model):
    """Model to store performance for each individual question"""
    
    test_result = models.ForeignKey(
        StudentTestResult,
        on_delete=models.CASCADE,
        related_name='question_performances'
    )
    
    # Question details
    question_number = models.IntegerField(verbose_name="Question Number")
    question_text = models.TextField(verbose_name="Question Text")
    options = models.JSONField(default=list, verbose_name="Question Options")
    
    # Answer details
    selected_answer = models.CharField(max_length=500, verbose_name="Selected Answer")
    correct_answer = models.CharField(max_length=500, verbose_name="Correct Answer")
    is_correct = models.BooleanField(default=False, verbose_name="Is Correct")
    
    # Timing
    time_taken_seconds = models.IntegerField(default=0, verbose_name="Time Taken (Seconds)")
    
    # Difficulty analysis
    predicted_difficulty = models.CharField(
        max_length=10,
        choices=StudentTestResult.DIFFICULTY_CHOICES,
        null=True,
        blank=True,
        verbose_name="Predicted Difficulty"
    )
    next_difficulty = models.CharField(
        max_length=10,
        choices=StudentTestResult.DIFFICULTY_CHOICES,
        null=True,
        blank=True,
        verbose_name="Next Difficulty"
    )
    
    # CrewAI analysis
    crew_reasoning = models.TextField(blank=True, verbose_name="CrewAI Reasoning")
    crew_recommendation = models.TextField(blank=True, verbose_name="CrewAI Recommendation")
    full_analysis = models.TextField(blank=True, verbose_name="Full Analysis")
    
    # Explanation
    explanation = models.TextField(blank=True, verbose_name="Question Explanation")
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created At")
    
    class Meta:
        db_table = 'question_performances'
        verbose_name = 'Question Performance'
        verbose_name_plural = 'Question Performances'
        ordering = ['test_result', 'question_number']
        unique_together = ['test_result', 'question_number']
    
    def __str__(self):
        return f"Q{self.question_number} - {'✓' if self.is_correct else '✗'}"


class AdaptiveLearningHistory(models.Model):
    """Model to track adaptive learning progression"""
    
    test_result = models.ForeignKey(
        StudentTestResult,
        on_delete=models.CASCADE,
        related_name='adaptive_history'
    )
    
    # Adaptive decision details
    question_number = models.IntegerField(verbose_name="Question Number")
    current_difficulty = models.CharField(
        max_length=10,
        choices=StudentTestResult.DIFFICULTY_CHOICES,
        verbose_name="Current Difficulty"
    )
    next_difficulty = models.CharField(
        max_length=10,
        choices=StudentTestResult.DIFFICULTY_CHOICES,
        verbose_name="Next Difficulty"
    )
    
    # Performance metrics for this decision
    was_correct = models.BooleanField(default=False, verbose_name="Answer Was Correct")
    time_taken_seconds = models.IntegerField(default=0, verbose_name="Time Taken (Seconds)")
    
    # Reasoning
    reasoning = models.TextField(blank=True, verbose_name="Adaptive Reasoning")
    recommendation = models.TextField(blank=True, verbose_name="Recommendation")
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created At")
    
    class Meta:
        db_table = 'adaptive_learning_history'
        verbose_name = 'Adaptive Learning History'
        verbose_name_plural = 'Adaptive Learning Histories'
        ordering = ['test_result', 'question_number']
    
    def __str__(self):
        return f"Q{self.question_number}: {self.current_difficulty} → {self.next_difficulty}"