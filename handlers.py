# handlers.py
import asyncio
import random
from datetime import datetime, timedelta
from contextlib import suppress

from aiogram import Router, F, Bot
# --- ИЗМЕНЕНИЕ ЗДЕСЬ: Убедимся, что ChatMemberUpdated импортирован ---
from aiogram.types import Message, CallbackQuery, ChatMemberUpdated, InlineKeyboardMarkup, InlineKeyboardButton
# --- ИЗМЕНЕНИЕ ЗДЕСЬ: Убираем лишние фильтры ---
from aiogram.filters import CommandStart, Command, Filter
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest

import config
from database import Database
from utils import format_time_delta

# --- ИНИЦИАЛИЗАЦИЯ ---
router = Router()
admin_router = Router()
db = Database(db_name='/data/bot_database.db')


# --- FSM СОСТОЯНИЯ ---
class AdminBroadcast(StatesGroup):
    waiting_for_message = State()


# --- ФИЛЬТРЫ ---
class IsAdmin(Filter):
    async def __call__(self, message: Message | CallbackQuery) -> bool:
        return message.from_user.id == config.ADMIN_ID


# --- CALLBACKDATA ФАБРИКИ ---
class AdminCallbackData(CallbackData, prefix="admin"):
    action: str

class RouletteCallbackData(CallbackData, prefix="roulette"):
    action: str


# --- КЛАССЫ И ПЕРЕМЕННЫЕ СОСТОЯНИЯ ---
class GameState:
    def __init__(self, creator, stake, max_players, lobby_message_id):
        self.creator = creator
        self.stake = stake
        self.max_players = max_players
        self.lobby_message_id = lobby_message_id
        self.players = {creator.id: creator}
        self.creation_time = datetime.now()
        self.task = None

BEER_COOLDOWN_SECONDS = 7200
ROULETTE_COOLDOWN_SECONDS = 600
ROULETTE_LOBBY_TIMEOUT_SECONDS = 60

active_games = {}
chat_cooldowns = {}


# --- ФРАЗЫ ДЛЯ КОМАНДЫ /beer ---
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


# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
async def check_user_registered(message_or_callback: Message | CallbackQuery, bot: Bot) -> bool:
    user = message_or_callback.from_user
    if await db.user_exists(user.id):
        return True
    
    me = await bot.get_me()
    start_link = f"https://t.me/{me.username}?start=register"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✍️ Зарегистрироваться", url=start_link)]])
    
    text = (
        "<b>Эй, новичок!</b> 🍻\n\n"
        "Прежде чем играть, нужно зайти в бар! "
        "Я тебя еще не знаю. Нажми на кнопку ниже, чтобы начать диалог со мной и зарегистрироваться."
    )

    if isinstance(message_or_callback, Message):
        await message_or_callback.reply(text, reply_markup=keyboard, parse_mode='HTML')
    else:
        await message_or_callback.answer("Сначала нужно зарегистрироваться!", show_alert=True)
        await message_or_callback.message.answer(text, reply_markup=keyboard, parse_mode='HTML')
        
    return False


# --- ОБРАБОТЧИКИ СОБЫТИЙ ЧАТА (ВАШ ИСПРАВЛЕННЫЙ КОД) ---
@router.my_chat_member()
async def handle_bot_membership(event: ChatMemberUpdated):
    """
    Отслеживает, когда бот добавлен или удалён из чата.
    """
    old_status = event.old_chat_member.status
    new_status = event.new_chat_member.status

    # Бота добавили в чат
    if old_status in ("left", "kicked") and new_status in ("member", "administrator"):
        await db.add_chat(event.chat.id, event.chat.title)

    # Бота удалили из чата
    elif old_status in ("member", "administrator") and new_status in ("left", "kicked"):
        await db.remove_chat(event.chat.id)


# --- АДМИН-ПАНЕЛЬ (admin_router) ---
@admin_router.message(Command("admin"), IsAdmin())
async def cmd_admin_panel(message: Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Сделать рассылку", callback_data=AdminCallbackData(action="broadcast").pack())],
        [InlineKeyboardButton(text="📊 Статистика", callback_data=AdminCallbackData(action="stats").pack())]
    ])
    await message.answer("Добро пожаловать в админ-панель!", reply_markup=keyboard)

