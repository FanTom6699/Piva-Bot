# main.py
import asyncio
import logging

from aiogram import Bot, Dispatcher

import config
from handlers import router, admin_router, db

async def main():
    # Настройка логирования для вывода информации в консоль
    logging.basicConfig(level=logging.INFO)
    
    # Инициализация базы данных (создание таблиц, если их нет)
    await db.initialize()
    
    # Создание объектов бота и диспетчера
    bot = Bot(token=config.BOT_TOKEN)
    dp = Dispatcher()
    
    # Подключение роутеров с командами
    # Подключаем команды для обычных пользователей
    dp.include_router(router)
    # Подключаем команды для админа
    dp.include_router(admin_router)

    # Перед запуском polling удаляем все старые обновления, чтобы бот не отвечал на старые сообщения
    await bot.delete_webhook(drop_pending_updates=True)
    # Запуск бота
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
