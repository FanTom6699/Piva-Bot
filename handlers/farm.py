# handlers/farm.py
import asyncio
import logging
import random
from datetime import datetime, timedelta
from contextlib import suppress
from typing import Dict, Any, Optional
from html import escape 
from math import floor 

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
    SEED_TO_PRODUCT_ID
)

# --- ИНИЦИАЛИЗАЦИЯ ---
farm_router = Router()

# --- UI HELPERS ---
def ui_bar(pct: int, width: int = 10) -> str:
    pct = max(0, min(100, pct))
    fill = int(width * pct / 100)
    return f"[{'█' * fill}{'░' * (width - fill)}] {pct}%"

def rows(btns, per_row: int) -> list[list]:
    return [btns[i:i + per_row] for i in range(0, len(btns), per_row)]

def safe_name(map_: dict, key: str, fallback: str = "??") -> str:
    return map_.get(key, fallback)

def dash_title(user_name: str) -> str:
    return f"<b>🌾 Ферма: {escape(user_name)}</b>"

def back_btn_to_farm(user_id: int) -> list:
    return [InlineKeyboardButton(text="⬅️ Назад на Ферму", callback_data=FarmCallback(action="main_dashboard", owner_id=user_id).pack())]
# --- ---


# --- CALLBACKDATA (С фиксом Optional) ---
class FarmCallback(CallbackData, prefix="farm"):
    action: str 
    owner_id: int 

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

# --- "ОФОРМЛЕННЫЙ" ДАШБОРД (Piva Bot) ---
# --- RENDER: DASHBOARD ---
async def get_farm_dashboard(user_id: int, user_name: str, db: Database) -> (str, InlineKeyboardMarkup):
    
    # --- Шаг 1: Собираем ВСЕ данные (Piva Bot) ---
    farm = await db.get_user_farm_data(user_id)
    rating = await db.get_user_beer_rating(user_id)
    inventory = await db.get_user_inventory(user_id)
    active_plots = await db.get_user_plots(user_id)
    now = datetime.now()

    # --- Шаг 2: Анализируем Поле (Piva Bot) ---
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
    
    # --- Шаг 3: Анализируем Пивоварню (Piva Bot) ---
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

    # --- Шаг 4: Генерируем "Совет" (Piva Bot) ---
    advice = "✨ Совет: Ферма в порядке. Так держать!" # Default
    
    field_upgrade_timer_end = farm.get('field_upgrade_timer_end')
    brewery_upgrade_timer_end = farm.get('brewery_upgrade_timer_end')
    
    can_upgrade_field = (not field_upgrade_timer_end or now >= field_upgrade_timer_end)
    can_upgrade_brewery = (not brewery_upgrade_timer_end or now >= brewery_upgrade_timer_end)

    if not field_stats['max_level'] and rating >= field_stats.get('next_cost', 999999) and can_upgrade_field:
        advice = "✨ Совет: У тебя хватает 🍺 на улучшение [🌾 Поля]!"
    elif not brew_stats['max_level'] and rating >= brew_stats.get('next_cost', 999999) and can_upgrade_brewery:
        advice = "✨ Совет: У тебя хватает 🍺 на улучшение [🏭 Пивоварни]!"
    elif (not batch_timer and not brew_upgrade_timer and 
          inventory['зерно'] >= BREWERY_RECIPE['зерно'] and
          inventory['хмель'] >= BREWERY_RECIPE['хмель']):
        advice = "✨ Совет: [🏭 Пивоварня] простаивает! Пора варить 🍺!"
    elif empty_plots_count > 0 and (inventory['семя_зерна'] > 0 or inventory['семя_хмеля'] > 0):
        advice = "✨ Совет: У тебя есть пустые грядки и семена. Пора сажать!"

    # --- Шаг 5: Собираем Текст (Piva Bot) ---
    text = (
        f"{dash_title(user_name)}\n\n"
        
        f"<b>📊 Статистика:</b>\n"
        f"• 🍺 Рейтинг: <b>{rating}</b>\n"
        f"• 🌾 Зерно:   <b>{inventory['зерно']}</b>\n"
        f"• 🌱 Хмель:   <b>{inventory['хмель']}</b>\n"
        f"<code>--- --- --- ---</code>\n"
        
        f"<b>🌱 Поле (Ур. {field_lvl}):</b>\n"
        f"• ✅ Готово к сбору: <b>{ready_plots_count}</b> грядок\n"
        f"• ⏳ Зреет: <b>{growing_plots_count}</b> грядок\n"
        f"• 🟦 Пусто: <b>{empty_plots_count}</b> грядок\n"
    )
    
    if min_ready_time:
        time_left_str = format_time_delta(min_ready_time - now)
        text += f"<i>(Ближайший урожай: {time_left_str})</i>\n"
    elif ready_plots_count > 0:
        text += "<i>(Пора собирать урожай!)</i>\n"
    else:
        text += "<i>(Все грядки свободны)</i>\n"

    text += "\n" # Пробел
    
    text += f"<b>🏭 Пивоварня (Ур. {brew_lvl}):</b>\n"
    text += f"• {brewery_status_text}\n"
    
    text += f"<code>--- --- --- ---</code>\n"
    text += f"{advice}\n"

    # --- Шаг 6: Собираем Кнопки (Piva Bot) ---
    kb = []
    
    # Кнопка Поля
    if field_upgrade_timer_end and now < field_upgrade_timer_end:
        kb.append([InlineKeyboardButton(
            text="🌾 Поле (⚠ закрыто на улучшение)", 
            callback_data=FarmCallback(action="show_upgrade_time", owner_id=user_id).pack()
        )])
    else:
        field_btn_text = "🌾 Моё Поле (СОБРАТЬ!)" if ready_plots_count > 0 else "🌾 Моё Поле (Грядки)"
        kb.append([InlineKeyboardButton(text=field_btn_text, callback_data=FarmCallback(action="view_plots", owner_id=user_id).pack())])

    # Кнопка Пивоварни
    if brew_upgrade_timer and now < brew_upgrade_timer:
        kb.append([InlineKeyboardButton(
            text=f"🏭 Пивоварня (⚠ закрыто на улучшение)", 
            callback_data=FarmCallback(action="show_upgrade_time", owner_id=user_id).pack()
        )])
    elif batch_timer: 
        if now >= batch_timer:
            reward = brew_stats.get('reward', 0)
            total = reward * farm.get('brewery_batch_size', 0)
            kb.append([InlineKeyboardButton(text=f"🏆 Забрать +{total} 🍺", callback_data=BreweryCallback(action="collect", owner_id=user_id).pack())])
        else:
            kb.append([InlineKeyboardButton(
                text=f"🏭 Пивоварня (варит...)", 
                callback_data=FarmCallback(action="show_brew_time", owner_id=user_id).pack()
            )])
    else:
        kb.append([InlineKeyboardButton(text="🏭 Пивоварня (Меню)", callback_data=BreweryCallback(action="brew_menu", owner_id=user_id).pack())])

    # Остальные кнопки
    kb_buttons = [
        InlineKeyboardButton(text="📦 Склад",     callback_data=FarmCallback(action="inventory", owner_id=user_id).pack()),
        InlineKeyboardButton(text="⭐ Улучшения", callback_data=FarmCallback(action="upgrades",  owner_id=user_id).pack()),
        InlineKeyboardButton(text="🏪 Магазин",   callback_data=FarmCallback(action="shop",      owner_id=user_id).pack()),
        InlineKeyboardButton(text="❓ Как играть?", callback_data=FarmCallback(action="show_help", owner_id=user_id).pack())
    ]
    kb += rows(kb_buttons, per_row=2)

    return text, InlineKeyboardMarkup(inline_keyboard=kb)
