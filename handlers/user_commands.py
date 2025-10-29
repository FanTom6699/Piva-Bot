# handlers/user_commands.py
import random
from datetime import datetime, timedelta

from aiogram import Router, Bot
from aiogram.types import Message
from aiogram.filters import Command

from database import Database
from settings import SettingsManager
from .common import check_user_registered
from utils import format_time_delta

# --- ИНИЦИАЛИЗАЦИЯ ---
user_commands_router = Router()
user_spam_tracker = {}

# --- ФРАЗЫ ДЛЯ КОМАНДЫ /beer ---
BEER_WIN_PHRASES = [
    "🥳🍻 <i>Ты успешно бахнул!</i>\nТвой рейтинг вырос на: <b>+{rating_change}</b> 🍺!",
    "🎉🍻 <i>Отличный глоток! Удача на твоей стороне!</i>\nТвой рейтинг вырос на: <b>+{rating_change}</b> 🍺!",
    "😌🍻 <i>Какой приятный вкус победы!</i>\nТы выпил +<b>{rating_change}</b> 🍺!",
    "🌟🍻 <i>Победа! Бармен налил тебе еще!</i>\nПолучаешь +<b>{rating_change}</b> 🍺!",
]
BEER_LOSE_PHRASES_RATING = [
    "😖🍻 <i>Неудача! Ты пролил пиво...</i>\nТвой рейтинг упал на: <b>{rating_loss}</b> 🍺.",
    "😡🍻 <i>Обидно! Кто-то толкнул тебя под локоть!</i>\nТы потерял <b>{rating_loss}</b> 🍺 рейтинга.",
]
BEER_LOSE_PHRASES_ZERO = [
    "😭💔 <i>Катастрофа! Братья Уизли отжали у тебя всё!</i>\nТы потерял <b>{rating_loss}</b> 🍺 и твой рейтинг обнулился!",
    "😖🍻 <i>Полный провал! Все пиво на пол!</i>\n<b>{rating_loss}</b> 🍺 рейтинга потеряно. Ты на нуле.",
]

# --- КОМАНДЫ ---
@user_commands_router.message(Command("beer"))
async def cmd_beer(message: Message, bot: Bot, db: Database, settings: SettingsManager):
    user_id = message.from_user.id
    now = datetime.now()
    if user_id in user_spam_tracker:
        if (now - user_spam_tracker[user_id]).total_seconds() < 5:
            return
    user_spam_tracker[user_id] = now
    if message.chat.type != 'private' and not await check_user_registered(message, bot, db):
        return
    
    last_beer_time = await db.get_last_beer_time(user_id)
    beer_cooldown = settings.beer_cooldown
    
    if last_beer_time:
        time_since = datetime.now() - last_beer_time
        if time_since.total_seconds() < beer_cooldown:
            remaining = timedelta(seconds=beer_cooldown) - time_since
            return await message.answer(f"⌛ Ты уже недавно пил! 🍻\nВернись в бар через: {format_time_delta(remaining)}.")
    
    current_rating = await db.get_user_beer_rating(user_id)
    outcomes = ['small_win', 'loss', 'big_win']
    weights = [0.60, 0.25, 0.15]
    chosen_outcome = random.choices(outcomes, weights=weights, k=1)[0]
    
    rating_change = 0
    new_rating = current_rating
    phrase = ""
    
    if chosen_outcome == 'small_win': 
        rating_change = random.randint(1, 4)
        new_rating = current_rating + rating_change
        phrase = random.choice(BEER_WIN_PHRASES).format(rating_change=rating_change)
    elif chosen_outcome == 'big_win': 
        rating_change = random.randint(5, 10)
        new_rating = current_rating + rating_change
        phrase = random.choice(BEER_WIN_PHRASES).format(rating_change=rating_change)
    else: 
        rating_change = random.randint(-5, -1)
        rating_loss = abs(rating_change)
        actual_loss = 0
        
        if current_rating - rating_loss <= 0:
            actual_loss = current_rating
            new_rating = 0
            if actual_loss > 0:
                phrase = random.choice(BEER_LOSE_PHRASES_ZERO).format(rating_loss=actual_loss)
            else:
                phrase = "Ты попытался выпить, но у тебя и так 0 🍺."
        else:
            actual_loss = rating_loss
            new_rating = current_rating - rating_loss
            phrase = random.choice(BEER_LOSE_PHRASES_RATING).format(rating_loss=rating_loss)
        
        if actual_loss > 0:
            await db.update_jackpot(actual_loss)
            
    await db.update_beer_data(user_id, new_rating)
    await message.answer(phrase, parse_mode='HTML')

    jackpot_chance = settings.jackpot_chance
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
async def cmd_top(message: Message, bot: Bot, db: Database):
    if message.chat.type != 'private' and not await check_user_registered(message, bot, db):
        return
    top_users = await db.get_top_users()
    if not top_users: return await message.answer("В баре пока никого нет, чтобы составить топ.")
    
    max_rating_width = 0
    if top_users:
        max_rating_width = len(str(top_users[0][2]))
    
    top_text = "🏆 <b>Топ-10 пивных мастеров:</b> 🏆\n\n"
    medals = ["🥇", "🥈", "🥉"]
    
    for i, (first_name, last_name, rating) in enumerate(top_users):
        full_name = first_name + (f" {last_name}" if last_name else "")
        place = i + 1
        medal = medals[i] if i < 3 else "🏅"
        
        rating_str = str(rating).rjust(max_rating_width)
        
        top_text += f"{medal} {place}. {full_name} — <code>{rating_str}</code> 🍺\n"
            
    await message.answer(top_text, parse_mode='HTML')
