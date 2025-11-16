# database.py
import aiosqlite
import logging
import random # ✅ НОВЫЙ ИМПОРТ
from datetime import datetime, timedelta # ✅ НОВЫЙ ИМПОРТ
from typing import Dict, Any, List, Tuple

# ✅ НОВЫЙ ИМПОРТ
from handlers.farm_config import FARM_ORDER_POOL, get_random_orders

# --- КОНСТАНТЫ ДЛЯ ФЕРМЫ ---
DEFAULT_INVENTORY = {
    'зерно': 0, 'хмель': 0,
    'семя_зерна': 5, 'семя_хмеля': 3
}

class Database:
    def __init__(self, db_name='bot_database.db'):
        self.db_name = db_name

    async def initialize(self):
        logging.info("Запуск миграции базы данных...")
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            # --- Таблица Юзеров (с колонкой /me) ---
            await db.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY, first_name TEXT, last_name TEXT,
                    username TEXT, beer_rating INTEGER DEFAULT 0, last_beer_time TEXT,
                    registration_date TEXT 
                )
            ''')
            try:
                await db.execute("ALTER TABLE users ADD COLUMN registration_date TEXT")
            except aiosqlite.OperationalError:
                pass 
            
            # --- (Другие таблицы: Чаты, Настройки, Рейды) ---
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
            
            # --- ✅✅✅ ИЗМЕНЕНИЕ (user_farm_data) ✅✅✅ ---
            await db.execute('''
                CREATE TABLE IF NOT EXISTS user_farm_data (
                    user_id INTEGER PRIMARY KEY,
                    field_level INTEGER DEFAULT 1,
                    brewery_level INTEGER DEFAULT 1,
                    field_upgrade_timer_end TEXT,
                    brewery_upgrade_timer_end TEXT,
                    brewery_batch_size INTEGER DEFAULT 0,
                    brewery_batch_timer_end TEXT,
                    last_orders_reset TEXT 
                )
            ''')
            # (Миграция: добавляем колонку для Доски Заказов)
            try:
                await db.execute("ALTER TABLE user_farm_data ADD COLUMN last_orders_reset TEXT")
            except aiosqlite.OperationalError:
                pass 
            # --- ---
            
            # --- (user_farm_plots с фиксом уведомлений) ---
            await db.execute('''
                CREATE TABLE IF NOT EXISTS user_farm_plots (
                    plot_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    plot_num INTEGER,
                    crop_id TEXT,
                    ready_time TEXT,
                    notification_sent INTEGER DEFAULT 0, 
                    UNIQUE(user_id, plot_num)
                )
            ''')
            try:
                await db.execute("ALTER TABLE user_farm_plots ADD COLUMN notification_sent INTEGER DEFAULT 0")
            except aiosqlite.OperationalError:
                pass 
            
            await db.execute('''
                CREATE TABLE IF NOT EXISTS user_farm_inventory (
                    user_id INTEGER,
                    item_id TEXT,
                    quantity INTEGER,
                    PRIMARY KEY (user_id, item_id)
                )
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS farm_notifications (
                    user_id INTEGER,
                    task_type TEXT,
                    data_json TEXT,
                    is_sent INTEGER DEFAULT 0,
                    PRIMARY KEY (user_id, task_type)
                )
            ''')
            
            # --- ✅✅✅ НОВАЯ ТАБЛИЦА (user_farm_orders) ✅✅✅ ---
            await db.execute('''
                CREATE TABLE IF NOT EXISTS user_farm_orders (
                    user_id INTEGER,
                    slot_id INTEGER,
                    order_id TEXT,
                    is_completed INTEGER DEFAULT 0,
                    PRIMARY KEY (user_id, slot_id)
                )
            ''')
            # --- ---
            
            # --- (Миграция Настроек) ---
            default_settings = [
                ('jackpot', 0), ('beer_cooldown', 7200), ('jackpot_chance', 150),
                ('roulette_cooldown', 600), ('roulette_min_bet', 5), ('roulette_max_bet', 100),
                ('ladder_min_bet', 5), ('ladder_max_bet', 100), ('raid_boss_health', 100000),
                ('raid_reward_pool', 5000), ('raid_duration_hours', 24), ('raid_hit_cooldown_minutes', 30),
                ('raid_strong_hit_cost', 100), ('raid_strong_hit_damage_min', 500),
                ('raid_strong_hit_damage_max', 1000), ('raid_normal_hit_damage_min', 10),
                ('raid_normal_hit_damage_max', 50), ('raid_reminder_hours', 6)
            ]
            await db.executemany("INSERT OR IGNORE INTO game_data (key, value) VALUES (?, ?)", default_settings)
            
            await db.commit()
        logging.info("Миграция базы данных завершена.")
    
    # --- Функции Чатов (Без изменений) ---
    async def add_chat(self, chat_id: int, title: str):
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            await db.execute("INSERT OR REPLACE INTO chats (chat_id, title) VALUES (?, ?)", (chat_id, title))
            await db.commit()

    async def remove_chat(self, chat_id: int):
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            await db.execute("DELETE FROM chats WHERE chat_id = ?", (chat_id,))
            await db.commit()

    async def get_all_chats(self) -> List[Tuple[int, str]]:
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            cursor = await db.execute("SELECT chat_id, title FROM chats ORDER BY title")
            return await cursor.fetchall()

    async def get_all_chat_ids(self):
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            cursor = await db.execute("SELECT chat_id FROM chats")
            return [row[0] for row in await cursor.fetchall()]

    # --- Функции Юзеров (Объединены /me и !напоить) ---
    async def user_exists(self, user_id):
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            cursor = await db.execute('SELECT 1 FROM users WHERE user_id = ?', (user_id,))
            return await cursor.fetchone() is not None

    async def add_user(self, user_id, first_name, last_name, username):
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            reg_date_iso = datetime.now().isoformat()
            await db.execute(
                'INSERT INTO users (user_id, first_name, last_name, username, beer_rating, registration_date) VALUES (?, ?, ?, ?, ?, ?)',
                (user_id, first_name, last_name, username, 0, reg_date_iso)
            )
            await self._ensure_inventory(db, user_id) # (Для фермы)
            await db.commit()
            
    async def get_all_user_ids(self):
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            cursor = await db.execute("SELECT user_id FROM users")
            return [row[0] for row in await cursor.fetchall()]

    async def get_total_users_count(self):
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM users")
            result = await cursor.fetchone()
            return result[0] if result else 0

    async def get_user_by_id(self, user_id: int):
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            cursor = await db.execute('SELECT first_name, last_name FROM users WHERE user_id = ?', (user_id,))
            row = await cursor.fetchone()
            if row:
                return (row[0], row[1]) 
            return None

    async def get_user_by_username(self, username: str):
        username = username.lstrip('@')
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            cursor = await db.execute('SELECT user_id, first_name FROM users WHERE username = ?', (username,))
            return await cursor.fetchone()

    async def get_user_beer_rating(self, user_id):
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            cursor = await db.execute('SELECT beer_rating FROM users WHERE user_id = ?', (user_id,))
            result = await cursor.fetchone()
            return result[0] if result else 0
            
    async def get_last_beer_time(self, user_id):
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            cursor = await db.execute('SELECT last_beer_time FROM users WHERE user_id = ?', (user_id,))
            result = await cursor.fetchone()
            return datetime.fromisoformat(result[0]) if result and result[0] else None

    async def update_beer_data(self, user_id, new_rating):
        current_time_iso = datetime.now().isoformat()
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            await db.execute(
                'UPDATE users SET beer_rating = ?, last_beer_time = ? WHERE user_id = ?',
                (new_rating, current_time_iso, user_id)
            )
            await db.commit()

    async def get_top_users(self, limit=10):
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            cursor = await db.execute(
                'SELECT first_name, last_name, beer_rating FROM users ORDER BY beer_rating DESC LIMIT ?',
                (limit,)
            )
            return await cursor.fetchall()

    async def change_rating(self, user_id, amount: int):
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            await db.execute(
                'UPDATE users SET beer_rating = beer_rating + ? WHERE user_id = ?',
                (amount, user_id)
            )
            await db.commit()

    # --- (Функции для /me) ---
    async def get_user_rank(self, user_id: int) -> int:
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            query = """
                SELECT COUNT(1) + 1 
                FROM users 
                WHERE beer_rating > (SELECT beer_rating FROM users WHERE user_id = ?)
            """
            cursor = await db.execute(query, (user_id,))
            result = await cursor.fetchone()
            return result[0] if result else 1
            
    async def get_user_reg_date(self, user_id: int) -> str | None:
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            cursor = await db.execute("SELECT registration_date FROM users WHERE user_id = ?", (user_id,))
            result = await cursor.fetchone()
            return result[0] if result else None
            
    async def get_user_raid_stats(self, user_id: int) -> Tuple[int, int]:
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            query = """
                SELECT COUNT(DISTINCT raid_id), SUM(damage_dealt) 
                FROM raid_participants 
                WHERE user_id = ?
            """
            cursor = await db.execute(query, (user_id,))
            result = await cursor.fetchone()
            return (result[0] or 0, result[1] or 0)
    # --- ---

    # --- Функции Настроек (Без изменений) ---
    async def get_jackpot(self) -> int:
        return await self.get_setting('jackpot')

    async def update_jackpot(self, amount: int):
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            await db.execute("UPDATE game_data SET value = value + ? WHERE key = 'jackpot'", (amount,))
            await db.commit()

    async def reset_jackpot(self):
        await self.update_setting('jackpot', 0)

    async def get_setting(self, key: str) -> int:
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            cursor = await db.execute("SELECT value FROM game_data WHERE key = ?", (key,))
            result = await cursor.fetchone()
            return result[0] if result else 0

    async def get_all_settings(self) -> Dict[str, int]:
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            cursor = await db.execute("SELECT key, value FROM game_data")
            return {row[0]: row[1] for row in await cursor.fetchall()}

    async def update_setting(self, key: str, value: int):
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            await db.execute("INSERT OR REPLACE INTO game_data (key, value) VALUES (?, ?)", (key, value))
            await db.commit()
    
    # --- Функции Рейдов (Без изменений) ---
    async def create_raid(self, chat_id: int, message_id: int, health: int, reward: int, end_time: datetime):
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            await db.execute(
                "INSERT INTO active_raids (chat_id, message_id, boss_health, boss_max_health, reward_pool, end_time) VALUES (?, ?, ?, ?, ?, ?)",
                (chat_id, message_id, health, health, reward, end_time.isoformat())
            )
            await db.execute("DELETE FROM raid_participants WHERE raid_id = ?", (chat_id,))
            await db.commit()
    async def get_active_raid(self, chat_id: int):
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            cursor = await db.execute("SELECT * FROM active_raids WHERE chat_id = ?", (chat_id,))
            return await cursor.fetchone() 
    async def get_all_active_raids(self):
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            cursor = await db.execute("SELECT * FROM active_raids")
            return await cursor.fetchall()
    async def update_raid_health(self, chat_id: int, damage: int):
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            await db.execute("UPDATE active_raids SET boss_health = boss_health - ? WHERE chat_id = ?", (damage, chat_id))
            await db.commit()
    async def delete_raid(self, chat_id: int):
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            await db.execute("DELETE FROM active_raids WHERE chat_id = ?", (chat_id,))
            await db.execute("DELETE FROM raid_participants WHERE raid_id = ?", (chat_id,))
            await db.commit()
    async def add_raid_participant(self, chat_id: int, user_id: int, damage: int):
        now_iso = datetime.now().isoformat()
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
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
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            cursor = await db.execute("SELECT * FROM raid_participants WHERE raid_id = ? AND user_id = ?", (chat_id, user_id))
            return await cursor.fetchone()
    async def get_all_raid_participants(self, chat_id: int) -> List[Tuple[int, int]]:
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            cursor = await db.execute("SELECT user_id, damage_dealt FROM raid_participants WHERE raid_id = ? ORDER BY damage_dealt DESC", (chat_id,))
            return await cursor.fetchall()

    # --- ФУНКЦИИ ФЕРМЫ (Твой код + Доска Заказов) ---
    
    async def _ensure_farm_data(self, db, user_id: int):
        await db.execute(
            "INSERT OR IGNORE INTO user_farm_data (user_id) VALUES (?)",
            (user_id,)
        )

    async def _ensure_inventory(self, db, user_id: int):
        for item_id, quantity in DEFAULT_INVENTORY.items():
            await db.execute(
                "INSERT OR IGNORE INTO user_farm_inventory (user_id, item_id, quantity) VALUES (?, ?, ?)",
                (user_id, item_id, quantity)
            )
    
    # --- ✅✅✅ ИЗМЕНЕНИЕ (get_user_farm_data) ✅✅✅ ---
    async def get_user_farm_data(self, user_id: int) -> Dict[str, Any]:
        """(Важно) Получает данные фермы. Теперь возвращает dict."""
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            await self._ensure_farm_data(db, user_id)
            
            db.row_factory = aiosqlite.Row # (Получаем dict, а не tuple)
            cursor = await db.execute("SELECT * FROM user_farm_data WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            
            if not row:
                 logging.error(f"КРИТИЧЕСКАЯ ОШИБКА: Не удалось создать farm_data для {user_id}")
                 return {}
            
            row_dict = dict(row) # (Конвертируем в dict)
            
            def to_datetime_safe(iso_str):
                return datetime.fromisoformat(iso_str) if iso_str else None

            # (Преобразуем нужные поля в datetime)
            row_dict['field_upgrade_timer_end'] = to_datetime_safe(row_dict.get('field_upgrade_timer_end'))
            row_dict['brewery_upgrade_timer_end'] = to_datetime_safe(row_dict.get('brewery_upgrade_timer_end'))
            row_dict['brewery_batch_timer_end'] = to_datetime_safe(row_dict.get('brewery_batch_timer_end'))
            # (last_orders_reset тоже остается строкой, мы его конвертируем в check_and_reset_orders)
            
            return row_dict
    # --- ---

    async def get_user_plots(self, user_id: int) -> List[Tuple]:
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            cursor = await db.execute(
                "SELECT plot_num, crop_id, ready_time FROM user_farm_plots WHERE user_id = ?",
                (user_id,)
            )
            return await cursor.fetchall()

    async def get_user_inventory(self, user_id: int) -> Dict[str, int]:
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            await self._ensure_inventory(db, user_id)
            cursor = await db.execute(
                "SELECT item_id, quantity FROM user_farm_inventory WHERE user_id = ?",
                (user_id,)
            )
            inventory = DEFAULT_INVENTORY.copy()
            inventory.update({item: qty for item, qty in await cursor.fetchall()})
            return inventory

    async def modify_inventory(self, user_id: int, item_id: str, amount: int) -> bool:
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            await self._ensure_inventory(db, user_id)
            await db.execute(
                """
                INSERT INTO user_farm_inventory (user_id, item_id, quantity)
                VALUES (?, ?, max(0, ?)) 
                ON CONFLICT(user_id, item_id) DO UPDATE SET
                quantity = max(0, quantity + ?)
                WHERE (quantity + ?) >= 0
                """,
                (user_id, item_id, amount, amount, amount) 
            )
            changes_cursor = await db.execute("SELECT changes()")
            changes = (await changes_cursor.fetchone())[0]
            await db.commit()
            if amount < 0 and changes == 0:
                logging.warning(f"Ошибка списания: у {user_id} не хватило {item_id} (нужно {abs(amount)})")
                return False
            return True

    async def plant_crop(self, user_id: int, plot_num: int, crop_id: str, ready_time: datetime) -> bool:
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            try:
                await db.execute(
                    "INSERT INTO user_farm_plots (user_id, plot_num, crop_id, ready_time, notification_sent) VALUES (?, ?, ?, ?, 0)",
                    (user_id, plot_num, crop_id, ready_time.isoformat())
                )
                await db.commit()
                return True
            except aiosqlite.IntegrityError: 
                logging.warning(f"Ошибка посадки: Участок {plot_num} (user {user_id}) уже занят.")
                return False

    async def harvest_plot(self, user_id: int, plot_num: int) -> str | None:
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            now_iso = datetime.now().isoformat()
            cursor = await db.execute(
                "SELECT crop_id FROM user_farm_plots WHERE user_id = ? AND plot_num = ? AND ready_time <= ?",
                (user_id, plot_num, now_iso)
            )
            result = await cursor.fetchone()
            if not result: return None
            crop_id = result[0]
            await db.execute(
                "DELETE FROM user_farm_plots WHERE user_id = ? AND plot_num = ?",
                (user_id, plot_num)
            )
            await db.commit()
            return crop_id

    async def start_brewing(self, user_id: int, quantity: int, end_time: datetime):
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            await self._ensure_farm_data(db, user_id)
            await db.execute(
                "UPDATE user_farm_data SET brewery_batch_size = ?, brewery_batch_timer_end = ? WHERE user_id = ?",
                (quantity, end_time.isoformat(), user_id)
            )
            await db.execute(
                "INSERT OR REPLACE INTO farm_notifications (user_id, task_type, data_json, is_sent) VALUES (?, 'batch', ?, 0)",
                (user_id, str(quantity))
            )
            await db.commit()

    async def collect_brewery(self, user_id: int, reward: int):
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            await db.execute(
                "UPDATE user_farm_data SET brewery_batch_size = 0, brewery_batch_timer_end = NULL WHERE user_id = ?",
                (user_id,)
            )
            await db.execute(
                'UPDATE users SET beer_rating = beer_rating + ? WHERE user_id = ?',
                (reward, user_id)
            )
            await db.commit()

    async def start_upgrade(self, user_id: int, building: str, end_time: datetime, cost: int):
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            await self._ensure_farm_data(db, user_id) 
            await db.execute(
                'UPDATE users SET beer_rating = beer_rating - ? WHERE user_id = ?',
                (cost, user_id)
            )
            if building == 'field':
                cursor = await db.execute("SELECT field_level FROM user_farm_data WHERE user_id = ?", (user_id,))
                level_row = await cursor.fetchone()
                level = level_row[0] if level_row else 1 
                await db.execute(
                    "UPDATE user_farm_data SET field_upgrade_timer_end = ? WHERE user_id = ?",
                    (end_time.isoformat(), user_id)
                )
                await db.execute(
                    "INSERT OR REPLACE INTO farm_notifications (user_id, task_type, data_json, is_sent) VALUES (?, 'field_upgrade', ?, 0)",
                    (user_id, str(level + 1))
                )
            else: # brewery
                cursor = await db.execute("SELECT brewery_level FROM user_farm_data WHERE user_id = ?", (user_id,))
                level_row = await cursor.fetchone()
                level = level_row[0] if level_row else 1 
                await db.execute(
                    "UPDATE user_farm_data SET brewery_upgrade_timer_end = ? WHERE user_id = ?",
                    (end_time.isoformat(), user_id)
                )
                await db.execute(
                    "INSERT OR REPLACE INTO farm_notifications (user_id, task_type, data_json, is_sent) VALUES (?, 'brewery_upgrade', ?, 0)",
                    (user_id, str(level + 1))
                )
            await db.commit()

    async def finish_upgrade(self, user_id: int, building: str):
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            if building == 'field':
                await db.execute(
                    "UPDATE user_farm_data SET field_level = field_level + 1, field_upgrade_timer_end = NULL WHERE user_id = ?",
                    (user_id,)
                )
            else: # brewery
                await db.execute(
                    "UPDATE user_farm_data SET brewery_level = brewery_level + 1, brewery_upgrade_timer_end = NULL WHERE user_id = ?",
                    (user_id,)
                )
            await db.commit()

    async def get_pending_notifications(self) -> List[Tuple]:
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            now = datetime.now()
            cursor_field = await db.execute(
                "SELECT T1.user_id, T1.task_type, T1.data_json FROM farm_notifications T1 "
                "JOIN user_farm_data T2 ON T1.user_id = T2.user_id "
                "WHERE T1.task_type = 'field_upgrade' AND T1.is_sent = 0 AND T2.field_upgrade_timer_end <= ?",
                (now.isoformat(),)
            )
            field_tasks = await cursor_field.fetchall()
            cursor_brewery = await db.execute(
                "SELECT T1.user_id, T1.task_type, T1.data_json FROM farm_notifications T1 "
                "JOIN user_farm_data T2 ON T1.user_id = T2.user_id "
                "WHERE T1.task_type = 'brewery_upgrade' AND T1.is_sent = 0 AND T2.brewery_upgrade_timer_end <= ?",
                (now.isoformat(),)
            )
            brewery_tasks = await cursor_brewery.fetchall()
            cursor_batch = await db.execute(
                "SELECT T1.user_id, T1.task_type, T1.data_json FROM farm_notifications T1 "
                "JOIN user_farm_data T2 ON T1.user_id = T2.user_id "
                "WHERE T1.task_type = 'batch' AND T1.is_sent = 0 AND T2.brewery_batch_timer_end <= ?",
                (now.isoformat(),)
            )
            batch_tasks = await cursor_batch.fetchall()
            all_tasks = field_tasks + brewery_tasks + batch_tasks
            return [(uid, ttype, int(data)) for uid, ttype, data in all_tasks if data is not None]

    async def mark_notification_sent(self, user_id: int, task_type: str):
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            await db.execute(
                "UPDATE farm_notifications SET is_sent = 1 WHERE user_id = ? AND task_type = ?",
                (user_id, task_type)
            )
            await db.commit()

    async def get_pending_crop_notifications(self) -> List[Tuple]:
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            now_iso = datetime.now().isoformat()
            cursor = await db.execute(
                "SELECT user_id, plot_num, crop_id FROM user_farm_plots "
                "WHERE ready_time <= ? AND (notification_sent = 0 OR notification_sent IS NULL)",
                (now_iso,)
            )
            return await cursor.fetchall()

    async def mark_crop_notification_sent(self, user_id: int, plot_num: int):
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            await db.execute(
                "UPDATE user_farm_plots SET notification_sent = 1 WHERE user_id = ? AND plot_num = ?",
                (user_id, plot_num)
            )
            await db.commit()
            
    # --- ✅✅✅ НОВЫЕ ФУНКЦИИ (Доска Заказов) ✅✅✅ ---
    
    async def check_and_reset_orders(self, user_id: int):
        """
        Проверяет, прошел ли 24-часовой таймер. 
        Если да, стирает старые и генерирует 3 новых заказа.
        """
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            await self._ensure_farm_data(db, user_id)
            
            # (Используем get_user_farm_data, который мы изменили)
            farm_data = await self.get_user_farm_data(user_id) 
            
            last_reset_str = farm_data.get('last_orders_reset')
            needs_reset = True
            
            if last_reset_str:
                try:
                    last_reset_time = datetime.fromisoformat(last_reset_str)
                    if (datetime.now() - last_reset_time) < timedelta(hours=24):
                        needs_reset = False
                except ValueError:
                    logging.warning(f"Неверный формат даты сброса у {user_id}")
            
            if not needs_reset:
                return # (Сброс еще не нужен)

            logging.info(f"Сброс Доски Заказов для {user_id}...")
            
            # (Стираем старые заказы)
            await db.execute("DELETE FROM user_farm_orders WHERE user_id = ?", (user_id,))
            
            # (Генерируем 3 новых ID из farm_config.py)
            new_order_ids = get_random_orders(3)
            orders_to_insert = []
            
            for i, order_id in enumerate(new_order_ids):
                slot_id = i + 1 # (Слот 1, 2, 3)
                orders_to_insert.append((user_id, slot_id, order_id, 0)) # is_completed = 0
            
            await db.executemany(
                "INSERT INTO user_farm_orders (user_id, slot_id, order_id, is_completed) VALUES (?, ?, ?, ?)",
                orders_to_insert
            )
            
            # (Обновляем таймер сброса)
            await db.execute(
                "UPDATE user_farm_data SET last_orders_reset = ? WHERE user_id = ?",
                (datetime.now().isoformat(), user_id)
            )
            
            await db.commit()

    async def get_user_orders(self, user_id: int) -> List[Tuple]:
        """Возвращает 3 текущих заказа (slot_id, order_id, is_completed)."""
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            cursor = await db.execute(
                "SELECT slot_id, order_id, is_completed FROM user_farm_orders WHERE user_id = ? ORDER BY slot_id",
                (user_id,)
            )
            return await cursor.fetchall()

    async def complete_order(self, user_id: int, slot_id: int) -> bool:
        """Помечает заказ как выполненный. Возвращает False, если уже был выполнен."""
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            await db.execute(
                "UPDATE user_farm_orders SET is_completed = 1 WHERE user_id = ? AND slot_id = ? AND is_completed = 0",
                (user_id, slot_id)
            )
            
            changes_cursor = await db.execute("SELECT changes()")
            changes = (await changes_cursor.fetchone())[0]
            
            await db.commit()
            
            if changes == 0:
                logging.warning(f"Попытка дважды выполнить заказ: {user_id}, слот {slot_id}")
                return False
            return True
    # --- ---
