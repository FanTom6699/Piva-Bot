# handlers/__init__.py
from aiogram import Router

from .common import common_router
from .admin import admin_router
from .game_roulette import game_router as roulette_router
from .game_ladder import game_router as ladder_router
# --- ИСПРАВЛЕНИЕ: 'user_commands_router' -> 'user_router' ---
from .user_commands import user_router
from .game_raid import game_router as raid_router

main_router = Router()

main_router.include_routers(
    admin_router,
    common_router,
    # --- ИСПРАВЛЕНИЕ: 'user_commands_router' -> 'user_router' ---
    user_router,
    roulette_router,
    ladder_router,
    raid_router,
)
