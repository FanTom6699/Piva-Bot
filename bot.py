# --- Стандартные библиотеки ---
import asyncio
import logging
import sqlite3
import os
import random
import time
from datetime import datetime, date, timedelta, time as dt_time
import html
import json
from typing import Callable, Dict, Any, Awaitable

# --- Сторонние библиотеки ---
from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from dotenv import load_dotenv
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from cachetools import TTLCache # Оставляем для ThrottlingMiddleware
from aiogram.client.default import DefaultBotProperties

# ИМПОРТ ДЛЯ GEMINI
import google.generativeai as genai
import google.ai.generativelanguage_v1beta as glm # Добавлено для явного указания типов

# --- Конфигурация ---
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

if not BOT_TOKEN:
    raise ValueError("Не найден BOT_TOKEN. Проверьте переменные окружения.")

DB_FILE = '/data/beer_game.db'
COOLDOWN_SECONDS = 3 * 60 * 60
THROTTLE_TIME = 0.5

WIN_CHANCE = 60
LOSE_CHANCE = 40

CARD_DRAW_COST = 15
CARD_COOLDOWN_SECONDS = 2 * 60 * 60

DAILY_BASE_COIN_BONUS = 20
DAILY_BASE_RATING_BONUS = 5
DAILY_STREAK_COIN_BONUSES = [0, 5, 10, 15, 20]
DAILY_MAX_STREAK_BONUS_INDEX = len(DAILY_STREAK_COIN_BONUSES) - 1

# --- File IDs для изображений (ЗАМЕНИТЕ ЭТИ ЗНАЧЕНИЯ НА ВАШИ РЕАЛЬНЫЕ ID!) ---
SUCCESS_IMAGE_ID = "AgACAgIAAxkBAAICvGjMNGhCINSBAeXyX9w0VddF-C8PAAJt8jEbFbVhSmh8gDAZrTCaAQADAgADeQADNgQ"
FAIL_IMAGE_ID = "AgACAgIAAxkBAAICwGjMNRAnAAHo1rDMPfaF_HUa0WzxaAACcvIxGxW1YUo5jEQQRkt4kgEAAwIAA3kAAzYE"
COOLDOWN_IMAGE_ID = "AgACAgIAAxkBAAID_GjPwr33gJU7xnYbc4VufhMAAWGCoAACqPwxG4FHeEqN8kfzsDpZzAEAAwIAA3kAAzYE"
TOP_IMAGE_ID = "AgACAgIAAxkBAAICw2jMNUqWi1d-ctjc67_Ryg9uLmBHAAJC-TEbLqthSiv8cCgp6EMnAQADAgADeQADNgQ"
DAILY_IMAGE_ID = "AgACAgIAAxkBAAID7mjPujl6mjX5QYH5mW26gwuAY2xSAAJt9jEbkeGASnOosg9TSbYvAQADAgADeQADNgQ"
CARD_COOLDOWN_IMAGE_ID = "AgACAgIAAxkBAAID_GjPwr33gJU7xnYbc4VufhMAAWGCoAACqPwxG4FHeEqN8kfzsDpZzAEAAwIAA3kAAzYE" # ЗАМЕНИТЬ
DAILY_COOLDOWN_IMAGE_ID = "AgACAgIAAxkBAAID_GjPwr33gJU7xnYbc4VufhMAAWGCoAACqPwxG4FHeEqN8kfzsDpZzAEAAwIAA3kAAzYE" # ЗАМЕНИТЬ


# --- Фразы для сообщений (для разнообразия) ---
BEER_WIN_PHRASES = [
    "🥳🍻 Ты успешно бахнул на <b>+{rating_change}</b> 🍺! Получаешь <b>+{coins_bonus}</b> ⚡ Фанкоинов!",
    "🎉🍻 Отличный глоток! Твой рейтинг вырос на <b>+{rating_change}</b> 🍺, и ты нашел <b>+{coins_bonus}</b> ⚡ Фанкоинов в кармане!",
    "😌🍻 Удача на твоей стороне! Ты выпил +<b>{rating_change}</b> 🍺, и тебе дают <b>+{coins_bonus}</b> ⚡ Фанкоинов за отвагу!",
    "🌟🍻 Победа! Бармен налил тебе +<b>{rating_change}</b> 🍺, и ты получил <b>+{coins_bonus}</b> ⚡ Фанкоинов!",
]

BEER_LOSE_PHRASES_RATING = [
    "😭💔 Братья Уизли отжали у тебя <b>{rating_loss}</b> 🍺, но ты всё равно получаешь <b>+{coins_bonus}</b> ⚡ Фанкоинов!",
    "😖🍻 Неудача! Ты пролил <b>{rating_loss}</b> 🍺 рейтинга, но за стойкость держи <b>+{coins_bonus}</b> ⚡ Фанкоинов!",
    "😡🍻 Обидно! <b>{rating_loss}</b> 🍺 испарилось, но <b>+{coins_bonus}</b> ⚡ Фанкоинов всё-таки твои!",
]

BEER_LOSE_PHRASES_ZERO = [
    "😭💔 Братья Уизли отжали у тебя все <b>{rating_loss}</b> 🍺! Ты на нуле, но получаешь <b>+{coins_bonus}</b> ⚡ Фанкоинов!",
    "😖🍻 Полный провал! Весь твой рейтинг (<b>{rating_loss}</b> 🍺) обнулился, но вот тебе <b>+{coins_bonus}</b> ⚡ Фанкоинов за попытку!",
    "😡🍻 Катастрофа! Все <b>{rating_loss}</b> 🍺 исчезли, но держи <b>+{coins_bonus}</b> ⚡ Фанкоинов для поднятия духа!",
]

