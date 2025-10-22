# handlers.py
import asyncio
import random
from datetime import datetime, timedelta
from contextlib import suppress
import logging
from typing import List

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, ChatMemberUpdated, InlineKeyboardMarkup, InlineKeyboardButton, User, Chat
from aiogram.enums.chat_action import ChatAction
from aiogram.filters import CommandStart, Command, Filter, StateFilter
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
class AdminStates(StatesGroup):
    broadcast_message = State()
    give_beer_user = State()
    give_beer_amount = State()


# --- ФИЛЬТРЫ ---
class IsAdmin(Filter):
    async def __call__(self, message: Message | CallbackQuery) -> bool:
        return message.from_user.id == config.ADMIN_ID


# --- CALLBACKDATA ФАБРИКИ ---
class AdminCallbackData(CallbackData, prefix="admin"):
    action: str

class RouletteCallbackData(CallbackData, prefix="roulette"):
    action: str

# --- ИЗМЕНЕНИЕ ЗДЕСЬ: Добавляем stake в CallbackData ---
class LadderCallbackData(CallbackData, prefix="ladder"):
    action: str
    level: int = 0
    choice: int = 0
    stake: int = 0 # Будет использоваться только для кнопки "Играть снова"


# --- КЛАССЫ И ПЕРЕМЕННЫЕ СОСТОЯНИЯ ---
class GameState:  # Для рулетки
    def __init__(self, creator, stake, max_players, lobby_message_id):
        self.creator = creator
        self.stake = stake
        self.max_players = max_players
        self.lobby_message_id = lobby_message_id
        self.players = {creator.id: creator}
        self.task = None

class LadderGameState:  # Для лесенки
    def __init__(self, player_id, chat_id, message_id, stake, correct_path):
        self.player_id = player_id
        self.chat_id = chat_id
        self.message_id = message_id
        self.stake = stake
        self.correct_path: List[int] = correct_path
        self.player_choices = {}
        self.current_level = 1
        self.current_win = 0.0
        self.is_finished = False
        self.last_choice = -1
        self.task = None # Для таймера бездействия


BEER_COOLDOWN_SECONDS = 7200
ROULETTE_COOLDOWN_SECONDS = 600
ROULETTE_LOBBY_TIMEOUT_SECONDS = 60
LADDER_LEVELS = 10
LADDER_INACTIVITY_TIMEOUT_SECONDS = 60

active_games = {}
active_ladder_games = {}
chat_cooldowns = {}
user_spam_tracker = {}


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

# --- КОЭФФИЦИЕНТЫ И НАГРАДЫ ДЛЯ ЛЕСЕНКИ ---
LADDER_MULTIPLIERS = [1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 2.0, 2.2, 2.5]
def calculate_ladder_rewards(stake: int) -> List[float]:
    rewards = []
    current_win = float(stake)
    for i in range(LADDER_LEVELS):
        current_win *= LADDER_MULTIPLIERS[i]
        rewards.append(round(current_win, 2))
    return rewards


# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
async def check_user_registered(message_or_callback: Message | CallbackQuery, bot: Bot) -> bool:
    user = message_or_callback.from_user
    if await db.user_exists(user.id):
        return True
    me = await bot.get_me()
    start_link = f"https.me/{me.username}?start=register"
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
        await bot.send_message(message_or_callback.message.chat.id, text, reply_markup=keyboard, parse_mode='HTML')
    return False


# --- ОБРАБОТЧИКИ СОБЫТИЙ ЧАТА ---
@router.my_chat_member()
async def handle_bot_membership(event: ChatMemberUpdated, bot: Bot):
    old_status = event.old_chat_member.status
    new_status = event.new_chat_member.status
    if old_status in ("left", "kicked") and new_status in ("member", "administrator"):
        await db.add_chat(event.chat.id, event.chat.title)
    elif old_status in ("member", "administrator") and new_status in ("left", "kicked"):
        await db.remove_chat(event.chat.id)


