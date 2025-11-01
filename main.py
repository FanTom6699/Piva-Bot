# main.py
import asyncio
import logging
import os
import sys

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from dotenv import load_dotenv # <-- Добавлен импорт

# --- Импорты (теперь они работают, т.к. все в одной папке) ---
import config
from database import Database
from settings import SettingsManager
from handlers import main_router # Импортируем из папки 'handlers'
from handlers.game_raid import raid_background_updater, active_raid_tasks, check_raid_status

async def start_active_raid_tasks(bot: Bot, db: Database, settings: SettingsManager):
    """При старте бота ищет активные рейды в БД и запускает для них фоновые задачи."""
    logging.info("Проверка активных рейдов...")
    active_raids = await db.get_all_active_raids()
    count = 0
    for raid_data in active_raids:
        chat_id = raid_data[0]
        # Проверяем, не закончился ли рейд, пока бот лежал
        is_still_active = await check_raid_status(chat_id, bot, db, settings)
        
        if is_still_active and chat_id not in active_raid_tasks:
            task = asyncio.create_task(raid_background_updater(chat_id, bot, db, settings))
            active_raid_tasks[chat_id] = task
            count += 1
    logging.info(f"Запущено {count} фоновых задач для активных рейдов.")


# --- Главная функция async main ---
async def main():
    logging.basicConfig(level=logging.INFO)
    load_dotenv() # <-- Вызываем dotenv
    
    # --- Загрузка токена ---
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    if not BOT_TOKEN:
        logging.warning("BOT_TOKEN не найден в .env, пытаюсь загрузить из config.py...")
        try:
            BOT_TOKEN = config.BOT_TOKEN 
        except (ImportError, AttributeError):
            logging.critical("ОШИБКА: BOT_TOKEN не найден ни в .env, ни в config.py!")
            return

    # --- Инициализация общих компонентов (БД и Настройки) ---
    db_path = os.getenv("DB_PATH", "bot_database.db")
    if "RENDER" in os.environ:
         db_path = "/data/bot_database.db"
         logging.info(f"Обнаружен Render.com. Путь к БД: {db_path}")

    db = Database(db_name=db_path)
    await db.initialize()
    
    # --- ИСПРАВЛЕНИЕ ЛОГИКИ ---
    # 1. Создаем settings_manager (твой __init__ не принимает db)
    settings_manager = SettingsManager()
    # 2. Вызываем load_settings (твой load_settings принимает db)
    await settings_manager.load_settings(db)
    # --- КОНЕЦ ИСПРАВЛЕНИЯ ---
    
    # --- Инициализация Бота ---
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    
    # Передаем зависимости
    dp["db"] = db
    dp["settings"] = settings_manager
    
    # Подключаем роутер
    dp.include_router(main_router) 
    
    logging.info("--- Основной бот (Пиво/Рейд) запущен. ---")

    # Удаляем вебхук
    await bot.delete_webhook(drop_pending_updates=True)
    
    # Запускаем фоновые задачи для рейдов
    await start_active_raid_tasks(bot, db, settings_manager)
    
    # Запускаем бота
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Работа ботов остановлена.")
    except Exception as e:
        logging.error(f"Критическая ошибка при запуске: {e}", exc_info=True)
