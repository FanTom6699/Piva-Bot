# handlers/game_mafia_lobby.py
import asyncio
import logging
from aiogram import Router, Bot, F, html
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command, StateFilter
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
# --- FSM (StatesGroup) УБРАН ОТСЮДА ---
from aiogram.exceptions import TelegramBadRequest
from contextlib import suppress

import config
from database import Database
from settings import SettingsManager
from utils import active_lobby_timers, format_time_left

# Импортируем проверку на 'Рулетку' и 'Лесенку'
from .user_commands import is_game_active, active_games, GAME_ACTIVE_KEY
# --- НОВЫЙ ИМПОРТ FSM ИЗ ЯДРА ---
from .game_mafia_core import MafiaGameStates

mafia_lobby_router = Router()

# --- CallbackData ---
class MafiaLobbyCallbackData(CallbackData, prefix="mafia_lobby"):
    action: str # join, leave, start, toggle_timer, cancel

# --- Вспомогательные функции Лобби ---

async def generate_lobby_text_and_keyboard(db: Database, settings: SettingsManager, chat_id: int, creator_id: int, timer_enabled: bool) -> (str, InlineKeyboardMarkup):
    """Генерирует текст и кнопки для лобби-сообщения."""
    
    players_list_data = await db.get_mafia_players(chat_id)
    player_count = len(players_list_data)
    
    player_lines = []
    for i, player_data in enumerate(players_list_data):
        user_id = player_data[1] # [game_id, user_id, ...]
        user_name = None
        
        db_user = await db.get_user_by_id(user_id)
        if db_user:
            # (first_name, last_name, username)
            user_name = db_user[0] # Берем first_name из нашей БД
            
        if not user_name:
             user_name = f"Игрок {i+1}"

        if user_id == creator_id:
            player_lines.append(f"• 👑 {html.quote(user_name)} (Создатель)")
        else:
            player_lines.append(f"• {html.quote(user_name)}")

    # Формируем текст
    text = f"🍻 <b>НАБОР В ПИВНОЙ ПЕРЕПОЛОХ!</b> 🍻\n\n"
    text += f"Собираем компанию ({settings.mafia_min_players}-{settings.mafia_max_players} чел) для игры.\n\n"
    text += f"<b>Игроки ({player_count}/{settings.mafia_max_players}):</b>\n"
    text += "\n".join(player_lines)
    
    if timer_enabled:
        time_left_str = format_time_left(settings.mafia_lobby_timer)
        text += f"\n\n⏳ <i>Игра начнется автоматически через ~{time_left_str}.</i>"
    else:
        text += f"\n\n⏳ <i>Авто-старт отключен. Ждем, пока создатель запустит игру вручную.</i>"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✍️ Присоединиться", callback_data=MafiaLobbyCallbackData(action="join").pack())],
        [InlineKeyboardButton(text="🚪 Выйти", callback_data=MafiaLobbyCallbackData(action="leave").pack())],
        [
            InlineKeyboardButton(text=f"🚀 Начать игру ({player_count}/{settings.mafia_min_players}+)", callback_data=MafiaLobbyCallbackData(action="start").pack()),
            InlineKeyboardButton(
                text="🚫 Откл. таймер" if timer_enabled else "✅ Вкл. таймер",
                callback_data=MafiaLobbyCallbackData(action="toggle_timer").pack()
            )
        ],
        [InlineKeyboardButton(text="❌ Отменить набор", callback_data=MafiaLobbyCallbackData(action="cancel").pack())]
    ])

    return text, keyboard

async def update_lobby_message(bot: Bot, db: Database, settings: SettingsManager, chat_id: int):
    """Перерисовывает сообщение лобби."""
    game = await db.get_mafia_game(chat_id)
    if not game or game[3] != 'lobby': # game[3] это 'status'
        return

    message_id = game[1] # message_id
    creator_id = game[2] # creator_id
    
    timer_enabled = chat_id in active_lobby_timers

    text, keyboard = await generate_lobby_text_and_keyboard(db, settings, chat_id, creator_id, timer_enabled)
    
    with suppress(TelegramBadRequest):
        await bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="HTML")

