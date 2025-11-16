# handlers/user_commands.py
import random
from datetime import datetime, timedelta
from aiogram import Router, Bot, html # ✅ (Импортируем html)
from aiogram.types import Message
from aiogram.filters import Command

from database import Database
from settings import SettingsManager
from .common import check_user_registered
from utils import format_time_delta

# --- ИНИЦИАЛИЗАЦИЯ --
user_commands_router = Router()
user_spam_tracker = {}

# --- ФРАЗЫ ДЛЯ КОМАНДЫ /beer ---(Твои фразы)
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
    "😕🍻 <i>Ты хотел выпить, но у тебя и так 0 🍺...</i>\nБармен сжалился и не стал отбирать кружку. <i>Повезло!</i>",
    "😬🍻 <i>Ты попытался выпить в долг, но бармен...</i>\n...тебя проигнорировал. Твой рейтинг: <b>0</b> 🍺.",
]
# --- ---

# --- ✅✅✅ ИСПРАВЛЕННАЯ КОМАНДА /beer ✅✅✅ ---
@user_commands_router.message(Command("beer"))
async def cmd_beer(message: Message, bot: Bot, db: Database, settings: SettingsManager):
    user_id = message.from_user.id
    
    # (Проверка регистрации в группе)
    if message.chat.type != 'private' and not await check_user_registered(message, bot, db):
        return

    # (Проверка кулдауна)
    cooldown_seconds = settings.beer_cooldown
    last_beer_time = await db.get_last_beer_time(user_id)
    
    if last_beer_time:
        time_passed = datetime.now() - last_beer_time
        if time_passed.total_seconds() < cooldown_seconds:
            time_left = timedelta(seconds=cooldown_seconds) - time_passed
            await message.reply(f"🍻 <b>Ты уже пил!</b>\nПриходи за добавкой через: <b>{format_time_delta(time_left)}</b>.", parse_mode='HTML')
            return

    # (Проверка спама - Anti-Spam)
    now = datetime.now()
    if user_id in user_spam_tracker:
        if (now - user_spam_tracker[user_id]).total_seconds() < 2.0:
            return # (Просто игнорируем)
    user_spam_tracker[user_id] = now
    
    jackpot_chance = settings.jackpot_chance
    win_roll = random.randint(1, 100)
    
    rating_change = 0
    reply_text = ""
    
    if win_roll > 35: # (65% шанс выиграть: 100 - 65 = 35)
        rating_change = random.randint(1, 15) # ✅ Победа: +1 до +15
        reply_text = random.choice(BEER_WIN_PHRASES).format(rating_change=rating_change)
    else:
        # (Проверяем текущий баланс ПЕРЕД списанием)
        current_rating = await db.get_user_beer_rating(user_id)
        if current_rating > 0:
            rating_loss = random.randint(1, 10) # ✅ Проигрыш: -1 до -10
            # (Не даем уйти в минус)
            rating_change = -min(current_rating, rating_loss) 
            reply_text = random.choice(BEER_LOSE_PHRASES_RATING).format(rating_loss=abs(rating_change))
        else:
            rating_change = 0 # (Не меняем рейтинг)
            reply_text = random.choice(BEER_LOSE_PHRASES_ZERO)

    # --- ✅✅✅ ИСПРАВЛЕНИЕ: ✅✅✅ ---
    # 1. Сначала меняем рейтинг (если он изменился)
    if rating_change != 0:
        await db.change_rating(user_id, rating_change)
        
    # 2. В любом случае (даже при 0) обновляем таймер
    await db.update_last_beer_time(user_id)
    # --- ---
    
    # (Отправляем результат)
    await message.reply(reply_text, parse_mode='HTML')

    # (Проверка джекпота - этот код не менялся)
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
# --- ---


