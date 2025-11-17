# handlers/farm.py
import asyncio
import logging
import random
from datetime import datetime, timedelta
from contextlib import suppress
from typing import Dict, Any, Optional
from html import escape 

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.exceptions import TelegramBadRequest

from database import Database
from .common import check_user_registered
from utils import format_time_delta

from .farm_config import (
    FARM_ITEM_NAMES, 
    BREWERY_RECIPE, 
    FIELD_UPGRADES, 
    BREWERY_UPGRADES, 
    get_level_data,
    SHOP_PRICES,
    CROP_CODE_TO_ID,
    CROP_SHORT,
    SEED_TO_PRODUCT_ID,
    FARM_ORDER_POOL
)

farm_router = Router()

# --- UI HELPERS ---
def rows(btns, per_row: int) -> list[list]:
    return [btns[i:i + per_row] for i in range(0, len(btns), per_row)]

def safe_name(map_: dict, key: str, fallback: str = "??") -> str:
    return map_.get(key, fallback)

def dash_title(user_name: str) -> str:
    return f"<b>🌾 Ферма: {escape(user_name)}</b>"

def back_btn_to_farm(user_id: int) -> list:
    return [InlineKeyboardButton(text="⬅️ Назад на Ферму", callback_data=FarmCallback(action="main_dashboard", owner_id=user_id).pack())]

# --- ✅ CALLBACK DATA (ИСПРАВЛЕНО) ---

# 1. Простая структура для навигации (чтобы кнопки не висли)
class FarmCallback(CallbackData, prefix="farm"):
    action: str 
    owner_id: int 

# 2. Отдельная структура для Заказов (со слотом и ID)
class OrderCallback(CallbackData, prefix="order"):
    action: str
    owner_id: int
    slot_id: int
    order_id: str

class PlotCallback(CallbackData, prefix="plot"):
    action: str 
    owner_id: int
    plot_num: int
    crop_id: Optional[str] = None 

class BreweryCallback(CallbackData, prefix="brew"):
    action: str 
    owner_id: int
    quantity: int = 0

class UpgradeCallback(CallbackData, prefix="upgrade"):
    action: str 
    owner_id: int

# --- RENDER: ДАШБОРД ФЕРМЫ ---

