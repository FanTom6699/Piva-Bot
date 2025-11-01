# mafia_handlers/__init__.py
from aiogram import Router

# Импортируем роутеры из наших новых файлов
from .common import mafia_common_router
from .game_mafia_lobby import mafia_lobby_router
from .game_mafia_core import mafia_game_router

# Создаем главный роутер Мафии
mafia_router = Router()

# Включаем в него все остальные роутеры Мафии
mafia_router.include_routers(
    mafia_common_router,
    mafia_lobby_router,
    mafia_game_router
)
