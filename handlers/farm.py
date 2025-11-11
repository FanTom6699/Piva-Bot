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

# --- ✅ ИЗМЕНЕННЫЙ ИМПОРТ (Piva Bot) ✅ ---
from .farm_config import (
    FARM_ITEM_NAMES, 
    BREWERY_RECIPE, 
    FIELD_UPGRADES, # Теперь время здесь
    BREWERY_UPGRADES, 
    get_level_data,
    SHOP_PRICES,
    CROP_CODE_TO_ID,
    CROP_SHORT,
    SEED_TO_PRODUCT_ID # Новый импорт
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

# --- RENDER: DASHBOARD ---
async def get_farm_dashboard(user_id: int, user_name: str, db: Database) -> (str, InlineKeyboardMarkup):
    farm = await db.get_user_farm_data(user_id)
    now = datetime.now()

    field_lvl = farm.get('field_level', 1)
    brew_lvl  = farm.get('brewery_level', 1)

    field = get_level_data(field_lvl, FIELD_UPGRADES)
    brew  = get_level_data(brew_lvl,  BREWERY_UPGRADES)

    active_plots = await db.get_user_plots(user_id)
    any_ready = False
    for p in active_plots:
        if isinstance(p[2], str) and now >= datetime.fromisoformat(p[2]):
            any_ready = True
            break

    text = (
        f"{dash_title(user_name)}\n\n"
        f"<b>📊 Статистика:</b>\n"
    )

    fld_timer = farm.get('field_upgrade_timer_end')
    if fld_timer and now < fld_timer:
        left = format_time_delta(fld_timer - now)
        text += f"• <b>Поле:</b> Ур. {field_lvl} ➜ {field_lvl+1} <i>(идёт улучшение ⏳ {left})</i>\n"
    else:
        # --- ✅ АДАПТАЦИЯ (Piva Bot): Показываем время роста ---
        g_time = field['grow_time_min']['зерно']
        h_time = field['grow_time_min']['хмель']
        text += f"• <b>Поле:</b> Ур. {field_lvl} ({field['plots']} уч., 🌾 {g_time}м, 🌱 {h_time}м)\n"
        # --- ---

    brew_timer = farm.get('brewery_upgrade_timer_end')
    batch_timer = farm.get('brewery_batch_timer_end')
    text += f"• <b>Пивоварня:</b> Ур. {brew_lvl} — +{brew['reward']} 🍺, Варка: {brew['brew_time_min']} мин\n"

    kb = []

    if fld_timer and now < fld_timer:
        kb.append([InlineKeyboardButton(text="🌾 Поле (⚠ закрыто на улучшение)", callback_data="dummy")])
    else:
        field_btn_text = "🌾 Моё Поле (СОБРАТЬ!)" if any_ready else "🌾 Моё Поле (Участки)"
        kb.append([InlineKeyboardButton(text=field_btn_text, callback_data=FarmCallback(action="view_plots", owner_id=user_id).pack())])

    if brew_timer and now < brew_timer:
        left = format_time_delta(brew_timer - now)
        kb.append([InlineKeyboardButton(text=f"🏭 Пивоварня (улучшается ⏳ {left})", callback_data="dummy")])
    else:
        batch_size = farm.get('brewery_batch_size', 0)
        if batch_timer:
            if now >= batch_timer:
                total = brew['reward'] * batch_size
                kb.append([InlineKeyboardButton(text=f"🏆 Забрать +{total} 🍺 ({batch_size}x)", callback_data=BreweryCallback(action="collect", owner_id=user_id).pack())])
            else:
                left = format_time_delta(batch_timer - now)
                kb.append([InlineKeyboardButton(text=f"🏭 Варка {batch_size}x… {left} ⏳", callback_data="dummy")])
        else:
            kb.append([InlineKeyboardButton(text="🏭 Пивоварня (Готова)", callback_data=BreweryCallback(action="brew_menu", owner_id=user_id).pack())])

    kb += rows([
        InlineKeyboardButton(text="📦 Склад",     callback_data=FarmCallback(action="inventory", owner_id=user_id).pack()),
        InlineKeyboardButton(text="⭐ Улучшения", callback_data=FarmCallback(action="upgrades",  owner_id=user_id).pack()),
        InlineKeyboardButton(text="🏪 Магазин",   callback_data=FarmCallback(action="shop",      owner_id=user_id).pack()),
    ], per_row=2)

    return text, InlineKeyboardMarkup(inline_keyboard=kb)
# --- ---

# --- RENDER: FIELD ---
async def get_plots_dashboard(user_id: int, db: Database) -> (str, InlineKeyboardMarkup):
    farm = await db.get_user_farm_data(user_id)
    now = datetime.now()

    lvl = farm.get('field_level', 1)
    stats = get_level_data(lvl, FIELD_UPGRADES)
    max_plots = stats['plots']
    
    # --- ✅ АДАПТАЦИЯ (Piva Bot): Показываем время роста ---
    g_time = stats['grow_time_min']['зерно']
    h_time = stats['grow_time_min']['хмель']
    
    text = (
        f"<b>🌱 Поле (Ур. {lvl})</b>\n"
        f"<i>Участков: {max_plots}, Шанс x2: {stats['chance_x2']}%</i>\n"
        f"<i>Время роста: 🌾 {g_time}м / 🌱 {h_time}м</i>\n\n"
        f"Нажми на <b>Пусто</b>, чтобы посадить.\n"
    )
    # --- ---

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
            
            # --- ✅ АДАПТАЦИЯ (Piva Bot): Используем SEED_TO_PRODUCT_ID ---
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
            txt = f"🟦 Участок {i} (Пусто)"
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
        f"<b>🌱 Посадка — Участок {plot_num}</b>\n\n"
        f"<i>На складе:</i>\n"
        f"• {FARM_ITEM_NAMES['семя_зерна']}: {inventory['семя_зерна']}\n"
        f"• {FARM_ITEM_NAMES['семя_хмеля']}: {inventory['семя_хмеля']}"
    )
    
    buttons = []
    
    # --- ✅ АДАПТАЦИЯ (Piva Bot): Берем время из Уровня Поля ---
    farm_data = await db.get_user_farm_data(user_id)
    field_lvl = farm_data.get('field_level', 1)
    field_stats = get_level_data(field_lvl, FIELD_UPGRADES)
    # --- ---
    
    if inventory['семя_зерна'] > 0:
        time_m = field_stats['grow_time_min']['зерно'] # <-- Новое время
        buttons.append(InlineKeyboardButton(
            text=f"Посадить 🌾 Зерно ({time_m} мин)", 
            callback_data=PlotCallback(action="plant_do", owner_id=user_id, plot_num=plot_num, crop_id="g").pack()
        ))
    
    if inventory['семя_хмеля'] > 0:
        time_m = field_stats['grow_time_min']['хмель'] # <-- Новое время
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

    keyboard_rows = rows(buttons, per_row=2)
    
    keyboard_rows.append([
        InlineKeyboardButton(text="⬅️ Назад в Поле", callback_data=FarmCallback(action="view_plots", owner_id=user_id).pack())
    ])
    
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_rows))
    await callback.answer()

