# handlers/user_commands.py
import asyncio
import random
import logging
from aiogram import Router, Bot, F, html
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest
from contextlib import suppress
from datetime import datetime, timedelta

from database import Database
from settings import SettingsManager

user_router = Router()

# --- СЛОВАРИ ДЛЯ АКТИВНЫХ ИГР ---
# (Мы выносим их сюда, чтобы lobby.py мог их импортировать)
GAME_ACTIVE_KEY = 'is_active'
active_games = {} # {chat_id: {'is_active': True, 'user_id': user_id, 'game_type': 'roulette'}}

def is_game_active(chat_id):
    """Проверяет, идет ли *любая* игра (рулетка, лесенка, мафия) в чате."""
    return chat_id in active_games and active_games[chat_id].get(GAME_ACTIVE_KEY, False)

# --- НОВАЯ Вспомогательная функция ---
def calculate_win_rate(wins, games):
    if games == 0:
        return 0.0
    return round((wins / games) * 100, 1)

# --- ОБЫЧНЫЕ КОМАНДЫ ---

@user_router.message(Command("top"))
async def cmd_top(message: Message, db: Database):
    top_users = await db.get_top_users(limit=10)
    
    if not top_users:
        await message.reply("Еще никто не пил пиво 🍻")
        return
        
    response = "<b>🏆 Топ 10 любителей пива:</b>\n\n"
    for i, user in enumerate(top_users):
        first_name, last_name, rating = user
        user_name = first_name + (f" {last_name}" if last_name else "")
        emoji = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else "🍺"
        response += f"{emoji} {html.quote(user_name)} — {rating} л.\n"
        
    await message.reply(response, parse_mode="HTML")

# --- НОВАЯ КОМАНДА: /mafiastats ---
@user_router.message(Command("mafiastats", "topmafia"))
async def cmd_mafiastats(message: Message, db: Database):
    top_players = await db.get_mafia_top(limit=10)
    
    if not top_players:
        await message.reply("Еще никто не играл в 'Пивной Переполох' 👑")
        return
        
    response = "<b>👑 Топ 10 игроков по 'Авторитету':</b>\n\n"
    for i, player in enumerate(top_players):
        # first_name, last_name, mafia_authority, mafia_games, mafia_wins
        first_name, last_name, authority, games, wins = player
        user_name = first_name + (f" {last_name}" if last_name else "")
        emoji = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else "🍻"
        
        win_rate = calculate_win_rate(wins, games)
        
        response += (f"{emoji} {html.quote(user_name)} — <b>{authority}</b> 👑 "
                    f"(<i>{wins}/{games} игр, {win_rate}% побед</i>)\n")
        
    await message.reply(response, parse_mode="HTML")


