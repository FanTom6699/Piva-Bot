# handlers/user_commands.py
import random
from datetime import datetime, timedelta

from aiogram import Router, Bot
from aiogram.types import Message
from aiogram.filters import Command

from database import Database
from .common import check_user_registered
from utils import format_time_delta
from settings import settings_manager # <-- ИМПОРТ МЕНЕДЖЕРА

# --- ИНИЦИАЛИЗАЦИЯ ---
user_commands_router = Router()
db = Database(db_name='/data/bot_database.db')

user_spam_tracker = {}
# УДАЛЯЕМ КОНСТАНТЫ (теперь они в settings_manager)

# --- ФРАЗЫ ДЛЯ /beer ... (без изменений) ...
BEER_WIN_PHRASES = ["..."]
BEER_LOSE_PHRASES_RATING = ["..."]
BEER_LOSE_PHRASES_ZERO = ["..."]

# --- КОМАНДЫ ---
@user_commands_router.message(Command("beer"))
async def cmd_beer(message: Message, bot: Bot):
    user_id = message.from_user.id
    now = datetime.now()
    if user_id in user_spam_tracker:
        if (now - user_spam_tracker[user_id]).total_seconds() < 5:
            return
    user_spam_tracker[user_id] = now
    if message.chat.type != 'private' and not await check_user_registered(message, bot):
        return
    
    last_beer_time = await db.get_last_beer_time(user_id)
    
    # --- ИЗМЕНЕНИЕ ЗДЕСЬ ---
    beer_cooldown = settings_manager.beer_cooldown
    if last_beer_time:
        time_since = datetime.now() - last_beer_time
        if time_since.total_seconds() < beer_cooldown:
            remaining = timedelta(seconds=beer_cooldown) - time_since
            return await message.answer(f"⌛ Ты уже недавно пил! 🍻\nВернись в бар через: {format_time_delta(remaining)}.")
    
    current_rating = await db.get_user_beer_rating(user_id)
    # ... (логика выигрыша/проигрыша без изменений) ...
    # ...
    
    await db.update_beer_data(user_id, new_rating)
    await message.answer(phrase, parse_mode='HTML')

    # --- ИЗМЕНЕНИЕ ЗДЕСЬ ---
    jackpot_chance = settings_manager.jackpot_chance
    if random.randint(1, jackpot_chance) == 1:
        current_jackpot = await db.get_jackpot()
        if current_jackpot > 0:
            await db.reset_jackpot()
            await db.change_rating(user_id, current_jackpot)
            
            await bot.send_message(
                chat_id=message.chat.id,
                text=f"🎉🎉🎉 <b>Д Ж Е К П О Т!</b> 🎉🎉🎉\n\n"
                     f"Невероятно! <b>{message.from_user.full_name}</b> срывает куш и забирает весь банк!\n\n"
                     f"<b>Выигрыш: +{current_jackpot} 🍺!</b>",
                parse_mode='HTML'
            )

@user_commands_router.message(Command("top"))
async def cmd_top(message: Message, bot: Bot):
    # ... (код без изменений) ...
    pass
