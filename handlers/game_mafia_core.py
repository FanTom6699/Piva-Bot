# handlers/game_mafia_core.py
import asyncio
import random
import logging
from aiogram import Router, Bot, F, html
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ChatPermissions
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest
from contextlib import suppress
from typing import Dict, List, Set, Any
from collections import Counter

from database import Database
from settings import SettingsManager
from utils import format_time_left
from .user_commands import active_games, GAME_ACTIVE_KEY # Для очистки игры в конце

mafia_game_router = Router()

# --- FSM (Главный) ---
class MafiaGameStates(StatesGroup):
    game_in_progress = State()
    awaiting_last_word = State()  # Состояние для убитого (ждем 30 сек)
    night_voting = State()        # Состояние для чата мафии
    # (FSM для дня пока не нужны, модерация идет по статусу в БД)


# --- CallbackData ---
class MafiaNightVoteCallbackData(CallbackData, prefix="mafia_vote"):
    action: str # 'kill', 'check', 'heal', 'self_heal'
    target_user_id: int = 0

class MafiaDayVoteCallbackData(CallbackData, prefix="mafia_day_vote"):
    action: str # 'nominate'
    target_user_id: int = 0
    
class MafiaLynchVoteCallbackData(CallbackData, prefix="mafia_lynch"):
    action: str # 'lynch', 'pardon'


# --- КОНСТАНТЫ РОЛЕЙ (чтобы не ошибиться в строках) ---
ROLE_MAFIA_LEADER = 'mafia_leader' # 🥤 Главарь
ROLE_MAFIA = 'mafia'               # 🥤 Трезвенник
ROLE_DETECTIVE = 'detective'       # 🕵️‍♂️ Бармен
ROLE_DOCTOR = 'doctor'             # 🩺 Похметолог
ROLE_CIVILIAN = 'civilian'         # 🍻 Любитель Пива

MAFIA_TEAM_ROLES = [ROLE_MAFIA_LEADER, ROLE_MAFIA]
CIVILIAN_TEAM_ROLES = [ROLE_DETECTIVE, ROLE_DOCTOR, ROLE_CIVILIAN]
ACTIVE_NIGHT_ROLES = [ROLE_MAFIA_LEADER, ROLE_MAFIA, ROLE_DETECTIVE, ROLE_DOCTOR]

ROLE_NAMES_RU = {
    ROLE_MAFIA_LEADER: "🥤 Главарь Трезвенников",
    ROLE_MAFIA: "🥤 Трезвенник",
    ROLE_DETECTIVE: "🕵️‍♂️ Бармен",
    ROLE_DOCTOR: "🩺 Похметолог",
    ROLE_CIVILIAN: "🍻 Любитель Пива"
}


# --- МАТРИЦА РОЛЕЙ (Как мы и договорились) ---
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
        self.day_count = 0
        self.players: Dict[int, Dict[str, Any]] = {} # {user_id: {'role': '...', 'is_alive': True, 'name': '...'}}
        # Ночь
        self.night_votes: Dict[str, Dict[int, int]] = {'kill': {}, 'heal': {}, 'check': {}}
        self.night_voted_users: Set[int] = set()
        self.mafia_leader_id: int = 0
        self.night_timer_task: asyncio.Task = None
        # День
        self.day_timer_task: asyncio.Task = None
        self.last_word_task: asyncio.Task = None
        self.day_votes_nominations: Dict[int, int] = {} # {voter_id: target_id}
        self.day_vote_timer_task: asyncio.Task = None
        # Суд Линча
        self.lynch_candidate_id: int = 0
        self.day_votes_lynch: Dict[int, str] = {} # {voter_id: 'lynch'/'pardon'}
        self.lynch_vote_timer_task: asyncio.Task = None
        self.lynch_message_id: int = 0


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
            
            if role == ROLE_MAFIA_LEADER and is_alive:
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
    
    def get_player_name(self, user_id: int) -> str:
        """Возвращает имя игрока (с проверкой)."""
        if user_id in self.players:
            return self.players[user_id]['name']
        return "<i>Неизвестный</i>"

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

    await db.update_mafia_game_status(chat_id, "night_1", day_count=1)

    game_db = await db.get_mafia_game(chat_id)
    message_id = game_db[1]
    
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

    await start_night_phase(chat_id, bot, db, settings, day_count=1)


# --- ЯДРО ИГРЫ: ФАЗА НОЧИ ---

