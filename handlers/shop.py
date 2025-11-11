# handlers/shop.py
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters.callback_data import CallbackData
from contextlib import suppress
from aiogram.exceptions import TelegramBadRequest

from database import Database
from .farm_config import SHOP_PRICES, FARM_ITEM_NAMES
# (Импорт FarmCallback убран отсюда, он теперь локальный в get_shop_menu)

shop_router = Router()

# --- CALLBACKDATA ---
class ShopCallback(CallbackData, prefix="shop"):
    action: str 
    owner_id: int
    item_id: str = None
    quantity: int = 0

# --- ✅✅✅ ПУНКТ 8: ТВОЙ НОВЫЙ get_shop_menu (...) ✅✅✅ ---
async def get_shop_menu(user_id: int, db: Database, owner_id: int) -> (str, InlineKeyboardMarkup):
    from .farm import FarmCallback  # локальный импорт, чтобы избежать цикличности

    balance = await db.get_user_beer_rating(user_id)
    inv = await db.get_user_inventory(user_id)

    text = (
        f"<b>🏪 Магазин Семян</b>\n"
        f"<i>Покупай семена за 🍺 Рейтинг.</i>\n\n"
        f"У тебя: <b>{balance} 🍺</b>\n"
        f"На складе: {FARM_ITEM_NAMES['семя_зерна']}: <b>{inv['семя_зерна']}</b> • "
        f"{FARM_ITEM_NAMES['семя_хмеля']}: <b>{inv['семя_хмеля']}</b>\n\n"
        f"<b>Товары:</b>"
    )

    def line(item_id: str) -> tuple[str, list]:
        price = SHOP_PRICES[item_id]
        name  = FARM_ITEM_NAMES[item_id]
        text_line = f"\n• {name} — <i>{price} 🍺</i>"
        btns = []
        for qty in (1, 5, 10):
            if balance >= price * qty:
                btns.append(InlineKeyboardButton(
                    text=f"Купить {qty}",
                    callback_data=ShopCallback(action="buy", owner_id=owner_id, item_id=item_id, quantity=qty).pack()
                ))
        return text_line, btns
    
    # Хелпер для кнопок (из твоего П.1, но тут локально)
    def rows(btns, per_row: int) -> list[list]:
        return [btns[i:i + per_row] for i in range(0, len(btns), per_row)]

    lines_buttons = []
    add_text, btns = line('семя_зерна');  text += add_text; lines_buttons.append(btns)
    add_text, btns = line('семя_хмеля');  text += add_text; lines_buttons.append(btns)

    kb = rows([b for row in lines_buttons for b in row], per_row=3)
    kb.append([InlineKeyboardButton(text="⬅️ Назад на Ферму", callback_data=FarmCallback(action="main_dashboard", owner_id=owner_id).pack())])

    return text, InlineKeyboardMarkup(inline_keyboard=kb)
# --- КОНЕЦ ПУНКТА 8 ---


# --- ХЭНДЛЕРЫ (Без изменений) ---

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
