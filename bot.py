import asyncio
import logging
import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from groq import Groq
from supabase import create_client

# Настройки
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Клиенты
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()
groq_client = Groq(api_key=GROQ_API_KEY)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

logging.basicConfig(level=logging.INFO)

# Главное меню
def main_menu():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📚 Учить слова"), KeyboardButton(text="💬 Диалог с AI")],
            [KeyboardButton(text="📊 Мой прогресс"), KeyboardButton(text="🎯 Урок дня")],
            [KeyboardButton(text="ℹ️ Помощь")]
        ],
        resize_keyboard=True
    )
    return keyboard

# Получить или создать пользователя
async def get_or_create_user(user_id: int, username: str, full_name: str):
    try:
        result = supabase.table("users").select("*").eq("telegram_id", user_id).execute()
        if result.data:
            return result.data[0]
        new_user = {
            "telegram_id": user_id,
            "username": username,
            "full_name": full_name,
            "level": "A0",
            "xp": 0,
            "streak": 0,
            "lessons_done": 0
        }
        result = supabase.table("users").insert(new_user).execute()
        return result.data[0]
    except Exception as e:
        logging.error(f"DB error: {e}")
        return {"level": "A0", "xp": 0, "streak": 0, "lessons_done": 0}

# AI ответ
async def ask_ai(messages: list, level: str = "A0") -> str:
    system_prompt = f"""Ты дружелюбный учитель английского языка. 
Уровень ученика: {level}.
Правила:
- Если уровень A0-A1: объясняй очень просто, используй много русского, английские слова пиши с переводом
- Если уровень A2: половина объяснений на русском, половина на английском
- Всегда исправляй ошибки мягко и с примерами
- Делай уроки интересными и короткими (не больше 5 предложений)
- Используй эмодзи для наглядности
- В конце каждого сообщения задавай один простой вопрос чтобы практиковаться"""
    
    try:
        response = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "system", "content": system_prompt}] + messages,
            max_tokens=500,
            temperature=0.7
        )
        return response.choices[0].message.content
    except Exception as e:
        logging.error(f"Groq error: {e}")
        return "Извини, произошла ошибка. Попробуй ещё раз! 🔄"

# Команда /start
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user = await get_or_create_user(
        message.from_user.id,
        message.from_user.username or "",
        message.from_user.full_name or ""
    )
    await message.answer(
        f"👋 Привет, {message.from_user.first_name}!\n\n"
        f"Я твой персональный учитель английского языка 🇬🇧\n\n"
        f"За 30 дней ты сможешь:\n"
        f"✅ Понимать английскую речь\n"
        f"✅ Общаться на базовом уровне\n"
        f"✅ Читать простые тексты\n\n"
        f"Твой текущий уровень: {user.get('level', 'A0')}\n"
        f"Занимаемся всего 30-60 минут в день!\n\n"
        f"Выбери с чего начнём 👇",
        reply_markup=main_menu()
    )

# Урок дня
@dp.message(F.text == "🎯 Урок дня")
async def daily_lesson(message: types.Message):
    user = await get_or_create_user(
        message.from_user.id,
        message.from_user.username or "",
        message.from_user.full_name or ""
    )
    level = user.get("level", "A0")
    lessons_done = user.get("lessons_done", 0)
    
    prompt = f"""Создай урок дня для ученика.
Это урок номер {lessons_done + 1}.
Уровень: {level}
Формат урока:
1. Тема дня (одна строка)
2. Три новых слова с переводом и примером
3. Одно простое грамматическое правило
4. Маленькое задание для практики
Сделай урок интересным и мотивирующим!"""
    
    response = await ask_ai([{"role": "user", "content": prompt}], level)
    
    try:
        supabase.table("users").update(
            {"lessons_done": lessons_done + 1}
        ).eq("telegram_id", message.from_user.id).execute()
    except:
        pass
    
    await message.answer(f"📖 *Урок дня #{lessons_done + 1}*\n\n{response}", parse_mode="Markdown")

# Учить слова
@dp.message(F.text == "📚 Учить слова")
async def learn_words(message: types.Message):
    user = await get_or_create_user(
        message.from_user.id,
        message.from_user.username or "",
        message.from_user.full_name or ""
    )
    level = user.get("level", "A0")
    
    prompt = """Дай мне 5 самых полезных английских слов для начинающего.
Формат для каждого слова:
🔤 Слово [транскрипция] — перевод
💡 Пример: английское предложение — русский перевод
После всех слов дай простое задание: составить одно предложение с любым из этих слов."""
    
    response = await ask_ai([{"role": "user", "content": prompt}], level)
    await message.answer(f"📚 *Новые слова*\n\n{response}", parse_mode="Markdown")

