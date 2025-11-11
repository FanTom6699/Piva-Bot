# handlers/shop.py
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters.callback_data import CallbackData
from contextlib import suppress
from aiogram.exceptions import TelegramBadRequest

from database import Database
from .farm_config import SHOP_PRICES, FARM_ITEM_NAMES
# ❌❌ УБИРАЕМ: from .farm import FarmCallback ❌❌

shop_router = Router()

# --- CALLBACKDATA ---
class ShopCallback(CallbackData, prefix="shop"):
    action: str 
    owner_id: int
    item_id: str = None
    quantity: int = 0

# --- "ДАШБОРД МАГАЗИНА" ---
async def get_shop_menu(user_id: int, db: Database, owner_id: int) -> (str, InlineKeyboardMarkup):
    # ✅✅✅ ДОБАВЛЯЕМ ИМПОРТ СЮДА: ✅✅✅
    from .farm import FarmCallback 
    
    balance = await db.get_user_beer_rating(user_id)
    inventory = await db.get_user_inventory(user_id)
    
    text = (
        f"<b>🏪 Магазин Семян</b>\n"
        f"<i>Здесь ты покупаешь семена за 🍺 Рейтинг.</i>\n\n"
        f"<b>У тебя:</b> {balance} 🍺\n"
        f"<b>На складе:</b>\n"
        f"• {FARM_ITEM_NAMES['семя_зерна']}: {inventory['семя_зерна']} шт.\n"
        f"• {FARM_ITEM_NAMES['семя_хмеля']}: {inventory['семя_хмеля']} шт.\n\n"
        f"--- --- ---\n"
        f"<b><u>КУПИТЬ СЕМЕНА:</u></b>"
    )
    
    buttons = []
    
    # --- Семя Зерна ---
    item_id_grain = 'семя_зерна'
    price_grain = SHOP_PRICES[item_id_grain]
    text += f"\n• <b>{FARM_ITEM_NAMES[item_id_grain]}</b>\n  <i>(Цена: {price_grain} 🍺)</i>"
    
    grain_buttons = []
    if balance >= price_grain:
        grain_buttons.append(InlineKeyboardButton(
            text="Купить 1", 
            callback_data=ShopCallback(action="buy", owner_id=owner_id, item_id=item_id_grain, quantity=1).pack()
        ))
    if balance >= (price_grain * 5):
        grain_buttons.append(InlineKeyboardButton(
            text="Купить 5", 
            callback_data=ShopCallback(action="buy", owner_id=owner_id, item_id=item_id_grain, quantity=5).pack()
        ))
    if balance >= (price_grain * 10):
        grain_buttons.append(InlineKeyboardButton(
            text="Купить 10", 
            callback_data=ShopCallback(action="buy", owner_id=owner_id, item_id=item_id_grain, quantity=10).pack()
        ))
    buttons.append(grain_buttons)

    # --- Семя Хмеля ---
    item_id_hops = 'семя_хмеля'
    price_hops = SHOP_PRICES[item_id_hops]
    text += f"\n• <b>{FARM_ITEM_NAMES[item_id_hops]}</b>\n  <i>(Цена: {price_hops} 🍺)</i>"
    
    hops_buttons = []
    if balance >= price_hops:
        hops_buttons.append(InlineKeyboardButton(
            text="Купить 1", 
            callback_data=ShopCallback(action="buy", owner_id=owner_id, item_id=item_id_hops, quantity=1).pack()
        ))
    if balance >= (price_hops * 5):
        hops_buttons.append(InlineKeyboardButton(
            text="Купить 5", 
            callback_data=ShopCallback(action="buy", owner_id=owner_id, item_id=item_id_hops, quantity=5).pack()
        ))
    if balance >= (price_hops * 10):
        hops_buttons.append(InlineKeyboardButton(
            text="Купить 10", 
            callback_data=ShopCallback(action="buy", owner_id=owner_id, item_id=item_id_hops, quantity=10).pack()
        ))
    buttons.append(hops_buttons)
    
    buttons.append([
        InlineKeyboardButton(text="⬅️ Назад на Ферму", callback_data=FarmCallback(action="main_dashboard", owner_id=owner_id).pack())
    ])
    
    return text, InlineKeyboardMarkup(inline_keyboard=buttons)


# --- ХЭНДЛЕРЫ ---

async def check_shop_owner(callback: CallbackQuery, owner_id: int) -> bool:
    if callback.from_user.id != owner_id:
        await callback.answer("⛔ Это не твой магазин! Напиши /farm, чтобы открыть свой.", show_alert=True)
        return False
    return True

@shop_router.callback_query(ShopCallback.filter(F.action == "buy"))
async def cq_shop_buy(callback: CallbackQuery, callback_data: ShopCallback, db: Database):
    if not await check_shop_owner(callback, callback_data.owner_id): return
    
    user_id = callback.from_user.id
    item_id = callback_data.item_id
    quantity = callback_data.quantity
    
    if item_id not in SHOP_PRICES:
        await callback.answer("⛔ Этот товар больше не продается.", show_alert=True)
        return
        
    price_per_one = SHOP_PRICES[item_id]
    total_cost = price_per_one * quantity
    
    balance = await db.get_user_beer_rating(user_id)
    
    if balance < total_cost:
        await callback.answer(f"⛔ Недостаточно 🍺!\nНужно: {total_cost} 🍺\nУ тебя: {balance} 🍺", show_alert=True)
        return

    # 1. Списываем 🍺
    await db.change_rating(user_id, -total_cost)
    
    # 2. Начисляем семена
    await db.modify_inventory(user_id, item_id, quantity)

    await callback.answer(f"✅ Куплено {quantity} x {FARM_ITEM_NAMES[item_id]}\nСписано: {total_cost} 🍺", show_alert=True)
    
    # Обновляем меню магазина
    text, keyboard = await get_shop_menu(user_id, db, callback_data.owner_id)
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(text, reply_markup=keyboard)
