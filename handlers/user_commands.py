# handlers/user_commands.py
import asyncio
import random
from datetime import datetime
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.formatting import as_key_value, as_line, Bold
from aiogram.exceptions import TelegramBadRequest

import config
from database import Database
from settings import SettingsManager

user_router = Router()

# Словарь для отслеживания кулдаунов
user_cooldowns = {}
# Словарь для отслеживания активных игр
active_games = {} 

# --- FSM СОСТОЯНИЯ ---
class RouletteStates(StatesGroup):
    bet = State()
    color = State()

class LadderStates(StatesGroup):
    bet = State()
    playing = State()

# --- ОБЩИЕ ФУНКЦИИ ---
async def update_user_data(db: Database, message: Message):
    user_id = message.from_user.id
    if not await db.user_exists(user_id):
        await db.add_user(
            user_id=user_id,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
            username=message.from_user.username
        )

# --- ИГРОВЫЕ МЕХАНИКИ ---

# --- РУЛЕТКА ---
ROULETTE_COOLDOWN_KEY = "roulette_cd"
LADDER_COOLDOWN_KEY = "ladder_cd" # (Добавим, если понадобится)
GAME_ACTIVE_KEY = "game_active"

def is_on_cooldown(user_id: int, key: str, duration: int) -> int:
    """Проверяет кулдаун. Возвращает 0, если кулдауна нет, или time_left, если есть."""
    if user_id not in user_cooldowns:
        return 0
    
    last_time = user_cooldowns[user_id].get(key)
    if not last_time:
        return 0
        
    time_passed = (datetime.now() - last_time).total_seconds()
    if time_passed < duration:
        return int(duration - time_passed)
    return 0

def set_cooldown(user_id: int, key: str):
    """Устанавливает кулдаун."""
    if user_id not in user_cooldowns:
        user_cooldowns[user_id] = {}
    user_cooldowns[user_id][key] = datetime.now()

def set_game_active(chat_id: int, user_id: int, active: bool):
    """Отмечает, что в чате идет игра."""
    if active:
        active_games[chat_id] = {GAME_ACTIVE_KEY: True, "user_id": user_id}
    else:
        if chat_id in active_games:
            del active_games[chat_id]

def is_game_active(chat_id: int) -> bool:
    """Проверяет, идет ли в чате другая игра."""
    return active_games.get(chat_id, {}).get(GAME_ACTIVE_KEY, False)

async def get_bet(message: Message, db: Database, settings: SettingsManager) -> (int, int):
    """Проверяет и возвращает ставку пользователя."""
    try:
        bet_amount = int(message.text)
    except (ValueError, TypeError):
        await message.reply("Это не число. Введите ставку (целое число).")
        return None, None
        
    user_balance = await db.get_user_beer_rating(message.from_user.id)
    
    if bet_amount < settings.roulette_min_bet:
        await message.reply(f"Минимальная ставка: {settings.roulette_min_bet} 🍺")
        return None, user_balance
        
    if bet_amount > settings.roulette_max_bet:
        await message.reply(f"Максимальная ставка: {settings.roulette_max_bet} 🍺")
        return None, user_balance
        
    if bet_amount > user_balance:
        await message.reply(f"У вас не хватает пива! Ваш баланс: {user_balance} 🍺")
        return None, user_balance
        
    return bet_amount, user_balance


@user_router.message(Command("roulette"))
async def cmd_roulette(message: Message, state: FSMContext, db: Database, settings: SettingsManager):
    if message.chat.type == 'private':
        await message.reply("Эту игру можно запускать только в группах.")
        return
        
    if is_game_active(message.chat.id):
        await message.reply("В этом чате уже идет другая игра. Дождитесь ее окончания.")
        return

    await update_user_data(db, message)
    user_id = message.from_user.id
    
    cooldown_duration = settings.roulette_cooldown
    time_left = is_on_cooldown(user_id, ROULETTE_COOLDOWN_KEY, cooldown_duration)
    
    if time_left > 0:
        minutes, seconds = divmod(time_left, 60)
        await message.reply(f"Рулетка перезаряжается! ⏳ Попробуй снова через {minutes}м {seconds}с.")
        return
        
    balance = await db.get_user_beer_rating(user_id)
    if balance < settings.roulette_min_bet:
        await message.reply(f"У вас {balance} 🍺. Недостаточно для минимальной ставки ({settings.roulette_min_bet} 🍺).")
        return

    set_game_active(message.chat.id, user_id, True)
    await state.set_state(RouletteStates.bet)
    await message.reply(
        f"{message.from_user.first_name}, введите вашу ставку 🍺 (от {settings.roulette_min_bet} до {settings.roulette_max_bet}).\n"
        f"Ваш баланс: {balance} 🍺"
    )

