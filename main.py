# main.py
import asyncio
import logging
import os
import sys

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from dotenv import load_dotenv

# --- Импорты ---
import config
from database import Database
from settings import SettingsManager

# --- Импортируем ОДИН главный роутер ---
from handlers import main_router 

# Импорт для фоновых задач Рейда
from handlers.game_raid import raid_background_updater, active_raid_tasks, check_raid_status

# --- Функция перезапуска задач Рейда ---
async def start_active_raid_tasks(bot: Bot, db: Database, settings: SettingsManager):
    """При старте бота ищет активные рейды в БД и запускает для них фоновые задачи."""
    logging.info("Проверка активных рейдов...")
    active_raids = await db.get_all_active_raids()
    count = 0
    for raid_data in active_raids:
        chat_id = raid_data[0]
        is_still_active = await check_raid_status(chat_id, bot, db, settings)
        
        if is_still_active and chat_id not in active_raid_tasks:
            task = asyncio.create_task(raid_background_updater(chat_id, bot, db, settings))
            active_raid_tasks[chat_id] = task
            count += 1
    logging.info(f"Запущено {count} фоновых задач для активных рейдов.")


# --- Главная функция async main (запускает ОДИН бот) ---
async def main():
    logging.basicConfig(level=logging.INFO)
    load_dotenv()
    
    # --- Инициализация общих компонентов (БД и Настройки) ---
    db_path = os.getenv("DB_PATH", "bot_database.db")
    if "RENDER" in os.environ:
         db_path = "/data/bot_database.db"
         logging.info(f"Обнаружен Render.com. Путь к БД: {db_path}")

    db = Database(db_name=db_path)
    await db.initialize()
    
    settings = SettingsManager() 
    await settings.load_settings(db)
    
    logging.info("Запускаем бота...")

    # --- Запускаем Основного Бота ---
    BOT_TOKEN = os.getenv("BOT_TOKEN", getattr(config, "BOT_TOKEN", None))
    
    if not BOT_TOKEN:
        logging.error("Токен для 'BOT_TOKEN' не найден! Бот не запущен.")
        sys.exit(1)

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    
    dp["db"] = db
    dp["settings"] = settings
    dp.include_router(main_router)
    
    await start_active_raid_tasks(bot, db, settings)
    
    logging.info("--- 🍻 Основной бот (Пиво/Рейд) запущен. ---")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Работа бота остановлена.")
    except Exception as e:
        logging.error(f"Критическая ошибка при запуске: {e}", exc_info=True)