async def get_farm_dashboard(user_id: int, user_name: str, db: Database) -> (str, InlineKeyboardMarkup):
    farm = await db.get_user_farm_data(user_id)
    rating = await db.get_user_beer_rating(user_id)
    inventory = await db.get_user_inventory(user_id)
    active_plots = await db.get_user_plots(user_id)
    now = datetime.now()

    field_lvl = farm.get('field_level', 1)
    field_stats = get_level_data(field_lvl, FIELD_UPGRADES)
    max_plots = field_stats['plots']

    ready_plots_count = 0
    growing_plots_count = 0
    min_ready_time = None 

    for plot_num, crop_id, ready_str in active_plots:
        if isinstance(ready_str, str):
            ready_dt = datetime.fromisoformat(ready_str)
            if now >= ready_dt:
                ready_plots_count += 1
            else:
                growing_plots_count += 1
                if min_ready_time is None or ready_dt < min_ready_time:
                    min_ready_time = ready_dt
            
    empty_plots_count = max_plots - ready_plots_count - growing_plots_count
    
    brew_lvl = farm.get('brewery_level', 1)
    brew_stats = get_level_data(brew_lvl, BREWERY_UPGRADES)
    
    brewery_status_text = ""
    brew_upgrade_timer = farm.get('brewery_upgrade_timer_end')
    batch_timer = farm.get('brewery_batch_timer_end') 

    if brew_upgrade_timer and now < brew_upgrade_timer:
        left = format_time_delta(brew_upgrade_timer - now)
        brewery_status_text = f"<i>(⚠ Закрыто на улучшение... ⏳ {left})</i>"
    elif batch_timer: 
        if now >= batch_timer:
            brewery_status_text = "<b>(🏆 ГОТОВО! Забери награду!)</b>"
        else:
            left = format_time_delta(batch_timer - now)
            brewery_status_text = f"<i>(Варка... ⏳ {left})</i>"
    else:
        brewery_status_text = "<i>(Готова к варке)</i>"

    advice = "✨ Совет: Ферма в порядке. Так держать!"
    field_upgrade_timer_end = farm.get('field_upgrade_timer_end')
    brewery_upgrade_timer_end = farm.get('brewery_upgrade_timer_end')
    
    if (not batch_timer and not brew_upgrade_timer and 
          inventory['зерно'] >= BREWERY_RECIPE['зерно'] and
          inventory['хмель'] >= BREWERY_RECIPE['хмель']):
        advice = "✨ Совет: [🏭 Пивоварня] простаивает! Пора варить 🍺!"

    text = (
        f"{dash_title(user_name)}\n\n"
        f"<b>📊 Статистика:</b>\n"
        f"• 🍺 Рейтинг: <b>{rating}</b>\n"
        f"• 🌾 Зерно:    <b>{inventory['зерно']}</b>\n"
        f"• 🌱 Хмель:    <b>{inventory['хмель']}</b>\n"
        f"<code>--- --- --- ---</code>\n"
        f"<b>🌱 Поле (Ур. {field_lvl}):</b>\n"
        f"• ✅ Готово: <b>{ready_plots_count}</b> | ⏳ Зреет: <b>{growing_plots_count}</b> | 🟦 Пусто: <b>{empty_plots_count}</b>\n\n"
        f"<b>🏭 Пивоварня (Ур. {brew_lvl}):</b>\n"
        f"• {brewery_status_text}\n"
        f"<code>--- --- --- ---</code>\n"
        f"{advice}\n"
    )

    kb = []
    
    # Кнопка Поле
    if field_upgrade_timer_end and now < field_upgrade_timer_end:
        kb.append([InlineKeyboardButton(text="🌾 Поле (Стройка...)", callback_data=FarmCallback(action="show_upgrade_time", owner_id=user_id).pack())])
    else:
        field_btn_text = "🌾 Моё Поле (СОБРАТЬ!)" if ready_plots_count > 0 else "🌾 Моё Поле"
        kb.append([InlineKeyboardButton(text=field_btn_text, callback_data=FarmCallback(action="view_plots", owner_id=user_id).pack())])

    # Кнопка Пивоварня
    if brew_upgrade_timer and now < brew_upgrade_timer:
        kb.append([InlineKeyboardButton(text=f"🏭 Пивоварня (Стройка...)", callback_data=FarmCallback(action="show_upgrade_time", owner_id=user_id).pack())])
    elif batch_timer: 
        if now >= batch_timer:
            reward = brew_stats.get('reward', 0) * farm.get('brewery_batch_size', 0)
            kb.append([InlineKeyboardButton(text=f"🏆 Забрать +{reward} 🍺", callback_data=BreweryCallback(action="collect", owner_id=user_id).pack())])
        else:
            kb.append([InlineKeyboardButton(text=f"🏭 Пивоварня (варит...)", callback_data=FarmCallback(action="show_brew_time", owner_id=user_id).pack())])
    else:
        kb.append([InlineKeyboardButton(text="🏭 Пивоварня (Меню)", callback_data=BreweryCallback(action="brew_menu", owner_id=user_id).pack())])

    # Остальные кнопки
    kb_buttons = [
        InlineKeyboardButton(text="📋 Доска Заказов", callback_data=FarmCallback(action="orders_menu", owner_id=user_id).pack()),
        InlineKeyboardButton(text="📦 Склад",     callback_data=FarmCallback(action="inventory", owner_id=user_id).pack()),
        InlineKeyboardButton(text="⭐ Улучшения", callback_data=FarmCallback(action="upgrades",  owner_id=user_id).pack()),
        InlineKeyboardButton(text="🏪 Магазин",   callback_data=FarmCallback(action="shop",      owner_id=user_id).pack()),
        InlineKeyboardButton(text="❓ Инфо", callback_data=FarmCallback(action="show_help", owner_id=user_id).pack())
    ]
    kb += rows(kb_buttons, per_row=2) 

    return text, InlineKeyboardMarkup(inline_keyboard=kb)

