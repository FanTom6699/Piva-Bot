# database.py
import aiosqlite
import logging
from datetime import datetime
# --- ДОБАВЛЯЕМ 'config' для ADMIN_ID при инициализации ---
import config 

class Database:
    def __init__(self, db_name="bot_database.db"): # (Используем твое имя БД)
        self.db_name = db_name
        logging.info(f"База данных {db_name} инициализирована.")

    # --- Твой 'initialize' (ранее 'init_db') ---
    async def initialize(self):
        """Создает таблицы, если они не существуют."""
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    first_name TEXT,
                    last_name TEXT,
                    username TEXT,
                    beer_rating INTEGER DEFAULT 0,
                    last_beer_time TIMESTAMP,
                    registration_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_admin INTEGER DEFAULT 0 
                );
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS chats (
                    chat_id INTEGER PRIMARY KEY,
                    title TEXT
                );
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS bot_settings (
                    key TEXT PRIMARY KEY,
                    value INTEGER
                );
            """)
            # (Я убрал таблицы Рейдов, так как новая логика 
            # (handlers/game_raid.py) их не использует, 
            # она хранит рейды в памяти (в active_raids).
            # Это упрощает код.)

            # Убедимся, что джекпот существует
            await db.execute("INSERT OR IGNORE INTO bot_settings (key, value) VALUES ('jackpot', 0)")
            
            # --- Добавляем админа при инициализации ---
            await db.execute(
                "INSERT OR IGNORE INTO users (user_id, first_name, last_name, username, is_admin) VALUES (?, ?, ?, ?, ?)",
                (config.ADMIN_ID, 'Admin', 'Bot', 'N/A', 1)
            )
            
            await db.commit()
            logging.info("Таблицы базы данных проверены и созданы (если отсутствовали).")

    # --- Управление Настройками ---
    async def get_all_settings(self):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT key, value FROM bot_settings")
            return await cursor.fetchall()

    async def get_setting(self, key):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT value FROM bot_settings WHERE key = ?", (key,))
            row = await cursor.fetchone()
            return row[0] if row else None

    async def update_setting(self, key, value):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("INSERT OR REPLACE INTO bot_settings (key, value) VALUES (?, ?)", (key, value))
            await db.commit()

    # --- Управление Пользователями ---
    async def user_exists(self, user_id):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,))
            return await cursor.fetchone() is not None

    async def add_user(self, user_id, first_name, last_name, username):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                "INSERT INTO users (user_id, first_name, last_name, username, last_beer_time) VALUES (?, ?, ?, ?, ?)",
                (user_id, first_name, last_name, username, datetime(2000, 1, 1).isoformat()) # Сохраняем как строку
            )
            await db.commit()
            
    # --- Проверка админа (нужна для admin.py) ---
    async def is_admin(self, user_id):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT is_admin FROM users WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            return row[0] == 1 if row else False

    async def get_total_users(self): # (Твой admin.py использует 'get_total_users')
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT COUNT(user_id) FROM users")
            row = await cursor.fetchone()
            return row[0] if row else 0
            
    # --- Управление Пивом и Рейтингом ---
    async def get_user_beer_rating(self, user_id):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT beer_rating FROM users WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            return row[0] if row else 0

    # (Это 'get_last_beer_time' из твоего файла, он корректен)
    async def get_last_beer_time(self, user_id):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT last_beer_time FROM users WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            if row and row[0]:
                try:
                    # Конвертируем строку ISO (как мы сохраняем) в datetime
                    return datetime.fromisoformat(row[0])
                except (ValueError, TypeError):
                     return datetime(2000, 1, 1)
            return datetime(2000, 1, 1) # (Возвращаем старую дату, если None, чтобы избежать ошибок)

    # --- ЭТОТ МЕТОД МЫ ВОЗВРАЩАЕМ (он был в оригинале, но пропал в версии из лога) ---
    async def update_user_last_beer_time(self, user_id, last_beer_time_str: str):
        """Обновляет ТОЛЬКО время последнего пива."""
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                "UPDATE users SET last_beer_time = ? WHERE user_id = ?",
                (last_beer_time_str, user_id)
            )
            await db.commit()
    # --- КОНЕЦ ВОЗВРАЩЕННОГО МЕТОДА ---
            
    # (Это 'change_rating' из твоего файла)
    async def change_rating(self, user_id, amount):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                "UPDATE users SET beer_rating = beer_rating + ? WHERE user_id = ?",
                (amount, user_id)
            )
            await db.commit()

    async def get_top_users(self, limit=10):
        async with aiosqlite.connect(self.db_name) as db:
            # (Твой admin.py ожидает user_id, first_name, last_name, beer_rating)
            cursor = await db.execute(
                "SELECT user_id, first_name, last_name, beer_rating FROM users ORDER BY beer_rating DESC LIMIT ?", (limit,)
            )
            # Возвращаем как dict, чтобы было проще работать в /top
            cursor.row_factory = aiosqlite.Row
            return await cursor.fetchall()

    async def get_jackpot(self):
        return await self.get_setting('jackpot')

    async def update_jackpot(self, amount):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("UPDATE bot_settings SET value = value + ? WHERE key = 'jackpot'", (amount,))
            await db.commit()

    async def reset_jackpot(self):
        await self.update_setting('jackpot', 0)

    # --- Управление Чатами ---
    async def add_chat(self, chat_id, title):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("INSERT OR REPLACE INTO chats (chat_id, title) VALUES (?, ?)", (chat_id, title))
            await db.commit()
            logging.info(f"Бот добавлен в чат: {title} ({chat_id})")

    async def remove_chat(self, chat_id):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("DELETE FROM chats WHERE chat_id = ?", (chat_id,))
            await db.commit()
            logging.info(f"Бот удален из чата: {chat_id}")
            
    async def get_total_chats(self): # (Твой admin.py использует 'get_total_chats')
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT COUNT(chat_id) FROM chats")
            row = await cursor.fetchone()
            return row[0] if row else 0
            
    # --- Управление Рейдами (из handlers/game_raid.py) ---
    # Нам нужны только 2 метода для кулдауна атаки
    
    async def get_user_last_raid_attack(self, user_id, chat_id):
        # (Эта логика теперь не нужна, т.к. рейд в памяти)
        # (Но handlers/game_raid.py ее вызывает. 
        # Пусть пока возвращает None, чтобы не было ошибки)
        return None 
        
    async def set_user_last_raid_attack(self, user_id, chat_id, current_time):
        # (Аналогично, в новой логике не используется)
        pass
