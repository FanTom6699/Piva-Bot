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

# --- ИЗМЕНЕНИЕ 1: Удалили 'raid_background_updater' и заменили 'active_raid_tasks' -> 'raid_tasks' ---
# Также импортируем 'active_raids', чтобы корректно завершать их при выключении
from handlers.game_raid import raid_tasks, check_raid_status, active_raids

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def on_startup(bot: Bot, db: Database, settings: SettingsManager):
    """
    Выполняется при старте бота.
    """
    await db.init_db()
    await settings.load_settings()
    
    # --- ИЗМЕНЕНИЕ 2: Удалили эту строку, так как 'raid_background_updater' больше нет ---
    # asyncio.create_task(raid_background_updater(bot, db, settings))
    # --- КОНЕЦ ИЗМЕНЕНИЯ 2 ---
    
    logger.info("Бот успешно запущен.")

async def on_shutdown(bot: Bot, db: Database):
    """
    Выполняется при остановке бота.
    """
    logger.info("Бот останавливается...")
    
    # --- ИЗМЕНЕНИЕ 3: Заменили 'active_raid_tasks' -> 'raid_tasks' ---
    # Отменяем все запущенные задачи рейдов
    for task in raid_tasks.values():
        task.cancel()
    
    # Находим все активные рейды и завершаем их (как проваленные)
    for chat_id, raid in active_raids.items():
        if raid.is_active:
            logger.warning(f"Завершение рейда (по выключению) для чата {chat_id}...")
            # Вызываем 'check_raid_status', он обработает логику поражения
            await check_raid_status(bot, db, raid) 
    # --- КОНЕЦ ИЗМЕНЕНИЯ 3 ---
            
    await db.close()
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