async def night_timer_task(game: GameManager):
    """Таймер ночи. Ждет N секунд, затем запускает 'end_night_phase'."""
    await asyncio.sleep(game.settings.mafia_night_timer)
    
    if game.chat_id not in active_game_managers:
        logging.info(f"[Mafia {game.chat_id}] Таймер ночи: игра не найдена, отмена.")
        return
        
    logging.info(f"[Mafia {game.chat_id}] Ночной таймер истек. Подводим итоги...")
    
    tasks = []
    for user_id in game.get_alive_players(MAFIA_TEAM_ROLES):
        fsm_context = FSMContext(game.bot, user_id=user_id, chat_id=user_id)
        tasks.append(fsm_context.clear())
    await asyncio.gather(*tasks)
    
    await end_night_phase(game)


async def generate_night_vote_keyboard(game: GameManager, player_role: str, user_id: int) -> InlineKeyboardMarkup:
    """Генерирует клавиатуру для ночного голосования в ЛС."""
    buttons = []
    
    if player_role in MAFIA_TEAM_ROLES:
        action = "kill"
        targets = game.get_alive_players()
        mafia_team_ids = game.get_alive_players(MAFIA_TEAM_ROLES)
        targets = [pid for pid in targets if pid not in mafia_team_ids]
    
    elif player_role == ROLE_DETECTIVE:
        action = "check"
        targets = [pid for pid in game.get_alive_players() if pid != user_id]
        
    elif player_role == ROLE_DOCTOR:
        action = "heal"
        targets = game.get_alive_players() 
    
    else: return None 
    
    for target_user_id in targets:
        target_name = game.players[target_user_id]['name']
        buttons.append([
            InlineKeyboardButton(
                text=target_name,
                callback_data=MafiaNightVoteCallbackData(action=action, target_user_id=target_user_id).pack()
            )
        ])
    
    if player_role == ROLE_DOCTOR:
        player_data = await game.db.get_mafia_player(game.chat_id, user_id)
        self_heals_used = player_data[4]
        
        if self_heals_used == 0:
            buttons.append([
                InlineKeyboardButton(
                    text="🛡️ Спасти СЕБЯ (Остался 1 раз)",
                    callback_data=MafiaNightVoteCallbackData(action="self_heal", target_user_id=user_id).pack()
                )
            ])
            
    if not buttons:
        return None 

    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def start_night_phase(chat_id: int, bot: Bot, db: Database, settings: SettingsManager, day_count: int):
    """Запускает ночную фазу."""
    logging.info(f"[Mafia {chat_id}] Ночь {day_count} началась.")
    await db.update_mafia_game_status(chat_id, f"night_{day_count}", day_count=day_count)
    
    # Сбрасываем старый менеджер, если он был, и создаем новый
    if chat_id in active_game_managers:
        del active_game_managers[chat_id]
        
    game = GameManager(chat_id, bot, db, settings)
    game.day_count = day_count
    await game.load_players_from_db()
    active_game_managers[chat_id] = game 

    tasks = []
    alive_players = game.get_alive_players()
    
    # Сообщение в чат
    game_db = await db.get_mafia_game(chat_id)
    message_id = game_db[1] # Cообщение, которое было лобби
    
    with suppress(TelegramBadRequest):
        await bot.edit_message_text(
            f"🌙 <b>НАСТУПАЕТ НОЧЬ {day_count}</b> 🌙\n\n"
            "Бар погружается в тишину. Активные роли делают свой ход...",
            chat_id, message_id,
            reply_markup=None 
        )
    
    for user_id in alive_players:
        role = game.players[user_id]['role']
        
        keyboard = await generate_night_vote_keyboard(game, role, user_id)
        
        if keyboard:
            tasks.append(
                bot.send_message(user_id, "Выберите ваш ход:", reply_markup=keyboard)
            )
        
        if role in MAFIA_TEAM_ROLES:
            fsm_context = FSMContext(bot, user_id=user_id, chat_id=user_id)
            tasks.append(
                fsm_context.set_state(MafiaGameStates.night_voting)
            )
            
    await asyncio.gather(*tasks)

    task = asyncio.create_task(night_timer_task(game))
    game.night_timer_task = task


# --- ХЭНДЛЕРЫ НОЧНОЙ ФАЗЫ ---

