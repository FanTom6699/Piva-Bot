# handlers/shop.py
import logging
from math import floor
from contextlib import suppress

from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters.callback_data import CallbackData
from aiogram.exceptions import TelegramBadRequest

from database import Database
from .farm_config import FARM_ITEM_NAMES, SHOP_PRICES
# (Импортируем FarmCallback, чтобы кнопка "Назад" работала)
from .farm import FarmCallback, check_owner

# --- ИНИЦИАЛИЗАЦИЯ ---
shop_router = Router()

# --- CALLBACKDATA ---
class ShopCallbackData(CallbackData, prefix="shop"):
    action: str
    owner_id: int
    item_id: str = "none"
    quantity: int = 0

# --- ГЕНЕРАТОРЫ МЕНЮ ---

async def get_shop_menu(user_id: int, db: Database, owner_id: int) -> (str, InlineKeyboardMarkup):
    """(Главное меню Магазина) Генерирует текст и кнопки."""
    
    balance = await db.get_user_beer_rating(user_id)
    
    item_name_grain = FARM_ITEM_NAMES['семя_зерна']
    item_name_hops = FARM_ITEM_NAMES['семя_хмеля']
    price_grain = SHOP_PRICES['семя_зерна']
    price_hops = SHOP_PRICES['семя_хмеля']

    text = (
        f"<b>🏪 Магазин Семян</b>\n"
        f"<i>Твой баланс: {balance} 🍺</i>\n\n"
        f"<b><u>Товары (для 🌾 Поля):</u></b>\n\n"
        
        f"• <b>Товар:</b> <code>{item_name_grain}</code>\n"
        f"  <b>Цена: {price_grain} 🍺 / шт.</b>\n\n"
        
        f"• <b>Товар:</b> <code>{item_name_hops}</code>\n"
        f"  <b>Цена: {price_hops} 🍺 / шт.</b>\n\n"
        
        f"<i>Нажми на кнопку ниже, чтобы выбрать количество.</i>"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=f"Купить 🌾 Зерно ({price_grain} 🍺)", 
                callback_data=ShopCallbackData(action="buy_menu", owner_id=owner_id, item_id="семя_зерна").pack()
            )
        ],
        [
            InlineKeyboardButton(
                text=f"Купить 🌱 Хмель ({price_hops} 🍺)", 
                callback_data=ShopCallbackData(action="buy_menu", owner_id=owner_id, item_id="семя_хмеля").pack()
            )
        ],
        [
            InlineKeyboardButton(
                text="⬅️ Назад на Ферму", 
                callback_data=FarmCallback(action="main_dashboard", owner_id=owner_id).pack()
            )
        ]
    ])
    
    return text, keyboard

async def get_buy_menu(user_id: int, db: Database, owner_id: int, item_id: str) -> (str, InlineKeyboardMarkup):
    """(Меню выбора кол-ва) Генерирует текст и кнопки."""
    
    balance = await db.get_user_beer_rating(user_id)
    item_name = FARM_ITEM_NAMES[item_id]
    price = SHOP_PRICES[item_id]
    
    # (Рассчитываем МАКС, сколько он может купить)
    max_buy = 0
    if price > 0:
        max_buy = floor(balance / price)

    text = (
        f"<b>Покупка: {item_name}</b>\n"
        f"<i>Твой баланс: {balance} 🍺</i>\n"
        f"<i>Цена: {price} 🍺 / шт.</i>\n\n"
        f"<b>Сколько хочешь купить?</b>\n"
        f"(Максимум: {max_buy} шт.)"
    )
    
    buttons = []
    if max_buy >= 1:
        buttons.append(InlineKeyboardButton(
            text=f"Купить 1 (Стоит: {price*1} 🍺)", 
            callback_data=ShopCallbackData(action="buy_confirm", owner_id=owner_id, item_id=item_id, quantity=1).pack()
        ))
    if max_buy >= 5:
        buttons.append(InlineKeyboardButton(
            text=f"Купить 5 (Стоит: {price*5} 🍺)", 
            callback_data=ShopCallbackData(action="buy_confirm", owner_id=owner_id, item_id=item_id, quantity=5).pack()
        ))
    if max_buy >= 10:
        buttons.append(InlineKeyboardButton(
            text=f"Купить 10 (Стоит: {price*10} 🍺)", 
            callback_data=ShopCallbackData(action="buy_confirm", owner_id=owner_id, item_id=item_id, quantity=10).pack()
        ))
    if max_buy > 0 and max_buy not in [1, 5, 10]:
         buttons.append(InlineKeyboardButton(
            text=f"Купить MAX ({max_buy}) (Стоит: {price*max_buy} 🍺)", 
            callback_data=ShopCallbackData(action="buy_confirm", owner_id=owner_id, item_id=item_id, quantity=max_buy).pack()
        ))
        
    if not buttons:
        text += f"\n\n<b>⛔ Недостаточно 🍺</b> для покупки 1 шт."

    keyboard_rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    
    keyboard_rows.append([
        InlineKeyboardButton(
            text="⬅️ Назад в Магазин", 
            callback_data=ShopCallbackData(action="back_to_shop", owner_id=owner_id).pack()
        )
    ])

    return text, InlineKeyboardMarkup(inline_keyboard=keyboard_rows)


