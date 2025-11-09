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
from .farm_updater import farm_router as farm_updater_router
from .give import give_router
from .shop import shop_router # ✅ ВКЛЮЧАЕМ МАГАЗИН

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
    farm_updater_router,
    give_router,
    shop_router, # ✅ РЕГИСТРИРУЕМ МАГАЗИН
    
    # --- Команды юзера должны быть последними ---
    user_commands_router
)
