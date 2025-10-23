# handlers/common.py
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, ChatMemberUpdated, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart, Command
from database import Database

common_router = Router()
db = Database(db_name='/data/bot_database.db')

# --- ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ РЕГИСТРАЦИИ ---
async def check_user_registered(message_or_callback: Message | CallbackQuery, bot: Bot) -> bool:
    user = message_or_callback.from_user
    if await db.user_exists(user.id):
        return True
    me = await bot.get_me()
    start_link = f"https://t.me/{me.username}?start=register"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✍️ Зарегистрироваться", url=start_link)]])
    text = (
        "<b>Эй, новичок!</b> 🍻\n\n"
        "Прежде чем играть, нужно зайти в бар! "
        "Я тебя еще не знаю. Нажми на кнопку ниже, чтобы начать диалог со мной и зарегистрироваться."
    )
    if isinstance(message_or_callback, Message):
        await message_or_callback.reply(text, reply_markup=keyboard, parse_mode='HTML')
    else:
        await message_or_callback.answer("Сначала нужно зарегистрироваться!", show_alert=True)
        await bot.send_message(message_or_callback.message.chat.id, text, reply_markup=keyboard, parse_mode='HTML')
    return False

# --- ОБРАБОТЧИКИ СОБЫТИЙ ЧАТА ---
@common_router.my_chat_member()
async def handle_bot_membership(event: ChatMemberUpdated, bot: Bot):
    old_status = event.old_chat_member.status
    new_status = event.new_chat_member.status
    if old_status in ("left", "kicked") and new_status in ("member", "administrator"):
        await db.add_chat(event.chat.id, event.chat.title)
    elif old_status in ("member", "administrator") and new_status in ("left", "kicked"):
        await db.remove_chat(event.chat.id)

# --- КОМАНДЫ ПОЛЬЗОВАТЕЛЕЙ ---
@common_router.message(CommandStart())
async def cmd_start(message: Message):
    user = message.from_user
    if not await db.user_exists(user.id):
        await db.add_user(user.id, user.first_name, user.last_name, user.username)
        welcome_text = (
            f"Привет, {user.full_name}! 👋\n"
            f"Добро пожаловать в наш пивной клуб! Твой начальный рейтинг: 0 🍺.\n\n"
            f"Вот список доступных команд:\n"
            f"• `/beer` - Испытать удачу (раз в 2 часа).\n"
            f"• `/top` - Показать таблицу лидеров.\n"
            f"• `/roulette <ставка> <игроки>` - Запустить 'Пивную рулетку'.\n"
            f"• `/ladder <ставка>` - Начать игру в 'Пивную лесенку'.\n"
            f"• `/help` - Показать эту справку."
        )
        await message.answer(welcome_text)
    else:
        rating = await db.get_user_beer_rating(user.id)
        await message.answer(f"С возвращением, {user.full_name}! 🍻\nТвой текущий рейтинг: {rating} 🍺.")

@common_router.message(Command("help"))
async def cmd_help(message: Message):
    help_text = (
        "<b>🍻 Справка по командам бота 🍻</b>\n\n"
        "Здесь собраны все доступные команды и их описание.\n\n"
        "--- --- ---\n"
        "<b>Основные команды</b>\n"
        "• <code>/start</code> - Зарегистрироваться или проверить свой профиль.\n"
        "• <code>/beer</code> - Испытать удачу (раз в 2 часа).\n"
        "• <code>/top</code> - Показать таблицу лидеров.\n\n"
        "--- --- ---\n"
        "<b>Мини-игры</b>\n"
        "• <code>/roulette &lt;ставка&gt; &lt;игроки&gt;</code> - Запустить 'Пивную рулетку' в группе.\n"
        "• <code>/ladder &lt;ставка&gt;</code> - Начать игру в 'Пивную лесенку'.\n\n"
        "--- --- ---\n"
        "<b>Прочее</b>\n"
        "• <code>/id</code> - Узнать свой User ID и ID текущего чата."
    )
    await message.answer(help_text, parse_mode='HTML')

@common_router.message(Command("id"))
async def cmd_id(message: Message):
    await message.reply(
        f"ℹ️ **Информация:**\n\n"
        f"👤 Ваш User ID: <code>{message.from_user.id}</code>\n"
        f"💬 ID этого чата: <code>{message.chat.id}</code>",
        parse_mode='HTML'
    )
