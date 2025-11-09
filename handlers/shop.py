# handlers/shop.py
import logging
from math import floor

from aiogram import Router, F, Bot, html
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.exceptions import TelegramBadRequest
from contextlib import suppress

from database import Database
from .common import check_user_registered

# --- ИНИЦИАIIЛИЗАЦИЯ ---
shop_router = Router()

# --- КОНСТАНТЫ МАГАЗИНА (Наш План) ---
SHOP_PRICES = {
    # item_id (из database.py) : Цена в 🍺
    "семя_зерна": 2,
    "семя_хмеля": 5,
}

SHOP_NAMES = {
    "семя_зерна": "🌾 Семя Зерна",
    "семя_хмеля": "🌱 Семя Хмеля",
}

# --- CALLBACKDATA ФАБРИКИ (Для кнопок) ---

class ShopCallback(CallbackData, prefix="shop"):
    action: str
    item_id: str = None
    quantity: int = 0
    # action:
    # 'menu' - Показать главное меню магазина
    # 'select_item' - Показать меню выбора кол-ва (Твой "Умный" магазин)
    # 'buy_item' - Финальная покупка

# --- ГЛАВНАЯ ФУНКЦИЯ: ГЕНЕРАТОР МЕНЮ МАГАЗИНА ---

async def get_shop_main_menu(db: Database, user_id: int) -> (str, InlineKeyboardMarkup):
    """
    Генерирует Главное Меню Магазина.
    (Твой план: Показывает баланс и цены)
    """
    balance = await db.get_user_beer_rating(user_id)
    
    text = (
        f"<b>🏪 Магазин Семян</b>\n\n"
        f"Здесь ты тратишь 🍺, чтобы купить семена для своего [🌾 Поля].\n\n"
        f"<i>Твой баланс: {balance} 🍺</i>\n\n"
        f"<b><u>Товары:</u></b>\n"
        f"• `{SHOP_NAMES['семя_зерна']}` - <b>{SHOP_PRICES['семя_зерна']} 🍺 / шт.</b>\n"
        f"• `{SHOP_NAMES['семя_хмеля']}` - <b>{SHOP_PRICES['семя_хмеля']} 🍺 / шт.</b>"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=f"Купить {SHOP_NAMES['семя_зерна']}", callback_data=ShopCallback(action="select_item", item_id="семя_зерна").pack()),
            InlineKeyboardButton(text=f"Купить {SHOP_NAMES['семя_хмеля']}", callback_data=ShopCallback(action="select_item", item_id="семя_хмеля").pack())
        ]
        # Можно добавить кнопку [Закрыть], но пока не будем, 
        # т.к. /farm все равно пришлет новое сообщение
    ])
    
    return text, keyboard

# --- ГЛАВНАЯ ФУНКЦИЯ: ГЕНЕРАТОР МЕНЮ ПОКУПКИ (Твой "Умный" Магазин) ---

async def get_shop_buy_menu(db: Database, user_id: int, item_id: str) -> (str, InlineKeyboardMarkup):
    """
    Генерирует Меню Выбора Количества.
    (Твой план: Считает MAX и показывает кнопки 1, 10, MAX)
    """
    balance = await db.get_user_beer_rating(user_id)
    price = SHOP_PRICES.get(item_id, 99999)
    item_name = SHOP_NAMES.get(item_id, "??")
    
    # Твой "Умный" расчет: Сколько MAX он может купить
    max_buy = 0
    if balance > 0 and price > 0:
        max_buy = floor(balance / price) # Округляем ВНИЗ
        
    text = (
        f"<b>Покупка: {item_name}</b> (Цена: {price} 🍺)\n\n"
        f"<i>Твой баланс: {balance} 🍺</i>\n\n"
        f"<b>Сколько ты хочешь взять?</b>\n"
    )
    
    if max_buy > 0:
        text += f"<i>Ты можешь позволить себе {max_buy} шт.</i>"
    else:
        text += "<i>Недостаточно 🍺 для покупки.</i>"

    buttons = []
    # Динамически добавляем кнопки, только если их можно купить
    if max_buy >= 1:
        buttons.append(InlineKeyboardButton(text="Купить 1 шт", callback_data=ShopCallback(action="buy_item", item_id=item_id, quantity=1).pack()))
    if max_buy >= 10:
        buttons.append(InlineKeyboardButton(text="Купить 10 шт", callback_data=ShopCallback(action="buy_item", item_id=item_id, quantity=10).pack()))
    if max_buy >= 50:
        buttons.append(InlineKeyboardButton(text="Купить 50 шт", callback_data=ShopCallback(action="buy_item", item_id=item_id, quantity=50).pack()))
    
    # Кнопка MAX (только если она > 0 и не равна 1, 10 или 50)
    if max_buy > 0 and max_buy not in [1, 10, 50]:
         buttons.append(InlineKeyboardButton(text=f"Купить MAX ({max_buy} шт)", callback_data=ShopCallback(action="buy_item", item_id=item_id, quantity=max_buy).pack()))

    # Группируем кнопки по 3 в ряд
    keyboard_rows = [buttons[i:i + 3] for i in range(0, len(buttons), 3)]
    
    # Кнопка "Назад"
    keyboard_rows.append([
        InlineKeyboardButton(text="⬅️ Назад в Магазин", callback_data=ShopCallback(action="menu").pack())
    ])
    
    return text, InlineKeyboardMarkup(inline_keyboard=keyboard_rows)


