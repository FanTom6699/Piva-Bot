# database.py
import aiosqlite
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Tuple
import json

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
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            
            # --- Таблицы Юзеров, Чатов, Настроек (У тебя уже есть) ---
            await db.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY, first_name TEXT, last_name TEXT,
                    username TEXT, beer_rating INTEGER DEFAULT 0, last_beer_time TEXT,
                    registration_date TEXT
                )
            ''')
            # (Миграция: Добавляем registration_date, если нет)
            try:
                await db.execute("ALTER TABLE users ADD COLUMN registration_date TEXT")
                logging.info("Миграция: Добавлен столбец 'registration_date' в 'users'.")
            except aiosqlite.OperationalError:
                pass # (Столбец уже существует)

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
            
            # --- ✅ НОВЫЕ ТАБЛИЦЫ ФЕРМЫ ---
            
            # (Хранит Уровни, Таймеры Постройки, Таймеры Варки)
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
            
            # (Хранит Инвентарь: Зерно, Хмель, Семена)
            await db.execute('''
                CREATE TABLE IF NOT EXISTS user_farm_inventory (
                    user_id INTEGER,
                    item_id TEXT,
                    quantity INTEGER,
                    PRIMARY KEY (user_id, item_id)
                )
            ''')

            # (Хранит Грядки: Что растет и когда)
            await db.execute('''
                CREATE TABLE IF NOT EXISTS user_farm_plots (
                    user_id INTEGER,
                    plot_num INTEGER,
                    crop_id TEXT,
                    ready_time TEXT,
                    PRIMARY KEY (user_id, plot_num)
                )
            ''')
            
            # (Хранит Заказы: 3 заказа и их статус)
            await db.execute('''
                CREATE TABLE IF NOT EXISTS user_farm_orders (
                    user_id INTEGER,
                    slot_id INTEGER,
                    order_id TEXT,
                    is_completed INTEGER DEFAULT 0,
                    PRIMARY KEY (user_id, slot_id)
                )
            ''')
            # (Хранит дату сброса заказов)
            await db.execute('''
                CREATE TABLE IF NOT EXISTS user_farm_order_timers (
                    user_id INTEGER PRIMARY KEY,
                    next_reset_time TEXT
                )
            ''')
            
            # (Хранит Уведомления)
            await db.execute('''
                CREATE TABLE IF NOT EXISTS farm_notifications (
                    user_id INTEGER,
                    task_type TEXT,
                    is_sent INTEGER DEFAULT 0,
                    data_json TEXT,
                    PRIMARY KEY (user_id, task_type)
                )
            ''')

            # --- Таблица Настроек (У тебя уже есть) ---
            await db.execute('''
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value INTEGER)
            ''')
            
            # (Миграция: Добавляем настройки Мафии, если их нет)
            mafia_settings = [
                ('mafia_min_players', 5), ('mafia_max_players', 10), ('mafia_lobby_timer', 120),
                ('mafia_night_timer', 30), ('mafia_day_timer', 60), ('mafia_vote_timer', 45),
                ('mafia_win_reward', 100), ('mafia_lose_reward', 10),
                ('mafia_win_authority', 5), ('mafia_lose_authority', 1)
            ]
            
            # (Стандартные настройки)
            default_settings = [
                ('beer_cooldown', 7200), ('jackpot_chance', 100), ('roulette_cooldown', 30),
                ('roulette_min_bet', 10), ('roulette_max_bet', 1000), ('ladder_min_bet', 20),
                ('ladder_max_bet', 1000), ('raid_boss_health', 10000), ('raid_reward_pool', 5000),
                ('raid_duration_hours', 24), ('raid_hit_cooldown_minutes', 10), ('raid_strong_hit_cost', 50),
                ('raid_strong_hit_damage_min', 150), ('raid_strong_hit_damage_max', 300),
                ('raid_normal_hit_damage_min', 50), ('raid_normal_hit_damage_max', 100),
                ('raid_reminder_hours', 4)
            ] + mafia_settings

            await db.executemany("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", default_settings)
            
            await db.commit()
            logging.info("Миграция базы данных завершена.")

    # --- (Старые функции: Юзеры, Рейтинг, Чаты, Джекпот...) ---

    async def user_exists(self, user_id: int) -> bool:
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            cursor = await db.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,))
            return await cursor.fetchone() is not None

    async def add_user(self, user_id: int, first_name: str, last_name: str, username: str):
        now_iso = datetime.now().isoformat()
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            await db.execute(
                "INSERT OR IGNORE INTO users (user_id, first_name, last_name, username, beer_rating, registration_date) VALUES (?, ?, ?, ?, 0, ?)",
                (user_id, first_name, last_name, username, now_iso)
            )
            await db.commit()

    async def get_user_profile(self, user_id: int) -> Tuple[str, str, str, int, str]:
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            cursor = await db.execute("SELECT first_name, last_name, username, beer_rating, registration_date FROM users WHERE user_id = ?", (user_id,))
            return await cursor.fetchone()

    async def get_user_beer_rating(self, user_id: int) -> int:
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            cursor = await db.execute("SELECT beer_rating FROM users WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def change_rating(self, user_id: int, amount: int):
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            await db.execute("UPDATE users SET beer_rating = beer_rating + ? WHERE user_id = ?", (amount, user_id))
            await db.commit()

    async def get_last_beer_time(self, user_id: int) -> datetime | None:
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            cursor = await db.execute("SELECT last_beer_time FROM users WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            return datetime.fromisoformat(row[0]) if row and row[0] else None

    async def update_last_beer_time(self, user_id: int):
        now_iso = datetime.now().isoformat()
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            await db.execute("UPDATE users SET last_beer_time = ? WHERE user_id = ?", (now_iso, user_id))
            await db.commit()

    async def get_top_users(self, limit: int = 10) -> List[Tuple[str, str, int]]:
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            cursor = await db.execute(
                "SELECT first_name, last_name, beer_rating FROM users ORDER BY beer_rating DESC LIMIT ?", (limit,)
            )
            return await cursor.fetchall()

    async def get_jackpot(self) -> int:
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            cursor = await db.execute("SELECT value FROM game_data WHERE key = 'jackpot'")
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def update_jackpot(self, amount: int):
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            await db.execute(
                "INSERT OR REPLACE INTO game_data (key, value) VALUES ('jackpot', COALESCE((SELECT value FROM game_data WHERE key = 'jackpot'), 0) + ?)",
                (amount,)
            )
            await db.commit()

    async def reset_jackpot(self):
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            await db.execute("REPLACE INTO game_data (key, value) VALUES ('jackpot', 0)")
            await db.commit()

    async def add_chat(self, chat_id: int, title: str):
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            await db.execute("INSERT OR REPLACE INTO chats (chat_id, title) VALUES (?, ?)", (chat_id, title))
            await db.commit()

    # --- (Старые функции: Рейды) ---
    
    async def get_all_active_raids(self) -> List[Tuple]:
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            cursor = await db.execute("SELECT * FROM active_raids")
            return await cursor.fetchall()

    async def get_active_raid(self, chat_id: int) -> Tuple | None:
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            cursor = await db.execute("SELECT * FROM active_raids WHERE chat_id = ?", (chat_id,))
            return await cursor.fetchone()

    async def start_raid(self, chat_id: int, message_id: int, boss_max_health: int, reward_pool: int, end_time: datetime):
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            await db.execute("DELETE FROM raid_participants WHERE raid_id = ?", (chat_id,))
            await db.execute(
                "INSERT OR REPLACE INTO active_raids (chat_id, message_id, boss_health, boss_max_health, reward_pool, end_time) VALUES (?, ?, ?, ?, ?, ?)",
                (chat_id, message_id, boss_max_health, boss_max_health, reward_pool, end_time.isoformat())
            )
            await db.commit()

    async def update_raid_health(self, chat_id: int, damage: int):
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            await db.execute("UPDATE active_raids SET boss_health = boss_health - ? WHERE chat_id = ?", (damage, chat_id))
            await db.commit()

    async def end_raid(self, chat_id: int):
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            await db.execute("DELETE FROM active_raids WHERE chat_id = ?", (chat_id,))
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
            
    async def delete_raid_participants(self, chat_id: int):
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            await db.execute("DELETE FROM raid_participants WHERE raid_id = ?", (chat_id,))
            await db.commit()

    # --- (Старые функции: Настройки) ---
    
    async def get_all_settings(self) -> Dict[str, int]:
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            cursor = await db.execute("SELECT key, value FROM settings")
            rows = await cursor.fetchall()
            return {row[0]: row[1] for row in rows}

    async def update_setting(self, key: str, value: int):
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            await db.execute("REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
            await db.commit()
            
    async def get_setting(self, key: str) -> int | None:
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            cursor = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = await cursor.fetchone()
            return row[0] if row else None
            
    # --- ✅ НОВЫЕ ФУНКЦИИ (Ферма: Инвентарь) ---
    
    async def _ensure_farm_inventory(self, db, user_id: int):
        """(Внутренний) Гарантирует, что у юзера есть инвентарь (для DEFAULT_INVENTORY)."""
        for item_id, default_qty in DEFAULT_INVENTORY.items():
            await db.execute(
                "INSERT OR IGNORE INTO user_farm_inventory (user_id, item_id, quantity) VALUES (?, ?, ?)",
                (user_id, item_id, default_qty)
            )
    
    async def get_user_inventory(self, user_id: int) -> Dict[str, int]:
        """Получает инвентарь юзера. Если юзера нет, создает инвентарь."""
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            await self._ensure_farm_inventory(db, user_id)
            cursor = await db.execute("SELECT item_id, quantity FROM user_farm_inventory WHERE user_id = ?", (user_id,))
            rows = await cursor.fetchall()
            # (Обновляем инвентарь из DEFAULT, если в БД нет новых предметов)
            inventory = DEFAULT_INVENTORY.copy()
            inventory.update({item_id: qty for item_id, qty in rows})
            return inventory

    async def modify_inventory(self, user_id: int, item_id: str, amount: int) -> bool:
        """Изменяет кол-во (e.g., +1, -5). Возвращает False, если ушел в минус."""
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            await self._ensure_farm_inventory(db, user_id)
            
            # (Защита от списания в минус)
            if amount < 0:
                cursor = await db.execute(
                    "SELECT quantity FROM user_farm_inventory WHERE user_id = ? AND item_id = ?",
                    (user_id, item_id)
                )
                row = await cursor.fetchone()
                current_qty = row[0] if row else 0
                if current_qty < abs(amount):
                    logging.warning(f"[DB Farm] Неудача: {user_id} пытался потратить {abs(amount)}x {item_id}, но есть {current_qty}")
                    return False
            
            await db.execute(
                "UPDATE user_farm_inventory SET quantity = quantity + ? WHERE user_id = ? AND item_id = ?",
                (amount, user_id, item_id)
            )
            await db.commit()
            return True

    # --- ✅ НОВЫЕ ФУНКЦИИ (Ферма: Данные) ---

    async def get_user_farm_data(self, user_id: int) -> Dict[str, Any]:
        """Получает данные о ферме (уровни, таймеры)."""
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            # (Гарантируем, что юзер есть в таблице)
            await db.execute("INSERT OR IGNORE INTO user_farm_data (user_id) VALUES (?)", (user_id,))
            
            cursor = await db.execute("SELECT * FROM user_farm_data WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            
            if not row:
                # (Это не должно случиться из-за INSERT OR IGNORE, но на всякий случай)
                return {'field_level': 1, 'brewery_level': 1} 

            # (Конвертируем ISO-строки в datetime, если они есть)
            return {
                'user_id': row[0],
                'field_level': row[1],
                'brewery_level': row[2],
                'field_upgrade_timer_end': datetime.fromisoformat(row[3]) if row[3] else None,
                'brewery_upgrade_timer_end': datetime.fromisoformat(row[4]) if row[4] else None,
                'brewery_batch_size': row[5],
                'brewery_batch_timer_end': datetime.fromisoformat(row[6]) if row[6] else None,
            }

    # --- ✅ НОВЫЕ ФУНКЦИИ (Ферма: Поле) ---

    async def get_user_plots(self, user_id: int) -> List[Tuple[int, str, str]]:
        """Получает список активных грядок (plot_num, crop_id, ready_time_iso)."""
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            cursor = await db.execute(
                "SELECT plot_num, crop_id, ready_time FROM user_farm_plots WHERE user_id = ?", (user_id,)
            )
            return await cursor.fetchall()

    async def plant_crop(self, user_id: int, plot_num: int, crop_id: str, ready_time: datetime) -> bool:
        """Сажает семя. Возвращает False, если грядка была занята (UNIQUE constraint)."""
        try:
            async with aiosqlite.connect(self.db_name, timeout=20) as db:
                await db.execute(
                    "INSERT INTO user_farm_plots (user_id, plot_num, crop_id, ready_time) VALUES (?, ?, ?, ?)",
                    (user_id, plot_num, crop_id, ready_time.isoformat())
                )
                await db.commit()
                return True
        except aiosqlite.IntegrityError:
            logging.warning(f"[DB Farm] {user_id} пытался посадить на занятую грядку {plot_num}")
            return False

    async def harvest_plot(self, user_id: int, plot_num: int) -> str | None:
        """Собирает урожай. Возвращает ID семени (str) или None, если грядка пуста/не готова."""
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            # (Проверяем, что грядка готова)
            cursor_check = await db.execute(
                "SELECT crop_id, ready_time FROM user_farm_plots WHERE user_id = ? AND plot_num = ?",
                (user_id, plot_num)
            )
            row = await cursor_check.fetchone()
            
            if not row:
                return None # (Грядка пуста)
            
            crop_id, ready_time_iso = row
            if datetime.now() < datetime.fromisoformat(ready_time_iso):
                return None # (Еще не готово)

            # (Удаляем грядку)
            await db.execute(
                "DELETE FROM user_farm_plots WHERE user_id = ? AND plot_num = ?",
                (user_id, plot_num)
            )
            await db.commit()
            return crop_id

    # --- ✅ НОВЫЕ ФУНКЦИИ (Ферма: Пивоварня) ---

    async def start_brewing(self, user_id: int, batch_size: int, end_time: datetime):
        """(Пивоварня) Начинает варку."""
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            await db.execute(
                "UPDATE user_farm_data SET brewery_batch_size = ?, brewery_batch_timer_end = ? WHERE user_id = ?",
                (batch_size, end_time.isoformat(), user_id)
            )
            # (Регистрируем уведомление)
            await db.execute(
                "INSERT OR REPLACE INTO farm_notifications (user_id, task_type, is_sent, data_json) VALUES (?, 'batch', 0, ?)",
                (user_id, str(batch_size))
            )
            await db.commit()

    async def collect_brewery(self, user_id: int, rating_reward: int):
        """(Пивоварня) Собирает награду и сбрасывает таймеры."""
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            # (Сбрасываем таймеры)
            await db.execute(
                "UPDATE user_farm_data SET brewery_batch_size = 0, brewery_batch_timer_end = NULL WHERE user_id = ?",
                (user_id,)
            )
            # (Начисляем рейтинг)
            await db.execute(
                "UPDATE users SET beer_rating = beer_rating + ? WHERE user_id = ?",
                (rating_reward, user_id)
            )
            # (Удаляем уведомление)
            await db.execute(
                "DELETE FROM farm_notifications WHERE user_id = ? AND task_type = 'batch'",
                (user_id,)
            )
            await db.commit()

    # --- ✅ НОВЫЕ ФУНКЦИИ (Ферма: Улучшения) ---
    
    async def start_upgrade(self, user_id: int, building_code: str, end_time: datetime, cost: int):
        """Начинает улучшение (field или brewery)."""
        
        timer_column = "field_upgrade_timer_end" if building_code == "field" else "brewery_upgrade_timer_end"
        
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            # (Списываем рейтинг)
            await db.execute(
                "UPDATE users SET beer_rating = beer_rating - ? WHERE user_id = ?",
                (cost, user_id)
            )
            # (Устанавливаем таймер)
            await db.execute(
                f"UPDATE user_farm_data SET {timer_column} = ? WHERE user_id = ?",
                (end_time.isoformat(), user_id)
            )
            
            # (Регистрируем уведомление)
            task_type = "field_upgrade" if building_code == "field" else "brewery_upgrade"
            await db.execute(
                "INSERT OR REPLACE INTO farm_notifications (user_id, task_type, is_sent, data_json) VALUES (?, ?, 0, ?)",
                (user_id, task_type, "1") # (data_json не нужен, но ставим 1)
            )
            await db.commit()

    async def check_and_apply_upgrades(self, user_id: int) -> Dict[str, bool]:
        """(Farm Updater) Проверяет таймеры, повышает уровень, если готово. Возвращает True, если что-то улучшилось."""
        
        farm_data = await self.get_user_farm_data(user_id)
        now = datetime.now()
        updated = {"field": False, "brewery": False}
        
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            
            # (Проверяем Поле)
            if farm_data['field_upgrade_timer_end'] and now >= farm_data['field_upgrade_timer_end']:
                await db.execute(
                    "UPDATE user_farm_data SET field_level = field_level + 1, field_upgrade_timer_end = NULL WHERE user_id = ?",
                    (user_id,)
                )
                await db.execute(
                    "DELETE FROM farm_notifications WHERE user_id = ? AND task_type = 'field_upgrade'",
                    (user_id,)
                )
                updated["field"] = True
            
            # (Проверяем Пивоварню)
            if farm_data['brewery_upgrade_timer_end'] and now >= farm_data['brewery_upgrade_timer_end']:
                await db.execute(
                    "UPDATE user_farm_data SET brewery_level = brewery_level + 1, brewery_upgrade_timer_end = NULL WHERE user_id = ?",
                    (user_id,)
                )
                await db.execute(
                    "DELETE FROM farm_notifications WHERE user_id = ? AND task_type = 'brewery_upgrade'",
                    (user_id,)
                )
                updated["brewery"] = True
                
            if updated["field"] or updated["brewery"]:
                await db.commit()
                
        return updated

    # --- ✅ НОВЫЕ ФУНКЦИИ (Ферма: Доска Заказов) ---
    
    async def check_and_reset_orders(self, user_id: int):
        """(Доска Заказов) Проверяет таймер. Если 24ч прошли, удаляет старые и таймер."""
        now = datetime.now()
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            cursor = await db.execute("SELECT next_reset_time FROM user_farm_order_timers WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            
            if row and datetime.fromisoformat(row[0]) <= now:
                # (Время вышло, чистим)
                await db.execute("DELETE FROM user_farm_orders WHERE user_id = ?", (user_id,))
                await db.execute("DELETE FROM user_farm_order_timers WHERE user_id = ?", (user_id,))
                await db.commit()

    async def get_user_orders(self, user_id: int) -> List[Tuple[int, str, int]]:
        """(Доска Заказов) Получает 3 заказа. Если их нет, создает."""
        
        # (Импорт здесь, чтобы избежать цикличного импорта)
        from .farm_config import get_random_orders 
        
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            cursor = await db.execute(
                "SELECT slot_id, order_id, is_completed FROM user_farm_orders WHERE user_id = ?", (user_id,)
            )
            orders = await cursor.fetchall()
            
            if orders:
                return orders
                
            # (Заказов нет, генерируем)
            new_order_ids = get_random_orders(count=3)
            orders_to_insert = [
                (user_id, 1, new_order_ids[0], 0),
                (user_id, 2, new_order_ids[1], 0),
                (user_id, 3, new_order_ids[2], 0)
            ]
            
            await db.executemany(
                "INSERT INTO user_farm_orders (user_id, slot_id, order_id, is_completed) VALUES (?, ?, ?, ?)",
                orders_to_insert
            )
            
            # (Устанавливаем таймер сброса)
            reset_time = datetime.now() + timedelta(hours=24)
            await db.execute(
                "INSERT OR REPLACE INTO user_farm_order_timers (user_id, next_reset_time) VALUES (?, ?)",
                (user_id, reset_time.isoformat())
            )
            
            await db.commit()
            return [(o[1], o[2], o[3]) for o in orders_to_insert] # (slot_id, order_id, is_completed)

    async def complete_order(self, user_id: int, slot_id: int) -> bool:
        """(Доска Заказов) Помечает заказ как выполненный. False, если уже выполнен."""
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            # (Проверяем, что он не выполнен)
            cursor_check = await db.execute(
                "SELECT is_completed FROM user_farm_orders WHERE user_id = ? AND slot_id = ?", (user_id, slot_id)
            )
            row = await cursor_check.fetchone()
            
            if not row or row[0] == 1:
                return False # (Уже выполнен или не существует)
            
            await db.execute(
                "UPDATE user_farm_orders SET is_completed = 1 WHERE user_id = ? AND slot_id = ?",
                (user_id, slot_id)
            )
            await db.commit()
            return True

    # --- ✅ НОВЫЕ ФУНКЦИИ (Ферма: Уведомления) ---

    async def get_pending_notifications(self, now: datetime) -> List[Tuple[int, str, str]]:
        """(Для farm_updater) Находит все НЕОТПРАВЛЕННЫЕ задачи, таймер которых ВЫШЕЛ."""
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            
            # (Ищем апгрейды Поля)
            cursor_field = await db.execute(
                "SELECT T1.user_id, T1.task_type, T1.data_json FROM farm_notifications T1 "
                "JOIN user_farm_data T2 ON T1.user_id = T2.user_id "
                "WHERE T1.task_type = 'field_upgrade' AND T1.is_sent = 0 AND T2.field_upgrade_timer_end <= ?",
                (now.isoformat(),)
            )
            field_tasks = await cursor_field.fetchall()
            
            # (Ищем апгрейды Пивоварни)
            cursor_brewery = await db.execute(
                "SELECT T1.user_id, T1.task_type, T1.data_json FROM farm_notifications T1 "
                "JOIN user_farm_data T2 ON T1.user_id = T2.user_id "
                "WHERE T1.task_type = 'brewery_upgrade' AND T1.is_sent = 0 AND T2.brewery_upgrade_timer_end <= ?",
                (now.isoformat(),)
            )
            brewery_tasks = await cursor_brewery.fetchall()
            
            # (Ищем Варку)
            cursor_batch = await db.execute(
                "SELECT T1.user_id, T1.task_type, T1.data_json FROM farm_notifications T1 "
                "JOIN user_farm_data T2 ON T1.user_id = T2.user_id "
                "WHERE T1.task_type = 'batch' AND T1.is_sent = 0 AND T2.brewery_batch_timer_end <= ?",
                (now.isoformat(),)
            )
            batch_tasks = await cursor_batch.fetchall()
            
            all_tasks = field_tasks + brewery_tasks + batch_tasks
            
            # (data_json сейчас хранит int/str, конвертируем в str для совместимости)
            return [(uid, ttype, str(data)) for uid, ttype, data in all_tasks if data is not None]

    async def mark_notification_sent(self, user_id: int, task_type: str):
        """(Для farm_updater) Помечает уведомление как отправленное."""
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            await db.execute(
                "UPDATE farm_notifications SET is_sent = 1 WHERE user_id = ? AND task_type = ?",
                (user_id, task_type)
            )
            await db.commit()
            
    # --- (Старые функции: Мафия) ---
    
    # (Лобби)
    async def create_mafia_game(self, chat_id: int, message_id: int, creator_id: int):
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            await db.execute("DELETE FROM mafia_players WHERE chat_id = ?", (chat_id,))
            await db.execute(
                "INSERT OR REPLACE INTO mafia_games (chat_id, message_id, creator_id, status) VALUES (?, ?, ?, 'lobby')",
                (chat_id, message_id, creator_id)
            )
            await db.commit()

    async def get_mafia_game(self, chat_id: int) -> Tuple | None:
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            cursor = await db.execute("SELECT * FROM mafia_games WHERE chat_id = ?", (chat_id,))
            return await cursor.fetchone()

    async def update_mafia_game_status(self, chat_id: int, status: str):
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            await db.execute("UPDATE mafia_games SET status = ? WHERE chat_id = ?", (status, chat_id))
            await db.commit()
            
    async def update_mafia_message_id(self, chat_id: int, message_id: int):
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            await db.execute("UPDATE mafia_games SET message_id = ? WHERE chat_id = ?", (message_id,))
            await db.commit()

    async def delete_mafia_game(self, chat_id: int):
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            await db.execute("DELETE FROM mafia_games WHERE chat_id = ?", (chat_id,))
            await db.execute("DELETE FROM mafia_players WHERE chat_id = ?", (chat_id,))
            await db.commit()

    # (Игроки)
    async def add_mafia_player(self, chat_id: int, user_id: int, first_name: str) -> bool:
        try:
            async with aiosqlite.connect(self.db_name, timeout=20) as db:
                await db.execute(
                    "INSERT INTO mafia_players (chat_id, user_id, first_name, is_alive) VALUES (?, ?, ?, 1)",
                    (chat_id, user_id, first_name)
                )
                await db.commit()
                return True
        except aiosqlite.IntegrityError:
            return False # (Уже в игре)

    async def remove_mafia_player(self, chat_id: int, user_id: int) -> bool:
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            await db.execute("DELETE FROM mafia_players WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
            changes = db.total_changes
            await db.commit()
            return changes > 0

    async def get_mafia_players(self, chat_id: int) -> List[Tuple[int, str, int]]:
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            cursor = await db.execute("SELECT user_id, first_name, is_alive FROM mafia_players WHERE chat_id = ?", (chat_id,))
            return await cursor.fetchall()
            
    async def get_mafia_player_count(self, chat_id: int) -> int:
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            cursor = await db.execute("SELECT COUNT(user_id) FROM mafia_players WHERE chat_id = ?", (chat_id,))
            row = await cursor.fetchone()
            return row[0] if row else 0

    # (Роли)
    async def assign_mafia_roles(self, chat_id: int, roles_map: Dict[int, str]):
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            for user_id, role_name in roles_map.items():
                await db.execute(
                    "UPDATE mafia_players SET role = ? WHERE chat_id = ? AND user_id = ?",
                    (role_name, chat_id, user_id)
                )
            await db.commit()
            
    async def get_mafia_roles(self, chat_id: int) -> List[Tuple[int, str, int]]:
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            cursor = await db.execute(
                "SELECT user_id, role, is_alive FROM mafia_players WHERE chat_id = ?", (chat_id,)
            )
            return await cursor.fetchall()
            
    # (Голосование/Убийство)
    async def kill_mafia_player(self, chat_id: int, user_id: int) -> str | None:
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            # (Проверяем, жив ли он)
            cursor = await db.execute(
                "SELECT role FROM mafia_players WHERE chat_id = ? AND user_id = ? AND is_alive = 1", (chat_id, user_id)
            )
            row = await cursor.fetchone()
            if not row:
                return None # (Уже мертв или не найден)
                
            role = row[0]
            await db.execute(
                "UPDATE mafia_players SET is_alive = 0 WHERE chat_id = ? AND user_id = ?", (chat_id, user_id)
            )
            await db.commit()
            return role
