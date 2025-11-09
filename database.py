# database.py
import aiosqlite
import logging
from datetime import datetime
from typing import Dict, Any, List, Tuple, Optional

# --- НОВЫЙ СПИСОК ПРЕДМЕТОВ (Наш План) ---
# Нам нужно знать "коды" предметов, чтобы создать инвентарь
FARM_ITEM_CODES = ['зерно', 'хмель', 'семя_зерна', 'семя_хмеля']

class Database:
    def __init__(self, db_name='bot_database.db'):
        self.db_name = db_name

    # --- ✅ НОВАЯ ФУНКЦИЯ МИГРАЦИИ (Очень Важная) ---
    async def _run_migrations(self, db: aiosqlite.Connection):
        """Безопасно добавляет новые колонки в 'users', если их нет."""
        logging.info("Запуск миграции базы данных...")
        
        # --- Миграция (Ранняя, регистрация) ---
        try:
            await db.execute("ALTER TABLE users ADD COLUMN registration_date TEXT DEFAULT NULL")
            logging.info("Колонка 'registration_date' добавлена в 'users'.")
        except aiosqlite.OperationalError as e:
            if "duplicate column name" not in str(e): raise e

        # --- Миграция "Фермы" (Уровни) ---
        try:
            await db.execute("ALTER TABLE users ADD COLUMN field_level INTEGER DEFAULT 1")
            logging.info("Колонка 'field_level' добавлена.")
        except aiosqlite.OperationalError as e:
            if "duplicate column name" not in str(e): raise e

        try:
            await db.execute("ALTER TABLE users ADD COLUMN brewery_level INTEGER DEFAULT 1")
            logging.info("Колонка 'brewery_level' добавлена.")
        except aiosqlite.OperationalError as e:
            if "duplicate column name" not in str(e): raise e

        # --- Миграция "Фермы" (Таймеры Улучшений) ---
        try:
            await db.execute("ALTER TABLE users ADD COLUMN field_upgrade_timer_end TEXT DEFAULT NULL")
            logging.info("Колонка 'field_upgrade_timer_end' добавлена.")
        except aiosqlite.OperationalError as e:
            if "duplicate column name" not in str(e): raise e

        try:
            await db.execute("ALTER TABLE users ADD COLUMN brewery_upgrade_timer_end TEXT DEFAULT NULL")
            logging.info("Колонка 'brewery_upgrade_timer_end' добавлена.")
        except aiosqlite.OperationalError as e:
            if "duplicate column name" not in str(e): raise e

        # --- Миграция "Фермы" (Пакетная Варка) ---
        try:
            await db.execute("ALTER TABLE users ADD COLUMN brewery_batch_size INTEGER DEFAULT 0")
            logging.info("Колонка 'brewery_batch_size' добавлена.")
        except aiosqlite.OperationalError as e:
            if "duplicate column name" not in str(e): raise e
            
        try:
            await db.execute("ALTER TABLE users ADD COLUMN brewery_batch_timer_end TEXT DEFAULT NULL")
            logging.info("Колонка 'brewery_batch_timer_end' добавлена.")
        except aiosqlite.OperationalError as e:
            if "duplicate column name" not in str(e): raise e

        # --- Миграция "Фермы" (Уведомления) ---
        try:
            await db.execute("ALTER TABLE users ADD COLUMN field_upgrade_notified INTEGER DEFAULT 0")
            logging.info("Колонка 'field_upgrade_notified' добавлена.")
        except aiosqlite.OperationalError as e:
            if "duplicate column name" not in str(e): raise e

        try:
            await db.execute("ALTER TABLE users ADD COLUMN brewery_upgrade_notified INTEGER DEFAULT 0")
            logging.info("Колонка 'brewery_upgrade_notified' добавлена.")
        except aiosqlite.OperationalError as e:
            if "duplicate column name" not in str(e): raise e
            
        try:
            await db.execute("ALTER TABLE users ADD COLUMN brewery_batch_notified INTEGER DEFAULT 0")
            logging.info("Колонка 'brewery_batch_notified' добавлена.")
        except aiosqlite.OperationalError as e:
            if "duplicate column name" not in str(e): raise e

        logging.info("Миграция базы данных завершена.")


    async def initialize(self):
        async with aiosqlite.connect(self.db_name) as db:
            # --- 1. Таблица Пользователей (users) ---
            await db.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY, first_name TEXT, last_name TEXT,
                    username TEXT, beer_rating INTEGER DEFAULT 0, last_beer_time TEXT
                )
            ''')
            
            # --- 2. Таблица Чатов (chats) ---
            await db.execute('''
                CREATE TABLE IF NOT EXISTS chats (chat_id INTEGER PRIMARY KEY, title TEXT)
            ''')
            
            # --- 3. Таблица Настроек (game_data) ---
            await db.execute('''
                CREATE TABLE IF NOT EXISTS game_data (key TEXT PRIMARY KEY, value INTEGER)
            ''')
            
            # --- 4. Таблицы Рейдов (active_raids, raid_participants) ---
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
            
            # --- 5. ✅✅✅ НОВЫЕ ТАБЛИЦЫ "ФЕРМЫ" (Наш План) ✅✅✅ ---
            
            # Инвентарь (Склад) - для 4 "понятных" предметов
            await db.execute('''
                CREATE TABLE IF NOT EXISTS farm_inventory (
                    user_id INTEGER NOT NULL,
                    item_id TEXT NOT NULL,
                    quantity INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY (user_id) REFERENCES users (user_id),
                    PRIMARY KEY (user_id, item_id)
                )
            ''')
            
            # Участки (Поля) - для таймеров 10/20 мин
            await db.execute('''
                CREATE TABLE IF NOT EXISTS farm_plots (
                    plot_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    plot_number INTEGER,
                    crop_type TEXT,
                    ready_time TEXT,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
            ''')
            
            # --- 6. Запуск Миграций (для старых баз) ---
            await self._run_migrations(db)

            # --- 7. Настройки по умолчанию ---
            default_settings = {
                'jackpot': 0, 'beer_cooldown': 7200, 'jackpot_chance': 150,
                'roulette_cooldown': 300, 'roulette_min_bet': 10, 'roulette_max_bet': 1000,
                'ladder_min_bet': 10, 'ladder_max_bet': 500, 'raid_boss_health': 1000,
                'raid_reward_pool': 5000, 'raid_duration_hours': 24, 'raid_hit_cooldown_minutes': 30,
                'raid_strong_hit_cost': 100, 'raid_strong_hit_damage_min': 50, 'raid_strong_hit_damage_max': 150,
                'raid_normal_hit_damage_min': 10, 'raid_normal_hit_damage_max': 30, 'raid_reminder_hours': 4
            }
            cursor = await db.execute("SELECT key FROM game_data")
            existing_keys = [row[0] for row in await cursor.fetchall()]
            for key, value in default_settings.items():
                if key not in existing_keys:
                    await db.execute("INSERT INTO game_data (key, value) VALUES (?, ?)", (key, value))
            
            await db.commit()

    # --- Функции Пользователей (Обновлено) ---

    async def user_exists(self, user_id: int) -> bool:
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,))
            return await cursor.fetchone() is not None

    async def add_user(self, user_id: int, first_name: str, last_name: str, username: str):
        now_iso = datetime.now().isoformat()
        async with aiosqlite.connect(self.db_name) as db:
            # 1. Добавляем в 'users'
            await db.execute(
                "INSERT INTO users (user_id, first_name, last_name, username, registration_date) VALUES (?, ?, ?, ?, ?)",
                (user_id, first_name, last_name, username, now_iso)
            )
            
            # 2. ✅ Сразу создаем "Склад" (Инвентарь) для 4 "понятных" предметов
            for item_id in FARM_ITEM_CODES:
                await db.execute(
                    "INSERT INTO farm_inventory (user_id, item_id, quantity) VALUES (?, ?, 0)",
                    (user_id, item_id)
                )
            await db.commit()

    async def get_user_beer_rating(self, user_id: int) -> int:
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT beer_rating FROM users WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def get_last_beer_time(self, user_id: int) -> Optional[datetime]:
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT last_beer_time FROM users WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            return datetime.fromisoformat(row[0]) if row and row[0] else None

    async def update_beer_data(self, user_id: int, new_rating: int):
        now_iso = datetime.now().isoformat()
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("UPDATE users SET beer_rating = ?, last_beer_time = ? WHERE user_id = ?", (new_rating, now_iso, user_id))
            await db.commit()

    async def change_rating(self, user_id: int, amount: int):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("UPDATE users SET beer_rating = beer_rating + ? WHERE user_id = ?", (amount, user_id))
            await db.commit()

    async def get_user_rank(self, user_id: int) -> int:
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                "SELECT COUNT(*) + 1 FROM users WHERE beer_rating > (SELECT beer_rating FROM users WHERE user_id = ?)",
                (user_id,)
            )
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def get_top_users(self, limit: int = 10) -> List[Tuple[str, str, int]]:
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                "SELECT first_name, last_name, beer_rating FROM users ORDER BY beer_rating DESC LIMIT ?", (limit,)
            )
            return await cursor.fetchall()

    async def get_user_reg_date(self, user_id: int) -> Optional[str]:
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT registration_date FROM users WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            return row[0] if row else None
            
    # --- ✅ НОВАЯ ФУНКЦИЯ (Для /кинуть @username) ---
    async def get_user_by_username(self, username: str) -> Optional[Tuple[int, str]]:
        """Ищет user_id и first_name по username (без @)."""
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                "SELECT user_id, first_name FROM users WHERE username = ?",
                (username,)
            )
            return await cursor.fetchone()
    
    # --- ✅ НОВАЯ ФУНКЦИЯ (Для /кинуть ID) ---
    async def get_user_by_id(self, user_id: int) -> Optional[Tuple[int, str]]:
        """Ищет user_id и first_name по ID (для проверки)."""
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                "SELECT user_id, first_name FROM users WHERE user_id = ?",
                (user_id,)
            )
            return await cursor.fetchone()

    # --- Функции Настроек (Без изменений) ---
    async def get_setting(self, key: str) -> int:
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT value FROM game_data WHERE key = ?", (key,))
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def update_setting(self, key: str, value: int):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("UPDATE game_data SET value = ? WHERE key = ?", (value, key))
            await db.commit()

    async def get_all_settings(self) -> Dict[str, Any]:
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT key, value FROM game_data")
            rows = await cursor.fetchall()
            return {row[0]: row[1] for row in rows}

    # --- Функции Джекпота (Без изменений) ---
    async def get_jackpot(self) -> int:
        return await self.get_setting('jackpot')

    async def update_jackpot(self, amount: int):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("UPDATE game_data SET value = value + ? WHERE key = 'jackpot'", (amount,))
            await db.commit()

    async def reset_jackpot(self):
        await self.update_setting('jackpot', 0)


    # --- Функции Чатов (Без изменений) ---
    async def add_chat(self, chat_id: int, title: str):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("INSERT OR REPLACE INTO chats (chat_id, title) VALUES (?, ?)", (chat_id, title))
            await db.commit()

    async def get_all_chats(self) -> List[Tuple[int, str]]:
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT chat_id, title FROM chats")
            return await cursor.fetchall()
    
    # --- Функции Рейдов (Без изменений) ---
    async def get_user_raid_stats(self, user_id: int) -> Tuple[int, int]:
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                "SELECT COUNT(raid_id), SUM(damage_dealt) FROM raid_participants WHERE user_id = ?",
                (user_id,)
            )
            row = await cursor.fetchone()
            return (row[0] or 0, row[1] or 0)

    async def create_raid(self, chat_id: int, message_id: int, health: int, reward: int, end_time: datetime):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                "INSERT INTO active_raids (chat_id, message_id, boss_health, boss_max_health, reward_pool, end_time) VALUES (?, ?, ?, ?, ?, ?)",
                (chat_id, message_id, health, health, reward, end_time.isoformat())
            )
            await db.commit()

    async def get_active_raid(self, chat_id: int) -> Tuple | None:
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT * FROM active_raids WHERE chat_id = ?", (chat_id,))
            return await cursor.fetchone()

    async def get_all_active_raids(self) -> List[Tuple]:
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT * FROM active_raids")
            return await cursor.fetchall()

    async def update_raid_health(self, chat_id: int, damage: int):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("UPDATE active_raids SET boss_health = boss_health - ? WHERE chat_id = ?", (damage, chat_id))
            await db.commit()

    async def end_raid(self, chat_id: int):
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
            cursor = await db.execute(
                "SELECT user_id, damage_dealt FROM raid_participants WHERE raid_id = ? ORDER BY damage_dealt DESC",
                (chat_id,)
            )
            return await cursor.fetchall()


    # --- ✅✅✅ НОВЫЕ ФУНКЦИИ ДЛЯ "ФЕРМЫ" (Наш План) ✅✅✅ ---

    # --- 1. Функции Инвентаря (Склада) (Для /shop, /кинуть, /farm) ---
    
    async def get_user_inventory(self, user_id: int) -> Dict[str, int]:
        """Возвращает Склад (4 "понятных" предмета) пользователя."""
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT item_id, quantity FROM farm_inventory WHERE user_id = ?", (user_id,))
            rows = await cursor.fetchall()
            # Гарантируем, что все 4 предмета всегда в словаре
            inventory = {item_id: 0 for item_id in FARM_ITEM_CODES}
            for item_id, quantity in rows:
                if item_id in inventory:
                    inventory[item_id] = quantity
            return inventory

    async def modify_inventory(self, user_id: int, item_id: str, quantity_change: int) -> bool:
        """
        Изменяет количество предмета. 
        True = Успех. False = Неудача (недостаточно предметов).
        Используется для /shop (покупка), /farm (посадка) и /кинуть (передача).
        """
        if item_id not in FARM_ITEM_CODES:
            logging.error(f"Неизвестный item_id '{item_id}' при изменении инвентаря.")
            return False

        async with aiosqlite.connect(self.db_name) as db:
            # Используем транзакцию для безопасности
            async with db.execute("BEGIN") as cursor:
                # 1. Получаем текущее количество
                await cursor.execute(
                    "SELECT quantity FROM farm_inventory WHERE user_id = ? AND item_id = ?",
                    (user_id, item_id)
                )
                row = await cursor.fetchone()
                
                current_quantity = row[0] if row else 0
                
                new_quantity = current_quantity + quantity_change

                # 2. Проверка, если мы тратим (quantity_change < 0)
                if new_quantity < 0:
                    return False # Недостаточно ресурсов!

                # 3. Обновляем (INSERT... ON CONFLICT... DO UPDATE...)
                await cursor.execute(
                    """
                    INSERT INTO farm_inventory (user_id, item_id, quantity)
                    VALUES (?, ?, ?)
                    ON CONFLICT(user_id, item_id) DO UPDATE SET
                    quantity = excluded.quantity
                    """,
                    (user_id, item_id, new_quantity)
                )
            await db.commit()
            return True

    # --- 2. Функции Статистики и Уровней (Для /farm) ---

    async def get_user_farm_data(self, user_id: int) -> Dict[str, Any]:
        """Возвращает ВСЕ данные о ферме (Уровни, Таймеры)."""
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                """
                SELECT 
                    field_level, brewery_level,
                    field_upgrade_timer_end, brewery_upgrade_timer_end,
                    brewery_batch_size, brewery_batch_timer_end
                FROM users 
                WHERE user_id = ?
                """,
                (user_id,)
            )
            row = await cursor.fetchone()
            if row:
                return {
                    "field_level": row[0],
                    "brewery_level": row[1],
                    "field_upgrade_timer_end": datetime.fromisoformat(row[2]) if row[2] else None,
                    "brewery_upgrade_timer_end": datetime.fromisoformat(row[3]) if row[3] else None,
                    "brewery_batch_size": row[4],
                    "brewery_batch_timer_end": datetime.fromisoformat(row[5]) if row[5] else None
                }
            # Если юзер старый и у него нет колонок (хотя миграция должна помочь)
            return {"field_level": 1, "brewery_level": 1, "field_upgrade_timer_end": None, "brewery_upgrade_timer_end": None, "brewery_batch_size": 0, "brewery_batch_timer_end": None} 

    # --- 3. Функции Полей (Участков) (Для /farm) ---

    async def get_user_plots(self, user_id: int) -> List[Tuple]:
        """Возвращает все активные участки (таймеры 10/20 мин) пользователя."""
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                "SELECT plot_number, crop_type, ready_time FROM farm_plots WHERE user_id = ?",
                (user_id,)
            )
            return await cursor.fetchall()

    async def plant_crop(self, user_id: int, plot_number: int, crop_type: str, ready_time: datetime) -> bool:
        """
        Сажает урожай. (Трату 'семя_хмеля' делаем в 'modify_inventory' до вызова этой функции).
        True = Успех. False = Участок уже занят.
        """
        async with aiosqlite.connect(self.db_name) as db:
            # Уникальный ключ (user_id, plot_number) не даст посадить, если уже занято
            await db.execute(
                "INSERT OR IGNORE INTO farm_plots (user_id, plot_number, crop_type, ready_time) VALUES (?, ?, ?, ?)",
                (user_id, plot_number, crop_type, ready_time.isoformat())
            )
            changes = db.total_changes
            await db.commit()
            return changes > 0 # Если 0, значит, запись уже была (ON IGNORE)

    async def harvest_plot(self, user_id: int, plot_number: int) -> Optional[str]:
        """
        Собирает урожай. (Добавление 'хмеля' делаем в 'modify_inventory' после).
        Возвращает crop_type ('семя_зерна' / 'семя_хмеля') или None, если нечего собирать.
        """
        async with aiosqlite.connect(self.db_name) as db:
            # 1. Получаем тип урожая, который там рос
            cursor = await db.execute(
                "SELECT crop_type FROM farm_plots WHERE user_id = ? AND plot_number = ?",
                (user_id, plot_number)
            )
            row = await cursor.fetchone()
            
            if not row:
                return None # Нечего собирать
                
            crop_type = row[0]
            
            # 2. Очищаем участок
            await db.execute(
                "DELETE FROM farm_plots WHERE user_id = ? AND plot_number = ?",
                (user_id, plot_number)
            )
            await db.commit()
            return crop_type

    # --- 4. Функции Пивоварни (Пакетная Варка) ---

    async def start_brewing(self, user_id: int, batch_size: int, end_time: datetime):
        """Запускает "пакетную" варку."""
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                "UPDATE users SET brewery_batch_size = ?, brewery_batch_timer_end = ?, brewery_batch_notified = 0 WHERE user_id = ?",
                (batch_size, end_time.isoformat(), user_id)
            )
            await db.commit()

    async def collect_brewery(self, user_id: int, reward: int):
        """Забирает награду. Добавляет 🍺 и очищает таймер."""
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                "UPDATE users SET beer_rating = beer_rating + ?, brewery_batch_size = 0, brewery_batch_timer_end = NULL, brewery_batch_notified = 0 WHERE user_id = ?", 
                (reward, user_id)
            )
            await db.commit()

    # --- 5. Функции Улучшений (Таймеры 48ч) ---

    async def start_upgrade(self, user_id: int, building: str, end_time: datetime, cost: int):
        """Тратит 🍺 и запускает таймер прокачки (8-48 часов)."""
        async with aiosqlite.connect(self.db_name) as db:
            # 1. Тратим 🍺
            await db.execute("UPDATE users SET beer_rating = beer_rating - ? WHERE user_id = ?", (cost, user_id))
            
            # 2. Ставим таймер
            if building == "field":
                await db.execute("UPDATE users SET field_upgrade_timer_end = ?, field_upgrade_notified = 0 WHERE user_id = ?", (end_time.isoformat(), user_id))
            elif building == "brewery":
                await db.execute("UPDATE users SET brewery_upgrade_timer_end = ?, brewery_upgrade_notified = 0 WHERE user_id = ?", (end_time.isoformat(), user_id))
            
            await db.commit()

    async def finish_upgrade(self, user_id: int, building: str):
        """Завершает прокачку: +1 Уровень, очищает таймер."""
        async with aiosqlite.connect(self.db_name) as db:
            if building == "field":
                await db.execute("UPDATE users SET field_level = field_level + 1, field_upgrade_timer_end = NULL WHERE user_id = ?", (user_id,))
            elif building == "brewery":
                await db.execute("UPDATE users SET brewery_level = brewery_level + 1, brewery_upgrade_timer_end = NULL WHERE user_id = ?", (user_id,))
            await db.commit()

    # --- 6. Функции Уведомлений (Для "Фоновой Задачи") ---

    async def get_pending_notifications(self) -> List[Tuple]:
        """Ищет ВСЕХ юзеров, чьи таймеры (Варка, Прокачка) готовы и о них НЕ уведомляли."""
        now_iso = datetime.now().isoformat()
        async with aiosqlite.connect(self.db_name) as db:
            
            # 1. Готовые "Пакетные Варки"
            cursor_brew_batch = await db.execute(
                """
                SELECT user_id, brewery_batch_size 
                FROM users 
                WHERE brewery_batch_timer_end IS NOT NULL 
                AND brewery_batch_timer_end <= ? 
                AND brewery_batch_notified = 0
                """, (now_iso,)
            )
            batch_notifications = await cursor_brew_batch.fetchall()
            
            # 2. Готовые "Прокачки Поля"
            cursor_field_upgrade = await db.execute(
                """
                SELECT user_id, field_level 
                FROM users 
                WHERE field_upgrade_timer_end IS NOT NULL 
                AND field_upgrade_timer_end <= ? 
                AND field_upgrade_notified = 0
                """, (now_iso,)
            )
            field_notifications = await cursor_field_upgrade.fetchall()

            # 3. Готовые "Прокачки Пивоварни"
            cursor_brewery_upgrade = await db.execute(
                """
                SELECT user_id, brewery_level 
                FROM users 
                WHERE brewery_upgrade_timer_end IS NOT NULL 
                AND brewery_upgrade_timer_end <= ? 
                AND brewery_upgrade_notified = 0
                """, (now_iso,)
            )
            brewery_notifications = await cursor_brewery_upgrade.fetchall()
            
            # Собираем все в один список
            # (user_id, 'batch', data)
            # (user_id, 'field_upgrade', data)
            # (user_id, 'brewery_upgrade', data)
            tasks = []
            for (user_id, batch_size) in batch_notifications:
                tasks.append((user_id, 'batch', batch_size))
            for (user_id, level) in field_notifications:
                tasks.append((user_id, 'field_upgrade', level + 1)) # Отправляем НОВЫЙ уровень
            for (user_id, level) in brewery_notifications:
                tasks.append((user_id, 'brewery_upgrade', level + 1)) # Отправляем НОВЫЙ уровень

            return tasks

    async def mark_notification_sent(self, user_id: int, notification_type: str):
        """Ставит "флажок", что мы отправили ЛС, чтобы не спамить."""
        async with aiosqlite.connect(self.db_name) as db:
            if notification_type == 'batch':
                await db.execute("UPDATE users SET brewery_batch_notified = 1 WHERE user_id = ?", (user_id,))
            elif notification_type == 'field_upgrade':
                await db.execute("UPDATE users SET field_upgrade_notified = 1 WHERE user_id = ?", (user_id,))
            elif notification_type == 'brewery_upgrade':
                await db.execute("UPDATE users SET brewery_upgrade_notified = 1 WHERE user_id = ?", (user_id,))
            await db.commit()
