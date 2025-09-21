import asyncio
import logging
import sqlite3
import os
import random
import time
from datetime import timedelta, date
import html
import json # Для работы с JSON-файлами

from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from dotenv import load_dotenv

# --- ИМПОРТЫ ДЛЯ АНТИСПАМА ---
from typing import Callable, Dict, Any, Awaitable
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from cachetools import TTLCache

# --- Конфигурация ---
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("Не найден BOT_TOKEN. Проверьте переменные окружения (.env или настройки хостинга).")

DB_FILE = '/data/beer_game.db'
COOLDOWN_SECONDS = 3 * 60 * 60  # 3 часа для /beer
THROTTLE_TIME = 0.5 # Минимальный интервал между командами для антиспама

# --- НОВЫЕ ПАРАМЕТРЫ ДЛЯ КАРТ И ЕЖЕДНЕВНОГО БОНУСА ---
WIN_CHANCE = 60    # Шанс на выигрыш в % для /beer
LOSE_CHANCE = 40   # Шанс на проигрыш в % для /beer

CARD_DRAW_COST = 15 # Стоимость вытягивания карты в Фанкоинах
CARD_COOLDOWN_SECONDS = 2 * 60 * 60 # 2 часа для /draw_card

DAILY_BASE_COIN_BONUS = 20 # Базовый ежедневный бонус Фанкоинов
DAILY_BASE_RATING_BONUS = 5 # Базовый ежедневный бонус Рейтинга
# Список дополнительных Фанкоинов за стрик (индекс 0 = 1 день, индекс 1 = 2 дня и т.д.)
# Например: 1 день = 0 доп., 2 день = 5 доп., 3 день = 10 доп.
DAILY_STREAK_COIN_BONUSES = [0, 5, 10, 15, 20] 
DAILY_MAX_STREAK_BONUS_INDEX = len(DAILY_STREAK_COIN_BONUSES) - 1

# --- File IDs для изображений ---
SUCCESS_IMAGE_ID = "AgACAgIAAxkBAAICvGjMNGhCINSBAeXyX9w0VddF-C8PAAJt8jEbFbVhSmh8gDAZrTCaAQADAgADeQADNgQ"
FAIL_IMAGE_ID = "AgACAgIAAxkBAAICwGjMNRAnAAHo1rDMPfaF_HUa0WzxaAACcvIxGxW1YUo5jEQQRkt4kgEAAwIAA3kAAzYE"
COOLDOWN_IMAGE_ID = "AgACAgIAAxkBAAICxWjMNXRNIOw6PJstVS2P6oFnW6wHAAJF-TEbLqthShzwv65k4n-MAQADAgADeQADNgQ"
TOP_IMAGE_ID = "AgACAgIAAxkBAAICw2jMNUqWi1d-ctjc67_Ryg9uLmBHAAJC-TEbLqthSiv8cCgp6EMnAQADAgADeQADNgQ"
# НОВАЯ КАРТИНКА ДЛЯ ЕЖЕДНЕВНОГО БОНУСА
DAILY_IMAGE_ID = "AgACAgIAAxkBAAID-2jWl_2tS0l36d_F42aI2zV_1dI7AAI34jEb5J_xSCu_t_37b98BAAMCAAN5AAM2BA" # ВСТАВЬТЕ СЮДА ВАШ FILE_ID ДЛЯ DAILY

logging.basicConfig(level=logging.INFO)

# --- ГЛОБАЛЬНАЯ КОЛОДА КАРТ ---
CARD_DECK = [] # Будет загружена из cards.json при запуске

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

