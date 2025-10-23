# main.py
import asyncio
import logging

from aiogram import Bot, Dispatcher
# --- ИМПОРТ ИЗМЕНЕН ---
from aiogram.client.default import DefaultBotProperties

import config
from handlers import main_router
from handlers.game_raid import raid_background_updater, active_raid_tasks
from database import Database
from settings import SettingsManager

async def start_active_raid_tasks(bot: Bot, db: Database, settings: SettingsManager):
    """При старте бота ищет активные рейды в БД и запускает для них фоновые задачи."""
    logging.info("Проверка активных рейдов...")
    active_raids = await db.get_all_active_raids()
    count = 0
    for raid in active_raids:
        chat_id = raid[0]
        if chat_id not in active_raid_tasks:
            # Передаем все нужные зависимости в фоновую задачу
            task = asyncio.create_task(raid_background_updater(chat_id, bot, db, settings))
            active_raid_tasks[chat_id] = task
            count += 1
    logging.info(f"Запущено {count} фоновых задач для активных рейдов.")


async def main():
    logging.basicConfig(level=logging.INFO)
    
    db = Database(db_name='/data/bot_database.db')
    settings_manager = SettingsManager()
    
    await db.initialize()
    await settings_manager.load_settings(db)
    
    # --- ИСПРАВЛЕНИЕ ЗДЕСЬ ---
    # Устанавливаем HTML-парсер по умолчанию через DefaultBotProperties
    bot = Bot(
        token=config.BOT_TOKEN, 
        default=DefaultBotProperties(parse_mode="HTML")
    )
    # --- КОНЕЦ ИСПРАВЛЕНИЯ ---
    
    dp = Dispatcher()
    # Передаем db и settings во все хэндлеры
    dp["db"] = db
    dp["settings"] = settings_manager
    
    dp.include_router(main_router)

    await bot.delete_webhook(drop_pending_updates=True)
    
    # Запускаем фоновые задачи для рейдов
    await start_active_raid_tasks(bot, db, settings_manager)
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
