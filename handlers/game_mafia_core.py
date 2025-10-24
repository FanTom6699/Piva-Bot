# handlers/game_mafia_core.py
import asyncio
import random
import logging
from aiogram import Router, Bot, F, html
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest
from contextlib import suppress
from typing import Dict, List, Set, Any

from database import Database
from settings import SettingsManager
from .user_commands import active_games, GAME_ACTIVE_KEY # Для очистки игры в конце

mafia_game_router = Router()

# --- FSM (Главный) ---
class MafiaGameStates(StatesGroup):
    game_in_progress = State()      # Общее состояние игры (для модерации чата)
    awaiting_last_word = State()  # Состояние для убитого (ждем 30 сек)
    night_voting = State()        # Состояние для чата мафии

# --- CallbackData ---
class MafiaNightVoteCallbackData(CallbackData, prefix="mafia_vote"):
    action: str # 'kill', 'check', 'heal', 'self_heal'
    target_user_id: int = 0

# --- КОНСТАНТЫ РОЛЕЙ (чтобы не ошибиться в строках) ---
ROLE_MAFIA_LEADER = 'mafia_leader' # 🥤 Главарь
ROLE_MAFIA = 'mafia'               # 🥤 Трезвенник
ROLE_DETECTIVE = 'detective'       # 🕵️‍♂️ Бармен
ROLE_DOCTOR = 'doctor'             # 🩺 Похметолог
ROLE_CIVILIAN = 'civilian'         # 🍻 Любитель Пива

MAFIA_TEAM_ROLES = [ROLE_MAFIA_LEADER, ROLE_MAFIA]

# --- МАТРИЦА РОЛЕЙ (Как мы и договорились) ---
# 'l' - leader, 'm' - mafia, 'd' - detective, 'h' - doctor, 'c' - civilian
MAFIA_ROLES_MATRIX = {
    5:  {'l': 1, 'm': 0, 'd': 1, 'h': 1, 'c': 2},
    6:  {'l': 1, 'm': 1, 'd': 1, 'h': 1, 'c': 2},
    7:  {'l': 1, 'm': 1, 'd': 1, 'h': 1, 'c': 3},
    8:  {'l': 1, 'm': 2, 'd': 1, 'h': 1, 'c': 3},
    9:  {'l': 1, 'm': 2, 'd': 1, 'h': 1, 'c': 4},
    10: {'l': 1, 'm': 2, 'd': 1, 'h': 1, 'c': 5},
}

# --- ОПИСАНИЯ РОЛЕЙ (для ЛС) ---
ROLE_DESCRIPTIONS = {
    ROLE_MAFIA_LEADER: {
        "title": "🥤 Главарь Трезвенников",
        "description": ("Вы — тайный лидер Трезвенников. "
                        "Ваша цель — выгнать из бара всех Любителей Пива.\n\n"
                        "• Каждую ночь вы и ваша команда выбираете, кого 'пролить'.\n"
                        "• <b>Ваш голос — решающий!</b>\n"
                        "• Вы можете общаться с командой в этом чате, пока длится ночь.")
    },
    ROLE_MAFIA: {
        "title": "🥤 Трезвенник",
        "description": ("Вы — Трезвенник. "
                        "Ваша цель — помочь своему Главарю выгнать из бара всех Любителей Пива.\n\n"
                        "• Каждую ночь вы с командой выбираете, кого 'пролить'.\n"
                        "• Вы можете общаться с командой в этом чате, пока длится ночь.")
    },
    ROLE_DETECTIVE: {
        "title": "🕵️‍♂️ Бармен",
        "description": ("Вы — Бармен. "
                        "Ваша цель — вычислить всех Трезвенников.\n\n"
                        "• Каждую ночь вы можете 'протереть стаканы' (проверить) одного посетителя.\n"
                        "• Вы узнаете, Трезвенник он или нет (Главаря вы тоже видите как Трезвенника).")
    },
    ROLE_DOCTOR: {
        "title": "🩺 Похметолог",
        "description": ("Вы — Похметолог. "
                        "Ваша цель — спасти Любителей Пива от выгона.\n\n"
                        "• Каждую ночь вы можете 'дать лекарство' (спасти) одного игрока от нападения Трезвенников.\n"
                        "• <b>Вы можете спасти себя, но только 1 раз за игру.</b>")
    },
    ROLE_CIVILIAN: {
        "title": "🍻 Любитель Пива",
        "description": ("Вы — обычный Любитель Пива. "
                        "Ваша цель — найти и выгнать всех Трезвенников из бара.\n\n"
                        "• Днем участвуйте в обсуждении и голосуйте против подозрительных личностей.\n"
                        "• Постарайтесь не попасться Трезвенникам ночью!")
    }
}

