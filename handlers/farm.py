# handlers/farm.py
import asyncio
import logging
import random
from datetime import datetime, timedelta
from contextlib import suppress
from typing import Dict, Any
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
    FARM_ITEM_NAMES, PLANT_IO, BREWERY_RECIPE, 
    FIELD_UPGRADES, BREWERY_UPGRADES, get_level_data,
    SHOP_PRICES
)

# --- ИНИЦИАЛИЗАЦИЯ ---
farm_router = Router()

# --- CALLBACKDATA ---
class FarmCallback(CallbackData, prefix="farm"):
    action: str 
    owner_id: int 

class PlotCallback(CallbackData, prefix="plot"):
    action: str 
    owner_id: int
    plot_num: int
    crop_id: str = None

class BreweryCallback(CallbackData, prefix="brew"):
    action: str 
    owner_id: int
    quantity: int = 0

class UpgradeCallback(CallbackData, prefix="upgrade"):
    action: str 
    owner_id: int

# --- ✅ НОВОЕ! "ДАШБОРД ПОЛЯ" (Внутреннее меню) ---
async def get_field_dashboard(user_id: int, db: Database) -> (str, InlineKeyboardMarkup):
    farm_data = await db.get_user_farm_data(user_id)
    now = datetime.now()

    field_lvl = farm_data.get('field_level', 1)
    field_stats = get_level_data(field_lvl, FIELD_UPGRADES)
    max_plots = field_stats['plots']
    
    text = (
        f"<b>🌾 Моё Поле (Ур. {field_lvl})</b>\n"
        f"<i>(Участков: {max_plots}, Шанс x2: {field_stats['chance_x2']}%)</i>\n\n"
        f"Выбери участок для посадки или сбора:"
    )
    
    buttons = []
    
    active_plots_data = await db.get_user_plots(user_id)
    active_plots = {plot[0]: (plot[1], datetime.fromisoformat(plot[2])) for plot in active_plots_data}
    
    plot_buttons = []
    for i in range(1, max_plots + 1):
        if i in active_plots:
            crop_id, ready_time = active_plots[i]
            crop_name = FARM_ITEM_NAMES.get(crop_id, "??").split(' ')[0] 
            
            if now >= ready_time:
                btn_text = f"[Участок {i} ({crop_name} СОБРАТЬ)]"
                btn_callback = PlotCallback(action="harvest", owner_id=user_id, plot_num=i).pack()
            else:
                time_left = format_time_delta(ready_time - now)
                btn_text = f"[Участок {i} ({crop_name}... {time_left} ⏳)]"
                btn_callback = "dummy"
        else:
            btn_text = f"[Участок {i} (Пусто)]"
            btn_callback = PlotCallback(action="plant_menu", owner_id=user_id, plot_num=i).pack()
        
        plot_buttons.append(InlineKeyboardButton(text=btn_text, callback_data=btn_callback))
    
    for i in range(0, len(plot_buttons), 2):
        buttons.append(plot_buttons[i:i+2])

    buttons.append([
        InlineKeyboardButton(text="⬅️ Назад на Ферму", callback_data=FarmCallback(action="main_dashboard", owner_id=user_id).pack())
    ])
    
    return text, InlineKeyboardMarkup(inline_keyboard=buttons)


