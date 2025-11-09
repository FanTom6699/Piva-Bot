# handlers/__init__.py
from aiogram import Router

# --- Базовые Хэндлеры ---
from .admin import admin_router
from .common import common_router
from .user_commands import user_commands_router

# --- Хэндлеры Игр ---
from .game_ladder import ladder_router
from .game_roulette import roulette_router
from .game_raid import raid_router

# --- ✅ НОВЫЕ ХЭНДЛЕРЫ Фермы ---
from .farm import farm_router
# (farm_updater не имеет кнопок, его роутер не нужен, он только для фоновой задачи)
from .give import give_router

main_router = Router()
main_router.include_routers(
    admin_router,
    common_router,
    
    # --- Игры ---
    ladder_router,
    roulette_router,
    raid_router,
    
    # --- Ферма ---
    farm_router,
    give_router,
    
    # --- Команды юзера должны быть последними ---
    user_commands_router
)
