import asyncio
import logging
import os
import tempfile
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from groq import Groq
from supabase import create_client

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()
groq_client = Groq(api_key=GROQ_API_KEY)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

logging.basicConfig(level=logging.INFO)

LEVELS = ["A0", "A1", "A2", "B1", "B2", "C1"]

LEVEL_NAMES = {
    "A0": "🥚 Абсолютный новичок",
    "A1": "🐣 Начинающий",
    "A2": "🐥 Элементарный",
    "B1": "🦅 Средний",
    "B2": "🦁 Выше среднего",
    "C1": "🏆 Продвинутый"
}

XP_PER_LEVEL = {
    "A0": 0, "A1": 100, "A2": 300, "B1": 600, "B2": 1000, "C1": 1500
}

user_modes = {}

def main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📚 Слова"), KeyboardButton(text="💬 Диалог")],
            [KeyboardButton(text="🖼 Картинки"), KeyboardButton(text="🎙 Голосовой чат")],
            [KeyboardButton(text="🔄 Переводчик"), KeyboardButton(text="📊 Прогресс")],
            [KeyboardButton(text="🎯 Урок дня"), KeyboardButton(text="❓ Помощь")]
        ],
        resize_keyboard=True
    )

async def get_user(user_id, username="", full_name=""):
    try:
        r = supabase.table("users").select("*").eq("telegram_id", user_id).execute()
        if r.data:
            return r.data[0]
        new = {"telegram_id": user_id, "username": username,
               "full_name": full_name, "level": "A0", "xp": 0,
               "streak": 0, "lessons_done": 0}
        r = supabase.table("users").insert(new).execute()
        return r.data[0]
    except Exception as e:
        logging.error(f"DB: {e}")
        return {"level": "A0", "xp": 0, "streak": 0, "lessons_done": 0}

async def add_xp(user_id, amount):
    try:
        user = await get_user(user_id)
        new_xp = user.get("xp", 0) + amount
        current_level = user.get("level", "A0")
        idx = LEVELS.index(current_level)
        if idx < len(LEVELS) - 1:
            next_level = LEVELS[idx + 1]
            if new_xp >= XP_PER_LEVEL[next_level]:
                supabase.table("users").update(
                    {"xp": new_xp, "level": next_level}
                ).eq("telegram_id", user_id).execute()
                return next_level
        supabase.table("users").update(
            {"xp": new_xp}
        ).eq("telegram_id", user_id).execute()
    except Exception as e:
        logging.error(f"XP: {e}")
    return None

async def ask_ai(messages, level="A0", mode="dialog"):
    prompts = {
        "dialog": f"""Ты дружелюбный учитель английского языка. Уровень ученика: {level}.
Правила:
- Объяснения и исправления ВСЕГДА на русском языке
- Но сам диалог и примеры ВСЕГДА на английском с переводом в скобках
- Если уровень A0-A1: пиши короткие английские фразы, сразу давай перевод и транскрипцию. Например: "Let's be friends! [лэтс би фрэндз] — Давай дружить! 🐱"
- Если уровень A2: английские предложения + перевод под каждым
- Если уровень B1+: в основном английский, перевод только для сложных слов
- ВСЕГДА давай 1-2 английские фразы по теме разговора с переводом
- В конце ВСЕГДА: "💡 Исправление: [ошибка] → [правильно по-английски] — [объяснение на русском]"
- Задавай один вопрос на английском с переводом
- Будь позитивным и поддерживающим""",

        "words": f"""Ты учитель английского. Уровень ученика: {level}.
Дай 5 полезных слов в формате:
🔤 Слово [транскрипция] — перевод
💡 Пример: English sentence — русский перевод
🧠 Ассоциация для запоминания (яркий образ или история)
После всех слов — простое задание на практику.""",

        "lesson": f"""Ты учитель английского. Уровень ученика: {level}.
Создай увлекательный урок:
📖 Тема урока (на русском)
✨ 3 новых слова с переводом и примерами
📝 Одно грамматическое правило с примерами на русском
🎯 Практическое задание
Всё объяснение на русском языке, английские примеры с переводом.""",

        "translator": f"""Ты переводчик.
Если текст на русском — переведи на английский.
Если текст на английском — переведи на русский.
Формат ответа:
🔄 Перевод: [результат]
📝 Примечание: [краткое грамматическое пояснение если нужно]""",

        "voice_dialog": f"""Ты ведёшь живой разговорный диалог на английском. Уровень ученика: {level}.
- Отвечай на английском коротко и естественно (2-3 предложения)
- В конце ВСЕГДА добавляй на русском: "💡 [исправление ошибки или совет если есть]"
- Если уровень A0-A1: добавь перевод своего ответа на русском
- Будь тёплым и поддерживающим""",

        "picture": f"""Ты учишь английскому через картинки. Уровень ученика: {level}.
Урок по картинке:
🖼 Что на картинке (описание на русском)
📚 5-7 ключевых слов: английское [транскрипция] — русский перевод
🧠 Яркая ассоциация для каждого слова
💬 2 примера предложений с переводом
❓ Один вопрос по картинке на английском с переводом"""
    }

    system = prompts.get(mode, prompts["dialog"])
    try:
        r = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "system", "content": system}] + messages,
            max_tokens=700,
            temperature=0.7
        )
        return r.choices[0].message.content
    except Exception as e:
        logging.error(f"Groq: {e}")
        return "Извини, произошла ошибка. Попробуй ещё раз! 🔄"

