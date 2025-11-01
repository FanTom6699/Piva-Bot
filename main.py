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

# --- ВАЖНО: Импортируем ОБА роутера ---
from handlers import main_router 
from mafia_handlers import mafia_router # <-- Раскомментировано

# Импорт для фоновых задач Рейда (привязан к ОСНОВНОМУ боту)
from handlers.game_raid import raid_background_updater, active_raid_tasks, check_raid_status

# --- Функция перезапуска задач Рейда (привязана к Основному боту) ---
async def start_active_raid_tasks(bot: Bot, db: Database, settings: SettingsManager):
    """При старте бота ищет активные рейды в БД и запускает для них фоновые задачи."""
    logging.info("Проверка активных рейдов...")
    active_raids = await db.get_all_active_raids()
    count = 0
    for raid_data in active_raids:
        chat_id = raid_data[0]
        # (Используем datetime.fromisoformat, как в database.py)
        is_still_active = await check_raid_status(chat_id, bot, db, settings)
        
        if is_still_active and chat_id not in active_raid_tasks:
            task = asyncio.create_task(raid_background_updater(chat_id, bot, db, settings))
            active_raid_tasks[chat_id] = task
            count += 1
    logging.info(f"Запущено {count} фоновых задач для активных рейдов.")


# --- Функция запуска Основного Бота (без изменений) ---
async def start_main_bot(db: Database, settings: SettingsManager):
    """Запускает основного бота (Пиво, Рейды)"""
    load_dotenv()
    BOT_TOKEN = os.getenv("BOT_TOKEN", getattr(config, "BOT_TOKEN", None))
    
    if not BOT_TOKEN:
        logging.error("Токен для 'BOT_TOKEN' не найден! Основной бот не запущен.")
        return

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    
    dp["db"] = db
    dp["settings"] = settings
    dp.include_router(main_router)
    
    await start_active_raid_tasks(bot, db, settings)
    
    logging.info("--- 🍻 Основной бот (Пиво/Рейд) запущен. ---")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

# --- ИСПРАВЛЕНИЕ: Функция запуска Мафия-Бота (ВКЛЮЧЕНА) ---
async def start_mafia_bot(db: Database, settings: SettingsManager):
    """Запускает Мафия-бота"""
    load_dotenv()
    BOT_TOKEN_MAFIA = os.getenv("BOT_TOKEN_MAFIA", getattr(config, "BOT_TOKEN_MAFIA", None))

    if not BOT_TOKEN_MAFIA:
        logging.warning("Токен 'BOT_TOKEN_MAFIA' не найден. Мафия-бот не будет запущен.")
        return
        
    # --- Код раскомментирован ---
    bot = Bot(token=BOT_TOKEN_MAFIA, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    
    dp["db"] = db
    dp["settings"] = settings
    # Подключаем роутер Мафии
    dp.include_router(mafia_router) 
    
    logging.info("--- 🕵️‍♂️ Мафия-бот запущен. ---")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


# --- Главная функция async main (запускает ОБА бота) ---
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
    
    # (Используем твой settings.py, который не требует db в __init__)
    settings = SettingsManager() 
    await settings.load_settings(db)
    
    logging.info("Запускаем ботов...")

    # --- Запускаем обе функции ОДНОВРЕМЕННО ---
    await asyncio.gather(
        start_main_bot(db, settings),
        start_mafia_bot(db, settings)
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Работа ботов остановлена.")
    except Exception as e:
        logging.error(f"Критическая ошибка при запуске: {e}", exc_info=True)