# --- "ДАШБОРД ФЕРМЫ" (Главное меню /farm) ---
async def get_farm_dashboard(user_id: int, user_name: str, db: Database) -> (str, InlineKeyboardMarkup):
    farm_data = await db.get_user_farm_data(user_id)
    now = datetime.now()

    field_lvl = farm_data.get('field_level', 1)
    brewery_lvl = farm_data.get('brewery_level', 1)
    
    field_stats = get_level_data(field_lvl, FIELD_UPGRADES)
    brewery_stats = get_level_data(brewery_lvl, BREWERY_UPGRADES)
    
    max_plots = field_stats['plots']
    
    text = f"<b>🌾 Ферма Игрока: {escape(user_name)}</b>\n\n"
    text += "<b>СТАТИСТИКА ЗДАНИЙ:</b>\n"
    
    buttons = []
    
    # --- ✅ ИЗМЕНЕНО: Кнопка Поля (Вместо списка участков) ---
    field_upgrade_timer = farm_data.get('field_upgrade_timer_end')
    text += f"• <b>Поле:</b> Ур. {field_lvl} ({field_stats['plots']} Участка, Шанс x2: {field_stats['chance_x2']}%)\n"
    
    if field_upgrade_timer and now < field_upgrade_timer:
        time_left = format_time_delta(field_upgrade_timer - now)
        text = text.replace(f"Ур. {field_lvl}", f"Ур. {field_lvl} ➔ Ур. {field_lvl + 1} (<b>СТРОИТСЯ!</b> ⏳ {time_left})")
        buttons.append([InlineKeyboardButton(text="⛔ Поле закрыто на улучшение ⛔", callback_data="dummy")])
    else:
        # (Считаем статус для кнопки)
        active_plots_data = await db.get_user_plots(user_id)
        active_plots = {plot[0]: (plot[1], datetime.fromisoformat(plot[2])) for plot in active_plots_data}
        
        ready_count = 0
        busy_count = 0
        for i in range(1, max_plots + 1):
             if i in active_plots:
                crop_id, ready_time = active_plots[i]
                if now >= ready_time:
                    ready_count += 1
                else:
                    busy_count += 1
        
        status_text = f"{busy_count + ready_count}/{max_plots} Занято"
        if ready_count > 0:
            status_text = f"✅ {ready_count} Готово!"
            
        btn_text = f"[🌾 Моё Поле ({status_text})]"
        btn_callback = FarmCallback(action="field_dashboard", owner_id=user_id).pack()
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=btn_callback)])
    
    # --- СТАТУС ПИВОВАРНИ (Без изменений) ---
    brewery_upgrade_timer = farm_data.get('brewery_upgrade_timer_end')
    brewery_batch_timer = farm_data.get('brewery_batch_timer_end')
    
    text += f"• <b>Пивоварня:</b> Ур. {brewery_lvl} (Награда: +{brewery_stats['reward']} 🍺, Варка: {brewery_stats['brew_time_min']} мин)\n"
    
    if brewery_upgrade_timer and now < brewery_upgrade_timer:
        time_left = format_time_delta(brewery_upgrade_timer - now)
        text = text.replace(f"Ур. {brewery_lvl}", f"Ур. {brewery_lvl} ➔ Ур. {brewery_lvl + 1} (<b>СТРОИТСЯ!</b> ⏳ {time_left})")
        buttons.append([InlineKeyboardButton(text=f"⛔ Пивоварня (Прокачка... ⏳ {time_left})", callback_data="dummy")])
    
    elif brewery_batch_timer:
        batch_size = farm_data.get('brewery_batch_size', 0)
        
        if now >= brewery_batch_timer:
            total_reward = brewery_stats['reward'] * batch_size
            btn_text = f"[🏭 ЗАБРАТЬ +{total_reward} 🍺 ({batch_size}x)]"
            btn_callback = BreweryCallback(action="collect", owner_id=user_id).pack()
        else:
            time_left = format_time_delta(brewery_batch_timer - now)
            btn_text = f"[🏭 Пивоварня (Варка {batch_size}x... {time_left} ⏳)]"
            btn_callback = "dummy"
        
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=btn_callback)])

    else:
        buttons.append([InlineKeyboardButton(text="[🏭 Пивоварня (Готова к варке)]", callback_data=BreweryCallback(action="brew_menu", owner_id=user_id).pack())])

    # --- Кнопки Управления (Без изменений) ---
    buttons.append([
        InlineKeyboardButton(text="[📦 Мой Склад]", callback_data=FarmCallback(action="inventory", owner_id=user_id).pack()),
        InlineKeyboardButton(text="[🌟 Улучшения]", callback_data=FarmCallback(action="upgrades", owner_id=user_id).pack())
    ])
    buttons.append([
        InlineKeyboardButton(text="[🏪 Магазин Семян (Быстрый доступ)]", callback_data=FarmCallback(action="shop", owner_id=user_id).pack())
    ])
    
    return text, InlineKeyboardMarkup(inline_keyboard=buttons)