@user_router.message(RouletteStates.bet)
async def process_roulette_bet(message: Message, state: FSMContext, db: Database, settings: SettingsManager):
    active_game = active_games.get(message.chat.id)
    if not active_game or active_game.get("user_id") != message.from_user.id:
        return # Это не тот юзер, который запустил игру

    bet, balance = await get_bet(message, db, settings)
    
    if bet is None:
        return # get_bet() уже отправил сообщение об ошибке

    await db.change_rating(message.from_user.id, -bet)
    await state.update_data(bet=bet, balance=balance - bet)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔴 Красное (x2)", callback_data="roulette_red")],
        [InlineKeyboardButton(text="⚫️ Черное (x2)", callback_data="roulette_black")],
        [InlineKeyboardButton(text="🍀 Зеленое (x14)", callback_data="roulette_green")]
    ])
    
    await state.set_state(RouletteStates.color)
    await message.reply(
        f"Ставка {bet} 🍺 принята!\n"
        f"Ваш баланс: {balance - bet} 🍺.\n"
        "На какой цвет ставите?",
        reply_markup=kb
    )

@user_router.callback_query(RouletteStates.color, F.data.startswith("roulette_"))
async def process_roulette_color(callback: CallbackQuery, state: FSMContext, db: Database, settings: SettingsManager):
    active_game = active_games.get(callback.message.chat.id)
    if not active_game or active_game.get("user_id") != callback.from_user.id:
        await callback.answer("Это не ваша игра!", show_alert=True)
        return

    choice = callback.data.split("_")[1]
    
    # 0 - green, 1-7 - red, 8-14 - black
    roll = random.randint(0, 14)
    
    if roll == 0:
        result = "green"
        result_text = "🍀 ЗЕЛЕНОЕ (x14)"
    elif 1 <= roll <= 7:
        result = "red"
        result_text = "🔴 КРАСНОЕ (x2)"
    else:
        result = "black"
        result_text = "⚫️ ЧЕРНОЕ (x2)"

    data = await state.get_data()
    bet = data.get("bet")
    balance = data.get("balance")
    
    text = f"🎲 {callback.from_user.first_name}, выпадает: {result_text}!\n\n"
    
    win = 0
    if choice == result:
        if result == "green":
            win = bet * 14
        else:
            win = bet * 2
            
        text += f"🎉 ПОБЕДА! 🎉\nВы выиграли {win} 🍺!\n"
        await db.change_rating(callback.from_user.id, win)
        text += f"Ваш новый баланс: {balance + win} 🍺."
    else:
        text += f"😥 Увы, вы проиграли {bet} 🍺.\n"
        text += f"Ваш баланс: {balance} 🍺."
        
    await state.clear()
    set_game_active(callback.message.chat.id, callback.from_user.id, False)
    set_cooldown(callback.from_user.id, ROULETTE_COOLDOWN_KEY)
    
    await callback.message.edit_text(text, reply_markup=None)
    await callback.answer()


# --- ЛЕСЕНКА ---
class LadderCallbackData(CallbackData, prefix="ladder"):
    action: str
    step: int = 0

LADDER_MULTIPLIERS = [1.25, 1.5, 2.0, 3.0, 5.0, 8.0, 12.0, 20.0, 50.0, 100.0]