# --- ---


# --- RENDER: FIELD ---
async def get_plots_dashboard(user_id: int, db: Database) -> (str, InlineKeyboardMarkup):
    farm = await db.get_user_farm_data(user_id)
    now = datetime.now()

    lvl = farm.get('field_level', 1)
    stats = get_level_data(lvl, FIELD_UPGRADES)
    max_plots = stats['plots']
    
    g_time = stats.get('grow_time_min', {}).get('зерно', '??')
    h_time = stats.get('grow_time_min', {}).get('хмель', '??')
    
    text = (
        f"<b>🌱 Поле (Ур. {lvl})</b>\n"
        f"<i>Грядок: {stats.get('plots', '??')}, Шанс x2: {stats.get('chance_x2', '??')}%</i>\n"
        f"<i>Время роста: 🌾 {g_time}м / 🌱 {h_time}м</i>\n\n"
        f"Нажми на <b>Пусто</b>, чтобы посадить.\n"
    )

    raw = await db.get_user_plots(user_id)
    active = {}
    for plot_num, crop_id, ready_str in raw:
        if isinstance(ready_str, str):
            active[plot_num] = (crop_id, datetime.fromisoformat(ready_str))

    per_row = 2 if max_plots <= 4 else 3
    plot_btns = []
    for i in range(1, max_plots + 1):
        if i in active:
            seed_id, ready = active[i]
            
            product_id = SEED_TO_PRODUCT_ID.get(seed_id, '??')
            crop_name = safe_name(CROP_SHORT, product_id, "??")
            
            if now >= ready:
                txt = f"✅ {crop_name} (Собрать)"
                cb  = PlotCallback(action="harvest", owner_id=user_id, plot_num=i).pack()
            else:
                left = format_time_delta(ready - now)
                txt = f"⏳ {crop_name} ({left})"
                cb  = PlotCallback(action="show_time", owner_id=user_id, plot_num=i).pack()
                
        else:
            txt = f"🟦 Грядка {i} (Пусто)"
            cb  = PlotCallback(action="plant_menu", owner_id=user_id, plot_num=i).pack()
        plot_btns.append(InlineKeyboardButton(text=txt, callback_data=cb))

    kb = rows(plot_btns, per_row=per_row)
    kb.append(back_btn_to_farm(user_id))

    return text, InlineKeyboardMarkup(inline_keyboard=kb)
# --- ---

# --- HANDLERS ---

async def check_owner(callback: CallbackQuery, owner_id: int) -> bool:
    if callback.from_user.id != owner_id:
        await callback.answer("⛔ Это не твоя ферма! Напиши /farm, чтобы открыть свою.", show_alert=True)
        return False
    return True

@farm_router.message(Command("farm"))
async def cmd_farm(message: Message, bot: Bot, db: Database):
    user_id = message.from_user.id
    if not await check_user_registered(message, bot, db):
        return
    text, keyboard = await get_farm_dashboard(user_id, message.from_user.full_name, db)
    await message.answer(text, reply_markup=keyboard)

@farm_router.callback_query(FarmCallback.filter(F.action == "main_dashboard"))
async def cq_farm_main_dashboard(callback: CallbackQuery, callback_data: FarmCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id): return
    text, keyboard = await get_farm_dashboard(callback.from_user.id, callback.from_user.full_name, db)
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()