async def lobby_timer_task(chat_id: int, bot: Bot, db: Database, settings: SettingsManager):
    """Фоновая задача-таймер, которая обновляет лобби и запускает игру."""
    lobby_duration = settings.mafia_lobby_timer
    
    sleep_time = min(15, lobby_duration // 3)
    if sleep_time <= 0: sleep_time = lobby_duration
    
    slept_time = 0
    while slept_time < lobby_duration:
        await asyncio.sleep(sleep_time)
        slept_time += sleep_time
        
        if chat_id not in active_lobby_timers:
            logging.info(f"[Mafia {chat_id}] Таймер лобби отменен.")
            return
            
        game = await db.get_mafia_game(chat_id)
        if not game: return
        
        message_id = game[1]
        creator_id = game[2]
        
        time_left_approx = lobby_duration - slept_time
        time_left_str = format_time_left(time_left_approx)

        text, keyboard = await generate_lobby_text_and_keyboard(db, settings, chat_id, creator_id, True)
        text = text.replace(f"~{format_time_left(settings.mafia_lobby_timer)}", f"~{time_left_str}")
        
        with suppress(TelegramBadRequest):
            await bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="HTML")

    logging.info(f"[Mafia {chat_id}] Таймер лобби истек. Запускаем игру...")
    if chat_id in active_lobby_timers:
        del active_lobby_timers[chat_id]
        
    await start_mafia_game(chat_id, bot, db, settings)

async def start_mafia_game(chat_id: int, bot: Bot, db: Database, settings: SettingsManager):
    """
    Главная функция запуска. Проводит все проверки (кол-во, ЛС) 
    и передает управление ядру игры (которое мы напишем в следующем файле).
    """
    logging.info(f"[Mafia {chat_id}] Попытка запуска игры...")
    
    active_games[chat_id] = {GAME_ACTIVE_KEY: True, "user_id": 0, "game_type": "mafia"}
    
    if chat_id in active_lobby_timers:
        active_lobby_timers[chat_id].cancel()
        del active_lobby_timers[chat_id]
        
    game = await db.get_mafia_game(chat_id)
    if not game or game[3] != 'lobby': 
        logging.warning(f"[Mafia {chat_id}] Попытка запуска, но игра не найдена в БД или не в лобби.")
        if chat_id in active_games: del active_games[chat_id]
        return
        
    message_id = game[1]
    players = await db.get_mafia_players(chat_id)
    player_count = len(players)
    
    if player_count < settings.mafia_min_players:
        logging.info(f"[Mafia {chat_id}] Недостаточно игроков ({player_count}). Отмена.")
        await db.delete_mafia_game(chat_id)
        if chat_id in active_games: del active_games[chat_id]
        
        with suppress(TelegramBadRequest):
            await bot.edit_message_text(
                f"❌ <b>Набор отменен!</b> ❌\nНе набралось минимальное кол-во игроков ({settings.mafia_min_players}).",
                chat_id, message_id, reply_markup=None
            )
        with suppress(TelegramBadRequest):
            await bot.unpin_chat_message(chat_id, message_id)
        return

    await bot.edit_message_text(
        "⏳ <i>Проверяю, что могу написать всем игрокам в ЛС...</i>",
        chat_id, message_id, reply_markup=None
    )
    
    undeliverable_users_data = []
    
    for player_data in players:
        user_id = player_data[1]
        try:
            await bot.send_message(user_id, "⏳ Проверка личных сообщений...\nИгра 'Пивной Переполох' скоро начнется!")
            await asyncio.sleep(0.1) 
        except Exception as e:
            logging.warning(f"[Mafia {chat_id}] Не удалось написать игроку {user_id}: {e}")
            
            user_name = f"Игрок {user_id}"
            db_user = await db.get_user_by_id(user_id)
            if db_user: user_name = db_user[0]
            undeliverable_users_data.append((user_id, user_name))

    if undeliverable_users_data:
        names_to_tag = [f"{html.quote(name)}" for user_id, name in undeliverable_users_data]
            
        await db.delete_mafia_game(chat_id)
        if chat_id in active_games: del active_games[chat_id]
        
        await bot.edit_message_text(
            f"❌ <b>Игра отменена!</b> ❌\n\n"
            f"Не удалось написать в ЛС следующим игрокам:\n"
            f"• {', '.join(names_to_tag)}\n\n"
            f"<i>Попросите их запустить бота (@{config.BOT_USERNAME}) у себя в ЛС и попробуйте снова.</i>",
            chat_id, message_id, reply_markup=None, parse_mode="HTML"
        )
        with suppress(TelegramBadRequest):
            await bot.unpin_chat_message(chat_id, message_id)
        return

    # --- ВЫЗЫВАЕМ ЯДРО ИГРЫ ---
    try:
        from .game_mafia_core import distribute_roles_and_start
        
        await distribute_roles_and_start(chat_id, bot, db, settings, players)
        
    except Exception as e:
        logging.error(f"[Mafia {chat_id}] КРИТИЧЕСКАЯ ОШИБКА при запуске ядра игры: {e}")
        await db.delete_mafia_game(chat_id)
        if chat_id in active_games: del active_games[chat_id]
        
        with suppress(TelegramBadRequest):
            await bot.edit_message_text(
                f"❌ <b>Критическая ошибка!</b> ❌\n"
                f"Не удалось запустить ядро игры. Пожалуйста, сообщите админу.\n"
                f"<i>Ошибка: {e}</i>",
                chat_id, message_id, reply_markup=None
            )
        with suppress(TelegramBadRequest):
            await bot.unpin_chat_message(chat_id, message_id)
    # --- ---