async def transcribe_voice(file_path):
    try:
        with open(file_path, "rb") as f:
            result = groq_client.audio.transcriptions.create(
                model="whisper-large-v3",
                file=f,
                response_format="text"
            )
        return result
    except Exception as e:
        logging.error(f"Whisper: {e}")
        return None

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user = await get_user(
        message.from_user.id,
        message.from_user.username or "",
        message.from_user.full_name or ""
    )
    level = user.get("level", "A0")
    level_name = LEVEL_NAMES.get(level, level)
    await message.answer(
        f"👋 Привет, {message.from_user.first_name}!\n\n"
        f"Я твой личный AI-репетитор английского языка 🇬🇧\n\n"
        f"За 30 дней ты сможешь:\n"
        f"✅ Понимать английскую речь\n"
        f"✅ Общаться с иностранцами\n"
        f"✅ Читать и писать уверенно\n\n"
        f"🎯 Твой уровень: {level_name}\n"
        f"⏱ Всего 30-60 минут в день!\n\n"
        f"Выбери с чего начнём 👇",
        reply_markup=main_menu()
    )

@dp.message(F.text == "🎯 Урок дня")
async def daily_lesson(message: types.Message):
    user = await get_user(message.from_user.id)
    level = user.get("level", "A0")
    lessons = user.get("lessons_done", 0)
    await message.answer("📖 Готовлю твой урок...")
    response = await ask_ai(
        [{"role": "user", "content": f"Создай урок номер {lessons+1}"}],
        level, "lesson"
    )
    try:
        supabase.table("users").update(
            {"lessons_done": lessons+1}
        ).eq("telegram_id", message.from_user.id).execute()
    except:
        pass
    new_level = await add_xp(message.from_user.id, 20)
    text = f"📖 *Урок #{lessons+1}*\n\n{response}"
    if new_level:
        text += f"\n\n🎉 *Новый уровень! Ты достиг {LEVEL_NAMES[new_level]}!*"
    await message.answer(text, parse_mode="Markdown")

@dp.message(F.text == "📚 Слова")
async def learn_words(message: types.Message):
    user = await get_user(message.from_user.id)
    level = user.get("level", "A0")
    await message.answer("📚 Подбираю слова для тебя...")
    response = await ask_ai(
        [{"role": "user", "content": "Дай 5 полезных слов"}],
        level, "words"
    )
    await add_xp(message.from_user.id, 10)
    await message.answer(f"📚 *Новые слова*\n\n{response}", parse_mode="Markdown")

@dp.message(F.text == "💬 Диалог")
async def start_dialog(message: types.Message):
    user_modes[message.from_user.id] = "dialog"
    await message.answer(
        "💬 *Режим диалога включён!*\n\n"
        "Напиши мне что-нибудь — по-английски или по-русски.\n"
        "Я отвечу, исправлю ошибки и объясню правила!\n\n"
        "Попробуй написать: *Hello! My name is...*\n"
        "Или спроси: *Как сказать 'я хочу есть'?*",
        parse_mode="Markdown"
    )

@dp.message(F.text == "🎙 Голосовой чат")
async def voice_chat_mode(message: types.Message):
    user_modes[message.from_user.id] = "voice_dialog"
    await message.answer(
        "🎙 *Голосовой режим включён!*\n\n"
        "Отправляй голосовые сообщения на английском.\n"
        "Я пойму тебя и отвечу!\n\n"
        "Также укажу на ошибки в произношении и грамматике 💪\n\n"
        "Нажми на микрофон и скажи что-нибудь! 🎤\n"
        "Например: *Hello! How are you?*",
        parse_mode="Markdown"
    )

@dp.message(F.text == "🖼 Картинки")
async def picture_mode(message: types.Message):
    user_modes[message.from_user.id] = "picture"
    await message.answer(
        "🖼 *Режим обучения по картинкам!*\n\n"
        "Отправь любое фото — я научу тебя английским словам "
        "связанным с тем что на картинке!\n\n"
        "Плюс дам яркие ассоциации для запоминания 🧠\n\n"
        "📸 Отправь фото прямо сейчас!",
        parse_mode="Markdown"
    )

@dp.message(F.text == "🔄 Переводчик")
async def translator_mode(message: types.Message):
    user_modes[message.from_user.id] = "translator"
    await message.answer(
        "🔄 *Режим переводчика включён!*\n\n"
        "Я переведу:\n"
        "✍️ Текст — просто напиши\n"
        "📸 Фото с текстом — отправь картинку\n"
        "🎙 Голосовое — запиши сообщение\n\n"
        "🇷🇺 Русский → 🇬🇧 Английский\n"
        "🇬🇧 Английский → 🇷🇺 Русский\n\n"
        "Напиши или отправь что нужно перевести!",
        parse_mode="Markdown"
    )

