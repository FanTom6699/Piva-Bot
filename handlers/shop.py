# handlers/shop.py
import logging
from contextlib import suppress

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters.callback_data import CallbackData
from aiogram.exceptions import TelegramBadRequest

from database import Database
from .common import check_user_registered
from .farm import FarmCallback, check_owner, back_btn_to_farm # (Импортируем хэлперы из farm.py)
from .farm_config import SHOP_PRICES, FARM_ITEM_NAMES

# --- ИНИЦИАЛИЗАЦИЯ ---
shop_router = Router()

# --- CALLBACKDATA ---
class ShopCallback(CallbackData, prefix="shop_buy"):
    action: str # 'buy'
    item_id: str # 'семя_зерна' or 'семя_хмеля'
    quantity: int
    owner_id: int

# --- ✅✅✅ "АДАПТИВНЫЙ" ДИЗАЙН (Piva Bot) ✅✅✅ ---
# --- RENDER: МЕНЮ МАГАЗИНА ---
async def get_shop_menu(user_id: int, db: Database, owner_id: int) -> (str, InlineKeyboardMarkup):
    
    balance = await db.get_user_beer_rating(user_id)
    inventory = await db.get_user_inventory(user_id)
    
    # --- Данные по Зерну ---
    item_g = 'семя_зерна'
    price_g = SHOP_PRICES.get(item_g, 0)
    stock_g = inventory.get(item_g, 0)
    
    # --- Данные по Хмелю ---
    item_h = 'семя_хмеля'
    price_h = SHOP_PRICES.get(item_h, 0)
    stock_h = inventory.get(item_h, 0)

    # --- Текст (Piva Bot: "Адаптивный" дизайн) ---
    text = (
        f"🏪 <b>МАГАЗИН</b>\n"
        f"<code>══════════════════</code>\n"
        f"Баланс: <b>{balance} 🍺</b>\n"
        f"<code>══════════════════</code>\n\n"
        
        f"🌾 <b>{FARM_ITEM_NAMES[item_g]}</b>\n"
        f"• Цена: <code>{price_g} 🍺</code>\n"
        f"• На складе: <code>{stock_g} шт.</code>"
    )

    # Кнопки Зерна
    kb = [
        [
            InlineKeyboardButton(text="🌾 1", callback_data=ShopCallback(action="buy", item_id=item_g, quantity=1, owner_id=owner_id).pack()),
            InlineKeyboardButton(text="🌾 5", callback_data=ShopCallback(action="buy", item_id=item_g, quantity=5, owner_id=owner_id).pack()),
            InlineKeyboardButton(text="🌾 10", callback_data=ShopCallback(action="buy", item_id=item_g, quantity=10, owner_id=owner_id).pack())
        ]
    ]

    text += (
        f"\n\n🌱 <b>{FARM_ITEM_NAMES[item_h]}</b>\n"
        f"• Цена: <code>{price_h} 🍺</code>\n"
        f"• На складе: <code>{stock_h} шт.</code>"
    )
    
    # Кнопки Хмеля
    kb.append(
        [
            InlineKeyboardButton(text="🌱 1", callback_data=ShopCallback(action="buy", item_id=item_h, quantity=1, owner_id=owner_id).pack()),
            InlineKeyboardButton(text="🌱 5", callback_data=ShopCallback(action="buy", item_id=item_h, quantity=5, owner_id=owner_id).pack()),
            InlineKeyboardButton(text="🌱 10", callback_data=ShopCallback(action="buy", item_id=item_h, quantity=10, owner_id=owner_id).pack())
        ]
    )
    
    # Кнопка Назад (импортирована из farm.py)
    kb.append(back_btn_to_farm(user_id))
    
    return text, InlineKeyboardMarkup(inline_keyboard=kb)
# --- ---

# --- ХЭНДЛЕР ПОКУПКИ ---
@shop_router.callback_query(ShopCallback.filter(F.action == "buy"))
async def cq_shop_buy(callback: CallbackQuery, callback_data: ShopCallback, db: Database):
    # Проверка владельца
    if not await check_owner(callback, callback_data.owner_id):
        return

    user_id = callback.from_user.id
    item_id = callback_data.item_id
    quantity = callback_data.quantity
    
    price_per_one = SHOP_PRICES.get(item_id)
    if price_per_one is None:
        await callback.answer("⛔ Ошибка! Предмет не найден в конфиге.", show_alert=True)
        return

    total_cost = price_per_one * quantity
    
    # Проверка баланса
    balance = await db.get_user_beer_rating(user_id)
    if balance < total_cost:
        await callback.answer(f"⛔ Недостаточно 🍺!\nНужно: {total_cost} 🍺\nУ тебя: {balance} 🍺", show_alert=True)
        return

    try:
        # Списываем 🍺
        await db.change_rating(user_id, -total_cost)
        # Добавляем семена
        await db.modify_inventory(user_id, item_id, quantity)
        
        await callback.answer(f"✅ Куплено: +{quantity} {FARM_ITEM_NAMES[item_id]}!", show_alert=False)

    except Exception as e:
        logging.error(f"[Shop] Ошибка покупки: {e}")
        await callback.answer(f"⛔ Ошибка базы данных при покупке!", show_alert=True)
        return

    # --- Обновляем меню Магазина ---
    # (Чтобы показать новый баланс и новый склад)
    text, keyboard = await get_shop_menu(
        user_id=user_id, 
        db=db, 
        owner_id=callback_data.owner_id
    )
    
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(text, reply_markup=keyboard)
