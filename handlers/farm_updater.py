# handlers/farm_updater.py
import asyncio
import logging
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest
from contextlib import suppress

from database import Database
# (Импортируем FarmCallback, чтобы кнопки "оживали")
from handlers.farm import FarmCallback 
# --- ✅✅✅ НОВЫЙ ИМПОРТ (для имен) ---
from handlers.farm_config import CROP_SHORT 

async def farm_background_updater(bot: Bot, db: Database):
    logging.info("Фоновая задача (Farm Updater) запущена...")
    
    # (Вспомогательная функция, чтобы не дублировать код кнопки)
    def get_refresh_button(user_id: int) -> InlineKeyboardMarkup:
        """Создает кнопку '⬅️ Открыть Ферму'"""
        refresh_button = InlineKeyboardButton(
            text="⬅️ Открыть Ферму", 
            # (Этот Callback вызовет 'cq_farm_main_dashboard' из handlers/farm.py)
            callback_data=FarmCallback(action="main_dashboard", owner_id=user_id).pack()
        )
        return InlineKeyboardMarkup(inline_keyboard=[[refresh_button]])

    while True:
        try:
            # --- 1. ОБРАБОТКА АПГРЕЙДОВ И ПИВОВАРНИ ---
            tasks = await db.get_pending_notifications()
            
            for user_id, task_type, data in tasks:
                logging.info(f"[Farm Updater] Найдена задача (Task): {task_type} для {user_id}")
                
                text = ""
                keyboard = get_refresh_button(user_id) # (Кнопка 'Открыть Ферму')

                try:
                    if task_type == 'field_upgrade':
                        await db.finish_upgrade(user_id, 'field')
                        level = data
                        text = f"✅ Улучшение [🌾 Поля] до Ур. {level} завершено!"
                    
                    elif task_type == 'brewery_upgrade':
                        await db.finish_upgrade(user_id, 'brewery')
                        level = data
                        text = f"✅ Улучшение [🏭 Пивоварни] до Ур. {level} завершено!"

                    elif task_type == 'batch':
                        quantity = data
                        text = f"🏆 Ваша варка ({quantity}x) в [🏭 Пивоварне] готова к сбору!"
                    
                    if text:
                        with suppress(TelegramBadRequest): # (Если юзер забанил бота)
                            await bot.send_message(user_id, text, reply_markup=keyboard) 
                    
                    # (Помечаем апгрейд/варку как отправленное)
                    await db.mark_notification_sent(user_id, task_type)
                
                except Exception as e:
                    logging.error(f"[Farm Updater] Ошибка обработки ЗАДАЧИ для {user_id}: {e}")

            # --- 2. ✅✅✅ ОБРАБОТКА ГОТОВЫХ ПОЛЕЙ (НОВЫЙ КОД) ---
            crop_tasks = await db.get_pending_crop_notifications()
            
            for user_id, plot_num, crop_id in crop_tasks:
                logging.info(f"[Farm Updater] Найдена задача (Crop): {crop_id} (Plot {plot_num}) для {user_id}")
                
                try:
                    # (Берем имя "🌾 Зерно" из farm_config)
                    crop_name = CROP_SHORT.get(crop_id, "Что-то") 
                    text = f"🌱 <b>Урожай Готов!</b>\n{crop_name} на участке [ {plot_num} ] созрело и ждет сбора."
                    
                    keyboard = get_refresh_button(user_id) # (Кнопка 'Открыть Ферму')
                    
                    with suppress(TelegramBadRequest):
                        await bot.send_message(user_id, text, reply_markup=keyboard, parse_mode='HTML')
                        
                    # (Помечаем, что уведомили)
                    await db.mark_crop_notification_sent(user_id, plot_num)
                    
                except Exception as e:
                    logging.error(f"[Farm Updater] Ошибка обработки УРОЖАЯ для {user_id}: {e}")
            # --- ---

        except Exception as e:
            logging.error(f"[Farm Updater] Критическая ошибка в цикле: {e}")
        
        # (Проверяем каждые 30 секунд)
        await asyncio.sleep(30)
