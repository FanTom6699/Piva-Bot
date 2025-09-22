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
from aiogram import Bot, Dispatcher, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from dotenv import load_dotenv
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from cachetools import TTLCache

# --- Конфигурация ---
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

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
SUCCESS_IMAGE_ID = "AgACAgIAAxkBAAICvGjMNGhCINSBAeXyX9w0VddF-C8PAAJt8jEbFbVhSmh8gDAZrTCaAQADAgADeQADNgQ" # Пример
FAIL_IMAGE_ID = "AgACAgIAAxkBAAICwGjMNRAnAAHo1rDMPfaF_HUa0WzxaAACcvIxGxW1YUo5jEQQRkt4kgEAAwIAA3kAAzYE" # Пример
COOLDOWN_IMAGE_ID = "AgACAgIAAxkBAAID_GjPwr33gJU7xnYbc4VufhMAAWGCoAACqPwxG4FHeEqN8kfzsDpZzAEAAwIAA3kAAzYE" # Пример
TOP_IMAGE_ID = "AgACAgIAAxkBAAICw2jMNUqWi1d-ctjc67_Ryg9uLmBHAAJC-TEbLqthSiv8cCgp6EMnAQADAgADeQADNgQ" # Пример
DAILY_IMAGE_ID = "AgACAgIAAxkBAAID7mjPujl6mjX5QYH5mW26gwuAY2xSAAJt9jEbkeGASnOosg9TSbYvAQADAgADeQADNgQ" # <--- ОБНОВЛЕНО!

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

CARD_DECK = []

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
            return
        self.cache[user_id] = None
        return await handler(event, data)

