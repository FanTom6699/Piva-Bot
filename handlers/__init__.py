# handlers/__init__.py
from aiogram import Router

from .admin import admin_router
from .common import common_router
from .user_commands import user_commands_router
from .game_ladder import ladder_router
from .game_roulette import roulette_router
from .game_raid import raid_router
from .farm import farm_router # (Ферма)
from .farm_updater import farm_updater_router # (Уведомления)
# from .shop import shop_router # ✅ (Piva Bot) Отключаем старый магазин
from .game_mafia_lobby import mafia_lobby_router
from .game_mafia_core import mafia_game_router

main_router = Router()
main_router.include_routers(
    admin_router,
    common_router,
    user_commands_router,
    ladder_router,
    roulette_router,
    raid_router,
    farm_router, # (Ферма)
    # shop_router, # ✅ (Piva Bot) Отключаем старый магазин
    mafia_lobby_router,
    mafia_game_router
)

# (farm_updater_router не нужно включать сюда, он запускается из main.py)
