# handlers/admin.py
import asyncio
from contextlib import suppress
import logging

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command, Filter, StateFilter
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest

# ИСПРАВЛЕННЫЕ ИМПОРТЫ (добавлены ..)
import config
from database import Database
from settings import SettingsManager
from .game_raid import start_raid_event # Импортируем функцию запуска

# --- ИНИЦИАЛИЗАЦИЯ ---
admin_router = Router()

# --- FSM СОСТОЯНИЯ ---
class AdminStates(StatesGroup):
    broadcast_message = State()
    give_beer_user = State()
    give_beer_amount = State()
    waiting_for_setting_value = State()
    select_raid_chat = State()

# --- ФИЛЬТРЫ ---
class IsAdmin(Filter):
    async def __call__(self, message: Message | CallbackQuery) -> bool:
        return message.from_user.id == config.ADMIN_ID

# --- CALLBACKDATA ФАБРИКИ ---
class AdminCallbackData(CallbackData, prefix="admin"):
    action: str

class AdminSettingsCallbackData(CallbackData, prefix="admin_set"):
    setting_key: str

class AdminRaidCallbackData(CallbackData, prefix="admin_raid"):
    action: str
    chat_id: int = 0
    page: int = 0


# --- Вспомогательные функции для меню ---
async def get_main_admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🍺 Выдать пиво", callback_data=AdminCallbackData(action="give_beer").pack())],
        [InlineKeyboardButton(text="📢 Сделать рассылку", callback_data=AdminCallbackData(action="broadcast").pack())],
        [InlineKeyboardButton(text="📊 Статистика", callback_data=AdminCallbackData(action="stats").pack())],
        [InlineKeyboardButton(text="⚙️ Настройки бота", callback_data=AdminCallbackData(action="settings").pack())],
        [InlineKeyboardButton(text="⚔️ Управление Ивентами", callback_data=AdminCallbackData(action="events").pack())]
    ])

async def get_settings_menu(settings_manager: SettingsManager) -> (str, InlineKeyboardMarkup):
    """Генерирует текст и клавиатуру для меню настроек."""
    text = (
        f"{settings_manager.get_all_settings_text()}\n\n"
        f"<b>Какую настройку вы хотите изменить?</b>"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Кулдаун /beer", callback_data=AdminSettingsCallbackData(setting_key="beer_cooldown").pack())],
        [InlineKeyboardButton(text="Шанс Джекпота (1 к X)", callback_data=AdminSettingsCallbackData(setting_key="jackpot_chance").pack())],
        [InlineKeyboardButton(text="Кулдаун Рулетки", callback_data=AdminSettingsCallbackData(setting_key="roulette_cooldown").pack())],
        [
            InlineKeyboardButton(text="Мин. Рулетка", callback_data=AdminSettingsCallbackData(setting_key="roulette_min_bet").pack()),
            InlineKeyboardButton(text="Макс. Рулетка", callback_data=AdminSettingsCallbackData(setting_key="roulette_max_bet").pack())
        ],
        [
            InlineKeyboardButton(text="Мин. Лесенка", callback_data=AdminSettingsCallbackData(setting_key="ladder_min_bet").pack()),
            InlineKeyboardButton(text="Макс. Лесенка", callback_data=AdminSettingsCallbackData(setting_key="ladder_max_bet").pack())
        ],
        [InlineKeyboardButton(text="⬅️ Назад в админ-меню", callback_data=AdminCallbackData(action="main_admin_menu").pack())]
    ])
    return text, keyboard

async def get_events_menu() -> (str, InlineKeyboardMarkup):
    text = "<b>⚔️ Управление Ивентами</b>\n\nВыберите ивент для настройки или запуска:"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👹 Вышибала (Рейд-Босс)", callback_data=AdminRaidCallbackData(action="menu").pack())],
        [InlineKeyboardButton(text="⬅️ Назад в админ-меню", callback_data=AdminCallbackData(action="main_admin_menu").pack())]
    ])
    return text, keyboard

