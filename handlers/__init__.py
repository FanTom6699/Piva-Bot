# # handlers/__init__.py
from aiogram import Router

from .admin import admin_router
from .common import common_router
from .user_commands import user_commands_router
from .game_ladder import ladder_router
from .game_roulette import roulette_router
from .game_raid import raid_router

# --- ✅ НОВЫЕ ИМПОРТЫ ФЕРМЫ ---
from .farm import farm_router
from .shop import shop_router
# --- ---

main_router = Router()
main_router.include_routers(
    admin_router,
    common_router,
    user_commands_router,
    ladder_router,
    roulette_router,
    raid_router,
    
    # --- ✅ НОВЫЕ РОУТЕРЫ ФЕРМЫ ---
    farm_router,
    shop_router
    # --- ---
)
