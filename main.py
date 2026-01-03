## main.py
import asyncio
import logging
import os
from datetime import datetime

from dotenv import load_dotenv

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from handlers import main_router
from handlers.game_raid import raid_background_updater, active_raid_tasks

from database import Database
from settings import SettingsManager

# ─────────────────────────────────────────────
# Загрузка .env
# ─────────────────────────────────────────────
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN не найден. Проверь файл .env")


# ─────────────────────────────────────────────
# Запуск активных рейдов при старте
# ─────────────────────────────────────────────
async def start_active_raid_tasks(bot: Bot, db: Database, settings: SettingsManager):
    logging.info("Проверка активных рейдов...")
    active_raids = await db.get_all_active_raids()
    count = 0

    for raid in active_raids:
        chat_id = raid[0]
        if chat_id not in active_raid_tasks:
            task = asyncio.create_task(
                raid_background_updater(chat_id, bot, db, settings)
            )
            active_raid_tasks[chat_id] = task
            count += 1

    logging.info(f"Запущено {count} фоновых задач для активных рейдов.")


# ─────────────────────────────────────────────
# Фоновая задача фермы
# ─────────────────────────────────────────────
async def farm_background_updater(bot: Bot, db: Database):
    logging.info("Фоновая задача (Farm Updater) запущена...")

    while True:
        await asyncio.sleep(60)

        try:
            now = datetime.now()
            pending_tasks = await db.get_pending_notifications(now)

            if not pending_tasks:
                continue

            logging.info(f"[Farm Updater] Найдено {len(pending_tasks)} задач")

            users_to_check = {uid for uid, _, _ in pending_tasks}
            for user_id in users_to_check:
                await db.check_and_apply_upgrades(user_id)

            for user_id, task_type, data in pending_tasks:
                text = None

                if task_type == "batch":
                    text = f"🍻 Твоя варка (x{data}) готова! Забери награду!"
                elif task_type == "field_upgrade":
                    text = "🌾 Улучшение Поля завершено!"
                elif task_type == "brewery_upgrade":
                    text = "🏭 Улучшение Пивоварни завершено!"

                if text:
                    try:
                        await bot.send_message(user_id, text)
                        await db.mark_notification_sent(user_id, task_type)
                        logging.info(
                            f"[Farm Updater] Отправлено {task_type} пользователю {user_id}"
                        )
                    except Exception as e:
                        logging.warning(
                            f"[Farm Updater] Не удалось отправить {task_type} пользователю {user_id}: {e}"
                        )
                        await db.mark_notification_sent(user_id, task_type)

        except Exception as e:
            logging.error(
                f"[Farm Updater] Критическая ошибка: {e}",
                exc_info=True
            )
            await asyncio.sleep(300)


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
    )

    logging.info("Запуск Piva Bot...")

    # База и настройки
    db = Database(db_name="/home/bot/app/bot_database.db")
    settings_manager = SettingsManager()

    await db.initialize()
    await settings_manager.load_settings(db)

    # Бот
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

    dp = Dispatcher()
    dp["db"] = db
    dp["settings"] = settings_manager

    # Роутеры
    dp.include_router(main_router)

    # Фоновые задачи
    await start_active_raid_tasks(bot, db, settings_manager)
    asyncio.create_task(farm_background_updater(bot, db))

    logging.info("🚀 Бот запущен (polling)")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
