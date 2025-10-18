# main.py
import asyncio
import logging

from aiogram import Bot, Dispatcher

import config
from handlers import router, db

async def main():
    # Настройка логирования
    logging.basicConfig(level=logging.INFO)
    
    # Инициализация базы данных
    await db.initialize()
    
    # Создание объектов бота и диспетчера
    bot = Bot(token=config.BOT_TOKEN)
    dp = Dispatcher()
    
    # Подключение роутера с хэндлерами
    dp.include_router(router)

    # Запуск бота
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
