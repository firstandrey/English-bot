import asyncio
import logging
import os
import tempfile
import json
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from groq import Groq
from supabase import create_client
from gtts import gTTS

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()
groq_client = Groq(api_key=GROQ_API_KEY)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

logging.basicConfig(level=logging.INFO)

LEVELS = ["A0","A1","A2","B1","B2","C1"]
LEVEL_NAMES = {
    "A0":"🥚 Абсолютный новичок","A1":"🐣 Начинающий",
    "A2":"🐥 Элементарный","B1":"🦅 Средний",
    "B2":"🦁 Выше среднего","C1":"🏆 Продвинутый"
}
XP_PER_LEVEL = {"A0":0,"A1":100,"A2":300,"B1":600,"B2":1000,"C1":1500}
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
        "dialog": f"""You are an English conversation partner. Student level: {level}.
STRICT RULES:
- Always reply in English only
- Keep conversation natural and flowing
- If student writes in Russian, respond in English and show them the English phrase
- At the end of EVERY message add: "💡 [на русском: исправление ошибки или похвала]"
- Ask one follow-up question in English to keep conversation going
- Never use Russian for the conversation itself, only for corrections""",

        "words": f"""Ты учитель английского. Уровень ученика: {level}.
Дай 5 полезных слов в формате:
🔤 Слово [транскрипция] — перевод
💡 Пример: English sentence — русский перевод
🧠 Ассоциация для запоминания
После всех слов — простое задание на практику.""",

        "lesson": f"""Ты учитель английского. Уровень ученика: {level}.
Создай увлекательный урок дня:
📖 Тема урока (на русском)
✨ 3 новых слова с переводом транскрипцией и примерами
📝 Одно грамматическое правило с примерами
🎯 Практическое задание
Объяснения на русском, примеры на английском с переводом.""",

        "translator": """You are a pure translator. Rules:
- Russian text → translate to English only
- English text → translate to Russian only
- Output ONLY the translation, nothing else
- No explanations, no notes, no comments
- Just the clean translation""",

        "voice_dialog": f"""You are an English speaking coach. Student level: {level}.
STRICT RULES:
- Reply ONLY in English, always, no exceptions
- Short natural replies (2-3 sentences max)
- This is speaking practice — stay in English no matter what
- If student writes or says something in Russian, show them the English version
- At the very end add ONE line: "💡 [по-русски: исправление если есть, или Отлично!]"
- Be warm, encouraging, keep conversation going""",

        "picture": f"""Ты учишь английскому через картинки. Уровень ученика: {level}.
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

async def text_to_speech(text):
    try:
        clean_text = text.split("💡")[0].strip()
        if not clean_text:
            clean_text = text
        tts = gTTS(text=clean_text, lang='en', slow=False)
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp_path = tmp.name
        tts.save(tmp_path)
        return tmp_path
    except Exception as e:
        logging.error(f"TTS: {e}")
        return None

# === WEB API для Mini App ===
async def handle_ai_request(request):
    try:
        data = await request.json()
        messages = data.get("messages", [])
        level = data.get("level", "A0")
        mode = data.get("mode", "dialog")
        response = await ask_ai(messages, level, mode)
        return web.Response(
            text=json.dumps({"reply": response}, ensure_ascii=False),
            content_type="application/json",
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Content-Type"
            }
        )
    except Exception as e:
        logging.error(f"API: {e}")
        return web.Response(
            text=json.dumps({"error": str(e)}),
            content_type="application/json",
            headers={"Access-Control-Allow-Origin": "*"}
        )

async def handle_options(request):
    return web.Response(
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type"
        }
    )

# === TELEGRAM HANDLERS ===
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
        f"Нажми кнопку меню внизу слева чтобы открыть приложение! 👇",
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
        "💬 *Режим свободного диалога!*\n\n"
        "Пиши по-английски на любую тему.\n"
        "Я отвечу по-английски и исправлю ошибки на русском.\n\n"
        "Try: *Hello! How was your day?*",
        parse_mode="Markdown"
    )

@dp.message(F.text == "🎙 Голосовой чат")
async def voice_chat_mode(message: types.Message):
    user_modes[message.from_user.id] = "voice_dialog"
    await message.answer(
        "🎙 *Голосовой режим включён!*\n\n"
        "Отправляй голосовые сообщения на английском.\n"
        "Я отвечу голосом на английском!\n\n"
        "Если будут ошибки — объясню на русском 💡\n\n"
        "Нажми на микрофон и говори! 🎤",
        parse_mode="Markdown"
    )

@dp.message(F.text == "🖼 Картинки")
async def picture_mode(message: types.Message):
    user_modes[message.from_user.id] = "picture"
    await message.answer(
        "🖼 *Режим обучения по картинкам!*\n\n"
        "Отправь любое фото — научу тебя английским словам!\n\n"
        "📸 Отправь фото прямо сейчас!",
        parse_mode="Markdown"
    )

@dp.message(F.text == "🔄 Переводчик")
async def translator_mode(message: types.Message):
    user_modes[message.from_user.id] = "translator"
    await message.answer(
        "🔄 *Переводчик включён!*\n\n"
        "Напиши любой текст — переведу мгновенно!\n\n"
        "🇷🇺 Русский → 🇬🇧 Английский\n"
        "🇬🇧 Английский → 🇷🇺 Русский",
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
        f"{'🏆 Отличный прогресс!' if lessons > 10 else '💪 Занимайся каждый день!'}",
        parse_mode="Markdown"
    )

@dp.message(F.text == "❓ Помощь")
async def help_cmd(message: types.Message):
    await message.answer(
        "❓ *Как пользоваться ботом*\n\n"
        "🎯 *Урок дня* — персональный урок\n"
        "📚 *Слова* — 5 новых слов с ассоциациями\n"
        "💬 *Диалог* — свободная практика английского\n"
        "🎙 *Голосовой чат* — живой разговор голосом\n"
        "🖼 *Картинки* — учи слова по фото\n"
        "🔄 *Переводчик* — мгновенный перевод\n"
        "📊 *Прогресс* — твой опыт и уровень\n\n"
        "📱 Нажми кнопку меню слева внизу для приложения!",
        parse_mode="Markdown"
    )

@dp.message(F.photo)
async def handle_photo(message: types.Message):
    user = await get_user(message.from_user.id)
    level = user.get("level", "A0")
    mode = user_modes.get(message.from_user.id, "picture")
    await message.answer("🔍 Анализирую картинку...")
    prompt = "Переведи любой текст на этом фото." if mode == "translator" else "Пользователь прислал фото для изучения английского."
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
    await message.answer("🎙 Слушаю...")
    try:
        file = await bot.get_file(message.voice.file_id)
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp_path = tmp.name
        await bot.download_file(file.file_path, tmp_path)
        text = await transcribe_voice(tmp_path)
        os.unlink(tmp_path)
        if not text:
            await message.answer("Не смог разобрать. Попробуй ещё раз! 🔄")
            return
        await message.answer(f"🗣 *Ты сказал:* _{text}_", parse_mode="Markdown")
        if mode == "translator":
            response = await ask_ai(
                [{"role": "user", "content": text}],
                level, "translator"
            )
            await message.answer(f"🔄 {response}")
        else:
            response = await ask_ai(
                [{"role": "user", "content": text}],
                level, "voice_dialog"
            )
            correction = ""
            if "💡" in response:
                parts = response.split("💡")
                english_part = parts[0].strip()
                correction = "💡" + parts[1] if len(parts) > 1 else ""
            else:
                english_part = response
            tts_path = await text_to_speech(english_part)
            if tts_path:
                audio = types.FSInputFile(tts_path)
                await bot.send_voice(message.chat.id, audio)
                os.unlink(tts_path)
                if correction:
                    await message.answer(correction)
            else:
                await message.answer(response)
        new_level = await add_xp(message.from_user.id, 20)
        if new_level:
            await message.answer(
                f"🎉 *Новый уровень! Ты достиг {LEVEL_NAMES[new_level]}!*",
                parse_mode="Markdown"
            )
    except Exception as e:
        logging.error(f"Voice: {e}")
        await message.answer("Что-то пошло не так. Попробуй ещё раз! 🔄")

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

# === ЗАПУСК ===
async def main():
    app = web.Application()
    app.router.add_post("/ai", handle_ai_request)
    app.router.add_route("OPTIONS", "/ai", handle_options)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info(f"API server started on port {port}")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
