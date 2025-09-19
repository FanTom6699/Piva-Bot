import asyncio
import logging
import sqlite3
import os
import random
import time
from datetime import timedelta
import html

from aiogram import Bot, Dispatcher, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from dotenv import load_dotenv

# --- ИМПОРТЫ ДЛЯ АНТИСПАМА ---
from typing import Callable, Dict, Any, Awaitable
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from cachetools import TTLCache

# --- Конфигурация ---
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("Не найден BOT_TOKEN. Проверьте переменные окружения (.env или настройки хостинга).")

DB_FILE = '/data/beer_game.db'
COOLDOWN_SECONDS = 3 * 60 * 60  # 3 часа
THROTTLE_TIME = 0.5 # Минимальный интервал между командами для антиспама

# --- НОВЫЕ ПАРАМЕТРЫ ШАНСОВ ---
WIN_CHANCE = 60    # Шанс на выигрыш в %
LOSE_CHANCE = 40   # Шанс на проигрыш в % (WIN_CHANCE + LOSE_CHANCE должно быть 100)
# Если вы хотите ввести ничью, можно добавить:
# DRAW_CHANCE = 10 (и тогда WIN_CHANCE + LOSE_CHANCE + DRAW_CHANCE = 100)
# Сейчас у нас только два исхода, поэтому проверяем только WIN_CHANCE, остальное - Lose

# --- File IDs для изображений ---
SUCCESS_IMAGE_ID = "AgACAgIAAxkBAAICvGjMNGhCINSBAeXyX9w0VddF-C8PAAJt8jEbFbVhSmh8gDAZrTCaAQADAgADeQADNgQ"
FAIL_IMAGE_ID = "AgACAgIAAxkBAAICwGjMNRAnAAHo1rDMPfaF_HUa0WzxaAACcvIxGxW1YUo5jEQQRkt4kgEAAwIAA3kAAzYE"
COOLDOWN_IMAGE_ID = "AgACAgIAAxkBAAICxWjMNXRNIOw6PJstVS2P6oFnW6wHAAJF-TEbLqthShzwv65k4n-MAQADAgADeQADNgQ"
TOP_IMAGE_ID = "AgACAgIAAxkBAAICw2jMNUqWi1d-ctjc67_Ryg9uLmBHAAJC-TEbLqthSiv8cCgp6EMnAQADAgADeQADNgQ"

logging.basicConfig(level=logging.INFO)

# --- АНТИСПАМ MIDDLEWARE ---
class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, throttle_time: float = 0.5):
        self.cache = TTLCache(maxsize=10_000, ttl=throttle_time)

    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any]
    ) -> Any:
        user_id = event.from_user.id
        if user_id in self.cache:
            return
        self.cache[user_id] = None
        return await handler(event, data)

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

def get_user_data(user_id: int):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT username, rating, last_beer_time FROM users WHERE user_id = ?", (user_id,))
    user_data = cursor.fetchone()
    conn.close()
    return user_data

def add_or_update_user(user_id: int, username: str):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO users (user_id, username) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET username = EXCLUDED.username",
        (user_id, username)
    )
    conn.commit()
    conn.close()

def update_user_rating_and_time(user_id: int, new_rating: int, current_time: int):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET rating = ?, last_beer_time = ? WHERE user_id = ?",
        (new_rating, current_time, user_id)
    )
    conn.commit()
    conn.close()

def get_top_users(limit: int = 10):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT username, rating FROM users ORDER BY rating DESC LIMIT ?", (limit,))
    top_users = cursor.fetchall()
    conn.close()
    return top_users

# --- Обработчики команд ---

@router.message(CommandStart())
async def cmd_start(message: Message):
    user_id = message.from_user.id
    username = html.escape(message.from_user.full_name) 

    user_data = get_user_data(user_id)
    add_or_update_user(user_id, username)

    if user_data:
        await message.answer(f"С возвращением, {username}! Рады снова видеть тебя в баре. 🍻")
    else:
         await message.answer(
            f"Добро пожаловать в бар, {username}! 🍻\n\n"
            "Здесь мы соревнуемся, кто больше выпьет пива.\n"
            "Используй команду /beer, чтобы испытать удачу!\n"
            "Проверить свой профиль: /profile\n"
            "Посмотреть на лучших: /top\n"
            "Нужна помощь? /help"
        )

