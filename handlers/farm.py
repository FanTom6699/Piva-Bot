# handlers/farm.py
import asyncio
import logging
from datetime import datetime, timedelta
from aiogram import Router, Bot, F, html
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command, StateFilter
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest
from contextlib import suppress

from database import Database
from settings import SettingsManager
from utils import format_time_delta, format_time_left

# --- ✅ НОВЫЕ ИМПОРТЫ ---
from .farm_config import (
    FARM_ITEM_NAMES, CROP_SHORT, SEED_TO_PRODUCT_ID, PRODUCT_TO_SEED_ID,
    CROP_CODE_TO_ID, FIELD_UPGRADES, BREWERY_UPGRADES,
    BREWERY_RECIPE, SHOP_PRICES, get_level_data,
    FARM_ORDER_POOL # (Для Доски Заказов)
)
from .common import check_user_registered

# --- ИНИЦИАЛИЗАЦИЯ ---
farm_router = Router()

# (Ограничиваем роутер только ЛС)
@farm_router.message(F.chat.type != "private")
@farm_router.callback_query(F.message.chat.type != "private")
async def block_farm_in_groups(message: Message | CallbackQuery):
    if isinstance(message, Message):
        await message.reply(
            "🚜 Ферма доступна только в Личных Сообщениях, чтобы не спамить в чате.\n"
            "Напиши мне в ЛС: /farm"
        )
    else:
        await message.answer("Ферма доступна только в ЛС (напиши /farm боту).", show_alert=True)
    return

# --- FSM (для Магазина) ---
class FarmStates(StatesGroup):
    shop_buy_amount = State() # (Ждем кол-во для покупки)

# --- ✅✅✅ ИЗМЕНЕНИЕ (FarmCallback) ✅✅✅ ---
class FarmCallback(CallbackData, prefix="farm"):
    action: str # (main_dashboard, field, brewery, shop, storage)
    
    # (Для Поля)
    plot_num: int = 0  # (Номер участка)
    crop_code: str = "" # (Код "g" или "h")
    
    # (Для Магазина)
    item_id: str = "" # (ID семени для покупки)
    
    # (Для Пивоварни)
    brew_amount: int = 0 # (Сколько варить)
    
    # (Для Апгрейдов)
    upgrade_b: str = "" # (Building: 'field' or 'brewery')
    
    # (Для Доски Заказов)
    order_id: str = ""  # (ID заказа из FARM_ORDER_POOL)
    slot_id: int = 0    # (Слот 1, 2 или 3)
    
    # (Для Владельца)
    owner_id: int = 0 # (Чтобы кнопка 'Открыть ферму' из ЛС работала)
# --- ---

# --- (Вспомогательная функция) ---
async def check_owner(callback: CallbackQuery, callback_data: FarmCallback) -> bool:
    """(Fix) Проверяет, что /farm нажимает владелец меню, а не кто-то другой."""
    if callback_data.owner_id != callback.from_user.id:
        await callback.answer("Это не твоя ферма!", show_alert=True)
        return False
    return True

# --- 1. ГЛАВНОЕ МЕНЮ (/farm) ---
@farm_router.message(Command("farm"))
async def cmd_farm_start(message: Message, bot: Bot, db: Database):
    if not await check_user_registered(message, bot, db):
        return
    
    user_id = message.from_user.id
    
    # (Отправляем главное меню)
    text, keyboard = await get_farm_dashboard_content(user_id, db)
    await message.answer(text, reply_markup=keyboard)

# (Callback для кнопки "Открыть ферму" из Уведомлений)
@farm_router.callback_query(FarmCallback.filter(F.action == "main_dashboard"))
async def cq_farm_main_dashboard_from_notify(callback: CallbackQuery, bot: Bot, db: Database, callback_data: FarmCallback):
    if not await check_owner(callback, callback_data):
        return
        
    user_id = callback.from_user.id
    text, keyboard = await get_farm_dashboard_content(user_id, db)
    
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()