@mafia_game_router.callback_query(MafiaNightVoteCallbackData.filter(), StateFilter("*"))
async def cq_mafia_night_vote(callback: CallbackQuery, callback_data: MafiaNightVoteCallbackData, bot: Bot):
    user_id = callback.from_user.id
    
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

    if not game_manager.players[user_id]['is_alive']:
        await callback.answer("Мертвые не голосуют.", show_alert=True)
        return
        
    if not game_manager.night_timer_task or game_manager.night_timer_task.done():
        await callback.answer("Ночь уже закончилась, ваш голос не принят.", show_alert=True)
        return

    action = callback_data.action
    target_user_id = callback_data.target_user_id
    target_name = game_manager.get_player_name(target_user_id)
    
    await game_manager.db.reset_mafia_player_inactive(game_id, user_id)
    game_manager.night_voted_users.add(user_id)
    
    if action == "kill":
        game_manager.night_votes['kill'][user_id] = target_user_id
        await callback.message.edit_text(f"✅ Ваш голос принят: 'пролить' <b>{target_name}</b>.", parse_mode="HTML")
        
        voter_name = game_manager.get_player_name(user_id)
        tasks = []
        for mafia_id in game_manager.get_alive_players(MAFIA_TEAM_ROLES):
            if mafia_id != user_id: 
                tasks.append(
                    bot.send_message(mafia_id, f"🗳️ *{voter_name}* предлагает выгнать *{target_name}*.")
                )
        await asyncio.gather(*tasks)

    elif action == "check":
        game_manager.night_votes['check'][user_id] = target_user_id
        await callback.message.edit_text(f"✅ Вы решили проверить <b>{target_name}</b>. Ожидайте рассвета...", parse_mode="HTML")

    elif action == "heal":
        game_manager.night_votes['heal'][user_id] = target_user_id
        await callback.message.edit_text(f"✅ Вы решили спасти <b>{target_name}</b>. Ожидайте рассвета...", parse_mode="HTML")

    elif action == "self_heal":
        player_data = await game_manager.db.get_mafia_player(game_id, user_id)
        if player_data[4] > 0:
             await callback.answer("Вы уже использовали самолечение!", show_alert=True)
             return
             
        game_manager.night_votes['heal'][user_id] = user_id
        await game_manager.db.set_mafia_player_self_heal(game_id, user_id)
        
        await callback.message.edit_text(
            f"✅ Вы использовали свое <b>единственное самолечение</b>. "
            f"Больше вы себя спасти не можете. Ожидайте рассвета...",
            parse_mode="HTML"
        )
    
    await callback.answer()


@mafia_game_router.message(MafiaGameStates.night_voting)
async def handle_mafia_chat(message: Message, bot: Bot, state: FSMContext):
    user_id = message.from_user.id
    
    game_id = None
    game_manager = None
    for chat_id_key, game in active_game_managers.items():
        if user_id in game.players:
            game_id = chat_id_key
            game_manager = game
            break
    if not game_manager: return

    if not game_manager.players[user_id]['is_alive']:
        await state.clear() 
        return
        
    role = game_manager.players[user_id]['role']
    prefix = "🥤 (Главарь)" if role == ROLE_MAFIA_LEADER else "🥤"
    sender_name = game_manager.get_player_name(user_id)
    
    text_to_send = f"💬 <b>{sender_name} {prefix}:</b>\n{html.quote(message.text)}"
    
    tasks = []
    for mafia_id in game_manager.get_alive_players(MAFIA_TEAM_ROLES):
        if mafia_id != user_id: 
            tasks.append(
                bot.send_message(mafia_id, text_to_send, parse_mode="HTML")
            )
            
    await asyncio.gather(*tasks)


# --- ЯДРО ИГРЫ: ФАЗА УТРА ---

async def end_night_phase(game: GameManager):
    """Подводит итоги ночи."""
    chat_id = game.chat_id
    logging.info(f"[Mafia {chat_id}] Подведение итогов ночи...")
    
    mafia_kill_target = None
    doctor_save_target = None
    detective_check_target = None
    detective_id = None
    
    mafia_votes = game.night_votes['kill']
    
    if game.mafia_leader_id in mafia_votes:
        mafia_kill_target = mafia_votes[game.mafia_leader_id]
    
    elif mafia_votes:
        vote_counts = Counter(mafia_votes.values())
        most_voted = vote_counts.most_common(1)
        
        if len(most_voted) > 0:
            top_target, top_count = most_voted[0]
            is_tie = sum(1 for target, count in vote_counts.items() if count == top_count) > 1
            if not is_tie:
                mafia_kill_target = top_target

    doctor_votes = game.night_votes['heal']
    if doctor_votes:
        doctor_save_target = list(doctor_votes.values())[0]
        
    detective_votes = game.night_votes['check']
    if detective_votes:
        detective_id = list(detective_votes.keys())[0]
        detective_check_target = list(detective_votes.values())[0]
        
    afk_kicked_players = []
    
    all_active_players = await game.db.get_mafia_players_by_role(chat_id, ACTIVE_NIGHT_ROLES, is_alive=True)
    
    for p_data in all_active_players:
        user_id = p_data[1]
        role = p_data[2]
        inactive_count = p_data[5] # inactive_nights_count
        
        if user_id not in game.night_voted_users:
            await game.db.increment_mafia_player_inactive(chat_id, user_id)
            
            if inactive_count + 1 >= 2:
                await game.db.set_mafia_player_alive(chat_id, user_id, is_alive=False)
                game.players[user_id]['is_alive'] = False
                afk_kicked_players.append(user_id)
                logging.info(f"[Mafia {chat_id}] Игрок {user_id} ({role}) кикнут за АФК.")

    final_killed_user_id = None
    was_saved = False
    
    if mafia_kill_target:
        if mafia_kill_target == doctor_save_target:
            was_saved = True
            logging.info(f"[Mafia {chat_id}] Доктор спас {mafia_kill_target}.")
        else:
            final_killed_user_id = mafia_kill_target
            await game.db.set_mafia_player_alive(chat_id, final_killed_user_id, is_alive=False)
            game.players[final_killed_user_id]['is_alive'] = False
            logging.info(f"[Mafia {chat_id}] Мафия убила {final_killed_user_id}.")

    if detective_check_target:
        target_role = game.players[detective_check_target]['role']
        is_mafia = target_role in MAFIA_TEAM_ROLES
        
        check_result_text = f"🕵️‍♂️ Вы проверили <b>{game.get_player_name(detective_check_target)}</b>.\n"
        if is_mafia:
            check_result_text += "<b>Он(а) — 🥤 Трезвенник!</b>"
        else:
            check_result_text += "Он(а) не Трезвенник."
            
        with suppress(TelegramBadRequest):
            await game.bot.send_message(detective_id, check_result_text, parse_mode="HTML")
            
    # Проверяем победу
    if await check_for_win_condition(game):
        return # (Функция check_for_win_condition сама завершит игру)

    await start_morning_phase(game, final_killed_user_id, was_saved, afk_kicked_players)


