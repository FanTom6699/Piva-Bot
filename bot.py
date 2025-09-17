import logging
import os
import random
import sqlite3
import time

from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher.filters.builtin import CommandStart

# Конфигурация
TOKEN = os.getenv('6711143584:AAGDrBrQek_q4X2s_iONkQmEafuk-b6SkrM')
DATABASE_NAME = 'beer_bot.db'
BEER_COOLDOWN = 3 * 60 * 60 # 3 часа в секундах
RATING_CHANGE = 10 # Максимальное изменение рейтинга

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Инициализация бота и диспетчера
bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# --- Работа с базой данных ---

def init_db():
    """Создание базы данных и таблицы, если они не существуют."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            rating INTEGER DEFAULT 0,
            last_beer_time INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()

def get_user(user_id):
    """Получение данных пользователя из БД."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    # Используем параметризованный запрос для безопасности
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    conn.close()
    return user

def add_new_user(user_id, username):
    """Добавление нового пользователя в БД."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO users (user_id, username) VALUES (?, ?)", (user_id, username))
        conn.commit()
    except sqlite3.IntegrityError:
        pass # Пользователь уже существует
    conn.close()

def update_user_data(user_id, new_rating, new_time):
    """Обновление рейтинга и времени последнего использования команды."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET rating = ?, last_beer_time = ? WHERE user_id = ?", (new_rating, new_time, user_id))
    conn.commit()
    conn.close()

def get_top_users():
    """Получение топ-10 пользователей по рейтингу."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT username, rating FROM users ORDER BY rating DESC LIMIT 10")
    top_users = cursor.fetchall()
    conn.close()
    return top_users

# --- Обработчики команд ---

@dp.message_handler(CommandStart())
async def cmd_start(message: types.Message):
    """Обработчик команды /start."""
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.full_name
    add_new_user(user_id, username)
    await message.reply(
        "Привет! Я твой Пиво-бот. Набери /beer, чтобы попытать удачу, или /top, чтобы увидеть лучших игроков!"
    )

@dp.message_handler(commands=['beer'])
async def cmd_beer(message: types.Message):
    """Обработчик команды /beer."""
    user_id = message.from_user.id
    user = get_user(user_id)

    if not user:
        add_new_user(user_id, message.from_user.username or message.from_user.full_name)
        user = get_user(user_id)

    _, _, current_rating, last_beer_time = user
    current_time = int(time.time())
    
    if current_time - last_beer_time < BEER_COOLDOWN:
        remaining_time = BEER_COOLDOWN - (current_time - last_beer_time)
        hours = remaining_time // 3600
        minutes = (remaining_time % 3600) // 60
        await message.reply(
            f"🤬🍻 Ты уже бахнул пива! Следующую попытку можно сделать через {hours} ч. {minutes} мин."
        )
    else:
        change = random.randint(1, RATING_CHANGE)
        if random.choice([True, False]): # 50% шанс на успех
            new_rating = current_rating + change
            response = f"😏🍻 Ты успешно бахнул! Твой рейтинг вырос на +{change}. Текущий рейтинг: {new_rating}."
        else:
            new_rating = current_rating - change
            response = f"🤬🍻 Братья Уизли отжали твоё пиво! Твой рейтинг упал на -{change}. Текущий рейтинг: {new_rating}."

        update_user_data(user_id, new_rating, current_time)
        await message.reply(response)

@dp.message_handler(commands=['top'])
async def cmd_top(message: types.Message):
    """Обработчик команды /top."""
    top_users = get_top_users()
    if not top_users:
        await message.reply("Список игроков пока пуст.")
        return

    top_list = "🏆 **Топ-10 самых крутых пивных богов:** 🏆\n\n"
    for i, user in enumerate(top_users, 1):
        username, rating = user
        top_list += f"{i}. {username} — {rating} 🍻\n"

    await message.reply(top_list, parse_mode='Markdown')

# --- Запуск бота ---

if __name__ == '__main__':
    # Инициализация базы данных при запуске
    init_db()
    from aiogram import executor
    executor.start_polling(dp, skip_updates=True)