# --- АДМИН-ПАНЕЛЬ (admin_router) ---
@admin_router.message(Command("cancel"), IsAdmin(), StateFilter("*"))
async def cancel_handler(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        return
    await state.clear()
    await message.answer("Действие отменено.")

@admin_router.message(Command("admin"), IsAdmin())
async def cmd_admin_panel(message: Message):
    await message.answer("Добро пожаловать в админ-панель!", reply_markup=await get_main_admin_keyboard())

@admin_router.callback_query(AdminCallbackData.filter(), IsAdmin())
async def handle_admin_callback(callback: CallbackQuery, callback_data: AdminCallbackData, state: FSMContext, db: Database, settings: SettingsManager):
    action = callback_data.action
    await callback.answer()
    
    if action == "main_admin_menu":
        await callback.message.edit_text("Добро пожаловать в админ-панель!", reply_markup=await get_main_admin_keyboard())
        return

    # Убираем кнопки только если это не меню настроек или ивентов
    if action not in ["settings", "events"]:
        await callback.message.edit_reply_markup(reply_markup=None)
    
    if action == "stats":
        total_users = await db.get_total_users_count()
        all_chats = await db.get_all_chat_ids()
        await callback.message.answer(
            f"<b>📊 Статистика бота</b>\n\n"
            f"Всего пользователей: {total_users}\n"
            f"Всего чатов: {len(all_chats)}",
            parse_mode='HTML'
        )
    elif action == "broadcast":
        await state.set_state(AdminStates.broadcast_message)
        await callback.message.answer("Пожалуйста, отправьте сообщение для рассылки. Для отмены введите /cancel")
    elif action == "give_beer":
        await state.set_state(AdminStates.give_beer_user)
        await callback.message.answer("Кому выдать пиво? Отправьте ID, @username или перешлите сообщение. Для отмены введите /cancel")
    elif action == "settings":
        text, keyboard = await get_settings_menu(settings)
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode='HTML')
    elif action == "events":
        text, keyboard = await get_events_menu()
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode='HTML')

# --- Обработчики меню настроек ---
@admin_router.callback_query(AdminSettingsCallbackData.filter(), IsAdmin())
async def cq_admin_select_setting(callback: CallbackQuery, callback_data: AdminSettingsCallbackData, state: FSMContext, settings: SettingsManager):
    await callback.answer()
    setting_key = callback_data.setting_key
    await state.update_data(setting_key=setting_key)
    await state.set_state(AdminStates.waiting_for_setting_value)
    
    current_value = getattr(settings, setting_key)
    await callback.message.edit_text(
        f"Введите новое значение для <code>{setting_key}</code>.\n"
        f"Текущее значение: <code>{current_value}</code>\n\n"
        f"Для отмены введите /cancel.",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад к настройкам", callback_data=AdminCallbackData(action="settings").pack())]
        ])
    )

@admin_router.message(AdminStates.waiting_for_setting_value, IsAdmin())
async def process_setting_value(message: Message, state: FSMContext, db: Database, settings: SettingsManager):
    if not message.text or not message.text.isdigit():
        await message.reply("Ошибка. Введите целое число. Или /cancel.")
        return
    new_value = int(message.text)
    data = await state.get_data()
    setting_key = data.get('setting_key')
    await state.clear()
    
    try:
        await db.update_setting(setting_key, new_value)
        await settings.reload_setting(db, setting_key)
        await message.answer(f"✅ Настройка '<code>{setting_key}</code>' обновлена на <code>{new_value}</code>.", parse_mode='HTML')
        
        text, keyboard = await get_settings_menu(settings)
        await message.answer(text, reply_markup=keyboard, parse_mode='HTML')
    except Exception as e:
        await message.answer(f"Ошибка при обновлении: {e}")

# --- Обработчики меню ивентов ---
CHATS_PER_PAGE = 5

@admin_router.callback_query(AdminRaidCallbackData.filter(F.action == "menu"), IsAdmin())
async def cq_raid_menu(callback: CallbackQuery, settings: SettingsManager):
    await callback.answer()
    text = settings.get_raid_settings_text()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 ЗАПУСТИТЬ ИВЕНТ", callback_data=AdminRaidCallbackData(action="select_chat", page=0).pack())],
        [InlineKeyboardButton(text="✏️ Изменить Настройки (см. /set)", callback_data="do_nothing")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=AdminCallbackData(action="events").pack())]
    ])
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode='HTML')

