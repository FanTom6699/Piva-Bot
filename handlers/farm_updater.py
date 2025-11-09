# handlers/farm_updater.py
import asyncio
import logging
from contextlib import suppress

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

from database import Database

# --- ИНИЦИАЛИЗАЦИЯ ---
# ❌❌❌ НЕТ РОУТЕРА. Этот файл не обрабатывает команды.

# Глобальная переменная для задачи (чтобы main.py мог ее импортировать)
farm_updater_task = None

async def process_farm_notifications(bot: Bot, db: Database):
    """
    Главная логика: Проверяет БД, завершает задачи, отправляет уведомления.
    """
    try:
        # 1. Получаем все "готовые" задачи
        pending_tasks = await db.get_pending_notifications()
        
        if not pending_tasks:
            return # Ничего не делаем
            
        logging.info(f"[Farm Updater] Найдено {len(pending_tasks)} готовых задач.")
        
        for user_id, task_type, data in pending_tasks:
            
            # 2. Завершаем задачу в БД
            if task_type == 'field_upgrade':
                await db.finish_upgrade(user_id, 'field')
                level = data
                text = f"✅ <b>Улучшение Завершено!</b>\n\n🌾 Твоё Поле достигло <b>Уровня {level}</b>!"
                
            elif task_type == 'brewery_upgrade':
                await db.finish_upgrade(user_id, 'brewery')
                level = data
                text = f"✅ <b>Улучшение Завершено!</b>\n\n🏭 Твоя Пивоварня достигла <b>Уровня {level}</b>!"
                
            elif task_type == 'batch':
                # (Для варки мы ничего НЕ завершаем, юзер должен сам нажать "Собрать")
                quantity = data
                text = f"🍺 <b>Варка Готова!</b>\n\nТвоя партия из <b>{quantity}x</b> порций готова!\n" \
                       f"Зайди в /farm, чтобы забрать награду!"
            
            else:
                continue # Неизвестный тип
                
            # 3. Помечаем, что отправили (чтобы не спамить)
            await db.mark_notification_sent(user_id, task_type)
            
            # 4. Отправляем уведомление юзеру
            with suppress(TelegramBadRequest):
                await bot.send_message(user_id, text, parse_mode="HTML")

    except Exception as e:
        logging.error(f"Критическая ошибка в process_farm_notifications: {e}")

async def farm_background_updater(bot: Bot, db: Database):
    """(Эта функция импортируется в main.py)"""
    logging.info("Фоновая задача (Farm Updater) запущена...")
    while True:
        await process_farm_notifications(bot, db)
        # (Проверяем раз в 60 секунд)
        await asyncio.sleep(60)
