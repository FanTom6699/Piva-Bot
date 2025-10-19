# handlers.py
import asyncio
import random
from datetime import datetime, timedelta
from contextlib import suppress

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, ChatMemberUpdated, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart, Command, ChatMemberUpdatedFilter, IS_MEMBER, IS_NOT_MEMBER, CallbackData
from aiogram.exceptions import TelegramBadRequest

from database import Database
from utils import format_time_delta

# --- Инициализация ---
router = Router()
db = Database()

# --- Константы и переменные состояния ---
BEER_COOLDOWN_SECONDS = 7200
ROULETTE_COOLDOWN_SECONDS = 600
ROULETTE_LOBBY_TIMEOUT_SECONDS = 60

active_games = {}  # chat_id -> GameState
chat_cooldowns = {}  # chat_id -> datetime

# --- Структуры данных для игры ---
class RouletteCallbackData(CallbackData, prefix="roulette"):
    action: str  # join, leave, cancel

class GameState:
    def __init__(self, creator, stake, max_players, lobby_message_id):
        self.creator = creator
        self.stake = stake
        self.max_players = max_players
        self.lobby_message_id = lobby_message_id
        self.players = {creator.id: creator}
        self.creation_time = datetime.now()
        self.task = None # Для задачи авто-старта игры

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


# --- Вспомогательные функции ---
async def check_user_registered(message_or_callback: Message | CallbackQuery, bot: Bot) -> bool:
    user = message_or_callback.from_user
    if await db.user_exists(user.id):
        return True
    
    me = await bot.get_me()
    start_link = f"https://t.me/{me.username}?start=register"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✍️ Зарегистрироваться", url=start_link)]
    ])
    
    text = (
        "<b>Эй, новичок!</b> 🍻\n\n"
        "Прежде чем играть, нужно зайти в бар! "
        "Я тебя еще не знаю. Нажми на кнопку ниже, чтобы начать диалог со мной и зарегистрироваться."
    )

    if isinstance(message_or_callback, Message):
        await message_or_callback.reply(text, reply_markup=keyboard, parse_mode='HTML')
    else: # CallbackQuery
        await message_or_callback.answer("Сначала нужно зарегистрироваться!", show_alert=True)
        await message_or_callback.message.answer(text, reply_markup=keyboard, parse_mode='HTML')
        
    return False

# --- Обработчики основных команд ---

@router.message(CommandStart())
async def cmd_start(message: Message):
    user = message.from_user
    if not await db.user_exists(user.id):
        await db.add_user(user.id, user.first_name, user.last_name, user.username)
        await message.answer(
            f"Привет, {user.full_name}! 👋\n"
            f"Добро пожаловать в наш пивной клуб. Твой начальный рейтинг: 0 🍺.\n"
            f"Используй команды в любом чате, где я есть!"
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
        if time_since_last_beer.total_seconds() < BEER_COOLDOWN_SECONDS:
            remaining_time = timedelta(seconds=BEER_COOLDOWN_SECONDS) - time_since_last_beer
            await message.answer(
                f"⌛ Ты уже недавно пил! 🍻\n"
                f"Вернись в бар через: {format_time_delta(remaining_time)}."
            )
            return

    current_rating = await db.get_user_beer_rating(user_id)
    
    outcomes = ['small_win', 'loss', 'big_win']
    weights = [0.60, 0.25, 0.15]
    chosen_outcome = random.choices(outcomes, weights=weights, k=1)[0]
    
    if chosen_outcome == 'small_win':
        rating_change = random.randint(1, 4)
    elif chosen_outcome == 'big_win':
        rating_change = random.randint(5, 10)
    else:
        rating_change = random.randint(-5, -1)

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

@router.message(Command("top"))
async def cmd_top(message: Message, bot: Bot):
    if message.chat.type != 'private':
        if not await check_user_registered(message, bot):
            return

    top_users = await db.get_top_users()
    if not top_users:
        return await message.answer("В баре пока никого нет, чтобы составить топ.")

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


# --- ЛОГИКА МИНИ-ИГРЫ "ПИВНАЯ РУЛЕТКА" ---

def get_roulette_keyboard(game: GameState, user_id: int) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(text="🍺 Присоединиться", callback_data=RouletteCallbackData(action="join").pack())
    ]
    
    if user_id in game.players:
        if user_id == game.creator.id:
            buttons.append(InlineKeyboardButton(text="❌ Отменить игру", callback_data=RouletteCallbackData(action="cancel").pack()))
        else:
            buttons.append(InlineKeyboardButton(text="🚪 Выйти", callback_data=RouletteCallbackData(action="leave").pack()))
            
    return InlineKeyboardMarkup(inline_keyboard=[buttons])