DAILY_CLAIM_PHRASES = [
    "🎉 <b>Ежедневный бонус!</b> Ты получил <b>+{coins}</b> ⚡ Фанкоинов и <b>+{rating}</b> 🍺 рейтинга!",
    "🌟 <b>Доброе утро (или день)!</b> Твой ежедневный запас: <b>+{coins}</b> ⚡ Фанкоинов и <b>+{rating}</b> 🍺 рейтинга!",
    "🎁 <b>Подарок дня!</b> Сегодня ты богат на <b>+{coins}</b> ⚡ Фанкоинов и <b>+{rating}</b> 🍺 рейтинга!",
    "🥳 <b>Бонус активирован!</b> Твои <b>+{coins}</b> ⚡ Фанкоинов и <b>+{rating}</b> 🍺 рейтинга уже ждут!",
]

logging.basicConfig(level=logging.INFO)

CARD_DECK = [] # Глобальная переменная для хранения колоды карт

# Максимальное количество последних *пользовательских* сообщений для сохранения контекста
# Каждое "сообщение" состоит из двух Content объектов (user и model)
# Плюс 2 стартовых Content объекта (пользовательский промпт и ответ модели на него)
MAX_CHAT_HISTORY_LENGTH_FOR_CONTEXT = 5 


# --- АНТИСПАМ MIDDLEWARE ---
class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, throttle_time: float = 0.5):
        self.cache = TTLCache(maxsize=10_000, ttl=throttle_time)

    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any]
    ) -> Any:
        user_id = event.from_user.id
        if user_id in self.cache:
            return # Игнорируем сообщение, если пользователь в кэше троттлинга
        self.cache[user_id] = None # Добавляем пользователя в кэш
        return await handler(event, data)

router = Router()
default_properties = DefaultBotProperties(parse_mode="HTML")
bot = Bot(token=BOT_TOKEN, default=default_properties)
dp = Dispatcher()

# --- Инициализация Google Gemini ---
model = None # Переменная для модели ИИ, инициализируем как None
if GOOGLE_API_KEY:
    genai.configure(api_key=GOOGLE_API_KEY)
    
    # Настраиваем модель Gemini, теперь используем 'models/gemini-1.5-flash-latest'
    generation_config = {
        "temperature": 0.9, # Креативность: выше = более креативно, ниже = более сфокусировано
        "top_p": 1,
        "top_k": 1,
        "max_output_tokens": 200, # Максимальная длина ответа
    }
    model = genai.GenerativeModel('models/gemini-1.5-flash-latest', generation_config=generation_config)
    logging.info("Google Gemini API успешно настроен.")
else:
    # Если GOOGLE_API_KEY не установлен, модель останется None
    logging.warning("Google Gemini API не настроен, так как GOOGLE_API_KEY не указан.")


