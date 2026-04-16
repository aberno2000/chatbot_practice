import aiosqlite
import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters.command import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram import F
from datetime import datetime

from quiz_data import quiz_data
import os
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.DEBUG)

API_TOKEN = str(os.getenv("BOT_TOKEN"))
DB_NAME = "quiz_bot.db"

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# Store user's current session answers
user_sessions = {}


def generate_options_keyboard(answer_options, right_answer):
    builder = InlineKeyboardBuilder()

    for option in answer_options:
        builder.add(
            types.InlineKeyboardButton(
                text=option,
                callback_data=f"answer_{option}",
            )
        )

    builder.adjust(1)
    return builder.as_markup()


@dp.callback_query(F.data.startswith("answer_"))
async def handle_answer(callback: types.CallbackQuery):
    # Get the selected answer text
    selected_text = callback.data.replace("answer_", "")
    user_id = callback.from_user.id
    current_question_index = await get_quiz_index(user_id)
    
    # Get correct answer for current question
    correct_option_text = quiz_data[current_question_index]["options"][quiz_data[current_question_index]["correct_option"]]
    is_correct = (selected_text == correct_option_text)
    
    # Save answer to session
    if user_id not in user_sessions:
        user_sessions[user_id] = {
            "answers": [],
            "start_time": datetime.now()
        }
    
    user_sessions[user_id]["answers"].append({
        "question": quiz_data[current_question_index]["question"],
        "selected": selected_text,
        "correct": is_correct,
        "correct_answer": correct_option_text
    })
    
    # Remove buttons and show the selected answer in the original message
    await callback.bot.edit_message_text(
        chat_id=callback.from_user.id,
        message_id=callback.message.message_id,
        text=f"{callback.message.text}\n\n{'✅' if is_correct else '❌'} Your answer: {selected_text}",
        reply_markup=None,
    )
    
    # Send result message
    if is_correct:
        await callback.message.answer("Верно! ✅")
    else:
        await callback.message.answer(
            f"Неправильно ❌\nПравильный ответ: {correct_option_text}"
        )
    
    # Move to next question
    current_question_index += 1
    await update_quiz_index(user_id, current_question_index)
    
    # Check if quiz is finished
    if current_question_index < len(quiz_data):
        await get_question(callback.message, user_id)
    else:
        # Quiz completed - save results to database
        await save_quiz_results(user_id)
        await show_quiz_results(callback.message, user_id)
    
    await callback.answer()


async def save_quiz_results(user_id):
    """Save quiz results to database"""
    if user_id not in user_sessions:
        return
    
    session = user_sessions[user_id]
    total_questions = len(session["answers"])
    correct_answers = sum(1 for a in session["answers"] if a["correct"])
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
        for answer in session["answers"]:
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
    
    # Clear session data after saving
    del user_sessions[user_id]

async def show_quiz_results(message, user_id):
    """Show quiz results to user"""
    async with aiosqlite.connect(DB_NAME) as db:
        # Get the latest attempt
        async with db.execute(
            """SELECT attempt_date, total_questions, correct_answers, score_percentage 
               FROM quiz_attempts 
               WHERE user_id = ? 
               ORDER BY attempt_date DESC LIMIT 1""",
            (user_id,)
        ) as cursor:
            attempt = await cursor.fetchone()
            
            if attempt:
                attempt_date, total, correct, percentage = attempt
                
                # Convert to datetime if it's a string
                if isinstance(attempt_date, str):
                    from datetime import datetime
                    attempt_date = datetime.fromisoformat(attempt_date)
                
                results_text = (
                    f"📊 *Результаты квиза:*\n\n"
                    f"📅 Дата: {attempt_date.strftime('%d.%m.%Y %H:%M')}\n"
                    f"❓ Всего вопросов: {total}\n"
                    f"✅ Правильных ответов: {correct}\n"
                    f"📈 Процент: {percentage:.1f}%\n"
                    f"{'🏆 Отлично!' if percentage >= 80 else '👍 Хорошо!' if percentage >= 60 else '📚 Нужно больше практики!'}"
                )
                
                await message.answer(results_text, parse_mode="Markdown")

@dp.message(Command("stats"))
async def show_user_stats(message: types.Message):
    """Show user's overall statistics"""
    user_id = message.from_user.id
    
    async with aiosqlite.connect(DB_NAME) as db:
        # Get user stats
        async with db.execute(
            """SELECT total_quizzes, total_questions_answered, total_correct_answers, best_score, last_quiz_date 
               FROM user_stats 
               WHERE user_id = ?""",
            (user_id,)
        ) as cursor:
            stats = await cursor.fetchone()
            
            if not stats or stats[0] == 0:
                await message.answer("У вас пока нет завершенных квизов. Начните игру с помощью /quiz или кнопки 'Начать игру'!")
                return
            
            total_quizzes, total_questions, total_correct, best_score, last_date = stats
            
            # Convert to datetime if it's a string
            if isinstance(last_date, str):
                from datetime import datetime
                last_date = datetime.fromisoformat(last_date)
            
            # Get recent attempts
            async with db.execute(
                """SELECT attempt_date, score_percentage 
                   FROM quiz_attempts 
                   WHERE user_id = ? 
                   ORDER BY attempt_date DESC 
                   LIMIT 5""",
                (user_id,)
            ) as cursor2:
                recent_attempts = await cursor2.fetchall()
            
            stats_text = (
                f"📊 *Ваша статистика:*\n\n"
                f"🎮 Всего квизов пройдено: {total_quizzes}\n"
                f"❓ Всего ответов: {total_questions}\n"
                f"✅ Правильных ответов: {total_correct}\n"
                f"📈 Общий процент: {(total_correct/total_questions*100):.1f}%\n"
                f"🏆 Лучший результат: {best_score:.1f}%\n"
                f"📅 Последний квиз: {last_date.strftime('%d.%m.%Y %H:%M')}\n\n"
                f"*Последние 5 результатов:*\n"
            )
            
            for i, (attempt_date, score) in enumerate(recent_attempts, 1):
                # Convert to datetime if it's a string
                if isinstance(attempt_date, str):
                    attempt_date = datetime.fromisoformat(attempt_date)
                stats_text += f"{i}. {attempt_date.strftime('%d.%m.%Y')}: {score:.1f}%\n"
            
            await message.answer(stats_text, parse_mode="Markdown")

