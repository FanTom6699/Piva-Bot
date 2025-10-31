# main.py
import asyncio
import logging
import os
import sys

# --- ВАЖНО: ИСПРАВЛЕНИЕ ОШИБКИ ИМПОРТА "No module named 'handlers'" ---
# Этот код принудительно добавляет папку, где лежит 'main.py' (т.е. 'src'),
# в список путей Python.
this_file_path = os.path.abspath(__file__)
this_dir = os.path.dirname(this_file_path)
if this_dir not in sys.path:
    sys.path.insert(0, this_dir)
# --- КОНЕЦ ФИКСА ---

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from dotenv import load_dotenv

# --- Импорты (теперь они работают) ---
from database import Database
from settings import SettingsManager
from handlers import main_router  # Импортируем только главный роутер
from handlers.game_raid import raid_background_updater, active_raid_tasks, check_raid_status

async def start_active_raid_tasks(bot: Bot, db: Database, settings: SettingsManager):
    """При старте бота ищет активные рейды в БД и запускает для них фоновые задачи."""
    logging.info("Проверка активных рейдов...")
    active_raids = await db.get_all_active_raids()
    count = 0
    for raid_data in active_raids:
        chat_id = raid_data[0]
        is_still_active = await check_raid_status(chat_id, bot, db, settings)
        
        if is_still_active and chat_id not in active_raid_tasks:
            task = asyncio.create_task(raid_background_updater(chat_id, bot, db, settings))
            active_raid_tasks[chat_id] = task
            count += 1
    logging.info(f"Запущено {count} фоновых задач для активных рейдов.")


# --- Главная функция async main (Упрощенная) ---
async def main():
    logging.basicConfig(level=logging.INFO)
    load_dotenv()
    
    # --- Загрузка токена (только один) ---
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    if not BOT_TOKEN:
        logging.critical("ОШИБКА: BOT_TOKEN не найден! Проверьте .env файл.")
        return

    # --- Инициализация общих компонентов (БД и Настройки) ---
    db_path = os.getenv("DB_PATH", "bot_database.db")
    if "RENDER" in os.environ:
         db_path = "/data/bot_database.db"
         logging.info(f"Обнаружен Render.com. Путь к БД: {db_path}")

    db = Database(db_name=db_path)
    await db.initialize()
    
    settings = SettingsManager(db) 
    await settings.load_settings()
    
    # --- Инициализация Бота (только один) ---
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    
    # Передаем зависимости
    dp["db"] = db
    dp["settings"] = settings
    
    # Подключаем ТОЛЬКО главный роутер
    dp.include_router(main_router) 
    
    logging.info("--- Основной бот (Пиво/Рейд) запущен. ---")

    # Удаляем вебхук
    await bot.delete_webhook(drop_pending_updates=True)
    
    # Запускаем фоновые задачи для рейдов
    await start_active_raid_tasks(bot, db, settings)
    
    # Запускаем бота
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Работа ботов остановлена.")
    except Exception as e:
        logging.error(f"Критическая ошибка при запуске: {e}", exc_info=True)