@farm_router.callback_query(FarmCallback.filter(F.action == "show_brew_time"))
async def cq_farm_show_brew_time(callback: CallbackQuery, callback_data: FarmCallback, db: Database):
    """Показывает оставшееся время варки"""
    if not await check_owner(callback, callback_data.owner_id):
        return

    user_id = callback_data.owner_id
    farm_data = await db.get_user_farm_data(user_id)
    
    batch_timer = farm_data.get('brewery_batch_timer_end')
    
    if not batch_timer:
        await callback.answer("Ошибка! Варка уже завершена или не найдена.", show_alert=True)
        return

    now = datetime.now()
    
    if now >= batch_timer:
        await callback.answer("✅ Готово! Нажмите 'Забрать'.", show_alert=True)
    else:
        time_left = format_time_delta(batch_timer - now)
        await callback.answer(f"⏳ Пиво еще варится. Осталось: {time_left}", show_alert=True)

@farm_router.callback_query(FarmCallback.filter(F.action == "show_upgrade_time"))
async def cq_farm_show_upgrade_time(callback: CallbackQuery, callback_data: FarmCallback, db: Database):
    """Показывает оставшееся время улучшения (Поля или Пивоварни)"""
    if not await check_owner(callback, callback_data.owner_id):
        return

    user_id = callback_data.owner_id
    farm_data = await db.get_user_farm_data(user_id)
    now = datetime.now()

    field_timer = farm_data.get('field_upgrade_timer_end')
    brew_timer = farm_data.get('brewery_upgrade_timer_end')

    alert_text = "Нет активных улучшений."
    
    if field_timer and now < field_timer:
        time_left = format_time_delta(field_timer - now)
        alert_text = f"🌾 Поле улучшается. Осталось: {time_left}"
    elif brew_timer and now < brew_timer:
        time_left = format_time_delta(brew_timer - now)
        alert_text = f"🏭 Пивоварня улучшается. Осталось: {time_left}"
    else:
        alert_text = "✅ Улучшение завершено!"

    await callback.answer(alert_text, show_alert=True)

@farm_router.callback_query(FarmCallback.filter(F.action == "view_plots"))
async def cq_farm_view_plots(callback: CallbackQuery, callback_data: FarmCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id): return
    
    user_id = callback.from_user.id
    text, keyboard = await get_plots_dashboard(user_id, db)
    
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()

@farm_router.callback_query(FarmCallback.filter(F.action == "shop"))
async def cq_farm_go_to_shop(callback: CallbackQuery, callback_data: FarmCallback, db: Database):
    from .shop import get_shop_menu 

    if not await check_owner(callback, callback_data.owner_id): 
        return

    text, keyboard = await get_shop_menu(
        user_id=callback.from_user.id, 
        db=db, 
        owner_id=callback_data.owner_id
    )
    
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(text, reply_markup=keyboard)
    
    await callback.answer()

@farm_router.callback_query(FarmCallback.filter(F.action == "inventory"))
async def cq_farm_inventory(callback: CallbackQuery, callback_data: FarmCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id): 
        return

    user_id = callback.from_user.id
    inv = await db.get_user_inventory(user_id)

    text = (
        f"<b>📦 Мой Склад</b>\n\n"
        f"<b>Урожай:</b>\n"
        f"• {FARM_ITEM_NAMES['зерно']}: <b>{inv['зерно']}</b>\n"
        f"• {FARM_ITEM_NAMES['хмель']}: <b>{inv['хмель']}</b>\n\n"
        f"<b>Семена:</b>\n"
        f"• {FARM_ITEM_NAMES['семя_зерна']}: <b>{inv['семя_зерна']}</b>\n"
        f"• {FARM_ITEM_NAMES['семя_хмеля']}: <b>{inv['семя_хмеля']}</b>\n"
    )

    kb = [back_btn_to_farm(user_id)]
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await callback.answer()


@farm_router.callback_query(PlotCallback.filter(F.action == "plant_menu"))
async def cq_plot_plant_menu(callback: CallbackQuery, callback_data: PlotCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id): return
    
    user_id = callback.from_user.id
    plot_num = callback_data.plot_num
    inventory = await db.get_user_inventory(user_id)
    
    text = (
        f"<b>🌱 Посадка — Грядка {plot_num}</b>\n\n"
        f"<i>На складе:</i>\n"
        f"• {FARM_ITEM_NAMES['семя_зерна']}: {inventory['семя_зерна']}\n"
        f"• {FARM_ITEM_NAMES['семя_хмеля']}: {inventory['семя_хмеля']}"
    )
    
    buttons = []
    
    farm_data = await db.get_user_farm_data(user_id)
    field_lvl = farm_data.get('field_level', 1)
    field_stats = get_level_data(field_lvl, FIELD_UPGRADES)
    
    if inventory['семя_зерна'] > 0:
        time_m = field_stats.get('grow_time_min', {}).get('зерно', '??')
        buttons.append(InlineKeyboardButton(
            text=f"Посадить 🌾 Зерно ({time_m} мин)", 
            callback_data=PlotCallback(action="plant_do", owner_id=user_id, plot_num=plot_num, crop_id="g").pack()
        ))
    
    if inventory['семя_хмеля'] > 0:
        time_m = field_stats.get('grow_time_min', {}).get('хмель', '??')
        buttons.append(InlineKeyboardButton(
            text=f"Посадить 🌱 Хмель ({time_m} мин)", 
            callback_data=PlotCallback(action="plant_do", owner_id=user_id, plot_num=plot_num, crop_id="h").pack()
        ))
    
    if inventory['семя_зерна'] == 0 and inventory['семя_хмеля'] == 0:
        text += "\n\n⛔ <b>У тебя нет семян!</b>\nСначала купи их в Магазине."
        buttons.append(InlineKeyboardButton(
            text="[🏪 Зайти в Магазин]", 
            callback_data=FarmCallback(action="shop", owner_id=user_id).pack()
        ))

    keyboard_rows = rows(buttons, per_row=1)
    
    keyboard_rows.append([
        InlineKeyboardButton(text="⬅️ Назад в Поле", callback_data=FarmCallback(action="view_plots", owner_id=user_id).pack())
    ])
    
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_rows))
    await callback.answer()