@dp.message(Command("answers"))
async def show_last_answers(message: types.Message):
    """Show user's answers from the last quiz"""
    user_id = message.from_user.id
    
    async with aiosqlite.connect(DB_NAME) as db:
        # Get the latest attempt
        async with db.execute(
            """SELECT attempt_id, attempt_date 
               FROM quiz_attempts 
               WHERE user_id = ? 
               ORDER BY attempt_date DESC LIMIT 1""",
            (user_id,)
        ) as cursor:
            latest = await cursor.fetchone()
            
            if not latest:
                await message.answer("У вас пока нет завершенных квизов!")
                return
            
            attempt_id, attempt_date = latest
            
            # Convert to datetime if it's a string
            if isinstance(attempt_date, str):
                from datetime import datetime
                attempt_date = datetime.fromisoformat(attempt_date)
            
            # Get all answers for this attempt
            async with db.execute(
                """SELECT question, selected_answer, correct_answer, is_correct 
                   FROM user_answers 
                   WHERE user_id = ? AND attempt_id = ?
                   ORDER BY id""",
                (user_id, attempt_id)
            ) as cursor2:
                answers = await cursor2.fetchall()
                
                answers_text = f"📝 *Ваши ответы на квиз от {attempt_date.strftime('%d.%m.%Y %H:%M')}:*\n\n"
                
                for i, (question, selected, correct, is_correct) in enumerate(answers, 1):
                    emoji = "✅" if is_correct else "❌"
                    answers_text += f"{i}. {emoji} *Вопрос:* {question}\n"
                    answers_text += f"   *Ваш ответ:* {selected}\n"
                    if not is_correct:
                        answers_text += f"   *Правильный ответ:* {correct}\n"
                    answers_text += "\n"
                
                if len(answers_text) > 4000:
                    answers_text = answers_text[:4000] + "...\n(Ответы обрезаны из-за длины)"
                
                await message.answer(answers_text, parse_mode="Markdown")
# Хэндлер на команду /start
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    builder = ReplyKeyboardBuilder()
    builder.add(
        types.KeyboardButton(text="Начать игру"),
        types.KeyboardButton(text="📊 Статистика"),
        types.KeyboardButton(text="📝 Мои ответы")
    )
    await message.answer(
        "Добро пожаловать в квиз!\n\n"
        "📌 *Доступные команды:*\n"
        "/quiz - Начать новый квиз\n"
        "/stats - Показать статистику\n"
        "/answers - Показать ответы на последний квиз\n\n"
        "Или используйте кнопки ниже:",
        reply_markup=builder.as_markup(resize_keyboard=True),
        parse_mode="Markdown"
    )


async def get_question(message, user_id):
    current_question_index = await get_quiz_index(user_id)
    correct_index = quiz_data[current_question_index]["correct_option"]
    opts = quiz_data[current_question_index]["options"]
    kb = generate_options_keyboard(opts, opts[correct_index])
    await message.answer(
        f"❓ *Вопрос {current_question_index + 1}/{len(quiz_data)}:*\n\n{quiz_data[current_question_index]['question']}",
        reply_markup=kb,
        parse_mode="Markdown"
    )


async def new_quiz(message):
    user_id = message.from_user.id
    current_question_index = 0
    await update_quiz_index(user_id, current_question_index)
    await get_question(message, user_id)


async def get_quiz_index(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT question_index FROM quiz_state WHERE user_id = (?)", (user_id,)
        ) as cursor:
            results = await cursor.fetchone()
            if results is not None:
                return results[0]
            else:
                return 0


async def update_quiz_index(user_id, index):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT OR REPLACE INTO quiz_state (user_id, question_index) VALUES (?, ?)",
            (user_id, index),
        )
        await db.commit()


# Хэндлер на команду /quiz и кнопки
@dp.message(F.text == "Начать игру")
@dp.message(Command("quiz"))
async def cmd_quiz(message: types.Message):
    await message.answer("🎯 *Начинаем новый квиз!* Удачи! 🍀", parse_mode="Markdown")
    await new_quiz(message)


@dp.message(F.text == "📊 Статистика")
async def button_stats(message: types.Message):
    await show_user_stats(message)


@dp.message(F.text == "📝 Мои ответы")
async def button_answers(message: types.Message):
    await show_last_answers(message)


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


# Запуск процесса поллинга новых апдейтов
async def main():
    await create_tables()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