# --- ХЭНДЛЕР ПОСАДКИ (С ФИКСОМ) ---
@farm_router.callback_query(PlotCallback.filter(F.action == "plant_do"))
async def cq_plot_plant_do(callback: CallbackQuery, callback_data: PlotCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id): return

    user_id = callback.from_user.id
    plot_num = callback_data.plot_num
    
    code = callback_data.crop_id
    crop_id = CROP_CODE_TO_ID.get(code) # 'семя_зерна' / 'семя_хмеля'

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

    # --- ✅ АДАПТАЦИЯ (Piva Bot): Берем время из Уровня Поля ---
    farm_data = await db.get_user_farm_data(user_id)
    field_lvl = farm_data.get('field_level', 1)
    field_stats = get_level_data(field_lvl, FIELD_UPGRADES)
    
    product_id = SEED_TO_PRODUCT_ID.get(crop_id) # 'зерно' / 'хмель'
    
    # (Piva Bot: Проверка, что product_id найден, иначе будет краш)
    if not product_id or product_id not in field_stats['grow_time_min']:
        logging.error(f"[Farm DEBUG] Участок {plot_num}: ОШИБКА! Не найден product_id для {crop_id}.")
        await db.modify_inventory(user_id, crop_id, 1) # (Возвращаем семя)
        await callback.answer(f"⛔ Внутренняя ошибка! Не найдено время для {crop_id}.", show_alert=True)
        return

    time_m = int(field_stats['grow_time_min'][product_id]) 
    ready_time = datetime.now() + timedelta(minutes=time_m)
    # --- ---
    
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
        await db.modify_inventory(user_id, crop_id, 1) # (Возвращаем семя)
        await callback.answer("⛔ Ошибка! Этот участок уже занят.", show_alert=True)
        return

    await callback.answer(f"✅ Участок {plot_num} засажен! (Готово через {time_m} мин)")
    
    await cq_farm_view_plots(callback, FarmCallback(action="view_plots", owner_id=user_id), db)
# --- ---