async def get_farm_dashboard_content(user_id: int, db: Database) -> (str, InlineKeyboardMarkup):
    """(Логика) Собирает текст и кнопки для /farm."""
    
    farm_data = await db.get_user_farm_data(user_id)
    
    # (Таймеры)
    field_timer_end = farm_data.get('field_upgrade_timer_end')
    brewery_timer_end = farm_data.get('brewery_upgrade_timer_end')
    
    # (Текст)
    text = "🚜 <b>Твоя Ферма</b>\n\n"
    text += "Здесь ты можешь выращивать 🌾 и 🌱, чтобы варить 🍺 и повышать свой рейтинг.\n"
    
    # --- ✅✅✅ ИЗМЕНЕНИЕ (Кнопки) ✅✅✅ ---
    buttons = [
        # (Кнопка Поля)
        [InlineKeyboardButton(
            text=f"🌾 Поле (Ур. {farm_data['field_level']})" + (" ⏳" if field_timer_end else ""),
            callback_data=FarmCallback(action="field", owner_id=user_id).pack()
        )],
        # (Кнопка Пивоварни)
        [InlineKeyboardButton(
            text=f"🏭 Пивоварня (Ур. {farm_data['brewery_level']})" + (" ⏳" if brewery_timer_end else ""),
            callback_data=FarmCallback(action="brewery", owner_id=user_id).pack()
        )],
        # (Кнопка Доски Заказов)
        [InlineKeyboardButton(
            text="📋 Доска Заказов",
            callback_data=FarmCallback(action="orders_menu", owner_id=user_id).pack()
        )],
        # (Нижний ряд)
        [
            InlineKeyboardButton(text="🏪 Магазин", callback_data=FarmCallback(action="shop", owner_id=user_id).pack()),
            InlineKeyboardButton(text="📦 Склад", callback_data=FarmCallback(action="storage", owner_id=user_id).pack())
        ]
    ]
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    return text, keyboard
# --- ---

# --- 2. СКЛАД [📦 Склад] ---
@farm_router.callback_query(FarmCallback.filter(F.action == "storage"))
async def cq_farm_storage(callback: CallbackQuery, db: Database, callback_data: FarmCallback):
    if not await check_owner(callback, callback_data):
        return
        
    inventory = await db.get_user_inventory(callback.from_user.id)
    
    text = "<b>📦 Склад</b>\n\nЗдесь хранятся твои ресурсы:\n\n"
    
    for item_id, name in FARM_ITEM_NAMES.items():
        text += f"• {name}: <b>{inventory.get(item_id, 0)}</b> шт.\n"
        
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="⬅️ Назад", callback_data=FarmCallback(action="main_dashboard", owner_id=callback.from_user.id).pack())
    ]])
    
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()
# --- ---

# --- 3. ПОЛЕ [🌾 Поле] ---
@farm_router.callback_query(FarmCallback.filter(F.action == "field"))
async def cq_farm_field(callback: CallbackQuery, db: Database, callback_data: FarmCallback):
    if not await check_owner(callback, callback_data):
        return
        
    user_id = callback.from_user.id
    text, keyboard = await get_field_content(user_id, db)
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()

async def get_field_content(user_id: int, db: Database) -> (str, InlineKeyboardMarkup):
    """(Логика) Собирает текст и кнопки для [🌾 Поля]."""
    
    farm_data = await db.get_user_farm_data(user_id)
    level = farm_data['field_level']
    level_data = get_level_data(level, FIELD_UPGRADES)
    
    upgrade_timer_end = farm_data.get('field_upgrade_timer_end')
    
    text = f"<b>🌾 Поле (Ур. {level})</b>\n\n"
    
    if upgrade_timer_end:
        time_left = format_time_left(upgrade_timer_end)
        text += f"⏳ Идет улучшение до Ур. {level + 1}!\n"
        text += f"Осталось: <b>{time_left}</b>"
    
    else:
        text += f"Доступно участков: <b>{level_data['plots']}</b>\n"
        text += f"Шанс x2 урожая: <b>{level_data['chance_x2']}%</b>\n\n"
        
    buttons = []
    
    # (Получаем инфу о грядках)
    plots = await db.get_user_plots(user_id)
    plots_dict = {row[0]: (row[1], row[2]) for row in plots} # {plot_num: (crop_id, ready_time)}
    
    # (Создаем кнопки грядок)
    plot_buttons = []
    for i in range(1, level_data['plots'] + 1):
        plot_text = f"[{i}] "
        
        if i in plots_dict:
            crop_id, ready_time_iso = plots_dict[i]
            ready_time = datetime.fromisoformat(ready_time_iso)
            crop_name = CROP_SHORT.get(crop_id, "???")
            
            if datetime.now() >= ready_time:
                plot_text += f"✅ {crop_name}"
                # (Кнопка Сбора)
                plot_buttons.append(InlineKeyboardButton(
                    text=plot_text,
                    callback_data=FarmCallback(action="harvest", owner_id=user_id, plot_num=i).pack()
                ))
            else:
                time_left = format_time_left(ready_time)
                plot_text += f"⏳ {time_left}"
                # (Кнопка таймера)
                plot_buttons.append(InlineKeyboardButton(
                    text=plot_text,
                    callback_data=FarmCallback(action="plot_timer", owner_id=user_id).pack()
                ))
        
        else:
            plot_text += "🌱 Пусто"
            # (Кнопка Посадки)
            plot_buttons.append(InlineKeyboardButton(
                text=plot_text,
                callback_data=FarmCallback(action="plant_select", owner_id=user_id, plot_num=i).pack()
            ))
            
    # (Делим кнопки по 3 в ряд)
    while plot_buttons:
        buttons.append(plot_buttons[:3])
        plot_buttons = plot_buttons[3:]
    
    # (Кнопка Апгрейда)
    if not upgrade_timer_end:
        buttons.append([InlineKeyboardButton(
            text="⬆️ Улучшить",
            callback_data=FarmCallback(action="upgrade_b", owner_id=user_id, upgrade_b="field").pack()
        )])
        
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=FarmCallback(action="main_dashboard", owner_id=user_id).pack())])
    
    return text, InlineKeyboardMarkup(inline_keyboard=buttons)