@admin_router.callback_query(AdminCallbackData.filter(F.action == "stats"), IsAdmin())
async def cq_admin_stats(callback: CallbackQuery):
    total_users = await db.get_total_users_count()
    all_chats = await db.get_all_chat_ids()
    await callback.message.edit_text(
        f"<b>📊 Статистика бота</b>\n\n"
        f"Всего пользователей: {total_users}\n"
        f"Всего чатов: {len(all_chats)}",
        parse_mode='HTML'
    )
    await callback.answer()

@admin_router.callback_query(AdminCallbackData.filter(F.action == "broadcast"), IsAdmin())
async def cq_admin_broadcast_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminBroadcast.waiting_for_message)
    await callback.message.edit_text("Пожалуйста, отправьте сообщение для рассылки. Вы можете использовать форматирование, фото, видео и т.д.")
    await callback.answer()

@admin_router.message(AdminBroadcast.waiting_for_message, IsAdmin())
async def handle_broadcast_message(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    await message.answer("Начинаю рассылку...")

    user_ids = await db.get_all_user_ids()
    chat_ids = await db.get_all_chat_ids()
    
    success_users, failed_users = 0, 0
    for user_id in user_ids:
        with suppress(TelegramBadRequest):
            try:
                await bot.copy_message(chat_id=user_id, from_chat_id=message.chat.id, message_id=message.message_id)
                success_users += 1
            except Exception:
                failed_users += 1
            await asyncio.sleep(0.1)

    success_chats, failed_chats = 0, 0
    for chat_id in chat_ids:
        with suppress(TelegramBadRequest):
            try:
                await bot.copy_message(chat_id=chat_id, from_chat_id=message.chat.id, message_id=message.message_id)
                success_chats += 1
            except Exception:
                failed_chats += 1
            await asyncio.sleep(0.1)

    await message.answer(
        f"<b>📢 Рассылка завершена!</b>\n\n"
        f"<b>Пользователи:</b>\n✅ Успешно: {success_users}\n❌ Неудачно: {failed_users}\n\n"
        f"<b>Чаты:</b>\n✅ Успешно: {success_chats}\n❌ Неудачно: {failed_chats}",
        parse_mode='HTML'
    )

# --- КОМАНДЫ ПОЛЬЗОВАТЕЛЕЙ (router) ---
@router.message(CommandStart())
async def cmd_start(message: Message):
    user = message.from_user
    if not await db.user_exists(user.id):
        await db.add_user(user.id, user.first_name, user.last_name, user.username)
        await message.answer(f"Привет, {user.full_name}! 👋\nТвой начальный рейтинг: 0 🍺.")
    else:
        rating = await db.get_user_beer_rating(user.id)
        await message.answer(f"С возвращением, {user.full_name}! 🍻\nТвой текущий рейтинг: {rating} 🍺.")

# ... (Остальной код для /beer, /top, /roulette остается без изменений) ...
# ... (Просто скопируйте его из моего предыдущего ответа) ...
@router.message(Command("beer"))
async def cmd_beer(message: Message, bot: Bot):
    if message.chat.type != 'private' and not await check_user_registered(message, bot):
        return

    user_id = message.from_user.id
    last_beer_time = await db.get_last_beer_time(user_id)
    
    if last_beer_time:
        time_since = datetime.now() - last_beer_time
        if time_since.total_seconds() < BEER_COOLDOWN_SECONDS:
            remaining = timedelta(seconds=BEER_COOLDOWN_SECONDS) - time_since
            return await message.answer(f"⌛ Ты уже недавно пил! 🍻\nВернись в бар через: {format_time_delta(remaining)}.")

    current_rating = await db.get_user_beer_rating(user_id)
    
    outcomes = ['small_win', 'loss', 'big_win']
    weights = [0.60, 0.25, 0.15]
    chosen_outcome = random.choices(outcomes, weights=weights, k=1)[0]
    
    if chosen_outcome == 'small_win': rating_change = random.randint(1, 4)
    elif chosen_outcome == 'big_win': rating_change = random.randint(5, 10)
    else: rating_change = random.randint(-5, -1)

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
    if message.chat.type != 'private' and not await check_user_registered(message, bot):
        return

    top_users = await db.get_top_users()
    if not top_users: return await message.answer("В баре пока никого нет, чтобы составить топ.")

    top_text = "🏆 <b>Топ-10 пивных мастеров:</b> 🏆\n\n"
    medals = ["🥇", "🥈", "🥉"]
    
    for i, (first_name, last_name, rating) in enumerate(top_users):
        full_name = first_name + (f" {last_name}" if last_name else "")
        place = i + 1
        medal = medals[i] if i < 3 else "🏅"
        top_text += f"{medal} {place}. {full_name} — {rating} 🍺\n"
            
    await message.answer(top_text, parse_mode='HTML')


# --- ЛОГИКА МИНИ-ИГРЫ "ПИВНАЯ РУЛЕТКА" (router) ---
def get_roulette_keyboard(game: GameState, user_id: int) -> InlineKeyboardMarkup:
    buttons = [InlineKeyboardButton(text="🍺 Присоединиться", callback_data=RouletteCallbackData(action="join").pack())]
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
        f"Игроки: ({len(game.players)}/{game.max_players})\n{players_list}\n\n"
        f"<i>Игра начнется через {ROULETTE_LOBBY_TIMEOUT_SECONDS} секунд или когда наберется {game.max_players} игроков.</i>"
    )

