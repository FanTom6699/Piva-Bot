# database.py
import aiosqlite
import logging
from datetime import datetime
from typing import Dict, Any, List, Tuple

# --- ✅ НОВЫЕ КОНСТАНТЫ ДЛЯ ФЕРМЫ ---
DEFAULT_INVENTORY = {
    'зерно': 0, 'хмель': 0,
    'семя_зерна': 5, 'семя_хмеля': 3
}

class Database:
    def __init__(self, db_name='bot_database.db'):
        self.db_name = db_name

    async def initialize(self):
        logging.info("Запуск миграции базы данных...")
        async with aiosqlite.connect(self.db_name) as db:
            # --- Таблицы Юзеров, Чатов, Настроек (У тебя уже есть) ---
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
            
            # --- Таблицы Рейдов (У тебя уже есть) ---
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
            
            # --- ✅✅✅ НОВЫЕ ТАБЛИЦЫ ДЛЯ ФЕРМЫ ✅✅✅ ---
            await db.execute('''
                CREATE TABLE IF NOT EXISTS user_farm_data (
                    user_id INTEGER PRIMARY KEY,
                    field_level INTEGER DEFAULT 1,
                    brewery_level INTEGER DEFAULT 1,
                    field_upgrade_timer_end TEXT,
                    brewery_upgrade_timer_end TEXT,
                    brewery_batch_size INTEGER DEFAULT 0,
                    brewery_batch_timer_end TEXT
                )
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS user_farm_plots (
                    plot_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    plot_num INTEGER,
                    crop_id TEXT,
                    ready_time TEXT,
                    UNIQUE(user_id, plot_num)
                )
            ''')
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
            # --- ✅✅✅ КОНЕЦ НОВЫХ ТАБЛИЦ ✅✅✅ ---
            
            # --- Миграция Настроек ---
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

    # --- Функции Юзеров (Без изменений) ---
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
            # --- ✅ НОВОЕ: Сразу выдаем инвентарь фермы ---
            await self._ensure_inventory(db, user_id)
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

    async def get_user_by_id(self, user_id: int):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute('SELECT first_name, last_name, username FROM users WHERE user_id = ?', (user_id,))
            row = await cursor.fetchone()
            if row:
                # (Возвращаем Имя, Юзернейм для /give)
                return row[0] or row[1], row[2] 
            return None

    async def get_user_by_username(self, username: str):
        username = username.lstrip('@')
        async with aiosqlite.connect(self.db_name) as db:
            # (Возвращаем ID и Имя для /give)
            cursor = await db.execute('SELECT user_id, first_name FROM users WHERE username = ?', (username,))
            return await cursor.fetchone()

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

    # --- Функции Настроек (Без изменений) ---
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
    
    # --- Функции Рейдов (Без изменений) ---
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

    # --- ✅✅✅ НОВЫЕ ФУНКЦИИ ФЕРМЫ (Которые чинят кнопки) ✅✅✅ ---
    
    async def _ensure_farm_data(self, db, user_id: int):
        """(Приватный) Убеждается, что у юзера есть запись в user_farm_data."""
        await db.execute(
            "INSERT OR IGNORE INTO user_farm_data (user_id) VALUES (?)",
            (user_id,)
        )

    async def _ensure_inventory(self, db, user_id: int):
        """(Приватный) Выдает юзеру базовый инвентарь, если у него его нет."""
        for item_id, quantity in DEFAULT_INVENTORY.items():
            await db.execute(
                "INSERT OR IGNORE INTO user_farm_inventory (user_id, item_id, quantity) VALUES (?, ?, ?)",
                (user_id, item_id, quantity)
            )
    
    async def get_user_farm_data(self, user_id: int) -> Dict[str, Any]:
        """Получает все данные о ферме юзера (уровни, таймеры)."""
        async with aiosqlite.connect(self.db_name) as db:
            await self._ensure_farm_data(db, user_id)
            cursor = await db.execute("SELECT * FROM user_farm_data WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            if not row:
                return {}
            
            def to_datetime_safe(iso_str):
                return datetime.fromisoformat(iso_str) if iso_str else None

            return {
                'user_id': row[0],
                'field_level': row[1],
                'brewery_level': row[2],
                'field_upgrade_timer_end': to_datetime_safe(row[3]),
                'brewery_upgrade_timer_end': to_datetime_safe(row[4]),
                'brewery_batch_size': row[5],
                'brewery_batch_timer_end': to_datetime_safe(row[6])
            }

    async def get_user_plots(self, user_id: int) -> List[Tuple]:
        """Получает все активные (засаженные) участки юзера."""
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                "SELECT plot_num, crop_id, ready_time FROM user_farm_plots WHERE user_id = ?",
                (user_id,)
            )
            return await cursor.fetchall()

    async def get_user_inventory(self, user_id: int) -> Dict[str, int]:
        """Получает инвентарь юзера (семена, урожай)."""
        async with aiosqlite.connect(self.db_name) as db:
            await self._ensure_inventory(db, user_id)
            cursor = await db.execute(
                "SELECT item_id, quantity FROM user_farm_inventory WHERE user_id = ?",
                (user_id,)
            )
            inventory = DEFAULT_INVENTORY.copy()
            inventory.update({item: qty for item, qty in await cursor.fetchall()})
            return inventory

    async def modify_inventory(self, user_id: int, item_id: str, amount: int) -> bool:
        """(✅ ВАЖНО ДЛЯ МАГАЗИНА) Изменяет кол-во предмета. Возвращает False, если не хватает."""
        async with aiosqlite.connect(self.db_name) as db:
            await self._ensure_inventory(db, user_id)
            
            await db.execute(
                """
                INSERT INTO user_farm_inventory (user_id, item_id, quantity)
                VALUES (?, ?, max(0, ?))
                ON CONFLICT(user_id, item_id) DO UPDATE SET
                quantity = max(0, quantity + excluded.quantity)
                WHERE (quantity + excluded.quantity) >= 0
                """,
                (user_id, item_id, amount)
            )
            
            changes_cursor = await db.execute("SELECT changes()")
            changes = (await changes_cursor.fetchone())[0]
            
            await db.commit()
            
            if amount < 0 and changes == 0:
                logging.warning(f"Ошибка списания: у {user_id} не хватило {item_id} (нужно {abs(amount)})")
                return False
            return True

    # --- 👇👇👇 ВОТ ЭТА ФУНКЦИЯ, КОТОРАЯ У ТЕБЯ ОТСУТСТВУЕТ 👇👇👇 ---
    async def plant_crop(self, user_id: int, plot_num: int, crop_id: str, ready_time: datetime) -> bool:
        """(✅ ВАЖНО ДЛЯ УЧАСТКОВ) Сажает урожай. Возвращает False, если участок занят."""
        async with aiosqlite.connect(self.db_name) as db:
            try:
                await db.execute(
                    "INSERT INTO user_farm_plots (user_id, plot_num, crop_id, ready_time) VALUES (?, ?, ?, ?)",
                    (user_id, plot_num, crop_id, ready_time.isoformat())
                )
                await db.commit()
                return True
            except aiosqlite.IntegrityError: # (UNIQUE constraint failed)
                logging.warning(f"Ошибка посадки: Участок {plot_num} (user {user_id}) уже занят.")
                return False
    # --- 👆👆👆 ВОТ ЭТА ФУНКЦИЯ, КОТОРАЯ У ТЕБЯ ОТСУТСТВУЕТ 👆👆👆 ---

    async def harvest_plot(self, user_id: int, plot_num: int) -> str | None:
        """Собирает урожай. Возвращает ID семени (str) или None, если пусто/не готово."""
        async with aiosqlite.connect(self.db_name) as db:
            now_iso = datetime.now().isoformat()
            cursor = await db.execute(
                "SELECT crop_id FROM user_farm_plots WHERE user_id = ? AND plot_num = ? AND ready_time <= ?",
                (user_id, plot_num, now_iso)
            )
            result = await cursor.fetchone()
            
            if not result:
                return None
                
            crop_id = result[0]
            await db.execute(
                "DELETE FROM user_farm_plots WHERE user_id = ? AND plot_num = ?",
                (user_id, plot_num)
            )
            await db.commit()
            return crop_id

    async def start_brewing(self, user_id: int, quantity: int, end_time: datetime):
        """Запускает варку в Пивоварне."""
        async with aiosqlite.connect(self.db_name) as db:
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
        """Забирает готовую варку и начисляет рейтинг."""
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                "UPDATE user_farm_data SET brewery_batch_size = 0, brewery_batch_timer_end = NULL WHERE user_id = ?",
                (user_id,)
            )
            await self.change_rating(user_id, reward)
            await db.commit()

    async def start_upgrade(self, user_id: int, building: str, end_time: datetime, cost: int):
        """Запускает апгрейд здания и списывает 🍺."""
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                'UPDATE users SET beer_rating = beer_rating - ? WHERE user_id = ?',
                (cost, user_id)
            )
            
            if building == 'field':
                cursor = await db.execute("SELECT field_level FROM user_farm_data WHERE user_id = ?", (user_id,))
                level = (await cursor.fetchone())[0]
                
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
                level = (await cursor.fetchone())[0]

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
        """Завершает апгрейд (вызывается из farm_updater)."""
        async with aiosqlite.connect(self.db_name) as db:
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
        """(Для farm_updater) Находит задачи, которые пора отправить."""
        async with aiosqlite.connect(self.db_name) as db:
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
            
            # (Конвертируем data_json (который str(level) или str(quantity)) в int)
            # Добавлена проверка на None, если data_json пуст
            return [(uid, ttype, int(data)) for uid, ttype, data in all_tasks if data is not None]

    async def mark_notification_sent(self, user_id: int, task_type: str):
        """(Для farm_updater) Помечает уведомление как отправленное."""
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                "UPDATE farm_notifications SET is_sent = 1 WHERE user_id = ? AND task_type = ?",
                (user_id, task_type)
            )
            await db.commit()
            
    # --- ✅✅✅ КОНЕЦ НОВЫХ ФУНКЦИЙ ФЕРМЫ ✅✅✅ ---