# (Нажатие на "Пусто")
@farm_router.callback_query(FarmCallback.filter(F.action == "plant_select"))
async def cq_plant_select(callback: CallbackQuery, db: Database, callback_data: FarmCallback):
    if not await check_owner(callback, callback_data):
        return
        
    plot_num = callback_data.plot_num
    user_id = callback.from_user.id
    inventory = await db.get_user_inventory(user_id)
    
    text = f"<b>Посадка (Участок [{plot_num}])</b>\n\n"
    text += "Что ты хочешь посадить?\n\n"
    text += f"<i>На складе:</i>\n"
    
    buttons = []
    # (Показываем только Семена)
    for crop_code, seed_id in CROP_CODE_TO_ID.items():
        seed_name = FARM_ITEM_NAMES.get(seed_id, "Семена")
        seed_count = inventory.get(seed_id, 0)
        
        text += f"• {seed_name}: <b>{seed_count}</b> шт.\n"
        
        # (Кнопка посадки)
        if seed_count > 0:
            buttons.append(InlineKeyboardButton(
                text=f"🌱 {seed_name}",
                callback_data=FarmCallback(action="plant", owner_id=user_id, plot_num=plot_num, crop_code=crop_code).pack()
            ))
            
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        buttons,
        [InlineKeyboardButton(text="⬅️ Назад (Поле)", callback_data=FarmCallback(action="field", owner_id=user_id).pack())]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()

# (Нажатие на "Семена...")
@farm_router.callback_query(FarmCallback.filter(F.action == "plant"))
async def cq_plant_crop(callback: CallbackQuery, db: Database, callback_data: FarmCallback):
    if not await check_owner(callback, callback_data):
        return
    
    user_id = callback.from_user.id
    plot_num = callback_data.plot_num
    seed_id = CROP_CODE_TO_ID.get(callback_data.crop_code)
    
    if not seed_id:
        await callback.answer("Ошибка: Неизвестный код семян.", show_alert=True)
        return

    # (Проверка баланса семян)
    success = await db.modify_inventory(user_id, seed_id, -1)
    if not success:
        await callback.answer(f"У тебя закончились {FARM_ITEM_NAMES[seed_id]}!", show_alert=True)
        return

    # (Получаем время роста)
    farm_data = await db.get_user_farm_data(user_id)
    level_data = get_level_data(farm_data['field_level'], FIELD_UPGRADES)
    crop_id = SEED_TO_PRODUCT_ID[seed_id]
    grow_time_min = level_data['grow_time_min'][crop_id]
    
    ready_time = datetime.now() + timedelta(minutes=grow_time_min)
    
    # (Сажаем в БД)
    success = await db.plant_crop(user_id, plot_num, crop_id, ready_time)
    if not success:
        await callback.answer("Ошибка! Участок уже занят.", show_alert=True)
        # (Возвращаем семя, если не вышло)
        await db.modify_inventory(user_id, seed_id, 1)
        return
        
    await callback.answer(f"Ты посадил {CROP_SHORT[crop_id]} на участке [{plot_num}]!")
    
    # (Обновляем меню Поля)
    text, keyboard = await get_field_content(user_id, db)
    await callback.message.edit_text(text, reply_markup=keyboard)

