# handlers/give.py
import logging
from aiogram import Router, F, Bot, html
from aiogram.types import Message
from aiogram.filters import Command, CommandPrefix

from database import Database
from .common import check_user_registered
from .farm import FARM_ITEM_NAMES # Импортируем "понятные" названия

# --- ИНИЦИАЛИЗАЦИЯ ---
give_router = Router()

# --- СПИСОК "ПОНЯТНЫХ" НАЗВАНИЙ (Наш План) ---
# (item_id из database.py)
ALLOWED_ITEMS = ['зерно', 'хмель', 'семя_зерна', 'семя_хмеля']

# --- ТЕКСТ "ПОМОЩИ" (Твой План) ---
GIVE_HELP_TEXT = (
    "⛔ <b>Ошибка!</b> Неправильный формат.\n\n"
    "<b>Помощь по передаче: <code>/кинуть</code></b>\n\n"
    "<b>Формат:</b> <code>/кинуть &lt;ресурс&gt; &lt;кол-во&gt; [цель]</code>\n\n"
    "<b>[Цель]</b> (необязательно, если отвечаешь):\n"
    "• <i>Ответ</i> (Reply) на сообщение\n"
    "• <code>@username</code>\n"
    "• <code>User ID</code>\n\n"
    "<b>&lt;Ресурсы&gt;:</b>\n"
    "• <code>зерно</code> (🌾 Урожай)\n"
    "• <code>хмель</code> (🌱 Урожай)\n"
    "• <code>семя_зерна</code> (🌾 Семена)\n"
    "• <code>семя_хмеля</code> (🌱 Семена)"
)

# --- 1. ХЭНДЛЕР (Срабатывает на /кинуть и !кинуть) ---
@give_router.message(CommandPrefix(prefixes=['/', '!']))
@give_router.message(Command("кинуть"))
async def cmd_give_item(message: Message, bot: Bot, db: Database):
    
    # 0. Проверка на регистрацию
    if not await check_user_registered(message, bot, db):
        return

    sender = message.from_user
    args = message.text.split()
    # args[0] = "/кинуть" или "!кинуть"
    # args[1] = <ресурс>
    # args[2] = <кол-во>
    # args[3] = [цель]

    # --- 2. ПАРСИНГ И ПРОВЕРКА АРГУМЕНТОВ ---
    
    item_id: str = ""
    quantity: int = 0
    target_user_id: int = 0
    target_user_name: str = ""
    
    # A. Неправильная команда (слишком короткая)
    if len(args) < 3:
        await message.reply(GIVE_HELP_TEXT)
        return

    # B. Проверка <ресурса> (args[1])
    item_id = args[1].lower()
    if item_id not in ALLOWED_ITEMS:
        await message.reply(f"⛔ <b>Ошибка!</b>\nНеизвестный ресурс: '<code>{html.escape(item_id)}</code>'.\n\n" + GIVE_HELP_TEXT)
        return
        
    item_name = FARM_ITEM_NAMES.get(item_id, item_id) # "🌾 Зерно (Урожай)"

    # C. Проверка <кол-во> (args[2])
    if not args[2].isdigit() or int(args[2]) <= 0:
        await message.reply(f"⛔ <b>Ошибка!</b>\nКоличество '<code>{html.escape(args[2])}</code>' должно быть положительным числом.\n\n" + GIVE_HELP_TEXT)
        return
    
    quantity = int(args[2])

    # --- 3. ПОИСК "ЦЕЛИ" (Твоя 3-Way Система) ---
    
    # Способ 1: Ответ (Reply)
    if message.reply_to_message:
        target_user = message.reply_to_message.from_user
        # Нельзя кинуть боту или самому себе через Reply
        if target_user.is_bot:
            await message.reply("⛔ Нельзя передавать ресурсы ботам.")
            return
        if target_user.id == sender.id:
            await message.reply("⛔ Нельзя передать ресурсы самому себе.")
            return
            
        target_user_id = target_user.id
        target_user_name = target_user.full_name

    # Способ 2 и 3: @Username или User ID (в args[3])
    elif len(args) >= 4:
        target_str = args[3]
        
        # Способ 2: @Username
        if target_str.startswith('@'):
            username = target_str[1:]
            if username.lower() == sender.username.lower():
                 await message.reply("⛔ Нельзя передать ресурсы самому себе.")
                 return
                 
            target_data = await db.get_user_by_username(username)
            if not target_data:
                await message.reply(f"⛔ <b>Ошибка!</b>\nНе могу найти игрока с <code>@{html.escape(username)}</code> в базе данных.")
                return
            target_user_id, target_user_name = target_data
        
        # Способ 3: User ID
        elif target_str.isdigit():
            user_id_int = int(target_str)
            if user_id_int == sender.id:
                 await message.reply("⛔ Нельзя передать ресурсы самому себе.")
                 return
                 
            target_data = await db.get_user_by_id(user_id_int)
            if not target_data:
                await message.reply(f"⛔ <b>Ошибка!</b>\nНе могу найти игрока с ID <code>{user_id_int}</code> в базе данных.")
                return
            target_user_id, target_user_name = target_data
            
        else:
            await message.reply(GIVE_HELP_TEXT)
            return
    
    # D. Если "Цель" не найдена (не было Reply и не было args[3])
    else:
        await message.reply(GIVE_HELP_TEXT)
        return

    # --- 4. ПРОВЕРКА БАЛАНСА "СКЛАДА" ---
    
    sender_inventory = await db.get_user_inventory(sender.id)
    if sender_inventory.get(item_id, 0) < quantity:
        await message.reply(f"⛔ <b>Недостаточно!</b>\nУ тебя {sender_inventory.get(item_id, 0)} {item_name}, а ты пытаешься кинуть {quantity}.")
        return

    # --- 5. АТОМНАЯ ОПЕРАЦИЯ ПЕРЕДАЧИ ---
    try:
        # Списываем у Отправителя
        success_remove = await db.modify_inventory(sender.id, item_id, -quantity)
        
        if not success_remove:
             # (Двойная проверка, на всякий случай)
             await message.reply(f"⛔ <b>Недостаточно!</b> (Ошибка при списании)")
             return
        
        # Начисляем Получателю
        await db.modify_inventory(target_user_id, item_id, quantity)

    except Exception as e:
        logging.error(f"Критическая ошибка при передаче /кинуть (с {sender.id} на {target_user_id}): {e}")
        # Пытаемся вернуть ресурсы отправителю, если получателю не дошло
        await db.modify_inventory(sender.id, item_id, quantity)
        await message.reply("⛔ <b>Критическая Ошибка!</b>\nПроизошла ошибка базы данных. Ресурсы возвращены тебе.")
        return

    # --- 6. УСПЕХ ---
    await message.reply(
        f"✅ <b>Передача Успешна!</b>\n\n"
        f"<i>{html.escape(sender.full_name)}</i> передал {quantity} {item_name} игроку <i>{html.escape(target_user_name)}</i>!"
    )
    
    # (Опционально: можно отправить ЛС получателю, но пока не будем, чтобы не спамить)
