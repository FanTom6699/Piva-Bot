# handlers/game_ladder.py
import asyncio
import random
from datetime import datetime, timedelta
from contextlib import suppress
import logging
from typing import List

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, User, Chat
from aiogram.enums.chat_action import ChatAction
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.exceptions import TelegramBadRequest

import config
from database import Database
from settings import SettingsManager
from .common import check_user_registered

# --- ИНИЦИАЛИЗАЦИЯ ---
ladder_router = Router()

# --- CALLBACKDATA ---
class LadderCallbackData(CallbackData, prefix="ladder"):
    action: str
    level: int = 0
    choice: int = 0
    stake: int = 0

# --- КЛАССЫ И КОНСТАНТЫ ---
class LadderGameState:
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
        self.task = None

LADDER_LEVELS = 10
LADDER_INACTIVITY_TIMEOUT_SECONDS = 60
active_ladder_games = {}

LADDER_MULTIPLIERS = [1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 2.0, 2.2, 2.5]
def calculate_ladder_rewards(stake: int) -> List[float]:
    rewards = []
    current_win = float(stake)
    for i in range(LADDER_LEVELS):
        current_win *= LADDER_MULTIPLIERS[i]
        rewards.append(round(current_win, 2))
    return rewards

# --- ФУНКЦИИ ИГРЫ ---
async def schedule_ladder_timeout(chat_id: int, player_id: int, message_id: int, stake: int, bot: Bot, db: Database):
    try:
        await asyncio.sleep(LADDER_INACTIVITY_TIMEOUT_SECONDS)
        if chat_id in active_ladder_games:
            game = active_ladder_games[chat_id]
            if game.player_id == player_id and game.current_level == 1 and not game.is_finished:
                await db.change_rating(player_id, stake)
                await bot.send_message(
                    chat_id=chat_id,
                    text=f"⏰ Игра в 'Лесенку' отменена из-за бездействия. Ваша ставка {stake} 🍺 возвращена."
                )
                with suppress(TelegramBadRequest):
                    await bot.delete_message(chat_id=chat_id, message_id=message_id)
                del active_ladder_games[chat_id]
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logging.error(f"Ошибка в таймере бездействия Лесенки для чата {chat_id}: {e}")
        if chat_id in active_ladder_games:
            del active_ladder_games[chat_id]

async def generate_ladder_keyboard(game: LadderGameState, rewards: List[float], reveal: bool = False, is_win: bool = False) -> InlineKeyboardMarkup:
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
                    if not is_win:
                        btn_text = f"🍺 {rewards[level_idx]}" if is_correct_path else "❌"
                    else:
                         btn_text = " "
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
            
            callback_data = "do_nothing"
            if is_active:
                callback_data = LadderCallbackData(action="play", level=i, choice=j, stake=game.stake).pack()
                
            row.append(InlineKeyboardButton(text=btn_text, callback_data=callback_data))
        keyboard.append(row)
    
    if not game.is_finished:
        cash_out_text = f"💰 Забрать выигрыш ({game.current_win} 🍺)" if game.current_win > 0 else "💰 Забрать ставку"
        keyboard.append([InlineKeyboardButton(text=cash_out_text, callback_data=LadderCallbackData(action="cash_out", stake=game.stake).pack())])
    else:
        keyboard.append([InlineKeyboardButton(text=f"🔁 Играть снова ({game.stake} 🍺)", callback_data=LadderCallbackData(action="play_again", stake=game.stake).pack())])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

async def generate_ladder_text(game: LadderGameState) -> str:
    return (f"🪜 <b>Пивная Лесенка</b> 🪜\n\n" f"Ставка: <b>{game.stake} 🍺</b> | Текущий выигрыш: <b>{game.current_win} 🍺</b>")

async def end_ladder_game(bot: Bot, chat_id: int, user: User, game: LadderGameState, is_win: bool, db: Database):
    game.is_finished = True
    if game.task:
        game.task.cancel()
        game.task = None
    
    with suppress(TelegramBadRequest):
        await bot.delete_message(chat_id=game.chat_id, message_id=game.message_id)

    play_again_button = InlineKeyboardButton(
        text=f"🔁 Играть снова ({game.stake} 🍺)",
        callback_data=LadderCallbackData(action="play_again", stake=game.stake).pack()
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[play_again_button]])
    
    player_name = user.full_name
    rewards = calculate_ladder_rewards(game.stake)
    
    if is_win:
        win_amount = game.current_win if game.current_win > 0 else game.stake
        await db.change_rating(game.player_id, int(win_amount))
        text = f"🎉 <b>Победа в Лесенке!</b> 🎉\n\nИгрок: <b>{player_name}</b>\nЗабрал выигрыш: <b>+{int(win_amount)} 🍺</b>"
        final_board_text = await generate_final_board_text(game, rewards, is_win=True)
    else:
        text = f"💥 <b>Неудача в Лесенке!</b> 💥\n\nИгрок: <b>{player_name}</b>\nОшибка на Уровне {game.current_level}!\nСтавка <b>{game.stake} 🍺</b> сгорела."
        final_board_text = await generate_final_board_text(game, rewards, is_win=False)

    await bot.send_message(chat_id=chat_id, text=f"{text}\n\n{final_board_text}", reply_markup=keyboard, parse_mode='HTML')

    if game.chat_id in active_ladder_games:
        del active_ladder_games[game.chat_id]