@farm_router.callback_query(PlotCallback.filter(F.action == "plant_do"))
async def cq_plot_plant_do(callback: CallbackQuery, callback_data: PlotCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id): return

    user_id = callback.from_user.id
    plot_num = callback_data.plot_num
    
    code = callback_data.crop_id
    crop_id = CROP_CODE_TO_ID.get(code) 

    if not crop_id:
        await callback.answer("⛔ Ошибка! Неизвестный код семян.", show_alert=True)
        return

    # --- Шаг 1: Списание семян ---
    logging.info(f"[Farm DEBUG] Участок {plot_num}: Пытаемся списать 1x {crop_id} у {user_id}")
    success = await db.modify_inventory(user_id, crop_id, -1)
    
    if not success:
        logging.warning(f"[Farm DEBUG] Участок {plot_num}: НЕУДАЧА списания (нет семян).")
        await callback.answer(f"⛔ Ошибка! У тебя закончились '{FARM_ITEM_NAMES[crop_id]}'.", show_alert=True)
        await cq_plot_plant_menu(callback, PlotCallback(action="plant_menu", owner_id=user_id, plot_num=plot_num), db)
        return
    
    logging.info(f"[Farm DEBUG] Участок {plot_num}: Списание семян УСПЕШНО.")

    farm_data = await db.get_user_farm_data(user_id)
    field_lvl = farm_data.get('field_level', 1)
    field_stats = get_level_data(field_lvl, FIELD_UPGRADES)
    
    product_id = SEED_TO_PRODUCT_ID.get(crop_id)
    
    if not product_id or product_id not in field_stats.get('grow_time_min', {}):
        logging.error(f"[Farm DEBUG] Участок {plot_num}: ОШИБКА! Не найден product_id для {crop_id}.")
        await db.modify_inventory(user_id, crop_id, 1) 
        await callback.answer(f"⛔ Внутренняя ошибка! Не найдено время для {crop_id}.", show_alert=True)
        return

    time_m = int(field_stats['grow_time_min'][product_id]) 
    ready_time = datetime.now() + timedelta(minutes=time_m)
    
    # --- Шаг 2: Посадка в БД ---
    planted = False
    try:
        logging.info(f"[Farm DEBUG] Участок {plot_num}: Пытаемся вызвать db.plant_crop()...")
        planted = await db.plant_crop(user_id, plot_num, crop_id, ready_time)
        logging.info(f"[Farm DEBUG] Участок {plot_num}: db.plant_crop() ВЫПОЛНЕНО. Результат: {planted}")
        
    except Exception as e:
        logging.error(f"[Farm DEBUG] Участок {plot_num}: НЕИЗВЕСТНАЯ ОШИБКА при db.plant_crop(): {e}")
        await callback.answer(f"⛔ Неизвестная ошибка: {e}", show_alert=True)
        await db.modify_inventory(user_id, crop_id, 1) # (Возвращаем семя)
        return

    if not planted:
        logging.error(f"[Farm DEBUG] Участок {plot_num} (user {user_id}) уже был занят (UNIQUE constraint).")
        await db.modify_inventory(user_id, crop_id, 1) 
        await callback.answer("⛔ Ошибка! Эта грядка уже занята.", show_alert=True)
        return

    await callback.answer(f"✅ Грядка {plot_num} засажена! (Готово через {time_m} мин)")
    
    await cq_farm_view_plots(callback, FarmCallback(action="view_plots", owner_id=user_id), db)

@farm_router.callback_query(PlotCallback.filter(F.action == "harvest"))
async def cq_plot_harvest(callback: CallbackQuery, callback_data: PlotCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id): return
    
    user_id = callback.from_user.id
    plot_num = callback_data.plot_num

    crop_id_seed = await db.harvest_plot(user_id, plot_num)
    
    if not crop_id_seed:
        await callback.answer("⛔ Ошибка! Этот участок уже пуст.", show_alert=True)
        return
        
    crop_id_product = SEED_TO_PRODUCT_ID.get(crop_id_seed)
    if not crop_id_product:
         await callback.answer(f"⛔ Ошибка! Неизвестный ID семени: {crop_id_seed}", show_alert=True)
         return
         
    product_name = FARM_ITEM_NAMES[crop_id_product]
    
    farm_data = await db.get_user_farm_data(user_id)
    field_stats = get_level_data(farm_data.get('field_level', 1), FIELD_UPGRADES)
    chance_x2 = field_stats.get('chance_x2', 0)
    
    amount_to_add = 1
    # --- ✅✅✅ (Piva Bot) ФИКС ТЕКСТА УВЕДОМЛЕНИЯ ✅✅✅ ---
    alert_text = f"✅ Собран +1 {product_name}!"
    
    if chance_x2 > 0 and random.randint(1, 100) <= chance_x2:
        amount_to_add = 2
        alert_text = f"🎉 УДАЧА (x2)! 🎉\nСобран +2 {product_name}!" # (Убрали <b>)
    # --- ---

    await db.modify_inventory(user_id, crop_id_product, amount_to_add)

    await callback.answer(alert_text, show_alert=True)
    
    await cq_farm_view_plots(callback, FarmCallback(action="view_plots", owner_id=user_id), db)