def get_ladder_keyboard(step: int) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text="?", callback_data=LadderCallbackData(action="play", step=step).pack()),
            InlineKeyboardButton(text="?", callback_data=LadderCallbackData(action="play", step=step).pack())
        ],
        [InlineKeyboardButton(text=f"💸 Забрать выигрыш ({LADDER_MULTIPLIERS[step-1]:.2f}x)", callback_data=LadderCallbackData(action="cashout", step=step).pack())]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_ladder_text(bet: int, step: int, current_win: float) -> str:
    text = f"🪜 <b>Пивная Лесенка</b> 🪜\n\n"
    text += f"<b>Ставка:</b> {bet} 🍺\n"
    text += f"<b>Текущий выигрыш:</b> {current_win:.2f} 🍺\n"
    text += f"<b>Следующий шаг (x{LADDER_MULTIPLIERS[step]:.2f}):</b> {bet * LADDER_MULTIPLIERS[step]:.2f} 🍺\n\n"
    
    for i in range(len(LADDER_MULTIPLIERS) - 1, -1, -1):
        if i == step:
            text += f"<b>➡️ {i+1}. x{LADDER_MULTIPLIERS[i]:.2f} </b>\n"
        else:
            text += f"   {i+1}. x{LADDER_MULTIPLIERS[i]:.2f}\n"
    
    text += "\nВыберите одну из двух кнопок. Удачи!"
    return text

@user_router.message(Command("ladder"))
async def cmd_ladder(message: Message, state: FSMContext, db: Database, settings: SettingsManager):
    if message.chat.type == 'private':
        await message.reply("Эту игру можно запускать только в группах.")
        return
        
    if is_game_active(message.chat.id):
        await message.reply("В этом чате уже идет другая игра. Дождитесь ее окончания.")
        return

    await update_user_data(db, message)
    user_id = message.from_user.id
    
    # (Здесь можно добавить кулдаун по аналогии с рулеткой, если нужно)
    
    balance = await db.get_user_beer_rating(user_id)
    if balance < settings.ladder_min_bet:
        await message.reply(f"У вас {balance} 🍺. Недостаточно для минимальной ставки ({settings.ladder_min_bet} 🍺).")
        return

    set_game_active(message.chat.id, user_id, True)
    await state.set_state(LadderStates.bet)
    await message.reply(
        f"{message.from_user.first_name}, введите вашу ставку 🍺 (от {settings.ladder_min_bet} до {settings.ladder_max_bet}).\n"
        f"Ваш баланс: {balance} 🍺"
    )

@user_router.message(LadderStates.bet)
async def process_ladder_bet(message: Message, state: FSMContext, db: Database, settings: SettingsManager):
    active_game = active_games.get(message.chat.id)
    if not active_game or active_game.get("user_id") != message.from_user.id:
        return 
        
    try:
        bet_amount = int(message.text)
    except (ValueError, TypeError):
        await message.reply("Это не число. Введите ставку (целое число).")
        return
        
    user_balance = await db.get_user_beer_rating(message.from_user.id)
    
    if bet_amount < settings.ladder_min_bet:
        await message.reply(f"Минимальная ставка: {settings.ladder_min_bet} 🍺")
        return
    if bet_amount > settings.ladder_max_bet:
        await message.reply(f"Максимальная ставка: {settings.ladder_max_bet} 🍺")
        return
    if bet_amount > user_balance:
        await message.reply(f"У вас не хватает пива! Ваш баланс: {user_balance} 🍺")
        return

    await db.change_rating(message.from_user.id, -bet_amount)
    
    # 0 - lose, 1 - win
    winning_button = random.randint(0, 1)
    
    await state.set_state(LadderStates.playing)
    await state.update_data(bet=bet_amount, step=0, win=winning_button)
    
    await message.answer(
        get_ladder_text(bet_amount, 0, 0.0),
        reply_markup=get_ladder_keyboard(0)
    )