async def generate_lobby_text(game: GameState) -> str:
    players_list = "\n".join(f"• {p.full_name}" for p in game.players.values())
    return (
        f"🍻 <b>Пивная рулетка началась!</b> 🍻\n\n"
        f"Создал игру: <b>{game.creator.full_name}</b>\n"
        f"Ставка для входа: <b>{game.stake} 🍺</b>\n"
        f"Игроки: ({len(game.players)}/{game.max_players})\n"
        f"{players_list}\n\n"
        f"<i>Игра начнется через {ROULETTE_LOBBY_TIMEOUT_SECONDS} секунд или как только наберется {game.max_players} игроков.</i>"
    )

@router.message(Command("roulette"))
async def cmd_roulette(message: Message, bot: Bot):
    if message.chat.type == 'private':
        return await message.answer("Эта команда работает только в групповых чатах.")

    args = message.text.split()
    if len(args) != 3 or not args[1].isdigit() or not args[2].isdigit():
        return await message.reply(
            "ℹ️ <b>Как запустить 'Пивную рулетку':</b>\n"
            "Используйте команду: <code>/roulette &lt;ставка&gt; &lt;игроки&gt;</code>\n\n"
            "• <code>&lt;ставка&gt;</code>: от 5 до 100 🍺\n"
            "• <code>&lt;игроки&gt;</code>: от 2 до 6 человек\n\n"
            "Пример: <code>/roulette 10 4</code>",
            parse_mode='HTML'
        )

    chat_id = message.chat.id
    
    if chat_id in active_games:
        return await message.reply("В этом чате уже идет игра. Дождитесь её окончания.")

    if chat_id in chat_cooldowns:
        time_since_last_game = datetime.now() - chat_cooldowns[chat_id]
        if time_since_last_game.total_seconds() < ROULETTE_COOLDOWN_SECONDS:
            remaining = timedelta(seconds=ROULETTE_COOLDOWN_SECONDS) - time_since_last_game
            return await message.reply(f"Создавать новую игру можно будет через: {format_time_delta(remaining)}.")

    stake, max_players = int(args[1]), int(args[2])

    if not (5 <= stake <= 100):
        return await message.reply("Ставка должна быть от 5 до 100 🍺.")
    if not (2 <= max_players <= 6):
        return await message.reply("Количество игроков должно быть от 2 до 6.")
    
    creator = message.from_user
    if not await check_user_registered(message, bot):
        return

    creator_balance = await db.get_user_beer_rating(creator.id)
    if creator_balance < stake:
        return await message.reply(f"У вас недостаточно пива для создания игры. Нужно {stake} 🍺, у вас {creator_balance} 🍺.")

    # Списываем ставку с создателя
    await db.change_rating(creator.id, -stake)
    
    lobby_message = await message.answer("Создание лобби...")
    
    game = GameState(creator, stake, max_players, lobby_message.message_id)
    active_games[chat_id] = game
    
    # Пытаемся закрепить сообщение
    with suppress(TelegramBadRequest):
        await bot.pin_chat_message(chat_id, lobby_message.message_id, disable_notification=True)
        
    await lobby_message.edit_text(
        await generate_lobby_text(game),
        reply_markup=get_roulette_keyboard(game, creator.id),
        parse_mode='HTML'
    )

    # Запускаем таймер на авто-старт
    game.task = asyncio.create_task(schedule_game_start(chat_id, bot))