# (Нажатие на "✅ Сбор")
@farm_router.callback_query(FarmCallback.filter(F.action == "harvest"))
async def cq_harvest_plot(callback: CallbackQuery, db: Database, callback_data: FarmCallback):
    if not await check_owner(callback, callback_data):
        return
        
    user_id = callback.from_user.id
    plot_num = callback_data.plot_num
    
    # (Собираем из БД)
    crop_id = await db.harvest_plot(user_id, plot_num)
    
    if not crop_id:
        await callback.answer("Ошибка! Этот участок пуст или еще не готов.", show_alert=True)
        return

    # (Проверяем шанс x2)
    farm_data = await db.get_user_farm_data(user_id)
    level_data = get_level_data(farm_data['field_level'], FIELD_UPGRADES)
    
    amount = 1
    if random.randint(1, 100) <= level_data['chance_x2']:
        amount = 2
        
    # (Начисляем в инвентарь)
    await db.modify_inventory(user_id, crop_id, amount)
    
    if amount > 1:
        await callback.answer(f"🎉 УДАЧА! (x2) 🎉\nТы собрал {amount}x {CROP_SHORT[crop_id]} с участка [{plot_num}]!", show_alert=True)
    else:
        await callback.answer(f"Ты собрал {amount}x {CROP_SHORT[crop_id]} с участка [{plot_num}]!")

    # (Обновляем меню Поля)
    text, keyboard = await get_field_content(user_id, db)
    await callback.message.edit_text(text, reply_markup=keyboard)

# (Нажатие на "⏳ Таймер")
@farm_router.callback_query(FarmCallback.filter(F.action == "plot_timer"))
async def cq_plot_timer(callback: CallbackQuery, callback_data: FarmCallback):
    if not await check_owner(callback, callback_data):
        return
    await callback.answer("⏳ Участок занят, семя еще растет...")
# --- ---

# --- 4. ПИВОВАРНЯ [🏭 Пивоварня] ---
@farm_router.callback_query(FarmCallback.filter(F.action == "brewery"))
async def cq_farm_brewery(callback: CallbackQuery, db: Database, callback_data: FarmCallback):
    if not await check_owner(callback, callback_data):
        return
        
    user_id = callback.from_user.id
    text, keyboard = await get_brewery_content(user_id, db)
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()

async def get_brewery_content(user_id: int, db: Database) -> (str, InlineKeyboardMarkup):
    """(Логика) Собирает текст и кнопки для [🏭 Пивоварни]."""
    
    farm_data = await db.get_user_farm_data(user_id)
    level = farm_data['brewery_level']
    level_data = get_level_data(level, BREWERY_UPGRADES)
    
    upgrade_timer_end = farm_data.get('brewery_upgrade_timer_end')
    batch_timer_end = farm_data.get('brewery_batch_timer_end')
    batch_size = farm_data['brewery_batch_size']
    
    text = f"<b>🏭 Пивоварня (Ур. {level})</b>\n\n"
    
    buttons = []
    
    if upgrade_timer_end:
        time_left = format_time_left(upgrade_timer_end)
        text += f"⏳ Идет улучшение до Ур. {level + 1}!\n"
        text += f"Осталось: <b>{time_left}</b>"
        
    elif batch_timer_end:
        time_left = format_time_left(batch_timer_end)
        text += f"⏳ Идет варка (x{batch_size})!\n"
        text += f"Награда: <b>{level_data['reward'] * batch_size}</b> 🍺\n"
        text += f"Осталось: <b>{time_left}</b>\n"
        
        if datetime.now() >= batch_timer_end:
            # (Кнопка Сбора)
            buttons.append([InlineKeyboardButton(
                text=f"✅ Собрать (x{batch_size})",
                callback_data=FarmCallback(action="brew_collect", owner_id=user_id).pack()
            )])
        else:
            # (Кнопка Таймера)
            buttons.append([InlineKeyboardButton(
                text=f"⏳ {time_left}",
                callback_data=FarmCallback(action="brew_timer", owner_id=user_id).pack()
            )])
    
    else:
        # (Пивоварня свободна)
        text += f"Награда за 1 варку: <b>{level_data['reward']}</b> 🍺\n"
        text += f"Время 1 варки: <b>{level_data['brew_time_min']}</b> мин.\n\n"
        
        # (Рецепт)
        text += "<i>Рецепт (на 1 варку):</i>\n"
        inventory = await db.get_user_inventory(user_id)
        can_brew_count = 999
        
        for item_id, amount in BREWERY_RECIPE.items():
            name = FARM_ITEM_NAMES.get(item_id, "???")
            in_stock = inventory.get(item_id, 0)
            text += f"• {name}: {amount} шт. (<i>На складе: {in_stock}</i>)\n"
            
            # (Считаем, сколько можем сварить)
            can_brew_count = min(can_brew_count, in_stock // amount)
        
        if can_brew_count > 0:
            text += f"\nТы можешь сварить: <b>{can_brew_count}</b> раз."
            # (Кнопки Варки)
            brew_buttons = []
            if can_brew_count >= 1:
                brew_buttons.append(InlineKeyboardButton(
                    text="Варить (x1)",
                    callback_data=FarmCallback(action="brew_start", owner_id=user_id, brew_amount=1).pack()
                ))
            if can_brew_count >= 5:
                brew_buttons.append(InlineKeyboardButton(
                    text="Варить (x5)",
                    callback_data=FarmCallback(action="brew_start", owner_id=user_id, brew_amount=5).pack()
                ))
            if can_brew_count >= 10:
                brew_buttons.append(InlineKeyboardButton(
                    text=f"Варить (x{can_brew_count})",
                    callback_data=FarmCallback(action="brew_start", owner_id=user_id, brew_amount=can_brew_count).pack()
                ))
            buttons.append(brew_buttons)
        else:
            text += "\n<i>Не хватает ресурсов для варки.</i>"
            
        # (Кнопка Апгрейда)
        buttons.append([InlineKeyboardButton(
            text="⬆️ Улучшить",
            callback_data=FarmCallback(action="upgrade_b", owner_id=user_id, upgrade_b="brewery").pack()
        )])
        
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=FarmCallback(action="main_dashboard", owner_id=user_id).pack())])
    
    return text, InlineKeyboardMarkup(inline_keyboard=buttons)