# --- АДМИН-ПАНЕЛЬ (admin_router) ---
@admin_router.message(Command("cancel"), IsAdmin(), StateFilter("*"))
async def cancel_handler(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        return
    await state.clear()
    await message.answer("Действие отменено.")

@admin_router.message(Command("admin"), IsAdmin())
async def cmd_admin_panel(message: Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🍺 Выдать пиво", callback_data=AdminCallbackData(action="give_beer").pack())],
        [InlineKeyboardButton(text="📢 Сделать рассылку", callback_data=AdminCallbackData(action="broadcast").pack())],
        [InlineKeyboardButton(text="📊 Статистика", callback_data=AdminCallbackData(action="stats").pack())]
    ])
    await message.answer("Добро пожаловать в админ-панель!", reply_markup=keyboard)

@admin_router.callback_query(AdminCallbackData.filter(), IsAdmin())
async def handle_admin_callback(callback: CallbackQuery, callback_data: AdminCallbackData, state: FSMContext):
    action = callback_data.action
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    if action == "stats":
        total_users = await db.get_total_users_count()
        all_chats = await db.get_all_chat_ids()
        await callback.message.answer(
            f"<b>📊 Статистика бота</b>\n\n"
            f"Всего пользователей: {total_users}\n"
            f"Всего чатов: {len(all_chats)}",
            parse_mode='HTML'
        )
    elif action == "broadcast":
        await state.set_state(AdminStates.broadcast_message)
        await callback.message.answer("Пожалуйста, отправьте сообщение для рассылки. Для отмены введите /cancel")
    elif action == "give_beer":
        await state.set_state(AdminStates.give_beer_user)
        await callback.message.answer("Кому выдать пиво? Отправьте ID, @username или перешлите сообщение. Для отмены введите /cancel")

@admin_router.message(AdminStates.broadcast_message, IsAdmin())
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
            await asyncio.sleep(0.05)
    success_chats, failed_chats = 0, 0
    for chat_id in chat_ids:
        with suppress(TelegramBadRequest):
            try:
                await bot.copy_message(chat_id=chat_id, from_chat_id=message.chat.id, message_id=message.message_id)
                success_chats += 1
            except Exception:
                failed_chats += 1
            await asyncio.sleep(0.05)
    await message.answer(
        f"<b>📢 Рассылка завершена!</b>\n\n"
        f"<b>Пользователи:</b>\n✅ Успешно: {success_users}\n❌ Неудачно: {failed_users}\n\n"
        f"<b>Чаты:</b>\n✅ Успешно: {success_chats}\n❌ Неудачно: {failed_chats}",
        parse_mode='HTML'
    )

@admin_router.message(AdminStates.give_beer_user, IsAdmin())
async def process_give_beer_user(message: Message, state: FSMContext):
    target_id = None
    if message.forward_from:
        target_id = message.forward_from.id
    elif message.text and message.text.startswith('@'):
        target_id = await db.get_user_by_username(message.text)
    elif message.text and message.text.isdigit():
        target_id = int(message.text)
    if not target_id or not await db.user_exists(target_id):
        await message.reply("Пользователь не найден. Попробуйте снова или /cancel.")
        return
    await state.update_data(target_id=target_id)
    await state.set_state(AdminStates.give_beer_amount)
    await message.answer("Отлично. Теперь введите сумму (например, `100` или `-50`).")

@admin_router.message(AdminStates.give_beer_amount, IsAdmin())
async def process_give_beer_amount(message: Message, state: FSMContext, bot: Bot):
    if not message.text or not message.text.lstrip('-').isdigit():
        await message.reply("Это не число. Введите сумму или /cancel.")
        return
    amount = int(message.text)
    user_data = await state.get_data()
    target_id = user_data.get('target_id')
    await state.clear()
    await db.change_rating(target_id, amount)
    new_balance = await db.get_user_beer_rating(target_id)
    await message.answer(
        f"Баланс изменен!\nID: <code>{target_id}</code>\nИзменение: {amount:+} 🍺\nНовый баланс: {new_balance} 🍺",
        parse_mode='HTML'
    )
    with suppress(TelegramBadRequest):
        await bot.send_message(chat_id=target_id, text=f"⚙️ Администратор изменил ваш баланс на {amount:+} 🍺.")