@farm_router.callback_query(PlotCallback.filter(F.action == "harvest"))
async def cq_plot_harvest(callback: CallbackQuery, callback_data: PlotCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id): return
    
    user_id = callback.from_user.id
    plot_num = callback_data.plot_num

    crop_id_seed = await db.harvest_plot(user_id, plot_num)
    
    if not crop_id_seed:
        await callback.answer("⛔ Ошибка! Этот участок уже пуст.", show_alert=True)
        return
        
    # --- ✅ АДАПТАЦИЯ (Piva Bot): Используем SEED_TO_PRODUCT_ID ---
    crop_id_product = SEED_TO_PRODUCT_ID.get(crop_id_seed)
    if not crop_id_product:
         await callback.answer(f"⛔ Ошибка! Неизвестный ID семени: {crop_id_seed}", show_alert=True)
         return
         
    product_name = FARM_ITEM_NAMES[crop_id_product]
    # --- ---
    
    farm_data = await db.get_user_farm_data(user_id)
    field_stats = get_level_data(farm_data.get('field_level', 1), FIELD_UPGRADES)
    chance_x2 = field_stats['chance_x2']
    
    amount_to_add = 1
    alert_text = f"✅ Собран +1 {product_name}!"
    
    if chance_x2 > 0 and random.randint(1, 100) <= chance_x2:
        amount_to_add = 2
        alert_text = f"🎉 <b>УДАЧА (x2)!</b> 🎉\nСобран +2 {product_name}!"

    await db.modify_inventory(user_id, crop_id_product, amount_to_add)

    await callback.answer(alert_text, show_alert=True)
    
    await cq_farm_view_plots(callback, FarmCallback(action="view_plots", owner_id=user_id), db)

# --- (Хэндлер "покажи время" - без изменений) ---
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
        await callback.answer("Ошибка! Участок уже пуст (или не найден).", show_alert=True)
        return

    ready_time = datetime.fromisoformat(plot_info[2])
    now = datetime.now()

    if now >= ready_time:
        await callback.answer("✅ Готово! Нажмите 'Собрать'.", show_alert=True)
    else:
        time_left = format_time_delta(ready_time - now)
        await callback.answer(f"⏳ Еще созревает. Осталось: {time_left}", show_alert=True)
# --- ---


# --- (Пивоварня - без изменений) ---

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
        f"Награда: +{st['reward']} 🍺 | Время: {st['brew_time_min']} мин\n\n"
        f"<b>На складе:</b>  {FARM_ITEM_NAMES['зерно']}: <b>{inv['зерно']}</b> / {need_g} • "
        f"{FARM_ITEM_NAMES['хмель']}: <b>{inv['хмель']}</b> / {need_h}\n"
    )

    buttons = []
    if max_brew > 0:
        text += f"\nМожешь сварить: <b>{max_brew}</b> порций."
        btns = []
        for qty in (1, 5, 10):
            if max_brew >= qty:
                # (Piva Bot: Проверка на int() для времени варки)
                total = timedelta(minutes=int(st['brew_time_min']) * qty)
                btns.append(InlineKeyboardButton(
                    text=f"🔥 {qty} ({format_time_delta(total)})",
                    callback_data=BreweryCallback(action="brew_do", owner_id=uid, quantity=qty).pack()
                ))
        if max_brew not in (1, 5, 10) and max_brew > 0:
            # (Piva Bot: Проверка на int() для времени варки)
            total = timedelta(minutes=int(st['brew_time_min']) * max_brew)
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
    
    brew_time_min = int(brewery_stats['brew_time_min'])
    
    total_time_minutes = brew_time_min * quantity
    end_time = datetime.now() + timedelta(minutes=total_time_minutes)
    
    await db.start_brewing(user_id, quantity, end_time)

    await callback.answer(f"✅ Варка {quantity}x порций началась! (Готово через {format_time_delta(timedelta(minutes=total_time_minutes))})")
    await cq_farm_main_dashboard(callback, FarmCallback(action="main_dashboard", owner_id=user_id), db)

@farm_router.callback_query(BreweryCallback.filter(F.action == "collect"))
async def cq_brewery_collect(callback: CallbackQuery, callback_data: BreweryCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id): return
    
    user_id = callback.from_user.id
    
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
        
    reward_per_one = brewery_stats['reward']
    total_reward = reward_per_one * batch_size
    
    await db.collect_brewery(user_id, total_reward)

    await callback.answer(f"🎉🎉🎉 <b>УСПЕХ!</b> 🎉🎉🎉\nТы получил +{total_reward} 🍺 Рейтинга!", show_alert=True)
    await cq_farm_main_dashboard(callback, FarmCallback(action="main_dashboard", owner_id=user_id), db)


