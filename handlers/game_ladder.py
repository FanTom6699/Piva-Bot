# handlers/game_ladder.py
import asyncio
import random
import html 
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from database import Database
from settings import SettingsManager
from handlers.common import check_user_registered

game_router = Router()

# Словарь для хранения игр {chat_id: LadderGame}
active_games = {}

# Конфигурация уровней (шанс %, множитель)
LADDER_LEVELS = [
    (90, 1.2), (80, 1.5), (70, 2.0), (60, 2.5), (50, 3.5),
    (40, 5.0), (30, 7.0), (20, 10.0), (10, 15.0), (5, 25.0)
]
MAX_LEVEL = len(LADDER_LEVELS)

class LadderGame:
    def __init__(self, player_id, player_name, stake):
        self.player_id = player_id
        self.player_name = player_name
        self.stake = stake
        self.current_level = 1
        self.current_win = 0
        self.message_id = None
        self.chat_id = None
        self.lock = asyncio.Lock() # Для предотвращения двойных нажатий

    @property
    def current_chance(self):
        return LADDER_LEVELS[self.current_level - 1][0]

    @property
    def current_multiplier(self):
        return LADDER_LEVELS[self.current_level - 1][1]

# --- КОМАНДА ЗАПУСКА ИГРЫ ---
@game_router.message(Command("ladder"))
async def cmd_ladder(message: Message, bot: Bot, db: Database, settings: SettingsManager):
    if message.chat.type == "private":
        return await message.answer("❌ Эту игру можно запускать только в группах.")
    if not await check_user_registered(message, bot, db):
        return
    if message.chat.id in active_games:
        return await message.answer("❌ В этом чате уже идет игра!")

    args = message.text.split()
    if len(args) < 2:
        return await message.answer(
            "🧐 <b>Хм, не так...</b>\n"
            "Пример: <code>/ladder &lt;ставка&gt;</code>\n"
            "<i>(Например: /ladder 100)</i>",
            parse_mode='HTML'
        )

    try:
        stake = int(args[1])
    except ValueError:
        return await message.answer("❌ Ставка должна быть числом.")

    # --- ИСПРАВЛЕНИЕ ОШИБКИ 1: 'ladder_min_stake' -> 'ladder_min_bet' ---
    min_stake = settings.ladder_min_bet 
    # --- КОНЕЦ ИСПРАВЛЕНИЯ 1 ---
    
    if stake < min_stake:
        return await message.answer(f"💰 <b>Мелковато...</b>\nМинимальная ставка для 'Лесенки': <b>{min_stake}</b> 🍺.")

    user_id = message.from_user.id
    user_rating = await db.get_user_beer_rating(user_id)
    if user_rating < stake:
        return await message.answer(f"🍻 <b>Маловато 'пива'!</b>\nУ тебя всего {user_rating} 🍺, а нужно {stake} 🍺 для ставки.")

    # Списываем ставку
    await db.change_rating(user_id, -stake) # (Используем 'change_rating' из твоего database.py)
    
    game = LadderGame(user_id, message.from_user.full_name, stake)
    game.chat_id = message.chat.id
    active_games[message.chat.id] = game

    game_message = await message.answer(
        generate_ladder_text(game),
        reply_markup=generate_ladder_keyboard(game),
        parse_mode='HTML'
    )
    game.message_id = game_message.message_id

# --- ГЕНЕРАЦИЯ ТЕКСТА ИГРЫ ---
def generate_ladder_text(game: LadderGame) -> str:
    text = (
        f"🪜 <b>Пивная Лесенка</b> 🪜\n\n"
        f"Игрок: <b>{html.escape(game.player_name)}</b> (Уровень {game.current_level})\n"
        f"Твоя ставка: <b>{game.stake} 🍺</b>\n"
        f"Риск оправдан: <b>{game.current_win} 🍺</b> (Шанс {game.current_chance}%)\n\n"
        f"<i>Выбери следующую ступень. Куда везет удача?</i>"
    )
    return text

# --- ГЕНЕРАЦИЯ КНОПОК ---
def generate_ladder_keyboard(game: LadderGame) -> InlineKeyboardMarkup:
    buttons = []
    step_buttons = [InlineKeyboardButton(text="❔", callback_data=f"ladder_step_{i}") for i in range(3)]
    buttons.append(step_buttons)
    if game.current_level > 1:
        buttons.append([
            InlineKeyboardButton(text=f"💰 Забрать {game.current_win} 🍺", callback_data="ladder_take")
        ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# --- ОБРАБОТЧИК НАЖАТИЙ НА КНОПКИ ---
@game_router.callback_query(F.data.startswith("ladder_"))
async def ladder_button_callback(callback: CallbackQuery, bot: Bot, db: Database):
    chat_id = callback.message.chat.id
    if chat_id not in active_games:
        return await callback.answer("❌ Эта игра уже закончилась!", show_alert=True)

    game = active_games[chat_id]
    if callback.from_user.id != game.player_id:
        return await callback.answer("🪜 Не твоя лесенка!", show_alert=True)
    
    async with game.lock:
        if callback.data == "ladder_take":
            await end_ladder_game(bot, db, game, win=True, reason="take")
            return await callback.answer(f"Поздравляем! Ты забрал {game.current_win} 🍺.", show_alert=True)

        if random.randint(1, 100) <= game.current_chance:
            game.current_win = int(game.stake * game.current_multiplier)
            
            if game.current_level == MAX_LEVEL:
                await end_ladder_game(bot, db, game, win=True, reason="max_level")
                return await callback.answer("Ты прошел всю лесенку!", show_alert=True)
                
            game.current_level += 1
            await callback.message.edit_text(
                generate_ladder_text(game),
                reply_markup=generate_ladder_keyboard(game),
                parse_mode='HTML'
            )
            await callback.answer(f"Уровень {game.current_level}! Шанс: {game.current_chance}%")
            
        else:
            await end_ladder_game(bot, db, game, win=False, reason="fail")
            await callback.answer("💥 Ой! Ступенька сломалась...", show_alert=True)

# --- ЗАВЕРШЕНИЕ ИГРЫ ---
async def end_ladder_game(bot: Bot, db: Database, game: LadderGame, win: bool, reason: str):
    player_name = html.escape(game.player_name)
    
    if win:
        final_win = game.current_win
        await db.change_rating(game.player_id, final_win) # (Используем 'change_rating' из твоего database.py)
        
        if reason == "take":
            text = (
                f"💰 <b>Отличный улов!</b> 💰\n\n"
                f"<b>{player_name}</b> решил не рисковать и забирает <b>{final_win} 🍺</b>.\n"
                f"<i>Удача любит смелых... но и осторожных уважает!</i>"
            )
        else: # reason == "max_level"
            text = (
                f"🏆 <b>ВЕРШИНА ЛЕСЕНКИ!</b> 🏆\n\n"
                f"Невероятно! <b>{player_name}</b> прошел все {MAX_LEVEL} уровней!\n"
                f"<b>Максимальный выигрыш: {final_win} 🍺!</b>"
            )
    else:
        # reason == "fail"
        text = (
            f"💥 <b>Ой! Ступенька сломалась!</b> 💥\n\n"
            f"<b>{player_name}</b> оступился на уровне {game.current_level}.\n"
            f"Ставка <b>{game.stake} 🍺</b> сгорела. Обидно!"
        )

    await bot.edit_message_text(
        chat_id=game.chat_id,
        message_id=game.message_id,
        text=text,
        parse_mode='HTML',
        reply_markup=None 
    )
    
    if game.chat_id in active_games:
        del active_games[game.chat_id]
