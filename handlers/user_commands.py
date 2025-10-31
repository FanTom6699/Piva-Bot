# handlers/user_commands.py
import random
import time
import html  # --- ДОБАВЛЕНО: для экранирования имен в /top ---
from aiogram import Router, F, Bot
from aiogram.types import Message
from aiogram.filters import Command
from database import Database
from settings import SettingsManager
from utils import format_time_delta
from handlers.common import check_user_registered

user_router = Router()

# --- ИЗМЕНЕНИЕ 1: Фразы выигрыша (Более живые) ---
BEER_WIN_PHRASES = [
    "🍻 Чин-чин! <i>Отличный глоток!</i>\nБармен подмигнул и налил тебе еще: <b>+{rating_change}</b> 🍺!",
    "😋🍻 <i>Вкуснотища!</i>\nТвой рейтинг растет: <b>+{rating_change}</b> 🍺!",
    "🌟🍻 <i>Везет же! Кажется, это пиво было за счет заведения.</i>\nПолучено +<b>{rating_change}</b> 🍺!",
    "🥳 <i>За твой счет!</i>\n...шутка! Бармен угощает: <b>+{rating_change}</b> 🍺!"
]

# --- ИЗМЕНЕНИЕ 2: Фразы проигрыша (Объясняем UX: проигрыш = вклад в джекпот) ---
BEER_LOSE_PHRASES_RATING = [
    "😖 Ох! <i>Пролил... бывает.</i>\nПотеряно: <b>{rating_loss}</b> 🍺. (Но не переживай, всё пошло в <b>общий джекпот!</b> 😉)",
    "😭 <i>Мимо рта!</i>\nТы теряешь <b>{rating_loss}</b> 🍺. (Зато <b>джекпот стал больше!</b>)",
    "🤢 <i>Кажется, пиво было... не очень.</i>\nМинус <b>{rating_loss}</b> 🍺. (Банк джекпота пополнен!)",
    "🤦‍♂️ <i>Уронил кружку!</i>\nПотеря: <b>{rating_loss}</b> 🍺. (По крайней мере, джекпот вырос...)"
]
# --- КОНЕЦ ИЗМЕНЕНИЙ 1 и 2 ---


@user_router.message(Command("beer"))
async def cmd_beer(message: Message, bot: Bot, db: Database, settings: SettingsManager):
    if message.chat.type != "private":
        if not await check_user_registered(message, bot, db):
            return

    user_id = message.from_user.id
    current_time = int(time.time())
    
    # Проверка кулдауна
    last_beer_time = await db.get_user_last_beer_time(user_id)
    cooldown = settings.beer_cooldown
    
    if last_beer_time and (current_time - last_beer_time) < cooldown:
        remaining = cooldown - (current_time - last_beer_time)
        
        # --- ИЗМЕНЕНИЕ 3: Текст кулдауна (Более дружелюбный) ---
        return await message.answer(f"⌛ Полегче, друг! 🍻\nТы только что пил. Следующая кружка будет готова через: {format_time_delta(remaining)}.")
        # --- КОНЕЦ ИЗМЕНЕНИЯ 3 ---

    await db.update_user_last_beer_time(user_id, current_time)

    # Логика выигрыша/проигрыша
    chance = random.random()
    
    # 1. Шанс на джекпот
    if chance < settings.jackpot_chance:
        current_jackpot = await db.get_jackpot()
        if current_jackpot < 1: # Если джекпот пуст, выдаем обычный биг вин
             rating_change = random.randint(settings.big_win_min, settings.big_win_max)
             phrase = random.choice(BEER_WIN_PHRASES).format(rating_change=rating_change)
             await db.update_user_beer_rating(user_id, rating_change)
             return await message.answer(phrase, parse_mode='HTML')

        await db.reset_jackpot()
        await db.update_user_beer_rating(user_id, current_jackpot)
        
        # --- ИЗМЕНЕНИЕ 4: Текст джекпота (Более эмоциональный) ---
        text=f"💥💰 <b>Д Ж Е К П О Т!</b> 💰💥\n\n" \
             f"<i>Звон монет заглушил шум бара!</i>\n\n" \
             f"<b>{message.from_user.full_name}</b> срывает куш! Вся 'копилка' твоя!\n\n" \
             f"<b>Выигрыш: +{current_jackpot} 🍺!</b>"
        # --- КОНЕЦ ИЗМЕНЕНИЯ 4 ---
        
        return await message.answer(text, parse_mode='HTML')

    # 2. Шанс на большой выигрыш
    if chance < (settings.jackpot_chance + settings.big_win_chance):
        rating_change = random.randint(settings.big_win_min, settings.big_win_max)
        phrase = random.choice(BEER_WIN_PHRASES).format(rating_change=rating_change)
        await db.update_user_beer_rating(user_id, rating_change)
        return await message.answer(phrase, parse_mode='HTML')

    # 3. Шанс на обычный выигрыш
    if chance < (settings.jackpot_chance + settings.big_win_chance + settings.normal_win_chance):
        rating_change = random.randint(settings.normal_win_min, settings.normal_win_max)
        phrase = random.choice(BEER_WIN_PHRASES).format(rating_change=rating_change)
        await db.update_user_beer_rating(user_id, rating_change)
        return await message.answer(phrase, parse_mode='HTML')

    # 4. Проигрыш (с пополнением джекпота)
    rating_loss = random.randint(settings.lose_min, settings.lose_max)
    user_rating = await db.get_user_beer_rating(user_id)
    
    actual_loss = min(user_rating, rating_loss)
    
    if actual_loss > 0:
        await db.update_user_beer_rating(user_id, -actual_loss)
        await db.update_jackpot(actual_loss)
        phrase = random.choice(BEER_LOSE_PHRASES_RATING).format(rating_loss=actual_loss)
        return await message.answer(phrase, parse_mode='HTML')
    else:
        # Если у юзера 0, он не может проиграть, даем ему +1 (утешительный)
        rating_change = 1
        phrase = f"<i>Твоя кружка пуста...</i>\nБармен сжалился и плеснул на дно: <b>+1</b> 🍺."
        await db.update_user_beer_rating(user_id, rating_change)
        return await message.answer(phrase, parse_mode='HTML')


@user_router.message(Command("top"))
async def cmd_top(message: Message, db: Database):
    top_users = await db.get_top_users(10)
    
    if not top_users:
        return await message.answer("В баре пока никого нет... 🍻")

    # --- ИЗМЕНЕНИЕ 5: Текст /top (Атмосфера + Техническое исправление) ---
    text = "🏆 <b>Легенды Нашего Бара</b> 🏆\n\n(Топ-10 завсегдатаев)\n\n"
    for i, user in enumerate(top_users, 1):
        emoji = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "🍺"
        
        # Собираем имя
        user_name = user['first_name']
        if user['last_name']:
            user_name += f" {user['last_name']}"
        
        # ТЕХНИЧЕСКОЕ УЛУЧШЕНИЕ: Экранируем имя, чтобы избежать HTML-инъекций
        user_name = html.escape(user_name)
        
        text += f"{emoji} {i}. {user_name} - <b>{user['beer_rating']}</b> 🍺\n"
    # --- КОНЕЦ ИЗМЕНЕНИЯ 5 ---

    await message.answer(text, parse_mode='HTML')
