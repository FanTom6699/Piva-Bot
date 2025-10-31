# handlers/game_roulette.py
import asyncio
import random
import time
import html  # --- ДОБАВЛЕНО: для экранирования имен ---
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from database import Database
from settings import SettingsManager
from handlers.common import check_user_registered

game_router = Router()

ROULETTE_LOBBY_TIMEOUT_SECONDS = 30
ROULETTE_TURN_DELAY_SECONDS = 3

# Словарь для хранения активных игр {chat_id: RouletteGame}
active_games = {}

class RouletteGame:
    def __init__(self, creator, stake, max_players):
        self.creator = creator
        self.stake = stake
        self.max_players = max_players
        self.players = {creator.id: creator}
        self.message_id = None
        self.chat_id = None
        self.lobby_task = None
        self.game_task = None

# --- КОМАНДА ЗАПУСКА ИГРЫ ---
@game_router.message(Command("roulette"))
async def cmd_roulette(message: Message, bot: Bot, db: Database, settings: SettingsManager):
    if message.chat.type == "private":
        return await message.answer("❌ Эту игру можно запускать только в группах.")
    if not await check_user_registered(message, bot, db):
        return
    if message.chat.id in active_games:
        return await message.answer("❌ В этом чате уже идет игра!")

    args = message.text.split()
    if len(args) < 3:
        # --- ИЗМЕНЕНИЕ 1: Текст ошибки (более живой) ---
        return await message.answer(
            "🧐 <b>Хм, не так...</b>\n"
            "Пример: <code>/roulette &lt;ставка&gt; &lt;игроки&gt;</code>\n"
            "<i>(Например: /roulette 100 3)</i>",
            parse_mode='HTML'
        )

    try:
        stake = int(args[1])
        max_players = int(args[2])
    except ValueError:
        return await message.answer("❌ Ставка и количество игроков должны быть числами.")

    min_stake = settings.roulette_min_stake
    if stake < min_stake:
        # --- ИЗМЕНЕНИЕ 2: Текст ошибки (более тематический) ---
        return await message.answer(f"💰 <b>Ставки повыше, друг!</b>\nМинимальная ставка для 'Рулетки': <b>{min_stake}</b> 🍺.")

    if not 2 <= max_players <= 6:
        return await message.answer("❌ В 'Рулетку' могут играть от 2 до 6 человек.")

    user_id = message.from_user.id
    user_rating = await db.get_user_beer_rating(user_id)
    if user_rating < stake:
        # --- ИЗМЕНЕНИЕ 3: Текст ошибки (более тематический) ---
        return await message.answer(f"🍻 <b>Маловато 'пива'!</b>\nУ тебя всего {user_rating} 🍺, а нужно {stake} 🍺 для ставки.")

    game = RouletteGame(creator=message.from_user, stake=stake, max_players=max_players)
    game.chat_id = message.chat.id
    active_games[message.chat.id] = game
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🍻 Присоединиться ({stake} 🍺)", callback_data="join_roulette")]
    ])
    
    lobby_text = generate_lobby_text(game)
    game_message = await message.answer(lobby_text, reply_markup=keyboard, parse_mode='HTML')
    game.message_id = game_message.message_id

    # Запускаем таймер лобби
    game.lobby_task = asyncio.create_task(
        lobby_timeout(bot, db, game)
    )

# --- ГЕНЕРАЦИЯ ТЕКСТА ЛОББИ ---
def generate_lobby_text(game: RouletteGame) -> str:
    players_list = []
    for user in game.players.values():
        # --- ТЕХ. УЛУЧШЕНИЕ: Экранируем имена ---
        safe_name = html.escape(user.full_name)
        players_list.append(f"• {safe_name}")
    players_list = "\n".join(players_list)

    # --- ИЗМЕНЕНИЕ 4: Текст лобби (призыв к действию) ---
    text = (
        f"🍻 <b>Кто рискнет в 'Рулетку'?</b> 🍻\n\n"
        f"<b>{html.escape(game.creator.full_name)}</b> ставит на кон <b>{game.stake} 🍺</b> и ждет смельчаков.\n\n"
        f"<b>Игроки за столом:</b> ({len(game.players)}/{game.max_players})\n{players_list}\n\n"
        f"<i>Старт через {ROULETTE_LOBBY_TIMEOUT_SECONDS} сек. или когда стол заполнится!</i>"
    )
    # --- КОНЕЦ ИЗМЕНЕНИЯ 4 ---
    return text

# --- ТАЙМЕР ЛОББИ ---
async def lobby_timeout(bot: Bot, db: Database, game: RouletteGame):
    await asyncio.sleep(ROULETTE_LOBBY_TIMEOUT_SECONDS)
    if game.chat_id in active_games and active_games[game.chat_id] == game:
        # Если игра все еще в лобби (не отменена и не запущена)
        if len(game.players) >= 2:
            game.game_task = asyncio.create_task(
                start_roulette_game(bot, db, game)
            )
        else:
            await bot.edit_message_text(
                chat_id=game.chat_id,
                message_id=game.message_id,
                text=f"{generate_lobby_text(game)}\n\n"
                     f"<i>Игра отменена. Не набралось хотя бы 2 игрока.</i>",
                parse_mode='HTML'
            )
            del active_games[game.chat_id]

