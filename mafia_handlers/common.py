# mafia_handlers/common.py
from aiogram import Router
from aiogram.types import Message
from aiogram.filters import CommandStart, Command

mafia_common_router = Router()

@mafia_common_router.message(CommandStart())
async def cmd_mafia_start(message: Message):
    await message.answer(
        "🕵️‍♂️ Привет! Я — <b>Мафия-Бот</b> для 'Пивной'.\n\n"
        "Добавь меня в свой групповой чат, дай права администратора (чтобы я мог удалять сообщения и видеть всех участников), и мы сможем начать игру.\n\n"
        "Для запуска игры в группе используй /mafia."
    )

@mafia_common_router.message(Command("help"))
async def cmd_mafia_help(message: Message):
    await message.answer(
        "<b>📜 Правила 'Пивной Мафии' (WIP) 📜</b>\n\n"
        "• <code>/mafia</code> - (Только в группе) Начать набор в игру.\n"
        "• <code>/join</code> - Присоединиться к игре (когда идет набор).\n"
        "• <code>/startgame</code> - (Только админ чата) Принудительно начать игру, не дожидаясь таймера.\n"
    )