# (Нажатие на "Варить (xN)")
@farm_router.callback_query(FarmCallback.filter(F.action == "brew_start"))
async def cq_start_brewing(callback: CallbackQuery, db: Database, callback_data: FarmCallback):
    if not await check_owner(callback, callback_data):
        return
        
    user_id = callback.from_user.id
    amount_to_brew = callback_data.brew_amount
    
    if amount_to_brew <= 0:
        return await callback.answer("Ошибка!", show_alert=True)
        
    # (Проверяем таймеры)
    farm_data = await db.get_user_farm_data(user_id)
    if farm_data.get('brewery_upgrade_timer_end') or farm_data.get('brewery_batch_timer_end'):
        await callback.answer("Пивоварня сейчас занята!", show_alert=True)
        return
        
    inventory = await db.get_user_inventory(user_id)
    
    # (Проверяем ресурсы)
    items_to_spend = []
    for item_id, amount_needed in BREWERY_RECIPE.items():
        total_needed = amount_needed * amount_to_brew
        if inventory.get(item_id, 0) < total_needed:
            await callback.answer(f"Не хватает {FARM_ITEM_NAMES[item_id]}!", show_alert=True)
            return
        items_to_spend.append((item_id, total_needed))
        
    # (Списываем ресурсы)
    for item_id, total_needed in items_to_spend:
        await db.modify_inventory(user_id, item_id, -total_needed)
        
    # (Запускаем таймер)
    level_data = get_level_data(farm_data['brewery_level'], BREWERY_UPGRADES)
    brew_time_min = level_data['brew_time_min']
    end_time = datetime.now() + timedelta(minutes=brew_time_min)
    
    await db.start_brewing(user_id, amount_to_brew, end_time)
    
    await callback.answer(f"Запущена варка (x{amount_to_brew})!")
    
    # (Обновляем меню Пивоварни)
    text, keyboard = await get_brewery_content(user_id, db)
    await callback.message.edit_text(text, reply_markup=keyboard)

# (Нажатие на "✅ Собрать")
@farm_router.callback_query(FarmCallback.filter(F.action == "brew_collect"))
async def cq_collect_brewery(callback: CallbackQuery, db: Database, callback_data: FarmCallback):
    if not await check_owner(callback, callback_data):
        return
        
    user_id = callback.from_user.id
    
    # (Проверяем таймеры)
    farm_data = await db.get_user_farm_data(user_id)
    batch_timer_end = farm_data.get('brewery_batch_timer_end')
    batch_size = farm_data['brewery_batch_size']
    
    if not batch_timer_end or not batch_size:
        await callback.answer("Нечего собирать!", show_alert=True)
        return
        
    if datetime.now() < batch_timer_end:
        await callback.answer("Варка еще не готова!", show_alert=True)
        return

    # (Получаем награду)
    level_data = get_level_data(farm_data['brewery_level'], BREWERY_UPGRADES)
    reward_per_batch = level_data['reward']
    total_reward = reward_per_batch * batch_size
    
    # (Забираем в БД)
    await db.collect_brewery(user_id, total_reward)
    
    await callback.answer(f"🍻 Ты собрал {total_reward} 🍺 рейтинга!", show_alert=True)
    
    # (Обновляем меню Пивоварни)
    text, keyboard = await get_brewery_content(user_id, db)
    await callback.message.edit_text(text, reply_markup=keyboard)

# (Нажатие на "⏳ Таймер")
@farm_router.callback_query(FarmCallback.filter(F.action == "brew_timer"))
async def cq_brew_timer(callback: CallbackQuery, callback_data: FarmCallback):
    if not await check_owner(callback, callback_data):
        return
    await callback.answer("⏳ Пивоварня занята, идет варка...")