@admin_router.message(F.text.lower() == "бот выйди", IsAdmin())
async def admin_leave_chat(message: Message, bot: Bot):
    if message.chat.type in ['group', 'supergroup']:
        await message.reply("Хорошо, слушаюсь...")
        await bot.leave_chat(chat_id=message.chat.id)
    else:
        await message.reply("Эту команду можно использовать только в группах.")


# --- КОМАНДЫ ПОЛЬЗОВАТЕЛЕЙ (router) ---
@router.message(CommandStart())
async def cmd_start(message: Message):
    user = message.from_user
    if not await db.user_exists(user.id):
        await db.add_user(user.id, user.first_name, user.last_name, user.username)
        welcome_text = (
            f"Привет, {user.full_name}! 👋\n"
            f"Добро пожаловать в наш пивной клуб! Твой начальный рейтинг: 0 🍺.\n\n"
            f"Вот список доступных команд:\n"
            f"• `/beer` - Испытать удачу (раз в 2 часа).\n"
            f"• `/top` - Показать таблицу лидеров.\n"
            f"• `/roulette <ставка> <игроки>` - Запустить 'Пивную рулетку'.\n"
            f"• `/ladder <ставка>` - Начать игру в 'Пивную лесенку'.\n"
            f"• `/help` - Показать эту справку."
        )
        await message.answer(welcome_text)
    else:
        rating = await db.get_user_beer_rating(user.id)
        await message.answer(f"С возвращением, {user.full_name}! 🍻\nТвой текущий рейтинг: {rating} 🍺.")

@router.message(Command("help"))
async def cmd_help(message: Message):
    help_text = (
        "<b>🍻 Справка по командам бота 🍻</b>\n\n"
        "Здесь собраны все доступные команды и их описание.\n\n"
        "--- --- ---\n"
        "<b>Основные команды</b>\n"
        "• <code>/start</code> - Зарегистрироваться или проверить свой профиль.\n"
        "• <code>/beer</code> - Испытать удачу (раз в 2 часа).\n"
        "• <code>/top</code> - Показать таблицу лидеров.\n\n"
        "--- --- ---\n"
        "<b>Мини-игры</b>\n"
        "• <code>/roulette &lt;ставка&gt; &lt;игроки&gt;</code> - Запустить 'Пивную рулетку' в группе.\n"
        "• <code>/ladder &lt;ставка&gt;</code> - Начать игру в 'Пивную лесенку'.\n\n"
        "--- --- ---\n"
        "<b>Прочее</b>\n"
        "• <code>/id</code> - Узнать свой User ID и ID текущего чата."
    )
    await message.answer(help_text, parse_mode='HTML')

@router.message(Command("id"))
async def cmd_id(message: Message):
    await message.reply(
        f"ℹ️ **Информация:**\n\n"
        f"👤 Ваш User ID: <code>{message.from_user.id}</code>\n"
        f"💬 ID этого чата: <code>{message.chat.id}</code>",
        parse_mode='HTML'
    )

@router.message(Command("beer"))
async def cmd_beer(message: Message, bot: Bot):
    user_id = message.from_user.id
    now = datetime.now()
    if user_id in user_spam_tracker:
        if (now - user_spam_tracker[user_id]).total_seconds() < 5:
            return
    user_spam_tracker[user_id] = now
    if message.chat.type != 'private' and not await check_user_registered(message, bot):
        return
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


# --- ЛОГИКА МИНИ-ИГРЫ "ПИВНАЯ ЛЕСЕНКА" ---

async def schedule_ladder_timeout(chat_id: int, player_id: int, message_id: int, stake: int, bot: Bot):
    try:
        await asyncio.sleep(LADDER_INACTIVITY_TIMEOUT_SECONDS)
        if chat_id in active_ladder_games:
            game = active_ladder_games[chat_id]
            if game.player_id == player_id and game.current_level == 1 and not game.is_finished:
                await db.change_rating(player_id, stake)
                await bot.edit_message_text(
                    text="Игра в 'Лесенку' отменена из-за бездействия. Ваша ставка возвращена.",
                    chat_id=chat_id,
                    message_id=message_id,
                    reply_markup=None
                )
                del active_ladder_games[chat_id]
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logging.error(f"Ошибка в таймере бездействия Лесенки для чата {chat_id}: {e}")
        if chat_id in active_ladder_games:
            del active_ladder_games[chat_id]

