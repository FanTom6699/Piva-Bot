# main.py
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

import config
from handlers import main_router
from database import Database
from settings import SettingsManager

# --- ✅ ИМПОРТЫ ЗАДАЧ ---
from handlers.game_raid import raid_background_updater, active_raid_tasks
from handlers.farm_updater import farm_background_updater, farm_updater_task # ✅ НОВЫЙ ИМПОРТ

async def start_active_raid_tasks(bot: Bot, db: Database, settings: SettingsManager):
    """При старте бота ищет активные рейды в БД и запускает для них фоновые задачи."""
    logging.info("Проверка активных рейдов...")
    active_raids = await db.get_all_active_raids()
    count = 0
    for raid in active_raids:
        chat_id = raid[0]
        if chat_id not in active_raid_tasks:
            task = asyncio.create_task(raid_background_updater(chat_id, bot, db, settings))
            active_raid_tasks[chat_id] = task
            count += 1
    logging.info(f"Запущено {count} фоновых задач для активных рейдов.")

# --- ✅ НОВАЯ ФУНКЦИЯ ЗАПУСКА ФЕРМЫ ---
async def start_farm_updater_task(bot: Bot, db: Database):
    """Запускает фоновую задачу для Фермы (уведомления об апгрейдах)."""
    global farm_updater_task
    if farm_updater_task is None:
        logging.info("Запуск фоновой задачи (Farm Updater)...")
        farm_updater_task = asyncio.create_task(farm_background_updater(bot, db))
    else:
        logging.warning("Фоновая задача (Farm Updater) уже была запущена.")
# --- ---

async def main():
    logging.basicConfig(level=logging.INFO)
    
    # (Используем /data/ для Render)
    db = Database(db_name='/data/bot_database.db')
    settings_manager = SettingsManager()
    
    await db.initialize()
    await settings_manager.load_settings(db)
    
    bot = Bot(
        token=config.BOT_TOKEN, 
        default=DefaultBotProperties(parse_mode="HTML")
    )
    
    dp = Dispatcher()
    dp["db"] = db
    dp["settings"] = settings_manager
    
    dp.include_router(main_router)

    await bot.delete_webhook(drop_pending_updates=True)
    
    # --- ✅ ИСПРАВЛЕННЫЙ ЗАПУСК ФОНОВЫХ ЗАДАЧ ---
    await start_active_raid_tasks(bot, db, settings_manager)
    await start_farm_updater_task(bot, db) # ✅ ЗАПУСКАЕМ ФЕРМУ
    
    logging.info("Запуск polling...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
