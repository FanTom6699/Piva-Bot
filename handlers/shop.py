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
# ✅ ИЗМЕНЕНО: Импортируем "Настройки" из farm_config.py
from .farm_config import SHOP_PRICES, FARM_ITEM_NAMES

# --- ИНИЦИАIIЛИЗАЦИЯ ---
shop_router = Router()

# --- КОНСТАНТЫ МАГАЗИНА (УДАЛЕНЫ) ---
# (Они теперь в farm_config.py)

# --- CALLBACKDATA ФАБРИКИ (Для кнопок) ---
class ShopCallback(CallbackData, prefix="shop"):
    action: str
    item_id: str = None
    quantity: int = 0

# --- ГЛАВНАЯ ФУНКЦИЯ: ГЕНЕРАТОР МЕНЮ МАГАЗИНА ---
async def get_shop_main_menu(db: Database, user_id: int) -> (str, InlineKeyboardMarkup):
    balance = await db.get_user_beer_rating(user_id)
    
    # ✅ ИЗМЕНЕНО: Используем FARM_ITEM_NAMES
    item_name_grain = FARM_ITEM_NAMES['семя_зерна']
    item_name_hops = FARM_ITEM_NAMES['семя_хмеля']
    
    text = (
        f"<b>🏪 Магазин Семян</b>\n\n"
        f"Здесь ты тратишь 🍺, чтобы купить семена для своего [🌾 Поля].\n\n"
        f"<i>Твой баланс: {balance} 🍺</i>\n\n"
        f"<b><u>Товары:</u></b>\n"
        f"• `{item_name_grain}` - <b>{SHOP_PRICES['семя_зерна']} 🍺 / шт.</b>\n"
        f"• `{item_name_hops}` - <b>{SHOP_PRICES['семя_хмеля']} 🍺 / шт.</b>"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=f"Купить {item_name_grain}", callback_data=ShopCallback(action="select_item", item_id="семя_зерна").pack()),
            InlineKeyboardButton(text=f"Купить {item_name_hops}", callback_data=ShopCallback(action="select_item", item_id="семя_хмеля").pack())
        ]
    ])
    
    return text, keyboard

# --- ГЛАВНАЯ ФУНКЦИЯ: ГЕНЕРАТОР МЕНЮ ПОКУПКИ (Твой "Умный" Магазин) ---
async def get_shop_buy_menu(db: Database, user_id: int, item_id: str) -> (str, InlineKeyboardMarkup):
    balance = await db.get_user_beer_rating(user_id)
    price = SHOP_PRICES.get(item_id, 99999)
    # ✅ ИЗМЕНЕНО: Используем FARM_ITEM_NAMES
    item_name = FARM_ITEM_NAMES.get(item_id, "??")
    
    max_buy = 0
    if balance > 0 and price > 0:
        max_buy = floor(balance / price)
        
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
    if max_buy >= 1:
        buttons.append(InlineKeyboardButton(text="Купить 1 шт", callback_data=ShopCallback(action="buy_item", item_id=item_id, quantity=1).pack()))
    if max_buy >= 10:
        buttons.append(InlineKeyboardButton(text="Купить 10 шт", callback_data=ShopCallback(action="buy_item", item_id=item_id, quantity=10).pack()))
    if max_buy >= 50:
        buttons.append(InlineKeyboardButton(text="Купить 50 шт", callback_data=ShopCallback(action="buy_item", item_id=item_id, quantity=50).pack()))
    
    if max_buy > 0 and max_buy not in [1, 10, 50]:
         buttons.append(InlineKeyboardButton(text=f"Купить MAX ({max_buy} шт)", callback_data=ShopCallback(action="buy_item", item_id=item_id, quantity=max_buy).pack()))

    keyboard_rows = [buttons[i:i + 3] for i in range(0, len(buttons), 3)]
    
    keyboard_rows.append([
        InlineKeyboardButton(text="⬅️ Назад в Магазин", callback_data=ShopCallback(action="menu").pack())
    ])
    
    return text, InlineKeyboardMarkup(inline_keyboard=keyboard_rows)


# --- ХЭНДЛЕРЫ ---
@shop_router.message(Command("shop"))
async def cmd_shop(message: Message, bot: Bot, db: Database):
    user_id = message.from_user.id
    if not await check_user_registered(message, bot, db):
        return
    text, keyboard = await get_shop_main_menu(db, user_id)
    await message.answer(text, reply_markup=keyboard)

@shop_router.callback_query(ShopCallback.filter(F.action == "menu"))
async def cq_shop_menu(callback: CallbackQuery, bot: Bot, db: Database):
    user_id = callback.from_user.id
    text, keyboard = await get_shop_main_menu(db, user_id)
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()

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
    # ✅ ИЗМЕНЕНО: Используем FARM_ITEM_NAMES
    item_name = FARM_ITEM_NAMES.get(item_id, "??")

    balance = await db.get_user_beer_rating(user_id)
    if balance < total_cost:
        await callback.answer(f"⛔ Недостаточно 🍺! Нужно {total_cost} 🍺, у тебя {balance} 🍺.", show_alert=True)
        text, keyboard = await get_shop_buy_menu(db, user_id, item_id)
        with suppress(TelegramBadRequest):
            await callback.message.edit_text(text, reply_markup=keyboard)
        return

    try:
        await db.change_rating(user_id, -total_cost)
        await db.modify_inventory(user_id, item_id, quantity)
    except Exception as e:
        logging.error(f"Критическая ошибка при покупке (user: {user_id}, item: {item_id}): {e}")
        await callback.answer("⛔ Произошла ошибка базы данных при покупке!", show_alert=True)
        return

    await callback.answer(f"✅ Успешно! Ты купил {quantity} {item_name} за {total_cost} 🍺.", show_alert=True)
    
    text, keyboard = await get_shop_buy_menu(db, user_id, item_id)
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(text, reply_markup=keyboard)