router = Router()
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

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
    cursor.execute(
        "INSERT INTO users (user_id, username, coins) VALUES (?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET username = EXCLUDED.username",
        (user_id, username, 50) # Изначальные 50 ⚡ Фанкоинов
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
    except json.JSONDecodeError:
        logging.error("Ошибка в формате файла cards.json! Проверьте синтаксис JSON.")
        return []

def choose_random_card():
    if not CARD_DECK:
        return None
    weights = [card['weight'] for card in CARD_DECK]
    chosen_card = random.choices(CARD_DECK, weights=weights, k=1)[0]
    return chosen_card

# --- Обработчики команд ---

@router.message(CommandStart())
async def cmd_start(message: Message):
    user_id = message.from_user.id
    username = html.escape(message.from_user.full_name) 
    user_data = get_user_data(user_id)
    add_or_update_user(user_id, username)
    if user_data:
        await message.answer(f"👋 С возвращением, <b>{username}</b>! Рады снова видеть тебя в баре. 🍻", parse_mode="HTML")
    else:
        await message.answer(
            f"👋 Добро пожаловать в бар, <b>{username}</b>! 🍻\n"
            "------------------------------------\n"
            "Здесь мы соревнуемся, кто больше выпьет пива и кто богаче на Фанкоины!\n\n"
            "🔸 Используй команду /beer, чтобы испытать удачу!\n"
            "🔸 Получи ежедневный бонус: /daily\n"
            "🔸 Попробуй вытянуть карту судьбы: /draw_card\n"
            "🔸 Проверить свой профиль: /profile\n"
            "🔸 Посмотреть на лучших: /top\n"
            "🔸 Нужна помощь? /help\n"
            "------------------------------------",
            parse_mode="HTML"
        )

@router.message(Command("profile"))
async def cmd_profile(message: Message):
    user_id = message.from_user.id
    user_data = get_user_data(user_id)
    if user_data:
        username, rating, coins, _, _, _, _ = user_data
        await message.answer(
            f"🌟 <b>Твой профиль, {username}:</b> 🌟\n"
            "------------------------------------\n"
            f"🔸 <b>Рейтинг:</b> <b>{rating}</b> 🍺\n"
            f"🔸 <b>Фанкоины:</b> <b>{coins}</b> ⚡\n" # Формат: ⚡ число Фанкоинов
            "------------------------------------",
            parse_mode="HTML"
        )
    else:
        await message.answer("Ты еще не зарегистрирован. Нажми /start.")

@router.message(Command("beer"))
async def cmd_beer(message: Message):
    user_id = message.from_user.id
    current_time = int(time.time())
    user_data = get_user_data(user_id)
    if not user_data:
        await message.answer("Сначала зарегистрируйся с помощью команды /start.")
        return
    _, rating, coins, last_beer_time, _, _, _ = user_data
    time_passed = current_time - last_beer_time
    if time_passed < COOLDOWN_SECONDS:
        time_left = COOLDOWN_SECONDS - time_passed
        time_left_formatted = str(timedelta(seconds=time_left))
        await message.answer_photo(
            photo=COOLDOWN_IMAGE_ID,
            caption=f"⌛ Ты уже недавно пил! 🍻\n"
                    f"Вернись в бар через: <b>{time_left_formatted}</b>",
            parse_mode="HTML"
        )
        return
    roll = random.randint(1, 100)
    rating_change_amount = random.randint(1, 10)
    coin_bonus = random.randint(1, 2)
    new_rating = rating
    new_coins = coins + coin_bonus
    caption_text = ""
    photo_id = ""
    if roll <= WIN_CHANCE:
        new_rating = rating + rating_change_amount
        caption_text = random.choice(BEER_WIN_PHRASES).format(rating_change=rating_change_amount, coins_bonus=coin_bonus)
        photo_id = SUCCESS_IMAGE_ID
    else:
        potential_new_rating = rating - rating_change_amount
        if potential_new_rating < 0:
            actual_loss = rating
            new_rating = 0
            caption_text = random.choice(BEER_LOSE_PHRASES_ZERO).format(rating_loss=actual_loss, coins_bonus=coin_bonus)
        else:
            actual_loss = rating_change_amount
            new_rating = potential_new_rating
            caption_text = random.choice(BEER_LOSE_PHRASES_RATING).format(rating_loss=actual_loss, coins_bonus=coin_bonus)
        photo_id = FAIL_IMAGE_ID
    update_user_beer_data(user_id, new_rating, new_coins, current_time)
    await message.answer_photo(photo=photo_id, caption=caption_text, parse_mode="HTML")

@router.message(Command("daily"))
async def cmd_daily(message: Message):
    user_id = message.from_user.id
    current_date = date.today()
    current_date_str = current_date.isoformat()
    user_data = get_user_data(user_id)
    if not user_data:
        await message.answer("Сначала зарегистрируйся с помощью команды /start.")
        return
    _, rating, coins, _, _, last_daily_claim_date, daily_streak = user_data
    if last_daily_claim_date == current_date_str:
        next_day = current_date + timedelta(days=1)
        time_until_midnight = datetime.combine(next_day, dt_time.min) - datetime.now()
        hours, remainder = divmod(int(time_until_midnight.total_seconds()), 3600)
        minutes, _ = divmod(remainder, 60)
        time_left_formatted = f"{hours}ч {minutes}м"
        await message.answer_photo(
            photo=COOLDOWN_IMAGE_ID,
            caption=f"⏰ <b>Рановато!</b> Ежедневный бонус можно получить завтра.\n"
                    f"До нового дня осталось: <b>{time_left_formatted}</b>",
            parse_mode="HTML"
        )
        return
    
    # Обновление стрика
    if last_daily_claim_date == (current_date - timedelta(days=1)).isoformat():
        new_streak = daily_streak + 1
    else:
        new_streak = 1 # Стрик сброшен

    streak_bonus_index = min(new_streak - 1, DAILY_MAX_STREAK_BONUS_INDEX)
    bonus_coins = DAILY_BASE_COIN_BONUS + DAILY_STREAK_COIN_BONUSES[streak_bonus_index]
    bonus_rating = DAILY_BASE_RATING_BONUS
    new_coins = coins + bonus_coins
    new_rating = rating + bonus_rating
    
    update_user_daily_data(user_id, new_rating, new_coins, current_date_str, new_streak)
    
    caption_text = random.choice(DAILY_CLAIM_PHRASES).format(coins=bonus_coins, rating=bonus_rating)
    if new_streak > 1:
        caption_text += f"\n🔥 Твой стрик: <b>{new_streak} дней</b> (Бонус: <b>+{DAILY_STREAK_COIN_BONUSES[streak_bonus_index]}</b> ⚡ Фанкоинов)!" # Формат: ⚡ число Фанкоинов
    
    await message.answer_photo(photo=DAILY_IMAGE_ID, caption=caption_text, parse_mode="HTML")

@router.message(Command("draw_card"))
async def cmd_draw_card(message: Message):
    user_id = message.from_user.id
    current_time = int(time.time())
    user_data = get_user_data(user_id)
    if not user_data:
        await message.answer("Сначала зарегистрируйся с помощью команды /start.")
        return
    username, rating, coins, _, last_card_time, _, _ = user_data
    time_passed = current_time - last_card_time
    if time_passed < CARD_COOLDOWN_SECONDS:
        time_left = CARD_COOLDOWN_SECONDS - time_passed
        time_left_formatted = str(timedelta(seconds=time_left))
        await message.answer_photo(
            photo=CARD_COOLDOWN_IMAGE_ID,
            caption=f"🎴 <b>Колода ещё не перемешана!</b> ⏳\n"
                    f"Попробуй вытянуть следующую карту через: <b>{time_left_formatted}</b>",
            parse_mode="HTML"
        )
        return
    if coins < CARD_DRAW_COST:
        await message.answer(
            f"⚡ Не хватает <b>{CARD_DRAW_COST - coins}</b> ⚡ Фанкоинов! Для вытягивания карты нужно <b>{CARD_DRAW_COST}</b> ⚡ Фанкоинов, а у тебя только <b>{coins}</b> ⚡ Фанкоинов.", # Формат: ⚡ число Фанкоинов
            parse_mode="HTML"
        )
        return
    new_coins = coins - CARD_DRAW_COST
    new_rating = rating
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
    
    # Сохраняем начальные значения, чтобы вычислить финальный итог для отображения
    initial_new_rating = new_rating
    initial_new_coins = new_coins

    new_rating = max(0, new_rating + rating_change)
    new_coins = max(0, new_coins + coin_change)
    beer_cooldown_reset = effects.get('cooldown_reset_beer', False)
    target_other_coin_change = effects.get('target_other_coin_change', 0)
    
    final_description = card_description
    
    # Обработка карты "Щедрый Сосед"
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
                other_user_data = get_user_data(other_user_id)
                if other_user_data:
                    other_username = html.escape(other_user_data[0])
                    await bot.send_message(
                        other_user_id,
                        f"🎉 <b>Сюрприз!</b> Игрок <b>{username}</b> был сегодня щедр и угостил тебя <b>+{target_other_coin_change}</b> ⚡ Фанкоинов!", # Формат: ⚡ число Фанкоинов
                        parse_mode="HTML"
                    )
            except Exception as e:
                logging.warning(f"Не удалось отправить уведомление другому игроку {other_user_id}: {e}")
        
    # Форматирование описания карты
    if '%d' in card_description:
        description_args = []
        try:
            if chosen_card['id'] == 'generous_neighbor':
                # Если никого нет, угощения не было, поэтому показываем 0 за угощение
                display_target_other_coin_change = target_other_coin_change if other_user_notified else 0 
                description_args = [abs(effects['coin_change_min']), abs(effects['rating_change_min']), display_target_other_coin_change]
            elif chosen_card['id'] == 'empty_glass':
                description_args = [CARD_DRAW_COST]
            else:
                # Для других карт, если есть изменения, добавляем их
                if effects.get('rating_change_min') != 0 or effects.get('rating_change_max') != 0:
                    description_args.append(abs(rating_change))
                if effects.get('coin_change_min') != 0 or effects.get('coin_change_max') != 0:
                    description_args.append(abs(coin_change))
            
            final_description = card_description % tuple(description_args)
        except (TypeError, IndexError) as e:
            logging.warning(f"Ошибка форматирования описания для карты {card_name}: {e}")
            final_description = card_description # Используем исходное описание, если ошибка
    
    update_user_card_data(user_id, new_rating, new_coins, current_time, beer_cooldown_reset)
    
    # Вычисление изменений для вывода в конце сообщения
    # Здесь нужно учитывать CARD_DRAW_COST, так как он уже вычтен из new_coins
    actual_rating_change = new_rating - rating 
    actual_coin_change = (new_coins + CARD_DRAW_COST) - coins # + CARD_DRAW_COST, потому что мы его вычли вначале

    rating_delta_str = ""
    if actual_rating_change > 0:
        rating_delta_str = f" (+<b>{actual_rating_change}</b> 🍺)"
    elif actual_rating_change < 0:
        rating_delta_str = f" (-<b>{abs(actual_rating_change)}</b> 🍺)"

    coin_delta_str = ""
    if actual_coin_change > 0:
        coin_delta_str = f" (+<b>{actual_coin_change}</b> ⚡ Фанкоинов)" # Формат: ⚡ число Фанкоинов
    elif actual_coin_change < 0:
        coin_delta_str = f" (-<b>{abs(actual_coin_change)}</b> ⚡ Фанкоинов)" # Формат: ⚡ число Фанкоинов


    caption_message = (
        f"🃏 <b>Ты вытянул карту: '{card_name}'</b> 🃏\n"
        "------------------------------------\n"
        f"{final_description}\n\n"
        f"📊 Твой рейтинг: <b>{new_rating}</b> 🍺{rating_delta_str}\n"
        f"💰 Твои Фанкоины: <b>{new_coins}</b> ⚡{coin_delta_str}" # Формат: ⚡ число Фанкоинов
    )
    await message.answer_photo(photo=card_image_id, caption=caption_message, parse_mode="HTML")

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
        place_icon = medals.get(i, f"🔹 <b>{i}.</b>") 
        response_text += f"{place_icon} {html.escape(username)} — <b>{rating}</b> 🍺\n"
    
    response_text += "------------------------------------"
    
    await message.answer_photo(
        photo=TOP_IMAGE_ID,
        caption=response_text,
        parse_mode="HTML"
    )

@router.message(Command("help"))
async def cmd_help(message: Message):
    help_text = (
        "📚 <b>Правила Игры в Пивном Баре</b> 🍻\n"
        "------------------------------------\n"
        "Это простая игра, где ты соревнуешься за самый высокий пивной рейтинг и копишь Фанкоины!\n\n"
        "🚀 <b>Основные команды:</b>\n"
        "🔸 /start - Начать игру и зарегистрироваться (или обновить профиль).\n"
        "🔸 /beer - Испытай удачу и получи (или потеряй) пивной рейтинг. Кулдаун: 3 часа. Даёт ⚡ Фанкоинов.\n" # Формат: ⚡ число Фанкоинов
        "🔸 /daily - Получи ежедневный бонус ⚡ Фанкоинов и рейтинга. Есть бонусы за серию!\n" # Формат: ⚡ число Фанкоинов
        "🔸 /draw_card - Вытяни карту судьбы за ⚡ Фанкоины! Кулдаун: 2 часа. <i>(Стоимость: <b>15</b> ⚡ Фанкоинов)</i>\n" # Формат: ⚡ число Фанкоинов
        "🔸 /profile - Посмотреть свой текущий рейтинг и количество ⚡ Фанкоинов.\n" # Формат: ⚡ число Фанкоинов
        "🔸 /top - Увидеть 10 лучших игроков по пивному рейтингу.\n"
        "🔸 /help - Показать это сообщение.\n"
        "------------------------------------"
    )
    await message.answer(help_text, parse_mode="HTML")

# --- ВРЕМЕННЫЙ ОБРАБОТЧИК ДЛЯ ПОЛУЧЕНИЯ FILE_ID (УДАЛИТЬ ПОСЛЕ ИСПОЛЬЗОВАНИЯ!) ---
@router.message()
async def get_file_id_temp(message: Message):
    """
    Временный обработчик для получения FILE_ID любых отправленных фото.
    УДАЛИТЬ ПОСЛЕ ТОГО, КАК ПОЛУЧИТЕ ВСЕ НЕОБХОДИМЫЕ FILE_ID!
    """
    if message.photo:
        file_id = message.photo[-1].file_id # Берем самый большой размер фото
        await message.answer(f"FILE_ID этой фотографии:\n`{file_id}`", parse_mode="MarkdownV2")
        logging.info(f"ВРЕМЕННО: Получен FILE_ID: {file_id}")
    elif message.document and message.document.mime_type and message.document.mime_type.startswith('image/'):
        file_id = message.document.file_id
        await message.answer(f"FILE_ID этого изображения (как документа):\n`{file_id}`", parse_mode="MarkdownV2")
        logging.info(f"ВРЕМЕННО: Получен FILE_ID (документ-изображение): {file_id}")
    # Важно: если вы хотите, чтобы бот не обрабатывал другие текстовые сообщения этим обработчиком
    # и продолжал работу с другими командами, этот catch-all обработчик должен быть ПОСЛЕДНИМ
    # в списке ваших @router.message() вызовов. В противном случае, он будет перехватывать все.
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
