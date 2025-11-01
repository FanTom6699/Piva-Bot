# mafia_handlers/game_mafia_lobby.py
import asyncio
import logging
from aiogram import Router, Bot, F, html
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command, StateFilter, Filter
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest
from contextlib import suppress
from datetime import datetime

import config
from database import Database
from settings import SettingsManager

# --- ИСПРАВЛЕННЫЕ ИМПОРТЫ ---
# (Берем данные из utils.py в корне)
from utils import active_lobby_timers, format_time_left, active_games, GAME_ACTIVE_KEY
# (Берем FSM и 'start_game' из .py-файла, который мы создали на Шаге 5)
from .game_mafia_core import MafiaGameStates, distribute_roles_and_start 
# --- КОНЕЦ ИСПРАВЛЕНИЯ ---

mafia_lobby_router = Router()

# --- CallbackData ---
class MafiaLobbyCallbackData(CallbackData, prefix="mafia_lobby"):
    action: str # join, leave, start, toggle_timer, cancel

# --- Фильтр: Является ли админом чата ---
class IsChatAdmin(Filter):
    async def __call__(self, message_or_callback: Message | CallbackQuery, bot: Bot) -> bool:
        if isinstance(message_or_callback, CallbackQuery):
            chat_id = message_or_callback.message.chat.id
        else:
            chat_id = message_or_callback.chat.id
            
        member = await bot.get_chat_member(chat_id, message_or_callback.from_user.id)
        return member.status in ('administrator', 'creator')

# --- Вспомогательные функции Лобби ---

async def is_game_active(chat_id: int) -> bool:
    """
    Проверяет, не идет ли уже в чате другая игра (Рулетка, Лесенка).
    (Использует 'active_games' из utils.py)
    """
    return active_games.get(chat_id, {}).get(GAME_ACTIVE_KEY, False)


async def generate_lobby_text_and_keyboard(db: Database, settings: SettingsManager, chat_id: int, creator_id: int, timer_enabled: bool) -> (str, InlineKeyboardMarkup):
    """Генерирует текст и кнопки для лобби-сообщения."""
    
    players_list_data = await db.get_mafia_players(chat_id)
    player_count = len(players_list_data)
    
    text = f"🕵️‍♂️ <b>Набор в 'Пивную Мафию'</b> 🕵️‍♂️\n\n"
    text += f"Идет набор игроков. Ведущий (создатель): {html.quote((await db.get_user_by_id(creator_id))[0])}\n\n"
    
    text += "<b>Участники:</b>\n"
    if not players_list_data:
        text += "<i>Пока никого нет...</i>\n"
    else:
        for i, player in enumerate(players_list_data):
            user_id = player[1]
            player_name = html.quote((await db.get_user_by_id(user_id))[0])
            text += f"{i+1}. {player_name}\n"
            
    text += f"\n<b>Всего:</b> {player_count} / {settings.mafia_max_players}\n"
    
    if timer_enabled:
        time_left = format_time_left(settings.mafia_lobby_timer)
        text += f"Авто-старт через: <b>{time_left}</b> (если наберется мин. {settings.mafia_min_players} чел.)"
    else:
        text += "<i>Авто-старт отключен. Ожидаем создателя.</i>"
        
    # --- Клавиатура ---
    buttons = [
        [
            InlineKeyboardButton(text="✅ Присоединиться", callback_data=MafiaLobbyCallbackData(action="join").pack()),
            InlineKeyboardButton(text="❌ Покинуть", callback_data=MafiaLobbyCallbackData(action="leave").pack())
        ],
        [
            InlineKeyboardButton(text="▶️ Начать игру", callback_data=MafiaLobbyCallbackData(action="start").pack()),
            InlineKeyboardButton(
                text=f"⏱️ {'Выкл' if timer_enabled else 'Вкл'} Таймер", 
                callback_data=MafiaLobbyCallbackData(action="toggle_timer").pack()
            )
        ],
        [InlineKeyboardButton(text="🚫 Отменить игру", callback_data=MafiaLobbyCallbackData(action="cancel").pack())]
    ]
    
    return text, InlineKeyboardMarkup(inline_keyboard=buttons)

async def update_lobby_message(bot: Bot, db: Database, settings: SettingsManager, chat_id: int):
    """Обновляет текст и кнопки в лобби (вызывается при join/leave)."""
    game = await db.get_mafia_game(chat_id)
    if not game or game[3] != 'lobby': # game[3] = status
        return
        
    message_id = game[1]
    creator_id = game[2]
    timer_enabled = chat_id in active_lobby_timers
    
    try:
        text, keyboard = await generate_lobby_text_and_keyboard(db, settings, chat_id, creator_id, timer_enabled)
        await bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            pass # Не спамим, если сообщение не изменилось
        else:
            logging.error(f"[Mafia {chat_id}] Ошибка обновления лобби: {e}")
    except Exception as e:
        logging.error(f"[Mafia {chat_id}] Крит. ошибка обновления лобби: {e}")