async def generate_ladder_keyboard(game: LadderGameState, rewards: List[float], reveal: bool = False) -> InlineKeyboardMarkup:
    keyboard = []
    for i in range(LADDER_LEVELS, 0, -1):
        level_idx = i - 1
        row = []
        for j in range(2):
            btn_text = ""
            is_active = (i == game.current_level) and not game.is_finished
            if reveal:
                is_correct_path = (j == game.correct_path[level_idx])
                if i < game.current_level:
                    if j == game.player_choices.get(level_idx):
                        btn_text = f"✅ {rewards[level_idx]} 🍺"
                    else:
                        btn_text = " "
                elif i == game.current_level:
                    btn_text = f"🍺 {rewards[level_idx]}" if is_correct_path else "❌"
                else:
                    btn_text = f"🍺 {rewards[level_idx]}" if is_correct_path else "💨"
            else:
                if i < game.current_level:
                    if j == game.player_choices.get(level_idx):
                        btn_text = f"✅ {rewards[level_idx]} 🍺"
                    else:
                        btn_text = " "
                else:
                    btn_text = f"{rewards[level_idx]} 🍺"
            row.append(InlineKeyboardButton(text=btn_text, callback_data=LadderCallbackData(action="play", level=i, choice=j).pack() if is_active else "do_nothing"))
        keyboard.append(row)
    if not game.is_finished:
        cash_out_text = f"💰 Забрать выигрыш ({game.current_win} 🍺)" if game.current_win > 0 else "💰 Забрать ставку"
        keyboard.append([InlineKeyboardButton(text=cash_out_text, callback_data=LadderCallbackData(action="cash_out").pack())])
    else:
        keyboard.append([InlineKeyboardButton(text=f"🔁 Играть снова ({game.stake} 🍺)", callback_data=LadderCallbackData(action="play_again", stake=game.stake).pack())])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

async def generate_ladder_text(game: LadderGameState) -> str:
    return (f"🪜 <b>Пивная Лесенка</b> 🪜\n\n" f"Ставка: <b>{game.stake} 🍺</b> | Текущий выигрыш: <b>{game.current_win} 🍺</b>")

async def end_ladder_game(callback: CallbackQuery, game: LadderGameState, is_win: bool):
    game.is_finished = True
    if game.task:
        game.task.cancel()
        game.task = None
    if is_win:
        win_amount = game.current_win if game.current_win > 0 else game.stake
        await db.change_rating(game.player_id, int(win_amount))
        text = f"🎉 <b>Выигрыш!</b> 🎉\n\nВы решили остановиться и забрать <b>{win_amount} 🍺</b>. Поздравляем!"
        rewards = calculate_ladder_rewards(game.stake)
        keyboard = await generate_ladder_keyboard(game, rewards, reveal=True) # Показываем путь даже при выигрыше
    else:
        text = f"💥 <b>Вы проиграли на Уровне {game.current_level}!</b> 💥\n\nВаша ставка в {game.stake} 🍺 сгорела.\nВот как выглядела выигрышная комбинация:"
        rewards = calculate_ladder_rewards(game.stake)
        keyboard = await generate_ladder_keyboard(game, rewards, reveal=True)
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode='HTML')
    if game.chat_id in active_ladder_games:
        del active_ladder_games[game.chat_id]

async def start_ladder_game(chat: Chat, user: User, bot: Bot, stake: int):
    await bot.send_chat_action(chat_id=chat.id, action=ChatAction.TYPING)
    await asyncio.sleep(0.3)
    await db.change_rating(user.id, -stake)
    correct_path = [random.randint(0, 1) for _ in range(LADDER_LEVELS)]
    if user.id == config.ADMIN_ID:
        path_str = " -> ".join(["Л" if c == 0 else "П" for c in correct_path])
        with suppress(TelegramBadRequest):
            await bot.send_message(user.id, text=f"🤫 Комбинация: <code>{path_str}</code>", parse_mode='HTML')
    rewards = calculate_ladder_rewards(stake)
    game = LadderGameState(user.id, chat.id, 0, stake, correct_path)
    text = await generate_ladder_text(game)
    keyboard = await generate_ladder_keyboard(game, rewards)
    game_message = await bot.send_message(chat_id=chat.id, text=text, reply_markup=keyboard, parse_mode='HTML')
    game.message_id = game_message.message_id
    active_ladder_games[chat.id] = game
    game.task = asyncio.create_task(schedule_ladder_timeout(chat.id, user.id, game.message_id, stake, bot))

