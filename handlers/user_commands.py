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
        # --- "ЗОЛОТАЯ СЕРЕДИНА" (40% Победа / 60% Поражение) ---
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
    
    max_rating_width = 0
    if top_users:
        max_rating_width = len(str(top_users[0][2])) # Длина рейтинга топ-1
    
    top_text = "🏆 <b>Топ-10 пивных мастеров:</b> 🏆\n\n"
    medals = ["🥇", "🥈", "🥉"]
    
    for i, (first_name, last_name, rating) in enumerate(top_users):
        name = html.quote(first_name or "")
        
        if i < 3:
            medal = medals[i]
        else:
            medal = f" {i + 1}."
            
        rating_str = f"<code>{rating:>{max_rating_width}}</code> 🍺"
        top_text += f"{medal} {name} - {rating_str}\n"
        
    await message.answer(top_text, parse_mode='HTML')

# --- КОМАНДА ПРОФИЛЯ (/me) ---
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
    
    # --- ТВОЙ НОВЫЙ СПИСОК СТАТУСОВ (20 шт.) ---
    status = "👣 Прохожий"
    if rating >= 100:   status = "🍻 Промочил Горло"
    if rating >= 500:   status = "🧐 Завсегдатай"
    if rating >= 1500:  status = "🧠 Пивной Эрудит"
    if rating >= 4000:  status = "🍷 Главный Сомелье"
    if rating >= 7500:  status = "⚔️ Барный Страж"
    if rating >= 12000: status = "🏅 Мастер Кружки"
    if rating >= 20000: status = "🥇 Чемпион Зала"
    if rating >= 30000: status = "👑 Хранитель Кранов"
    if rating >= 50000: status = "💰 Пивной Барон"
    if rating >= 75000: status = "⭐ Звезда Паба"
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


# --- КОД ДЛЯ !НАПОИТЬ ---
@user_commands_router.message(Command(commands=["напоить", "Напоить"], prefix="!"))
async def cmd_give_beer(message: Message, bot: Bot, db: Database):
    
    # 1. Проверяем отправителя
    if not await check_user_registered(message, bot, db):
        return
        
    sender = message.from_user
    sender_id = sender.id
    sender_name = html.quote(sender.full_name)
    
    args = message.text.split()
    reply = message.reply_to_message
    
    target_id = None
    target_name = None
    amount = None
    
    hint_text = (
        "<b>Ошибка!</b> 😥 Неправильный формат.\n\n"
        "<b>Как использовать:</b>\n"
        "<code>!напоить &lt;@username&gt; &lt;кол-во&gt;</code>\n"
        "<code>!напоить &lt;ID&gt; &lt;кол-во&gt;</code>\n"
        "<code>!напоить &lt;кол-во&gt;</code> (в ответ на сообщение)"
    )

    try:
        # 2. Ищем цель и количество
        # Случай 1: В ответ на сообщение (!напоить 100)
        if reply:
            if len(args) != 2 or not args[1].isdigit():
                await message.reply(hint_text, parse_mode="HTML")
                return
            
            target_user = reply.from_user
            target_id = target_user.id
            target_name = html.quote(target_user.full_name)
            amount = int(args[1])

        # Случай 2: Через @username или ID (!напоить @user 100)
        elif len(args) == 3 and args[2].isdigit():
            amount = int(args[2])
            target_input = args[1]
            
            if target_input.startswith('@'):
                username = target_input.lstrip('@')
                user_data = await db.get_user_by_username(username)
                if user_data:
                    target_id = user_data[0] # user_id
                    target_name = html.quote(user_data[1]) # first_name
                else:
                    await message.reply(f"Не могу найти пользователя {target_input} в базе данных бота.")
                    return

            elif target_input.isdigit():
                target_id = int(target_input)
                user_data = await db.get_user_by_id(target_id)
                if user_data:
                    target_name = html.quote(user_data[0] + (f" {user_data[1]}" if user_data[1] else ""))
                else:
                    await message.reply(f"Не могу найти пользователя с ID {target_id} в базе данных бота.")
                    return
            
            else:
                await message.reply(hint_text, parse_mode="HTML")
                return
        
        # Случай 3: Неверный формат
        else:
            await message.reply(hint_text, parse_mode="HTML")
            return

        # 3. Проверки
        if amount <= 0:
            await message.reply("Количество пива должно быть больше нуля!")
            return
            
        if target_id == sender_id:
            await message.reply("Нельзя напоить самого себя! 😅")
            return

        if not await db.user_exists(target_id):
            await message.reply(f"<b>{target_name}</b> еще не зарегистрирован(а) в боте. Он(а) должен(на) сначала написать <code>/start</code> боту в ЛС.")
            return
            
        # 4. Проверка баланса отправителя
        sender_balance = await db.get_user_beer_rating(sender_id)
        if sender_balance < amount:
            await message.reply(f"У тебя не хватает пива! 🍻\nНужно: {amount} 🍺\nУ тебя: {sender_balance} 🍺.")
            return
            
        # 5. Транзакция
        await db.change_rating(sender_id, -amount)
        await db.change_rating(target_id, amount)
        
        # --- ✅✅✅ ИЗМЕНЕНИЕ ЗДЕСЬ ✅✅✅ ---
        # 6. Успех (Новый текст по твоему запросу)
        success_text = (
            f"🍺 <b>Бармен подаёт!</b>\n"
            f"<b>{sender_name}</b> угощает <b>{target_name}</b>\n"
            f"<b>{amount}</b> пива."
        )
        await message.reply(success_text, parse_mode="HTML")
        # --- --- ---

    except Exception as e:
        await message.reply(f"Что-то пошло не так... Ошибка: {e}")