@user_router.message(Command("me"))
async def cmd_me(message: Message, db: Database, settings: SettingsManager):
    user_id = message.from_user.id
    
    # 1. Проверяем, есть ли юзер в БД
    if not await db.user_exists(user_id):
        await db.add_user(
            user_id=user_id,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
            username=message.from_user.username
        )
    
    # 2. Получаем Пивной Рейтинг
    rating = await db.get_user_beer_rating(user_id)
    last_beer_time = await db.get_last_beer_time(user_id)
    
    response = f"<b>🍺 Ваш Пивной Рейтинг:</b> {rating} л.\n"
    
    cooldown = timedelta(seconds=settings.beer_cooldown)
    if last_beer_time and (datetime.now() - last_beer_time) < cooldown:
        time_left = (last_beer_time + cooldown) - datetime.now()
        hours, remainder = divmod(time_left.seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        response += f"<i>Следующая кружка будет доступна через {hours} ч {minutes} м.</i>\n"
    else:
        response += f"<i>Вы можете выпить пива (/beer)!</i>\n"

    # --- ОБНОВЛЕНИЕ: Добавляем статистику Мафии ---
    mafia_stats = await db.get_mafia_user_stats(user_id)
    if mafia_stats:
        authority, games, wins = mafia_stats
        win_rate = calculate_win_rate(wins, games)
        
        response += "\n"
        response += f"<b>👑 Ваш 'Авторитет' в Мафии:</b> {authority}\n"
        response += f"<i>Игр сыграно: {games}</i>\n"
        response += f"<i>Побед: {wins} ({win_rate}%)</i>\n"

    await message.reply(response, parse_mode="HTML")

# --- ИГРОВЫЕ КОМАНДЫ ---

@user_router.message(Command("beer"))
async def cmd_beer(message: Message, db: Database, settings: SettingsManager):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    if is_game_active(chat_id):
        await message.reply("В чате уже идет игра, пиво отменяется!")
        return
        
    # 1. Проверяем, есть ли юзер в БД
    if not await db.user_exists(user_id):
        await db.add_user(
            user_id=user_id,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
            username=message.from_user.username
        )

    # 2. Проверка КД
    last_beer_time = await db.get_last_beer_time(user_id)
    cooldown = timedelta(seconds=settings.beer_cooldown)

    if last_beer_time and (datetime.now() - last_beer_time) < cooldown:
        time_left = (last_beer_time + cooldown) - datetime.now()
        hours, remainder = divmod(time_left.seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        await message.reply(f"Вы уже пили пиво. Следующая кружка будет доступна через {hours} ч {minutes} м.")
        return

    # 3. Шанс на Джекпот
    jackpot_chance = settings.jackpot_chance
    if random.randint(1, jackpot_chance) == 1:
        jackpot_amount = await db.get_jackpot()
        new_rating = await db.get_user_beer_rating(user_id) + jackpot_amount
        await db.update_beer_data(user_id, new_rating)
        await db.reset_jackpot()
        await message.reply(f"<b>💥 ДЖЕКПОТ! 💥</b>\nВы нашли {jackpot_amount} л. пива! 🍻\nВаш новый рейтинг: {new_rating} л.", parse_mode="HTML")
    else:
        # 4. Обычная выдача
        amount = random.randint(1, 100)
        new_rating = await db.get_user_beer_rating(user_id) + amount
        await db.update_beer_data(user_id, new_rating)
        await db.update_jackpot(amount // 10) # 10% в джекпот
        await message.reply(f"Вы выпили {amount} л. пива 🍻\nВаш новый рейтинг: {new_rating} л.")


@user_router.message(Command("roulette"))
async def cmd_roulette(message: Message, command: CommandObject, db: Database, settings: SettingsManager):
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    if is_game_active(chat_id):
        await message.reply("В этом чате уже идет другая игра. Дождитесь ее окончания.")
        return

    if not await db.user_exists(user_id):
        await message.reply("Сначала получите свой /beer рейтинг, чтобы делать ставки.")
        return

    # Парсинг ставки
    try:
        bet_arg = command.args
        if not bet_arg:
            raise ValueError("Ставка не указана.")
        
        bet = int(bet_arg)
        min_bet = settings.roulette_min_bet
        max_bet = settings.roulette_max_bet
        
        if not (min_bet <= bet <= max_bet):
            raise ValueError(f"Ставка должна быть от {min_bet} до {max_bet} л.")
            
        current_rating = await db.get_user_beer_rating(user_id)
        if bet > current_rating:
            raise ValueError(f"У вас нет столько пива! Ваш рейтинг: {current_rating} л.")

    except ValueError as e:
        await message.reply(f"Ошибка ставки: {e}\nПример: /roulette {settings.roulette_min_bet}")
        return

    # Ставка принята, начинаем игру
    active_games[chat_id] = {GAME_ACTIVE_KEY: True, "user_id": user_id, "game_type": "roulette"}
    
    await db.change_rating(user_id, -bet)
    
    msg = await message.reply(
        f"{message.from_user.first_name} ставит {bet} л. и запускает 'Пивную Рулетку'...\n"
        "Заряжаем 6-зарядный револьвер одним патроном... 🍻"
    )
    await asyncio.sleep(2)
    
    result_msg = ""
    for i in range(1, 7):
        await asyncio.sleep(1.5)
        roll = random.randint(i, 6)
        if roll == 6: # Выстрел
            await msg.edit_text(msg.text + f"\n\n<b>...БА-БАХ!</b> 💥 На {i}-м выстреле!\n"
                                          f"Вы проиграли {bet} л. пива.", parse_mode="HTML")
            break
        else:
            await msg.edit_text(msg.text + f"\n...{i}-й выстрел... щелк! (пусто)")
    else:
        # Цикл завершился без выстрела
        win_amount = bet * 2
        await db.change_rating(user_id, win_amount + bet) # (Возвращаем ставку + выигрыш)
        await msg.edit_text(msg.text + f"\n\n<b>...щелк!</b> Все 6 патронов пустые! 🥳\n"
                                      f"Вы выжили и выигрываете {win_amount} л. пива!", parse_mode="HTML")
    
    # Завершаем игру
    if chat_id in active_games:
        del active_games[chat_id]


@user_router.message(Command("ladder"))
async def cmd_ladder(message: Message, command: CommandObject, db: Database, settings: SettingsManager):
    chat_id = message.chat.id
    user_id = message.from_user.id

    if is_game_active(chat_id):
        await message.reply("В этом чате уже идет другая игра. Дождитесь ее окончания.")
        return

    if not await db.user_exists(user_id):
        await message.reply("Сначала получите свой /beer рейтинг, чтобы делать ставки.")
        return

    # Парсинг ставки
    try:
        bet_arg = command.args
        if not bet_arg:
            raise ValueError("Ставка не указана.")
        
        bet = int(bet_arg)
        min_bet = settings.ladder_min_bet
        max_bet = settings.ladder_max_bet
        
        if not (min_bet <= bet <= max_bet):
            raise ValueError(f"Ставка должна быть от {min_bet} до {max_bet} л.")
            
        current_rating = await db.get_user_beer_rating(user_id)
        if bet > current_rating:
            raise ValueError(f"У вас нет столько пива! Ваш рейтинг: {current_rating} л.")

    except ValueError as e:
        await message.reply(f"Ошибка ставки: {e}\nПример: /ladder {settings.ladder_min_bet}")
        return

    # Ставка принята
    active_games[chat_id] = {GAME_ACTIVE_KEY: True, "user_id": user_id, "game_type": "ladder"}
    
    await db.change_rating(user_id, -bet)
    
    steps = ["🟥", "🟥", "🟥", "🟥", "🟥"]
    win_step = random.randint(0, 4)
    steps[win_step] = "🟩"
    
    steps_text = " ".join(f"[{i+1}]" for i in range(5))
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=str(i+1), callback_data=f"ladder_{i}_{win_step}_{bet}_{user_id}") for i in range(5)]
    ])
    
    await message.reply(
        f"{message.from_user.first_name} ставит {bet} л. и запускает 'Пивную Лесенку'!\n"
        f"Одна из 5 ступенек — выигрыш (x4). Какую выберете?\n\n{steps_text}",
        reply_markup=keyboard
    )
    
    # (Завершение игры (del active_games) происходит в callback'е)