@user_router.callback_query(LadderStates.playing, LadderCallbackData.filter(F.action == "play"))
async def process_ladder_play(callback: CallbackQuery, callback_data: LadderCallbackData, state: FSMContext, db: Database):
    active_game = active_games.get(callback.message.chat.id)
    if not active_game or active_game.get("user_id") != callback.from_user.id:
        await callback.answer("Это не ваша игра!", show_alert=True)
        return

    data = await state.get_data()
    bet = data.get("bet")
    step = data.get("step")
    winning_button_index = data.get("win") # 0 or 1
    
    # Определяем, на какую кнопку нажал юзер (0 или 1)
    buttons_in_row = callback.message.reply_markup.inline_keyboard[0]
    pressed_button_text = ""
    for i, button in enumerate(buttons_in_row):
        if button.callback_data == callback.data:
            user_choice_index = i
            pressed_button_text = button.text
            break
            
    if pressed_button_text != "?":
        await callback.answer("Вы уже сделали этот ход!", show_alert=True)
        return
        
    if user_choice_index == winning_button_index:
        # --- ПОБЕДА ---
        new_step = step + 1
        current_win = bet * LADDER_MULTIPLIERS[step]
        
        # Обновляем кнопки, показывая результат
        new_keyboard_markup = callback.message.reply_markup.inline_keyboard
        new_keyboard_markup[0][winning_button_index] = InlineKeyboardButton(text="✅", callback_data="ladder_done")
        
        other_index = 1 - winning_button_index
        new_keyboard_markup[0][other_index] = InlineKeyboardButton(text="❌", callback_data="ladder_done")
        
        # Редактируем сообщение, убирая кнопки "забрать"
        await callback.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=[new_keyboard_markup[0]]))
        
        if new_step == len(LADDER_MULTIPLIERS):
            # --- ПОЛНАЯ ПОБЕДА (Последний шаг) ---
            await db.change_rating(callback.from_user.id, current_win)
            await state.clear()
            set_game_active(callback.message.chat.id, callback.from_user.id, False)
            await callback.message.answer(
                f"🎉🎉🎉 <b>ДЖЕКПОТ ЛЕСЕНКИ!</b> 🎉🎉🎉\n"
                f"{callback.from_user.first_name} прошел всю лесенку!\n"
                f"<b>Выигрыш: {current_win:.2f} 🍺!</b>"
            )
        else:
            # --- СЛЕДУЮЩИЙ ШАГ ---
            new_winning_button = random.randint(0, 1)
            await state.update_data(step=new_step, win=new_winning_button)
            await asyncio.sleep(1) # Пауза, чтобы игрок увидел результат
            await callback.message.answer(
                get_ladder_text(bet, new_step, current_win),
                reply_markup=get_ladder_keyboard(new_step)
            )
            
    else:
        # --- ПРОИГРЫШ ---
        await state.clear()
        set_game_active(callback.message.chat.id, callback.from_user.id, False)
        
        # Обновляем кнопки, показывая проигрыш
        new_keyboard_markup = callback.message.reply_markup.inline_keyboard
        new_keyboard_markup[0][winning_button_index] = InlineKeyboardButton(text="✅", callback_data="ladder_done")
        
        other_index = 1 - winning_button_index
        new_keyboard_markup[0][other_index] = InlineKeyboardButton(text="❌", callback_data="ladder_done")
        
        await callback.message.edit_text(
            f"😥 <b>Проигрыш!</b> 😥\n"
            f"{callback.from_user.first_name}, вы проиграли {bet} 🍺.\n"
            f"Вы дошли до {step+1} ступени.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[new_keyboard_markup[0]])
        )
        
    await callback.answer()

@user_router.callback_query(LadderStates.playing, LadderCallbackData.filter(F.action == "cashout"))
async def process_ladder_cashout(callback: CallbackQuery, callback_data: LadderCallbackData, state: FSMContext, db: Database):
    active_game = active_games.get(callback.message.chat.id)
    if not active_game or active_game.get("user_id") != callback.from_user.id:
        await callback.answer("Это не ваша игра!", show_alert=True)
        return
        
    data = await state.get_data()
    bet = data.get("bet")
    step = data.get("step")
    
    # step тут - это номер текущей ступени (начиная с 0), а выигрыш - за прошлую (step-1)
    win_multiplier_index = step - 1 
    
    if win_multiplier_index < 0:
        await callback.answer("Вы не можете забрать выигрыш на первом шаге!", show_alert=True)
        return
        
    win_amount = bet * LADDER_MULTIPLIERS[win_multiplier_index]
    
    await db.change_rating(callback.from_user.id, win_amount)
    await state.clear()
    set_game_active(callback.message.chat.id, callback.from_user.id, False)
    
    await callback.message.edit_text(
        f"💸 <b>Выигрыш забран!</b> 💸\n"
        f"{callback.from_user.first_name}, вы забираете {win_amount:.2f} 🍺!\n"
        f"Вы остановились на {step} ступени.",
        reply_markup=None
    )
    await callback.answer()


