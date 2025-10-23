# handlers/admin.py
import asyncio
from contextlib import suppress

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command, Filter, StateFilter
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest

import config
from database import Database
from settings import settings_manager # <-- ИМПОРТ МЕНЕДЖЕРА

# --- ИНИЦИАЛИЗАЦИЯ ---
admin_router = Router()
db = Database(db_name='/data/bot_database.db')

# --- FSM СОСТОЯНИЯ ---
class AdminStates(StatesGroup):
    broadcast_message = State()
    give_beer_user = State()
    give_beer_amount = State()

# --- ФИЛЬТРЫ ---
class IsAdmin(Filter):
    async def __call__(self, message: Message | CallbackQuery) -> bool:
        return message.from_user.id == config.ADMIN_ID

# --- CALLBACKDATA ФАБРИКИ ---
class AdminCallbackData(CallbackData, prefix="admin"):
    action: str

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
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🍺 Выдать пиво", callback_data=AdminCallbackData(action="give_beer").pack())],
        [InlineKeyboardButton(text="📢 Сделать рассылку", callback_data=AdminCallbackData(action="broadcast").pack())],
        [InlineKeyboardButton(text="📊 Статистика", callback_data=AdminCallbackData(action="stats").pack())],
        [InlineKeyboardButton(text="⚙️ Настройки бота", callback_data=AdminCallbackData(action="settings").pack())]
    ])
    await message.answer("Добро пожаловать в админ-панель!", reply_markup=keyboard)

@admin_router.callback_query(AdminCallbackData.filter(), IsAdmin())
async def handle_admin_callback(callback: CallbackQuery, callback_data: AdminCallbackData, state: FSMContext):
    action = callback_data.action
    await callback.answer()
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
        await callback.message.answer(
            settings_manager.get_all_settings_text(),
            parse_mode='HTML'
        )

@admin_router.message(AdminStates.broadcast_message, IsAdmin())
async def handle_broadcast_message(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    await message.answer("Начинаю рассылку...")
    user_ids = await db.get_all_user_ids()
    chat_ids = await db.get_all_chat_ids()
    success_users, failed_users = 0, 0
    
    # Рассылка по пользователям (без закрепления)
    for user_id in user_ids:
        with suppress(TelegramBadRequest):
            try:
                await bot.copy_message(chat_id=user_id, from_chat_id=message.chat.id, message_id=message.message_id)
                success_users += 1
            except Exception:
                failed_users += 1
            await asyncio.sleep(0.05)
            
    # Рассылка по чатам (С ЗАКРЕПЛЕНИЕМ)
    success_chats, failed_chats = 0, 0
    for chat_id in chat_ids:
        with suppress(TelegramBadRequest):
            try:
                sent_message = await bot.copy_message(chat_id=chat_id, from_chat_id=message.chat.id, message_id=message.message_id)
                
                # --- ИЗМЕНЕНИЕ ЗДЕСЬ ---
                try:
                    await bot.pin_chat_message(chat_id=chat_id, message_id=sent_message.message_id)
                except Exception as e:
                    logging.warning(f"Не удалось закрепить сообщение в чате {chat_id}: {e}")
                # --- КОНЕЦ ИЗМЕНЕНИЯ ---
                    
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

# ... (код выдачи пива process_give_beer_user и process_give_beer_amount без изменений) ...

@admin_router.message(F.text.lower() == "бот выйди", IsAdmin())
async def admin_leave_chat(message: Message, bot: Bot):
    if message.chat.type in ['group', 'supergroup']:
        await message.reply("Хорошо, слушаюсь...")
        await bot.leave_chat(chat_id=message.chat.id)
    else:
        await message.reply("Эту команду можно использовать только в группах.")

# --- НОВЫЕ КОМАНДЫ ДЛЯ НАСТРОЕК ---
@admin_router.message(Command("settings"), IsAdmin())
async def cmd_show_settings(message: Message):
    await message.answer(
        settings_manager.get_all_settings_text(),
        parse_mode='HTML'
    )

@admin_router.message(Command("set"), IsAdmin())
async def cmd_set_setting(message: Message, bot: Bot):
    args = message.text.split()
    if len(args) != 3:
        await message.reply("Неверный формат. Используйте: <code>/set &lt;ключ&gt; &lt;значение&gt;</code>\n"
                            "Пример: <code>/set beer_cooldown 3600</code>\n\n"
                            "Доступные ключи:\n"
                            "<code>beer_cooldown, jackpot_chance, roulette_cooldown, "
                            "roulette_min_bet, roulette_max_bet, ladder_min_bet, ladder_max_bet</code>",
                            parse_mode='HTML')
        return

    key, value = args[1], args[2]

    if not hasattr(settings_manager, key):
        await message.reply(f"Ошибка: Неизвестный ключ настройки '<code>{key}</code>'.")
        return
        
    if not value.isdigit():
        await message.reply("Ошибка: Значение должно быть целым числом.")
        return
        
    int_value = int(value)
    
    try:
        await db.update_setting(key, int_value)
        await settings_manager.reload_setting(db, key)
        await message.answer(f"✅ Настройка '<code>{key}</code>' успешно обновлена на <code>{int_value}</code>.", parse_mode='HTML')
        
        # Показываем обновленные настройки
        await cmd_show_settings(message)
        
    except Exception as e:
        await message.answer(f"Произошла ошибка при обновлении настройки: {e}")