# Диалог с AI
@dp.message(F.text == "💬 Диалог с AI")
async def start_dialog(message: types.Message):
    await message.answer(
        "💬 *Режим диалога активирован!*\n\n"
        "Напиши мне что-нибудь на английском (или по-русски если не знаешь как) — "
        "и я отвечу, исправлю ошибки и помогу научиться!\n\n"
        "Например напиши: *Hello* или *Как сказать 'я хочу есть'?*",
        parse_mode="Markdown"
    )

# Прогресс
@dp.message(F.text == "📊 Мой прогресс")
async def show_progress(message: types.Message):
    user = await get_or_create_user(
        message.from_user.id,
        message.from_user.username or "",
        message.from_user.full_name or ""
    )
    level = user.get("level", "A0")
    xp = user.get("xp", 0)
    streak = user.get("streak", 0)
    lessons = user.get("lessons_done", 0)
    
    levels = ["A0", "A1", "A2", "B1", "B2", "C1"]
    current_idx = levels.index(level) if level in levels else 0
    progress_bar = "🟩" * (current_idx + 1) + "⬜" * (5 - current_idx)
    
    await message.answer(
        f"📊 *Твой прогресс*\n\n"
        f"🎯 Уровень: {level}\n"
        f"{progress_bar}\n\n"
        f"⭐ Опыт: {xp} XP\n"
        f"🔥 Streak: {streak} дней подряд\n"
        f"📖 Уроков пройдено: {lessons}\n\n"
        f"{'🏆 Отличный прогресс! Продолжай!' if lessons > 5 else '💪 Хорошее начало! Занимайся каждый день!'}",
        parse_mode="Markdown"
    )

# Помощь
@dp.message(F.text == "ℹ️ Помощь")
async def help_cmd(message: types.Message):
    await message.answer(
        "ℹ️ *Как пользоваться ботом*\n\n"
        "🎯 *Урок дня* — получи новый урок\n"
        "📚 *Учить слова* — новые слова с примерами\n"
        "💬 *Диалог с AI* — практикуй разговор\n"
        "📊 *Прогресс* — смотри свои достижения\n\n"
        "💡 *Советы:*\n"
        "• Занимайся каждый день хотя бы 30 минут\n"
        "• Отправляй голосовые сообщения для практики\n"
        "• Не бойся ошибаться — это нормально!\n\n"
        "📸 Можешь отправить картинку — я помогу описать её по-английски!",
        parse_mode="Markdown"
    )

# Обработка картинок
@dp.message(F.photo)
async def handle_photo(message: types.Message):
    user = await get_or_create_user(
        message.from_user.id,
        message.from_user.username or "",
        message.from_user.full_name or ""
    )
    level = user.get("level", "A0")
    
    prompt = """Пользователь прислал картинку для изучения английского.
Сделай следующее:
1. Опиши что обычно бывает на таких картинках (5-7 предметов)
2. Дай английские слова для этих предметов с переводом
3. Составь 2 простых предложения описывающих картинку
4. Задай вопрос о картинке на английском с переводом"""
    
    response = await ask_ai([{"role": "user", "content": prompt}], level)
    await message.answer(
        f"🖼 *Учим английский по картинке!*\n\n{response}",
        parse_mode="Markdown"
    )

# Обработка голосовых
@dp.message(F.voice)
async def handle_voice(message: types.Message):
    await message.answer(
        "🎙 *Голосовое получено!*\n\n"
        "Голосовые сообщения скоро будут доступны.\n"
        "А пока напиши текстом что хотел сказать — я помогу перевести и исправить! 💪",
        parse_mode="Markdown"
    )

# Обработка всех текстовых сообщений (диалог)
@dp.message(F.text)
async def handle_text(message: types.Message):
    user = await get_or_create_user(
        message.from_user.id,
        message.from_user.username or "",
        message.from_user.full_name or ""
    )
    level = user.get("level", "A0")
    
    response = await ask_ai(
        [{"role": "user", "content": message.text}],
        level
    )
    
    try:
        xp = user.get("xp", 0)
        supabase.table("users").update(
            {"xp": xp + 5}
        ).eq("telegram_id", message.from_user.id).execute()
    except:
        pass
    
    await message.answer(response)

# Запуск
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
