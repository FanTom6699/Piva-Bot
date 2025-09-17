import aiosqlite
import logging

from config import DATABASE_NAME

logger = logging.getLogger(__name__)

async def init_db():
    """Создание базы данных и таблицы, если они не существуют."""
    try:
        async with aiosqlite.connect(DATABASE_NAME) as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    rating INTEGER DEFAULT 0,
                    last_beer_time INTEGER DEFAULT 0
                )
            ''')
            await db.commit()
        logger.info("Database initialized successfully.")
    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        raise # Перевыбрасываем ошибку, чтобы бот не запустился без БД

async def get_user(user_id):
    """Получение данных пользователя из БД."""
    try:
        async with aiosqlite.connect(DATABASE_NAME) as db:
            cursor = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            user = await cursor.fetchone()
            return user
    except Exception as e:
        logger.error(f"Error getting user {user_id}: {e}")
        return None

async def add_new_user(user_id, username):
    """Добавление нового пользователя в БД."""
    try:
        async with aiosqlite.connect(DATABASE_NAME) as db:
            await db.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, username))
            await db.commit()
            logger.info(f"User {user_id} added or already exists.")
    except Exception as e:
        logger.error(f"Error adding new user {user_id}: {e}")

async def update_user_data(user_id, new_rating, new_time):
    """Обновление рейтинга и времени последнего использования команды."""
    try:
        async with aiosqlite.connect(DATABASE_NAME) as db:
            await db.execute("UPDATE users SET rating = ?, last_beer_time = ? WHERE user_id = ?", (new_rating, new_time, user_id))
            await db.commit()
            logger.info(f"User {user_id} data updated.")
    except Exception as e:
        logger.error(f"Error updating user {user_id} data: {e}")

async def get_top_users():
    """Получение топ-10 пользователей по рейтингу."""
    try:
        async with aiosqlite.connect(DATABASE_NAME) as db:
            cursor = await db.execute("SELECT username, rating FROM users ORDER BY rating DESC LIMIT 10")
            top_users = await cursor.fetchall()
            return top_users
    except Exception as e:
        logger.error(f"Error getting top users: {e}")
        return []