async def start_morning_phase(game: GameManager, killed_user_id: int, was_saved: bool, afk_kicked_players: List[int]):
    """Формирует утренний отчет и запускает "Последнее слово" или "День"."""
    chat_id = game.chat_id
    day_count = game.day_count
    
    report = f"☀️ <b>Утро в Баре (День {day_count})</b> ☀️\n\n"
    
    if afk_kicked_players:
        for user_id in afk_kicked_players:
            name = game.get_player_name(user_id)
            role_key = game.players[user_id]['role']
            role_name = ROLE_NAMES_RU.get(role_key, "Неизвестный")
            report += f"😴 *{name}* был(а) изгнан(а) из бара за бездействие! Он(а) был(а)... **{role_name}**!\n"
        report += "\n"

    if killed_user_id:
        name = game.get_player_name(killed_user_id)
        role_key = game.players[killed_user_id]['role']
        role_name = ROLE_NAMES_RU.get(role_key, "Неизвестный")
        report += f"Этой ночью Трезвенники выгнали <b>{name}</b>.\n"
        report += f"Он(а) был(а)... <b>{role_name}</b>!\n"
        
    elif was_saved:
        report += "Этой ночью Трезвенники напали, но 🩺 <b>Похметолог</b> успел(а) спасти жертву!\n"
    else:
        report += "Эта ночь прошла спокойно. Никто не был выгнан.\n"
        
    report += "\n---\n<b>Живые игроки:</b>\n"
    alive_players = game.get_alive_players()
    for i, user_id in enumerate(alive_players):
        report += f"{i+1}. {game.get_player_name(user_id)}\n"
        
    await game.bot.send_message(chat_id, report, parse_mode="HTML")
    
    if killed_user_id:
        task = asyncio.create_task(last_word_task(game, killed_user_id))
        game.last_word_task = task
    else:
        await start_day_discussion(game)


async def last_word_task(game: GameManager, killed_user_id: int):
    """Дает 30 секунд на последнее слово и запускает день."""
    try:
        fsm_context = FSMContext(game.bot, user_id=killed_user_id, chat_id=killed_user_id)
        await fsm_context.set_state(MafiaGameStates.awaiting_last_word)
        await game.bot.send_message(killed_user_id, "У вас есть <b>30 секунд</b> на последнее слово. Напишите его в этот чат.", parse_mode="HTML")
    except Exception as e:
        logging.warning(f"[Mafia {game.chat_id}] Не удалось отправить запрос на 'последнее слово' игроку {killed_user_id}: {e}")
        await start_day_discussion(game)
        return

    await asyncio.sleep(30)
    
    if game.chat_id not in active_game_managers:
        return
        
    with suppress(Exception):
        await fsm_context.clear()
        
    await start_day_discussion(game)

