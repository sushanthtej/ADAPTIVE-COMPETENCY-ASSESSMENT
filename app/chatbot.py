import google.generativeai as genai
import json
import time
import os
API_KEY = os.getenv("GCP_API_KEY")

# Configure once at module load
genai.configure(api_key="")


def call_gemini_api(topic, difficulty, question_number=1, total_questions=20):
    """Generate one MCQ question at a time using Gemini API.
    
    Retries up to 3 times on transient errors (503, 429, etc).
    """
    prompt = f"""
                Generate 1 Multiple Choice Question (Question #{question_number} of {total_questions}) 
                based on {topic} topic with {difficulty} difficulty level.
                
                Strictly follow this JSON format:
                {{
                  "id": {question_number},
                  "question": "The text of the question",
                  "options": ["Option A", "Option B", "Option C", "Option D"],
                  "correct_answer": "The exact string from the options list",
                  "explanation": "Brief reasoning"
                }}
                
                Conditions:
                1. Return ONLY valid JSON object (not an array).
                2. Do not include markdown code blocks (no ```json).
                3. Ensure the 'correct_answer' exactly matches one of the strings in the 'options' array.
                4. Question should be appropriate for {difficulty} difficulty level.
                5. Make the question challenging but fair for {difficulty} level.
                6. Ensure variety across different questions.
                7. For {topic} topic, create relevant questions.
            """

    max_retries = 3
    last_error = None

    for attempt in range(max_retries):
        try:
            model = genai.GenerativeModel('gemini-2.5-flash')
            response = model.generate_content(prompt)

            # Parse the response
            response_text = response.text.strip()

            # Remove markdown code blocks if present
            if response_text.startswith('```json'):
                response_text = response_text[7:]
            if response_text.startswith('```'):
                response_text = response_text[3:]
            if response_text.endswith('```'):
                response_text = response_text[:-3]

            response_text = response_text.strip()
            question_data = json.loads(response_text)
            return question_data

        except json.JSONDecodeError as e:
            print(f'========== JSON parse error (attempt {attempt+1}): {e}')
            last_error = e
            # Don't retry JSON errors — the API responded, just bad format
            return {
                "id": question_number,
                "question": f"What is the basic concept of {topic}?",
                "options": ["Option A", "Option B", "Option C", "Option D"],
                "correct_answer": "Option A",
                "explanation": f"This is a basic question about {topic}."
            }

        except Exception as e:
            error_str = str(e)
            print(f'========== Gemini API error (attempt {attempt+1}/{max_retries}): {error_str}')
            last_error = e

            # Retry on transient errors (503, 429, 500)
            is_transient = any(code in error_str for code in ['503', '429', '500', 'UNAVAILABLE', 'overloaded', 'high demand'])

            if is_transient and attempt < max_retries - 1:
                wait_time = (attempt + 1) * 2  # 2s, 4s
                print(f'           Retrying in {wait_time}s...')
                time.sleep(wait_time)
                continue
            else:
                # Non-transient error or exhausted retries
                break

    # All retries exhausted — return fallback
    print(f'========== All {max_retries} attempts failed. Last error: {last_error}')
    return {
        "id": question_number,
        "question": f"Sample question about {topic} (Difficulty: {difficulty})",
        "options": ["Sample Answer 1", "Sample Answer 2", "Sample Answer 3", "Sample Answer 4"],
        "correct_answer": "Sample Answer 1",
        "explanation": "This is a sample question due to API error."
    }