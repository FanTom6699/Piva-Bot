# handlers/user_commands.py
import random
from datetime import datetime, timedelta

from aiogram import Router, Bot
from aiogram.types import Message
from aiogram.filters import Command

from database import Database
from .common import check_user_registered
from utils import format_time_delta

# --- ИНИЦИАЛИЗАЦИЯ ---
user_commands_router = Router()
db = Database(db_name='/data/bot_database.db')

BEER_COOLDOWN_SECONDS = 7200
user_spam_tracker = {}

# --- ФРАЗЫ ДЛЯ КОМАНДЫ /beer ---
BEER_WIN_PHRASES = [
    "🥳🍻 Ты успешно бахнул на <b>+{rating_change}</b> 🍺!",
    "🎉🍻 Отличный глоток! Твой рейтинг вырос на <b>+{rating_change}</b> 🍺!",
    "😌🍻 Удача на твоей стороне! Ты выпил +<b>{rating_change}</b> 🍺!",
    "🌟🍻 Победа! Бармен налил тебе +<b>{rating_change}</b> 🍺!",
]
BEER_LOSE_PHRASES_RATING = [
    "😖🍻 Неудача! Ты пролил <b>{rating_loss}</b> 🍺 рейтинга!",
    "😡🍻 Обидно! <b>{rating_loss}</b> 🍺 испарилось!",
]
BEER_LOSE_PHRASES_ZERO = [
    "😭💔 Братья Уизли отжали у тебя все <b>{rating_loss}</b> 🍺! Ты на нуле!",
    "😖🍻 Полный провал! Весь твой рейтинг (<b>{rating_loss}</b> 🍺) обнулился!",
]

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
    if last_beer_time:
        time_since = datetime.now() - last_beer_time
        if time_since.total_seconds() < BEER_COOLDOWN_SECONDS:
            remaining = timedelta(seconds=BEER_COOLDOWN_SECONDS) - time_since
            return await message.answer(f"⌛ Ты уже недавно пил! 🍻\nВернись в бар через: {format_time_delta(remaining)}.")
    current_rating = await db.get_user_beer_rating(user_id)
    outcomes = ['small_win', 'loss', 'big_win']
    weights = [0.60, 0.25, 0.15]
    chosen_outcome = random.choices(outcomes, weights=weights, k=1)[0]
    if chosen_outcome == 'small_win': rating_change = random.randint(1, 4)
    elif chosen_outcome == 'big_win': rating_change = random.randint(5, 10)
    else: rating_change = random.randint(-5, -1)
    if rating_change > 0:
        new_rating = current_rating + rating_change
        phrase = random.choice(BEER_WIN_PHRASES).format(rating_change=rating_change)
    else:
        rating_loss = abs(rating_change)
        if current_rating - rating_loss <= 0:
            actual_loss = current_rating
            new_rating = 0
            phrase = random.choice(BEER_LOSE_PHRASES_ZERO).format(rating_loss=actual_loss) if actual_loss > 0 else "Ты попытался выпить, но у тебя и так 0 🍺."
        else:
            new_rating = current_rating - rating_loss
            phrase = random.choice(BEER_LOSE_PHRASES_RATING).format(rating_loss=rating_loss)
    await db.update_beer_data(user_id, new_rating)
    await message.answer(phrase, parse_mode='HTML')

@user_commands_router.message(Command("top"))
async def cmd_top(message: Message, bot: Bot):
    if message.chat.type != 'private' and not await check_user_registered(message, bot):
        return
    top_users = await db.get_top_users()
    if not top_users: return await message.answer("В баре пока никого нет, чтобы составить топ.")

    # --- ИЗМЕНЕНИЕ ЗДЕСЬ: Логика выравнивания ---
    # 1. Находим максимальную ширину рейтинга для выравнивания
    max_rating_width = 0
    if top_users: # Убедимся, что список не пустой
        max_rating_width = len(str(top_users[0][2])) # Берем рейтинг первого (самого большого)
    
    top_text = "🏆 <b>Топ-10 пивных мастеров:</b> 🏆\n\n"
    medals = ["🥇", "🥈", "🥉"]
    
    for i, (first_name, last_name, rating) in enumerate(top_users):
        full_name = first_name + (f" {last_name}" if last_name else "")
        place = i + 1
        medal = medals[i] if i < 3 else "🏅"
        
        # 2. Выравниваем рейтинг по правому краю
        rating_str = str(rating).rjust(max_rating_width)
        
        top_text += f"{medal} {place}. {full_name} — <code>{rating_str}</code> 🍺\n"
    # --- КОНЕЦ ИЗМЕНЕНИЯ ---
            
    await message.answer(top_text, parse_mode='HTML')
