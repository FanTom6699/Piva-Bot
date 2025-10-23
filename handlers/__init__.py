# handlers/__init__.py
from aiogram import Router

from .admin import admin_router
from .common import common_router
from .user_commands import user_commands_router
from .game_ladder import ladder_router
from .game_roulette import roulette_router

# Собираем все роутеры в один главный
main_router = Router()
main_router.include_routers(
    admin_router,
    common_router,
    user_commands_router,
    ladder_router,
    roulette_router
    # Новый роутер для новой игры будет добавляться сюда
)