# --- МЕНЕДЖЕР ИГРЫ (для хранения 'живых' данных) ---
class GameManager:
    """Хранит 'живые' данные текущей игры (голоса, таймеры)."""
    def __init__(self, chat_id: int, bot: Bot, db: Database, settings: SettingsManager):
        self.chat_id = chat_id
        self.bot = bot
        self.db = db
        self.settings = settings
        self.players: Dict[int, Dict[str, Any]] = {} # {user_id: {'role': '...', 'is_alive': True, 'name': '...'}}
        self.night_votes: Dict[str, Dict[int, int]] = { # {'kill': {voter_id: target_id}, 'heal': ..., 'check': ...}
            'kill': {}, 'heal': {}, 'check': {}
        }
        self.mafia_leader_id: int = 0
        self.night_timer_task: asyncio.Task = None

    async def load_players_from_db(self):
        """Загружает игроков из БД в self.players и находит Лидера."""
        players_data = await self.db.get_mafia_players(self.chat_id)
        for p in players_data:
            user_id = p[1]
            role = p[2]
            is_alive = bool(p[3])
            db_user = await self.db.get_user_by_id(user_id)
            name = db_user[0] if db_user else f"Игрок {user_id}"
            
            self.players[user_id] = {'role': role, 'is_alive': is_alive, 'name': html.quote(name)}
            
            if role == ROLE_MAFIA_LEADER:
                self.mafia_leader_id = user_id
                
    def get_alive_players(self, roles: List[str] = None) -> List[int]:
        """Возвращает user_id живых игроков, опционально фильтруя по ролям."""
        alive = []
        for user_id, data in self.players.items():
            if data['is_alive']:
                if roles is None: # Если роли не важны
                    alive.append(user_id)
                elif data['role'] in roles: # Если фильтруем по ролям
                    alive.append(user_id)
        return alive

# Словарь для хранения активных GameManager'ов
active_game_managers: Dict[int, GameManager] = {}


# --- ЯДРО ИГРЫ: РАЗДАЧА РОЛЕЙ ---
async def distribute_roles_and_start(chat_id: int, bot: Bot, db: Database, settings: SettingsManager, players: list):
    logging.info(f"[Mafia {chat_id}] Шаг 2: Раздача ролей...")
    
    player_count = len(players)
    player_ids = [p[1] for p in players] # p[1] это user_id
    random.shuffle(player_ids)
    
    roles_config = MAFIA_ROLES_MATRIX[player_count]
    roles_list = []
    roles_list.extend([ROLE_MAFIA_LEADER] * roles_config['l'])
    roles_list.extend([ROLE_MAFIA] * roles_config['m'])
    roles_list.extend([ROLE_DETECTIVE] * roles_config['d'])
    roles_list.extend([ROLE_DOCTOR] * roles_config['h'])
    roles_list.extend([ROLE_CIVILIAN] * roles_config['c'])
    random.shuffle(roles_list)
    
    assigned_roles = {} # {user_id: role_key}
    mafia_team_info = {} # {user_id: "Name (Role)"}
    
    player_names = {} # {user_id: first_name}
    for user_id in player_ids:
        db_user = await db.get_user_by_id(user_id)
        player_names[user_id] = html.quote(db_user[0]) if db_user else f"Игрок {user_id}"
        
    for i, user_id in enumerate(player_ids):
        role = roles_list[i]
        assigned_roles[user_id] = role
        if role in [ROLE_MAFIA, ROLE_MAFIA_LEADER]:
            role_name = "Главарь" if role == ROLE_MAFIA_LEADER else "Трезвенник"
            mafia_team_info[user_id] = f"{player_names[user_id]} (🥤 {role_name})"

    tasks = []
    
    for user_id, role in assigned_roles.items():
        tasks.append(
            db.update_mafia_player_role(chat_id, user_id, role)
        )

    for user_id, role in assigned_roles.items():
        role_data = ROLE_DESCRIPTIONS[role]
        text = f"<b>{role_data['title']}</b>\n\n{role_data['description']}"
        
        if role in [ROLE_MAFIA, ROLE_MAFIA_LEADER]:
            text += "\n\n<b>Ваша команда:</b>\n"
            for mafia_id, mafia_name in mafia_team_info.items():
                if mafia_id == user_id:
                    text += f"• <b>{mafia_name} (Вы)</b>\n"
                else:
                    text += f"• {mafia_name}\n"
                    
        tasks.append(
            bot.send_message(user_id, text, parse_mode="HTML")
        )

    try:
        await asyncio.gather(*tasks)
    except Exception as e:
        logging.error(f"[Mafia {chat_id}] Ошибка при рассылке ролей: {e}")
        pass 

    await db.update_mafia_game_status(chat_id, "night", day_count=1)

    game = await db.get_mafia_game(chat_id)
    message_id = game[1]
    
    with suppress(TelegramBadRequest):
        await bot.unpin_chat_message(chat_id, message_id)
    
    await bot.edit_message_text(
        ("🌙 <b>НАСТУПАЕТ НОЧЬ 1</b> 🌙\n\n"
         "Все роли розданы в ЛС! Бар погружается в тишину.\n"
         "Активные роли делают свой ход..."),
        chat_id, message_id,
        reply_markup=None 
    )
    
    logging.info(f"[Mafia {chat_id}] Роли розданы. Начинаем Ночь 1...")

    # 7. Вызываем следующую фазу
    await start_night_phase(chat_id, bot, db, settings, day_count=1)