# --- Управление базой данных (ОБНОВЛЕНО: добавлены coins, last_card_time, daily_streak, last_daily_claim_date) ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT NOT NULL,
            rating INTEGER DEFAULT 0,
            coins INTEGER DEFAULT 0, -- НОВОЕ ПОЛЕ: Фанкоины
            last_beer_time INTEGER DEFAULT 0,
            last_card_time INTEGER DEFAULT 0, -- НОВОЕ ПОЛЕ: для кулдауна карт
            last_daily_claim_date TEXT DEFAULT '1970-01-01', -- НОВОЕ ПОЛЕ: Дата последнего ежедневного бонуса
            daily_streak INTEGER DEFAULT 0 -- НОВОЕ ПОЛЕ: Счётчик ежедневных заходов
        )
    ''')
    conn.commit()
    conn.close()
    logging.info("База данных успешно инициализирована/обновлена.")

def get_user_data(user_id: int):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    # ОБНОВЛЕНО: Запрос всех новых полей
    cursor.execute("SELECT username, rating, coins, last_beer_time, last_card_time, last_daily_claim_date, daily_streak FROM users WHERE user_id = ?", (user_id,))
    user_data = cursor.fetchone()
    conn.close()
    return user_data

def add_or_update_user(user_id: int, username: str):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    # ОБНОВЛЕНО: При первом добавлении/обновлении можно дать стартовые монеты
    cursor.execute(
        "INSERT INTO users (user_id, username, coins) VALUES (?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET username = EXCLUDED.username",
        (user_id, username, 50) # Даем 50 Фанкоинов при первом /start
    )
    conn.commit()
    conn.close()

# ОБНОВЛЕНО: Функция для обновления рейтинга, монет и времени пива
def update_user_beer_data(user_id: int, new_rating: int, new_coins: int, current_time: int):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET rating = ?, coins = ?, last_beer_time = ? WHERE user_id = ?",
        (new_rating, new_coins, current_time, user_id)
    )
    conn.commit()
    conn.close()

# НОВАЯ ФУНКЦИЯ: Обновление данных после вытягивания карты
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

# НОВАЯ ФУНКЦИЯ: Обновление данных после ежедневного бонуса
def update_user_daily_data(user_id: int, new_rating: int, new_coins: int, current_date_str: str, new_streak: int):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET rating = ?, coins = ?, last_daily_claim_date = ?, daily_streak = ? WHERE user_id = ?",
        (new_rating, new_coins, current_date_str, new_streak, user_id)
    )
    conn.commit()
    conn.close()

# НОВАЯ ФУНКЦИЯ: Обновление монет для другого пользователя (для "Щедрого Соседа")
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

# НОВАЯ ФУНКЦИЯ: Загрузка колоды карт из JSON файла
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

# НОВАЯ ФУНКЦИЯ: Выбор случайной карты из колоды по весу
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
    # ОБНОВЛЕНО: add_or_update_user теперь даёт стартовые монеты
    add_or_update_user(user_id, username)

    if user_data:
        # ОБНОВЛЕНО: Сообщение теперь упоминает Фанкоины
        await message.answer(f"С возвращением, {username}! Рады снова видеть тебя в баре. 🍻")
    else:
         await message.answer(
            f"Добро пожаловать в бар, {username}! 🍻\n\n"
            "Здесь мы соревнуемся, кто больше выпьет пива и кто богаче на Фанкоины!\n"
            "Используй команду /beer, чтобы испытать удачу!\n"
            "Получи ежедневный бонус: /daily\n"
            "Попробуй вытянуть карту судьбы: /draw_card\n"
            "Проверить свой профиль: /profile\n"
            "Посмотреть на лучших: /top\n"
            "Нужна помощь? /help"
        )

@router.message(Command("profile"))
async def cmd_profile(message: Message):
    user_id = message.from_user.id
    user_data = get_user_data(user_id)
    
    if user_data:
        # ОБНОВЛЕНО: Отображение Фанкоинов в профиле
        username, rating, coins, _, _, _, _ = user_data
        await message.answer(
            f"👤 <b>Твой профиль:</b>\n\n"
            f"Имя: <b>{username}</b>\n"
            f"Рейтинг: <b>{rating}</b> 🍺\n"
            f"Фанкоины: <b>{coins}</b> 🪙",
            parse_mode="HTML"
        )
    else:
        await message.answer("Ты еще не зарегистрирован. Нажми /start, чтобы начать игру.")

@router.message(Command("beer"))
async def cmd_beer(message: Message):
    user_id = message.from_user.id
    current_time = int(time.time())

    user_data = get_user_data(user_id)

    if not user_data:
        await message.answer("Сначала зарегистрируйся с помощью команды /start.")
        return

    username, rating, coins, last_beer_time, _, _, _ = user_data

    time_passed = current_time - last_beer_time
    if time_passed < COOLDOWN_SECONDS:
        time_left = COOLDOWN_SECONDS - time_passed
        time_left_formatted = str(timedelta(seconds=time_left))
        await message.answer_photo(
            photo=COOLDOWN_IMAGE_ID,
            caption=f"Ты уже недавно пил! ⏳\nПопробуй снова через: <b>{time_left_formatted}</b>",
            parse_mode="HTML"
        )
        return

    # Определяем исход на основе заданных процентов
    roll = random.randint(1, 100)
    
    rating_change_amount = random.randint(1, 10)
    coin_bonus = random.randint(1, 2) # Бонус Фанкоинов за каждый /beer

    new_rating = rating
    new_coins = coins + coin_bonus
    
    caption_text = ""
    photo_id = ""

    if roll <= WIN_CHANCE:
        # Успех
        new_rating = rating + rating_change_amount
        caption_text = f"😏🍻 Ты успешно бахнул на <b>+{rating_change_amount}</b> 🍺 пива! Получаешь <b>+{coin_bonus}</b> 🪙 Фанкоинов!"
        photo_id = SUCCESS_IMAGE_ID
    else:
        # Неудача
        potential_new_rating = rating - rating_change_amount
        if potential_new_rating < 0:
            actual_loss = rating
            new_rating = 0
            caption_text = f"🤬🍻 Братья Уизли отжали у тебя все <b>{actual_loss}</b> 🍺 пива! Ты на нуле, но получаешь <b>+{coin_bonus}</b> 🪙 Фанкоинов."
        else:
            actual_loss = rating_change_amount
            new_rating = potential_new_rating
            caption_text = f"🤬🍻 Братья Уизли отжали у тебя <b>{actual_loss}</b> 🍺 пива, но ты всё равно получаешь <b>+{coin_bonus}</b> 🪙 Фанкоинов!"
        photo_id = FAIL_IMAGE_ID
    
    update_user_beer_data(user_id, new_rating, new_coins, current_time)
    await message.answer_photo(photo=photo_id, caption=caption_text, parse_mode="HTML")

# НОВАЯ КОМАНДА: /daily
@router.message(Command("daily"))
async def cmd_daily(message: Message):
    user_id = message.from_user.id
    current_time = int(time.time())
    current_date = date.today()
    current_date_str = current_date.isoformat() # 'YYYY-MM-DD'

    user_data = get_user_data(user_id)
    if not user_data:
        await message.answer("Сначала зарегистрируйся с помощью команды /start.")
        return

    username, rating, coins, _, _, last_daily_claim_date, daily_streak = user_data

    # Проверяем, был ли уже получен бонус сегодня
    if last_daily_claim_date == current_date_str:
        time_left_until_tomorrow = datetime.combine(current_date + timedelta(days=1), time(0, 0, 0)) - datetime.now()
        hours, remainder = divmod(int(time_left_until_tomorrow.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        time_left_formatted = f"{hours}ч {minutes}м {seconds}с"
        await message.answer_photo(
            photo=COOLDOWN_IMAGE_ID, # Можно использовать другую картинку для ежедневного кулдауна, если есть
            caption=f"⏰ **Рановато!** Ежедневный бонус можно получить завтра. Осталось: <b>{time_left_formatted}</b>",
            parse_mode="HTML"
        )
        return

    # Проверяем стрик
    if last_daily_claim_date == (current_date - timedelta(days=1)).isoformat():
        # Стрик продолжается
        new_streak = daily_streak + 1
    else:
        # Стрик прерван или начинается
        new_streak = 1
    
    # Ограничиваем стрик для бонусов
    streak_bonus_index = min(new_streak - 1, DAILY_MAX_STREAK_BONUS_INDEX)
    bonus_coins = DAILY_BASE_COIN_BONUS + DAILY_STREAK_COIN_BONUSES[streak_bonus_index]
    bonus_rating = DAILY_BASE_RATING_BONUS

    new_coins = coins + bonus_coins
    new_rating = rating + bonus_rating

    update_user_daily_data(user_id, new_rating, new_coins, current_date_str, new_streak)

    caption_text = f"🎉 **Ежедневный бонус!** Ты получил <b>+{bonus_coins}</b> 🪙 Фанкоинов и <b>+{bonus_rating}</b> 🍺 рейтинга!"
    if new_streak > 1:
        caption_text += f"\nТвой стрик: <b>{new_streak} дней</b> (+{DAILY_STREAK_COIN_BONUSES[streak_bonus_index]} 🪙 за серию)!"

    await message.answer_photo(photo=DAILY_IMAGE_ID, caption=caption_text, parse_mode="HTML")

# НОВАЯ КОМАНДА: /draw_card
@router.message(Command("draw_card"))
async def cmd_draw_card(message: Message):
    user_id = message.from_user.id
    current_time = int(time.time())

    user_data = get_user_data(user_id)
    if not user_data:
        await message.answer("Сначала зарегистрируйся с помощью команды /start.")
        return

    username, rating, coins, _, last_card_time, _, _ = user_data

    # Проверка кулдауна для карт
    time_passed = current_time - last_card_time
    if time_passed < CARD_COOLDOWN_SECONDS:
        time_left = CARD_COOLDOWN_SECONDS - time_passed
        time_left_formatted = str(timedelta(seconds=time_left))
        await message.answer_photo(
            photo=COOLDOWN_IMAGE_ID, # Можно использовать другую картинку для кулдауна карт
            caption=f"Колода ещё не перемешана! ⏳\nПопробуй вытянуть карту через: <b>{time_left_formatted}</b>",
            parse_mode="HTML"
        )
        return

    # Проверка наличия Фанкоинов
    if coins < CARD_DRAW_COST:
        await message.answer(
            f"Не хватает Фанкоинов! 😔 Для вытягивания карты нужно <b>{CARD_DRAW_COST}</b> 🪙, а у тебя только <b>{coins}</b> 🪙.",
            parse_mode="HTML"
        )
        return

    # Списываем стоимость
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

    # Применяем эффекты
    rating_change = random.randint(effects.get('rating_change_min', 0), effects.get('rating_change_max', 0))
    coin_change = random.randint(effects.get('coin_change_min', 0), effects.get('coin_change_max', 0))
    
    new_rating = max(0, new_rating + rating_change) # Рейтинг не может быть ниже 0
    new_coins = max(0, new_coins + coin_change) # Монеты не могут быть ниже 0

    beer_cooldown_reset = effects.get('cooldown_reset_beer', False)
    target_other_coin_change = effects.get('target_other_coin_change', 0)

    final_description = card_description # Сообщение, которое отправится игроку

    if target_other_coin_change > 0:
        # Находим случайного другого пользователя
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM users WHERE user_id != ? ORDER BY RANDOM() LIMIT 1", (user_id,))
        other_user_id = cursor.fetchone()
        conn.close()

        if other_user_id:
            other_user_id = other_user_id[0]
            update_other_user_coins(other_user_id, target_other_coin_change)
            # Отправляем уведомление другому игроку, если это возможно (например, если он в ЛС с ботом)
            try:
                # ОБНОВЛЕНО: Делаем описание для "Щедрого Соседа" более динамичным
                # description_args = (abs(coin_change), abs(target_other_coin_change), target_other_coin_change)
                # final_description = card_description % description_args
                other_user_data = get_user_data(other_user_id)
                if other_user_data:
                    other_username = html.escape(other_user_data[0])
                    await bot.send_message(
                        other_user_id,
                        f"🎉 **Сюрприз!** Игрок <b>{username}</b> был сегодня щедр и угостил тебя <b>+{target_other_coin_change}</b> 🪙 Фанкоинов!",
                        parse_mode="HTML"
                    )
            except Exception as e:
                logging.warning(f"Не удалось отправить уведомление другому игроку {other_user_id}: {e}")
        else:
            final_description += "\n(Но никого другого в баре не оказалось, чтобы угостить!)"
            # Если нет других пользователей, монеты просто пропадают или возвращаются игроку
            new_coins = new_coins - coin_change # Отменяем потерю монет, если некого угощать
            new_rating = max(0, new_rating - rating_change) # Отменяем бонус рейтинга, если некого угощать
            
    # Форматируем описание карты, если есть динамические значения
    if '%d' in card_description:
        # Собираем аргументы для форматирования строки
        description_args = []
        if 'coin_change_min' in effects and 'coin_change_max' in effects:
            val = abs(random.randint(effects['coin_change_min'], effects['coin_change_max']))
            if val > 0: description_args.append(val)
        if 'rating_change_min' in effects and 'rating_change_max' in effects:
            val = abs(random.randint(effects['rating_change_min'], effects['rating_change_max']))
            if val > 0: description_args.append(val)
        
        # Для Щедрого Соседа, описание специфично
        if chosen_card['id'] == 'generous_neighbor':
             description_args = [abs(coin_change), abs(rating_change), target_other_coin_change]

        try:
            final_description = card_description % tuple(description_args)
        except TypeError:
            logging.warning(f"Ошибка форматирования описания для карты {card_name}. Описание: {card_description}, Аргументы: {description_args}")
            final_description = card_description # Возвращаемся к базовому описанию, если ошибка

    # Обновляем данные пользователя
    update_user_card_data(user_id, new_rating, new_coins, current_time, beer_cooldown_reset)

    # Отправляем результат
    caption_message = (
        f"🃏 **Ты вытянул карту: '{card_name}'** 🃏\n\n"
        f"{final_description}\n\n"
        f"Твой новый рейтинг: <b>{new_rating}</b> 🍺\n"
        f"Твои новые Фанкоины: <b>{new_coins}</b> 🪙"
    )
    await message.answer_photo(photo=card_image_id, caption=caption_message, parse_mode="HTML")

@router.message(Command("top"))
async def cmd_top(message: Message):
    top_users = get_top_users()

    if not top_users:
        await message.answer("В баре пока никого нет, ты можешь стать первым! 🍻")
        return

    response_text = "🏆 <b>Топ-10 лучших пивохлёбов:</b>\n\n"
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    
    for i, (username, rating) in enumerate(top_users, 1):
        place_icon = medals.get(i, f"<b>{i}.</b>")
        response_text += f"{place_icon} {username} — <b>{rating}</b> 🍺\n"
        
    await message.answer_photo(
        photo=TOP_IMAGE_ID,
        caption=response_text,
        parse_mode="HTML"
    )

@router.message(Command("help"))
async def cmd_help(message: Message):
    help_text = (
        "<b>🍻 Правила Игры в Пивном Баре 🍻</b>\n\n"
        "Это простая игра, где ты соревнуешься за самый высокий пивной рейтинг и копишь Фанкоины!\n\n"
        "<b>Основные команды:</b>\n"
        "/start - Начать игру и зарегистрироваться (или просто обновить свой профиль)\n"
        "/beer - Испытать удачу и получить (или потерять) пивной рейтинг. Кулдаун: 3 часа. Даёт Фанкоины.\n"
        "/daily - Получи ежедневный бонус Фанкоинов и рейтинга. Есть бонусы за серию!\n"
        "/draw_card - Вытяни карту судьбы за Фанкоины! Кулдаун: 2 часа.\n"
        "/profile - Посмотреть свой текущий рейтинг и количество Фанкоинов.\n"
        "/top - Увидеть 10 лучших игроков по пивному рейтингу.\n"
        "/help - Показать это сообщение."
    )
    await message.answer(help_text, parse_mode="HTML")

# Временный обработчик для получения FILE_ID (УДАЛИТЬ ПОСЛЕ использования!)
 @router.message(F.photo)
 async def get_photo_id(message: Message):
     if message.photo:
         file_id = message.photo[-1].file_id # Берем самое большое разрешение фото
         await message.answer(f"FILE_ID этого фото: `{file_id}`\n\nНе забудь удалить этот обработчик после получения всех ID!", parse_mode="Markdown")
         logging.info(f"Received photo FILE_ID: {file_id}")
# Удалить до этой строки.

async def main():
    global CARD_DECK # Объявляем, что будем использовать глобальную переменную
    init_db()
    CARD_DECK = load_card_deck() # Загружаем карты при старте
    
    router.message.middleware(ThrottlingMiddleware(throttle_time=THROTTLE_TIME))
    
    dp.include_router(router)
    await dp.start_polling(bot)

if __name__ == '__main__':
    # Обязательно импортируем datetime.time и datetime.datetime для cmd_daily
    from datetime import datetime, time
    asyncio.run(main())