# --- RENDER: ПОЛЕ ---

async def get_plots_dashboard(user_id: int, db: Database) -> (str, InlineKeyboardMarkup):
    farm = await db.get_user_farm_data(user_id)
    now = datetime.now()
    lvl = farm.get('field_level', 1)
    stats = get_level_data(lvl, FIELD_UPGRADES)
    max_plots = stats['plots']
    g_time = stats.get('grow_time_min', {}).get('зерно', '??')
    h_time = stats.get('grow_time_min', {}).get('хмель', '??')
    
    text = (f"<b>🌱 Поле (Ур. {lvl})</b>\n<i>Время: 🌾{g_time}м / 🌱{h_time}м</i>\n")
    
    raw = await db.get_user_plots(user_id)
    active = {}
    for plot_num, crop_id, ready_str in raw:
        if isinstance(ready_str, str): active[plot_num] = (crop_id, datetime.fromisoformat(ready_str))

    per_row = 2 if max_plots <= 4 else 3
    plot_btns = []
    for i in range(1, max_plots + 1):
        if i in active:
            seed_id, ready = active[i]
            product_id = SEED_TO_PRODUCT_ID.get(seed_id, '??')
            crop_name = safe_name(CROP_SHORT, product_id, "??")
            if now >= ready:
                plot_btns.append(InlineKeyboardButton(text=f"✅ {crop_name}", callback_data=PlotCallback(action="harvest", owner_id=user_id, plot_num=i).pack()))
            else:
                left = format_time_delta(ready - now)
                plot_btns.append(InlineKeyboardButton(text=f"⏳ {crop_name} ({left})", callback_data=PlotCallback(action="show_time", owner_id=user_id, plot_num=i).pack()))
        else:
            plot_btns.append(InlineKeyboardButton(text=f"🟦 Грядка {i}", callback_data=PlotCallback(action="plant_menu", owner_id=user_id, plot_num=i).pack()))

    kb = rows(plot_btns, per_row=per_row)
    kb.append(back_btn_to_farm(user_id))
    return text, InlineKeyboardMarkup(inline_keyboard=kb)


# --- HANDLERS (ОБРАБОТЧИКИ) ---

async def check_owner(callback: CallbackQuery, owner_id: int) -> bool:
    if callback.from_user.id != owner_id:
        await callback.answer("⛔ Это не твоя ферма!", show_alert=True)
        return False
    return True

@farm_router.message(Command("farm"))
async def cmd_farm(message: Message, bot: Bot, db: Database):
    if not await check_user_registered(message, bot, db): return
    try:
        text, keyboard = await get_farm_dashboard(message.from_user.id, message.from_user.full_name, db)
        await message.answer(text, reply_markup=keyboard)
    except Exception as e:
        logging.error(f"Error /farm: {e}")
        await message.answer("⚠️ Ошибка фермы. Попробуйте позже.")

@farm_router.callback_query(FarmCallback.filter(F.action == "main_dashboard"))
async def cq_farm_main_dashboard(callback: CallbackQuery, callback_data: FarmCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id): return
    try:
        text, keyboard = await get_farm_dashboard(callback.from_user.id, callback.from_user.full_name, db)
        with suppress(TelegramBadRequest): await callback.message.edit_text(text, reply_markup=keyboard)
    except Exception as e:
        logging.error(f"Main Dash Error: {e}")
    await callback.answer()

@farm_router.callback_query(FarmCallback.filter(F.action == "view_plots"))
async def cq_farm_view_plots(callback: CallbackQuery, callback_data: FarmCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id): return
    try:
        text, keyboard = await get_plots_dashboard(callback.from_user.id, db)
        with suppress(TelegramBadRequest): await callback.message.edit_text(text, reply_markup=keyboard)
    except Exception as e:
        logging.error(f"View Plots Error: {e}")
    await callback.answer()