@router.message(Command("ladder"))
async def cmd_ladder(message: Message, bot: Bot):
    chat_id = message.chat.id
    if chat_id in active_ladder_games:
        return await message.reply("Пожалуйста, подождите, пока текущая игра в 'Лесенку' в этом чате не закончится.")
    args = message.text.split()
    if len(args) != 2 or not args[1].isdigit():
        return await message.reply("Неверный формат. Используйте: `/ladder <ставка>` (например, `/ladder 10`).")
    stake = int(args[1])
    if not (5 <= stake <= 100):
        return await message.reply("Ставка должна быть от 5 до 100 🍺.")
    if not await check_user_registered(message, bot):
        return
    balance = await db.get_user_beer_rating(message.from_user.id)
    if balance < stake:
        return await message.reply(f"У вас недостаточно пива для этой ставки. Нужно {stake} 🍺, у вас {balance} 🍺.")
    await start_ladder_game(message.chat, message.from_user, bot, stake)

# --- ИЗМЕНЕНИЕ ЗДЕСЬ: Разделили обработчики ---

# Обработчик для кнопок "Играть" и "Забрать"
@router.callback_query(LadderCallbackData.filter(F.action.in_({"play", "cash_out"})))
async def on_ladder_game_callback(callback: CallbackQuery, callback_data: LadderCallbackData, bot: Bot):
    chat_id = callback.message.chat.id
    user = callback.from_user
    
    if chat_id not in active_ladder_games:
        return await callback.answer("Эта игра больше не активна.", show_alert=True)
        
    game = active_ladder_games[chat_id]
    
    if user.id != game.player_id:
        return await callback.answer("Это не ваша игра!", show_alert=True)
        
    if game.is_finished:
        return await callback.answer() # Игнорируем нажатия на завершенной игре

    action = callback_data.action

    if action == "cash_out":
        if game.current_win == 0 and game.current_level == 1:
            return await callback.answer("Сделайте хотя бы один ход!", show_alert=True)
        await callback.answer()
        await end_ladder_game(callback, game, is_win=True)
        return

    if action == "play":
        level, choice = callback_data.level, callback_data.choice
        if level != game.current_level:
            return await callback.answer("Сейчас не ваш ход.", show_alert=True)
            
        if game.current_level == 1 and game.task:
            game.task.cancel()
            game.task = None
            
        await callback.answer()
        game.player_choices[level - 1] = choice
        rewards = calculate_ladder_rewards(game.stake)
        
        if choice == game.correct_path[level - 1]:
            game.current_level += 1
            game.current_win = rewards[level - 1]
            if game.current_level > LADDER_LEVELS:
                await end_ladder_game(callback, game, is_win=True)
            else:
                try:
                    keyboard = await generate_ladder_keyboard(game, rewards)
                    text = await generate_ladder_text(game)
                    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode='HTML')
                except TelegramBadRequest as e:
                     if "message is not modified" not in str(e):
                         logging.error(f"Ошибка при обновлении Лесенки: {e}")
        else:
            game.last_choice = choice
            await end_ladder_game(callback, game, is_win=False)

# Отдельный обработчик для "Играть снова"
@router.callback_query(LadderCallbackData.filter(F.action == "play_again"))
async def on_ladder_play_again(callback: CallbackQuery, callback_data: LadderCallbackData, bot: Bot):
    await callback.answer()
    stake = callback_data.stake
    
    # Проверяем баланс
    balance = await db.get_user_beer_rating(callback.from_user.id)
    if balance < stake:
         return await callback.message.answer(f"Недостаточно пива для новой игры! Нужно {stake} 🍺, у вас {balance} 🍺.")
    
    # Проверяем, не идет ли уже другая игра
    if callback.message.chat.id in active_ladder_games:
        return await callback.message.answer("Пожалуйста, подождите, пока текущая игра в 'Лесенку' в этом чате не закончится.")

    await callback.message.delete()
    await start_ladder_game(callback.message.chat, callback.from_user, bot, stake)


