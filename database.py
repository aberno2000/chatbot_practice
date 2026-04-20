import aiosqlite
from datetime import datetime
from config import DB_NAME

async def create_tables():
    """Create all necessary database tables"""
    async with aiosqlite.connect(DB_NAME) as db:
        # Table for quiz state (current question index)
        await db.execute(
            """CREATE TABLE IF NOT EXISTS quiz_state 
               (user_id INTEGER PRIMARY KEY, question_index INTEGER)"""
        )
        
        # Table for quiz attempts
        await db.execute(
            """CREATE TABLE IF NOT EXISTS quiz_attempts 
               (attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                attempt_date TIMESTAMP,
                total_questions INTEGER,
                correct_answers INTEGER,
                score_percentage REAL)"""
        )
        
        # Table for individual answers
        await db.execute(
            """CREATE TABLE IF NOT EXISTS user_answers 
               (id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                attempt_id INTEGER,
                question TEXT,
                selected_answer TEXT,
                correct_answer TEXT,
                is_correct BOOLEAN)"""
        )
        
        # Table for user statistics
        await db.execute(
            """CREATE TABLE IF NOT EXISTS user_stats 
               (user_id INTEGER PRIMARY KEY,
                total_quizzes INTEGER DEFAULT 0,
                total_questions_answered INTEGER DEFAULT 0,
                total_correct_answers INTEGER DEFAULT 0,
                best_score REAL DEFAULT 0,
                last_quiz_date TIMESTAMP)"""
        )
        
        await db.commit()

async def get_quiz_index(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT question_index FROM quiz_state WHERE user_id = (?)", (user_id,)
        ) as cursor:
            results = await cursor.fetchone()
            return results[0] if results is not None else 0

async def update_quiz_index(user_id, index):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT OR REPLACE INTO quiz_state (user_id, question_index) VALUES (?, ?)",
            (user_id, index),
        )
        await db.commit()

async def save_quiz_results(user_id, session_data):
    """Save quiz results to database"""
    total_questions = len(session_data["answers"])
    correct_answers = sum(1 for a in session_data["answers"] if a["correct"])
    score_percentage = (correct_answers / total_questions * 100) if total_questions > 0 else 0
    
    async with aiosqlite.connect(DB_NAME) as db:
        # Save quiz attempt
        await db.execute(
            """INSERT INTO quiz_attempts 
               (user_id, attempt_date, total_questions, correct_answers, score_percentage) 
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, datetime.now(), total_questions, correct_answers, score_percentage)
        )
        
        # Get the attempt_id of the just inserted record
        cursor = await db.execute("SELECT last_insert_rowid()")
        attempt_id = (await cursor.fetchone())[0]
        
        # Save individual answers
        for answer in session_data["answers"]:
            await db.execute(
                """INSERT INTO user_answers 
                   (user_id, attempt_id, question, selected_answer, correct_answer, is_correct) 
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (user_id, attempt_id, answer["question"], answer["selected"], 
                 answer["correct_answer"], answer["correct"])
            )
        
        # Update user stats
        await db.execute(
            """INSERT OR REPLACE INTO user_stats 
               (user_id, total_quizzes, total_questions_answered, total_correct_answers, best_score, last_quiz_date) 
               VALUES (?, 
                       COALESCE((SELECT total_quizzes FROM user_stats WHERE user_id = ?), 0) + 1,
                       COALESCE((SELECT total_questions_answered FROM user_stats WHERE user_id = ?), 0) + ?,
                       COALESCE((SELECT total_correct_answers FROM user_stats WHERE user_id = ?), 0) + ?,
                       MAX(COALESCE((SELECT best_score FROM user_stats WHERE user_id = ?), 0), ?),
                       ?)""",
            (user_id, user_id, user_id, total_questions, user_id, correct_answers, user_id, score_percentage, datetime.now())
        )
        
        await db.commit()