@farm_router.callback_query(FarmCallback.filter(F.action == "shop"))
async def cq_farm_go_to_shop(callback: CallbackQuery, callback_data: FarmCallback, db: Database):
    # Импортируем ВНУТРИ функции, чтобы не было ошибок импорта
    from .shop import get_shop_menu 
    if not await check_owner(callback, callback_data.owner_id): return
    try:
        text, keyboard = await get_shop_menu(callback.from_user.id, db, callback_data.owner_id)
        with suppress(TelegramBadRequest): await callback.message.edit_text(text, reply_markup=keyboard)
    except Exception as e:
        logging.error(f"SHOP ERROR: {e}")
        await callback.answer("Ошибка магазина!", show_alert=True)
    await callback.answer()

@farm_router.callback_query(FarmCallback.filter(F.action == "inventory"))
async def cq_farm_inventory(callback: CallbackQuery, callback_data: FarmCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id): return
    inv = await db.get_user_inventory(callback.from_user.id)
    text = (f"<b>📦 Склад</b>\n\n🌾 Зерно: {inv['зерно']}\n🌱 Хмель: {inv['хмель']}\n\n📜 Семена Зерна: {inv['семя_зерна']}\n📜 Семена Хмеля: {inv['семя_хмеля']}")
    kb = [back_btn_to_farm(callback.from_user.id)]
    with suppress(TelegramBadRequest): await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await callback.answer()

# --- ORDERS (ДОСКА ЗАКАЗОВ) - ИСПОЛЬЗУЕМ OrderCallback ---

@farm_router.callback_query(FarmCallback.filter(F.action == "orders_menu"))
async def cq_farm_orders_menu(callback: CallbackQuery, db: Database, callback_data: FarmCallback):
    if not await check_owner(callback, callback_data.owner_id): return
    try:
        user_id = callback.from_user.id
        await db.check_and_reset_orders(user_id)
        orders = await db.get_user_orders(user_id)
        inventory = await db.get_user_inventory(user_id)
        
        text = "<b>📋 Доска Заказов</b>\n(Обновление раз в 24ч)\n"
        buttons = []
        
        for slot_id, order_id, is_completed in orders:
            if order_id not in FARM_ORDER_POOL: continue
            order = FARM_ORDER_POOL[order_id]
            
            reward_text = f"+{order['reward_amount']} 🍺" if order['reward_type'] == 'beer' else "Предметы"
            
            if is_completed:
                text += f"\n✅ <s>{order['text']}</s>\n"
            else:
                has_items = inventory.get(order['item_id'], 0) >= order['item_amount']
                status_icon = "✅" if has_items else "❌"
                text += f"\n{status_icon} <b>{order['text']}</b>\n"
                
                if has_items:
                    # ✅ Используем OrderCallback!
                    cb = OrderCallback(action="complete", owner_id=user_id, slot_id=slot_id, order_id=order_id).pack()
                    buttons.append(InlineKeyboardButton(text=f"Сдать ({reward_text})", callback_data=cb))
        
        kb_rows = [[btn] for btn in buttons]
        kb_rows.append(back_btn_to_farm(user_id))
        
        with suppress(TelegramBadRequest):
            await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))
    except Exception as e:
        logging.error(f"ORDERS ERROR: {e}")
        await callback.answer("Ошибка заказов!", show_alert=True)
    await callback.answer()

