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

from database import Database
from settings import SettingsManager
from .user_commands import active_games, GAME_ACTIVE_KEY # Для очистки игры в конце

mafia_game_router = Router()

# --- FSM (Мы переносим его сюда из 'lobby') ---
class MafiaGameStates(StatesGroup):
    game_in_progress = State()      # Общее состояние игры
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

# --- ЯДРО ИГРЫ: РАЗДАЧА РОЛЕЙ ---

async def distribute_roles_and_start(chat_id: int, bot: Bot, db: Database, settings: SettingsManager, players: list):
    """
    Вызывается из 'lobby' после всех проверок.
    Раздает роли, сохраняет в БД, пишет в ЛС и запускает Ночь 1.
    """
    logging.info(f"[Mafia {chat_id}] Шаг 2: Раздача ролей...")
    
    player_count = len(players)
    player_ids = [p[1] for p in players] # p[1] это user_id
    random.shuffle(player_ids)
    
    # 1. Генерируем список ролей
    roles_config = MAFIA_ROLES_MATRIX[player_count]
    roles_list = []
    roles_list.extend([ROLE_MAFIA_LEADER] * roles_config['l'])
    roles_list.extend([ROLE_MAFIA] * roles_config['m'])
    roles_list.extend([ROLE_DETECTIVE] * roles_config['d'])
    roles_list.extend([ROLE_DOCTOR] * roles_config['h'])
    roles_list.extend([ROLE_CIVILIAN] * roles_config['c'])
    random.shuffle(roles_list)
    
    # 2. Сопоставляем игроков и роли
    assigned_roles = {} # {user_id: role_key}
    mafia_team_info = {} # {user_id: "Name (Role)"}
    
    # Получаем имена из БД
    player_names = {} # {user_id: first_name}
    for user_id in player_ids:
        db_user = await db.get_user_by_id(user_id)
        player_names[user_id] = html.quote(db_user[0]) if db_user else f"Игрок {user_id}"
        
    # Сначала находим мафию, чтобы составить список
    for i, user_id in enumerate(player_ids):
        role = roles_list[i]
        assigned_roles[user_id] = role
        if role in [ROLE_MAFIA, ROLE_MAFIA_LEADER]:
            role_name = "Главарь" if role == ROLE_MAFIA_LEADER else "Трезвенник"
            mafia_team_info[user_id] = f"{player_names[user_id]} (🥤 {role_name})"

    # 3. Готовим задачи (Рассылка в ЛС + Запись в БД)
    tasks = []
    
    # Готовим задачи на запись в БД
    for user_id, role in assigned_roles.items():
        tasks.append(
            db.update_mafia_player_role(chat_id, user_id, role)
        )

    # Готовим задачи на рассылку в ЛС
    for user_id, role in assigned_roles.items():
        role_data = ROLE_DESCRIPTIONS[role]
        text = f"<b>{role_data['title']}</b>\n\n{role_data['description']}"
        
        # Добавляем список команды для Мафии
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

    # 4. Выполняем все задачи
    try:
        await asyncio.gather(*tasks)
    except Exception as e:
        # Эта ошибка не должна произойти, т.к. мы уже проверяли ЛС
        logging.error(f"[Mafia {chat_id}] Ошибка при рассылке ролей: {e}")
        # (В реальной ситуации здесь нужна очистка)
        pass 

    # 5. Обновляем статус игры
    await db.update_mafia_game_status(chat_id, "night", day_count=1)

    # 6. Обновляем сообщение в группе
    game = await db.get_mafia_game(chat_id)
    message_id = game[1]
    
    with suppress(TelegramBadRequest):
        await bot.unpin_chat_message(chat_id, message_id)
    
    await bot.edit_message_text(
        ("🌙 <b>НАСТУПАЕТ НОЧЬ 1</b> 🌙\n\n"
         "Все роли розданы в ЛС! Бар погружается в тишину.\n"
         "Активные роли делают свой ход..."),
        chat_id, message_id,
        reply_markup=None # Убираем кнопки лобби
    )
    
    logging.info(f"[Mafia {chat_id}] Роли розданы. Начинаем Ночь 1...")

    # 7. Вызываем следующую фазу (которую напишем в след. файле)
    # await start_night_phase(chat_id, bot, db, settings, 1)