async def lobby_timer_task(chat_id: int, bot: Bot, db: Database, settings: SettingsManager):
    """Фоновая задача-таймер для лобби."""
    await asyncio.sleep(settings.mafia_lobby_timer)
    
    if chat_id in active_lobby_timers:
        del active_lobby_timers[chat_id]
        
    game = await db.get_mafia_game(chat_id)
    if not game or game[3] != 'lobby':
        logging.info(f"[Mafia {chat_id}] Таймер лобби: игра не найдена, отмена.")
        return

    player_count = await db.get_mafia_player_count(chat_id)
    
    if player_count < settings.mafia_min_players:
        logging.info(f"[Mafia {chat_id}] Таймер лобби: Недостаточно игроков ({player_count}). Отмена.")
        await bot.send_message(chat_id, "⏰ Время вышло, а игроков не набралось. Игра отменена.")
        await db.delete_mafia_game(chat_id)
        if chat_id in active_games: del active_games[chat_id]
    else:
        logging.info(f"[MafIA {chat_id}] Таймер лобби: Запуск игры...")
        players = await db.get_mafia_players(chat_id)
        await distribute_roles_and_start(chat_id, bot, db, settings, players)


# --- ХЭНДЛЕРЫ ЛОББИ ---

@mafia_lobby_router.message(Command("mafia"))
async def cmd_mafia_start(message: Message, bot: Bot, db: Database, settings: SettingsManager):
    chat_id = message.chat.id
    if message.chat.type == 'private':
        await message.reply("🕵️‍♂️ Игру в Мафию можно начать только в <b>групповом чате</b>.", parse_mode="HTML")
        return
        
    if await is_game_active(chat_id):
        await message.reply("В этом чате уже идет другая игра (Рулетка или Лесенка). Дождитесь ее окончания.")
        return
        
    if await db.get_mafia_game(chat_id):
        await message.reply("В этом чате уже идет набор или игра в Мафию!")
        return
        
    # Отправляем "пустышку", чтобы получить message_id
    dummy_message = await message.answer("Создание лобби...")
    message_id = dummy_message.message_id
    
    creator_id = message.from_user.id
    
    # Создаем игру в БД
    success = await db.create_mafia_game(chat_id, message_id, creator_id)
    if not success:
        await dummy_message.edit_text("Не удалось создать игру (возможно, она уже есть).")
        return
        
    # Создаем и запускаем таймер
    task = asyncio.create_task(lobby_timer_task(chat_id, bot, db, settings))
    active_lobby_timers[chat_id] = task
    
    # Ставим флаг "игра активна"
    active_games[chat_id] = {GAME_ACTIVE_KEY: True, "game_type": "mafia"}
    
    # Обновляем сообщение в полноценное лобби
    await update_lobby_message(bot, db, settings, chat_id)
    with suppress(TelegramBadRequest):
        await bot.pin_chat_message(chat_id, message_id, disable_notification=True)


@mafia_lobby_router.callback_query(MafiaLobbyCallbackData.filter(F.action == "join"))
async def cq_mafia_join(callback: CallbackQuery, bot: Bot, db: Database, settings: SettingsManager):
    chat_id = callback.message.chat.id
    user = callback.from_user
    
    game = await db.get_mafia_game(chat_id)
    if not game or game[3] != 'lobby':
        await callback.answer("Набор в игру уже закрыт.", show_alert=True)
        return
        
    if not await db.user_exists(user.id):
        # (Проверка регистрации из handlers/common.py не сработает, т.к. это другой бот)
        # Отправляем в ЛС основному боту
        me = await bot.get_me() # Получаем инфо о Мафия-боте
        # Ищем токен Пиво-бота (хак)
        main_bot_token = os.getenv("BOT_TOKEN", getattr(config, "BOT_TOKEN", None))
        if main_bot_token:
            try:
                main_bot_info = await Bot(main_bot_token).get_me()
                start_link = f"https://t.me/{main_bot_info.username}?start=register"
                await callback.answer("Вы не зарегистрированы в Пивном Боте! Сначала зайдите к нему в ЛС.", show_alert=True)
                await bot.send_message(user.id, f"Похоже, ты не зарегистрирован в основном боте 'Пивной'.\n"
                                             f"Зайди сюда ➡️ @{main_bot_info.username} и нажми /start, потом возвращайся.",
                                             reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                                 [InlineKeyboardButton(text="➡️ К Пивному Боту", url=start_link)]
                                             ]))
            except Exception:
                 await callback.answer("Ошибка: не могу найти основного Пивного Бота для регистрации.", show_alert=True)
        else:
             await callback.answer("Ошибка: не могу найти основного ПивCSS-бота.", show_alert=True)
        return

    player_count = await db.get_mafia_player_count(chat_id)
    if player_count >= settings.mafia_max_players:
        await callback.answer("Лобби заполнено!", show_alert=True)
        return
        
    success = await db.add_mafia_player(chat_id, user.id)
    if success:
        await callback.answer("Вы присоединились к игре!")
        await update_lobby_message(bot, db, settings, chat_id)
    else:
        await callback.answer("Вы уже в игре!", show_alert=True)