@farm_router.callback_query(PlotCallback.filter(F.action == "show_time"))
async def cq_plot_show_time(callback: CallbackQuery, callback_data: PlotCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id):
        return

    user_id = callback_data.owner_id
    plot_num = callback_data.plot_num

    active_plots_data = await db.get_user_plots(user_id)
    plot_info = None
    for plot in active_plots_data:
        if plot[0] == plot_num: 
            plot_info = plot
            break

    if not plot_info or not isinstance(plot_info[2], str):
        await callback.answer("Ошибка! Грядка уже пуста (или не найдена).", show_alert=True)
        return

    ready_time = datetime.fromisoformat(plot_info[2])
    now = datetime.now()

    if now >= ready_time:
        await callback.answer("✅ Готово! Нажмите 'Собрать'.", show_alert=True)
    else:
        time_left = format_time_delta(ready_time - now)
        await callback.answer(f"⏳ Еще созревает. Осталось: {time_left}", show_alert=True)
# --- ---


# --- (Пивоварня) ---

@farm_router.callback_query(BreweryCallback.filter(F.action == "brew_menu"))
async def cq_brewery_menu(callback: CallbackQuery, callback_data: BreweryCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id): 
        return

    uid = callback.from_user.id
    farm = await db.get_user_farm_data(uid)
    inv  = await db.get_user_inventory(uid)

    lvl  = farm.get('brewery_level', 1)
    st   = get_level_data(lvl, BREWERY_UPGRADES)

    need_g = BREWERY_RECIPE['зерно']
    need_h = BREWERY_RECIPE['хмель']

    max_by_g = inv['зерно'] // need_g if need_g > 0 else 999
    max_by_h = inv['хмель'] // need_h if need_h > 0 else 999
    max_brew = min(max_by_g, max_by_h)

    text = (
        f"<b>🏭 Пивоварня (Ур. {lvl})</b>\n"
        f"Рецепт: {need_g} × {FARM_ITEM_NAMES['зерно']} + {need_h} × {FARM_ITEM_NAMES['хмель']}\n"
        f"Награда: +{st.get('reward', '??')} 🍺 | Время: {st.get('brew_time_min', '??')} мин\n\n" 
        f"<b>На складе:</b>  {FARM_ITEM_NAMES['зерно']}: <b>{inv['зерно']}</b> / {need_g} • "
        f"{FARM_ITEM_NAMES['хмель']}: <b>{inv['хмель']}</b> / {need_h}\n"
    )

    buttons = []
    if max_brew > 0:
        text += f"\nМожешь сварить: <b>{max_brew}</b> порций."
        btns = []
        for qty in (1, 5, 10):
            if max_brew >= qty:
                total = timedelta(minutes=int(st.get('brew_time_min', 30)) * qty)
                btns.append(InlineKeyboardButton(
                    text=f"🔥 {qty} ({format_time_delta(total)})", 
                    callback_data=BreweryCallback(action="brew_do", owner_id=uid, quantity=qty).pack()
                ))
        if max_brew not in (1, 5, 10) and max_brew > 0:
            total = timedelta(minutes=int(st.get('brew_time_min', 30)) * max_brew)
            btns.append(InlineKeyboardButton(
                text=f"🔥 MAX {max_brew} ({format_time_delta(total)})", 
                callback_data=BreweryCallback(action="brew_do", owner_id=uid, quantity=max_brew).pack()
            ))
        buttons += rows(btns, per_row=3)
    else:
        text += "\n⛔ <b>Недостаточно ресурсов для варки.</b>"

    buttons.append(back_btn_to_farm(uid))

    with suppress(TelegramBadRequest):
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@farm_router.callback_query(BreweryCallback.filter(F.action == "brew_do"))
async def cq_brewery_do(callback: CallbackQuery, callback_data: BreweryCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id): return
    
    user_id = callback.from_user.id
    quantity = callback_data.quantity
    
    if quantity <= 0:
        await callback.answer("⛔ Ошибка! Неверное количество.", show_alert=True)
        return

    inventory = await db.get_user_inventory(user_id)
    cost_grain = BREWERY_RECIPE['зерно'] * quantity
    cost_hops = BREWERY_RECIPE['хмель'] * quantity
    
    if inventory['зерно'] < cost_grain or inventory['хмель'] < cost_hops:
        await callback.answer("⛔ Ошибка! У тебя закончились ресурсы, пока ты думал.", show_alert=True)
        await cq_brewery_menu(callback, BreweryCallback(action="brew_menu", owner_id=user_id), db)
        return

    success_grain = await db.modify_inventory(user_id, 'зерно', -cost_grain)
    success_hops = await db.modify_inventory(user_id, 'хмель', -cost_hops)
    
    if not success_grain or not success_hops:
        if success_grain: await db.modify_inventory(user_id, 'зерно', cost_grain)
        if success_hops: await db.modify_inventory(user_id, 'хмель', cost_hops)
        await callback.answer("⛔ Ошибка! Не хватило ресурсов (повторная проверка).", show_alert=True)
        await cq_brewery_menu(callback, BreweryCallback(action="brew_menu", owner_id=user_id), db)
        return
    
    farm_data = await db.get_user_farm_data(user_id)
    brewery_lvl = farm_data.get('brewery_level', 1)
    brewery_stats = get_level_data(brewery_lvl, BREWERY_UPGRADES)
    
    brew_time_min = int(brewery_stats.get('brew_time_min', 30))
    
    total_time_minutes = brew_time_min * quantity
    end_time = datetime.now() + timedelta(minutes=total_time_minutes)
    
    await db.start_brewing(user_id, quantity, end_time)

    await callback.answer(f"✅ Варка {quantity}x порций началась! (Готово через {format_time_delta(timedelta(minutes=total_time_minutes))})")
    await cq_farm_main_dashboard(callback, FarmCallback(action="main_dashboard", owner_id=user_id), db)