# --- КНОПКА "ПРИСОЕДИНИТЬСЯ" ---
@game_router.callback_query(F.data == "join_roulette")
async def join_roulette_game(callback: CallbackQuery, bot: Bot, db: Database):
    user = callback.from_user
    chat_id = callback.message.chat.id

    if chat_id not in active_games:
        return await callback.answer("❌ Эта игра уже закончилась!", show_alert=True)
        
    game = active_games[chat_id]

    if game.game_task is not None:
        return await callback.answer("❌ Игра уже началась!", show_alert=True)
    if len(game.players) >= game.max_players:
        # --- ИЗМЕНЕНИЕ 5: Текст ошибки (тематический) ---
        return await callback.answer("🍻 Стол полон, друг! В следующий раз.", show_alert=True)
    if user.id in game.players:
        return await callback.answer("👍 Ты уже за столом.", show_alert=True)

    user_rating = await db.get_user_beer_rating(user.id)
    if user_rating < game.stake:
        # --- ИЗМЕНЕНИЕ 6: Текст ошибки (тематический) ---
        return await callback.answer(f"💰 Не хватает 'пива' на ставку ({game.stake} 🍺).", show_alert=True)

    # Успешное присоединение
    game.players[user.id] = user
    await callback.answer(f"Ты присоединился к игре! Ставка: {game.stake} 🍺.")
    
    await bot.edit_message_text(
        chat_id=game.chat_id,
        message_id=game.message_id,
        text=generate_lobby_text(game),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"🍻 Присоединиться ({game.stake} 🍺)", callback_data="join_roulette")]
        ]),
        parse_mode='HTML'
    )

    # Если лобби заполнено, немедленно начинаем игру
    if len(game.players) == game.max_players:
        if game.lobby_task:
            game.lobby_task.cancel() # Отменяем таймер лобби
        game.game_task = asyncio.create_task(
            start_roulette_game(bot, db, game)
        )

# --- ЛОГИКА ИГРЫ (ЗАПУСК) ---
async def start_roulette_game(bot: Bot, db: Database, game: RouletteGame):
    if len(game.players) < 2:
        # --- ИЗМЕНЕНИЕ 7: Текст отмены (тематический) ---
        await bot.edit_message_text(
            chat_id=game.chat_id,
            message_id=game.message_id,
            text=f"{generate_lobby_text(game)}\n\n"
                 f"🍻 <b>Эх! Все разбежались.</b>\nИгра отменена, не хватило игроков.",
            parse_mode='HTML'
        )
        if game.chat_id in active_games:
             del active_games[game.chat_id]
        return

    # Списываем ставки
    total_pot = 0
    players_in_game = list(game.players.values())
    
    for player in players_in_game:
        await db.update_user_beer_rating(player.id, -game.stake)
        total_pot += game.stake

    await bot.edit_message_text(
        chat_id=game.chat_id,
        message_id=game.message_id,
        text=f"<b>🍻 Рулетка крутится! 🍻</b>\n\n"
             f"<i>Игроки за столом: {len(players_in_game)}. Банк: {total_pot} 🍺</i>\n\n"
             "Затаите дыхание...",
        parse_mode='HTML'
    )
    await asyncio.sleep(ROULETTE_TURN_DELAY_SECONDS)

    # Раунды
    while len(players_in_game) > 1:
        loser = random.choice(players_in_game)
        players_in_game.remove(loser)
        
        remaining_players_text = "\n".join(f"• {html.escape(p.full_name)}" for p in players_in_game)
        
        # --- ИЗМЕНЕНИЕ 8: Текст выбывания (тематический) ---
        text = (
            f"<b>🍻 Рулетка крутится... 🍻</b>\n\n"
            f"...и пустая кружка достается... <b>{html.escape(loser.full_name)}</b>! 😖\n\n"
            f"<i>Ты выбыл. Остались в игре:</i>\n{remaining_players_text}"
        )
        # --- КОНЕЦ ИЗМЕНЕНИЯ 8 ---
        
        await bot.edit_message_text(
            chat_id=game.chat_id,
            message_id=game.message_id,
            text=text,
            parse_mode='HTML'
        )
        await asyncio.sleep(ROULETTE_TURN_DELAY_SECONDS)

    # Определение победителя
    winner = players_in_game[0]
    await db.update_user_beer_rating(winner.id, total_pot)

    # --- ИЗМЕНЕНИЕ 9: Текст победы (более эмоциональный) ---
    text = (
        f"<b>🍻 Рулетка остановилась! 🍻</b>\n\n"
        f"🏆 <b>{html.escape(winner.full_name)}</b> забирает весь банк!\n\n"
        f"<b>Выигрыш: +{total_pot} 🍺!</b>\n"
        f"<i>Поздравляем счастливчика!</i>"
    )
    # --- КОНЕЦ ИЗМЕНЕНИЯ 9 ---

    await bot.edit_message_text(
        chat_id=game.chat_id,
        message_id=game.message_id,
        text=text,
        parse_mode='HTML'
    )
    
    if game.chat_id in active_games:
        del active_games[game.chat_id]