# --- ХЭНДЛЕРЫ КНОПОК МАГАЗИНА ---

# (Этот хэндлер вызывается из farm.py)
# @farm_router.callback_query(FarmCallback.filter(F.action == "shop"))

@shop_router.callback_query(ShopCallbackData.filter(F.action == "back_to_shop"))
async def cq_shop_back_to_main(callback: CallbackQuery, callback_data: ShopCallbackData, db: Database):
    """(Кнопка Назад) Возвращает в Главное Меню Магазина."""
    if not await check_owner(callback, callback_data.owner_id): return
    
    text, keyboard = await get_shop_menu(callback.from_user.id, db, callback_data.owner_id)
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()

@shop_router.callback_query(ShopCallbackData.filter(F.action == "buy_menu"))
async def cq_shop_buy_menu(callback: CallbackQuery, callback_data: ShopCallbackData, db: Database):
    """(Кнопка Купить) Показывает меню выбора количества."""
    if not await check_owner(callback, callback_data.owner_id): return
    
    text, keyboard = await get_buy_menu(
        user_id=callback.from_user.id, 
        db=db, 
        owner_id=callback_data.owner_id, 
        item_id=callback_data.item_id
    )
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()

@shop_router.callback_query(ShopCallbackData.filter(F.action == "buy_confirm"))
async def cq_shop_buy_confirm(callback: CallbackQuery, callback_data: ShopCallbackData, db: Database):
    """(Кнопка 1/5/10/MAX) Выполняет покупку."""
    if not await check_owner(callback, callback_data.owner_id): return
    
    user_id = callback.from_user.id
    item_id = callback_data.item_id
    quantity = callback_data.quantity
    
    price_per_one = SHOP_PRICES[item_id]
    total_cost = price_per_one * quantity

    # (Проверка баланса на всякий случай)
    balance = await db.get_user_beer_rating(user_id)
    if balance < total_cost:
        await callback.answer("⛔ Недостаточно 🍺! Баланс мог измениться.", show_alert=True)
        # (Обновляем меню, чтобы показать актуальный баланс)
        await cq_shop_buy_menu(callback, callback_data, db)
        return

    try:
        # (Сначала списываем 🍺, потом начисляем семена)
        await db.change_rating(user_id, -total_cost)
        await db.modify_inventory(user_id, item_id, quantity)
        
        await callback.answer(
            f"✅ Покупка Успешна!\n"
            f"Куплено: {quantity} x {FARM_ITEM_NAMES[item_id]}\n"
            f"Потрачено: {total_cost} 🍺",
            show_alert=True
        )
                            
    except Exception as e:
        logging.error(f"Критическая ошибка /shop (user: {user_id}): {e}")
        # (Если произошла ошибка, лучше вернуть 🍺)
        await db.change_rating(user_id, total_cost)
        await callback.answer("⛔ Критическая Ошибка! Твои 🍺 возвращены.", show_alert=True)
    
    # (Возвращаемся в Главное Меню Магазина, чтобы показать новый баланс)
    await cq_shop_back_to_main(callback, callback_data, db)