@router.callback_query(RouletteCallbackData.filter())
async def on_roulette_button_click(callback: CallbackQuery, callback_data: RouletteCallbackData, bot: Bot):
    chat_id = callback.message.chat.id
    user = callback.from_user

    if chat_id not in active_games:
        return await callback.answer("Эта игра уже неактивна.", show_alert=True)
    
    game = active_games[chat_id]
    action = callback_data.action

    if action == "join":
        if user.id in game.players:
            return await callback.answer("Вы уже в игре!", show_alert=True)
        if len(game.players) >= game.max_players:
            return await callback.answer("Лобби заполнено.", show_alert=True)
        if not await check_user_registered(callback, bot):
             return
             
        balance = await db.get_user_beer_rating(user.id)
        if balance < game.stake:
            return await callback.answer(f"Недостаточно пива! Нужно {game.stake} 🍺, у вас {balance} 🍺.", show_alert=True)
        
        await db.change_rating(user.id, -game.stake)
        game.players[user.id] = user
        await callback.answer("Вы присоединились к игре!")
        
        if len(game.players) == game.max_players:
            game.task.cancel() # Отменяем таймер
            await start_roulette_game(chat_id, bot)
        else:
            await callback.message.edit_text(
                await generate_lobby_text(game),
                reply_markup=get_roulette_keyboard(game, user.id),
                parse_mode='HTML'
            )
    
    elif action == "leave":
        if user.id not in game.players:
            return await callback.answer("Вы не в этой игре.", show_alert=True)
        if user.id == game.creator.id:
            return await callback.answer("Создатель не может покинуть игру. Только отменить.", show_alert=True)
        
        del game.players[user.id]
        await db.change_rating(user.id, game.stake) # Возвращаем ставку
        await callback.answer("Вы покинули игру, ваша ставка возвращена.", show_alert=True)
        await callback.message.edit_text(
            await generate_lobby_text(game),
            reply_markup=get_roulette_keyboard(game, user.id),
            parse_mode='HTML'
        )

    elif action == "cancel":
        if user.id != game.creator.id:
            return await callback.answer("Только создатель может отменить игру.", show_alert=True)
        
        game.task.cancel() # Отменяем таймер
        
        # Возвращаем ставки всем
        for player_id in game.players:
            await db.change_rating(player_id, game.stake)
        
        del active_games[chat_id]
        with suppress(TelegramBadRequest):
            await bot.unpin_chat_message(chat_id, game.lobby_message_id)
        
        await callback.message.edit_text("Игра отменена создателем. Все ставки возвращены.")
        await callback.answer()


async def schedule_game_start(chat_id: int, bot: Bot):
    await asyncio.sleep(ROULETTE_LOBBY_TIMEOUT_SECONDS)
    if chat_id in active_games:
        game = active_games[chat_id]
        if len(game.players) >= 2:
            await start_roulette_game(chat_id, bot)
        else:
            # Возвращаем ставку создателю
            await db.change_rating(game.creator.id, game.stake)
            del active_games[chat_id]
            with suppress(TelegramBadRequest):
                await bot.unpin_chat_message(chat_id, game.lobby_message_id)
            await bot.edit_message_text(
                "Недостаточно игроков для начала. Игра отменена.", 
                chat_id, 
                game.lobby_message_id
            )

async def start_roulette_game(chat_id: int, bot: Bot):
    game = active_games[chat_id]
    
    with suppress(TelegramBadRequest):
        await bot.unpin_chat_message(chat_id, game.lobby_message_id)
        
    await bot.edit_message_text(
        f"Все в сборе! Ставки сделаны ({game.stake} 🍺 с каждого). Крутим барабан... 🔫",
        chat_id,
        game.lobby_message_id,
        reply_markup=None
    )
    await asyncio.sleep(3)

    players_in_game = list(game.players.values())
    round_num = 1
    
    while len(players_in_game) > 1:
        loser = random.choice(players_in_game)
        players_in_game.remove(loser)
        
        remaining_players_text = "\n".join(f"• {p.full_name}" for p in players_in_game)
        
        await bot.edit_message_text(
            f"🍻 <b>Раунд {round_num}</b> 🍻\n\n"
            f"Выбывает... <b>{loser.full_name}</b>! Он пролил всё пиво. 😖\n\n"
            f"<i>Остались в игре:</i>\n{remaining_players_text}\n\n"
            f"Следующий раунд через 5 секунд...",
            chat_id,
            game.lobby_message_id,
            parse_mode='HTML'
        )
        round_num += 1
        await asyncio.sleep(5)
        
    winner = players_in_game[0]
    prize = game.stake * len(game.players)
    
    # Возвращаем ставку победителя и добавляем выигрыш
    await db.change_rating(winner.id, prize)
    
    winner_text = (
        f"🏆 <b>ПОБЕДИТЕЛЬ!</b> 🏆\n\n"
        f"Поздравляем, <b>{winner.full_name}</b>! Он продержался до конца и забирает весь банк: <b>{prize} 🍺</b>!\n\n"
        f"<i>Игра окончена.</i>"
    )
    
    await bot.edit_message_text(winner_text, chat_id, game.lobby_message_id, parse_mode='HTML')
    
    with suppress(TelegramBadRequest):
        await bot.pin_chat_message(chat_id, game.lobby_message_id, disable_notification=True)
        # Запускаем задачу на открепление сообщения через 2 минуты
        asyncio.create_task(unpin_after_delay(chat_id, game.lobby_message_id, bot, 120))
        
    del active_games[chat_id]
    chat_cooldowns[chat_id] = datetime.now()

async def unpin_after_delay(chat_id: int, message_id: int, bot: Bot, delay: int):
    await asyncio.sleep(delay)
    with suppress(TelegramBadRequest):
        await bot.unpin_chat_message(chat_id, message_id)
