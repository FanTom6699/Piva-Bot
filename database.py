# database.py
import aiosqlite
import logging
from datetime import datetime
from typing import Dict, Any, List, Tuple

class Database:
    def __init__(self, db_name="bot_database.db"):
        self.db_name = db_name
        logging.info(f"База данных {db_name} инициализирована.")

    async def initialize(self):
        """Создает таблицы, если они не существуют."""
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
            
            # --- НОВЫЕ ТАБЛИЦЫ ДЛЯ МАФИИ ---
            await db.execute("""
                CREATE TABLE IF NOT EXISTS mafia_games (
                    chat_id INTEGER PRIMARY KEY,
                    message_id INTEGER,
                    creator_id INTEGER,
                    status TEXT DEFAULT 'lobby',
                    day_count INTEGER DEFAULT 0
                );
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS mafia_players (
                    game_id INTEGER,
                    user_id INTEGER,
                    role TEXT,
                    is_alive INTEGER DEFAULT 1,
                    self_heals_used INTEGER DEFAULT 0,
                    inactive_nights_count INTEGER DEFAULT 0,
                    PRIMARY KEY (game_id, user_id)
                );
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS mafia_stats (
                    user_id INTEGER PRIMARY KEY,
                    games_played INTEGER DEFAULT 0,
                    games_won INTEGER DEFAULT 0,
                    authority INTEGER DEFAULT 0
                );
            """)
            # --- КОНЕЦ НОВЫХ ТАБЛИЦ ---

            # Убедимся, что джекпот существует
            await db.execute("INSERT OR IGNORE INTO bot_settings (key, value) VALUES ('jackpot', 0)")
            await db.commit()
            logging.info("Таблицы базы данных проверены и созданы (если отсутствовали).")

    # --- Управление Настройками ---
    async def get_all_settings(self) -> Dict[str, Any]:
        """Возвращает ВСЕ настройки в виде СЛОВАРЯ {key: value}."""
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
                "INSERT INTO users (user_id, first_name, last_name, username, last_beer_time) VALUES (?, ?, ?, ?, ?)",
                (user_id, first_name, last_name, username, datetime(2000, 1, 1).isoformat())
            )
            await db.commit()
            
    # --- НОВАЯ ФУНКЦИЯ (Нужна для Мафии) ---
    async def get_user_by_id(self, user_id):
        """Возвращает (first_name, last_name, username) пользователя по ID."""
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
            cursor = await db.execute("SELECT chat_id FROM chats")
            return [row[0] for row in await cursor.fetchall()]

    # --- Управление Рейдами (без изменений) ---
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

    # --- НОВЫЕ ФУНКЦИИ: УПРАВЛЕНИЕ ИГРОЙ МАФИИ ---
    
    async def create_mafia_game(self, chat_id, message_id, creator_id) -> bool:
        """Создает лобби игры. Возвращает False, если игра уже есть."""
        async with aiosqlite.connect(self.db_name) as db:
            try:
                await db.execute(
                    "INSERT INTO mafia_games (chat_id, message_id, creator_id, status) VALUES (?, ?, ?, 'lobby')",
                    (chat_id, message_id, creator_id)
                )
                await db.commit()
                return True
            except aiosqlite.IntegrityError:
                logging.warning(f"Попытка создать игру в {chat_id}, но она уже существует.")
                return False

    async def get_mafia_game(self, chat_id):
        """Возвращает данные игры (chat_id, message_id, creator_id, status, day_count)."""
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT * FROM mafia_games WHERE chat_id = ?", (chat_id,))
            return await cursor.fetchone()

    async def update_mafia_game_message_id(self, chat_id, message_id):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("UPDATE mafia_games SET message_id = ? WHERE chat_id = ?", (message_id, chat_id))
            await db.commit()
            
    async def update_mafia_game_status(self, chat_id, status, day_count=None):
        async with aiosqlite.connect(self.db_name) as db:
            if day_count:
                await db.execute("UPDATE mafia_games SET status = ?, day_count = ? WHERE chat_id = ?", (status, day_count, chat_id))
            else:
                await db.execute("UPDATE mafia_games SET status = ? WHERE chat_id = ?", (status, chat_id))
            await db.commit()

    async def delete_mafia_game(self, chat_id):
        """Полностью удаляет игру и всех ее участников."""
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("DELETE FROM mafia_games WHERE chat_id = ?", (chat_id,))
            await db.execute("DELETE FROM mafia_players WHERE game_id = ?", (chat_id,))
            await db.commit()
            
    # --- НОВЫЕ ФУНКЦИИ: УПРАВЛЕНИЕ ИГРОКАМИ МАФИИ ---

    async def add_mafia_player(self, chat_id, user_id) -> bool:
        """Добавляет игрока в лобби. Возвращает False, если игрок уже в игре."""
        async with aiosqlite.connect(self.db_name) as db:
            try:
                await db.execute(
                    "INSERT INTO mafia_players (game_id, user_id, is_alive) VALUES (?, ?, 1)",
                    (chat_id, user_id)
                )
                await db.commit()
                return True
            except aiosqlite.IntegrityError:
                return False # Игрок уже в игре

    async def remove_mafia_player(self, chat_id, user_id):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("DELETE FROM mafia_players WHERE game_id = ? AND user_id = ?", (chat_id, user_id))
            await db.commit()

    async def get_mafia_players(self, chat_id):
        """Возвращает всех игроков (даже мертвых) из текущей игры."""
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT * FROM mafia_players WHERE game_id = ?", (chat_id,))
            return await cursor.fetchall()
            
    async def get_mafia_player(self, chat_id, user_id):
        """Возвращает данные одного игрока."""
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT * FROM mafia_players WHERE game_id = ? AND user_id = ?", (chat_id, user_id))
            return await cursor.fetchone()

    async def get_mafia_player_count(self, chat_id):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT COUNT(user_id) FROM mafia_players WHERE game_id = ?", (chat_id,))
            row = await cursor.fetchone()
            return row[0] if row else 0
            
    async def update_mafia_player_role(self, chat_id, user_id, role):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("UPDATE mafia_players SET role = ? WHERE game_id = ? AND user_id = ?", (role, chat_id, user_id))
            await db.commit()
            
    async def set_mafia_player_self_heal(self, chat_id, user_id):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("UPDATE mafia_players SET self_heals_used = 1 WHERE game_id = ? AND user_id = ?", (chat_id, user_id))
            await db.commit()
            
    async def increment_mafia_player_inactive(self, chat_id, user_id):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("UPDATE mafia_players SET inactive_nights_count = inactive_nights_count + 1 WHERE game_id = ? AND user_id = ?", (chat_id, user_id))
            await db.commit()
            
    async def reset_mafia_player_inactive(self, chat_id, user_id):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("UPDATE mafia_players SET inactive_nights_count = 0 WHERE game_id = ? AND user_id = ?", (chat_id, user_id))
            await db.commit()
            
    async def set_mafia_player_alive(self, chat_id, user_id, is_alive: bool = False):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("UPDATE mafia_players SET is_alive = ? WHERE game_id = ? AND user_id = ?", (int(is_alive), chat_id, user_id))
            await db.commit()
            
    async def get_mafia_players_by_role(self, chat_id, roles: list, is_alive: bool = True):
        async with aiosqlite.connect(self.db_name) as db:
            # Создаем плейсхолдеры '?' для списка ролей
            placeholders = ','.join('?' * len(roles))
            query = f"SELECT * FROM mafia_players WHERE game_id = ? AND is_alive = ? AND role IN ({placeholders})"
            params = [chat_id, int(is_alive)] + roles
            cursor = await db.execute(query, tuple(params))
            return await cursor.fetchall()

    # --- НОВЫЕ ФУНКЦИИ: СТАТИСТИКА МАФИИ ---
    
    async def update_mafia_stats(self, user_id, has_won: bool, authority_change: int):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                "INSERT OR IGNORE INTO mafia_stats (user_id, games_played, games_won, authority) VALUES (?, 0, 0, 0)",
                (user_id,)
            )
            if has_won:
                await db.execute(
                    "UPDATE mafia_stats SET games_played = games_played + 1, games_won = games_won + 1, authority = authority + ? WHERE user_id = ?",
                    (authority_change, user_id)
                )
            else:
                await db.execute(
                    "UPDATE mafia_stats SET games_played = games_played + 1, authority = authority + ? WHERE user_id = ?",
                    (authority_change, user_id)
                )
            await db.commit()
            
    async def get_mafia_stats(self, user_id):
        """Возвращает (games_played, games_won, authority)."""
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT games_played, games_won, authority FROM mafia_stats WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            return row if row else (0, 0, 0)
