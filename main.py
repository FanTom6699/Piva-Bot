# main.py
import asyncio
import logging
from datetime import datetime # (Этот импорт нужен для farm_background_updater)

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

import config
from handlers import main_router # ✅ ИМПОРТИРУЕМ ТОЛЬКО main_router
from handlers.game_raid import raid_background_updater, active_raid_tasks

# --- ❌ УБРАНЫ ❌ ---
# (Импорты farm_router и shop_router здесь больше не нужны)
# --- ---

from database import Database
from settings import SettingsManager

async def start_active_raid_tasks(bot: Bot, db: Database, settings: SettingsManager):
    """(Твой код) При старте бота ищет активные рейды в БД и запускает для них фоновые задачи."""
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


# --- ФОНОВАЯ ЗАДАЧА ФЕРМЫ (С ИСПРАВЛЕНИЕМ 'now') ---
async def farm_background_updater(bot: Bot, db: Database):
    """
    (Piva Bot) Эта фоновая задача проверяет таймеры фермы (варку, стройку) 
    и отправляет уведомления.
    """
    logging.info("Фоновая задача (Farm Updater) запущена...")
    while True:
        await asyncio.sleep(60) # Проверяем раз в минуту
        try:
            # ✅ (ИСПРАВЛЕНИЕ ОШИБКИ 'now' ОСТАЕТСЯ ЗДЕСЬ)
            now = datetime.now()
            pending_tasks = await db.get_pending_notifications(now) # <-- 'now' ПЕРЕДАН
            
            if not pending_tasks:
                continue
                
            logging.info(f"[Farm Updater] Найдено {len(pending_tasks)} готовых задач...")
            
            # (Сначала применяем апгрейды)
            users_to_check = {uid for uid, ttype, data in pending_tasks}
            for user_id in users_to_check:
                 await db.check_and_apply_upgrades(user_id)
            
            # (Потом рассылаем уведомления)
            for user_id, task_type, data in pending_tasks:
                text = None
                if task_type == 'batch':
                    text = f"🍻 (Ферма) Твоя варка (x{data}) готова! Забери награду!"
                elif task_type == 'field_upgrade':
                    text = f"🌾 (Ферма) Улучшение [Поля] завершено!"
                elif task_type == 'brewery_upgrade':
                    text = f"🏭 (Ферма) Улучшение [Пивоварни] завершено!"
                
                if text:
                    try:
                        await bot.send_message(user_id, text)
                        await db.mark_notification_sent(user_id, task_type)
                        logging.info(f"[Farm Updater] Отправлено {task_type} юзеру {user_id}")
                    except Exception as e:
                        logging.warning(f"[Farm Updater] Не удалось отправить {task_type} юзеру {user_id}: {e}")
                        await db.mark_notification_sent(user_id, task_type)

        except Exception as e:
            logging.error(f"[Farm Updater] Критическая ошибка в цикле: {e}", exc_info=True)
            await asyncio.sleep(300) # (Пауза 5 минут при сбое)
# --- ---


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(name)s - %(message)s'
    )
    logging.info("Инициализация Менеджера Настроек...")
    
    db = Database(db_name='/data/bot_database.db') 
    settings_manager = SettingsManager()
    
    await db.initialize()
    await settings_manager.load_settings(db)
    
    bot = Bot(
        token=config.BOT_TOKEN, 
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    
    dp = Dispatcher()
    dp["db"] = db
    dp["settings"] = settings_manager
    
    # --- ✅✅✅ ИСПРАВЛЕНИЕ RuntimeError ✅✅✅ ---
    # (Теперь мы включаем ТОЛЬКО 'main_router', который уже содержит ферму)
    dp.include_router(main_router) 
    # --- ❌ УБРАНЫ ❌ ---
    # dp.include_router(farm_router) 
    # dp.include_router(shop_router) 
    # --- ---
    
    # Запускаем фоновые задачи
    await start_active_raid_tasks(bot, db, settings_manager)
    asyncio.create_task(farm_background_updater(bot, db)) # (Задача фермы)
    
    logging.info("Start polling")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