# --- ЯДРО ИГРЫ: ФАЗА НОЧИ ---

async def generate_night_vote_keyboard(game: GameManager, player_role: str, user_id: int) -> InlineKeyboardMarkup:
    """Генерирует клавиатуру для ночного голосования в ЛС."""
    buttons = []
    
    if player_role in MAFIA_TEAM_ROLES:
        action = "kill"
        text = "🥤 Кого 'проливаем'?"
        # Мафия не может голосовать за своих
        targets = game.get_alive_players()
        mafia_team_ids = game.get_alive_players(MAFIA_TEAM_ROLES)
        targets = [pid for pid in targets if pid not in mafia_team_ids]
    
    elif player_role == ROLE_DETECTIVE:
        action = "check"
        text = "🕵️‍♂️ Кого проверяем?"
        # Детектив не может проверять себя
        targets = [pid for pid in game.get_alive_players() if pid != user_id]
        
    elif player_role == ROLE_DOCTOR:
        action = "heal"
        text = "🩺 Кого спасаем?"
        targets = game.get_alive_players() # Доктор может спасать себя
    
    else: return None # У Мирного нет кнопок
    
    for target_user_id in targets:
        target_name = game.players[target_user_id]['name']
        buttons.append([
            InlineKeyboardButton(
                text=target_name,
                callback_data=MafiaNightVoteCallbackData(action=action, target_user_id=target_user_id).pack()
            )
        ])
    
    # Добавляем кнопку "Спасти себя" для Доктора
    if player_role == ROLE_DOCTOR:
        player_data = await game.db.get_mafia_player(game.chat_id, user_id)
        self_heals_used = player_data[4] # self_heals_used
        
        if self_heals_used == 0:
            buttons.append([
                InlineKeyboardButton(
                    text="🛡️ Спасти СЕБЯ (Остался 1 раз)",
                    callback_data=MafiaNightVoteCallbackData(action="self_heal", target_user_id=user_id).pack()
                )
            ])
            
    if not buttons:
        return None # (например, мафии некого убивать)

    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def start_night_phase(chat_id: int, bot: Bot, db: Database, settings: SettingsManager, day_count: int):
    """
    Запускает ночную фазу:
    1. Создает GameManager.
    2. Рассылает всем кнопки в ЛС.
    3. Включает FSM для чата мафии.
    4. Запускает ночной таймер.
    """
    logging.info(f"[Mafia {chat_id}] Ночь {day_count} началась.")
    
    # 1. Создаем Менеджер Игры
    game = GameManager(chat_id, bot, db, settings)
    await game.load_players_from_db()
    active_game_managers[chat_id] = game # Сохраняем его

    # 2. Рассылаем кнопки и включаем FSM
    tasks = []
    alive_players = game.get_alive_players()
    
    for user_id in alive_players:
        role = game.players[user_id]['role']
        
        # Генерируем кнопки
        keyboard = await generate_night_vote_keyboard(game, role, user_id)
        
        if keyboard:
            tasks.append(
                bot.send_message(user_id, "Выберите ваш ход:", reply_markup=keyboard)
            )
        
        # Включаем FSM для чата мафии
        if role in MAFIA_TEAM_ROLES:
            fsm_context = FSMContext(bot, user_id=user_id, chat_id=user_id)
            tasks.append(
                fsm_context.set_state(MafiaGameStates.night_voting)
            )
            
    await asyncio.gather(*tasks)

    # 3. (ЗАГЛУШКА) Запускаем ночной таймер
    # task = asyncio.create_task(night_timer_task(game))
    # game.night_timer_task = task
    
    # --- (ВРЕМЕННАЯ ЗАГЛУШКА) ---
    # (Пока нет таймера, просто ждем 15 сек и завершаем игру)
    await asyncio.sleep(15)
    logging.warning(f"[Mafia {chat_id}] ВРЕМЕННАЯ ЗАГЛУШКА: Ночь закончилась.")
    if chat_id in active_games:
        del active_games[chat_id]
    if chat_id in active_game_managers:
        del active_game_managers[chat_id]
    await db.delete_mafia_game(chat_id)
    await bot.send_message(chat_id, "<i>(ВРЕМЕННАЯ ЗАГЛУШКА: Ночь 1 завершена. Игра окончена.)</i>")
    # --- (КОНЕЦ ЗАГЛУШКИ) ---