@farm_router.callback_query(BreweryCallback.filter(F.action == "collect"))
async def cq_brewery_collect(callback: CallbackQuery, callback_data: BreweryCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id): return
    
    user_id = callback.from_user.id
    
    try:
        farm_data = await db.get_user_farm_data(user_id)
        brewery_lvl = farm_data.get('brewery_level', 1)
        brewery_stats = get_level_data(brewery_lvl, BREWERY_UPGRADES)
        
        batch_size = farm_data.get('brewery_batch_size', 0)
        batch_timer = farm_data.get('brewery_batch_timer_end')
        
        if batch_size == 0 or not batch_timer:
            await callback.answer("⛔ Ошибка! Нечего забирать.", show_alert=True)
            return
            
        if datetime.now() < batch_timer:
            await callback.answer("⛔ Еще не готово!", show_alert=True)
            return
        
        reward_per_one = brewery_stats.get('reward')
        if reward_per_one is None:
            logging.error(f"[Farm DEBUG] КРИТИЧЕСКАЯ ОШИБКА: 'reward' не найден в brewery_stats (Уровень: {brewery_lvl})")
            await callback.answer("⛔ Критическая ошибка! 'reward' не найден.", show_alert=True)
            return

        total_reward = reward_per_one * batch_size
        
        await db.collect_brewery(user_id, total_reward)

        # --- ✅✅✅ (Piva Bot) ФИКС ТЕКСТА УВЕДОМЛЕНИЯ ✅✅✅ ---
        # (Убрали <b> и 🎉)
        await callback.answer(f"УСПЕХ!\nТы получил +{total_reward} 🍺 Рейтинга!", show_alert=True)
        # --- ---
        
        await cq_farm_main_dashboard(callback, FarmCallback(action="main_dashboard", owner_id=user_id), db)
    
    except Exception as e:
        logging.error(f"[Farm DEBUG] КРИТИЧЕСКАЯ ОШИБКА в cq_brewery_collect: {e}")
        await callback.answer(f"⛔ Ошибка сбора! База данных занята (locked) или {e}", show_alert=True)
        await cq_farm_main_dashboard(callback, FarmCallback(action="main_dashboard", owner_id=user_id), db)
# --- ---