# --- Управление базой данных ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT NOT NULL,
            rating INTEGER DEFAULT 0,
            coins INTEGER DEFAULT 0,
            last_beer_time INTEGER DEFAULT 0,
            last_card_time INTEGER DEFAULT 0,
            last_daily_claim_date TEXT DEFAULT '1970-01-01',
            daily_streak INTEGER DEFAULT 0
        )
    ''')
    
    # --- ДОБАВЛЕННАЯ ЧАСТЬ ДЛЯ НОВОГО ПОЛЯ ---
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN gemini_chat_history TEXT DEFAULT '[]'")
        logging.info("Поле 'gemini_chat_history' добавлено в таблицу 'users'.")
    except sqlite3.OperationalError as e:
        if "duplicate column name: gemini_chat_history" in str(e):
            logging.info("Поле 'gemini_chat_history' уже существует.")
        else:
            logging.error(f"Ошибка при добавлении колонки: {e}")
    # --- КОНЕЦ ДОБАВЛЕННОЙ ЧАСТИ ---

    conn.commit()
    conn.close()
    logging.info("База данных успешно инициализирована.")

def get_user_data(user_id: int):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT username, rating, coins, last_beer_time, last_card_time, last_daily_claim_date, daily_streak FROM users WHERE user_id = ?", (user_id,))
    user_data = cursor.fetchone()
    conn.close()
    return user_data

def add_or_update_user(user_id: int, username: str):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    # При регистрации/обновлении username, если пользователя нет, даем 50 монет
    cursor.execute(
        "INSERT INTO users (user_id, username, coins) VALUES (?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET username = EXCLUDED.username",
        (user_id, username, 50)
    )
    conn.commit()
    conn.close()

def update_user_beer_data(user_id: int, new_rating: int, new_coins: int, current_time: int):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET rating = ?, coins = ?, last_beer_time = ? WHERE user_id = ?",
        (new_rating, new_coins, current_time, user_id)
    )
    conn.commit()
    conn.close()

def update_user_card_data(user_id: int, new_rating: int, new_coins: int, current_time: int, beer_cooldown_reset: bool = False):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    if beer_cooldown_reset:
        cursor.execute(
            "UPDATE users SET rating = ?, coins = ?, last_card_time = ?, last_beer_time = 0 WHERE user_id = ?",
            (new_rating, new_coins, current_time, user_id)
        )
    else:
        cursor.execute(
            "UPDATE users SET rating = ?, coins = ?, last_card_time = ? WHERE user_id = ?",
            (new_rating, new_coins, current_time, user_id)
        )
    conn.commit()
    conn.close()

def update_user_daily_data(user_id: int, new_rating: int, new_coins: int, current_date_str: str, new_streak: int):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET rating = ?, coins = ?, last_daily_claim_date = ?, daily_streak = ? WHERE user_id = ?",
        (new_rating, new_coins, current_date_str, new_streak, user_id)
    )
    conn.commit()
    conn.close()

def update_other_user_coins(user_id: int, coin_change: int):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET coins = coins + ? WHERE user_id = ?",
        (coin_change, user_id)
    )
    conn.commit()
    conn.close()

def get_top_users(limit: int = 10):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT username, rating FROM users ORDER BY rating DESC LIMIT ?", (limit,))
    top_users = cursor.fetchall()
    conn.close()
    return top_users

def load_card_deck():
    try:
        with open('cards.json', 'r', encoding='utf-8') as f:
            logging.info("Колода карт успешно загружена.")
            return json.load(f)
    except FileNotFoundError:
        logging.error("Файл cards.json не найден! Колода будет пуста.")
        return []
    except json.JSONDecodeError as e:
        logging.error(f"Ошибка в формате файла cards.json! Проверьте синтаксис JSON: {e}")
        return []

def choose_random_card():
    if not CARD_DECK:
        return None
    weights = [card['weight'] for card in CARD_DECK]
    # Используем random.choices для взвешенного выбора
    chosen_card = random.choices(CARD_DECK, weights=weights, k=1)[0]
    return chosen_card
    
# --- НОВЫЕ ФУНКЦИИ ДЛЯ РАБОТЫ С ИСТОРИЕЙ GEMINI В БД (ИСПРАВЛЕНИЕ 4) ---

def clean_gemini_history_for_saving(history: list) -> list:
    cleaned_history = []
    for item in history:
        current_item_dict = {} # Будем строить этот словарь
        
        # Попытка преобразовать элемент истории в словарь.
        # Это должен быть либо Content объект, либо уже готовый словарь.
        if hasattr(item, 'to_dict') and callable(item.to_dict):
            # Это Content объект, преобразуем его в словарь
            temp_representation = item.to_dict()
        elif isinstance(item, dict):
            # Это уже словарь, используем его напрямую
            temp_representation = item
        else:
            # Если элемент не является Content объектом или словарем, логируем и пропускаем его
            logging.warning(f"Неожиданный тип корневого элемента в истории Gemini при сохранении: {type(item)}. Элемент будет пропущен.")
            continue # Пропускаем этот элемент, так как не знаем, как его сериализовать безопасно
        
        # Теперь temp_representation гарантированно является словарем.
        # Извлекаем роль
        role = temp_representation.get('role')
        if not role:
            logging.warning(f"Элемент истории Gemini не содержит 'role': {temp_representation}. Элемент будет пропущен.")
            continue # Пропускаем элемент без роли
        current_item_dict['role'] = role
        
        # Обрабатываем части (parts)
        current_item_dict['parts'] = []
        parts_from_item = temp_representation.get('parts', [])
        
        if isinstance(parts_from_item, list):
            for part in parts_from_item:
                if hasattr(part, 'to_dict') and callable(part.to_dict):
                    # Это Part объект, преобразуем его в словарь и извлекаем текст
                    part_dict = part.to_dict()
                    if 'text' in part_dict:
                        current_item_dict['parts'].append({'text': part_dict['text']})
                    else:
                        logging.warning(f"Объект 'part' после to_dict не содержит 'text': {part_dict}. Игнорируем эту часть.")
                elif isinstance(part, dict) and 'text' in part:
                    # Это уже словарь с ключом 'text'
                    current_item_dict['parts'].append({'text': part['text']})
                elif isinstance(part, str):
                    # Это просто строка, оборачиваем её в словарь {'text': ...}
                    current_item_dict['parts'].append({'text': part})
                else:
                    logging.warning(f"Неожиданный тип 'part' в истории Gemini при сохранении: {type(part)}. Преобразуем в строку и оборачиваем.")
                    current_item_dict['parts'].append({'text': str(part)})
        else:
            logging.warning(f"Поле 'parts' не является списком в элементе: {temp_representation}. Инициализируем пустым списком.")
            # current_item_dict['parts'] уже инициализирован как пустой список

        cleaned_history.append(current_item_dict)
    return cleaned_history

def prepare_gemini_history_for_loading(history_data: list) -> list:
    prepared_history = []
    for item in history_data:
        # Убедимся, что item это dict перед доступом по ключу
        if not isinstance(item, dict):
            logging.warning(f"Неожиданный формат 'item' при загрузке истории (ожидался dict, получено {type(item)}): {item}. Пропускаем.")
            continue
            
        role = item.get('role')
        parts_data = item.get('parts')

        if not role or not isinstance(parts_data, list):
            logging.warning(f"Элемент истории неполный или некорректный при загрузке: {item}. Пропускаем.")
            continue

        parts_list = []
        for part_item in parts_data:
            if isinstance(part_item, dict) and 'text' in part_item:
                parts_list.append(genai.types.contents.Part(text=part_item['text']))
            elif isinstance(part_item, str): # На случай, если каким-то образом сохранилась чистая строка (для обратной совместимости)
                parts_list.append(genai.types.contents.Part(text=part_item))
            else:
                logging.warning(f"Неожиданный формат 'part_item' при загрузке: {part_item} (тип: {type(part_item)}). Преобразуем в строку.")
                parts_list.append(genai.types.contents.Part(text=str(part_item)))
        
        prepared_history.append(genai.types.contents.Content(role=role, parts=parts_list))
    return prepared_history

# load_gemini_history и save_gemini_history остаются прежними
def load_gemini_history(user_id: int):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT gemini_chat_history FROM users WHERE user_id = ?", (user_id,))
    history_json = cursor.fetchone()
    conn.close()
    if history_json and history_json[0]:
        try:
            # Важно: history_json[0] должна быть строкой JSON
            return prepare_gemini_history_for_loading(json.loads(history_json[0]))
        except json.JSONDecodeError as e:
            logging.error(f"Ошибка декодирования JSON истории для пользователя {user_id}: {e}. Данные: {history_json[0]}. Возвращаю пустую историю.")
            return []
    return []

def save_gemini_history(user_id: int, history: list):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cleaned_history = clean_gemini_history_for_saving(history)
    # Гарантируем, что сохраняем валидный JSON
    try:
        json_to_save = json.dumps(cleaned_history, ensure_ascii=False)
        cursor.execute(
            "UPDATE users SET gemini_chat_history = ? WHERE user_id = ?",
            (json_to_save, user_id)
        )
        conn.commit()
    except TypeError as e:
        logging.error(f"Ошибка сериализации истории Gemini для пользователя {user_id}: {e}. История: {cleaned_history}")
    finally:
        conn.close()
# --- КОНЕЦ НОВЫХ ФУНКЦИЙ ----


# --- Middleware для проверки регистрации пользователя ---
class UserRegistrationMiddleware(BaseMiddleware):
    async def __call__(self, handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]], event: Message, data: Dict[str, Any]) -> Any:
        # Пропускаем, если это не сообщение (например, коллбэк)
        if not isinstance(event, Message):
            return await handler(event, data)

        user_id = event.from_user.id
        # Пропускаем команду /start, чтобы пользователь мог зарегистрироваться
        if event.text and event.text.startswith('/start'):
            return await handler(event, data)
        
        # Пропускаем временный обработчик FILE_ID, чтобы он всегда работал
        if event.photo:
             return await handler(event, data)

        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
        user_exists = cursor.fetchone()
        conn.close()

        if not user_exists:
            await event.answer("Привет! Прежде чем начать, пожалуйста, используй команду /start.")
            return # Прерываем обработку, если пользователь не зарегистрирован

        return await handler(event, data)

dp.message.middleware(UserRegistrationMiddleware())


# --- Промпт для бармена Элвина (ОБНОВЛЕННЫЙ СОГЛАСНО ВАШИМ ПОЖЕЛАНИЯМ) ---
# Использование f-строк для удобства
BARTENDER_PROMPT = (
    "Ты — мудрый и весёлый эльф-бармен по имени Элвин в фэнтезийной таверне 'Золотой Дракон'. "
    "Твоя задача — поддерживать приятную атмосферу и общаться с посетителями. "
    "Отвечай на вопросы, делись короткими байками и шутками, но делай это сдержанно и дружелюбно. "
    "Твой стиль речи: Вежливый, слегка старомодный, фэнтезийный. "
    "Избегай излишней магичности и навязчивых предложений. "
    "Длина ответов: Старайся давать краткие и содержательные ответы, **не более 50 слов**. "
    "Предложения напитков/меню: Крайне редко, если это уместно по контексту, и никогда не навязчиво. "
    "Темы для обсуждения: Отвечай на вопросы, связанные с таверной, миром Фандомия или обыденными вещами. "
    "Избегай: Грубости, агрессии, неприличных тем, слишком длинных ответов, частого предложения меню. "
    "Если вопрос кажется неподобающим или ты не можешь на него ответить: Вежливо откажись, "
    "сославшись на правила таверны, и предложи задать другой вопрос. "
    "Если вопрос касается *технических аспектов работы этого 'бота'* или *его команд* "
    "(например, 'как играть', 'какие у тебя команды'): Вежливо объясни, что ты — бармен, "
    "а не технический помощник, и предложи гостю посмотреть свитки с правилами, используя команду /help."
)

# --- Обработчики команд ---

@router.message(CommandStart())
async def cmd_start(message: Message):
    user_id = message.from_user.id
    username = html.escape(message.from_user.full_name) # Экранируем имя пользователя для HTML безопасности
    
    user_data = get_user_data(user_id) # Проверяем, существует ли пользователь
    add_or_update_user(user_id, username) # Регистрируем или обновляем пользователя

    welcome_message = ""
    if user_data:
        # Сообщение для вернувшегося пользователя
        welcome_message = (
            f"👋 С возвращением в бар, <b>{username}</b>!\n\n"
            "Рады снова тебя видеть. Вот чем можно заняться:"
        )
    else:
        # Сообщение для нового пользователя
        welcome_message = (
            f"👋 Добро пожаловать в бар, <b>{username}</b>! 🍻\n\n"
            "Здесь мы соревнуемся, кто больше выпьет пива и кто богаче на Фанкоины!"
        )

    menu_text = (
        "\n\n🚀 <b>Основные команды:</b>\n"
        "🔸 /beer - Испытай удачу и получи рейтинг/Фанкоины.\n"
        "🔸 /daily - Получи ежедневный бонус.\n"
        "🔸 /draw_card - Вытяни карту судьбы за Фанкоины.\n"
        "🔸 /profile - Посмотреть свой профиль.\n"
        "🔸 /top - Увидеть 10 лучших игроков.\n"
        "🔸 /help - Показать это сообщение.\n"
        "🔸 /menu - Показать это меню снова.\n"
        "🤖 /ask_bartender [вопрос] - Поговори с барменом Фандомия (ИИ)!"
    )
    
    await message.answer(welcome_message + menu_text) # parse_mode="HTML" уже по умолчанию

@router.message(Command("menu"))
async def cmd_menu(message: Message):
    # Повторяет логику /start для отображения меню, но без логики регистрации
    user_id = message.from_user.id
    username = html.escape(message.from_user.full_name)
    
    menu_text = (
        f"<b>Добро пожаловать обратно, {username}!</b> ✨\n\n"
        "Вот список команд, которые помогут тебе в приключениях по Фандомию:\n\n"
        "🚀 <b>Основные команды:</b>\n"
        "🔸 /beer - Закажи кружку пива и получи Фанкоины! Кто знает, может, попадется что-то особенное?\n"
        "🔸 /daily - Получи ежедневный бонус Фанкоинов и рейтинга. Не забывай про стрик!\n"
        "🔸 /draw_card - Испытай удачу и вытяни случайную карту из колоды!\n"
        "🔸 /profile - Посмотри свой текущий баланс Фанкоинов и рейтинг.\n"
        "🔸 /top - Узнай, кто занимает почетное место в таблице лидеров Фандомия.\n"
        "🔸 /help - Подробное описание всех команд и правил игры.\n"
        "🔸 /menu - Открой это меню снова, чтобы вспомнить все команды.\n"
        "🤖 /ask_bartender [вопрос] - Поговори с барменом Фандомия (ИИ)!"
        "\n\n<i>Просто введи нужную команду, чтобы продолжить игру!</i>"
    )
    await message.answer(menu_text)


@router.message(Command("profile"))
async def cmd_profile(message: Message):
    user_id = message.from_user.id
    user_data = get_user_data(user_id)
    # Благодаря middleware, user_data всегда будет существовать здесь, но проверка не помешает
    if user_data:
        username, rating, coins, _, _, _, _ = user_data
        await message.answer(
            f"🌟 <b>Твой профиль, {html.escape(username)}:</b> 🌟\n"
            "------------------------------------\n"
            f"🔸 <b>Рейтинг:</b> <b>{rating}</b> 🍺\n"
            f"🔸 <b>Фанкоины:</b> <b>{coins}</b> ⚡\n"
            "------------------------------------"
        )
    else:
        # Это сообщение в теории не должно появиться, т.к. middleware требует /start
        await message.answer("Ты еще не зарегистрирован. Нажми /start.")

@router.message(Command("beer"))
async def cmd_beer(message: Message):
    user_id = message.from_user.id
    current_time = int(time.time())
    user_data = get_user_data(user_id) # user_data всегда будет существовать благодаря middleware
    
    _, rating, coins, last_beer_time, _, _, _ = user_data
    time_passed = current_time - last_beer_time

    if time_passed < COOLDOWN_SECONDS:
        time_left = COOLDOWN_SECONDS - time_passed
        time_left_formatted = str(timedelta(seconds=time_left)).split('.')[0] # Убираем миллисекунды
        await message.answer_photo(
            photo=COOLDOWN_IMAGE_ID,
            caption=f"⌛ Ты уже недавно пил! 🍻\n"
                    f"Вернись в бар через: <b>{time_left_formatted}</b>",
        )
        return
    
    roll = random.randint(1, 100)
    rating_change_amount = random.randint(1, 10)
    coin_bonus = random.randint(1, 2) # Бонус Фанкоинов всегда, даже при проигрыше
    
    new_rating = rating
    new_coins = coins + coin_bonus
    caption_text = ""
    photo_id = ""

    if roll <= WIN_CHANCE:
        new_rating = rating + rating_change_amount
        caption_text = random.choice(BEER_WIN_PHRASES).format(rating_change=rating_change_amount, coins_bonus=coin_bonus)
        photo_id = SUCCESS_IMAGE_ID
    else: # Проигрыш
        potential_new_rating = rating - rating_change_amount
        if potential_new_rating < 0:
            actual_loss = rating # Теряем весь текущий рейтинг до 0
            new_rating = 0
            caption_text = random.choice(BEER_LOSE_PHRASES_ZERO).format(rating_loss=actual_loss, coins_bonus=coin_bonus)
        else:
            actual_loss = rating_change_amount
            new_rating = potential_new_rating
            caption_text = random.choice(BEER_LOSE_PHRASES_RATING).format(rating_loss=actual_loss, coins_bonus=coin_bonus)
        photo_id = FAIL_IMAGE_ID
    
    update_user_beer_data(user_id, new_rating, new_coins, current_time)
    await message.answer_photo(photo=photo_id, caption=caption_text)


@router.message(Command("daily"))
async def cmd_daily(message: Message):
    user_id = message.from_user.id
    current_date = date.today()
    current_date_str = current_date.isoformat()
    user_data = get_user_data(user_id) # user_data всегда будет существовать благодаря middleware

    _, rating, coins, _, _, last_daily_claim_date, daily_streak = user_data
    
    if last_daily_claim_date == current_date_str:
        next_day = current_date + timedelta(days=1)
        time_until_midnight = datetime.combine(next_day, dt_time.min) - datetime.now()
        hours, remainder = divmod(int(time_until_midnight.total_seconds()), 3600)
        minutes, _ = divmod(remainder, 60)
        time_left_formatted = f"{hours}ч {minutes}м"
        await message.answer_photo(
            photo=DAILY_COOLDOWN_IMAGE_ID,
            caption=f"⏰ <b>Рановато!</b> Ежедневный бонус можно получить завтра.\n"
                    f"До нового дня осталось: <b>{time_left_formatted}</b>",
        )
        return
    
    # Обновление стрика
    if last_daily_claim_date == (current_date - timedelta(days=1)).isoformat():
        new_streak = daily_streak + 1
    else:
        new_streak = 1 # Стрик сброшен, если день пропущен

    streak_bonus_index = min(new_streak - 1, DAILY_MAX_STREAK_BONUS_INDEX)
    bonus_coins = DAILY_BASE_COIN_BONUS + DAILY_STREAK_COIN_BONUSES[streak_bonus_index]
    bonus_rating = DAILY_BASE_RATING_BONUS
    
    new_coins = coins + bonus_coins
    new_rating = rating + bonus_rating
    
    update_user_daily_data(user_id, new_rating, new_coins, current_date_str, new_streak)
    
    caption_text = random.choice(DAILY_CLAIM_PHRASES).format(coins=bonus_coins, rating=bonus_rating)
    if new_streak > 1:
        caption_text += f"\n🔥 Твой стрик: <b>{new_streak} дней</b> (Бонус: <b>+{DAILY_STREAK_COIN_BONUSES[streak_bonus_index]}</b> ⚡ Фанкоинов)!"
    
    await message.answer_photo(photo=DAILY_IMAGE_ID, caption=caption_text)

@router.message(Command("draw_card"))
async def cmd_draw_card(message: Message):
    user_id = message.from_user.id
    current_time = int(time.time())
    user_data = get_user_data(user_id) # user_data всегда будет существовать благодаря middleware

    _, rating, coins, _, last_card_time, _, _ = user_data
    time_passed = current_time - last_card_time

    if time_passed < CARD_COOLDOWN_SECONDS:
        time_left = CARD_COOLDOWN_SECONDS - time_passed
        time_left_formatted = str(timedelta(seconds=time_left)).split('.')[0]
        await message.answer_photo(
            photo=CARD_COOLDOWN_IMAGE_ID,
            caption=f"🎴 <b>Колода ещё не перемешана!</b> ⏳\n"
                    f"Попробуй вытянуть следующую карту через: <b>{time_left_formatted}</b>",
        )
        return

    if coins < CARD_DRAW_COST:
        await message.answer(
            f"⚡ Не хватает <b>{CARD_DRAW_COST - coins}</b> ⚡ Фанкоинов! Для вытягивания карты нужно <b>{CARD_DRAW_COST}</b> ⚡ Фанкоинов, а у тебя только <b>{coins}</b> ⚡ Фанкоинов."
        )
        return
    
    new_coins = coins - CARD_DRAW_COST # Сразу списываем стоимость карты
    new_rating = rating # Начальный рейтинг до эффектов карты
    
    chosen_card = choose_random_card()
    if not chosen_card:
        await message.answer("Ошибка: Колода карт пуста или не загружена. Сообщите администратору.")
        logging.error("CARD_DECK is empty or not loaded.")
        return
    
    card_name = chosen_card['name']
    card_description = chosen_card['description']
    card_image_id = chosen_card['image_id']
    effects = chosen_card['effects']
    
    rating_change = random.randint(effects.get('rating_change_min', 0), effects.get('rating_change_max', 0))
    coin_change = random.randint(effects.get('coin_change_min', 0), effects.get('coin_change_max', 0))
    
    # Применяем изменения рейтинга и монет
    new_rating = max(0, new_rating + rating_change)
    new_coins = max(0, new_coins + coin_change)
    
    beer_cooldown_reset = effects.get('cooldown_reset_beer', False)
    target_other_coin_change = effects.get('target_other_coin_change', 0)
    
    final_description = card_description # Исходное описание, если не будет форматирования
    
    # Обработка карты "Щедрый Сосед" или других карт с динамическим текстом
    other_user_notified = False
    if target_other_coin_change > 0:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        # Ищем другого случайного пользователя, исключая текущего
        cursor.execute("SELECT user_id FROM users WHERE user_id != ? ORDER BY RANDOM() LIMIT 1", (user_id,))
        other_user_id_tuple = cursor.fetchone()
        conn.close()

        if other_user_id_tuple:
            other_user_id = other_user_id_tuple[0]
            update_other_user_coins(other_user_id, target_other_coin_change)
            other_user_notified = True
            try:
                # Отправляем уведомление другому пользователю
                other_user_data = get_user_data(other_user_id)
                if other_user_data:
                    other_username = html.escape(other_user_data[0])
                    await bot.send_message(
                        other_user_id,
                        f"🎉 <b>Сюрприз!</b> Игрок <b>{html.escape(user_data[0])}</b> был сегодня щедр и угостил тебя <b>+{target_other_coin_change}</b> ⚡ Фанкоинов!"
                    )
            except Exception as e:
                logging.warning(f"Не удалось отправить уведомление другому игроку {other_user_id}: {e}")
    
    # Форматирование описания карты, если в нём есть плейсхолдеры %d
    if '%d' in card_description:
        description_args = []
        try:
            # Логика для конкретных карт
            if chosen_card['id'] == 'generous_neighbor':
                display_target_other_coin_change = target_other_coin_change if other_user_notified else 0 # Если никого нет, угощения не было
                description_args = [abs(effects.get('coin_change_min', 0)), abs(effects.get('rating_change_min', 0)), display_target_other_coin_change]
            elif chosen_card['id'] == 'empty_glass':
                description_args = [CARD_DRAW_COST]
            else: # Для других карт, если есть изменения, добавляем их
                if effects.get('rating_change_min') != 0 or effects.get('rating_change_max') != 0:
                    description_args.append(abs(rating_change))
                if effects.get('coin_change_min') != 0 or effects.get('coin_change_max') != 0:
                    description_args.append(abs(coin_change))
            
            final_description = card_description % tuple(description_args)
        except (TypeError, IndexError, KeyError) as e:
            logging.warning(f"Ошибка форматирования описания для карты {card_name}: {e}")
            final_description = card_description # Используем исходное описание, если ошибка
            
    update_user_card_data(user_id, new_rating, new_coins, current_time, beer_cooldown_reset)
    
    # Вычисление фактических изменений для вывода в конце сообщения
    actual_rating_change = new_rating - rating 
    actual_coin_change = (new_coins + CARD_DRAW_COST) - coins # Восстанавливаем списанную стоимость карты для расчета дельты

    rating_delta_str = ""
    if actual_rating_change > 0:
        rating_delta_str = f" (+<b>{actual_rating_change}</b> 🍺)"
    elif actual_rating_change < 0:
        rating_delta_str = f" (-<b>{abs(actual_rating_change)}</b> 🍺)"

    coin_delta_str = ""
    if actual_coin_change > 0:
        coin_delta_str = f" (+<b>{actual_coin_change}</b> ⚡ Фанкоинов)"
    elif actual_coin_change < 0:
        coin_delta_str = f" (-<b>{abs(actual_coin_change)}</b> ⚡ Фанкоинов)"

    caption_message = (
        f"🃏 <b>Ты вытянул карту: '{card_name}'</b> 🃏\n"
        "------------------------------------\n"
        f"{final_description}\n\n"
        f"📊 Твой рейтинг: <b>{new_rating}</b> 🍺{rating_delta_str}\n"
        f"💰 Твои Фанкоины: <b>{new_coins}</b> ⚡{coin_delta_str}"
    )
    await message.answer_photo(photo=card_image_id, caption=caption_message)

@router.message(Command("top"))
async def cmd_top(message: Message):
    top_users = get_top_users()
    if not top_users:
        await message.answer("В баре пока никого нет, ты можешь стать первым! 🍻")
        return
    
    response_text = "🏆 <b>Топ-10 лучших пивохлёбов:</b> 🏆\n"
    response_text += "------------------------------------\n"
    
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    for i, (username, rating) in enumerate(top_users, 1):
        place_icon = medals.get(i, f"🔹 <b>{i}.</b>") # Используем эмодзи для первых трех, затем просто номер
        response_text += f"{place_icon} {html.escape(username)} — <b>{rating}</b> 🍺\n"
    
    response_text += "------------------------------------"
    
    await message.answer_photo(
        photo=TOP_IMAGE_ID,
        caption=response_text,
    )

@router.message(Command("help"))
async def cmd_help(message: Message):
    help_text = (
        "📚 <b>Правила Игры в Пивном Баре</b> 🍻\n"
        "------------------------------------\n"
        "Это простая игра, где ты соревнуешься за самый высокий пивной рейтинг и копишь Фанкоины!\n\n"
        "🚀 <b>Основные команды:</b>\n"
        "🔸 /start - Начать игру и зарегистрироваться (или обновить профиль).\n"
        "🔸 /beer - Испытай удачу и получи (или потеряй) пивной рейтинг. Кулдаун: 3 часа. Даёт ⚡ Фанкоинов.\n"
        "🔸 /daily - Получи ежедневный бонус ⚡ Фанкоинов и рейтинга. Есть бонусы за серию!\n"
        "🔸 /draw_card - Вытяни карту судьбы за ⚡ Фанкоины! Кулдаун: 2 часа. <i>(Стоимость: <b>15</b> ⚡ Фанкоинов)</i>\n"
        "🔸 /profile - Посмотреть свой текущий рейтинг и количество ⚡ Фанкоинов.\n"
        "🔸 /top - Увидеть 10 лучших игроков по пивному рейтингу.\n"
        "🔸 /menu - Показать краткое меню команд.\n"
        "🔸 /help - Показать это сообщение.\n"
        "🤖 /ask_bartender [вопрос] - Поговори с барменом Фандомия (ИИ)!\n"
        "------------------------------------"
    )
    await message.answer(help_text)

# КОМАНДА: ИИ-Бармен
@router.message(Command("ask_bartender"))
async def cmd_ask_bartender(message: Message):
    if not model:
        await message.answer("Извините, бармен сегодня занят и не может принимать посетителей (ИИ не настроен).")
        return

    user_id = message.from_user.id
    user_question = message.text.replace("/ask_bartender", "").strip()

    if not user_question:
        await message.answer("Спроси что-нибудь у бармена, например: <code>/ask_bartender Что нового в таверне?</code>")
        return

    # --- НАЧАЛО ИЗМЕНЕНИЙ ДЛЯ ПОСТОЯННОЙ ПАМЯТИ ---
    current_chat_history = load_gemini_history(user_id)
    
    # Создаем эталонный Content объект для сравнения с первым элементом истории
    # Используем глобальную константу BARTENDER_PROMPT
    expected_initial_user_content = genai.types.contents.Content(
        role="user", 
        parts=[genai.types.contents.Part(text=BARTENDER_PROMPT)]
    )

    # Проверяем, нужна ли инициализация истории:
    # 1. История пуста
    # 2. Или первый элемент истории не является ожидаемым промптом (по роли и тексту)
    #    (Убедимся, что история не пуста перед доступом к индексу [0])
    if not current_chat_history or \
       not (len(current_chat_history) > 0 and 
            isinstance(current_chat_history[0], genai.types.contents.Content) and
            current_chat_history[0].role == "user" and 
            len(current_chat_history[0].parts) > 0 and 
            isinstance(current_chat_history[0].parts[0], genai.types.contents.Part) and
            current_chat_history[0].parts[0].text == BARTENDER_PROMPT):
        
        # Если история не инициализирована или устарела, создаем новую с текущим промптом
        initial_history_parts = [
            expected_initial_user_content, # Используем заранее созданный объект
            genai.types.contents.Content(role="model", parts=[genai.types.contents.Part(text="Рад видеть тебя, добрый путник! Что привело тебя в 'Золотого Дракона' сегодня?")])
        ]
        current_chat_history = initial_history_parts
    
    # Инициализируем новую сессию чата с загруженной (или инициализированной) историей
    chat_session = model.start_chat(history=current_chat_history)
    # --- КОНЕЦ ИЗМЕНЕНИЙ ДЛЯ ПОСТОЯННОЙ ПАМЯТИ ---

    try:
        await bot.send_chat_action(chat_id=message.chat.id, action="typing")
        
        # Отправляем сообщение пользователя в модель
        # Используем asyncio.to_thread для блокирующей функции send_message
        response = await asyncio.to_thread(chat_session.send_message, user_question)
        
        ai_response_text = ""
        # Добавлена более надежная проверка ответа Gemini
        if response.candidates and \
           len(response.candidates) > 0 and \
           response.candidates[0].content and \
           len(response.candidates[0].content.parts) > 0 and \
           isinstance(response.candidates[0].content.parts[0], genai.types.contents.Part) and \
           response.candidates[0].content.parts[0].text:
            
            ai_response_text = response.candidates[0].content.parts[0].text
            # Форматирование Markdown (можно улучшить, но для базовых случаев достаточно)
            ai_response_text = ai_response_text.replace('**', '<b>').replace('*', '<i>')
            
            await message.reply(f"🤖 <b>Элвин, бармен Фандомия:</b>\n{ai_response_text}")
            
            # --- СОХРАНЕНИЕ ОБНОВЛЕННОЙ ИСТОРИИ ---
            # Обновляем историю чата с новым вопросом пользователя и ответом модели
            current_chat_history.append(genai.types.contents.Content(role="user", parts=[genai.types.contents.Part(text=user_question)]))
            current_chat_history.append(response.candidates[0].content)

            # Обрезаем историю, сохраняя последние MAX_CHAT_HISTORY_LENGTH_FOR_CONTEXT
            # пар (вопрос-ответ) плюс начальные 2 промпта.
            # Если в истории 2 начальных промпта, а затем N пар user/model,
            # то длина истории будет 2 + N*2.
            # Нам нужно сохранить 2 + MAX_CHAT_HISTORY_LENGTH_FOR_CONTEXT * 2 элементов.
            # Если история длиннее, берем последние X элементов.
            
            # Длина истории, которую хотим сохранить: 2 (начальных промпта) + MAX_CHAT_HISTORY_LENGTH_FOR_CONTEXT * 2 (пары диалога)
            desired_history_len = 2 + MAX_CHAT_HISTORY_LENGTH_FOR_CONTEXT * 2
            
            if len(current_chat_history) > desired_history_len:
                # Обрезаем, сохраняя начальные 2 элемента (промпт) и последние desired_history_len - 2 элемента
                current_chat_history = current_chat_history[:2] + current_chat_history[-(desired_history_len - 2):]
            
            # Сохраняем обновленную историю в БД
            save_gemini_history(user_id, current_chat_history)
            # --- КОНЕЦ СОХРАНЕНИЯ ---

        else:
            logging.warning(f"Gemini response was empty or filtered for user {user_id}. Prompt: {user_question}")
            await message.reply("🤖 <b>Элвин, бармен Фандомия:</b>\n"
                                 "Прошу прощения, друг, но этот вопрос немного... необычен. "
                                 "Таверна 'Золотой Дракон' хранит свои секреты. Спроси что-нибудь другое.")

    except Exception as e:
        logging.error(f"Ошибка при запросе к Gemini для пользователя {user_id}: {e}", exc_info=True) # exc_info=True для полного стектрейса
        await message.reply("🤖 <b>Элвин, бармен Фандомия:</b>\n"
                            "Упс! Кажется, магический кристалл бармена затуманился. "
                            "Попробуй спросить меня ещё раз через мгновение, пока я его протру.")

# --- ВРЕМЕННЫЙ ОБРАБОТЧИК ДЛЯ ПОЛУЧЕНИЯ FILE_ID (УДАЛИТЬ ПОСЛЕ ИСПОЛЬЗОВАНИЯ!) ---
@router.message(F.photo)
async def get_file_id_temp(message: Message):
    if message.photo:
        file_id = message.photo[-1].file_id
        escaped_file_id = html.escape(file_id)
        response_text = f"FILE_ID этой фотографии:\n<code>{escaped_file_id}</code>"
        await message.answer(response_text)
        logging.info(f"ВРЕМЕННО: Получен FILE_ID: {file_id}")
# --- КОНЕЦ ВРЕМЕННОГО БЛОКА ---


async def main():
    global CARD_DECK
    init_db()
    CARD_DECK = load_card_deck()

    router.message.middleware(ThrottlingMiddleware(throttle_time=THROTTLE_TIME))
    
    dp.include_router(router)
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
