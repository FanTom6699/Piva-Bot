import asyncio
import logging
import sqlite3
import os
import random
import time
from datetime import timedelta

from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from dotenv import load_dotenv

# --- Конфигурация ---
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("Не найден BOT_TOKEN. Проверьте переменные окружения.")

DB_FILE = 'beer_game.db'
COOLDOWN_SECONDS = 3 * 60 * 60

# --- File IDs для изображений (ВАЖНО: ЗАМЕНИТЕ ЭТИ ЗНАЧЕНИЯ!) ---
# Получите эти ID, отправив картинки @RawDataBot или похожему боту
SUCCESS_IMAGE_ID = "AgACAgIAAxkBAAE7RhNoy3mtHS_htKXAn3IbDwWd-h2lYQACbfIxGxW1YUq0_SzDnrjbjwEAAwIAA3kAAzYE"       # Картинка для успешного "бахнул!"
FAIL_IMAGE_ID = "AgACAgIAAxkBAAE7RhZoy3o_4reUDml6pZHO9UhL0HNEgwACcvIxGxW1YUp50kRQuOHYXQEAAwIAA3kAAzYE"         # Картинка для неудачного "отжали пиво!"
COOLDOWN_IMAGE_ID = "AgACAgIAAxkBAAE7TUBozC13Ufm8h-FaqtfXmDf-Q2wk_gACRfkxGy6rYUq-T0t5tZO1rAEAAwIAA3kAAzYE"    # Картинка для сообщения о кулдауне
TOP_IMAGE_ID = "AgACAgIAAxkBAAE7TTpozC1YlSg_3GxjdtRYJBZZIicJ_gACQvkxGy6rYUoZ8xwiFk0lVwEAAwIAA3kAAzYE"         # Картинка для топа игроков


logging.basicConfig(level=logging.INFO)

router = Router()
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- Управление базой данных ---

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT NOT NULL,
            rating INTEGER DEFAULT 0,
            last_beer_time INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()
    logging.info("База данных успешно инициализирована.")

# --- ВРЕМЕННАЯ КОМАНДА ДЛЯ ПОЛУЧЕНИЯ FILE ID ---
# После того как получите все ID, этот блок можно удалить
@router.message(Command("getid"))
async def cmd_getid(message: Message):
    await message.reply("Отправьте мне фото, чтобы получить его File ID.")

@router.message(F.photo)
async def photo_handler(message: Message):
    photo_id = message.photo[-1].file_id
    await message.reply(f"File ID этого фото:\n`{photo_id}`")
# --- КОНЕЦ ВРЕМЕННОГО БЛОКА ---


@router.message(CommandStart())
async def cmd_start(message: Message):
    user_id = message.from_user.id
    username = message.from_user.full_name
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    user_exists = cursor.fetchone()
    if not user_exists:
        cursor.execute(
            "INSERT INTO users (user_id, username, rating, last_beer_time) VALUES (?, ?, ?, ?)",
            (user_id, username, 0, 0)
        )
        conn.commit()
        await message.answer(
            f"Добро пожаловать в бар, {username}! 🍻\n\n"
            "Используй команду /beer, чтобы испытать удачу!"
        )
    else:
        await message.answer(f"С возвращением, {username}! 🍻")
    conn.close()


@router.message(Command("profile"))
async def cmd_profile(message: Message):
    user_id = message.from_user.id
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT username, rating FROM users WHERE user_id = ?", (user_id,))
    user_data = cursor.fetchone()
    conn.close()
    if user_data:
        username, rating = user_data
        await message.answer(
            f"👤 <b>Твой профиль:</b>\n\n"
            f"Имя: <b>{username}</b>\n"
            f"Рейтинг: <b>{rating}</b> 🍺",
            parse_mode="HTML"
        )
    else:
        await message.answer("Ты еще не зарегистрирован. Нажми /start.")


@router.message(Command("beer"))
async def cmd_beer(message: Message):
    user_id = message.from_user.id
    current_time = int(time.time())
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT rating, last_beer_time FROM users WHERE user_id = ?", (user_id,))
    user_data = cursor.fetchone()

    if not user_data:
        conn.close()
        await message.answer("Сначала зарегистрируйся с помощью команды /start.")
        return

    rating, last_beer_time = user_data
    time_passed = current_time - last_beer_time
    if time_passed < COOLDOWN_SECONDS:
        time_left = COOLDOWN_SECONDS - time_passed
        time_left_formatted = str(timedelta(seconds=time_left))
        await message.answer_photo(
            photo=COOLDOWN_IMAGE_ID,
            caption=f"Ты уже недавно пил! ⏳\nПопробуй снова через: <b>{time_left_formatted}</b>",
            parse_mode="HTML"
        )
        conn.close()
        return

    if random.choice([True, False]):
        rating_change = random.randint(1, 10)
        new_rating = rating + rating_change
        await message.answer_photo(
            photo=SUCCESS_IMAGE_ID,
            caption=f"😏🍻 Ты успешно бахнул на <b>+{rating_change}</b> 🍺 пива!",
            parse_mode="HTML"
        )
    else:
        rating_change = -random.randint(1, 10)
        new_rating = rating + rating_change
        await message.answer_photo(
            photo=FAIL_IMAGE_ID,
            caption=f"🤬🍻 Братья Уизли отжали у тебя <b>{rating_change}</b> 🍺 пива!",
            parse_mode="HTML"
        )
    
    cursor.execute(
        "UPDATE users SET rating = ?, last_beer_time = ? WHERE user_id = ?",
        (new_rating, current_time, user_id)
    )
    conn.commit()
    conn.close()


@router.message(Command("top"))
async def cmd_top(message: Message):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT username, rating FROM users ORDER BY rating DESC LIMIT 10")
    top_users = cursor.fetchall()
    conn.close()

    if not top_users:
        await message.answer("В баре пока никого нет, ты можешь стать первым! 🍻")
        return

    response_text = "🏆 <b>Топ-10 лучших пивохлёбов:</b>\n\n"
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    
    for i, (username, rating) in enumerate(top_users, 1):
        place_icon = medals.get(i, f"<b>{i}.</b>")
        # ИСПРАВЛЕНИЕ ЗДЕСЬ:
        response_text += f"{place_icon} {username} — <b>{rating}</b> 🍺\n"
        
    await message.answer_photo(
        photo=TOP_IMAGE_ID,
        caption=response_text,
        parse_mode="HTML"
    )


async def main():
    init_db()
    dp.include_router(router)
    await dp.start_polling(bot)


if __name__ == '__main__':
    asyncio.run(main())