@router.message(Command("roulette"))
async def cmd_roulette(message: Message, bot: Bot):
    if message.chat.type == 'private': return await message.answer("Эта команда работает только в групповых чатах.")

    args = message.text.split()
    if len(args) != 3 or not args[1].isdigit() or not args[2].isdigit():
        return await message.reply(
            "ℹ️ <b>Как запустить 'Пивную рулетку':</b>\n"
            "Используйте команду: <code>/roulette &lt;ставка&gt; &lt;игроки&gt;</code>\n\n"
            "• <code>&lt;ставка&gt;</code>: от 5 до 100 🍺\n"
            "• <code>&lt;игроки&gt;</code>: от 2 до 6 человек\n\n"
            "Пример: <code>/roulette 10 4</code>", parse_mode='HTML'
        )
    
    chat_id = message.chat.id
    if chat_id in active_games: return await message.reply("В этом чате уже идет игра.")
    if chat_id in chat_cooldowns:
        time_since = datetime.now() - chat_cooldowns[chat_id]
        if time_since.total_seconds() < ROULETTE_COOLDOWN_SECONDS:
            remaining = timedelta(seconds=ROULETTE_COOLDOWN_SECONDS) - time_since
            return await message.reply(f"Создавать новую игру можно будет через: {format_time_delta(remaining)}.")

    stake, max_players = int(args[1]), int(args[2])
    if not (5 <= stake <= 100): return await message.reply("Ставка должна быть от 5 до 100 🍺.")
    if not (2 <= max_players <= 6): return await message.reply("Количество игроков должно быть от 2 до 6.")
    
    creator = message.from_user
    if not await check_user_registered(message, bot): return

    creator_balance = await db.get_user_beer_rating(creator.id)
    if creator_balance < stake: return await message.reply(f"У вас недостаточно пива. Нужно {stake} 🍺, у вас {creator_balance} 🍺.")

    await db.change_rating(creator.id, -stake)
    lobby_message = await message.answer("Создание лобби...")
    game = GameState(creator, stake, max_players, lobby_message.message_id)
    active_games[chat_id] = game
    
    with suppress(TelegramBadRequest): await bot.pin_chat_message(chat_id, lobby_message.message_id, disable_notification=True)
    await lobby_message.edit_text(await generate_lobby_text(game), reply_markup=get_roulette_keyboard(game, creator.id), parse_mode='HTML')
    game.task = asyncio.create_task(schedule_game_start(chat_id, bot))