@router.message(Command("profile"))
async def cmd_profile(message: Message):
    user_id = message.from_user.id
    user_data = get_user_data(user_id)
    
    if user_data:
        username, rating, _ = user_data
        await message.answer(
            f"👤 <b>Твой профиль:</b>\n\n"
            f"Имя: <b>{username}</b>\n"
            f"Рейтинг: <b>{rating}</b> 🍺",
            parse_mode="HTML"
        )
    else:
        await message.answer("Ты еще не зарегистрирован. Нажми /start, чтобы начать игру.")

@router.message(Command("beer"))
async def cmd_beer(message: Message):
    user_id = message.from_user.id
    current_time = int(time.time())

    user_data = get_user_data(user_id)

    if not user_data:
        await message.answer("Сначала зарегистрируйся с помощью команды /start.")
        return

    _, rating, last_beer_time = user_data

    time_passed = current_time - last_beer_time
    if time_passed < COOLDOWN_SECONDS:
        time_left = COOLDOWN_SECONDS - time_passed
        time_left_formatted = str(timedelta(seconds=time_left))
        await message.answer_photo(
            photo=COOLDOWN_IMAGE_ID,
            caption=f"Ты уже недавно пил! ⏳\nПопробуй снова через: <b>{time_left_formatted}</b>",
            parse_mode="HTML"
        )
        return

    # Определяем исход на основе заданных процентов
    roll = random.randint(1, 100) # Генерируем число от 1 до 100
    
    rating_change_amount = random.randint(1, 10) # Сколько пива получим/потеряем

    if roll <= WIN_CHANCE: # Если выпавшее число меньше или равно шансу выигрыша
        # Успех
        new_rating = rating + rating_change_amount
        await message.answer_photo(
            photo=SUCCESS_IMAGE_ID,
            caption=f"😏🍻 Ты успешно бахнул на <b>+{rating_change_amount}</b> 🍺 пива!",
            parse_mode="HTML"
        )
    else:
        # Неудача (выпавшее число больше WIN_CHANCE)
        # Убедимся, что рейтинг не опустится ниже нуля
        potential_new_rating = rating - rating_change_amount
        new_rating = max(0, potential_new_rating) 

        caption_message = ""
        if potential_new_rating < 0:
            actual_loss = rating # Сколько пива реально отняли до 0
            caption_message = f"🤬🍻 Братья Уизли отжали у тебя все <b>{rating}</b> 🍺 пива! Ты на нуле..."
        else:
            actual_loss = rating_change_amount
            caption_message = f"🤬🍻 Братья Уизли отжали у тебя <b>{actual_loss}</b> 🍺 пива!"

        await message.answer_photo(
            photo=FAIL_IMAGE_ID,
            caption=caption_message,
            parse_mode="HTML"
        )
    
    update_user_rating_and_time(user_id, new_rating, current_time)

@router.message(Command("top"))
async def cmd_top(message: Message):
    top_users = get_top_users()

    if not top_users:
        await message.answer("В баре пока никого нет, ты можешь стать первым! 🍻")
        return

    response_text = "🏆 <b>Топ-10 лучших пивохлёбов:</b>\n\n"
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    
    for i, (username, rating) in enumerate(top_users, 1):
        place_icon = medals.get(i, f"<b>{i}.</b>")
        response_text += f"{place_icon} {username} — <b>{rating}</b> 🍺\n"
        
    await message.answer_photo(
        photo=TOP_IMAGE_ID,
        caption=response_text,
        parse_mode="HTML"
    )

@router.message(Command("help"))
async def cmd_help(message: Message):
    help_text = (
        "<b>🍻 Правила Игры в Пивном Баре 🍻</b>\n\n"
        "Это простая игра, где ты соревнуешься за самый высокий пивной рейтинг!\n\n"
        "<b>Основные команды:</b>\n"
        "/start - Начать игру и зарегистрироваться (или просто обновить свой профиль)\n"
        "/beer - Испытать удачу и получить (или потерять) пивной рейтинг. Кулдаун: 3 часа.\n"
        "/profile - Посмотреть свой текущий рейтинг\n"
        "/top - Увидеть 10 лучших игроков\n"
        "/help - Показать это сообщение"
    )
    await message.answer(help_text, parse_mode="HTML")

async def main():
    init_db()
    
    router.message.middleware(ThrottlingMiddleware(throttle_time=THROTTLE_TIME))
    
    dp.include_router(router)
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
