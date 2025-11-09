# handlers/farm_updater.py
import asyncio
import logging
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from contextlib import suppress

from database import Database
# ✅ ИЗМЕНЕНО: Импортируем "Настройки" из farm_config.py
from .farm_config import FIELD_UPGRADES, BREWERY_UPGRADES, get_level_data

farm_updater_task = None

# --- ✅✅✅ ГЛАВНАЯ ФУНКЦИЯ "УВЕДОМЛЕНИЙ" (Твой План) ✅✅✅ ---
async def farm_background_updater(bot: Bot, db: Database):
    logging.info("Фоновая задача (Farm Updater) запущена...")
    
    while True:
        await asyncio.sleep(60) 
        
        try:
            tasks = await db.get_pending_notifications()
            
            if not tasks:
                continue 

            logging.info(f"[Farm Updater] Найдено {len(tasks)} готовых задач (Уведомлений)...")

            for (user_id, task_type, data) in tasks:
                text_to_send = ""
                
                try:
                    if task_type == 'field_upgrade':
                        new_level = data
                        await db.finish_upgrade(user_id, 'field')
                        
                        stats = get_level_data(new_level, FIELD_UPGRADES)
                        bonus_text = ""
                        # (Сравниваем с Уровнем НИЖЕ)
                        prev_stats = get_level_data(new_level-1, FIELD_UPGRADES)
                        
                        if stats['plots'] > prev_stats['plots']:
                            bonus_text += f" (Открыт {stats['plots']}-й Участок!)"
                        if stats['chance_x2'] > prev_stats['chance_x2']:
                             bonus_text += f" (Шанс x2 Урожая теперь {stats['chance_x2']}!)"
                        
                        text_to_send = f"🎉 <b>Прокачка Завершена!</b> 🎉\n\nТвоё <b>[🌾 Моё Поле]</b> достигло <b>Уровня {new_level}</b>!{bonus_text}\n\nЗаходи в /farm, чтобы продолжить!"

                    elif task_type == 'brewery_upgrade':
                        new_level = data
                        await db.finish_upgrade(user_id, 'brewery')
                        
                        stats = get_level_data(new_level, BREWERY_UPGRADES)
                        text_to_send = (
                            f"🎉 <b>Прокачка Завершена!</b> 🎉\n\n"
                            f"Твоя <b>[🏭 Пивоварня]</b> достигла <b>Уровня {new_level}</b>!\n"
                            f"<i>(Новая Награда: +{stats['reward']} 🍺, Новая Варка: {stats['brew_time_min']} мин/порция)</i>\n\n"
                            f"Заходи в /farm, чтобы варить!"
                        )

                    elif task_type == 'batch':
                        batch_size = data
                        farm_data = await db.get_user_farm_data(user_id)
                        brew_stats = get_level_data(farm_data.get('brewery_level', 1), BREWERY_UPGRADES)
                        total_reward = brew_stats['reward'] * batch_size
                        
                        text_to_send = (
                            f"🔥 <b>"Пакетная Варка" ({batch_size}x) готова!</b> 🔥\n\n"
                            f"Заходи в /farm и нажимай [🏭 ЗАБРАТЬ +{total_reward} 🍺]!"
                        )
                    
                    if text_to_send:
                        with suppress(TelegramBadRequest, TelegramForbiddenError):
                            await bot.send_message(user_id, text_to_send)
                            
                    await db.mark_notification_sent(user_id, task_type)

                except Exception as e:
                    logging.error(f"[Farm Updater] Ошибка при обработке задачи (user: {user_id}, type: {task_type}): {e}")

        except Exception as e:
            logging.error(f"[Farm Updater] Критическая ошибка в цикле: {e}")
            await asyncio.sleep(300)