# --- "ИДЕАЛЬНОЕ МЕНЮ УЛУЧШЕНИЙ" (Piva Bot) ---
@farm_router.callback_query(FarmCallback.filter(F.action == "upgrades"))
async def cq_farm_upgrades(callback: CallbackQuery, callback_data: FarmCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id): return
    
    user_id = callback.from_user.id
    
    balance = await db.get_user_beer_rating(user_id)
    farm_data = await db.get_user_farm_data(user_id)
    now = datetime.now()

    field_lvl = farm_data.get('field_level', 1)
    brewery_lvl = farm_data.get('brewery_level', 1)
    
    field_stats = get_level_data(field_lvl, FIELD_UPGRADES)
    brewery_stats = get_level_data(brewery_lvl, BREWERY_UPGRADES)
    
    text = (
        f"<b>⭐ Улучшения</b>\n"
        f"<i>Твой Рейтинг: {balance} 🍺</i>\n\n"
    )
    
    buttons = []
    
    # --- БЛОК: ПОЛЕ (Piva Bot) ---
    text += f"<b>🌱 Поле — Уровень {field_lvl}</b>\n"
    field_upgrade_timer = farm_data.get('field_upgrade_timer_end')

    if field_upgrade_timer and now < field_upgrade_timer:
        time_left = format_time_delta(field_upgrade_timer - now)
        text += f"<i>(Строится... ⏳ {time_left})</i>\n"
        buttons.append([InlineKeyboardButton(text=f"Поле (Строится... ⏳ {time_left})", callback_data=UpgradeCallback(action="dummy_build", owner_id=user_id).pack())])
    
    else:
        text += "📌 Текущие бонусы:\n"
        text += f"• Грядок: {field_stats.get('plots', '??')}\n"
        text += f"• Шанс x2: {field_stats.get('chance_x2', '??')}%\n"
        text += f"• Рост: 🌾 {field_stats.get('grow_time_min', {}).get('зерно', '??')}м / 🌱 {field_stats.get('grow_time_min', {}).get('хмель', '??')}м\n"
        
        if field_stats.get('max_level', False):
            text += "\n<b>⭐ Поле — максимальный уровень!</b>\n"
            buttons.append([InlineKeyboardButton(text="✅ Поле (Макс. Уровень)", callback_data=UpgradeCallback(action="dummy_max", owner_id=user_id).pack())])
        else:
            next_field_stats = FIELD_UPGRADES.get(field_lvl + 1, {})
            cost = next_field_stats.get('cost')
            time_h = next_field_stats.get('time_h')
            
            text += f"\n➡ Следующий уровень ({field_lvl + 1}):\n"
            text += f"• Грядок: {field_stats.get('plots', '??')} → {next_field_stats.get('plots', '??')}\n"
            text += f"• Шанс x2: {field_stats.get('chance_x2', '??')}% → {next_field_stats.get('chance_x2', '??')}%\n"
            text += f"• Рост (🌾): {field_stats.get('grow_time_min', {}).get('зерно', '??')}м → {next_field_stats.get('grow_time_min', {}).get('зерно', '??')}м\n"
            
            text += f"💰 Стоимость: {cost} 🍺\n"
            text += f"⏳ Время улучшения: {time_h} ч\n"
            
            if balance < cost:
                buttons.append([InlineKeyboardButton(text=f"⛔ Недостаточно 🍺 ({cost})", callback_data=UpgradeCallback(action="dummy_money", owner_id=user_id).pack())])
            else:
                buttons.append([InlineKeyboardButton(text="⬆️ Улучшить Поле", callback_data=UpgradeCallback(action="buy_field", owner_id=user_id).pack())])

    # --- РАЗДЕЛИТЕЛЬ (Piva Bot) ---
    text += "\n────────────────────\n\n"

    # --- БЛОК: ПИВОВАРНЯ (Piva Bot) ---
    text += f"<b>🏭 Пивоварня — Уровень {brewery_lvl}</b>\n"
    brewery_upgrade_timer = farm_data.get('brewery_upgrade_timer_end')

    if brewery_upgrade_timer and now < brewery_upgrade_timer:
        time_left = format_time_delta(brewery_upgrade_timer - now)
        text += f"<i>(Строится... ⏳ {time_left})</i>\n"
        buttons.append([InlineKeyboardButton(text=f"Пивоварня (Строится... ⏳ {time_left})", callback_data=UpgradeCallback(action="dummy_build", owner_id=user_id).pack())])
    
    else:
        text += "📌 Текущие бонусы:\n"
        text += f"• Награда за варку: +{brewery_stats.get('reward', '??')} 🍺\n"
        text += f"• Время варки: {brewery_stats.get('brew_time_min', '??')} мин\n" 
        
        if brewery_stats.get('max_level', False):
            text += "\n<b>⭐ Пивоварня — максимальный уровень!</b>\n"
            buttons.append([InlineKeyboardButton(text="✅ Пивоварня (Макс. Уровень)", callback_data=UpgradeCallback(action="dummy_max", owner_id=user_id).pack())])
        else:
            next_brew_stats = BREWERY_UPGRADES.get(brewery_lvl + 1, {})
            cost = next_brew_stats.get('cost')
            time_h = next_brew_stats.get('time_h')

            text += f"\n➡ Следующий уровень ({brewery_lvl + 1}):\n"
            text += f"• Награда: +{brewery_stats.get('reward', '??')} → +{next_brew_stats.get('reward', '??')} 🍺\n"
            text += f"• Время варки: {brewery_stats.get('brew_time_min', '??')}м → {next_brew_stats.get('brew_time_min', '??')}м\n" 

            text += f"💰 Стоимость: {cost} 🍺\n"
            text += f"⏳ Время улучшения: {time_h} ч\n"

            if balance < cost:
                buttons.append([InlineKeyboardButton(text=f"⛔ Недостаточно 🍺 ({cost})", callback_data=UpgradeCallback(action="dummy_money", owner_id=user_id).pack())])
            else:
                buttons.append([InlineKeyboardButton(text="⬆️ Улучшить Пивоварню", callback_data=UpgradeCallback(action="buy_brewery", owner_id=user_id).pack())])

    # --- РАЗДЕЛИТЕЛЬ (Piva Bot) ---
    text += "\n────────────────────\n"
    
    # --- Кнопка НАЗАД (Piva Bot) ---
    buttons.append(back_btn_to_farm(user_id))
    
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()
# --- ---


@farm_router.callback_query(UpgradeCallback.filter(F.action.in_({"buy_field", "buy_brewery"})))
async def cq_upgrade_confirm(callback: CallbackQuery, callback_data: UpgradeCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id): return
    
    user_id = callback.from_user.id
    building = "field" if callback_data.action == "buy_field" else "brewery"
    
    farm_data = await db.get_user_farm_data(user_id)
    balance = await db.get_user_beer_rating(user_id)
    
    if building == "field":
        level = farm_data.get('field_level', 1)
        next_level_stats = get_level_data(level + 1, FIELD_UPGRADES)
        building_name = "🌾 Поле"
        block_warning = "На время улучшения твои [🌾 Грядки] **будут недоступны**."
        confirm_callback = UpgradeCallback(action="confirm_field", owner_id=user_id).pack()
    else:
        level = farm_data.get('brewery_level', 1)
        next_level_stats = get_level_data(level + 1, BREWERY_UPGRADES)
        building_name = "🏭 Пивоварня"
        block_warning = "На время улучшения [🏭 Пивоварня] **будет недоступна** (ты не сможешь варить)."
        confirm_callback = UpgradeCallback(action="confirm_brewery", owner_id=user_id).pack()

    cost = next_level_stats['cost']
    time_h = next_level_stats['time_h']

    if balance < cost:
        await callback.answer(f"⛔ Недостаточно 🍺! Нужно {cost} 🍺.", show_alert=True)
        return

    text = (
        f"<b>Подтверждение Прокачки</b>\n\n"
        f"Ты улучшаешь <b>{building_name}</b> до <b>Ур. {level + 1}</b>.\n\n"
        f"• <b>Цена:</b> {cost} 🍺\n"
        f"• <b>Время:</b> {time_h} часов\n\n"
        f"⚠️ {block_warning}\n\n"
        f"Начать прокачку?"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=f"✅ Да, начать ({time_h} ч)", callback_data=confirm_callback),
            InlineKeyboardButton(text="❌ Нет, я передумал", callback_data=FarmCallback(action="upgrades", owner_id=user_id).pack())
        ]
    ])
    
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()