# --- ХЭНДЛЕРЫ ---

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

# --- ✅ НОВЫЙ ХЭНДЛЕР (Для кнопки [🌾 Моё Поле]) ---
@farm_router.callback_query(FarmCallback.filter(F.action == "field_dashboard"))
async def cq_farm_field_dashboard(callback: CallbackQuery, callback_data: FarmCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id): return
    text, keyboard = await get_field_dashboard(callback.from_user.id, db)
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()

@farm_router.callback_query(FarmCallback.filter(F.action == "shop"))
async def cq_farm_shop_shortcut(callback: CallbackQuery, callback_data: FarmCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id): return
    
    user_id = callback.from_user.id
    balance = await db.get_user_beer_rating(user_id)
    
    item_name_grain = FARM_ITEM_NAMES['семя_зерна']
    item_name_hops = FARM_ITEM_NAMES['семя_хмеля']
    
    text = (
        f"<b>🏪 Магазин Семян</b> (Быстрый доступ)\n"
        f"<i>Твой баланс: {balance} 🍺</i>\n"
        f"• `{item_name_grain}` - <b>{SHOP_PRICES['семя_зерна']} 🍺 / шт.</b>\n"
        f"• `{item_name_hops}` - <b>{SHOP_PRICES['семя_хмеля']} 🍺 / шт.</b>\n\n"
        f"Чтобы купить, напиши /shop"
    )
    await callback.answer(text, show_alert=True, cache_time=5)

@farm_router.callback_query(FarmCallback.filter(F.action == "inventory"))
async def cq_farm_inventory(callback: CallbackQuery, callback_data: FarmCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id): return
    
    user_id = callback.from_user.id
    inventory = await db.get_user_inventory(user_id)
    
    text = (
        f"<b>📦 Мой Склад</b>\n\n"
        f"<b>УРОЖАЙ (Для Пивоварни):</b>\n"
        f"• `{FARM_ITEM_NAMES['зерно']}`: <b>{inventory['зерно']}</b>\n"
        f"• `{FARM_ITEM_NAMES['хмель']}`: <b>{inventory['хмель']}</b>\n\n"
        f"<b>СЕМЕНА (Для Поля):</b>\n"
        f"• `{FARM_ITEM_NAMES['семя_зерна']}`: <b>{inventory['семя_зерна']}</b>\n"
        f"• `{FARM_ITEM_NAMES['семя_хмеля']}`: <b>{inventory['семя_хмеля']}</b>\n"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад на Ферму", callback_data=FarmCallback(action="main_dashboard", owner_id=user_id).pack())]
    ])
    
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()

