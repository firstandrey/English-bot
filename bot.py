import asyncio
import logging
import os
import tempfile
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, FSInputFile
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
    "A0": "🥚 Absolute Beginner",
    "A1": "🐣 Beginner",
    "A2": "🐥 Elementary",
    "B1": "🦅 Intermediate",
    "B2": "🦁 Upper-Intermediate",
    "C1": "🏆 Advanced"
}

XP_PER_LEVEL = {
    "A0": 0, "A1": 100, "A2": 300, "B1": 600, "B2": 1000, "C1": 1500
}

user_modes = {}

def main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📚 Words"), KeyboardButton(text="💬 Dialog")],
            [KeyboardButton(text="🖼 Pictures"), KeyboardButton(text="🎙 Voice chat")],
            [KeyboardButton(text="🔄 Translator"), KeyboardButton(text="📊 Progress")],
            [KeyboardButton(text="🎯 Lesson"), KeyboardButton(text="❓ Help")]
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
        supabase.table("users").update({"xp": new_xp}).eq("telegram_id", user_id).execute()
    except Exception as e:
        logging.error(f"XP: {e}")
    return None

async def ask_ai(messages, level="A0", mode="dialog"):
    prompts = {
        "dialog": f"""You are an English tutor. Student level: {level}.
Rules:
- Respond only in English
- If level A0-A1: use very simple words, short sentences
- If level A2+: use natural English
- Always correct mistakes gently at the end of your reply like this: "💡 Correction: [mistake] → [correct form]"
- Ask one follow-up question to keep conversation going
- Be friendly and encouraging""",

        "words": f"""You are an English vocabulary teacher. Student level: {level}.
Give 5 useful words with:
🔤 word [transcription]
🇷🇺 translation
💡 Example sentence
🧠 Memory tip (association or image)
End with a simple practice task.""",

        "lesson": f"""You are an English teacher. Student level: {level}.
Create a short engaging lesson:
📖 Topic
✨ 3 new words with examples
📝 One grammar rule with examples
🎯 Quick practice exercise
Keep it fun and under 10 sentences total.""",

        "translator": f"""You are a translator. 
Translate the given text to English if it's in Russian, or to Russian if it's in English.
Format:
🔄 Translation: [result]
📝 Notes: [brief grammar or usage note if helpful]""",

        "voice_dialog": f"""You are having a real spoken English conversation. Student level: {level}.
- Respond naturally as in real conversation
- Keep responses short (2-3 sentences max)
- At the end add: "💡 [one tip or correction if needed]"
- Be warm and encouraging""",

        "picture": f"""You are teaching English through images. Student level: {level}.
Create an image-based lesson:
🖼 Describe what's typically in this type of scene (5-7 items)
📚 Key vocabulary with translations
🧠 Memory associations for each word
💬 2 example sentences
❓ One question about the image in English"""
    }

    system = prompts.get(mode, prompts["dialog"])
    try:
        r = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "system", "content": system}] + messages,
            max_tokens=600,
            temperature=0.7
        )
        return r.choices[0].message.content
    except Exception as e:
        logging.error(f"Groq: {e}")
        return "Sorry, something went wrong. Please try again! 🔄"

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
    user = await get_user(message.from_user.id,
                          message.from_user.username or "",
                          message.from_user.full_name or "")
    level = user.get("level", "A0")
    level_name = LEVEL_NAMES.get(level, level)
    await message.answer(
        f"👋 Hello, {message.from_user.first_name}!\n\n"
        f"I'm your personal English AI tutor 🇬🇧\n\n"
        f"In 30 days you will:\n"
        f"✅ Understand English speech\n"
        f"✅ Have real conversations\n"
        f"✅ Read and write confidently\n\n"
        f"Your level: {level_name}\n"
        f"Just 30-60 min a day!\n\n"
        f"Choose what to do 👇",
        reply_markup=main_menu()
    )

@dp.message(F.text == "🎯 Lesson")
async def daily_lesson(message: types.Message):
    user = await get_user(message.from_user.id)
    level = user.get("level", "A0")
    lessons = user.get("lessons_done", 0)
    response = await ask_ai(
        [{"role": "user", "content": f"Create lesson number {lessons+1}"}],
        level, "lesson"
    )
    try:
        supabase.table("users").update(
            {"lessons_done": lessons+1}
        ).eq("telegram_id", message.from_user.id).execute()
    except:
        pass
    new_level = await add_xp(message.from_user.id, 20)
    text = f"📖 *Lesson #{lessons+1}*\n\n{response}"
    if new_level:
        text += f"\n\n🎉 *Level up! You reached {LEVEL_NAMES[new_level]}!*"
    await message.answer(text, parse_mode="Markdown")

@dp.message(F.text == "📚 Words")
async def learn_words(message: types.Message):
    user = await get_user(message.from_user.id)
    level = user.get("level", "A0")
    response = await ask_ai(
        [{"role": "user", "content": "Give me 5 useful words"}],
        level, "words"
    )
    await add_xp(message.from_user.id, 10)
    await message.answer(f"📚 *New Words*\n\n{response}", parse_mode="Markdown")

@dp.message(F.text == "💬 Dialog")
async def start_dialog(message: types.Message):
    user_modes[message.from_user.id] = "dialog"
    await message.answer(
        "💬 *Dialog mode*\n\n"
        "Write anything in English — I'll reply, correct mistakes and help you improve!\n\n"
        "Try: *Hello! How are you?*",
        parse_mode="Markdown"
    )

