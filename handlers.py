from aiogram import types, F
from aiogram.filters.command import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from datetime import datetime

from quiz_data import quiz_data
from database import get_quiz_index, update_quiz_index, save_quiz_results

# Store user's current session answers
user_sessions = {}

def generate_options_keyboard(answer_options, right_answer):
    builder = InlineKeyboardBuilder()
    for option in answer_options:
        builder.add(types.InlineKeyboardButton(text=option, callback_data=f"answer_{option}"))
    builder.adjust(1)
    return builder.as_markup()

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
    await update_quiz_index(user_id, 0)
    await get_question(message, user_id)

async def show_quiz_results(message, user_id):
    """Show quiz results to user"""
    async with aiosqlite.connect(DB_NAME) as db:
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
                if isinstance(attempt_date, str):
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

async def show_user_stats(message, user_id):
    """Show user's overall statistics"""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            """SELECT total_quizzes, total_questions_answered, total_correct_answers, best_score, last_quiz_date 
               FROM user_stats WHERE user_id = ?""",
            (user_id,)
        ) as cursor:
            stats = await cursor.fetchone()
            
            if not stats or stats[0] == 0:
                await message.answer("У вас пока нет завершенных квизов. Начните игру с помощью /quiz!")
                return
            
            total_quizzes, total_questions, total_correct, best_score, last_date = stats
            if isinstance(last_date, str):
                last_date = datetime.fromisoformat(last_date)
            
            async with db.execute(
                """SELECT attempt_date, score_percentage FROM quiz_attempts 
                   WHERE user_id = ? ORDER BY attempt_date DESC LIMIT 5""",
                (user_id,)
            ) as cursor2:
                recent_attempts = await cursor2.fetchall()
            
            stats_text = (
                f"📊 *Ваша статистика:*\n\n"
                f"🎮 Всего квизов: {total_quizzes}\n"
                f"❓ Всего ответов: {total_questions}\n"
                f"✅ Правильных ответов: {total_correct}\n"
                f"📈 Процент: {(total_correct/total_questions*100):.1f}%\n"
                f"🏆 Лучший результат: {best_score:.1f}%\n"
                f"📅 Последний квиз: {last_date.strftime('%d.%m.%Y %H:%M')}\n\n"
                f"*Последние 5 результатов:*\n"
            )
            
            for i, (attempt_date, score) in enumerate(recent_attempts, 1):
                if isinstance(attempt_date, str):
                    attempt_date = datetime.fromisoformat(attempt_date)
                stats_text += f"{i}. {attempt_date.strftime('%d.%m.%Y')}: {score:.1f}%\n"
            
            await message.answer(stats_text, parse_mode="Markdown")

async def show_last_answers(message, user_id):
    """Show user's answers from the last quiz"""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            """SELECT attempt_id, attempt_date FROM quiz_attempts 
               WHERE user_id = ? ORDER BY attempt_date DESC LIMIT 1""",
            (user_id,)
        ) as cursor:
            latest = await cursor.fetchone()
            
            if not latest:
                await message.answer("У вас пока нет завершенных квизов!")
                return
            
            attempt_id, attempt_date = latest
            if isinstance(attempt_date, str):
                attempt_date = datetime.fromisoformat(attempt_date)
            
            async with db.execute(
                """SELECT question, selected_answer, correct_answer, is_correct 
                   FROM user_answers WHERE user_id = ? AND attempt_id = ? ORDER BY id""",
                (user_id, attempt_id)
            ) as cursor2:
                answers = await cursor2.fetchall()
                
                answers_text = f"📝 *Ваши ответы от {attempt_date.strftime('%d.%m.%Y %H:%M')}:*\n\n"
                
                for i, (question, selected, correct, is_correct) in enumerate(answers, 1):
                    emoji = "✅" if is_correct else "❌"
                    answers_text += f"{i}. {emoji} *{question}*\n"
                    answers_text += f"   Ваш ответ: {selected}\n"
                    if not is_correct:
                        answers_text += f"   Правильный: {correct}\n"
                    answers_text += "\n"
                
                if len(answers_text) > 4000:
                    answers_text = answers_text[:4000] + "...\n(Обрезано)"
                
                await message.answer(answers_text, parse_mode="Markdown")

def register_handlers(dp):
    # Callback handler for answers
    @dp.callback_query(F.data.startswith("answer_"))
    async def handle_answer(callback: types.CallbackQuery):
        selected_text = callback.data.replace("answer_", "")
        user_id = callback.from_user.id
        current_question_index = await get_quiz_index(user_id)
        
        correct_option_text = quiz_data[current_question_index]["options"][quiz_data[current_question_index]["correct_option"]]
        is_correct = (selected_text == correct_option_text)
        
        if user_id not in user_sessions:
            user_sessions[user_id] = {"answers": [], "start_time": datetime.now()}
        
        user_sessions[user_id]["answers"].append({
            "question": quiz_data[current_question_index]["question"],
            "selected": selected_text,
            "correct": is_correct,
            "correct_answer": correct_option_text
        })
        
        await callback.bot.edit_message_text(
            chat_id=callback.from_user.id,
            message_id=callback.message.message_id,
            text=f"{callback.message.text}\n\n{'✅' if is_correct else '❌'} Your answer: {selected_text}",
            reply_markup=None,
        )
        
        if is_correct:
            await callback.message.answer("Верно! ✅")
        else:
            await callback.message.answer(f"Неправильно ❌\nПравильный ответ: {correct_option_text}")
        
        current_question_index += 1
        await update_quiz_index(user_id, current_question_index)
        
        if current_question_index < len(quiz_data):
            await get_question(callback.message, user_id)
        else:
            await save_quiz_results(user_id, user_sessions[user_id])
            await show_quiz_results(callback.message, user_id)
            del user_sessions[user_id]
        
        await callback.answer()
    
    # Command handlers
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
            "/stats - Статистика\n"
            "/answers - Мои ответы\n\n"
            "Или используйте кнопки:",
            reply_markup=builder.as_markup(resize_keyboard=True),
            parse_mode="Markdown"
        )
    
    @dp.message(F.text == "Начать игру")
    @dp.message(Command("quiz"))
    async def cmd_quiz(message: types.Message):
        await message.answer("🎯 *Новый квиз!* Удачи! 🍀", parse_mode="Markdown")
        await new_quiz(message)
    
    @dp.message(F.text == "📊 Статистика")
    @dp.message(Command("stats"))
    async def cmd_stats(message: types.Message):
        await show_user_stats(message, message.from_user.id)
    
    @dp.message(F.text == "📝 Мои ответы")
    @dp.message(Command("answers"))
    async def cmd_answers(message: types.Message):
        await show_last_answers(message, message.from_user.id)