# --- КОМАНДЫ ПОЛЬЗОВАТЕЛЯ ---
@user_router.message(Command("start"))
async def cmd_start(message: Message, db: Database):
    await update_user_data(db, message)
    await message.answer(
        "Добро пожаловать в Пивной Бот! 🍻\n\n"
        "Здесь ты можешь:\n"
        "🍺 Получить пиво (команда /beer)\n"
        "🏆 Соревноваться в топе (/top)\n"
        "🎲 Играть в Рулетку (/roulette)\n"
        "🪜 Играть в Лесенку (/ladder)\n\n"
        "Ивенты:\n"
        "👹 Сражаться с Рейд-Боссом (когда он активен)\n"
        "🎲 Играть в Мафию (/mafia)\n\n"
        "Админ: @FanDomiy"
    )

@user_router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "<b>Основные команды:</b>\n"
        "/start - Перезапустить бота\n"
        "/help - Это сообщение\n"
        "/beer - Получить свою порцию пива (1 раз в N часов)\n"
        "/top - Показать топ-10 пивных магнатов\n"
        "/profile - Показать твой профиль\n"
        "\n<b>Игры:</b>\n"
        "/roulette - Пивная рулетка (ставки от 5 до 100 🍺)\n"
        "/ladder - Пивная лесенка (риск-игра)\n"
        "/mafia - Начать набор в 'Пивной Переполох'\n"
        "/mafia_top - Рейтинг игроков в Мафию\n"
        "\n<b>Ивенты:</b>\n"
        "Когда в чате появляется Рейд-Босс, жми кнопки, чтобы атаковать!"
    )

@user_router.message(Command("profile"))
async def cmd_profile(message: Message, db: Database):
    await update_user_data(db, message)
    user_id = message.from_user.id
    
    beer = await db.get_user_beer_rating(user_id)
    mafia_stats = await db.get_mafia_user_stats(user_id)
    
    if not mafia_stats:
        mafia_authority = 1000
        mafia_games = 0
        mafia_wins = 0
    else:
        mafia_authority, mafia_games, mafia_wins = mafia_stats

    win_rate = (mafia_wins / mafia_games * 100) if mafia_games > 0 else 0

    user_data = as_line(
        Bold("👤 Профиль:"), f" {message.from_user.full_name}\n\n",
        "🍺 Пивной баланс: ", f"{beer}\n",
        "🎩 Авторитет (Мафия): ", f"{mafia_authority}\n",
        "🎲 Игры в Мафию: ", f"{mafia_games}\n",
        "🏆 Победы в Мафии: ", f"{mafia_wins} ({win_rate:.1f}%)"
    )
    await message.answer(user_data.as_html())


@user_router.message(Command("beer"))
async def cmd_beer(message: Message, db: Database, settings: SettingsManager):
    await update_user_data(db, message)
    user_id = message.from_user.id
    cooldown_seconds = settings.beer_cooldown
    
    # Проверка кулдауна
    last_time = await db.get_last_beer_time(user_id)
    if last_time:
        time_passed = (datetime.now() - last_time).total_seconds()
        if time_passed < cooldown_seconds:
            time_left = int(cooldown_seconds - time_passed)
            hours, rem = divmod(time_left, 3600)
            minutes, seconds = divmod(rem, 60)
            await message.reply(f"Ты уже получил свое пиво! ⏳ Попробуй снова через {hours}ч {minutes}м {seconds}с.")
            return

    # Начисление
    current_rating = await db.get_user_beer_rating(user_id)
    beer_amount = 10
    
    # Шанс на джекпот
    jackpot_chance = settings.jackpot_chance
    if random.randint(1, jackpot_chance) == 1:
        jackpot = await db.get_jackpot()
        beer_amount += jackpot
        await db.reset_jackpot()
        await message.answer(f"🎉🍻 <b>ДЖЕКПОТ!</b> 🍻🎉\n{message.from_user.first_name} срывает куш в <b>{jackpot} 🍺</b>!")
    else:
        # Увеличиваем джекпот, если не выиграли
        await db.update_jackpot(1)


    await db.update_beer_data(user_id, current_rating + beer_amount)
    if message.chat.type != 'private':
        await message.reply(f"🍻 {message.from_user.first_name} получает {beer_amount} 🍺! Теперь у тебя {current_rating + beer_amount} 🍺.")
    else:
        await message.reply(f"🍻 Ты получил {beer_amount} 🍺! Теперь у тебя {current_rating + beer_amount} 🍺.")