@farm_router.callback_query(OrderCallback.filter(F.action == "complete"))
async def cq_farm_order_complete(callback: CallbackQuery, db: Database, callback_data: OrderCallback):
    if not await check_owner(callback, callback_data.owner_id): return
    try:
        user_id = callback.from_user.id
        order = FARM_ORDER_POOL.get(callback_data.order_id)
        if not order: return await callback.answer("Ошибка заказа", show_alert=True)

        inventory = await db.get_user_inventory(user_id)
        if inventory.get(order['item_id'], 0) < order['item_amount']:
            return await callback.answer("Не хватает ресурсов!", show_alert=True)

        if not await db.complete_order(user_id, callback_data.slot_id):
            return await callback.answer("Уже выполнено!", show_alert=True)
            
        await db.modify_inventory(user_id, order['item_id'], -order['item_amount'])
        
        if order['reward_type'] == 'beer':
            await db.change_rating(user_id, order['reward_amount'])
            msg = f"Получено: +{order['reward_amount']} 🍺"
        elif order['reward_type'] == 'item':
            await db.modify_inventory(user_id, order['reward_id'], order['reward_amount'])
            msg = f"Получены предметы!"

        await callback.answer(msg, show_alert=True)
        # Возвращаемся в меню заказов
        await cq_farm_orders_menu(callback, db, FarmCallback(action="orders_menu", owner_id=user_id))
    except Exception as e:
        logging.error(f"ORDER COMPLETE ERROR: {e}")
        await callback.answer("Ошибка выполнения!", show_alert=True)

# --- ДЕЙСТВИЯ НА ГРЯДКАХ ---

@farm_router.callback_query(PlotCallback.filter(F.action == "plant_menu"))
async def cq_plot_plant_menu(callback: CallbackQuery, callback_data: PlotCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id): return
    user_id = callback.from_user.id
    inv = await db.get_user_inventory(user_id)
    
    btns = []
    if inv['семя_зерна'] > 0:
        btns.append(InlineKeyboardButton(text="🌾 Зерно", callback_data=PlotCallback(action="plant_do", owner_id=user_id, plot_num=callback_data.plot_num, crop_id="g").pack()))
    if inv['семя_хмеля'] > 0:
        btns.append(InlineKeyboardButton(text="🌱 Хмель", callback_data=PlotCallback(action="plant_do", owner_id=user_id, plot_num=callback_data.plot_num, crop_id="h").pack()))
    
    text = f"<b>Грядка {callback_data.plot_num}</b>\nЧто сажаем?\n\nНа складе:\n🌾 Семян Зерна: {inv['семя_зерна']}\n🌱 Семян Хмеля: {inv['семя_хмеля']}"
    
    rows_kb = rows(btns, 2)
    if not btns:
        text += "\n\n⛔ Нет семян! Купите в магазине."
        rows_kb.append([InlineKeyboardButton(text="Магазин", callback_data=FarmCallback(action="shop", owner_id=user_id).pack())])
    
    rows_kb.append([InlineKeyboardButton(text="Назад", callback_data=FarmCallback(action="view_plots", owner_id=user_id).pack())])
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows_kb))
    await callback.answer()

@farm_router.callback_query(PlotCallback.filter(F.action == "plant_do"))
async def cq_plot_plant_do(callback: CallbackQuery, callback_data: PlotCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id): return
    user_id = callback.from_user.id
    crop_id = CROP_CODE_TO_ID.get(callback_data.crop_id)
    
    if await db.modify_inventory(user_id, crop_id, -1):
        farm = await db.get_user_farm_data(user_id)
        stats = get_level_data(farm.get('field_level', 1), FIELD_UPGRADES)
        prod_id = SEED_TO_PRODUCT_ID[crop_id]
        minutes = stats['grow_time_min'][prod_id]
        ready = datetime.now() + timedelta(minutes=minutes)
        
        await db.plant_crop(user_id, callback_data.plot_num, crop_id, ready)
        await callback.answer(f"Посажено! Ждать {minutes} мин.")
        await cq_farm_view_plots(callback, FarmCallback(action="view_plots", owner_id=user_id), db)
    else:
        await callback.answer("Нет семян!", show_alert=True)