@farm_router.callback_query(UpgradeCallback.filter(F.action.in_({"confirm_field", "confirm_brewery"})))
async def cq_upgrade_do(callback: CallbackQuery, callback_data: UpgradeCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id): return
    
    user_id = callback.from_user.id
    building = "field" if callback_data.action == "confirm_field" else "brewery"

    farm_data = await db.get_user_farm_data(user_id)
    balance = await db.get_user_beer_rating(user_id)
    
    if farm_data.get(f"{building}_upgrade_timer_end"):
        await callback.answer(f"⛔ Ошибка! {building} уже прокачивается!", show_alert=True)
        return

    if building == "field":
        level = farm_data.get('field_level', 1)
        next_level_stats = get_level_data(level + 1, FIELD_UPGRADES)
    else:
        level = farm_data.get('brewery_level', 1)
        next_level_stats = get_level_data(level + 1, BREWERY_UPGRADES)

    cost = next_level_stats['cost']
    time_h = next_level_stats['time_h']

    if balance < cost:
        await callback.answer(f"⛔ Недостаточно 🍺! Нужно {cost} 🍺.", show_alert=True)
        await cq_farm_upgrades(callback, FarmCallback(action="upgrades", owner_id=user_id), db)
        return

    end_time = datetime.now() + timedelta(hours=time_h)
    await db.start_upgrade(user_id, building, end_time, cost)
    
    await callback.answer(f"✅ Прокачка до Ур. {level + 1} началась! (Готово через {time_h} ч)")
    await cq_farm_main_dashboard(callback, FarmCallback(action="main_dashboard", owner_id=user_id), db)

# --- (Хэлпер) ---
@farm_router.callback_query(FarmCallback.filter(F.action == "show_help"))
async def cq_farm_show_help(callback: CallbackQuery, callback_data: FarmCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id): 
        return

    user_id = callback.from_user.id
    
    text = (
        "<b>❓ Как играть на Ферме</b>\n\n"
        "Цель: Варить 🍺 Пиво, чтобы получать 🍺 Рейтинг.\n\n"
        "<b>1. 🌾 Поле (Грядки)</b>\n"
        "• Нажми [🟦 Пусто], чтобы посадить <b>Семена</b>.\n"
        "• Семена можно купить в [🏪 Магазине].\n"
        "• Подожди таймер и собери [✅ Урожай].\n\n"
        "<b>2. 🏭 Пивоварня</b>\n"
        "• Когда у тебя есть <b>Урожай</b> (🌾 Зерно и 🌱 Хмель), нажми [🔥 Начать варку].\n"
        "• Подожди таймер и забери [🏆 Награду] (это твой 🍺 Рейтинг).\n\n"
        "<b>3. ⭐ Улучшения</b>\n"
        "• Трать 🍺 Рейтинг, чтобы улучшать Поле и Пивоварню.\n"
        "• Улучшение <b>Поля</b>: Дает больше Грядок и ускоряет Рост.\n"
        "• Улучшение <b>Пивоварни</b>: Дает больше 🍺 Рейтинга и ускоряет Варку."
    )

    kb = [back_btn_to_farm(user_id)]
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await callback.answer()
# --- ---

# --- (Обработчики "мёртвых" кнопок) ---

@farm_router.callback_query(UpgradeCallback.filter(F.action == "dummy_money"))
async def cq_dummy_money(callback: CallbackQuery, callback_data: UpgradeCallback):
    """(Piva Bot) Юзер нажал на 'Недостаточно 🍺'"""
    if not await check_owner(callback, callback_data.owner_id): return
    await callback.answer("⛔ Недостаточно 🍺 Рейтинга для этого улучшения!", show_alert=True)

@farm_router.callback_query(UpgradeCallback.filter(F.action == "dummy_build"))
async def cq_dummy_build(callback: CallbackQuery, callback_data: UpgradeCallback):
    """(Piva Bot) Юзер нажал на 'Строится...'"""
    if not await check_owner(callback, callback_data.owner_id): return
    await callback.answer("⏳ Здание еще улучшается. Ты сможешь нажать, когда стройка закончится.", show_alert=True)

@farm_router.callback_query(UpgradeCallback.filter(F.action == "dummy_max"))
async def cq_dummy_max(callback: CallbackQuery, callback_data: UpgradeCallback):
    """(Piva Bot) Юзер нажал на 'Макс. Уровень'"""
    if not await check_owner(callback, callback_data.owner_id): return
    await callback.answer("✅ У тебя уже максимальный уровень!", show_alert=True)
# --- ---
