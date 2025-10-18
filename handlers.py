# handlers.py
import random
from datetime import datetime, timedelta

from aiogram import Router, F, Bot
from aiogram.types import Message, ChatMemberUpdated, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart, Command, ChatMemberUpdatedFilter, IS_MEMBER, IS_NOT_MEMBER

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

# --- Вспомогательная функция для проверки регистрации ---

async def check_user_registered(message: Message, bot: Bot) -> bool:
    if await db.user_exists(message.from_user.id):
        return True
    
    me = await bot.get_me()
    start_link = f"https://t.me/{me.username}?start=register"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✍️ Зарегистрироваться", url=start_link)]
    ])
    
    await message.reply(
        "<b>Эй, новичок!</b> 🍻\n\n"
        "Прежде чем пить пиво, нужно зайти в бар! "
        "Я тебя еще не знаю. Нажми на кнопку ниже, чтобы начать диалог со мной и зарегистрироваться.",
        reply_markup=keyboard,
        parse_mode='HTML'
    )
    return False


# --- Обработчики команд ---

@router.my_chat_member(ChatMemberUpdatedFilter(member_status_changed=IS_NOT_MEMBER >> IS_MEMBER))
async def on_bot_join_group(event: ChatMemberUpdated, bot: Bot):
    me = await bot.get_me()
    await bot.send_message(
        event.chat.id,
        text=(
            "<b>Всем привет в этом чате!</b> 🍻\n\n"
            "Я Piva Bot, и я здесь, чтобы вести учет вашего пивного рейтинга!\n\n"
            "<b>Как начать:</b>\n"
            "1️⃣ Каждый участник должен написать мне в личные сообщения -> @" + me.username + " и нажать /start.\n"
            "2️⃣ Возвращайтесь сюда и используйте команду /beer, чтобы испытать удачу.\n"
            "3️⃣ Проверяйте лучших игроков командой /top.\n\n"
            "Да начнутся пивные игры!"
        ),
        parse_mode='HTML'
    )

@router.message(CommandStart())
async def cmd_start(message: Message):
    user = message.from_user
    if not await db.user_exists(user.id):
        await db.add_user(user.id, user.first_name, user.last_name, user.username)
        await message.answer(
            f"Привет, {user.full_name}! 👋\n"
            f"Добро пожаловать в наш пивной клуб. Твой начальный рейтинг: 0 🍺.\n"
            f"Увеличивай его командой /beer в любом чате, где я есть!"
        )
    else:
        rating = await db.get_user_beer_rating(user.id)
        await message.answer(
            f"С возвращением, {user.full_name}! 🍻\n"
            f"Твой текущий рейтинг: {rating} 🍺."
        )

@router.message(Command("beer"))
async def cmd_beer(message: Message, bot: Bot):
    if message.chat.type != 'private':
        if not await check_user_registered(message, bot):
            return

    user_id = message.from_user.id
    last_beer_time = await db.get_last_beer_time(user_id)
    
    if last_beer_time:
        time_since_last_beer = datetime.now() - last_beer_time
        if time_since_last_beer.total_seconds() < COOLDOWN_SECONDS:
            remaining_time = timedelta(seconds=COOLDOWN_SECONDS) - time_since_last_beer
            await message.answer(
                f"⌛ Ты уже недавно пил! 🍻\n"
                f"Вернись в бар через: {format_time_delta(remaining_time)}."
            )
            return

    # --- НОВАЯ ЛОГИКА ВЗВЕШЕННОГО РАНДОМА ---
    current_rating = await db.get_user_beer_rating(user_id)
    
    outcomes = ['small_win', 'loss', 'big_win']
    weights = [0.60, 0.25, 0.15]  # 60% small win, 25% loss, 15% big win
    
    chosen_outcome = random.choices(outcomes, weights=weights, k=1)[0]
    
    if chosen_outcome == 'small_win':
        rating_change = random.randint(1, 4)
    elif chosen_outcome == 'big_win':
        rating_change = random.randint(5, 10)
    else: # 'loss'
        rating_change = random.randint(-5, -1)
    # --- КОНЕЦ НОВОЙ ЛОГИКИ ---

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
            else: 
                phrase = "Ты попытался выпить, но у тебя и так 0 🍺. Попробуй еще раз позже!"
        else:
            new_rating = current_rating - rating_loss
            phrase = random.choice(BEER_LOSE_PHRASES_RATING).format(rating_loss=rating_loss)

    await db.update_beer_data(user_id, new_rating)
    await message.answer(phrase, parse_mode='HTML')


@router.message(Command("top"))
async def cmd_top(message: Message, bot: Bot):
    if message.chat.type != 'private':
        if not await check_user_registered(message, bot):
            return

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