# --- ХЭНДЛЕР: ЛОВИТ ПОСЛЕДНЕЕ СЛОВО ---
@mafia_game_router.message(MafiaGameStates.awaiting_last_word)
async def handle_last_word(message: Message, bot: Bot, state: FSMContext):
    user_id = message.from_user.id
    
    game_id = None
    game_manager = None
    for chat_id_key, game in active_game_managers.items():
        if user_id in game.players:
            game_id = chat_id_key
            game_manager = game
            break
    if not game_manager: return
    
    await state.clear()
    
    name = game_manager.get_player_name(user_id)
    text = html.quote(message.text[:200]) # Ограничим длину
    
    await bot.send_message(game_id, f"📣 <b>{name}</b> крикнул(а) перед смертью:\n<i>«{text}»</i>", parse_mode="HTML")
    
    if game_manager.last_word_task and not game_manager.last_word_task.done():
        game_manager.last_word_task.cancel()
        await start_day_discussion(game_manager) # Запускаем день немедленно
    

# --- ЯДРО ИГРЫ: ФАЗА ДНЯ (Обсуждение) ---

async def day_timer_task(game: GameManager):
    """Таймер дневного обсуждения."""
    await asyncio.sleep(game.settings.mafia_day_timer)
    
    if game.chat_id not in active_game_managers:
        return
        
    logging.info(f"[Mafia {game.chat_id}] Время обсуждения вышло. Начинаем номинацию.")
    
    await start_day_vote_nominating(game)


async def start_day_discussion(game: GameManager):
    """Запускает фазу Дня ("Только Текст")."""
    chat_id = game.chat_id
    day_count = game.day_count
    
    await game.db.update_mafia_game_status(chat_id, f"day_discussion_{day_count}")
    
    time_str = format_time_left(game.settings.mafia_day_timer)
    await game.bot.send_message(
        chat_id,
        f"☀️ <b>Начинается обсуждение! (День {day_count})</b> ☀️\n\n"
        f"У вас есть <b>{time_str}</b>, чтобы обсудить, кто Трезвенник.\n"
        f"В чате включен режим <b>'Только Текст'</b> (GIF, стикеры и медиа запрещены).",
        parse_mode="HTML"
    )
    
    task = asyncio.create_task(day_timer_task(game))
    game.day_timer_task = task


# --- ЯДРО ИГРЫ: ФАЗА ДНЯ (Номинация) ---

async def day_vote_timer_task(game: GameManager):
    """Таймер голосования (Номинации)."""
    await asyncio.sleep(game.settings.mafia_vote_timer)
    
    if game.chat_id not in active_game_managers:
        return
        
    logging.info(f"[Mafia {game.chat_id}] Время номинации вышло. Подсчет голосов...")
    
    await end_day_vote_nominating(game)
    

async def end_day_vote_nominating(game: GameManager):
    """
    Подсчитывает голоса номинации.
    Если есть 1 кандидат (>1 голоса, нет ничьи) -> запускает Суд Линча.
    Иначе -> пропускает голосование и запускает Ночь.
    """
    chat_id = game.chat_id
    logging.info(f"[Mafia {chat_id}] Подсчет голосов номинации...")
    
    votes = game.day_votes_nominations
    if not votes:
        await game.bot.send_message(chat_id, "⚖️ Никто не голосовал. Суд Линча отменяется. Наступает ночь.")
        await start_night_phase(game.chat_id, game.bot, game.db, game.settings, game.day_count + 1)
        return

    vote_counts = Counter(votes.values())
    most_voted = vote_counts.most_common(2) 

    if not most_voted or most_voted[0][1] == 1: 
        await game.bot.send_message(chat_id, "⚖️ Ни один кандидат не набрал достаточного числа голосов ( > 1). Суд Линча отменяется. Наступает ночь.")
        await start_night_phase(game.chat_id, game.bot, game.db, game.settings, game.day_count + 1)
        return
        
    candidate_id, top_count = most_voted[0]
    
    if len(most_voted) > 1 and most_voted[1][1] == top_count:
        await game.bot.send_message(chat_id, "⚖️ Голоса разделились. Суд Линча отменяется. Наступает ночь.")
        await start_night_phase(game.chat_id, game.bot, game.db, game.settings, game.day_count + 1)
        return

    game.lynch_candidate_id = candidate_id
    await start_day_vote_lynching(game)


