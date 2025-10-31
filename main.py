# main.py
import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import load_config
from database import Database
from settings import SettingsManager
from handlers import main_router

# Импорты для on_shutdown (все корректны)
from handlers.game_raid import raid_tasks, check_raid_status, active_raids

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def on_startup(bot: Bot, db: Database, settings: SettingsManager):
    """
    Выполняется при старте бота.
    """
    
    # --- ИСПРАВЛЕНИЕ 1: 'init_db' -> 'initialize' ---
    await db.initialize()
    # --- КОНЕЦ ИСПРАВЛЕНИЯ 1 ---
    
    await settings.load_settings()
    logger.info("Бот успешно запущен.")

async def on_shutdown(bot: Bot, db: Database):
    """
    Выполняется при остановке бота.
    """
    logger.info("Бот останавливается...")
    
    # Отменяем все запущенные задачи рейдов
    for task in raid_tasks.values():
        task.cancel()
    
    # Находим все активные рейды и завершаем их (как проваленные)
    for chat_id, raid in active_raids.items():
        if raid.is_active:
            logger.warning(f"Завершение рейда (по выключению) для чата {chat_id}...")
            # Вызываем 'check_raid_status', он обработает логику поражения
            await check_raid_status(bot, db, raid) 
            
    # --- ИСПРАВЛЕНИЕ 2: Убираем db.close() ---
    # Твой database.py использует 'async with' и не требует ручного закрытия.
    # await db.close()
    # --- КОНЕЦ ИСПРАВЛЕНИЯ 2 ---
            
    logger.info("Бот успешно остановлен.")

async def main():
    config = load_config()
    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    
    # Инициализация БД и Менеджера Настроек
    # (Твой database.py ожидает db_name, даем ему твое имя)
    db = Database('pivobot.db') 
    settings = SettingsManager(db)

    # Внедрение зависимостей (DI)
    dp['db'] = db
    dp['settings'] = settings

    # Регистрация роутеров
    dp.include_router(main_router)

    # Регистрация хуков startup/shutdown
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    # Запуск бота
    await bot.delete_webhook(drop_pending_updates=True)
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Выход.")