# --- ---

# --- 5. МАГАЗИН [🏪 Магазин] ---
@farm_router.callback_query(FarmCallback.filter(F.action == "shop"))
async def cq_farm_shop(callback: CallbackQuery, db: Database, callback_data: FarmCallback):
    if not await check_owner(callback, callback_data):
        return
        
    user_id = callback.from_user.id
    text, keyboard = await get_shop_content(user_id, db)
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()

async def get_shop_content(user_id: int, db: Database) -> (str, InlineKeyboardMarkup):
    """(Логика) Собирает текст и кнопки для [🏪 Магазина]."""
    
    balance = await db.get_user_beer_rating(user_id)
    
    text = (
        f"<b>🏪 Магазин Сеян</b>\n\n"
        f"Здесь можно купить семена для [🌾 Поля].\n\n"
        f"Твой баланс: <b>{balance}</b> 🍺\n\n"
        f"<i>Товары:</i>\n"
    )
    
    buttons = []
    
    for seed_id, price in SHOP_PRICES.items():
        name = FARM_ITEM_NAMES.get(seed_id, "???")
        text += f"• {name} — <b>{price}</b> 🍺\n"
        
        # (Кнопка Купить)
        if balance >= price:
            buttons.append(InlineKeyboardButton(
                text=f"Купить {name} (x1)",
                callback_data=FarmCallback(action="shop_buy", owner_id=user_id, item_id=seed_id).pack()
            ))
            
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        buttons,
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=FarmCallback(action="main_dashboard", owner_id=user_id).pack())]
    ])
    
    return text, keyboard

# (Нажатие на "Купить...")
@farm_router.callback_query(FarmCallback.filter(F.action == "shop_buy"))
async def cq_shop_buy_select(callback: CallbackQuery, state: FSMContext, callback_data: FarmCallback):
    """(FSM) Спрашивает, сколько покупать."""
    if not await check_owner(callback, callback_data):
        return
        
    item_id = callback_data.item_id
    price = SHOP_PRICES.get(item_id)
    
    if not price:
        await callback.answer("Товар не найден!", show_alert=True)
        return
        
    await state.set_state(FarmStates.shop_buy_amount)
    await state.update_data(item_id=item_id, price=price, item_name=FARM_ITEM_NAMES[item_id])
    
    await callback.message.edit_text(
        f"<b>Покупка: {FARM_ITEM_NAMES[item_id]}</b>\n"
        f"Цена: {price} 🍺 / шт.\n\n"
        f"➡️ <b>Введи количество</b> (например: <code>5</code> или <code>10</code>)",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="Отмена", callback_data=FarmCallback(action="shop", owner_id=callback.from_user.id).pack())
        ]])
    )
    await callback.answer()

# (Ответ на FSM)
@farm_router.message(StateFilter(FarmStates.shop_buy_amount))
async def state_shop_buy_amount(message: Message, bot: Bot, db: Database, state: FSMContext):
    """(FSM) Обрабатывает введенное кол-во."""
    
    data = await state.get_data()
    item_id = data.get('item_id')
    price = data.get('price')
    item_name = data.get('item_name')
    
    await state.clear()
    
    if not item_id or not price:
        return
        
    try:
        amount = int(message.text)
        if amount <= 0:
            raise ValueError("Кол-во < 0")
    except ValueError:
        await message.reply("Неверный ввод. Введи целое число (например: <code>5</code>).")
        # (Возвращаем в Магазин)
        text, kbd = await get_shop_content(message.from_user.id, db)
        await message.answer(text, reply_markup=kbd)
        return

    total_cost = price * amount
    
    # (Проверяем баланс 🍺)
    balance = await db.get_user_beer_rating(message.from_user.id)
    if balance < total_cost:
        await message.reply(f"Не хватает 🍺! Нужно: {total_cost} 🍺, у тебя: {balance} 🍺.")
        # (Возвращаем в Магазин)
        text, kbd = await get_shop_content(message.from_user.id, db)
        await message.answer(text, reply_markup=kbd)
        return

    # (Транзакция)
    await db.change_rating(message.from_user.id, -total_cost)
    await db.modify_inventory(message.from_user.id, item_id, amount)
    
    await message.reply(f"✅ Ты купил <b>{amount}x {item_name}</b> за <b>{total_cost}</b> 🍺!")
    
    # (Возвращаем в Магазин)
    text, kbd = await get_shop_content(message.from_user.id, db)
    await message.answer(text, reply_markup=kbd)
# --- ---