# --- ЛОГИКА МИНИ-ИГРЫ "ПИВНАЯ РУЛЕТКА" ---
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
    with suppress(TelegramBadRequest): await bot.pin_chat_message(chat_id=chat_id, message_id=lobby_message.message_id, disable_notification=True)
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
        with suppress(TelegramBadRequest): await bot.unpin_chat_message(chat_id=chat_id, message_id=game.lobby_message_id)
        await callback.message.edit_text("Игра отменена создателем. Все ставки возвращены.")
        await callback.answer()

async def schedule_game_start(chat_id: int, bot: Bot):
    try:
        await asyncio.sleep(ROULETTE_LOBBY_TIMEOUT_SECONDS)
        if chat_id not in active_games: return
        game = active_games[chat_id]
        if len(game.players) >= 2:
            await start_roulette_game(chat_id, bot)
        else:
            await db.change_rating(game.creator.id, game.stake)
            await bot.edit_message_text(text="Недостаточно игроков. Игра отменена.", chat_id=chat_id, message_id=game.lobby_message_id, reply_markup=None)
            with suppress(TelegramBadRequest):
                await bot.unpin_chat_message(chat_id=chat_id, message_id=game.lobby_message_id)
            del active_games[chat_id]
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logging.error(f"Ошибка в schedule_game_start: {e}")
        if chat_id in active_games:
            del active_games[chat_id]

async def start_roulette_game(chat_id: int, bot: Bot):
    if chat_id not in active_games: return
    game = active_games[chat_id]
    with suppress(TelegramBadRequest): await bot.unpin_chat_message(chat_id=chat_id, message_id=game.lobby_message_id)
    await bot.edit_message_text(text=f"Все в сборе! Ставки ({game.stake} 🍺 с каждого). Крутим барабан... 🔫", chat_id=chat_id, message_id=game.lobby_message_id, reply_markup=None)
    await asyncio.sleep(3)
    players_in_game = list(game.players.values())
    round_num = 1
    while len(players_in_game) > 1:
        await bot.send_message(chat_id, f"🍻 <b>Раунд {round_num}</b>. Крутим барабан... 🔫", parse_mode='HTML')
        await asyncio.sleep(5)
        loser = random.choice(players_in_game)
        players_in_game.remove(loser)
        remaining_players_text = "\n".join(f"• {p.full_name}" for p in players_in_game)
        await bot.send_message(
            chat_id,
            text=f"Выбывает... <b>{loser.full_name}</b>! 😖\n\n"
                 f"<i>Остались в игре:</i>\n{remaining_players_text}",
            parse_mode='HTML'
        )
        round_num += 1
        await asyncio.sleep(7)
    winner = players_in_game[0]
    prize = game.stake * len(game.players)
    await db.change_rating(winner.id, prize)
    winner_text = (
        f"🏆 <b>ПОБЕДИТЕЛЬ!</b> 🏆\n\n"
        f"Поздравляем, <b>{winner.full_name}</b>! Он забирает весь банк: <b>{prize} 🍺</b>!\n\n"
        f"<i>Игра окончена.</i>"
    )
    winner_message = await bot.send_message(chat_id, text=winner_text, parse_mode='HTML')
    with suppress(TelegramBadRequest):
        await bot.pin_chat_message(chat_id=chat_id, message_id=winner_message.message_id, disable_notification=True)
        asyncio.create_task(unpin_after_delay(chat_id, winner_message.message_id, bot, 120))
    del active_games[chat_id]
    chat_cooldowns[chat_id] = datetime.now()

async def unpin_after_delay(chat_id: int, message_id: int, bot: Bot, delay: int):
    await asyncio.sleep(delay)
    with suppress(TelegramBadRequest):
        await bot.unpin_chat_message(chat_id=chat_id, message_id=message_id)