@farm_router.callback_query(PlotCallback.filter(F.action == "plant_menu"))
async def cq_plot_plant_menu(callback: CallbackQuery, callback_data: PlotCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id): return
    
    user_id = callback.from_user.id
    plot_num = callback_data.plot_num
    
    inventory = await db.get_user_inventory(user_id)
    
    text = f"<b>Что сажаем на [Участок {plot_num}]?</b>\n\n"
    text += "<i>(У тебя на складе:)\n"
    text += f"• {FARM_ITEM_NAMES['семя_зерна']}: {inventory['семя_зерна']} шт.\n"
    text += f"• {FARM_ITEM_NAMES['семя_хмеля']}: {inventory['семя_хмеля']} шт.</i>"
    
    buttons = []
    
    if inventory['семя_зерна'] > 0:
        time_m = PLANT_IO['семя_зерна'][1]
        buttons.append(InlineKeyboardButton(
            text=f"Посадить 🌾 Зерно ({time_m} мин)", 
            callback_data=PlotCallback(action="plant_do", owner_id=user_id, plot_num=plot_num, crop_id="семя_зерна").pack()
        ))
    
    if inventory['семя_хмеля'] > 0:
        time_m = PLANT_IO['семя_хмеля'][1]
        buttons.append(InlineKeyboardButton(
            text=f"Посадить 🌱 Хмель ({time_m} мин)", 
            callback_data=PlotCallback(action="plant_do", owner_id=user_id, plot_num=plot_num, crop_id="семя_хмеля").pack()
        ))
    
    if inventory['семя_зерна'] == 0 and inventory['семя_хмеля'] == 0:
        text += "\n\n⛔ <b>У тебя нет семян!</b>\nСначала купи их в Магазине (/shop)."
        buttons.append(InlineKeyboardButton(
            text="[🏪 Магазин (Быстрый доступ)]", 
            callback_data=FarmCallback(action="shop", owner_id=user_id).pack()
        ))

    keyboard_rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    
    # --- ✅ ИЗМЕНЕНО: Кнопка "Назад" ведет в "Моё Поле" ---
    keyboard_rows.append([
        InlineKeyboardButton(text="⬅️ Назад в [Моё Поле]", callback_data=FarmCallback(action="field_dashboard", owner_id=user_id).pack())
    ])
    
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_rows))
    await callback.answer()

@farm_router.callback_query(PlotCallback.filter(F.action == "plant_do"))
async def cq_plot_plant_do(callback: CallbackQuery, callback_data: PlotCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id): return

    user_id = callback.from_user.id
    plot_num = callback_data.plot_num
    crop_id = callback_data.crop_id

    if crop_id not in PLANT_IO:
        await callback.answer("⛔ Ошибка! Неизвестный тип семян.", show_alert=True)
        return

    success = await db.modify_inventory(user_id, crop_id, -1)
    
    if not success:
        await callback.answer(f"⛔ Ошибка! У тебя закончились '{FARM_ITEM_NAMES[crop_id]}'.", show_alert=True)
        # (Обновляем меню Посадки)
        await cq_plot_plant_menu(callback, PlotCallback(action="plant_menu", owner_id=user_id, plot_num=plot_num), db)
        return

    time_m = PLANT_IO[crop_id][1]
    ready_time = datetime.now() + timedelta(minutes=time_m)
    
    planted = await db.plant_crop(user_id, plot_num, crop_id, ready_time)
    
    if not planted:
        logging.error(f"Ошибка посадки: участок {plot_num} (user {user_id}) уже был занят.")
        await db.modify_inventory(user_id, crop_id, 1) # (Возвращаем семя)
        await callback.answer("⛔ Ошибка! Этот участок уже занят. Попробуй обновить /farm.", show_alert=True)
        return

    await callback.answer(f"✅ Участок {plot_num} засажен! (Готово через {time_m} мин)")
    
    # --- ✅ ИЗМЕНЕНО: Возвращаемся в "Моё Поле" ---
    await cq_farm_field_dashboard(callback, FarmCallback(action="field_dashboard", owner_id=user_id), db)

@farm_router.callback_query(PlotCallback.filter(F.action == "harvest"))
async def cq_plot_harvest(callback: CallbackQuery, callback_data: PlotCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id): return
    
    user_id = callback.from_user.id
    plot_num = callback_data.plot_num

    crop_id_seed = await db.harvest_plot(user_id, plot_num)
    
    if not crop_id_seed:
        await callback.answer("⛔ Ошибка! Этот участок уже пуст.", show_alert=True)
        return
        
    crop_id_product = PLANT_IO[crop_id_seed][0]
    product_name = FARM_ITEM_NAMES[crop_id_product]
    
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
    
    # --- ✅ ИЗМЕНЕНО: Возвращаемся в "Моё Поле" ---
    await cq_farm_field_dashboard(callback, FarmCallback(action="field_dashboard", owner_id=user_id), db)

