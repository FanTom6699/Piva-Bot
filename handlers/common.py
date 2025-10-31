# handlers/user_commands.py
import random
import time
import html 
from aiogram import Router, F, Bot
from aiogram.types import Message
from aiogram.filters import Command
from database import Database
from settings import SettingsManager
from utils import format_time_delta
from handlers.common import check_user_registered

user_router = Router()

# (Наши новые атмосферные фразы)
BEER_WIN_PHRASES = [
    "🍻 Чин-чин! <i>Отличный глоток!</i>\nБармен подмигнул и налил тебе еще: <b>+{rating_change}</b> 🍺!",
    "😋🍻 <i>Вкуснотища!</i>\nТвой рейтинг растет: <b>+{rating_change}</b> 🍺!",
    "🌟🍻 <i>Везет же! Кажется, это пиво было за счет заведения.</i>\nПолучено +<b>{rating_change}</b> 🍺!",
    "🥳 <i>За твой счет!</i>\n...шутка! Бармен угощает: <b>+{rating_change}</b> 🍺!"
]
BEER_LOSE_PHRASES_RATING = [
    "😖 Ох! <i>Пролил... бывает.</i>\nПотеряно: <b>{rating_loss}</b> 🍺. (Но не переживай, всё пошло в <b>общий джекпот!</b> 😉)",
    "😭 <i>Мимо рта!</i>\nТы теряешь <b>{rating_loss}</b> 🍺. (Зато <b>джекпот стал больше!</b>)",
    "🤢 <i>Кажется, пиво было... не очень.</i>\nМинус <b>{rating_loss}</b> 🍺. (Банк джекпота пополнен!)",
    "🤦‍♂️ <i>Уронил кружку!</i>\nПотеря: <b>{rating_loss}</b> 🍺. (По крайней мере, джекпот вырос...)"
]


@user_router.message(Command("beer"))
async def cmd_beer(message: Message, bot: Bot, db: Database, settings: SettingsManager):
    if message.chat.type != "private":
        if not await check_user_registered(message, bot, db):
            return

    user_id = message.from_user.id
    current_time_obj = time.time() # Используем объект time для сравнения
    current_time_int = int(current_time_obj)

    # --- ИСПРАВЛЕНИЕ ОШИБКИ 2 (Часть А): 'get_user_last_beer_time' -> 'get_last_beer_time' ---
    last_beer_time_obj = await db.get_last_beer_time(user_id) 
    # --- КОНЕЦ ИСПРАВЛЕНИЯ 2 (Часть А) ---
    
    cooldown = settings.beer_cooldown
    
    if last_beer_time_obj:
        # Конвертируем timestamp из БД в int для сравнения
        last_beer_time_int = int(last_beer_time_obj.timestamp())
        
        if (current_time_int - last_beer_time_int) < cooldown:
            remaining = cooldown - (current_time_int - last_beer_time_int)
            return await message.answer(f"⌛ Полегче, друг! 🍻\nТы только что пил. Следующая кружка будет готова через: {format_time_delta(remaining)}.")

    # --- ИСПРАВЛЕНИЕ ОШИБКИ 2 (Часть Б): Вызываем 'update_user_last_beer_time' (мы добавим его в database.py) ---
    # Передаем current_time_obj (datetime)
    await db.update_user_last_beer_time(user_id, time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(current_time_obj)))
    # --- КОНЕЦ ИСПРАВЛЕНИЯ 2 (Часть Б) ---

    # Логика выигрыша/проигрыша
    chance = random.random()
    
    # 1. Шанс на джекпот
    if chance < settings.jackpot_chance:
        current_jackpot = await db.get_jackpot()
        if current_jackpot < 1:
             rating_change = random.randint(settings.big_win_min, settings.big_win_max)
             phrase = random.choice(BEER_WIN_PHRASES).format(rating_change=rating_change)
             await db.change_rating(user_id, rating_change)
             return await message.answer(phrase, parse_mode='HTML')

        await db.reset_jackpot()
        await db.change_rating(user_id, current_jackpot)
        
        text=f"💥💰 <b>Д Ж Е К П О Т!</b> 💰💥\n\n" \
             f"<i>Звон монет заглушил шум бара!</i>\n\n" \
             f"<b>{message.from_user.full_name}</b> срывает куш! Вся 'копилка' твоя!\n\n" \
             f"<b>Выигрыш: +{current_jackpot} 🍺!</b>"
        
        return await message.answer(text, parse_mode='HTML')

    # 2. Шанс на большой выигрыш
    if chance < (settings.jackpot_chance + settings.big_win_chance):
        rating_change = random.randint(settings.big_win_min, settings.big_win_max)
        phrase = random.choice(BEER_WIN_PHRASES).format(rating_change=rating_change)
        await db.change_rating(user_id, rating_change)
        return await message.answer(phrase, parse_mode='HTML')

    # 3. Шанс на обычный выигрыш
    if chance < (settings.jackpot_chance + settings.big_win_chance + settings.normal_win_chance):
        rating_change = random.randint(settings.normal_win_min, settings.normal_win_max)
        phrase = random.choice(BEER_WIN_PHRASES).format(rating_change=rating_change)
        await db.change_rating(user_id, rating_change)
        return await message.answer(phrase, parse_mode='HTML')

    # 4. Проигрыш (с пополнением джекпота)
    rating_loss = random.randint(settings.lose_min, settings.lose_max)
    user_rating = await db.get_user_beer_rating(user_id)
    
    actual_loss = min(user_rating, rating_loss)
    
    if actual_loss > 0:
        await db.change_rating(user_id, -actual_loss)
        await db.update_jackpot(actual_loss)
        phrase = random.choice(BEER_LOSE_PHRASES_RATING).format(rating_loss=actual_loss)
        return await message.answer(phrase, parse_mode='HTML')
    else:
        # Утешительный +1
        rating_change = 1
        phrase = f"<i>Твоя кружка пуста...</i>\nБармен сжалился и плеснул на дно: <b>+1</b> 🍺."
        await db.change_rating(user_id, rating_change)
        return await message.answer(phrase, parse_mode='HTML')


@user_router.message(Command("top"))
async def cmd_top(message: Message, db: Database):
    top_users = await db.get_top_users(10)
    
    if not top_users:
        return await message.answer("В баре пока никого нет... 🍻")

    text = "🏆 <b>Легенды Нашего Бара</b> 🏆\n\n(Топ-10 завсегдатаев)\n\n"
    for i, user in enumerate(top_users, 1):
        emoji = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "🍺"
        
        # (user[0] = first_name, user[1] = last_name, user[2] = beer_rating)
        user_name = user[0]
        if user[1]:
            user_name += f" {user[1]}"
        
        user_name = html.escape(user_name)
        
        text += f"{emoji} {i}. {user_name} - <b>{user[2]}</b> 🍺\n"

    await message.answer(text, parse_mode='HTML')