@user_router.callback_query(F.data.startswith("ladder_"))
async def cq_ladder_step(callback: CallbackQuery, bot: Bot, db: Database):
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    
    # 1. Парсим данные
    try:
        _, choice_str, win_step_str, bet_str, owner_id_str = callback.data.split("_")
        choice = int(choice_str)
        win_step = int(win_step_str)
        bet = int(bet_str)
        owner_id = int(owner_id_str)
    except Exception as e:
        await callback.answer("Ошибка данных. Начните игру заново.", show_alert=True)
        return

    # 2. Проверяем, что нажал владелец
    if user_id != owner_id:
        await callback.answer("Это не ваша игра!", show_alert=True)
        return
        
    # 3. Показываем результат
    steps = ["🟥", "🟥", "🟥", "🟥", "🟥"]
    steps[win_step] = "🟩"
    
    result_text = f"<b>Пивная Лесенка</b>\nСтавка: {bet} л.\n\n"
    result_text += " ".join(steps) + "\n"
    
    arrow_steps = [" "] * 5
    arrow_steps[choice] = "⬆️"
    result_text += " ".join(arrow_steps) + "\n\n"

    if choice == win_step:
        win_amount = bet * 4
        await db.change_rating(user_id, win_amount + bet) # (Возвращаем ставку + выигрыш)
        result_text += f"🥳 <b>ВЫИГРЫШ!</b>\nВы выбрали верную ступеньку и получаете {win_amount} л. пива!"
    else:
        result_text += f"😥 <b>Проигрыш!</b>\nВы выбрали неверную ступеньку и теряете {bet} л."

    await callback.message.edit_text(result_text, reply_markup=None, parse_mode="HTML")
    await callback.answer()

    # 4. Завершаем игру
    if chat_id in active_games:
        del active_games[chat_id]
