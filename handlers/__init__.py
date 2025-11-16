# handlers/__init__.py
from aiogram import Router

from .admin import admin_router
from .common import common_router
from .user_commands import user_commands_router
from .game_ladder import ladder_router
from .game_roulette import roulette_router
from .game_raid import raid_router
from .farm import farm_router # (Ферма)
# from .shop import shop_router # (Этот мы отключили в прошлый раз)
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
    # shop_router, # (Этот мы отключили в прошлый раз)
    mafia_lobby_router,
    mafia_game_router
)

# ---
# (Piva Bot) Я УДАЛИЛ отсюда 'farm_updater_router'. 
# Он не должен здесь подключаться.
# Он запускается только из main.py.
# ---
