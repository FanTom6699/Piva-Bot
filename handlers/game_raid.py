# handlers/game_raid.py
import asyncio
import random
import logging
from datetime import datetime, timedelta
from contextlib import suppress

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Filter
from aiogram.filters.callback_data import CallbackData
from aiogram.exceptions import TelegramBadRequest

from database import Database
from settings import settings_manager
from .common import check_user_registered

# --- ИНИЦИАЛИЗАЦИЯ ---
raid_router = Router()
db = Database(db_name='/data/bot_database.db')

# Глобальная переменная для отслеживания запущенных задач (чтобы не дублировать)
active_raid_tasks = {}

# --- CALLBACKDATA ---
class RaidCallbackData(CallbackData, prefix="raid"):
    action: str
    
class RaidAttackCallbackData(CallbackData, prefix="raid_attack"):
    action: str # 'normal' or 'strong'

# --- ФУНКЦИИ ИГРЫ ---

def format_health_bar(current: int, maximum: int, width: int = 10) -> str:
    """Генерирует текстовый бар здоровья."""
    if maximum == 0: return "[ПУСТО]"
    percent = current / maximum
    filled_blocks = int(percent * width)
    empty_blocks = width - filled_blocks
    return f"[{'█' * filled_blocks}{' ' * empty_blocks}] {int(percent * 100)}%"

async def generate_raid_message(chat_id: int) -> dict:
    """Готовит текст и клавиатуру для сообщения о рейде."""
    raid_data = await db.get_active_raid(chat_id)
    if not raid_data:
        return {"text": "Рейд не найден.", "reply_markup": None}
    
    chat_id, msg_id, health, max_health, reward, end_time_iso = raid_data
    end_time = datetime.fromisoformat(end_time_iso)
    time_left = end_time - datetime.now()
    
    if time_left.total_seconds() <= 0:
         time_str = "Время вышло!"
    else:
        hours, rem = divmod(time_left.seconds, 3600)
        minutes, _ = divmod(rem, 60)
        time_str = f"{time_left.days}д {hours}ч {minutes}м"

    health_bar = format_health_bar(health, max_health)
    
    text = (
        f"🚨 <b>В БАРЕ ПЕРЕПОЛОХ!</b> 🚨\n\n"
        f"На пороге <b>Огромный Вышибала</b>!\n"
        f"❤️ Здоровье: <code>{health_bar}</code>\n"
        f"({health} / {max_health})\n\n"
        f"💰 Награда за победу: <b>{reward} 🍺</b>\n"
        f"⏳ Конец через: <b>{time_str}</b>"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⚔️ АТАКОВАТЬ", callback_data=RaidCallbackData(action="show_attack").pack()),
            InlineKeyboardButton(text="ℹ️ Инфо", callback_data=RaidCallbackData(action="info").pack())
        ]
    ])
    
    return {"text": text, "reply_markup": keyboard}

async def check_raid_status(chat_id: int, bot: Bot):
    """Проверяет, завершен ли рейд (победа или время)."""
    raid_data = await db.get_active_raid(chat_id)
    if not raid_data:
        return
        
    chat_id, msg_id, health, max_health, reward, end_time_iso = raid_data
    end_time = datetime.fromisoformat(end_time_iso)
    
    is_ended = False
    final_text = ""

    if health <= 0:
        is_ended = True
        final_text = (
            f"🏆 <b>ПОБЕДА!</b> 🏆\n\n"
            f"Вышибала повержен! Бар спасен! "
            f"Все участники рейда делят между собой <b>{reward} 🍺</b>!"
        )
    elif datetime.now() >= end_time:
        is_ended = True
        final_text = (
            f"😭 <b>ПОРАЖЕНИЕ!</b> 😭\n\n"
            f"Время вышло! Вышибала оказался слишком силен... "
            f"Бар закрыт на уборку."
        )

    if is_ended:
        # Открепляем и удаляем старое сообщение
        with suppress(TelegramBadRequest):
            await bot.unpin_chat_message(chat_id=chat_id, message_id=msg_id)
            await bot.delete_message(chat_id=chat_id, message_id=msg_id)
            
        participants = await db.get_all_raid_participants(chat_id)
        
        if health <= 0 and participants:
            reward_per_user = int(reward / len(participants))
            if reward_per_user > 0:
                final_text += f"\n\nКаждый из {len(participants)} участников получает по {reward_per_user} 🍺!"
                for user_id, damage in participants:
                    await db.change_rating(user_id, reward_per_user)
            else:
                 final_text += "\n\nТак много участников, что награда округлилась до нуля. Но вы сражались!"
        
        # Отправляем финальное сообщение
        await bot.send_message(chat_id=chat_id, text=final_text, parse_mode='HTML')
        
        # Удаляем рейд из БД
        await db.delete_raid(chat_id)
        # Удаляем задачу из памяти
        if chat_id in active_raid_tasks:
            active_raid_tasks[chat_id].cancel()
            del active_raid_tasks[chat_id]
            
        return False # Рейд завершен
    
    return True # Рейд продолжается

