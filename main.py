# main.py
import asyncio
import logging
import os
import sys

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from dotenv import load_dotenv

# --- ВАЖНО: ИСПРАВЛЕНИЕ ОШИБКИ ИМПОРТА ---
# Это добавляет корневую папку в пути Python.
# Теперь `from utils import ...` и `from database import ...` 
# будут работать изнутри папки `handlers`.
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# --- Импорты (теперь они работают) ---
import config
from database import Database
from settings import SettingsManager
from handlers import main_router
from handlers.game_raid import raid_background_updater, active_raid_tasks, check_raid_status

async def start_active_raid_tasks(bot: Bot, db: Database, settings: SettingsManager):
    """При старте бота ищет активные рейды в БД и запускает для них фоновые задачи."""
    logging.info("Проверка активных рейдов...")
    active_raids = await db.get_all_active_raids()
    count = 0
    for raid_data in active_raids:
        chat_id = raid_data[0]
        
        # Сначала проверим, не закончился ли рейд, пока бот лежал
        is_still_active = await check_raid_status(chat_id, bot, db, settings)
        
        if is_still_active and chat_id not in active_raid_tasks:
            # Передаем все нужные зависимости в фоновую задачу
            task = asyncio.create_task(raid_background_updater(chat_id, bot, db, settings))
            active_raid_tasks[chat_id] = task
            count += 1
    logging.info(f"Запущено {count} фоновых задач для активных рейдов.")


async def main():
    # --- Загрузка конфигурации ---
    load_dotenv()
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    
    # Если в .env нет, пробуем из config.py
    if not BOT_TOKEN:
        try:
            from config import BOT_TOKEN as CFG_TOKEN
            BOT_TOKEN = CFG_TOKEN
            logging.warning("Токен загружен из config.py. Рекомендуется использовать .env")
        except ImportError:
             logging.critical("ОШИБКА: BOT_TOKEN не найден! Проверьте .env или config.py.")
             return

    # --- Инициализация ---
    # Используем DefaultBotProperties для aiogram 3.9.0
    bot = Bot(
        token=BOT_TOKEN, 
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    
    # Путь к БД для Render.com
    db_path = os.getenv("DB_PATH", "bot_database.db")
    if "RENDER" in os.environ:
         db_path = "/data/bot_database.db"
         logging.info(f"Обнаружен Render.com. Путь к БД: {db_path}")

    db = Database(db_name=db_path)
    await db.initialize()
    
    # Инициализируем Настройки
    settings = SettingsManager(db)
    await settings.load_settings()

    # Инициализируем Диспетчер
    dp = Dispatcher()
    
    # Подключаем главный роутер (который собрал все игры)
    dp.include_router(main_router)
    
    # Передаем db и settings в хэндлеры
    dp["db"] = db
    dp["settings"] = settings
    
    logging.info("Бот запускается...")

    # Удаляем вебхук (если он был) и начинаем опрос
    await bot.delete_webhook(drop_pending_updates=True)
    
    # Запускаем фоновые задачи для рейдов
    await start_active_raid_tasks(bot, db, settings)
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Бот остановлен.")
    except Exception as e:
        logging.error(f"Критическая ошибка при запуске: {e}", exc_info=True)
