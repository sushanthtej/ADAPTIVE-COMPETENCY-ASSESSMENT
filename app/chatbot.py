import google.generativeai as genai
import json

def call_gemini_api(topic, difficulty, question_number=1, total_questions=20):
    """Generate one MCQ question at a time using Gemini API"""
    try:
        genai.configure(api_key="AIzaSyBZ4DWJ5aCWds2Yj_H3MAhxuHQWfk-m5SI")
        model = genai.GenerativeModel('gemini-3-flash-preview')

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
        
        response = model.generate_content(prompt)
        
        # Parse the response
        try:
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
            
        except json.JSONDecodeError:
            # Return a fallback question
            return {
                "id": question_number,
                "question": f"What is the basic concept of {topic}?",
                "options": ["Option A", "Option B", "Option C", "Option D"],
                "correct_answer": "Option A",
                "explanation": f"This is a basic question about {topic}."
            }
            
    except Exception as e:
        print('==========', e)
        # Return a fallback question
        return {
            "id": question_number,
            "question": f"Sample question about {topic} (Difficulty: {difficulty})",
            "options": ["Sample Answer 1", "Sample Answer 2", "Sample Answer 3", "Sample Answer 4"],
            "correct_answer": "Sample Answer 1",
            "explanation": "This is a sample question due to API error."
        }

# print(call_gemini_api("Verbal Ability", "Hard"))