# --- ХЭНДЛЕРЫ НОЧНОЙ ФАЗЫ ---

@mafia_game_router.callback_query(MafiaNightVoteCallbackData.filter(), StateFilter("*"))
async def cq_mafia_night_vote(callback: CallbackQuery, callback_data: MafiaNightVoteCallbackData, bot: Bot):
    """
    Обрабатывает ВСЕ ночные голоса (убийство, проверка, лечение).
    """
    chat_id = callback.message.chat.id # Это ЛС, но нам нужен ID игры
    user_id = callback.from_user.id
    
    # Находим ID игры (это хак, т.к. колбэк приходит из ЛС)
    # Нам нужно найти, в какой игре состоит этот user_id
    game_id = None
    game_manager = None
    for chat_id_key, game in active_game_managers.items():
        if user_id in game.players:
            game_id = chat_id_key
            game_manager = game
            break
            
    if not game_manager:
        await callback.answer("Не удалось найти вашу активную игру.", show_alert=True)
        return

    # Проверяем, жив ли игрок
    if not game_manager.players[user_id]['is_alive']:
        await callback.answer("Мертвые не голосуют.", show_alert=True)
        return

    action = callback_data.action
    target_user_id = callback_data.target_user_id
    target_name = game_manager.players[target_user_id]['name']
    
    # 1. Обработка голоса Мафии
    if action == "kill":
        game_manager.night_votes['kill'][user_id] = target_user_id
        await callback.message.edit_text(f"✅ Ваш голос принят: 'пролить' <b>{target_name}</b>.", parse_mode="HTML")
        
        # --- Анонс для команды мафии ---
        voter_name = game_manager.players[user_id]['name']
        tasks = []
        for mafia_id in game_manager.get_alive_players(MAFIA_TEAM_ROLES):
            if mafia_id != user_id: # Не отправляем самому себе
                tasks.append(
                    bot.send_message(mafia_id, f"🗳️ *{voter_name}* предлагает выгнать *{target_name}*.")
                )
        await asyncio.gather(*tasks)

    # 2. Обработка хода Детектива
    elif action == "check":
        game_manager.night_votes['check'][user_id] = target_user_id
        await callback.message.edit_text(f"✅ Вы решили проверить <b>{target_name}</b>. Ожидайте рассвета...", parse_mode="HTML")

    # 3. Обработка хода Доктора (обычное лечение)
    elif action == "heal":
        game_manager.night_votes['heal'][user_id] = target_user_id
        await callback.message.edit_text(f"✅ Вы решили спасти <b>{target_name}</b>. Ожидайте рассвета...", parse_mode="HTML")

    # 4. Обработка хода Доктора (самолечение)
    elif action == "self_heal":
        # Проверяем, не использовал ли он его уже (на всякий случай)
        player_data = await game_manager.db.get_mafia_player(game_id, user_id)
        if player_data[4] > 0:
             await callback.answer("Вы уже использовали самолечение!", show_alert=True)
             return
             
        # Записываем голос и обновляем БД
        game_manager.night_votes['heal'][user_id] = user_id
        await game_manager.db.set_mafia_player_self_heal(game_id, user_id) # (Нам нужна эта функция в DB)
        
        await callback.message.edit_text(
            f"✅ Вы использовали свое <b>единственное самолечение</b>. "
            f"Больше вы себя спасти не можете. Ожидайте рассвета...",
            parse_mode="HTML"
        )
    
    await callback.answer()