# --- ХЭНДЛЕРЫ ЛОББИ ---

@mafia_lobby_router.message(Command("mafia"))
async def cmd_mafia(message: Message, bot: Bot, db: Database, settings: SettingsManager):
    if message.chat.type == 'private':
        await message.reply("Эту игру можно запускать только в группах.")
        return
        
    if is_game_active(message.chat.id):
        await message.reply("В этом чате уже идет другая игра (Рулетка, Лесенка или Мафия). Дождитесь ее окончания.")
        return
    
    try:
        me = await bot.get_me()
        chat_member = await bot.get_chat_member(message.chat.id, me.id)
        if not chat_member.can_pin_messages or not chat_member.can_restrict_members:
            await message.reply("<b>Ошибка!</b> 😥\nДля проведения игры боту нужны права:\n• `Закреплять сообщения` (для лобби)\n• `Блокировать участников` (для модерации чата)", parse_mode="HTML")
            return
    except Exception as e:
        await message.reply(f"Не удалось проверить права администратора. Ошибка: {e}")
        return

    creator_id = message.from_user.id
    
    if not await db.user_exists(creator_id):
        await db.add_user(
            user_id=creator_id,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
            username=message.from_user.username
        )
    
    try:
        success_create = await db.create_mafia_game(
            chat_id=message.chat.id,
            message_id=0, # Временный
            creator_id=creator_id
        )
        if not success_create:
            await message.reply("Игра уже создается, подождите...")
            return
            
        await db.add_mafia_player(message.chat.id, creator_id)
        
        lobby_text, lobby_keyboard = await generate_lobby_text_and_keyboard(db, settings, message.chat.id, creator_id, True)
        
        lobby_message = await message.answer(
            lobby_text,
            reply_markup=lobby_keyboard,
            parse_mode="HTML"
        )
        await bot.pin_chat_message(message.chat.id, lobby_message.message_id)
        
        await db.update_mafia_game_message_id(message.chat.id, lobby_message.message_id)
        
    except Exception as e:
        await message.answer(f"Не удалось создать лобби. Ошибка: {e}")
        await db.delete_mafia_game(message.chat.id) # Чистим за собой
        return
        
    active_games[message.chat.id] = {GAME_ACTIVE_KEY: True, "user_id": 0, "game_type": "mafia"}
    
    task = asyncio.create_task(lobby_timer_task(message.chat.id, bot, db, settings))
    active_lobby_timers[message.chat.id] = task
    logging.info(f"[Mafia {message.chat.id}] Лобби создано, таймер запущен.")


