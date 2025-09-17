import logging
import os
import random
import time
from aiogram import Bot, Dispatcher, executor, types
from dotenv import load_dotenv
from database import init_db

# Логирование
logging.basicConfig(level=logging.INFO)

# Загружаем токен
load_dotenv()
BOT_TOKEN = os.getenv("6711143584:AAGDrBrQek_q4X2s_iONkQmEafuk-b6SkrM")

if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не найден! Укажи его в .env")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)

# БД
conn = init_db()
cur = conn.cursor()

COOLDOWN = 3 * 60 * 60  # 3 часа в секундах

# /start
@dp.message_handler(commands=["start"])
async def start_command(message: types.Message):
    telegram_id = str(message.from_user.id)
    username = message.from_user.username or message.from_user.first_name

    cur.execute("SELECT * FROM players WHERE telegram_id = ?", (telegram_id,))
    player = cur.fetchone()

    if not player:
        cur.execute("INSERT INTO players (telegram_id, username) VALUES (?, ?)", (telegram_id, username))
        conn.commit()
        await message.answer(f"👋 Привет, {username}!\nТы зарегистрирован.")
    else:
        await message.answer(f"👋 С возвращением, {username}! Ты уже есть в базе.")

# /beer
@dp.message_handler(commands=["beer"])
async def beer_command(message: types.Message):
    telegram_id = str(message.from_user.id)
    username = message.from_user.username or message.from_user.first_name

    cur.execute("SELECT beer_points, last_beer FROM players WHERE telegram_id = ?", (telegram_id,))
    player = cur.fetchone()

    if not player:
        await message.answer("❌ Сначала напиши /start, чтобы зарегистрироваться.")
        return

    beer_points, last_beer = player
    now = int(time.time())

    # проверка кулдауна
    if now - last_beer < COOLDOWN:
        remaining = COOLDOWN - (now - last_beer)
        h = remaining // 3600
        m = (remaining % 3600) // 60
        s = remaining % 60
        await message.answer(f"⌛ Ты уже пил недавно! Попробуй снова через {h:02d}:{m:02d}:{s:02d}.")
        return

    # определяем плюс или минус
    if random.choice([True, False]):
        change = random.randint(1, 10)
        text = f"😏🍻 Ты успешно бахнул!\nСливочное пиво: **+{change}**"
    else:
        change = -random.randint(1, 10)
        text = f"🤬🍻 Братья Уизли отжали твоё пиво!\nСливочное пиво: **{change}**"

    beer_points += change
    cur.execute("UPDATE players SET beer_points = ?, last_beer = ? WHERE telegram_id = ?", (beer_points, now, telegram_id))
    conn.commit()

    await message.answer(f"{text}\n\n🏆 Твой счёт: {beer_points}")

# /top
@dp.message_handler(commands=["top"])
async def top_command(message: types.Message):
    cur.execute("SELECT username, beer_points FROM players ORDER BY beer_points DESC LIMIT 10")
    top_players = cur.fetchall()

    if not top_players:
        await message.answer("❌ Пока нет игроков в рейтинге.")
        return

    text = "🏆 Топ-10 любителей пива:\n\n"
    for i, (username, points) in enumerate(top_players, start=1):
        name = username or "Безымянный"
        text += f"{i}. {name} — {points} очков\n"

    await message.answer(text)

if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