@mafia_game_router.message(MafiaGameStates.night_voting)
async def handle_mafia_chat(message: Message, bot: Bot, state: FSMContext):
    """
    Обрабатывает ТАЙНЫЙ ЧАТ Мафии.
    Пересылает сообщение всем живым членам команды.
    """
    user_id = message.from_user.id
    
    # 1. Находим игру
    game_id = None
    game_manager = None
    for chat_id_key, game in active_game_managers.items():
        if user_id in game.players:
            game_id = chat_id_key
            game_manager = game
            break
    if not game_manager: return

    # 2. Проверяем, жив ли
    if not game_manager.players[user_id]['is_alive']:
        await state.clear() # Мертвый не должен быть в этом FSM
        return
        
    # 3. Готовим и рассылаем сообщение
    role = game_manager.players[user_id]['role']
    prefix = "🥤 (Главарь)" if role == ROLE_MAFIA_LEADER else "🥤"
    sender_name = game_manager.players[user_id]['name']
    
    text_to_send = f"💬 <b>{sender_name} {prefix}:</b>\n{html.quote(message.text)}"
    
    tasks = []
    for mafia_id in game_manager.get_alive_players(MAFIA_TEAM_ROLES):
        if mafia_id != user_id: # Не отправляем самому себе
            tasks.append(
                bot.send_message(mafia_id, text_to_send, parse_mode="HTML")
            )
            
    await asyncio.gather(*tasks)


# --- ХЭНДЛЕРЫ МОДЕРАЦИИ ---

@mafia_game_router.message(StateFilter(MafiaGameStates.game_in_progress))
async def handle_game_moderation(message: Message, bot: Bot):
    """
    УДАЛЯЕТ все сообщения в группе, пока идет игра.
    (Этот хэндлер будет работать, только если мы включим FSM для *чата*)
    
    ПЛАН Б: Если FSM для чата не сработает, мы будем использовать
    проверку 'if chat_id in active_game_managers'
    """
    pass # (Пока заглушка)


@mafia_game_router.message(F.chat.type.in_({'group', 'supergroup'}))
async def handle_game_moderation_global(message: Message, bot: Bot):
    """
    УДАЛЯЕТ все сообщения в группе, пока идет игра.
    (Проверяет по словарю 'active_game_managers')
    """
    chat_id = message.chat.id
    if chat_id in active_game_managers:
        game_status = (await active_game_managers[chat_id].db.get_mafia_game(chat_id))[3]
        
        # --- МОДЕРАЦИЯ НОЧИ ---
        if game_status.startswith('night'):
            with suppress(TelegramBadRequest):
                await message.delete()
            # (Тут можно добавить логику мута за повтор)
            
        # --- МОДЕРАЦИЯ ДНЯ (Обсуждение) ---
        elif game_status.startswith('day') and message.content_type != 'text':
             with suppress(TelegramBadRequest):
                await message.delete()
        
        # --- МОДЕРАЦИЯ ДНЯ (Голосование) ---
        elif game_status.startswith('vote'):
            game = active_game_managers[chat_id]
            if not game.players[message.from_user.id]['is_alive']:
                 with suppress(TelegramBadRequest):
                    await message.delete() # Удаляем мертвых
            elif message.content_type != 'text':
                 with suppress(TelegramBadRequest):
                    await message.delete() # Удаляем медиа