@dp.message(F.text == "🎙 Voice chat")
async def voice_chat_mode(message: types.Message):
    user_modes[message.from_user.id] = "voice_dialog"
    await message.answer(
        "🎙 *Voice chat mode*\n\n"
        "Send voice messages in English — I'll understand you and reply!\n\n"
        "I'll also point out any mistakes to help you improve 💪\n\n"
        "Go ahead, say something! 🎤",
        parse_mode="Markdown"
    )

@dp.message(F.text == "🖼 Pictures")
async def picture_mode(message: types.Message):
    user_modes[message.from_user.id] = "picture"
    await message.answer(
        "🖼 *Picture mode*\n\n"
        "Send any photo — I'll teach you English words and associations based on it!\n\n"
        "📸 Send your photo now!",
        parse_mode="Markdown"
    )

@dp.message(F.text == "🔄 Translator")
async def translator_mode(message: types.Message):
    user_modes[message.from_user.id] = "translator"
    await message.answer(
        "🔄 *Translator mode*\n\n"
        "Send text, photo or voice — I'll translate it!\n\n"
        "🇷🇺 Russian → 🇬🇧 English\n"
        "🇬🇧 English → 🇷🇺 Russian\n\n"
        "Type or send something now!",
        parse_mode="Markdown"
    )

@dp.message(F.text == "📊 Progress")
async def show_progress(message: types.Message):
    user = await get_user(message.from_user.id)
    level = user.get("level", "A0")
    xp = user.get("xp", 0)
    streak = user.get("streak", 0)
    lessons = user.get("lessons_done", 0)
    level_name = LEVEL_NAMES.get(level, level)
    idx = LEVELS.index(level) if level in LEVELS else 0
    filled = "🟩" * (idx + 1)
    empty = "⬜" * (5 - idx)
    bar = filled + empty
    if idx < len(LEVELS) - 1:
        next_level = LEVELS[idx + 1]
        needed = XP_PER_LEVEL[next_level] - xp
        next_info = f"📈 {needed} XP to {LEVEL_NAMES[next_level]}"
    else:
        next_info = "🏆 Maximum level reached!"
    await message.answer(
        f"📊 *Your Progress*\n\n"
        f"🎯 Level: {level_name}\n"
        f"{bar}\n\n"
        f"⭐ XP: {xp}\n"
        f"{next_info}\n\n"
        f"🔥 Streak: {streak} days\n"
        f"📖 Lessons done: {lessons}\n\n"
        f"{'🏆 Amazing progress!' if lessons > 10 else '💪 Keep going every day!'}",
        parse_mode="Markdown"
    )

@dp.message(F.text == "❓ Help")
async def help_cmd(message: types.Message):
    await message.answer(
        "❓ *How to use the bot*\n\n"
        "🎯 *Lesson* — daily lesson for your level\n"
        "📚 *Words* — 5 new words with associations\n"
        "💬 *Dialog* — chat with AI, get corrections\n"
        "🎙 *Voice chat* — speak English, AI replies\n"
        "🖼 *Pictures* — learn words from photos\n"
        "🔄 *Translator* — text, photo or voice\n"
        "📊 *Progress* — your XP and level\n\n"
        "💡 *Tips:*\n"
        "• Practice every day\n"
        "• Don't be afraid to make mistakes\n"
        "• Use voice mode for speaking practice\n"
        "• Send photos to learn new vocabulary",
        parse_mode="Markdown"
    )

@dp.message(F.photo)
async def handle_photo(message: types.Message):
    user = await get_user(message.from_user.id)
    level = user.get("level", "A0")
    mode = user_modes.get(message.from_user.id, "picture")
    if mode == "translator":
        prompt = "The user sent a photo with text. Please translate any text you see, or describe what to translate."
    else:
        prompt = "User sent a photo for English learning."
    response = await ask_ai(
        [{"role": "user", "content": prompt}],
        level, mode if mode in ["translator", "picture"] else "picture"
    )
    await add_xp(message.from_user.id, 15)
    await message.answer(
        f"🖼 *Picture lesson*\n\n{response}",
        parse_mode="Markdown"
    )

@dp.message(F.voice)
async def handle_voice(message: types.Message):
    user = await get_user(message.from_user.id)
    level = user.get("level", "A0")
    mode = user_modes.get(message.from_user.id, "voice_dialog")
    await message.answer("🎙 Processing your voice message...")
    try:
        file = await bot.get_file(message.voice.file_id)
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp_path = tmp.name
        await bot.download_file(file.file_path, tmp_path)
        text = await transcribe_voice(tmp_path)
        os.unlink(tmp_path)
        if not text:
            await message.answer("Sorry, I couldn't understand the audio. Please try again! 🔄")
            return
        await message.answer(f"🗣 *You said:* _{text}_", parse_mode="Markdown")
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
        await add_xp(message.from_user.id, 20)
        new_level = await add_xp(message.from_user.id, 0)
        await message.answer(response)
        if new_level:
            await message.answer(f"🎉 *Level up! You reached {LEVEL_NAMES[new_level]}!*", parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Voice: {e}")
        await message.answer("Something went wrong with voice processing. Try again! 🔄")

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
            f"🎉 *Level up! You reached {LEVEL_NAMES[new_level]}!*",
            parse_mode="Markdown"
        )

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
