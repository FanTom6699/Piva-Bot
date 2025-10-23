# main.py
import asyncio
import logging

from aiogram import Bot, Dispatcher

import config
from handlers import main_router
from database import Database
from settings import settings_manager # <-- ИМПОРТИРУЕМ МЕНЕДЖЕР

async def main():
    logging.basicConfig(level=logging.INFO)
    
    db = Database(db_name='/data/bot_database.db')
    await db.initialize()
    
    # --- ЗАГРУЖАЕМ НАСТРОЙКИ ПРИ СТАРТЕ ---
    await settings_manager.load_settings(db)
    
    bot = Bot(token=config.BOT_TOKEN)
    dp = Dispatcher()
    
    dp.include_router(main_router)

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