# --- ХЭНДЛЕРЫ ---

@shop_router.message(Command("shop"))
async def cmd_shop(message: Message, bot: Bot, db: Database):
    user_id = message.from_user.id
    
    # 0. Проверка на регистрацию
    if not await check_user_registered(message, bot, db):
        return

    # 1. Показываем Главное Меню Магазина
    text, keyboard = await get_shop_main_menu(db, user_id)
    await message.answer(text, reply_markup=keyboard)

# --- Навигация: Назад в Главное Меню Магазина ---
@shop_router.callback_query(ShopCallback.filter(F.action == "menu"))
async def cq_shop_menu(callback: CallbackQuery, bot: Bot, db: Database):
    user_id = callback.from_user.id
    
    text, keyboard = await get_shop_main_menu(db, user_id)
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()

# --- Шаг 1: Игрок выбрал, ЧТО купить (Показываем "Умное" меню) ---
@shop_router.callback_query(ShopCallback.filter(F.action == "select_item"))
async def cq_shop_select_item(callback: CallbackQuery, callback_data: ShopCallback, bot: Bot, db: Database):
    user_id = callback.from_user.id
    item_id = callback_data.item_id
    
    if item_id not in SHOP_PRICES:
        await callback.answer("⛔ Ошибка! Такого товара нет.", show_alert=True)
        return

    text, keyboard = await get_shop_buy_menu(db, user_id, item_id)
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()

# --- Шаг 2: Игрок выбрал, СКОЛЬКО купить (Финальная Покупка) ---
@shop_router.callback_query(ShopCallback.filter(F.action == "buy_item"))
async def cq_shop_buy_item(callback: CallbackQuery, callback_data: ShopCallback, bot: Bot, db: Database):
    user_id = callback.from_user.id
    item_id = callback_data.item_id
    quantity = callback_data.quantity
    
    if item_id not in SHOP_PRICES or quantity <= 0:
        await callback.answer("⛔ Ошибка! Неверное количество.", show_alert=True)
        return

    price_per_one = SHOP_PRICES[item_id]
    total_cost = price_per_one * quantity
    
    item_name = SHOP_NAMES[item_id]

    # 1. Проверяем баланс (ЕЩЕ РАЗ, на всякий случай)
    balance = await db.get_user_beer_rating(user_id)
    if balance < total_cost:
        await callback.answer(f"⛔ Недостаточно 🍺! Нужно {total_cost} 🍺, у тебя {balance} 🍺.", show_alert=True)
        # Обновляем меню на случай, если баланс изменился
        text, keyboard = await get_shop_buy_menu(db, user_id, item_id)
        with suppress(TelegramBadRequest):
            await callback.message.edit_text(text, reply_markup=keyboard)
        return

    # 2. Атомная операция: Тратим 🍺 и Добавляем "Семена"
    try:
        # Тратим 🍺
        await db.change_rating(user_id, -total_cost)
        # Добавляем "Семена" на Склад
        await db.modify_inventory(user_id, item_id, quantity)
        
    except Exception as e:
        logging.error(f"Критическая ошибка при покупке (user: {user_id}, item: {item_id}): {e}")
        await callback.answer("⛔ Произошла ошибка базы данных при покупке!", show_alert=True)
        return

    # 3. Показываем Уведомление
    await callback.answer(f"✅ Успешно! Ты купил {quantity} {item_name} за {total_cost} 🍺.", show_alert=True)
    
    # 4. Обновляем "Умное" меню (с новым балансом)
    text, keyboard = await get_shop_buy_menu(db, user_id, item_id)
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(text, reply_markup=keyboard)
