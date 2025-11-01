# mafia_handlers/__init__.py
from aiogram import Router
from .common import mafia_common_router

# Сюда позже добавим .lobby.py, .game.py
# from .lobby import mafia_lobby_router

mafia_router = Router()
mafia_router.include_routers(
    mafia_common_router
    # mafia_lobby_router
)