@farm_router.callback_query(PlotCallback.filter(F.action == "harvest"))
async def cq_plot_harvest(callback: CallbackQuery, callback_data: PlotCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id): return
    seed = await db.harvest_plot(callback.from_user.id, callback_data.plot_num)
    if seed:
        prod = SEED_TO_PRODUCT_ID[seed]
        await db.modify_inventory(callback.from_user.id, prod, 1)
        await callback.answer(f"Собрано: 1 {FARM_ITEM_NAMES[prod]}")
        await cq_farm_view_plots(callback, FarmCallback(action="view_plots", owner_id=callback.from_user.id), db)
    else:
        await callback.answer("Ошибка сбора", show_alert=True)

@farm_router.callback_query(PlotCallback.filter(F.action == "show_time"))
async def cq_plot_time(callback: CallbackQuery):
    await callback.answer("Еще растет...", show_alert=True)

@farm_router.callback_query(FarmCallback.filter(F.action == "show_brew_time"))
async def cq_farm_show_brew_time(callback: CallbackQuery, callback_data: FarmCallback, db: Database):
    user_id = callback_data.owner_id
    farm_data = await db.get_user_farm_data(user_id)
    batch_timer = farm_data.get('brewery_batch_timer_end')
    now = datetime.now()
    if batch_timer and now < batch_timer:
        time_left = format_time_delta(batch_timer - now)
        await callback.answer(f"⏳ Пиво еще варится. Осталось: {time_left}", show_alert=True)
    else:
        await callback.answer("✅ Готово!", show_alert=True)

@farm_router.callback_query(FarmCallback.filter(F.action == "show_upgrade_time"))
async def cq_farm_show_upgrade_time(callback: CallbackQuery, callback_data: FarmCallback):
    await callback.answer("⏳ Идет улучшение...", show_alert=True)

# --- ПИВОВАРНЯ ---

@farm_router.callback_query(BreweryCallback.filter(F.action == "brew_menu"))
async def cq_brewery_menu(callback: CallbackQuery, callback_data: BreweryCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id): return
    uid = callback.from_user.id
    inv = await db.get_user_inventory(uid)
    text = f"🏭 <b>Пивоварня</b>\n\nНужно на 1 варку:\n🌾 {BREWERY_RECIPE['зерно']} Зерна\n🌱 {BREWERY_RECIPE['хмель']} Хмеля\n\nУ тебя:\n🌾 {inv['зерно']} | 🌱 {inv['хмель']}"
    
    can_brew = inv['зерно'] >= BREWERY_RECIPE['зерно'] and inv['хмель'] >= BREWERY_RECIPE['хмель']
    btns = []
    if can_brew:
        btns.append(InlineKeyboardButton(text="🔥 Варить (1)", callback_data=BreweryCallback(action="brew_do", owner_id=uid, quantity=1).pack()))
    
    kb = rows(btns, 1)
    kb.append(back_btn_to_farm(uid))
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await callback.answer()

@farm_router.callback_query(BreweryCallback.filter(F.action == "brew_do"))
async def cq_brewery_do(callback: CallbackQuery, callback_data: BreweryCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id): return
    uid = callback.from_user.id
    qty = callback_data.quantity
    
    # Списание
    if await db.modify_inventory(uid, 'зерно', -BREWERY_RECIPE['зерно']*qty) and \
       await db.modify_inventory(uid, 'хмель', -BREWERY_RECIPE['хмель']*qty):
           
        farm = await db.get_user_farm_data(uid)
        stats = get_level_data(farm.get('brewery_level', 1), BREWERY_UPGRADES)
        minutes = stats['brew_time_min']
        ready = datetime.now() + timedelta(minutes=minutes*qty)
        
        await db.start_brewing(uid, qty, ready)
        await callback.answer("Варка началась!")
        await cq_farm_main_dashboard(callback, FarmCallback(action="main_dashboard", owner_id=uid), db)
    else:
        await callback.answer("Ошибка ресурсов!", show_alert=True)