@farm_router.callback_query(BreweryCallback.filter(F.action == "brew_menu"))
async def cq_brewery_menu(callback: CallbackQuery, callback_data: BreweryCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id): return
    
    user_id = callback.from_user.id
    
    farm_data = await db.get_user_farm_data(user_id)
    inventory = await db.get_user_inventory(user_id)
    
    brewery_lvl = farm_data.get('brewery_level', 1)
    brewery_stats = get_level_data(brewery_lvl, BREWERY_UPGRADES)
    
    recipe_grain = BREWERY_RECIPE['зерно']
    recipe_hops = BREWERY_RECIPE['хмель']
    
    max_by_grain = 999
    if recipe_grain > 0 and inventory['зерно'] > 0:
        max_by_grain = floor(inventory['зерно'] / recipe_grain)
    elif recipe_grain > 0:
        max_by_grain = 0
        
    max_by_hops = 999
    if recipe_hops > 0 and inventory['хмель'] > 0:
        max_by_hops = floor(inventory['хмель'] / recipe_hops)
    elif recipe_hops > 0:
        max_by_hops = 0
        
    max_brew = min(max_by_grain, max_by_hops)
    
    text = (
        f"<b>🏭 Пивоварня (Ур. {brewery_lvl})</b>\n"
        f"<i>Здесь ты варишь пиво из собранных ресурсов, чтобы поднять свой Рейтинг 🍺.</i>\n\n"
        f"<b><u>Рецепт (1 Варка):</u></b>\n"
        f"• {recipe_grain} x {FARM_ITEM_NAMES['зерно']}\n"
        f"• {recipe_hops} x {FARM_ITEM_NAMES['хмель']}\n"
        f"<i>(Награда: +{brewery_stats['reward']} 🍺, Время: {brewery_stats['brew_time_min']} мин)</i>\n\n"
        f"<b><u>У тебя на складе:</u></b>\n"
        f"• {FARM_ITEM_NAMES['зерно']}: <b>{inventory['зерно']}</b> (Нужно: {recipe_grain})\n"
        f"• {FARM_ITEM_NAMES['хмель']}: <b>{inventory['хмель']}</b> (Нужно: {recipe_hops})\n"
    )

    buttons = []
    if max_brew > 0:
        text += f"\nТы можешь сварить <b>{max_brew}</b> порций."
        buttons.append(InlineKeyboardButton(
            text=f"Сварить Пиво (Макс: {max_brew})", 
            callback_data=BreweryCallback(action="brew_start", owner_id=user_id, quantity=max_brew).pack()
        ))
    else:
        text += "\n⛔ <b>Недостаточно ресурсов</b> для варки."

    keyboard_rows = [buttons]
    keyboard_rows.append([
        InlineKeyboardButton(text="⬅️ Назад на Ферму", callback_data=FarmCallback(action="main_dashboard", owner_id=user_id).pack())
    ])
    
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_rows))
    await callback.answer()

