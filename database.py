# database.py
import aiosqlite
from datetime import datetime
from typing import Dict, Any, List, Tuple

class Database:
    def __init__(self, db_name='bot_database.db'):
        self.db_name = db_name

    async def _add_column_safely(self, db, table_name, column_name, column_type):
        """Вспомогательная функция для безопасного добавления колонок."""
        try:
            await db.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
        except aiosqlite.OperationalError as e:
            if f"duplicate column name: {column_name}" not in str(e):
                raise e

    async def initialize(self):
        async with aiosqlite.connect(self.db_name) as db:
            # --- Существующие таблицы ---
            await db.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY, first_name TEXT, last_name TEXT,
                    username TEXT, beer_rating INTEGER DEFAULT 0, last_beer_time TEXT
                )
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS chats (chat_id INTEGER PRIMARY KEY, title TEXT)
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS game_data (key TEXT PRIMARY KEY, value INTEGER)
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS active_raids (
                    chat_id INTEGER PRIMARY KEY, message_id INTEGER, boss_health INTEGER,
                    boss_max_health INTEGER, reward_pool INTEGER, end_time TEXT
                )
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS raid_participants (
                    raid_id INTEGER, user_id INTEGER, damage_dealt INTEGER DEFAULT 0,
                    last_hit_time TEXT, PRIMARY KEY (raid_id, user_id)
                )
            ''')

            # --- НОВЫЕ ТАБЛИЦЫ ДЛЯ МАФИИ ---
            await db.execute('''
                CREATE TABLE IF NOT EXISTS mafia_games (
                    chat_id INTEGER PRIMARY KEY,
                    message_id INTEGER,
                    creator_id INTEGER,
                    status TEXT DEFAULT 'lobby',
                    day_count INTEGER DEFAULT 0,
                    start_time TEXT,
                    lobby_timer_task_id TEXT 
                )
            ''')
            
            await db.execute('''
                CREATE TABLE IF NOT EXISTS mafia_players (
                    game_id INTEGER,
                    user_id INTEGER,
                    role TEXT,
                    is_alive INTEGER DEFAULT 1,
                    self_heals_used INTEGER DEFAULT 0,
                    inactive_nights_count INTEGER DEFAULT 0,
                    PRIMARY KEY (game_id, user_id)
                )
            ''')

            # --- ОБНОВЛЕНИЕ ТАБЛИЦЫ USERS (Безопасно) ---
            await self._add_column_safely(db, "users", "mafia_authority", "INTEGER DEFAULT 1000")
            await self._add_column_safely(db, "users", "mafia_games", "INTEGER DEFAULT 0")
            await self._add_column_safely(db, "users", "mafia_wins", "INTEGER DEFAULT 0")

            # --- Настройки по умолчанию ---
            default_settings = [
                ('jackpot', 0), ('beer_cooldown', 7200), ('jackpot_chance', 150),
                ('roulette_cooldown', 600), ('roulette_min_bet', 5), ('roulette_max_bet', 100),
                ('ladder_min_bet', 5), ('ladder_max_bet', 100), ('raid_boss_health', 100000),
                ('raid_reward_pool', 5000), ('raid_duration_hours', 24), ('raid_hit_cooldown_minutes', 30),
                ('raid_strong_hit_cost', 100), ('raid_strong_hit_damage_min', 500),
                ('raid_strong_hit_damage_max', 1000), ('raid_normal_hit_damage_min', 10),
                ('raid_normal_hit_damage_max', 50), ('raid_reminder_hours', 6),
                # --- НОВЫЕ НАСТРОЙКИ ДЛЯ МАФИИ ---
                ('mafia_lobby_timer', 90),
                ('mafia_min_players', 5),
                ('mafia_max_players', 10),
                ('mafia_night_timer', 90),
                ('mafia_day_timer', 120),
                ('mafia_vote_timer', 60),
                ('mafia_win_reward', 100),
                ('mafia_lose_reward', 25),
                ('mafia_win_authority', 15),
                ('mafia_lose_authority', -10)
            ]
            await db.executemany("INSERT OR IGNORE INTO game_data (key, value) VALUES (?, ?)", default_settings)
            
            await db.commit()
    
    # --- Существующие функции (без изменений) ---
    async def add_chat(self, chat_id: int, title: str):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("INSERT OR REPLACE INTO chats (chat_id, title) VALUES (?, ?)", (chat_id, title))
            await db.commit()

    async def remove_chat(self, chat_id: int):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("DELETE FROM chats WHERE chat_id = ?", (chat_id,))
            await db.commit()

    async def get_all_chats(self) -> List[Tuple[int, str]]:
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT chat_id, title FROM chats ORDER BY title")
            return await cursor.fetchall()

    async def get_all_chat_ids(self):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT chat_id FROM chats")
            return [row[0] for row in await cursor.fetchall()]

    async def user_exists(self, user_id):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute('SELECT 1 FROM users WHERE user_id = ?', (user_id,))
            return await cursor.fetchone() is not None

    async def add_user(self, user_id, first_name, last_name, username):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                'INSERT INTO users (user_id, first_name, last_name, username, beer_rating) VALUES (?, ?, ?, ?, ?)',
                (user_id, first_name, last_name, username, 0)
            )
            await db.commit()
            
    async def get_all_user_ids(self):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT user_id FROM users")
            return [row[0] for row in await cursor.fetchall()]

    async def get_total_users_count(self):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM users")
            result = await cursor.fetchone()
            return result[0] if result else 0

    async def get_user_by_username(self, username: str):
        username = username.lstrip('@')
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute('SELECT user_id FROM users WHERE username = ?', (username,))
            result = await cursor.fetchone()
            return result[0] if result else None

    async def get_user_beer_rating(self, user_id):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute('SELECT beer_rating FROM users WHERE user_id = ?', (user_id,))
            result = await cursor.fetchone()
            return result[0] if result else 0
            
    async def get_last_beer_time(self, user_id):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute('SELECT last_beer_time FROM users WHERE user_id = ?', (user_id,))
            result = await cursor.fetchone()
            return datetime.fromisoformat(result[0]) if result and result[0] else None

    async def update_beer_data(self, user_id, new_rating):
        current_time_iso = datetime.now().isoformat()
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                'UPDATE users SET beer_rating = ?, last_beer_time = ? WHERE user_id = ?',
                (new_rating, current_time_iso, user_id)
            )
            await db.commit()

    async def get_top_users(self, limit=10):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                'SELECT first_name, last_name, beer_rating FROM users ORDER BY beer_rating DESC LIMIT ?',
                (limit,)
            )
            return await cursor.fetchall()

    async def change_rating(self, user_id, amount: int):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                'UPDATE users SET beer_rating = beer_rating + ? WHERE user_id = ?',
                (amount, user_id)
            )
            await db.commit()

    async def get_jackpot(self) -> int:
        return await self.get_setting('jackpot')

    async def update_jackpot(self, amount: int):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("UPDATE game_data SET value = value + ? WHERE key = 'jackpot'", (amount,))
            await db.commit()

    async def reset_jackpot(self):
        await self.update_setting('jackpot', 0)

    async def get_setting(self, key: str) -> int:
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT value FROM game_data WHERE key = ?", (key,))
            result = await cursor.fetchone()
            return result[0] if result else 0

    async def get_all_settings(self) -> Dict[str, int]:
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT key, value FROM game_data")
            return {row[0]: row[1] for row in await cursor.fetchall()}

    async def update_setting(self, key: str, value: int):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("INSERT OR REPLACE INTO game_data (key, value) VALUES (?, ?)", (key, value))
            await db.commit()
    
    # --- Функции Рейда (без изменений) ---
    async def create_raid(self, chat_id: int, message_id: int, health: int, reward: int, end_time: datetime):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                "INSERT INTO active_raids (chat_id, message_id, boss_health, boss_max_health, reward_pool, end_time) VALUES (?, ?, ?, ?, ?, ?)",
                (chat_id, message_id, health, health, reward, end_time.isoformat())
            )
            await db.execute("DELETE FROM raid_participants WHERE raid_id = ?", (chat_id,))
            await db.commit()

    async def get_active_raid(self, chat_id: int):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT * FROM active_raids WHERE chat_id = ?", (chat_id,))
            return await cursor.fetchone() 

    async def get_all_active_raids(self):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT * FROM active_raids")
            return await cursor.fetchall()

    async def update_raid_health(self, chat_id: int, damage: int):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("UPDATE active_raids SET boss_health = boss_health - ? WHERE chat_id = ?", (damage, chat_id))
            await db.commit()
            
    async def delete_raid(self, chat_id: int):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("DELETE FROM active_raids WHERE chat_id = ?", (chat_id,))
            await db.execute("DELETE FROM raid_participants WHERE raid_id = ?", (chat_id,))
            await db.commit()

    async def add_raid_participant(self, chat_id: int, user_id: int, damage: int):
        now_iso = datetime.now().isoformat()
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                """
                INSERT INTO raid_participants (raid_id, user_id, damage_dealt, last_hit_time)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(raid_id, user_id) DO UPDATE SET
                damage_dealt = damage_dealt + excluded.damage_dealt,
                last_hit_time = excluded.last_hit_time
                """,
                (chat_id, user_id, damage, now_iso)
            )
            await db.commit()

    async def get_raid_participant(self, chat_id: int, user_id: int):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT * FROM raid_participants WHERE raid_id = ? AND user_id = ?", (chat_id, user_id))
            return await cursor.fetchone()

    async def get_all_raid_participants(self, chat_id: int) -> List[Tuple[int, int]]:
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT user_id, damage_dealt FROM raid_participants WHERE raid_id = ? ORDER BY damage_dealt DESC", (chat_id,))
            return await cursor.fetchall()

    # --- НОВЫЕ ФУНКЦИИ ДЛЯ МАФИИ ---

    async def create_mafia_game(self, chat_id: int, message_id: int, creator_id: int, status: str = 'lobby') -> bool:
        """Создает новую игру в Мафию в чате."""
        async with aiosqlite.connect(self.db_name) as db:
            try:
                await db.execute(
                    "INSERT INTO mafia_games (chat_id, message_id, creator_id, status, start_time) VALUES (?, ?, ?, ?, ?)",
                    (chat_id, message_id, creator_id, status, datetime.now().isoformat())
                )
                # Удаляем всех "старых" игроков из прошлой игры в этом чате, если они зависли
                await db.execute("DELETE FROM mafia_players WHERE game_id = ?", (chat_id,))
                await db.commit()
                return True
            except aiosqlite.IntegrityError:
                # Игра в этом чате уже существует
                return False

    async def get_mafia_game(self, chat_id: int):
        """Получает данные об активной игре в Мафию."""
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT * FROM mafia_games WHERE chat_id = ?", (chat_id,))
            return await cursor.fetchone()

    async def add_mafia_player(self, chat_id: int, user_id: int):
        """Добавляет игрока в лобби Мафии."""
        async with aiosqlite.connect(self.db_name) as db:
            try:
                await db.execute("INSERT INTO mafia_players (game_id, user_id) VALUES (?, ?)", (chat_id, user_id))
                await db.commit()
                return True
            except aiosqlite.IntegrityError:
                return False # Игрок уже в игре

    async def remove_mafia_player(self, chat_id: int, user_id: int):
        """Удаляет игрока из лобби Мафии."""
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("DELETE FROM mafia_players WHERE game_id = ? AND user_id = ?", (chat_id, user_id))
            await db.commit()

    async def get_mafia_players(self, chat_id: int) -> List[Tuple]:
        """Получает список всех игроков в конкретной игре Мафии."""
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT * FROM mafia_players WHERE game_id = ?", (chat_id,))
            return await cursor.fetchall()

    async def get_mafia_player_count(self, chat_id: int) -> int:
        """Считает, сколько игроков в лобби."""
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM mafia_players WHERE game_id = ?", (chat_id,))
            result = await cursor.fetchone()
            return result[0] if result else 0

    async def delete_mafia_game(self, chat_id: int):
        """Полностью удаляет игру и всех ее участников."""
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("DELETE FROM mafia_games WHERE chat_id = ?", (chat_id,))
            await db.execute("DELETE FROM mafia_players WHERE game_id = ?", (chat_id,))
            await db.commit()

    async def update_mafia_stats(self, user_id: int, has_won: bool, authority_change: int):
        """Обновляет ELO (Авторитет) и статистику побед/игр."""
        async with aiosqlite.connect(self.db_name) as db:
            win_add = 1 if has_won else 0
            await db.execute(
                """
                UPDATE users 
                SET mafia_authority = mafia_authority + ?,
                    mafia_games = mafia_games + 1,
                    mafia_wins = mafia_wins + ?
                WHERE user_id = ?
                """,
                (authority_change, win_add, user_id)
            )
            await db.commit()

    async def get_mafia_top(self, limit=10) -> List[Tuple]:
        """Получает топ игроков по 'Авторитету'."""
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                """
                SELECT first_name, last_name, mafia_authority, mafia_games, mafia_wins 
                FROM users 
                WHERE mafia_games > 0
                ORDER BY mafia_authority DESC 
                LIMIT ?
                """,
                (limit,)
            )
            return await cursor.fetchall()

    async def get_mafia_user_stats(self, user_id: int):
        """Получает статистику Мафии для одного игрока."""
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                "SELECT mafia_authority, mafia_games, mafia_wins FROM users WHERE user_id = ?",
                (user_id,)
            )
            return await cursor.fetchone()