@router.callback_query(RouletteCallbackData.filter())
async def on_roulette_button_click(callback: CallbackQuery, callback_data: RouletteCallbackData, bot: Bot):
    chat_id = callback.message.chat.id
    user = callback.from_user
    if chat_id not in active_games: return await callback.answer("Эта игра уже неактивна.", show_alert=True)
    
    game = active_games[chat_id]
    action = callback_data.action

    if action == "join":
        if user.id in game.players: return await callback.answer("Вы уже в игре!", show_alert=True)
        if len(game.players) >= game.max_players: return await callback.answer("Лобби заполнено.", show_alert=True)
        if not await check_user_registered(callback, bot): return
             
        balance = await db.get_user_beer_rating(user.id)
        if balance < game.stake: return await callback.answer(f"Недостаточно пива! Нужно {game.stake} 🍺, у вас {balance} 🍺.", show_alert=True)
        
        await db.change_rating(user.id, -game.stake)
        game.players[user.id] = user
        await callback.answer("Вы присоединились к игре!")
        
        if len(game.players) == game.max_players:
            if game.task: game.task.cancel()
            await start_roulette_game(chat_id, bot)
        else:
            await callback.message.edit_text(await generate_lobby_text(game), reply_markup=get_roulette_keyboard(game, user.id), parse_mode='HTML')
    
    elif action == "leave":
        if user.id not in game.players: return await callback.answer("Вы не в этой игре.", show_alert=True)
        if user.id == game.creator.id: return await callback.answer("Создатель не может покинуть игру. Только отменить.", show_alert=True)
        
        del game.players[user.id]
        await db.change_rating(user.id, game.stake)
        await callback.answer("Вы покинули игру, ваша ставка возвращена.", show_alert=True)
        await callback.message.edit_text(await generate_lobby_text(game), reply_markup=get_roulette_keyboard(game, user.id), parse_mode='HTML')

    elif action == "cancel":
        if user.id != game.creator.id: return await callback.answer("Только создатель может отменить игру.", show_alert=True)
        if game.task: game.task.cancel()
        
        for player_id in game.players: await db.change_rating(player_id, game.stake)
        del active_games[chat_id]
        with suppress(TelegramBadRequest): await bot.unpin_chat_message(chat_id, game.lobby_message_id)
        
        await callback.message.edit_text("Игра отменена создателем. Все ставки возвращены.")
        await callback.answer()

async def schedule_game_start(chat_id: int, bot: Bot):
    await asyncio.sleep(ROULETTE_LOBBY_TIMEOUT_SECONDS)
    if chat_id in active_games:
        game = active_games[chat_id]
        if len(game.players) >= 2:
            await start_roulette_game(chat_id, bot)
        else:
            await db.change_rating(game.creator.id, game.stake)
            del active_games[chat_id]
            with suppress(TelegramBadRequest): await bot.unpin_chat_message(chat_id, game.lobby_message_id)
            await bot.edit_message_text("Недостаточно игроков для начала. Игра отменена.", chat_id, game.lobby_message_id)

async def start_roulette_game(chat_id: int, bot: Bot):
    if chat_id not in active_games: return
    game = active_games[chat_id]
    
    with suppress(TelegramBadRequest): await bot.unpin_chat_message(chat_id, game.lobby_message_id)
    await bot.edit_message_text(f"Все в сборе! Ставки ({game.stake} 🍺 с каждого). Крутим барабан... 🔫", chat_id, game.lobby_message_id, reply_markup=None)
    await asyncio.sleep(3)

    players_in_game = list(game.players.values())
    round_num = 1
    while len(players_in_game) > 1:
        loser = random.choice(players_in_game)
        players_in_game.remove(loser)
        remaining_players_text = "\n".join(f"• {p.full_name}" for p in players_in_game)
        
        await bot.edit_message_text(
            f"🍻 <b>Раунд {round_num}</b> 🍻\n\n"
            f"Выбывает... <b>{loser.full_name}</b>! 😖\n\n"
            f"<i>Остались в игре:</i>\n{remaining_players_text}\n\n"
            f"Следующий раунд через 5 секунд...",
            chat_id, game.lobby_message_id, parse_mode='HTML'
        )
        round_num += 1
        await asyncio.sleep(5)
        
    winner = players_in_game[0]
    prize = game.stake * len(game.players)
    await db.change_rating(winner.id, prize)
    
    winner_text = (
        f"🏆 <b>ПОБЕДИТЕЛЬ!</b> 🏆\n\n"
        f"Поздравляем, <b>{winner.full_name}</b>! Он забирает весь банк: <b>{prize} 🍺</b>!\n\n"
        f"<i>Игра окончена.</i>"
    )
    await bot.edit_message_text(winner_text, chat_id, game.lobby_message_id, parse_mode='HTML')
    
    with suppress(TelegramBadRequest):
        await bot.pin_chat_message(chat_id, game.lobby_message_id, disable_notification=True)
        asyncio.create_task(unpin_after_delay(chat_id, game.lobby_message_id, bot, 120))
        
    del active_games[chat_id]
    chat_cooldowns[chat_id] = datetime.now()

async def unpin_after_delay(chat_id: int, message_id: int, bot: Bot, delay: int):
    await asyncio.sleep(delay)
    with suppress(TelegramBadRequest):
        await bot.unpin_chat_message(chat_id, message_id)
