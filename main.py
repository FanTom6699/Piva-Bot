# main.py
import asyncio
import logging

from aiogram import Bot, Dispatcher

import config
from handlers import main_router
from handlers.game_raid import raid_background_updater, active_raid_tasks # <-- ИМПОРТ
from database import Database
from settings import settings_manager

async def start_active_raid_tasks(bot: Bot, db: Database):
    """При старте бота ищет активные рейды в БД и запускает для них фоновые задачи."""
    logging.info("Проверка активных рейдов...")
    active_raids = await db.get_all_active_raids()
    count = 0
    for raid in active_raids:
        chat_id = raid[0]
        if chat_id not in active_raid_tasks:
            task = asyncio.create_task(raid_background_updater(chat_id, bot))
            active_raid_tasks[chat_id] = task
            count += 1
    logging.info(f"Запущено {count} фоновых задач для активных рейдов.")


async def main():
    logging.basicConfig(level=logging.INFO)
    
    db = Database(db_name='/data/bot_database.db')
    await db.initialize()
    
    await settings_manager.load_settings(db)
    
    bot = Bot(token=config.BOT_TOKEN)
    dp = Dispatcher()
    
    dp.include_router(main_router)

    await bot.delete_webhook(drop_pending_updates=True)
    
    # --- ЗАПУСКАЕМ ФОНОВЫЕ ЗАДАЧИ ---
    await start_active_raid_tasks(bot, db)
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