async def generate_day_nominate_keyboard(game: GameManager, voter_user_id: int) -> InlineKeyboardMarkup:
    """Генерирует кнопки для номинации в ЛС."""
    buttons = []
    
    targets = [pid for pid in game.get_alive_players() if pid != voter_user_id]
    
    for target_user_id in targets:
        target_name = game.get_player_name(target_user_id)
        buttons.append([
            InlineKeyboardButton(
                text=target_name,
                callback_data=MafiaDayVoteCallbackData(action="nominate", target_user_id=target_user_id).pack()
            )
        ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def start_day_vote_nominating(game: GameManager):
    """
    Запускает фазу Номинации ("Полная Тишина").
    Рассылает кнопки в ЛС.
    Запускает таймер голосования.
    """
    chat_id = game.chat_id
    day_count = game.day_count
    
    await game.db.update_mafia_game_status(chat_id, f"day_vote_nominate_{day_count}")
    
    time_str = format_time_left(game.settings.mafia_vote_timer)
    await game.bot.send_message(
        chat_id,
        f"⚖️ <b>Обсуждение закончено!</b> ⚖️\n\n"
        f"Начинается <b>Номинация</b>. У вас есть <b>{time_str}</b>, чтобы проголосовать в ЛС.\n"
        f"В чате включен режим <b>'Полной Тишины'</b>.",
        parse_mode="HTML"
    )
    
    tasks = []
    alive_players = game.get_alive_players()
    for user_id in alive_players:
        keyboard = await generate_day_nominate_keyboard(game, user_id)
        tasks.append(
            game.bot.send_message(user_id, "Кого вы номинируете на выгон?", reply_markup=keyboard)
        )
        
    await asyncio.gather(*tasks)
    
    task = asyncio.create_task(day_vote_timer_task(game))
    game.day_vote_timer_task = task


# --- ХЭНДЛЕР: ЛОВИТ ГОЛОС НОМИНАЦИИ ---
@mafia_game_router.callback_query(MafiaDayVoteCallbackData.filter(F.action == "nominate"), StateFilter("*"))
async def cq_mafia_day_vote_nominate(callback: CallbackQuery, callback_data: MafiaDayVoteCallbackData, bot: Bot):
    user_id = callback.from_user.id
    
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

    if not game_manager.players[user_id]['is_alive']:
        await callback.answer("Мертвые не голосуют.", show_alert=True)
        return
        
    if not game_manager.day_vote_timer_task or game_manager.day_vote_timer_task.done():
        await callback.answer("Время голосования вышло, ваш голос не принят.", show_alert=True)
        return

    action = callback_data.action
    target_user_id = callback_data.target_user_id
    target_name = game_manager.get_player_name(target_user_id)
    
    game_manager.day_votes_nominations[user_id] = target_user_id
    
    await callback.message.edit_text(f"✅ Вы номинировали на выгон: <b>{target_name}</b>.", parse_mode="HTML")
    await callback.answer()


# --- ЯДРО ИГРЫ: ФАЗА ДНЯ (Суд Линча) ---

async def lynch_vote_timer_task(game: GameManager):
    """Таймер Суда Линча."""
    await asyncio.sleep(game.settings.mafia_vote_timer)
    
    if game.chat_id not in active_game_managers:
        return
        
    logging.info(f"[Mafia {game.chat_id}] Время Суда Линча вышло. Подсчет...")
    
    # (ЗАГЛУШКА УБРАНА)
    await end_day_vote_lynching(game)
    
    
async def end_day_vote_lynching(game: GameManager):
    """
    Подсчитывает голоса Суда Линча.
    Выгоняет игрока (если > 50% "За").
    Проверяет победу.
    Запускает Ночь.
    """
    chat_id = game.chat_id
    candidate_id = game.lynch_candidate_id
    candidate_name = game.get_player_name(candidate_id)
    
    # 1. Убираем кнопки
    with suppress(TelegramBadRequest):
        await game.bot.edit_message_reply_markup(chat_id, game.lynch_message_id, reply_markup=None)
        
    # 2. Считаем голоса
    votes = game.day_votes_lynch.values()
    lynch_votes = sum(1 for v in votes if v == 'lynch')
    pardon_votes = sum(1 for v in votes if v == 'pardon')
    total_votes = lynch_votes + pardon_votes
    
    # (Для ничьи: lynch_votes == pardon_votes -> помилован)
    # (Для победы: lynch_votes > pardon_votes)
    
    is_lynched = lynch_votes > pardon_votes
    
    if is_lynched:
        logging.info(f"[Mafia {chat_id}] Игрок {candidate_id} выгнан Судом Линча.")
        # "Убиваем" игрока
        await game.db.set_mafia_player_alive(chat_id, candidate_id, is_alive=False)
        game.players[candidate_id]['is_alive'] = False
        
        role_key = game.players[candidate_id]['role']
        role_name = ROLE_NAMES_RU.get(role_key, "Неизвестный")
        
        await game.bot.send_message(
            chat_id,
            f"⚖️ <b>Приговор вынесен!</b> ⚖️\n\n"
            f"Игрок <b>{candidate_name}</b> был(а) изгнан(а) из бара! ({lynch_votes} ⬆️ vs {pardon_votes} ⬇️)\n"
            f"Он(а) был(а)... <b>{role_name}</b>!",
            parse_mode="HTML"
        )
    else:
        logging.info(f"[Mafia {chat_id}] Игрок {candidate_id} помилован Судом Линча.")
        await game.bot.send_message(
            chat_id,
            f"⚖️ <b>Игрок помилован!</b> ⚖️\n\n"
            f"<b>{candidate_name}</b> остается в баре. ({lynch_votes} ⬆️ vs {pardon_votes} ⬇️)\n",
            parse_mode="HTML"
        )
        
    # 3. Проверяем победу (т.к. игрок мог умереть)
    if is_lynched:
        if await check_for_win_condition(game):
            return # Игра окончена
            
    # 4. Если игра не окончена, запускаем следующую ночь
    await start_night_phase(game.chat_id, game.bot, game.db, game.settings, game.day_count + 1)


async def start_day_vote_lynching(game: GameManager):
    """
    Запускает Суд Линча ("Только живые, Только Текст").
    Публикует кнопки в чат.
    Запускает таймер Суда Линча.
    """
    chat_id = game.chat_id
    day_count = game.day_count
    await game.db.update_mafia_game_status(chat_id, f"day_vote_lynch_{day_count}")
    
    candidate_name = game.get_player_name(game.lynch_candidate_id)
    time_str = format_time_left(game.settings.mafia_vote_timer)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=f"⚖️ Выгнать ({game.get_player_name(game.lynch_candidate_id)})", callback_data=MafiaLynchVoteCallbackData(action="lynch").pack()),
            InlineKeyboardButton(text="🕊️ Помиловать", callback_data=MafiaLynchVoteCallbackData(action="pardon").pack())
        ]
    ])
    
    msg = await game.bot.send_message(
        chat_id,
        f"⚖️ <b>СУД ЛИНЧА</b> ⚖️\n\n"
        f"На выгон номинирован: <b>{candidate_name}</b>\n"
        f"Все живые игроки, решите его(ее) судьбу. У вас <b>{time_str}</b>.\n"
        f"В чате режим: <b>'Только живые, только текст'</b>.",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    game.lynch_message_id = msg.message_id # Сохраняем ID, чтобы убрать кнопки
    
    task = asyncio.create_task(lynch_vote_timer_task(game))
    game.lynch_vote_timer_task = task


# --- ХЭНДЛЕР: ЛОВИТ ГОЛОС СУДА ЛИНЧА ---
@mafia_game_router.callback_query(MafiaLynchVoteCallbackData.filter(), StateFilter("*"))
async def cq_mafia_day_vote_lynch(callback: CallbackQuery, callback_data: MafiaLynchVoteCallbackData, bot: Bot):
    user_id = callback.from_user.id
    
    game_id = None
    game_manager = None
    for chat_id_key, game in active_game_managers.items():
        if user_id in game.players:
            game_id = chat_id_key
            game_manager = game
            break
    if not game_manager:
        await callback.answer("Игра не найдена.", show_alert=True)
        return

    if not game_manager.players[user_id]['is_alive']:
        await callback.answer("Мертвые не голосуют.", show_alert=True)
        return
        
    if not game_manager.lynch_vote_timer_task or game_manager.lynch_vote_timer_task.done():
        await callback.answer("Время голосования вышло.", show_alert=True)
        return
    
    action = callback_data.action # 'lynch' or 'pardon'
    
    game_manager.day_votes_lynch[user_id] = action
    
    action_text = "ВЫГНАТЬ" if action == "lynch" else "ПОМИЛОВАТЬ"
    await callback.answer(f"Вы проголосовали: {action_text}")


# --- ЯДРО ИГРЫ: ПРОВЕРКА ПОБЕДЫ И ЗАВЕРШЕНИЕ ---

async def check_for_win_condition(game: GameManager) -> bool:
    """
    Проверяет, победила ли одна из команд.
    Если да, запускает 'cleanup_and_end_game' и возвращает True.
    Иначе False.
    """
    chat_id = game.chat_id
    
    # Обновляем состояние (т.к. кто-то мог умереть)
    alive_mafia = game.get_alive_players(MAFIA_TEAM_ROLES)
    alive_civilians = game.get_alive_players(CIVILIAN_TEAM_ROLES)
    
    mafia_count = len(alive_mafia)
    civilian_count = len(alive_civilians)
    
    winner = None # 'mafia' or 'civilians'
    
    if mafia_count == 0:
        winner = 'civilians'
    elif mafia_count >= civilian_count:
        winner = 'mafia'
        
    if winner:
        logging.info(f"[Mafia {chat_id}] Игра окончена! Победитель: {winner}")
        await cleanup_and_end_game(game, winner)
        return True
        
    return False

async def cleanup_and_end_game(game: GameManager, winner: str):
    """
    Завершает игру, чистит данные, начисляет награды.
    """
    chat_id = game.chat_id
    
    # 1. Отменяем все таймеры (на всякий случай)
    if game.night_timer_task: game.night_timer_task.cancel()
    if game.day_timer_task: game.day_timer_task.cancel()
    if game.last_word_task: game.last_word_task.cancel()
    if game.day_vote_timer_task: game.day_vote_timer_task.cancel()
    if game.lynch_vote_timer_task: game.lynch_vote_timer_task.cancel()
    
    # 2. Определяем победителей и проигравших
    winners = []
    losers = []
    
    win_team_roles = MAFIA_TEAM_ROLES if winner == 'mafia' else CIVILIAN_TEAM_ROLES
    
    for user_id, data in game.players.items():
        if data['role'] in win_team_roles:
            winners.append(user_id)
        else:
            losers.append(user_id)
            
    # 3. Готовим финальный отчет
    report = "🍻 <b>ИГРА ОКОНЧЕНА!</b> 🍻\n\n"
    if winner == 'mafia':
        report += "<b>Победила команда 🥤 Трезвенников!</b>\n"
    else:
        report += "<b>Победила команда 🍻 Любителей Пива!</b>\n"
        
    report += "\n<b>Состав команд:</b>\n"
    for user_id, data in game.players.items():
        role_name = ROLE_NAMES_RU.get(data['role'], "Неизвестный")
        report += f"• {game.get_player_name(user_id)} — {role_name}\n"
        
    # 4. Начисляем награды
    tasks = []
    report += "\n<b>Награды:</b>\n"
    
    # Победители
    win_reward = game.settings.mafia_win_reward
    win_auth = game.settings.mafia_win_authority
    for user_id in winners:
        tasks.append(game.db.change_rating(user_id, win_reward))
        tasks.append(game.db.update_mafia_stats(user_id, has_won=True, authority_change=win_auth))
        report += f"• {game.get_player_name(user_id)}: +{win_reward} 🍺, +{win_auth} 👑\n"

    # Проигравшие
    lose_reward = game.settings.mafia_lose_reward
    lose_auth = game.settings.mafia_lose_authority
    for user_id in losers:
        tasks.append(game.db.change_rating(user_id, lose_reward))
        tasks.append(game.db.update_mafia_stats(user_id, has_won=False, authority_change=lose_auth))
        report += f"• {game.get_player_name(user_id)}: +{lose_reward} 🍺, {lose_auth} 👑\n"
        
    await asyncio.gather(*tasks)
    
    # 5. Отправляем отчет
    await game.bot.send_message(chat_id, report, parse_mode="HTML")
    
    # 6. Чистим все
    await game.db.delete_mafia_game(chat_id)
    if chat_id in active_game_managers:
        del active_game_managers[chat_id]
    if chat_id in active_games:
        del active_games[chat_id]
    
    logging.info(f"[Mafia {chat_id}] Игра полностью завершена и очищена.")


# --- ХЭНДЛЕРЫ МОДЕРАЦИИ ---

@mafia_game_router.message(F.chat.type.in_({'group', 'supergroup'}))
async def handle_game_moderation_global(message: Message, bot: Bot):
    """
    УДАЛЯЕТ все сообщения в группе, пока идет игра.
    (Проверяет по словарю 'active_game_managers')
    """
    chat_id = message.chat.id
    if chat_id in active_game_managers:
        game = active_game_managers[chat_id] # Получаем менеджер
        game_status_row = await game.db.get_mafia_game(chat_id)
        if not game_status_row: return # Игра закончилась
        
        game_status = game_status_row[3] # status
        
        # --- МОДЕРАЦИЯ (ПОЛНАЯ ТИШИНA) ---
        # Ночь ИЛИ Номинация
        if game_status.startswith('night') or game_status.startswith('day_vote_nominate'):
            with suppress(TelegramBadRequest):
                await message.delete()
            return
            
        # --- МОДЕРАЦИЯ ДНЯ (Только Текст) ---
        if game_status.startswith('day_discussion'):
            if message.content_type != 'text':
                 with suppress(TelegramBadRequest):
                    await message.delete()
            return
        
        # --- МОДЕРАЦИЯ (Суд Линча: Только живые, Только Текст) ---
        if game_status.startswith('day_vote_lynch'):
            # Проверяем, жив ли игрок
            is_alive = message.from_user.id in game.players and game.players[message.from_user.id]['is_alive']
            
            if not is_alive:
                 with suppress(TelegramBadRequest):
                    await message.delete() # Удаляем мертвых и зрителей
            # Проверяем на медиа
            elif message.content_type != 'text':
                 with suppress(TelegramBadRequest):
                    await message.delete() # Удаляем медиа
            return