@dp.message(F.text == "📊 Прогресс")
async def show_progress(message: types.Message):
    user = await get_user(message.from_user.id)
    level = user.get("level", "A0")
    xp = user.get("xp", 0)
    streak = user.get("streak", 0)
    lessons = user.get("lessons_done", 0)
    level_name = LEVEL_NAMES.get(level, level)
    idx = LEVELS.index(level) if level in LEVELS else 0
    bar = "🟩" * (idx+1) + "⬜" * (5-idx)
    if idx < len(LEVELS)-1:
        next_level = LEVELS[idx+1]
        needed = XP_PER_LEVEL[next_level] - xp
        next_info = f"📈 До уровня {LEVEL_NAMES[next_level]}: {needed} XP"
    else:
        next_info = "🏆 Максимальный уровень!"
    await message.answer(
        f"📊 *Твой прогресс*\n\n"
        f"🎯 Уровень: {level_name}\n"
        f"{bar}\n\n"
        f"⭐ Опыт: {xp} XP\n"
        f"{next_info}\n\n"
        f"🔥 Streak: {streak} дней подряд\n"
        f"📖 Уроков пройдено: {lessons}\n\n"
        f"{'🏆 Отличный прогресс! Так держать!' if lessons > 10 else '💪 Занимайся каждый день!'}",
        parse_mode="Markdown"
    )

@dp.message(F.text == "❓ Помощь")
async def help_cmd(message: types.Message):
    await message.answer(
        "❓ *Как пользоваться ботом*\n\n"
        "🎯 *Урок дня* — персональный урок под твой уровень\n"
        "📚 *Слова* — 5 новых слов с ассоциациями\n"
        "💬 *Диалог* — общайся с AI, получай исправления\n"
        "🎙 *Голосовой чат* — говори по-английски, AI отвечает\n"
        "🖼 *Картинки* — учи слова по фотографиям\n"
        "🔄 *Переводчик* — текст, фото или голос\n"
        "📊 *Прогресс* — твой опыт и уровень\n\n"
        "💡 *Советы:*\n"
        "• Занимайся каждый день хотя бы 30 минут\n"
        "• Не бойся ошибаться — это часть обучения\n"
        "• Используй голосовой режим для практики речи\n"
        "• Отправляй фото из жизни для изучения слов",
        parse_mode="Markdown"
    )

@dp.message(F.photo)
async def handle_photo(message: types.Message):
    user = await get_user(message.from_user.id)
    level = user.get("level", "A0")
    mode = user_modes.get(message.from_user.id, "picture")
    await message.answer("🔍 Анализирую картинку...")
    if mode == "translator":
        prompt = "Пользователь прислал фото с текстом для перевода."
    else:
        prompt = "Пользователь прислал фото для изучения английского."
    response = await ask_ai(
        [{"role": "user", "content": prompt}],
        level, mode if mode in ["translator", "picture"] else "picture"
    )
    await add_xp(message.from_user.id, 15)
    await message.answer(f"🖼 *Урок по картинке*\n\n{response}", parse_mode="Markdown")

@dp.message(F.voice)
async def handle_voice(message: types.Message):
    user = await get_user(message.from_user.id)
    level = user.get("level", "A0")
    mode = user_modes.get(message.from_user.id, "voice_dialog")
    await message.answer("🎙 Обрабатываю голосовое сообщение...")
    try:
        file = await bot.get_file(message.voice.file_id)
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp_path = tmp.name
        await bot.download_file(file.file_path, tmp_path)
        text = await transcribe_voice(tmp_path)
        os.unlink(tmp_path)
        if not text:
            await message.answer("Не смог разобрать голосовое. Попробуй ещё раз! 🔄")
            return
        await message.answer(f"🗣 *Ты сказал:* _{text}_", parse_mode="Markdown")
        if mode == "translator":
            response = await ask_ai(
                [{"role": "user", "content": text}],
                level, "translator"
            )
        else:
            response = await ask_ai(
                [{"role": "user", "content": text}],
                level, "voice_dialog"
            )
        new_level = await add_xp(message.from_user.id, 20)
        await message.answer(response)
        if new_level:
            await message.answer(
                f"🎉 *Новый уровень! Ты достиг {LEVEL_NAMES[new_level]}!*",
                parse_mode="Markdown"
            )
    except Exception as e:
        logging.error(f"Voice: {e}")
        await message.answer("Что-то пошло не так с голосовым. Попробуй ещё раз! 🔄")

@dp.message(F.text)
async def handle_text(message: types.Message):
    user = await get_user(message.from_user.id)
    level = user.get("level", "A0")
    mode = user_modes.get(message.from_user.id, "dialog")
    response = await ask_ai(
        [{"role": "user", "content": message.text}],
        level, mode
    )
    new_level = await add_xp(message.from_user.id, 5)
    await message.answer(response)
    if new_level:
        await message.answer(
            f"🎉 *Новый уровень! Ты достиг {LEVEL_NAMES[new_level]}!*",
            parse_mode="Markdown"
        )

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