async def raid_background_updater(chat_id: int, bot: Bot):
    """Фоновая задача, которая проверяет рейд и шлет напоминания."""
    while True:
        try:
            is_active = await check_raid_status(chat_id, bot)
            if not is_active:
                break # Завершаем задачу, если рейд окончен
            
            # Напоминание
            await asyncio.sleep(settings_manager.raid_reminder_hours * 3600)
            
            raid_data = await db.get_active_raid(chat_id)
            if raid_data:
                health, max_health = raid_data[2], raid_data[3]
                await bot.send_message(
                    chat_id=chat_id,
                    text=f"<i>Битва с Вышибалой продолжается! ⚔️\n"
                         f"Осталось здоровья: [{health}/{max_health}]\n"
                         f"Жмите на закреп, нужна помощь!</i>",
                    parse_mode='HTML'
                )
                
        except asyncio.CancelledError:
            logging.info(f"Задача обновления рейда для чата {chat_id} остановлена.")
            break
        except Exception as e:
            logging.error(f"Ошибка в raid_background_updater для чата {chat_id}: {e}")
            await asyncio.sleep(60) # Пауза перед повторной попыткой в случае сбоя


# --- ХЭНДЛЕРЫ КНОПОК РЕЙДА ---

@raid_router.callback_query(RaidCallbackData.filter(F.action == "info"))
async def raid_info(callback: CallbackQuery):
    await callback.answer(
        text=f"Атакуйте босса!\n"
             f"• Обычный удар: 1 раз в {settings_manager.raid_hit_cooldown_minutes} мин.\n"
             f"• Сильный удар: стоит {settings_manager.raid_strong_hit_cost} 🍺.",
        show_alert=True
    )

@raid_router.callback_query(RaidCallbackData.filter(F.action == "show_attack"))
async def raid_show_attack(callback: CallbackQuery):
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    
    if not await check_user_registered(callback, bot=callback.bot):
        return
        
    participant_data = await db.get_raid_participant(chat_id, user_id)
    cooldown = settings_manager.raid_hit_cooldown_minutes * 60
    
    can_normal_attack = True
    if participant_data:
        last_hit_time = datetime.fromisoformat(participant_data[3])
        time_since_hit = (datetime.now() - last_hit_time).total_seconds()
        if time_since_hit < cooldown:
            can_normal_attack = False
            
    balance = await db.get_user_beer_rating(user_id)
    cost = settings_manager.raid_strong_hit_cost
    can_strong_attack = balance >= cost

    # Генерируем кнопки выбора атаки
    buttons = []
    if can_normal_attack:
        buttons.append(InlineKeyboardButton(
            text="🗡️ Обычный удар (Готово)", 
            callback_data=RaidAttackCallbackData(action="normal").pack()
        ))
    if can_strong_attack:
        buttons.append(InlineKeyboardButton(
            text=f"💥 Сильный удар ({cost} 🍺)", 
            callback_data=RaidAttackCallbackData(action="strong").pack()
        ))
    
    if not buttons:
        await callback.answer(
            f"Вы пока не можете атаковать! "
            f"Обычный удар будет готов через {int((cooldown - time_since_hit)/60)} мин. "
            f"Для сильного удара нужно {cost} 🍺.",
            show_alert=True
        )
        return

    await callback.answer()
    await callback.message.answer(
        "Выберите тип атаки:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[buttons]),
        ephemeral=True # Сообщение видит только тот, кто нажал
    )

@raid_router.callback_query(RaidAttackCallbackData.filter())
async def raid_do_attack(callback: CallbackQuery, callback_data: RaidAttackCallbackData, bot: Bot):
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    action = callback_data.action

    if chat_id not in active_raid_tasks: # Проверяем, активен ли рейд
        return await callback.message.edit_text("Этот рейд уже завершен!")

    raid_data = await db.get_active_raid(chat_id)
    if not raid_data:
        return await callback.message.edit_text("Этот рейд уже завершен!")
    
    damage = 0
    cooldown = settings_manager.raid_hit_cooldown_minutes * 60
    
    if action == "normal":
        participant_data = await db.get_raid_participant(chat_id, user_id)
        if participant_data:
            last_hit_time = datetime.fromisoformat(participant_data[3])
            time_since_hit = (datetime.now() - last_hit_time).total_seconds()
            if time_since_hit < cooldown:
                await callback.answer(f"Обычный удар еще не готов!", show_alert=True)
                return await callback.message.delete()
        
        damage = random.randint(settings_manager.raid_normal_hit_damage_min, settings_manager.raid_normal_hit_damage_max)
        await db.add_raid_participant(chat_id, user_id, damage)
        await callback.message.edit_text(f"<i>{callback.from_user.full_name} наносит {damage} урона!</i>", parse_mode='HTML')

    elif action == "strong":
        cost = settings_manager.raid_strong_hit_cost
        balance = await db.get_user_beer_rating(user_id)
        if balance < cost:
            await callback.answer(f"Недостаточно 🍺 для сильного удара!", show_alert=True)
            return await callback.message.delete()
            
        await db.change_rating(user_id, -cost)
        damage = random.randint(settings_manager.raid_strong_hit_damage_min, settings_manager.raid_strong_hit_damage_max)
        await db.add_raid_participant(chat_id, user_id, damage)
        await callback.message.edit_text(f"<i>{callback.from_user.full_name} кидает бочонок и наносит {damage} урона!</i>", parse_mode='HTML')

    # Обновляем здоровье босса и сообщение
    await db.update_raid_health(chat_id, damage)
    new_data = await generate_raid_message(chat_id)
    
    try:
        await bot.edit_message_text(
            text=new_data["text"],
            chat_id=chat_id,
            message_id=raid_data[1], # message_id
            reply_markup=new_data["reply_markup"],
            parse_mode='HTML'
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
             logging.error(f"Ошибка при обновлении сообщения рейда: {e}")
             
    # Проверяем, не убил ли этот удар босса
    await check_raid_status(chat_id, bot)
