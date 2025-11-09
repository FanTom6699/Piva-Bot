# handlers/farm_updater.py
import asyncio
import logging
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from contextlib import suppress

from database import Database
from .farm import FIELD_UPGRADES, BREWERY_UPGRADES, get_level_data # (Импортируем прайс-листы)

# --- Глобальная переменная для отслеживания ЗАПУЩЕННОЙ задачи ---
# (Чтобы не запустить 2 апдейтера)
farm_updater_task = None

# --- ✅✅✅ ГЛАВНАЯ ФУНКЦИЯ "УВЕДОМЛЕНИЙ" (Твой План) ✅✅✅ ---
async def farm_background_updater(bot: Bot, db: Database):
    """
    "Фоновая Задача" (как у /raid).
    Проверяет 24/7, не готовы ли "Пакетные Варки" или "Прокачки".
    Если готовы - Завершает Прокачку и Шлет ЛС.
    """
    logging.info("Фоновая задача (Farm Updater) запущена...")
    
    while True:
        await asyncio.sleep(60) # Проверяем раз в минуту
        
        try:
            # 1. Получаем из БД список ВСЕХ, кто ждет (Ур. 10, Варка 10x)
            # (user_id, 'batch', batch_size)
            # (user_id, 'field_upgrade', new_level)
            # (user_id, 'brewery_upgrade', new_level)
            tasks = await db.get_pending_notifications()
            
            if not tasks:
                continue # Если нечего делать, спим дальше

            logging.info(f"[Farm Updater] Найдено {len(tasks)} готовых задач (Уведомлений)...")

            for (user_id, task_type, data) in tasks:
                text_to_send = ""
                
                try:
                    # 2. ЗАВЕРШАЕМ "ПРОКАЧКУ" (Это важно!)
                    # (Мы повышаем уровень, А ПОТОМ шлем ЛС)
                    if task_type == 'field_upgrade':
                        new_level = data
                        # ЗАВЕРШАЕМ (Ур. 9 -> Ур. 10)
                        await db.finish_upgrade(user_id, 'field')
                        
                        # Собираем Бонусы (чтобы написать в ЛС)
                        stats = get_level_data(new_level, FIELD_UPGRADES)
                        bonus_text = ""
                        if stats['plots'] > get_level_data(new_level-1, FIELD_UPGRADES)['plots']:
                            bonus_text += f" (Открыт {stats['plots']}-й Участок!)"
                        if stats['chance_x2'] > get_level_data(new_level-1, FIELD_UPGRADES)['chance_x2']:
                             bonus_text += f" (Шанс x2 Урожая теперь {stats['chance_x2']}!)"
                        
                        text_to_send = f"🎉 <b>Прокачка Завершена!</b> 🎉\n\nТвоё <b>[🌾 Моё Поле]</b> достигло <b>Уровня {new_level}</b>!{bonus_text}\n\nЗаходи в /farm, чтобы продолжить!"

                    elif task_type == 'brewery_upgrade':
                        new_level = data
                        # ЗАВЕРШАЕМ (Ур. 9 -> Ур. 10)
                        await db.finish_upgrade(user_id, 'brewery')
                        
                        stats = get_level_data(new_level, BREWERY_UPGRADES)
                        text_to_send = (
                            f"🎉 <b>Прокачка Завершена!</b> 🎉\n\n"
                            f"Твоя <b>[🏭 Пивоварня]</b> достигла <b>Уровня {new_level}</b>!\n"
                            f"<i>(Новая Награда: +{stats['reward']} 🍺, Новая Варка: {stats['brew_time_min']} мин/порция)</i>\n\n"
                            f"Заходи в /farm, чтобы варить!"
                        )

                    elif task_type == 'batch':
                        # "Пакетная Варка" (Мы ее не завершаем, только шлем ЛС)
                        batch_size = data
                        # (Нам нужно Узнать Награду)
                        farm_data = await db.get_user_farm_data(user_id)
                        brew_stats = get_level_data(farm_data.get('brewery_level', 1), BREWERY_UPGRADES)
                        total_reward = brew_stats['reward'] * batch_size
                        
                        text_to_send = (
                            f"🔥 <b>"Пакетная Варка" ({batch_size}x) готова!</b> 🔥\n\n"
                            f"Заходи в /farm и нажимай [🏭 ЗАБРАТЬ +{total_reward} 🍺]!"
                        )
                    
                    # 3. ОТПРАВЛЯЕМ ЛС
                    if text_to_send:
                        with suppress(TelegramBadRequest, TelegramForbiddenError):
                            # (Если юзер заблокировал бота, мы просто игнорируем)
                            await bot.send_message(user_id, text_to_send)
                            
                    # 4. СТАВИМ "ФЛАЖОК" (Чтобы не спамить 100 раз)
                    await db.mark_notification_sent(user_id, task_type)

                except Exception as e:
                    logging.error(f"[Farm Updater] Ошибка при обработке задачи (user: {user_id}, type: {task_type}): {e}")

        except Exception as e:
            logging.error(f"[Farm Updater] Критическая ошибка в цикле: {e}")
            await asyncio.sleep(300) # (В случае сбоя БД, ждем 5 минут)