async def generate_final_board_text(game: LadderGameState, rewards: List[float], is_win: bool) -> str:
    board_lines = ["<b>Ваш путь:</b>\n"]
    for i in range(LADDER_LEVELS, 0, -1):
        level_idx = i - 1
        row = ["", ""]
        is_correct_path_0 = (0 == game.correct_path[level_idx])
        is_correct_path_1 = (1 == game.correct_path[level_idx])
        if i < game.current_level:
            if 0 == game.player_choices.get(level_idx): row[0], row[1] = "✅", "⬛"
            else: row[0], row[1] = "⬛", "✅"
        elif i == game.current_level and not is_win:
            if 0 == game.last_choice: row[0], row[1] = "❌", "🍺"
            else: row[0], row[1] = "🍺", "❌"
        elif i == game.current_level and is_win:
            if 0 == game.player_choices.get(level_idx - 1): row[0], row[1] = "✅", "⬛"
            else: row[0], row[1] = "⬛", "✅"
        elif i >= game.current_level and is_win:
            if i in game.player_choices:
                 if 0 == game.player_choices.get(level_idx): row[0], row[1] = "✅", "⬛"
                 else: row[0], row[1] = "⬛", "✅"
            else:
                 row[0] = " "
                 row[1] = " "
        else:
            row[0] = "🍺" if is_correct_path_0 else "💨"
            row[1] = "🍺" if is_correct_path_1 else "💨"
        board_lines.append(f"<code>{rewards[level_idx]:<7} | {row[0]:<2} | {row[1]:<2}</code>")
    return "\n".join(board_lines)

async def start_ladder_game(chat: Chat, user: User, bot: Bot, stake: int, db: Database):
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
    game.task = asyncio.create_task(schedule_ladder_timeout(chat.id, user.id, game.message_id, stake, bot, db))

@ladder_router.message(Command("ladder"))
async def cmd_ladder(message: Message, bot: Bot, db: Database, settings: SettingsManager):
    chat_id = message.chat.id
    if chat_id in active_ladder_games:
        return await message.reply("Пожалуйста, подождите, пока текущая игра в 'Лесенку' в этом чате не закончится.")
    args = message.text.split()
    if len(args) != 2 or not args[1].isdigit():
        return await message.reply("Неверный формат. Используйте: `/ladder <ставка>` (например, `/ladder 10`).")
    
    stake = int(args[1])
    min_bet = settings.ladder_min_bet
    max_bet = settings.ladder_max_bet
    
    if not (min_bet <= stake <= max_bet):
        return await message.reply(f"Ставка должна быть от {min_bet} до {max_bet} 🍺.")
    if not await check_user_registered(message, bot, db):
        return
    balance = await db.get_user_beer_rating(message.from_user.id)
    if balance < stake:
        return await message.reply(f"У вас недостаточно пива для этой ставки. Нужно {stake} 🍺, у вас {balance} 🍺.")
    await start_ladder_game(message.chat, message.from_user, bot, stake, db)

@ladder_router.callback_query(LadderCallbackData.filter(F.action == "play_again"))
async def on_ladder_play_again(callback: CallbackQuery, callback_data: LadderCallbackData, bot: Bot, db: Database):
    await callback.answer()
    stake = callback_data.stake
    
    if callback.message.chat.id in active_ladder_games:
        return await callback.message.answer("Пожалуйста, подождите, пока текущая игра в 'Лесенку' в этом чате не закончится.", show_alert=True)
    balance = await db.get_user_beer_rating(callback.from_user.id)
    if balance < stake:
         return await callback.message.answer(f"Недостаточно пива для новой игры! Нужно {stake} 🍺, у вас {balance} 🍺.")
    
    await callback.message.delete()
    await start_ladder_game(callback.message.chat, callback.from_user, bot, stake, db)

@ladder_router.callback_query(LadderCallbackData.filter(F.action.in_({"play", "cash_out"})))
async def on_ladder_game_callback(callback: CallbackQuery, callback_data: LadderCallbackData, bot: Bot, db: Database):
    chat_id = callback.message.chat.id
    user = callback.from_user
    if chat_id not in active_ladder_games:
        return await callback.answer("Эта игра больше не активна.", show_alert=True)
    game = active_ladder_games[chat_id]
    if user.id != game.player_id:
        return await callback.answer("Это не ваша игра!", show_alert=True)
    if game.is_finished:
        return await callback.answer()

    action = callback_data.action
    
    if action == "cash_out":
        if game.current_win == 0 and game.current_level == 1:
            return await callback.answer("Сделайте хотя бы один ход!", show_alert=True)
        await callback.answer()
        await end_ladder_game(bot, chat_id, user, game, is_win=True, db=db)
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
                await end_ladder_game(bot, chat_id, user, game, is_win=True, db=db)
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
            await end_ladder_game(bot, chat_id, user, game, is_win=False, db=db)
