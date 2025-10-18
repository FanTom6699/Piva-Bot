# handlers.py
import random
from datetime import datetime, timedelta

from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import CommandStart, Command

from database import Database
from utils import format_time_delta

# Инициализируем роутер и базу данных
router = Router()
db = Database()

# --- Фразы для команды /beer ---
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

COOLDOWN_SECONDS = 7200  # 2 часа в секундах

# --- Обработчики команд ---

@router.message(CommandStart())
async def cmd_start(message: Message):
    user = message.from_user
    if not await db.user_exists(user.id):
        await db.add_user(user.id, user.first_name, user.last_name, user.username)
        await message.answer(
            f"Привет, {user.full_name}! 👋\n"
            f"Добро пожаловать в наш пивной клуб. Твой начальный рейтинг: 0 🍺.\n"
            f"Увеличивай его командой /beer!"
        )
    else:
        rating = await db.get_user_beer_rating(user.id)
        await message.answer(
            f"С возвращением, {user.full_name}! 🍻\n"
            f"Твой текущий рейтинг: {rating} 🍺."
        )

@router.message(Command("beer"))
async def cmd_beer(message: Message):
    user_id = message.from_user.id
    last_beer_time = await db.get_last_beer_time(user_id)
    
    # Проверка кулдауна
    if last_beer_time:
        time_since_last_beer = datetime.now() - last_beer_time
        if time_since_last_beer.total_seconds() < COOLDOWN_SECONDS:
            remaining_time = timedelta(seconds=COOLDOWN_SECONDS) - time_since_last_beer
            await message.answer(
                f"⌛ Ты уже недавно пил! 🍻\n"
                f"Вернись в бар через: {format_time_delta(remaining_time)}."
            )
            return

    # Логика игры
    current_rating = await db.get_user_beer_rating(user_id)
    rating_change = random.randint(-5, 10)
    
    if rating_change > 0:
        new_rating = current_rating + rating_change
        phrase = random.choice(BEER_WIN_PHRASES).format(rating_change=rating_change)
    else:
        rating_loss = abs(rating_change)
        if current_rating - rating_loss <= 0:
            actual_loss = current_rating
            new_rating = 0
            if actual_loss > 0:
                phrase = random.choice(BEER_LOSE_PHRASES_ZERO).format(rating_loss=actual_loss)
            else: # Если рейтинг уже был 0
                phrase = "Ты попытался выпить, но у тебя и так 0 🍺. Попробуй еще раз позже!"
        else:
            new_rating = current_rating - rating_loss
            phrase = random.choice(BEER_LOSE_PHRASES_RATING).format(rating_loss=rating_loss)

    await db.update_beer_data(user_id, new_rating)
    await message.answer(phrase, parse_mode='HTML')


@router.message(Command("top"))
async def cmd_top(message: Message):
    top_users = await db.get_top_users()
    if not top_users:
        await message.answer("В баре пока никого нет, чтобы составить топ. Будь первым!")
        return

    top_text = "🏆 <b>Топ-10 пивных мастеров:</b> 🏆\n\n"
    medals = ["🥇", "🥈", "🥉"]
    
    for i, user_data in enumerate(top_users):
        first_name, last_name, rating = user_data
        full_name = first_name + (f" {last_name}" if last_name else "")
        
        if i < 3:
            top_text += f"{medals[i]} {i+1}. {full_name} — {rating} 🍺\n"
        else:
            top_text += f"🏅 {i+1}. {full_name} — {rating} 🍺\n"
            
    await message.answer(top_text, parse_mode='HTML')