# --- 6. УЛУЧШЕНИЯ [⬆️ Улучшить] ---
@farm_router.callback_query(FarmCallback.filter(F.action == "upgrade_b"))
async def cq_upgrade_building(callback: CallbackQuery, db: Database, callback_data: FarmCallback):
    if not await check_owner(callback, callback_data):
        return
        
    user_id = callback.from_user.id
    building_code = callback_data.upgrade_b # 'field' or 'brewery'
    
    if building_code == 'field':
        CONFIG = FIELD_UPGRADES
        farm_data = await db.get_user_farm_data(user_id)
        current_level = farm_data['field_level']
        building_name = "🌾 Поле"
        back_action = "field"
    else:
        CONFIG = BREWERY_UPGRADES
        farm_data = await db.get_user_farm_data(user_id)
        current_level = farm_data['brewery_level']
        building_name = "🏭 Пивоварня"
        back_action = "brewery"
        
    level_data = get_level_data(current_level, CONFIG)
    
    if level_data.get('max_level', False):
        await callback.answer(f"У тебя максимальный уровень {building_name}!", show_alert=True)
        return
        
    next_cost = level_data.get('next_cost')
    next_time_h = level_data.get('next_time_h')
    
    balance = await db.get_user_beer_rating(user_id)
    
    text = (
        f"<b>Улучшение: {building_name}</b>\n\n"
        f"Текущий Уровень: <b>{current_level}</b>\n"
        f"Следующий Уровень: <b>{current_level + 1}</b>\n\n"
        f"Цена: <b>{next_cost}</b> 🍺\n"
        f"Время: <b>{next_time_h}</b> ч.\n\n"
        f"Твой баланс: <b>{balance}</b> 🍺"
    )
    
    buttons = []
    
    if balance >= next_cost:
        buttons.append([InlineKeyboardButton(
            text=f"Начать улучшение (Стоимость: {next_cost} 🍺)",
            callback_data=FarmCallback(action="upgrade_confirm", owner_id=user_id, upgrade_b=building_code).pack()
        )])
    else:
        text += "\n\n<i>(Не хватает 🍺 для улучшения)</i>"
        
    buttons.append([InlineKeyboardButton(
        text="⬅️ Назад",
        callback_data=FarmCallback(action=back_action, owner_id=user_id).pack()
    )])
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

# (Нажатие на "Начать улучшение")
@farm_router.callback_query(FarmCallback.filter(F.action == "upgrade_confirm"))
async def cq_upgrade_confirm(callback: CallbackQuery, db: Database, callback_data: FarmCallback):
    if not await check_owner(callback, callback_data):
        return
        
    user_id = callback.from_user.id
    building_code = callback_data.upgrade_b
    
    # (Повторная проверка)
    if building_code == 'field':
        CONFIG = FIELD_UPGRADES
        farm_data = await db.get_user_farm_data(user_id)
        current_level = farm_data['field_level']
        timer_end = farm_data.get('field_upgrade_timer_end')
        back_action = "field"
    else:
        CONFIG = BREWERY_UPGRADES
        farm_data = await db.get_user_farm_data(user_id)
        current_level = farm_data['brewery_level']
        timer_end = farm_data.get('brewery_upgrade_timer_end')
        back_action = "brewery"
        
    if timer_end:
        await callback.answer("Улучшение уже идет!", show_alert=True)
        return
        
    level_data = get_level_data(current_level, CONFIG)
    if level_data.get('max_level', False):
        await callback.answer("У тебя уже максимальный уровень!", show_alert=True)
        return
        
    cost = level_data.get('next_cost')
    time_h = level_data.get('next_time_h')
    
    balance = await db.get_user_beer_rating(user_id)
    if balance < cost:
        await callback.answer("Не хватает 🍺!", show_alert=True)
        return
        
    # (Запускаем апгрейд в БД)
    end_time = datetime.now() + timedelta(hours=time_h)
    await db.start_upgrade(user_id, building_code, end_time, cost)
    
    await callback.answer(f"Улучшение началось! (Завершится через {time_h} ч.)")
    
    # (Возвращаем в меню Поля/Пивоварни)
    if building_code == 'field':
        text, kbd = await get_field_content(user_id, db)
    else:
        text, kbd = await get_brewery_content(user_id, db)
        
    await callback.message.edit_text(text, reply_markup=kbd)
# --- ---

# --- ✅✅✅ НОВЫЙ КОД (7. ДОСКА ЗАКАЗОВ) ✅✅✅ ---