@farm_router.callback_query(BreweryCallback.filter(F.action == "collect"))
async def cq_brewery_collect(callback: CallbackQuery, callback_data: BreweryCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id): return
    uid = callback.from_user.id
    farm = await db.get_user_farm_data(uid)
    stats = get_level_data(farm.get('brewery_level', 1), BREWERY_UPGRADES)
    reward = stats['reward'] * farm.get('brewery_batch_size', 1)
    
    await db.collect_brewery(uid, reward)
    await callback.answer(f"Сварено! +{reward} 🍺")
    await cq_farm_main_dashboard(callback, FarmCallback(action="main_dashboard", owner_id=uid), db)

# --- УЛУЧШЕНИЯ ---

@farm_router.callback_query(FarmCallback.filter(F.action == "upgrades"))
async def cq_farm_upgrades(callback: CallbackQuery, callback_data: FarmCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id): return
    
    user_id = callback.from_user.id
    balance = await db.get_user_beer_rating(user_id)
    farm = await db.get_user_farm_data(user_id)
    
    field_lvl = farm.get('field_level', 1)
    field_next = get_level_data(field_lvl + 1, FIELD_UPGRADES)
    
    brew_lvl = farm.get('brewery_level', 1)
    brew_next = get_level_data(brew_lvl + 1, BREWERY_UPGRADES)
    
    text = f"⭐ <b>Улучшения</b> (Баланс: {balance} 🍺)\n\n"
    
    # Поле
    text += f"<b>🌱 Поле (Ур. {field_lvl})</b>\n"
    buttons = []
    if not field_next.get('max_level') and not farm.get('field_upgrade_timer_end'):
        cost = field_next['cost']
        text += f"След. ур: +Грядки, -Время\nЦена: {cost} 🍺\n"
        if balance >= cost:
            buttons.append([InlineKeyboardButton(text=f"⬆️ Улучшить Поле ({cost} 🍺)", callback_data=UpgradeCallback(action="buy_field", owner_id=user_id).pack())])
        else:
            text += "<i>(Не хватает денег)</i>\n"
    else:
        text += "(Макс. уровень или стройка)\n"

    text += "\n"
    
    # Пивоварня
    text += f"<b>🏭 Пивоварня (Ур. {brew_lvl})</b>\n"
    if not brew_next.get('max_level') and not farm.get('brewery_upgrade_timer_end'):
        cost = brew_next['cost']
        text += f"След. ур: +Награда, -Время\nЦена: {cost} 🍺\n"
        if balance >= cost:
            buttons.append([InlineKeyboardButton(text=f"⬆️ Улучшить Пивоварню ({cost} 🍺)", callback_data=UpgradeCallback(action="buy_brewery", owner_id=user_id).pack())])
        else:
             text += "<i>(Не хватает денег)</i>\n"
    else:
         text += "(Макс. уровень или стройка)\n"

    buttons.append(back_btn_to_farm(user_id))
    
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@farm_router.callback_query(UpgradeCallback.filter(F.action.in_({"buy_field", "buy_brewery"})))
async def cq_upgrade_confirm(callback: CallbackQuery, callback_data: UpgradeCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id): return
    
    b_type = "field" if callback_data.action == "buy_field" else "brewery"
    
    farm = await db.get_user_farm_data(callback.from_user.id)
    lvl = farm.get(f'{b_type}_level', 1)
    stats = get_level_data(lvl + 1, FIELD_UPGRADES if b_type == 'field' else BREWERY_UPGRADES)
    
    cost = stats['cost']
    time_h = stats['time_h']
    end_time = datetime.now() + timedelta(hours=time_h)
    
    await db.start_upgrade(callback.from_user.id, b_type, end_time, cost)
    await callback.answer(f"Улучшение запущено! ({time_h} ч)")
    await cq_farm_main_dashboard(callback, FarmCallback(action="main_dashboard", owner_id=callback.from_user.id), db)

@farm_router.callback_query(FarmCallback.filter(F.action == "show_help"))
async def cq_farm_help(callback: CallbackQuery, callback_data: FarmCallback):
    text = "ℹ️ <b>Помощь</b>\n\nСажай семена -> Собирай урожай -> Вари пиво!"
    kb = [back_btn_to_farm(callback.from_user.id)]
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await callback.answer()
