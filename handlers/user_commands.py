# handlers/user_commands.py
import random
from datetime import datetime, timedelta
from aiogram import Router, Bot, html
from aiogram.types import Message
from aiogram.filters import Command

from database import Database
from settings import SettingsManager
from .common import check_user_registered
from utils import format_time_delta

# --- ИНИЦИАЛИЗАЦИЯ ---
user_commands_router = Router()
user_spam_tracker = {}

# --- ФРАЗЫ ДЛЯ КОМАНДЫ /beer ---(без изменений)
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
    "😬 <i>Ты попытался бахнуть, но кружка пуста!</i>\nТвой рейтинг: <b>0</b> 🍺.",
    "🤷‍♂️ <i>Ты проиграл, но у тебя и так 0...</i>\nБармен смотрит на тебя с сочувствием.",
]

@user_commands_router.message(Command("beer"))
async def cmd_beer(message: Message, bot: Bot, db: Database, settings: SettingsManager):
    user_id = message.from_user.id
    
    # 0. Проверка на регистрацию
    if not await check_user_registered(message, bot, db):
        return

    # 1. Проверка на Кулдаун
    last_beer_time = await db.get_last_beer_time(user_id)
    cooldown = timedelta(seconds=settings.beer_cooldown)
    
    if last_beer_time and (datetime.now() - last_beer_time) < cooldown:
        time_left = (last_beer_time + cooldown) - datetime.now()
        await message.reply(f"Ты уже пил! 🍻\nСледующая кружка будет доступна через: <b>{format_time_delta(time_left)}</b>", parse_mode='HTML')
        return

    # 2. Проверка на спам (анти-абуз)
    if user_id in user_spam_tracker:
        await message.reply("⏳ Пожалуйста, подожди... (Защита от спама)")
        return
    user_spam_tracker[user_id] = datetime.now()

    # 3. Получаем текущий рейтинг
    current_rating = await db.get_user_beer_rating(user_id)
    
    try:
        # 4. Проверяем на Джекпот
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
                del user_spam_tracker[user_id] # Снимаем спам-блок
                return # Выходим, так как джекпот заменяет обычный /beer

        # 5. Обычный /beer
        # --- ✅ ИЗМЕНЕН ШАНС (40% Победа / 60% Поражение) ---
        if random.choice([True, True, False, False, False]): 
            rating_change = random.randint(5, 15)
            new_rating = current_rating + rating_change
            await db.update_beer_data(user_id, new_rating)
            await message.reply(random.choice(BEER_WIN_PHRASES).format(rating_change=rating_change), parse_mode='HTML')
        
        else: # 60% шанс проиграть
            rating_loss = random.randint(1, 5)
            if current_rating > 0:
                new_rating = max(0, current_rating - rating_loss)
                await db.update_beer_data(user_id, new_rating)
                # Пополняем джекпот
                await db.update_jackpot(rating_loss)
                await message.reply(random.choice(BEER_LOSE_PHRASES_RATING).format(rating_loss=rating_loss), parse_mode='HTML')
            else:
                await message.reply(random.choice(BEER_LOSE_PHRASES_ZERO), parse_mode='HTML')

    finally:
        if user_id in user_spam_tracker:
            del user_spam_tracker[user_id]


@user_commands_router.message(Command("top"))
async def cmd_top(message: Message, bot: Bot, db: Database):
    if message.chat.type != 'private' and not await check_user_registered(message, bot, db):
        return
        
    top_users = await db.get_top_users()
    if not top_users: 
        return await message.answer("В баре пока никого нет, чтобы составить топ.")
    
    max_rating_width = len(str(top_users[0][2])) # Длина рейтинга топ-1
    
    top_text = "🏆 <b>Топ-10 пивных мастеров:</b> 🏆\n\n"
    medals = ["🥇", "🥈", "🥉"]
    
    for i, (first_name, last_name, rating) in enumerate(top_users):
        name = html.quote(first_name or "")
        
        if i < 3:
            medal = medals[i]
        else:
            medal = f" {i + 1}."
            
        # Форматируем рейтинг с отступом
        rating_str = f"<code>{rating:>{max_rating_width}}</code> 🍺"
        top_text += f"{medal} {name} - {rating_str}\n"
        
    await message.answer(top_text, parse_mode='HTML')

# --- Профиль (/me) (Текстовая версия) ---
@user_commands_router.message(Command("me", "profile"))
async def cmd_me(message: Message, bot: Bot, db: Database):
    user = message.from_user
    
    # 1. Проверка на регистрацию
    if not await check_user_registered(message, bot, db):
        return

    # 2. Сбор данных из БД
    rating = await db.get_user_beer_rating(user.id)
    rank = await db.get_user_rank(user.id)
    reg_date_raw = await db.get_user_reg_date(user.id)
    (raid_count, total_damage) = await db.get_user_raid_stats(user.id)

    # 3. Форматирование данных
    
    # Определяем статус
    status = "🍺 Новичок"
    if rating >= 100: status = "🍻 Завсегдатай"
    if rating >= 500: status = "💪 Опытный"
    if rating >= 1500: status = "👹 Легенда Бара"
    if rating >= 5000: status = "👑 Пивной Король"

    # Безопасно получаем имя
    user_name = html.quote(user.first_name)

    # Безопасно форматируем дату
    reg_date_str = "Неизвестно"
    if reg_date_raw:
        try:
            reg_date_str = datetime.fromisoformat(reg_date_raw).strftime("%d.%m.%Y")
        except (ValueError, TypeError):
            reg_date_str = "Давно..." # На случай, если в БД старая дата

    # --- ТЕКСТОВЫЙ ПРОФИЛЬ ---
    
    profile_text = (
        f"🍻 <b>ТВОЙ ПРОФИЛЬ</b> 🍻\n\n"
        f"👤 <b>Имя:</b> {user_name}\n"
        f"🔰 <b>Статус:</b> {status}\n\n"
        
        f"📈 <b>СТАТИСТИКА</b>\n"
        f"🍺 <b>Рейтинг:</b> {rating}\n"
        f"🏆 <b>Место в топе:</b> {rank}-е\n\n"
        
        f"👹 <b>РЕЙДЫ</b>\n"
        f"💥 <b>Всего урона:</b> {total_damage}\n"
        f"⚔️ <b>Участвовал(а) в:</b> {raid_count} рейдах\n\n"
        
        f"📅 <i>Ты в баре с {reg_date_str}</i>"
    )

    # Отправляем с явным указанием parse_mode='HTML'
    await message.answer(profile_text, parse_mode='HTML')
