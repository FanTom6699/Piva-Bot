# database.py
import aiosqlite
import logging
from datetime import datetime
from typing import Dict, Any, List, Tuple

class Database:
    def __init__(self, db_name="bot_database.db"):
        self.db_name = db_name
        logging.info(f"База данных {db_name} инициализирована.")

    # --- ИСПРАВЛЕННАЯ ФУНКЦИЯ МИГРАЦИИ ---
    async def _run_migrations(self, db: aiosqlite.Connection):
        """Проверяет и добавляет недостающие колонки в существующие таблицы."""
        logging.info("Проверка структуры базы данных (миграции)...")
        try:
            # 1. Проверяем колонку 'registration_date' в 'users'
            cursor = await db.execute("PRAGMA table_info(users)")
            columns = [row[1] for row in await cursor.fetchall()]
            
            if 'registration_date' not in columns:
                logging.warning("Обнаружена старая версия таблицы 'users'. Добавляю 'registration_date' (Шаг 1/2)...")
                
                # --- ИСПРАВЛЕНИЕ ЗДЕСЬ ---
                # Шаг 1: Добавляем колонку, разрешая ей быть NULL (БЕЗ DEFAULT)
                await db.execute("ALTER TABLE users ADD COLUMN registration_date TIMESTAMP") 
                
                logging.info("... (Шаг 2/2) Заполняем 'registration_date' для старых пользователей...")
                # Шаг 2: Заполняем NULL значения для существующих пользователей
                await db.execute("UPDATE users SET registration_date = CURRENT_TIMESTAMP WHERE registration_date IS NULL")
                # --- КОНЕЦ ИСПРАВЛЕНИЯ ---

                await db.commit()
                logging.info("Таблица 'users' успешно обновлена (миграция завершена).")
            
        except Exception as e:
            logging.error(f"Ошибка во время миграции базы данных: {e}", exc_info=True)


    async def initialize(self):
        """Создает таблицы, если они не существуют, и запускает миграции."""
        async with aiosqlite.connect(self.db_name) as db:
            # --- Таблица Пользователей ---
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    first_name TEXT,
                    last_name TEXT,
                    username TEXT,
                    beer_rating INTEGER DEFAULT 0,
                    last_beer_time TIMESTAMP,
                    registration_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            # --- Таблица Чатов ---
            await db.execute("""
                CREATE TABLE IF NOT EXISTS chats (
                    chat_id INTEGER PRIMARY KEY,
                    title TEXT
                );
            """)
            # --- Таблица Настроек ---
            await db.execute("""
                CREATE TABLE IF NOT EXISTS bot_settings (
                    key TEXT PRIMARY KEY,
                    value INTEGER
                );
            """)
            # --- Таблицы Рейдов ---
            await db.execute("""
                CREATE TABLE IF NOT EXISTS active_raids (
                    chat_id INTEGER PRIMARY KEY,
                    message_id INTEGER,
                    health INTEGER,
                    max_health INTEGER,
                    reward INTEGER,
                    end_time TIMESTAMP
                );
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS raid_participants (
                    raid_id INTEGER,
                    user_id INTEGER,
                    total_damage INTEGER DEFAULT 0,
                    last_hit_time TIMESTAMP,
                    PRIMARY KEY (raid_id, user_id)
                );
            """)
            
            await db.execute("INSERT OR IGNORE INTO bot_settings (key, value) VALUES ('jackpot', 0)")
            await db.commit()
            logging.info("Таблицы базы данных проверены.")
            
            # --- ЗАПУСКАЕМ МИГРАЦИЮ ---
            await self._run_migrations(db)

    # --- Управление Настройками ---
    async def get_all_settings(self) -> Dict[str, Any]:
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT key, value FROM bot_settings")
            rows = await cursor.fetchall()
            return {row[0]: row[1] for row in rows}

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
                "INSERT INTO users (user_id, first_name, last_name, username, last_beer_time, registration_date) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
                (user_id, first_name, last_name, username, datetime(2000, 1, 1).isoformat())
            )
            await db.commit()
            
    async def get_user_by_id(self, user_id):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT first_name, last_name, username FROM users WHERE user_id = ?", (user_id,))
            return await cursor.fetchone()

    async def get_total_users_count(self):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT COUNT(user_id) FROM users")
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def get_all_user_ids(self):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT user_id FROM users")
            return [row[0] for row in await cursor.fetchall()]
            
    async def get_user_by_username(self, username):
        username = username.lstrip('@')
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT user_id FROM users WHERE username = ?", (username,))
            row = await cursor.fetchone()
            return row[0] if row else None

    # --- Управление Пивом и Рейтингом ---
    async def get_user_beer_rating(self, user_id):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT beer_rating FROM users WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def get_last_beer_time(self, user_id):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT last_beer_time FROM users WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            if row and row[0]:
                try:
                    return datetime.fromisoformat(row[0])
                except (ValueError, TypeError):
                     return datetime(2000, 1, 1)
            return None

    async def update_beer_data(self, user_id, new_rating):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                "UPDATE users SET beer_rating = ?, last_beer_time = ? WHERE user_id = ?",
                (new_rating, datetime.now().isoformat(), user_id)
            )
            await db.commit()
            
    async def change_rating(self, user_id, amount):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                "UPDATE users SET beer_rating = beer_rating + ? WHERE user_id = ?",
                (amount, user_id)
            )
            await db.commit()

    async def get_top_users(self, limit=10):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                "SELECT first_name, last_name, beer_rating FROM users ORDER BY beer_rating DESC LIMIT ?", (limit,)
            )
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
            
    async def get_all_chats(self):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT chat_id, title FROM chats")
            return await cursor.fetchall()

    async def get_all_chat_ids(self):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT chat_id FROM users")
            return [row[0] for row in await cursor.fetchall()]

    # --- Управление Рейдами ---
    async def create_raid(self, chat_id, message_id, health, reward, end_time):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                "INSERT INTO active_raids (chat_id, message_id, health, max_health, reward, end_time) VALUES (?, ?, ?, ?, ?, ?)",
                (chat_id, message_id, health, health, reward, end_time.isoformat())
            )
            await db.commit()

    async def get_active_raid(self, chat_id):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT * FROM active_raids WHERE chat_id = ?", (chat_id,))
            row = await cursor.fetchone()
            if row:
                return row[:-1] + (datetime.fromisoformat(row[-1]),)
            return None
            
    async def get_all_active_raids(self):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT * FROM active_raids")
            return await cursor.fetchall()

    async def delete_raid(self, chat_id):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("DELETE FROM active_raids WHERE chat_id = ?", (chat_id,))
            await db.execute("DELETE FROM raid_participants WHERE raid_id = ?", (chat_id,))
            await db.commit()

    async def update_raid_health(self, chat_id, damage):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("UPDATE active_raids SET health = health - ? WHERE chat_id = ?", (damage, chat_id))
            await db.commit()

    async def add_raid_participant(self, chat_id, user_id, damage):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                "INSERT OR IGNORE INTO raid_participants (raid_id, user_id, total_damage, last_hit_time) VALUES (?, ?, 0, ?)",
                (chat_id, user_id, datetime(2000, 1, 1).isoformat())
            )
            await db.execute(
                "UPDATE raid_participants SET total_damage = total_damage + ?, last_hit_time = ? WHERE raid_id = ? AND user_id = ?",
                (damage, datetime.now().isoformat(), chat_id, user_id)
            )
            await db.commit()
            
    async def get_raid_participant(self, chat_id, user_id):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                "SELECT * FROM raid_participants WHERE raid_id = ? AND user_id = ?", (chat_id, user_id)
            )
            row = await cursor.fetchone()
            if row:
                return row[:-1] + (datetime.fromisoformat(row[-1]),)
            return None

    async def get_all_raid_participants(self, chat_id):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                "SELECT user_id, total_damage FROM raid_participants WHERE raid_id = ? ORDER BY total_damage DESC", (chat_id,)
            )
            return await cursor.fetchall()

    # --- Функции Профиля (/me) ---
    async def get_user_rank(self, user_id: int) -> int:
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                """
                SELECT (SELECT COUNT(1) FROM users WHERE beer_rating > t.beer_rating) + 1 AS rank
                FROM users t
                WHERE t.user_id = ?
                """,
                (user_id,)
            )
            row = await cursor.fetchone()
            return row[0] if row else "N/A"

    async def get_user_reg_date(self, user_id: int) -> str | None:
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT registration_date FROM users WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            return row[0] if row else None

    async def get_user_raid_stats(self, user_id: int) -> Tuple[int, int]:
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                "SELECT COUNT(raid_id), SUM(total_damage) FROM raid_participants WHERE user_id = ?",
                (user_id,)
            )
            row = await cursor.fetchone()
            if row:
                return (row[0] or 0, row[1] or 0)
            return (0, 0)
