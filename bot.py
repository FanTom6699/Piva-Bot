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
load_dotenv()  # Загружаем переменные из .env файла для локального запуска
BOT_TOKEN = os.getenv("6711143584:AAGDrBrQek_q4X2s_iONkQmEafuk-b6SkrM")
DB_FILE = 'beer_game.db'
COOLDOWN_SECONDS = 3 * 60 * 60  # 3 часа

# Настройка логирования для отладки
logging.basicConfig(level=logging.INFO)

# --- Инициализация ---
# Создаем объекты роутера и диспетчера
router = Router()
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- Управление базой данных ---

def init_db():
    """Инициализирует базу данных и создает таблицу, если её нет."""
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

# --- Обработчики команд ---

@router.message(CommandStart())
async def cmd_start(message: Message):
    """Обработчик команды /start. Регистрирует нового пользователя."""
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
            "Здесь мы соревнуемся, кто больше выпьет пива.\n"
            "Используй команду /beer, чтобы испытать удачу!\n"
            "Проверить свой профиль: /profile\n"
            "Посмотреть на лучших: /top"
        )
    else:
        await message.answer(f"С возвращением, {username}! Рады снова видеть тебя в баре. 🍻")

    conn.close()


@router.message(Command("profile"))
async def cmd_profile(message: Message):
    """Обработчик команды /profile. Показывает профиль пользователя."""
    user_id = message.from_user.id
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute("SELECT username, rating FROM users WHERE user_id = ?", (user_id,))
    user_data = cursor.fetchone()
    
    conn.close()
    
    if user_data:
        username, rating = user_data
        await message.answer(
            f"👤 **Твой профиль:**\n\n"
            f"Имя: **{username}**\n"
            f"Рейтинг: **{rating}** 🍺"
        )
    else:
        await message.answer("Ты еще не зарегистрирован. Нажми /start, чтобы начать игру.")


@router.message(Command("beer"))
async def cmd_beer(message: Message):
    """Обработчик команды /beer. Основная игровая механика."""
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
        await message.answer(f"Ты уже недавно пил! ⏳\nПопробуй снова через: **{time_left_formatted}**")
        conn.close()
        return

    # 50/50 шанс на успех или неудачу
    if random.choice([True, False]):
        # Успех
        rating_change = random.randint(1, 10)
        new_rating = rating + rating_change
        await message.answer(f"😏🍻 Ты успешно бахнул! Твой рейтинг увеличен на **+{rating_change}**.")
    else:
        # Неудача
        rating_change = -random.randint(1, 10)
        new_rating = rating + rating_change
        await message.answer(f"🤬🍻 Братья Уизли отжали твоё пиво! Твой рейтинг уменьшен на **{rating_change}**.")
    
    cursor.execute(
        "UPDATE users SET rating = ?, last_beer_time = ? WHERE user_id = ?",
        (new_rating, current_time, user_id)
    )
    conn.commit()
    conn.close()


@router.message(Command("top"))
async def cmd_top(message: Message):
    """Обработчик команды /top. Показывает топ-10 игроков."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute("SELECT username, rating FROM users ORDER BY rating DESC LIMIT 10")
    top_users = cursor.fetchall()
    conn.close()

    if not top_users:
        await message.answer("В баре пока никого нет, ты можешь стать первым! 썰")
        return

    response_text = "🏆 **Топ-10 лучших пивохлёбов:**\n\n"
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    
    for i, (username, rating) in enumerate(top_users, 1):
        place_icon = medals.get(i, f"**{i}.**")
        response_text += f"{place_icon} {username} — **{rating}** 🍺\n"
        
    await message.answer(response_text)


async def main():
    """Главная функция для запуска бота."""
    init_db()  # Убедимся, что БД и таблицы созданы
    dp.include_router(router)
    await dp.start_polling(bot)


if __name__ == '__main__':
    asyncio.run(main())