# --- УЛУЧШЕНИЯ ---
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
        f"<b>🌟 Меню Улучшений</b>\n"
        f"<i>Твой Рейтинг: {balance} 🍺</i>\n\n"
        f"Здесь ты тратишь 🍺 и ⏳, чтобы прокачать свою Ферму до 10 Уровня.\n\n"
        f"--- --- ---\n"
    )
    
    buttons = []
    
    field_upgrade_timer = farm_data.get('field_upgrade_timer_end')
    
    # --- ✅ АДАПТАЦИЯ (Piva Bot): Показываем время роста ---
    g_time = field_stats['grow_time_min']['зерно']
    h_time = field_stats['grow_time_min']['хмель']
    text += f"<b>🌾 Поле (Ур. {field_lvl})</b>\n"
    text += f"• <i>Дает: {field_stats['plots']} Участка</i>\n"
    text += f"• <i>Шанс x2: {field_stats['chance_x2']}%</i>\n"
    text += f"• <i>Рост: 🌾 {g_time}м / 🌱 {h_time}м</i>\n"
    # --- ---

    if field_upgrade_timer and now < field_upgrade_timer:
        time_left = format_time_delta(field_upgrade_timer - now)
        buttons.append([InlineKeyboardButton(text=f"Поле (Строится... ⏳ {time_left})", callback_data="dummy")])
    
    elif field_stats['max_level']:
        buttons.append([InlineKeyboardButton(text="✅ Поле (Макс. Уровень 10)", callback_data="dummy")])
        
    else:
        next_field_stats_data = FIELD_UPGRADES.get(field_lvl + 1, {})
        cost = next_field_stats_data.get('cost')
        time_h = next_field_stats_data.get('time_h')
        
        bonus_plot = ""
        if next_field_stats_data.get('plots', 0) > field_stats['plots']:
             bonus_plot = f" (Даст {next_field_stats_data['plots']} Участка)"
        
        bonus_chance = ""
        if next_field_stats_data.get('chance_x2', 0) > field_stats['chance_x2']:
             bonus_chance = f" (Даст {next_field_stats_data['chance_x2']}% Шанс x2)"
        
        # --- ✅ АДАПТАЦИЯ (Piva Bot): Показываем ускорение ---
        bonus_time = ""
        next_g_time = next_field_stats_data.get('grow_time_min', {}).get('зерно', g_time)
        if next_g_time < g_time:
             bonus_time = f" (Рост {next_g_time}м)"
        # --- ---
             
        btn_text = f"Улучшить до Ур. {field_lvl + 1}{bonus_plot}{bonus_chance}{bonus_time}"
        btn_callback = UpgradeCallback(action="buy_field", owner_id=user_id).pack()
        
        if balance < cost:
            btn_text = f"⛔ (Нужно {cost} 🍺)"
            btn_callback = "dummy"
            
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=btn_callback)])
        buttons.append([InlineKeyboardButton(text=f"(Цена: {cost} 🍺, Время: {time_h} ч)", callback_data=btn_callback)])


    text += f"\n--- --- ---\n"

    brewery_upgrade_timer = farm_data.get('brewery_upgrade_timer_end')

    text += f"<b>🏭 Пивоварня (Ур. {brewery_lvl})</b>\n"
    text += f"• <i>Награда: +{brewery_stats['reward']} 🍺</i>\n"
    text += f"• <i>Варка: {brewery_stats['brew_time_min']} мин/порция</i>\n"

    if brewery_upgrade_timer and now < brewery_upgrade_timer:
        time_left = format_time_delta(brewery_upgrade_timer - now)
        buttons.append([InlineKeyboardButton(text=f"Пивоварня (Строится... ⏳ {time_left})", callback_data="dummy")])
    
    elif brewery_stats['max_level']:
        buttons.append([InlineKeyboardButton(text="✅ Пивоварня (Макс. Уровень 10)", callback_data="dummy")])
        
    else:
        next_brewery_stats = get_level_data(brewery_lvl + 1, BREWERY_UPGRADES)
        cost = next_brewery_stats['cost']
        time_h = next_brewery_stats['time_h']
        
        btn_text = f"Улучшить до Ур. {brewery_lvl + 1} (Награда +{next_brewery_stats['reward']}, Варка {next_brewery_stats['brew_time_min']} мин)"
        btn_callback = UpgradeCallback(action="buy_brewery", owner_id=user_id).pack()

        if balance < cost:
            btn_text = f"⛔ (Нужно {cost} 🍺)"
            btn_callback = "dummy"
            
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=btn_callback)])
        buttons.append([InlineKeyboardButton(text=f"(Цена: {cost} 🍺, Время: {time_h} ч)", callback_data=btn_callback)])

    buttons.append(back_btn_to_farm(user_id))
    
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

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
        block_warning = "На время улучшения твои Участки [🌾 Поля] **будут недоступны**."
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
