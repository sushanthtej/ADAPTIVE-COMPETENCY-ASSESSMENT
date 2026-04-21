# =============================================
# - MCQ Difficulty Prediction System
# Using Google Gemini + CrewAI
# =============================================

import os
from crewai import Agent, Task, Crew, Process
from crewai.llm import LLM

# ====================== GEMINI LLM SETUP ======================
def get_default_llm():
    api_key = ""
    if not api_key:
        raise ValueError("❌ GEMINI_API_KEY is not set!\nRun this command first:\nset GEMINI_API_KEY=")
    
    print("✅ Using Gemini model: gemini/gemini-2.5-flash")
    return LLM(
        model="gemini/gemini-2.5-flash",
        temperature=0.7,
        api_key=api_key,
    )

# ====================== 1. MCQ EVALUATOR AGENT ======================
def create_mcq_evaluator_agent(llm=None):
    if llm is None:
        llm = get_default_llm()
    return Agent(
        role="MCQ Evaluator Agent",
        goal="Accurately determine if the student's selected answer is correct or wrong.",
        backstory="You are a strict and fair MCQ examiner. You only compare the student's answer with the correct option.",
        verbose=True,
        allow_delegation=False,
        llm=llm
    )

# ====================== 2. DIFFICULTY PREDICTOR AGENT ======================
def create_difficulty_predictor_agent(llm=None):
    if llm is None:
        llm = get_default_llm()
    return Agent(
        role="Difficulty Predictor Agent",
        goal="Predict the true difficulty of the question (Easy / Medium / Hard) based on correctness and time taken.",
        backstory=(
            "You are an expert in adaptive testing and psychometrics. "
            "Fast + Correct = Easy question. Slow + Correct = Medium. Wrong = Hard."
        ),
        verbose=True,
        allow_delegation=False,
        llm=llm
    )

# ====================== 3. ADAPTIVE MCQ OVERSEER AGENT ======================
def create_adaptive_mcq_agent(llm=None):
    if llm is None:
        llm = get_default_llm()
    return Agent(
        role="Adaptive MCQ Overseer Agent",
        goal="Analyze results and decide next question difficulty based on current performance. Output both current question difficulty and recommended next difficulty.",
        backstory=(
            "You are an intelligent adaptive learning system. You adjust question difficulty dynamically "
            "to keep the student in their optimal learning zone. You analyze the current question's difficulty "
            "and recommend the appropriate next difficulty level based on these rules:\n\n"
            
            "IF ANSWER IS CORRECT:\n"
            "- If current question was Easy: Next should be Medium\n"
            "- If current question was Medium: Next should be Hard\n"
            "- If current question was Hard: Next should be Hard or Medium (maintain mastery)\n\n"
            
            "IF ANSWER IS INCORRECT:\n"
            "- If current question was Hard: Next should be Medium\n"
            "- If current question was Medium: Next should be Easy\n"
            "- If current question was Easy: Next should be Easy (stay at same level to build confidence)\n\n"
            
            "Always output both CURRENT DIFFICULTY and NEXT DIFFICULTY."
        ),
        verbose=True,
        allow_delegation=True,
        llm=llm
    )

def analyze_answer_with_crew(question, correct_answer, student_answer, time_taken):
    """
    Analyze the student's answer using CrewAI agents to determine difficulty and next steps
    
    Returns:
        dict: Contains current_difficulty, next_difficulty, reasoning, recommendation
    """
    try:
        llm = get_default_llm()
    except ValueError as e:
        return {
            'current_difficulty': 'Medium',
            'next_difficulty': 'Medium',
            'reasoning': 'Using default difficulty due to API key issue',
            'recommendation': 'Continue with current difficulty level'
        }
    
    # Create Agents
    evaluator = create_mcq_evaluator_agent(llm)
    predictor = create_difficulty_predictor_agent(llm)
    adaptive = create_adaptive_mcq_agent(llm)
    
    # Prepare input for CrewAI
    input_data = f"""
    Question: {question}
    Correct Answer: {correct_answer}
    Student Selected Answer: {student_answer}
    Time Taken by Student: {time_taken} seconds
    """
    
    # Create Tasks
    task1 = Task(
        description=f"Evaluate if the student's answer is correct or wrong:\n{input_data}",
        expected_output="Correct or Wrong + one line explanation.",
        agent=evaluator
    )
    
    task2 = Task(
        description="Based on correctness and time taken, predict the difficulty level of this question (Easy / Medium / Hard).",
        expected_output="Current Question Difficulty: Easy/Medium/Hard + reasoning for this classification.",
        agent=predictor
    )
    
    task3 = Task(
        description=(
            "Review the evaluation and difficulty prediction. "
            "Based on the student's performance, determine:\n"
            "1. CURRENT QUESTION DIFFICULTY (from task2)\n"
            "2. NEXT QUESTION DIFFICULTY (what difficulty should the next question be?)\n\n"
            
            "ADAPTIVE RULES:\n"
            "FOR CORRECT ANSWERS:\n"
            "• Easy → Next: Medium (progressive challenge)\n"
            "• Medium → Next: Hard (advance to next level)\n"
            "• Hard → Next: Easy or Medium (maintain mastery or consolidate)\n\n"
            
            "FOR INCORRECT ANSWERS:\n"
            "• Hard → Next: Medium (step down one level)\n"
            "• Medium → Next: Easy (step down one level)\n"
            "• Easy → Next: Easy (stay at same level for reinforcement)\n\n"
            
            "Format your output EXACTLY as:\n"
            "Questions Difficulty: [Easy/Medium/Hard]\n"
            "Next Question Difficulty: [Easy/Medium/Hard]\n"
            "Reasoning: [Your reasoning here]\n"
            "Recommendation: [Additional recommendations]"
        ),
        expected_output="Questions Difficulty: [Level] | Next Question Difficulty: [Level] | Reasoning: [Explanation] | Recommendation: [Actions]",
        agent=adaptive,
        context=[task1, task2]
    )
    
    # Create and run Crew
    crew = Crew(
        agents=[evaluator, predictor, adaptive],
        tasks=[task1, task2, task3],
        process=Process.sequential,
        verbose=False,
        memory=False,
        max_rpm=10
    )
    
    # Run the crew
    result = crew.kickoff()
    
    # Parse the result
    result_text = str(result)
    
    # Extract values from result
    current_difficulty = "Medium"
    next_difficulty = "Medium"
    reasoning = ""
    recommendation = ""
    
    # Parse the result
    lines = result_text.split('\n')
    for line in lines:
        if 'Questions Difficulty:' in line:
            current_difficulty = line.split('Questions Difficulty:')[1].strip().split()[0]
        elif 'Next Question Difficulty:' in line:
            next_difficulty = line.split('Next Question Difficulty:')[1].strip().split()[0]
        elif 'Reasoning:' in line:
            reasoning = line.split('Reasoning:')[1].strip()
        elif 'Recommendation:' in line:
            recommendation = line.split('Recommendation:')[1].strip()
    
    return {
        'current_difficulty': current_difficulty,
        'next_difficulty': next_difficulty,
        'reasoning': reasoning,
        'recommendation': recommendation,
        'full_analysis': result_text
    }