@user_router.message(Command("top"))
async def cmd_top(message: Message, db: Database):
    await update_user_data(db, message)
    top_users = await db.get_top_users(10)
    
    if not top_users:
        await message.answer("В баре пока пусто, ты будешь первым!")
        return

    response = "🏆 <b>Топ-10 Пивных Магнатов:</b> 🏆\n\n"
    place_emojis = ["🥇", "🥈", "🥉"]
    
    for i, (first_name, last_name, rating) in enumerate(top_users):
        name = first_name
        if last_name:
            name += f" {last_name}"
            
        place = place_emojis[i] if i < 3 else f" {i+1}. "
        response += f"{place} <b>{name}</b> — {rating} 🍺\n"

    await message.answer(response)

# --- НОВАЯ КОМАНДА ДЛЯ МАФИИ ---
@user_router.message(Command("mafia_top"))
async def cmd_mafia_top(message: Message, db: Database):
    await update_user_data(db, message)
    top_players = await db.get_mafia_top(10)
    
    response = "🏆 <b>ЗАЛ СЛАВЫ 'ПИВНОГО ПЕРЕПОЛОХА'</b> 🏆\n\n"
    response += "<i>Рейтинг самых авторитетных игроков:</i>\n\n"
    
    if not top_players:
        await message.answer(f"{response}Пока никто не играл в Мафию. Стань первым!")
        return

    place_emojis = ["🥇", "🥈", "🥉"]
    
    for i, (first_name, last_name, authority, games, wins) in enumerate(top_players):
        name = first_name
        if last_name:
            name += f" {last_name}"
        
        win_rate = (wins / games * 100) if games > 0 else 0
        place = place_emojis[i] if i < 3 else f" {i+1}. "
        
        response += f"{place} <b>{name}</b> — <b>{authority} 🎩 Авторитета</b>\n"
        response += f"    <i>(Игр: {games}, Побед: {wins}, Винрейт: {win_rate:.1f}%)</i>\n"

    # Добавляем статистику текущего пользователя
    user_stats = await db.get_mafia_user_stats(message.from_user.id)
    if user_stats and user_stats[1] > 0: # user_stats[1] - это mafia_games
        authority, games, wins = user_stats
        win_rate = (wins / games * 100) if games > 0 else 0
        response += f"\n---\n<b>Твой ранг:</b>\n"
        response += f"<b>{message.from_user.first_name}</b> — <b>{authority} 🎩 Авторитета</b>\n"
        response += f"<i>(Игр: {games}, Побед: {wins}, Винрейт: {win_rate:.1f}%)</i>"
    else:
        response += "\n---\n<i>Ты еще не играл в Мафию. Напиши /mafia в группе, чтобы начать!</i>"

    await message.answer(response)

@user_router.message(Command("cancel"), F.state != None)
async def cmd_cancel_game(message: Message, state: FSMContext):
    """Отменяет активную игру (Рулетка, Лесенка)."""
    current_state = await state.get_state()
    if current_state is None:
        return

    data = await state.get_data()
    bet = data.get("bet")
    
    if bet:
        # Возвращаем ставку, если она была сделана
        await db.change_rating(message.from_user.id, bet)
        await message.reply(f"Игра отменена. Ваша ставка {bet} 🍺 возвращена.")
    else:
        await message.reply("Игра отменена.")
        
    set_game_active(message.chat.id, message.from_user.id, False)
    await state.clear()