@user_commands_router.message(Command("top"))
async def cmd_top(message: Message, bot: Bot, db: Database):
    # (Проверка регистрации в группе)
    if message.chat.type != 'private' and not await check_user_registered(message, bot, db):
        return
        
    top_users = await db.get_top_users()
    if not top_users: 
        return await message.answer("В баре пока никого нет, чтобы составить топ.")
    
    # (Ищем макс. длину рейтинга для форматирования)
    max_rating_width = 0
    if top_users:
        max_rating_width = len(str(top_users[0][2]))
    
    top_text = "🏆 <b>Топ-10 пивных мастеров:</b> 🏆\n\n"
    medals = ["🥇", "🥈", "🥉"]
    
    for i, (first_name, last_name, rating) in enumerate(top_users):
        name = html.quote(first_name)
        if last_name:
            name += f" {html.quote(last_name)}"
            
        medal = medals[i] if i < len(medals) else f"<b>{i+1}.</b>"
        
        # (Форматирование рейтинга)
        rating_str = f"<code>{rating:<{max_rating_width}}</code>"
        
        top_text += f"{medal} {rating_str} 🍺 - {name}\n"
        
    await message.answer(top_text, parse_mode='HTML')


# --- (ТВОЯ НОВАЯ КОМАНДА /start, КОТОРАЯ БЫЛА В user_commands.py) ---
@user_commands_router.message(Command("start"))
async def cmd_start(message: Message, bot: Bot, db: Database):
    user = message.from_user
    
    # (Регистрируем или обновляем инфо)
    await db.add_user(user.id, user.first_name, user.last_name, user.username)
    
    user_profile = await db.get_user_profile(user.id)
    (first_name, last_name, username, rating, reg_date_raw) = user_profile
    
    # --- (Твои статусы) ---
    status = "🧐 Новичок"
    if rating >= 100: status = "🍻 Выпивоха"
    if rating >= 300: status = "🎩 Завсегдатай"
    if rating >= 750: status = "😎 Свой в доску"
    if rating >= 1500: status = "💪 Синяк"
    if rating >= 3000: status = " V.I.P."
    if rating >= 5000: status = "🍾 Сомелье"
    if rating >= 7500: status = "🎗 Ветеран Бара"
    if rating >= 10000: status = "🌟 Легенда Бара"
    if rating >= 15000: status = "🎖 Элита"
    if rating >= 20000: status = "🏆 Чемпион"
    if rating >= 30000: status = "💎 Алмазный Алконафт"
    if rating >= 40000: status = "🌀 Повелитель Пены"
    if rating >= 50000: status = "🌌 Бог Пива"
    if rating >= 65000: status = "🔱 Атлант"
    if rating >= 80000: status = "🦄 Мифический"
    if rating >= 100000: status = "🧙‍♂️ Пивной Магистр"
    if rating >= 150000: status = "🦖 Пивозавр"
    if rating >= 225000: status = "🤖 Барный Киборг"
    if rating >= 300000: status = "🚀 Трижды Несокрушимый"
    if rating >= 400000: status = "⚡️ Гроза Кранов"
    if rating >= 500000: status = "🌪️ Лорд Хмельных Бурь"
    if rating >= 650000: status = "👑 Император Пива"
    if rating >= 800000: status = "🪐 Хозяин Галактики Пива"
    if rating >= 1000000: status = "✨ Пивной Абсолют"
    # --- --- ---

    # Безопасно получаем имя
    user_name = html.quote(user.first_name)

    # Безопасно форматируем дату
    reg_date_str = "Неизвестно"
    if reg_date_raw:
        try:
            reg_date_str = datetime.fromisoformat(reg_date_raw).strftime("%d.%m.%Y")
        except (ValueError, TypeError):
            reg_date_str = "Давно..." # На случай, если в БД старая дата

    # --- ТЕКСТОВЫЙ ПРОФИЛЬ (Без символов рамки) ---
    
    profile_text = (
        f"🍻 <b>ТВОЙ ПРОФИЛЬ</b> 🍻\n\n"
        f"👤 <b>Имя:</b> {user_name}\n"
        f"🏆 <b>Статус:</b> {status}\n"
        f"🍺 <b>Рейтинг:</b> {rating}\n\n"
        f"🗓 <b>В баре c:</b> {reg_date_str}\n"
        f"🆔 <b>ID:</b> <code>{user.id}</code>\n\n"
        f"<i>Напиши <code>/help</code>, чтобы узнать все команды.</i>"
    )
    
    await message.answer(profile_text, parse_mode='HTML')