@mafia_lobby_router.callback_query(MafiaLobbyCallbackData.filter(F.action == "leave"))
async def cq_mafia_leave(callback: CallbackQuery, bot: Bot, db: Database, settings: SettingsManager):
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    
    game = await db.get_mafia_game(chat_id)
    if not game or game[3] != 'lobby':
        await callback.answer("Набор в игру уже закрыт.", show_alert=True)
        return
        
    await db.remove_mafia_player(chat_id, user_id)
    await callback.answer("Вы покинули лобби.")
    await update_lobby_message(bot, db, settings, chat_id)


@mafia_lobby_router.callback_query(MafiaLobbyCallbackData.filter(F.action == "cancel"), IsChatAdmin())
async def cq_mafia_cancel_game(callback: CallbackQuery, bot: Bot, db: Database, settings: SettingsManager):
    chat_id = callback.message.chat.id
    game = await db.get_mafia_game(chat_id)
    if not game: return await callback.answer()
    
    # Отменяем таймер
    if chat_id in active_lobby_timers:
        active_lobby_timers[chat_id].cancel()
        del active_lobby_timers[chat_id]
        
    # Удаляем флаг игры
    if chat_id in active_games:
        del active_games[chat_id]
        
    message_id = game[1]
    with suppress(TelegramBadRequest):
        await bot.unpin_chat_message(chat_id, message_id)
        
    await db.delete_mafia_game(chat_id)
    await callback.answer("Игра отменена.")
    await bot.edit_message_text("🚫 Игра в Мафию отменена.", chat_id, message_id, reply_markup=None)


@mafia_lobby_router.callback_query(MafiaLobbyCallbackData.filter(F.action == "toggle_timer"))
async def cq_mafia_toggle_timer(callback: CallbackQuery, bot: Bot, db: Database, settings: SettingsManager):
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    
    game = await db.get_mafia_game(chat_id)
    if not game or game[3] != 'lobby': return await callback.answer()
    
    creator_id = game[2]
    if user_id != creator_id:
        await callback.answer("Только создатель лобби может управлять таймером.", show_alert=True)
        return

    if chat_id in active_lobby_timers:
        active_lobby_timers[chat_id].cancel()
        del active_lobby_timers[chat_id]
        await callback.answer("Таймер авто-старта отключен.")
        await update_lobby_message(bot, db, settings, chat_id)
    else:
        task = asyncio.create_task(lobby_timer_task(chat_id, bot, db, settings))
        active_lobby_timers[chat_id] = task
        await callback.answer("Таймер авто-старта запущен!")
        await update_lobby_message(bot, db, settings, chat_id)

@mafia_lobby_router.callback_query(MafiaLobbyCallbackData.filter(F.action == "start"), IsChatAdmin())
async def cq_mafia_start_game(callback: CallbackQuery, bot: Bot, db: Database, settings: SettingsManager):
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    
    game = await db.get_mafia_game(chat_id)
    if not game or game[3] != 'lobby': return
    
    creator_id = game[2]
    
    # Проверка на Админа чата (фильтр IsChatAdmin уже сделал, но для /startgame нужна отдельная)
    # Здесь мы разрешаем любому Админу (не только создателю)
    
    player_count = await db.get_mafia_player_count(chat_id)
    if player_count < settings.mafia_min_players:
        await callback.answer(f"Недостаточно игроков. (Мин: {settings.mafia_min_players})", show_alert=True)
        return

    # Отменяем таймер
    if chat_id in active_lobby_timers:
        active_lobby_timers[chat_id].cancel()
        del active_lobby_timers[chat_id]
        
    await callback.answer("Принудительный запуск игры...")
    
    players = await db.get_mafia_players(chat_id)
    await distribute_roles_and_start(chat_id, bot, db, settings, players)


# --- Команда принудительного старта (для Админов) ---
@mafia_lobby_router.message(Command("startgame"), IsChatAdmin())
async def cmd_mafia_force_start(message: Message, bot: Bot, db: Database, settings: SettingsManager):
    chat_id = message.chat.id
    
    game = await db.get_mafia_game(chat_id)
    if not game or game[3] != 'lobby':
        await message.reply("Сейчас нет активного лобби.")
        return

    player_count = await db.get_mafia_player_count(chat_id)
    if player_count < settings.mafia_min_players:
        await message.reply(f"Недостаточно игроков. (Мин: {settings.mafia_min_players})")
        return

    # Отменяем таймер
    if chat_id in active_lobby_timers:
        active_lobby_timers[chat_id].cancel()
        del active_lobby_timers[chat_id]
        
    await message.answer("Принудительный запуск игры...")
    
    players = await db.get_mafia_players(chat_id)
    await distribute_roles_and_start(chat_id, bot, db, settings, players)