@mafia_lobby_router.callback_query(MafiaLobbyCallbackData.filter(F.action == "join"))
async def cq_mafia_join(callback: CallbackQuery, bot: Bot, db: Database, settings: SettingsManager):
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    
    game = await db.get_mafia_game(chat_id)
    if not game or game[3] != 'lobby':
        await callback.answer("Набор в игру уже закрыт.", show_alert=True)
        return

    player_count = await db.get_mafia_player_count(chat_id)
    if player_count >= settings.mafia_max_players:
        await callback.answer(f"Лобби заполнено (макс. {settings.mafia_max_players} игроков).", show_alert=True)
        return
        
    if not await db.user_exists(user_id):
        await db.add_user(
            user_id=user_id,
            first_name=callback.from_user.first_name,
            last_name=callback.from_user.last_name,
            username=callback.from_user.username
        )
        
    success = await db.add_mafia_player(chat_id, user_id)
    
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
        
    creator_id = game[2]
    if user_id == creator_id:
        await callback.answer("Создатель не может покинуть лобби. Отмените набор (❌).", show_alert=True)
        return
        
    await db.remove_mafia_player(chat_id, user_id)
    await callback.answer("Вы покинули лобби.")
    await update_lobby_message(bot, db, settings, chat_id)


@mafia_lobby_router.callback_query(MafiaLobbyCallbackData.filter(F.action == "cancel"))
async def cq_mafia_cancel(callback: CallbackQuery, bot: Bot, db: Database):
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    
    game = await db.get_mafia_game(chat_id)
    if not game: return
    
    creator_id = game[2]
    if user_id != creator_id and user_id != config.ADMIN_ID:
        await callback.answer("Только создатель лобби или Админ может отменить набор.", show_alert=True)
        return

    if chat_id in active_lobby_timers:
        active_lobby_timers[chat_id].cancel()
        del active_lobby_timers[chat_id]
        
    await db.delete_mafia_game(chat_id)
    if chat_id in active_games: del active_games[chat_id]
    
    await callback.answer("Набор в игру отменен.")
    with suppress(TelegramBadRequest):
        await bot.edit_message_text(
            f"❌ <b>Набор отменен!</b> ❌\n<i>(Отменил: {callback.from_user.first_name})</i>",
            chat_id, callback.message.message_id, reply_markup=None,
            parse_mode="HTML"
        )
    with suppress(TelegramBadRequest):
        await bot.unpin_chat_message(chat_id, callback.message.message_id)

@mafia_lobby_router.callback_query(MafiaLobbyCallbackData.filter(F.action == "toggle_timer"))
async def cq_mafia_toggle_timer(callback: CallbackQuery, bot: Bot, db: Database, settings: SettingsManager):
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    
    game = await db.get_mafia_game(chat_id)
    if not game or game[3] != 'lobby': return
    
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

@mafia_lobby_router.callback_query(MafiaLobbyCallbackData.filter(F.action == "start"))
async def cq_mafia_start_game(callback: CallbackQuery, bot: Bot, db: Database, settings: SettingsManager):
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    
    game = await db.get_mafia_game(chat_id)
    if not game or game[3] != 'lobby': return
    
    creator_id = game[2]
    if user_id != creator_id:
        await callback.answer("Только создатель лобби может запустить игру.", show_alert=True)
        return

    player_count = await db.get_mafia_player_count(chat_id)
    if player_count < settings.mafia_min_players:
        await callback.answer(f"Недостаточно игроков. Нужно минимум {settings.mafia_min_players}.", show_alert=True)
        return
        
    await callback.answer("Запускаем игру...")
    await start_mafia_game(chat_id, bot, db, settings)
