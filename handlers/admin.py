# handlers/admin.py
import html
from aiogram import Router, F, Bot
from aiogram.types import Message
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from database import Database
# --- ИСПРАВЛЕНИЕ 1: Убираем 'SETTINGS_KEYS' из импорта ---
from settings import SettingsManager

admin_router = Router()

# --- ФИЛЬТР АДМИНА ---
class AdminFilter:
    def __init__(self, db: Database):
        self.db = db
    async def __call__(self, message: Message) -> bool:
        return await self.db.is_admin(message.from_user.id)

# --- КОМАНДЫ АДМИНОВ ---
@admin_router.message(Command("admin"), AdminFilter)
async def cmd_admin(message: Message):
    # (Тексты, которые мы поменяли, остаются)
    await message.answer(
        "🔧 <b>Админ-панель 'Пивной'</b> 🔧\n\n"
        "Добро пожаловать, босс. Что настраиваем?\n\n"
        "• <code>/set &lt;ключ&gt; &lt;значение&gt;</code> - Изменить настройку.\n"
        "• <code>/give &lt;id&gt; &lt;кол-во&gt;</code> - Выдать 'пиво' юзеру.\n"
        "• <code>/stats</code> - Посмотреть статистику.\n"
        "• <code>/reload_settings</code> - Перезагрузить настройки из БД.",
        parse_mode='HTML'
    )

@admin_router.message(Command("set"), AdminFilter)
async def cmd_set(message: Message, db: Database, settings: SettingsManager):
    args = message.text.split()
    if len(args) < 3:
        
        # --- ИСПРАВЛЕНИЕ 2: Получаем SETTINGS_KEYS из 'settings', а не из импорта ---
        keys_list = "\n".join(f"• <code>{k}</code> ({v.get('type', 'str')}) - {v.get('desc', 'N/A')}" for k, v in settings.SETTINGS_KEYS.items())
        # --- КОНЕЦ ИСПРАВЛЕНИЯ 2 ---
        
        return await message.answer(
            "⚙️ <b>Настройка баланса (SET)</b>\n"
            "<code>/set &lt;ключ&gt; &lt;значение&gt;</code>\n\n"
            "<b>Доступные ключи:</b>\n"
            f"{keys_list}",
            parse_mode='HTML'
        )

    key = args[1]
    value_str = args[2]

    try:
        await settings.set(key, value_str)
        await message.answer(
            f"✅ <b>Настройка сохранена!</b>\n"
            f"<code>{key}</code> = <code>{html.escape(value_str)}</code>",
            parse_mode='HTML'
        )
    except Exception as e:
        await message.answer(f"❌ <b>Ошибка при сохранении:</b>\n{e}")

@admin_router.message(Command("give"), AdminFilter)
async def cmd_give(message: Message, db: Database):
    args = message.text.split()
    if len(args) < 3:
        return await message.answer(
            "🎁 <b>Выдача 'Пива' (GIVE)</b>\n"
            "<code>/give &lt;user_id&gt; &lt;кол-во&gt;</code>\n\n"
            "<i>(<code>user_id</code> можно узнать командой /id или в /stats)</i>",
            parse_mode='HTML'
        )
        
    try:
        user_id = int(args[1])
        amount = int(args[2])
    except ValueError:
        return await message.answer("❌ ID пользователя и количество должны быть числами.")

    if not await db.user_exists(user_id):
        return await message.answer(f"❌ Не удалось найти пользователя с ID: <code>{user_id}</code>")

    await db.update_user_beer_rating(user_id, amount)
    
    await message.answer(
        f"🍻 <b>Угощение выдано!</b>\n"
        f"<b>{amount} 🍺</b> отправлено игроку <code>{user_id}</code>.",
        parse_mode='HTML'
    )

@admin_router.message(Command("stats"), AdminFilter)
async def cmd_stats(message: Message, db: Database):
    total_users = await db.get_total_users()
    total_chats = await db.get_total_chats()
    total_rating = await db.get_total_beer_rating()
    top_user = await db.get_top_users(1)
    
    top_user_str = "N/A"
    if top_user:
        user = top_user[0]
        user_name = html.escape(f"{user['first_name']} {user.get('last_name', '')}".strip())
        top_user_str = f"{user_name} (ID: <code>{user['user_id']}</code>) - <b>{user['beer_rating']}</b> 🍺"

    await message.answer(
        "<b>📊 Статистика Бота</b>\n\n"
        f"👤 Всего игроков: <b>{total_users}</b>\n"
        f"👥 Всего чатов: <b>{total_chats}</b>\n"
        f"🍺 Всего 'пива' в системе: <b>{total_rating}</b>\n\n"
        f"🏆 Топ игрок: {top_user_str}",
        parse_mode='HTML'
    )

@admin_router.message(Command("reload_settings"), AdminFilter)
async def cmd_reload_settings(message: Message, settings: SettingsManager):
    try:
        await settings.load_settings()
        await message.answer(
            "🔄 <b>Настройки из БД перезагружены!</b>\n"
            "Все 'краны' работают по-новому."
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка при перезагрузке настроек:\n{e}")