@admin_router.callback_query(AdminRaidCallbackData.filter(F.action == "select_chat"), IsAdmin())
async def cq_raid_select_chat(callback: CallbackQuery, callback_data: AdminRaidCallbackData, db: Database):
    await callback.answer()
    page = callback_data.page
    
    all_chats = await db.get_all_chats()
    if not all_chats:
        await callback.message.edit_text("Бот не состоит ни в одном чате.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=AdminRaidCallbackData(action="menu").pack())]
        ]))
        return

    start = page * CHATS_PER_PAGE
    end = start + CHATS_PER_PAGE
    chats_on_page = all_chats[start:end]

    buttons = []
    for chat_id, title in chats_on_page:
        buttons.append([InlineKeyboardButton(text=title, callback_data=AdminRaidCallbackData(action="start", chat_id=chat_id).pack())])
    
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="⬅️", callback_data=AdminRaidCallbackData(action="select_chat", page=page-1).pack()))
    if end < len(all_chats):
        nav_buttons.append(InlineKeyboardButton(text="➡️", callback_data=AdminRaidCallbackData(action="select_chat", page=page+1).pack()))
    
    if nav_buttons: buttons.append(nav_buttons)
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=AdminRaidCallbackData(action="menu").pack())])

    await callback.message.edit_text(f"В каком чате запустить ивент? (Стр. {page+1})", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@admin_router.callback_query(AdminRaidCallbackData.filter(F.action == "start"), IsAdmin())
async def cq_raid_start(callback: CallbackQuery, callback_data: AdminRaidCallbackData, bot: Bot, db: Database, settings: SettingsManager):
    chat_id = callback_data.chat_id
    
    if await db.get_active_raid(chat_id):
        await callback.answer("В этом чате уже идет рейд!", show_alert=True)
        return
        
    await callback.answer("Запускаю рейд...")
    
    try:
        await start_raid_event(chat_id, bot, db, settings)
        await callback.message.edit_text(f"✅ Ивент 'Вышибала' успешно запущен в чате (ID: {chat_id})!")
    except Exception as e:
        await callback.message.edit_text(f"❌ Не удалось запустить ивент в чате {chat_id}.\nОшибка: {e}")


# --- Остальные админ-команды ---
@admin_router.message(AdminStates.broadcast_message, IsAdmin())
async def handle_broadcast_message(message: Message, state: FSMContext, bot: Bot, db: Database):
    await state.clear()
    await message.answer("Начинаю рассылку...")
    user_ids = await db.get_all_user_ids()
    chat_ids = await db.get_all_chat_ids()
    success_users, failed_users = 0, 0
    
    for user_id in user_ids:
        with suppress(TelegramBadRequest):
            try:
                await bot.copy_message(chat_id=user_id, from_chat_id=message.chat.id, message_id=message.message_id)
                success_users += 1
            except Exception:
                failed_users += 1
            await asyncio.sleep(0.05)
            
    success_chats, failed_chats = 0, 0
    for chat_id in chat_ids:
        with suppress(TelegramBadRequest):
            try:
                sent_message = await bot.copy_message(chat_id=chat_id, from_chat_id=message.chat.id, message_id=message.message_id)
                try:
                    await bot.pin_chat_message(chat_id=chat_id, message_id=sent_message.message_id)
                except Exception as e:
                    logging.warning(f"Не удалось закрепить сообщение в чате {chat_id}: {e}")
                success_chats += 1
            except Exception:
                failed_chats += 1
            await asyncio.sleep(0.05)
            
    await message.answer(
        f"<b>📢 Рассылка завершена!</b>\n\n"
        f"<b>Пользователи:</b>\n✅ Успешно: {success_users}\n❌ Неудачно: {failed_users}\n\n"
        f"<b>Чаты:</b>\n✅ Успешно: {success_chats}\n❌ Неудачно: {failed_chats}",
        parse_mode='HTML'
    )

@admin_router.message(AdminStates.give_beer_user, IsAdmin())
async def process_give_beer_user(message: Message, state: FSMContext, db: Database):
    target_id = None
    if message.forward_from:
        target_id = message.forward_from.id
    elif message.text and message.text.startswith('@'):
        target_id = await db.get_user_by_username(message.text)
    elif message.text and message.text.isdigit():
        target_id = int(message.text)
    if not target_id or not await db.user_exists(target_id):
        await message.reply("Пользователь не найден. Попробуйте снова или /cancel.")
        return
    await state.update_data(target_id=target_id)
    await state.set_state(AdminStates.give_beer_amount)
    await message.answer("Отлично. Теперь введите сумму (например, `100` или `-50`).")

@admin_router.message(AdminStates.give_beer_amount, IsAdmin())
async def process_give_beer_amount(message: Message, state: FSMContext, bot: Bot, db: Database):
    if not message.text or not message.text.lstrip('-').isdigit():
        await message.reply("Это не число. Введите сумму или /cancel.")
        return
    amount = int(message.text)
    user_data = await state.get_data()
    target_id = user_data.get('target_id')
    await state.clear()
    await db.change_rating(target_id, amount)
    new_balance = await db.get_user_beer_rating(target_id)
    await message.answer(
        f"Баланс изменен!\nID: <code>{target_id}</code>\nИзменение: {amount:+} 🍺\nНовый баланс: {new_balance} 🍺",
        parse_mode='HTML'
    )
    with suppress(TelegramBadRequest):
        await bot.send_message(chat_id=target_id, text=f"⚙️ Администратор изменил ваш баланс на {amount:+} 🍺.")

@admin_router.message(F.text.lower() == "бот выйди", IsAdmin())
async def admin_leave_chat(message: Message, bot: Bot):
    if message.chat.type in ['group', 'supergroup']:
        await message.reply("Хорошо, слушаюсь...")
        await bot.leave_chat(chat_id=message.chat.id)
    else:
        await message.reply("Эту команду можно использовать только в группах.")

@admin_router.message(Command("settings"), IsAdmin())
async def cmd_show_settings(message: Message, settings: SettingsManager):
    await show_settings_menu(message, settings)

@admin_router.message(Command("set"), IsAdmin())
async def cmd_set_setting(message: Message, bot: Bot, db: Database, settings: SettingsManager):
    args = message.text.split()
    if len(args) != 3:
        await message.reply("Неверный формат. Используйте: <code>/set &lt;ключ&gt; &lt;значение&gt;</code>\n"
                            "Пример: <code>/set beer_cooldown 3600</code>\n\n"
                            "Доступные ключи:\n"
                            "<code>beer_cooldown, jackpot_chance, roulette_cooldown, "
                            "roulette_min_bet, roulette_max_bet, ladder_min_bet, ladder_max_bet, "
                            "raid_boss_health, raid_reward_pool, raid_duration_hours, raid_hit_cooldown_minutes, "
                            "raid_strong_hit_cost, raid_strong_hit_damage_min, raid_strong_hit_damage_max, "
                            "raid_normal_hit_damage_min, raid_normal_hit_damage_max, raid_reminder_hours</code>",
                            parse_mode='HTML')
        return

    key, value = args[1], args[2]

    if not hasattr(settings, key):
        await message.reply(f"Ошибка: Неизвестный ключ настройки '<code>{key}</code>'.")
        return
        
    if not value.isdigit():
        await message.reply("Ошибка: Значение должно быть целым числом.")
        return
        
    int_value = int(value)
    
    try:
        await db.update_setting(key, int_value)
        await settings.reload_setting(db, key)
        await message.answer(f"✅ Настройка '<code>{key}</code>' успешно обновлена на <code>{int_value}</code>.", parse_mode='HTML')
        
        text, keyboard = await get_settings_menu(settings)
        await message.answer(text, reply_markup=keyboard, parse_mode='HTML')
        
    except Exception as e:
        await message.answer(f"Произошла ошибка при обновлении настройки: {e}")
