# main.py
import asyncio
import logging

from aiogram import Bot, Dispatcher

import config
from handlers import main_router # <-- ИЗМЕНЕНИЕ ЗДЕСЬ
from database import Database # <-- Нам нужен класс, а не объект

async def main():
    # Настройка логирования
    logging.basicConfig(level=logging.INFO)
    
    # Инициализация базы данных
    db = Database(db_name='/data/bot_database.db')
    await db.initialize()
    
    # Создание объектов бота и диспетчера
    bot = Bot(token=config.BOT_TOKEN)
    dp = Dispatcher()
    
    # Подключение главного роутера
    dp.include_router(main_router) # <-- ИЗМЕНЕНИЕ ЗДЕСЬ

    # Запуск бота
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