@farm_router.callback_query(FarmCallback.filter(F.action == "orders_menu"))
async def cq_farm_orders_menu(callback: CallbackQuery, db: Database, callback_data: FarmCallback):
    """(Новый) Показывает 3 ежедневных заказа."""
    
    if not await check_owner(callback, callback_data):
        return
        
    user_id = callback.from_user.id
    
    # 1. (Сбрасываем заказы, если 24ч прошли)
    await db.check_and_reset_orders(user_id)
    
    # 2. (Получаем 3 текущих заказа)
    orders = await db.get_user_orders(user_id)
    
    # 3. (Получаем инвентарь для проверки)
    inventory = await db.get_user_inventory(user_id)
    
    text = (
        "<b>📋 Доска Заказов</b>\n\n"
        "Поручения от бармена. Обновляются раз в 24 часа.\n"
    )
    
    buttons = []
    
    if not orders:
        text += "\n<i>(Новые заказы появятся в ближайшее время...)</i>"
        
    for slot_id, order_id, is_completed in orders:
        # (На случай, если мы удалили заказ из конфига, а он остался у юзера)
        if order_id not in FARM_ORDER_POOL:
            continue
            
        order = FARM_ORDER_POOL[order_id]
        
        # (Форматируем награду для кнопки)
        reward_text = ""
        if order['reward_type'] == 'beer':
            reward_text = f"+{order['reward_amount']} 🍺"
        elif order['reward_type'] == 'item':
            reward_name = FARM_ITEM_NAMES.get(order['reward_id'], 'Предмет')
            reward_text = f"+{order['reward_amount']}x {reward_name}"
        
        
        if is_completed:
            text += f"\n✅ <s>{order['text']}</s> (Выполнено)\n"
        
        else:
            # (Проверяем, хватает ли ресурсов)
            has_items = inventory.get(order['item_id'], 0) >= order['item_amount']
            
            if has_items:
                text += f"\n➡️ <b>{order['text']}</b>\n"
                buttons.append([
                    InlineKeyboardButton(
                        text=f"✅ Сдать (Награда: {reward_text})",
                        callback_data=FarmCallback(
                            action="order_complete", 
                            owner_id=user_id,
                            slot_id=slot_id,
                            order_id=order_id # (order_id для проверки)
                        ).pack()
                    )
                ])
            
            else:
                text += f"\n❌ {order['text']} (Не хватает ресурсов)\n"

    # (Кнопка Назад)
    buttons.append([
        InlineKeyboardButton(text="⬅️ Назад", callback_data=FarmCallback(action="main_dashboard", owner_id=user_id).pack())
    ])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()

@farm_router.callback_query(FarmCallback.filter(F.action == "order_complete"))
async def cq_farm_order_complete(callback: CallbackQuery, db: Database, callback_data: FarmCallback):
    """(Новый) Выполняет заказ (списывает и награждает)."""
    
    if not await check_owner(callback, callback_data):
        return
        
    user_id = callback.from_user.id
    slot_id = callback_data.slot_id
    order_id = callback_data.order_id
    
    if order_id not in FARM_ORDER_POOL:
        await callback.answer("Ошибка! Этот заказ устарел.", show_alert=True)
        return
        
    order = FARM_ORDER_POOL[order_id]
    
    # --- (КРИТИЧЕСКАЯ ПРОВЕРКА) ---
    # (Сначала проверяем инвентарь)
    inventory = await db.get_user_inventory(user_id)
    if inventory.get(order['item_id'], 0) < order['item_amount']:
        await callback.answer("Упс! Кажется, у тебя уже не хватает ресурсов.", show_alert=True)
        # (Обновляем меню, чтобы кнопка пропала)
        await cq_farm_orders_menu(callback, db, callback_data)
        return

    # (Помечаем заказ как выполненный. Если False - кто-то нажал дважды)
    success = await db.complete_order(user_id, slot_id)
    if not success:
        await callback.answer("Этот заказ уже выполнен!", show_alert=True)
        return
        
    # --- (ТРАНЗАКЦИЯ) ---
    
    # 1. Списываем ресурсы
    await db.modify_inventory(user_id, order['item_id'], -order['item_amount'])
    
    # 2. Выдаем награду
    reward_text_alert = ""
    if order['reward_type'] == 'beer':
        await db.change_rating(user_id, order['reward_amount'])
        reward_text_alert = f"+{order['reward_amount']} 🍺"
        
    elif order['reward_type'] == 'item':
        await db.modify_inventory(user_id, order['reward_id'], order['reward_amount'])
        reward_name = FARM_ITEM_NAMES.get(order['reward_id'], 'Предмет')
        reward_text_alert = f"+{order['reward_amount']}x {reward_name}"

    await callback.answer(f"Заказ выполнен! Награда: {reward_text_alert}", show_alert=True)
    
    # (Обновляем меню Доски Заказов)
    await cq_farm_orders_menu(callback, db, callback_data)
# --- ---