@farm_router.callback_query(BreweryCallback.filter(F.action == "brew_start"))
async def cq_brewery_start(callback: CallbackQuery, callback_data: BreweryCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id): return
    
    user_id = callback.from_user.id
    max_brew = callback_data.quantity
    
    farm_data = await db.get_user_farm_data(user_id)
    brewery_lvl = farm_data.get('brewery_level', 1)
    brewery_stats = get_level_data(brewery_lvl, BREWERY_UPGRADES)
    brew_time_min = brewery_stats['brew_time_min']

    text = (
        f"<b>Выбор Варки (Макс: {max_brew} порций)</b>\n"
        f"<i>1 Варка = {brew_time_min} минут</i>\n\n"
        f"<b>Сколько ты хочешь сварить?</b>"
    )
    
    buttons = []
    if max_brew >= 1:
        total_time_1 = timedelta(minutes=brew_time_min * 1)
        buttons.append(InlineKeyboardButton(
            text=f"Сварить 1 ({format_time_delta(total_time_1)})", 
            callback_data=BreweryCallback(action="brew_do", owner_id=user_id, quantity=1).pack()
        ))
        
    if max_brew >= 5:
        total_time_5 = timedelta(minutes=brew_time_min * 5)
        buttons.append(InlineKeyboardButton(
            text=f"Сварить 5 ({format_time_delta(total_time_5)})", 
            callback_data=BreweryCallback(action="brew_do", owner_id=user_id, quantity=5).pack()
        ))
        
    if max_brew >= 10:
        total_time_10 = timedelta(minutes=brew_time_min * 10)
        buttons.append(InlineKeyboardButton(
            text=f"Сварить 10 ({format_time_delta(total_time_10)})", 
            callback_data=BreweryCallback(action="brew_do", owner_id=user_id, quantity=10).pack()
        ))
    
    if max_brew > 0 and max_brew not in [1, 5, 10]:
        total_time_max = timedelta(minutes=brew_time_min * max_brew)
        buttons.append(InlineKeyboardButton(
            text=f"Сварить MAX ({max_brew}) ({format_time_delta(total_time_max)})", 
            callback_data=BreweryCallback(action="brew_do", owner_id=user_id, quantity=max_brew).pack()
        ))

    keyboard_rows = [buttons[i:i + 3] for i in range(0, len(buttons), 3)]
    keyboard_rows.append([
        InlineKeyboardButton(text="⬅️ Назад в Пивоварню", callback_data=BreweryCallback(action="brew_menu", owner_id=user_id).pack())
    ])

    with suppress(TelegramBadRequest):
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_rows))
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

    await db.modify_inventory(user_id, 'зерно', -cost_grain)
    await db.modify_inventory(user_id, 'хмель', -cost_hops)
    
    farm_data = await db.get_user_farm_data(user_id)
    brewery_lvl = farm_data.get('brewery_level', 1)
    brewery_stats = get_level_data(brewery_lvl, BREWERY_UPGRADES)
    brew_time_min = brewery_stats['brew_time_min']
    
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
    
    text += f"<b>🌾 Поле (Ур. {field_lvl})</b>\n"
    text += f"• <i>Дает: {field_stats['plots']} Участка</i>\n"
    text += f"• <i>Дает: {field_stats['chance_x2']}% Шанс x2 Урожая</i>\n"

    if field_upgrade_timer and now < field_upgrade_timer:
        time_left = format_time_delta(field_upgrade_timer - now)
        buttons.append([InlineKeyboardButton(text=f"Поле (Строится... ⏳ {time_left})", callback_data="dummy")])
    
    elif field_stats['max_level']:
        buttons.append([InlineKeyboardButton(text="✅ Поле (Макс. Уровень 10)", callback_data="dummy")])
        
    else:
        next_field_stats = get_level_data(field_lvl + 1, FIELD_UPGRADES)
        cost = next_field_stats['cost']
        time_h = next_field_stats['time_h']
        
        bonus_plot = ""
        if next_field_stats['plots'] > field_stats['plots']:
             bonus_plot = f" (Даст {next_field_stats['plots']} Участка)"
        
        bonus_chance = ""
        if next_field_stats['chance_x2'] > field_stats['chance_x2']:
             bonus_chance = f" (Даст {next_field_stats['chance_x2']}% Шанс x2)"
             
        btn_text = f"Улучшить до Ур. {field_lvl + 1}{bonus_plot}{bonus_chance}"
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

    buttons.append([
        InlineKeyboardButton(text="⬅️ Назад на Ферму", callback_data=FarmCallback(action="main_dashboard", owner_id=user_id).pack())
    ])
    
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
    
    if (building == 'field' and farm_data.get('field_upgrade_timer_end')) or \
       (building == 'brewery' and farm_data.get('brewery_upgrade_timer_end')):
        await callback.answer(f"⛔ Ошибка! Здание уже прокачивается!", show_alert=True)
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
