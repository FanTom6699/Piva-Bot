# handlers/__init__.py
from aiogram import Router

# Импортируем все наши роутеры
from .admin import admin_router
from .common import common_router
from .user_commands import user_router
from .game_raid import raid_router
# --- ИМПОРТЫ МАФИИ ---
from .game_mafia_lobby import mafia_lobby_router
# from .game_mafia_core import mafia_game_router # <-- НОВЫЙ ИМПОРТ

# Создаем главный роутер
main_router = Router()

# Регистрируем все роутеры в главном
main_router.include_router(admin_router)
main_router.include_router(common_router)
main_router.include_router(raid_router)

# --- НОВЫЕ РОУТЕРЫ МАФИИ ---
main_router.include_router(mafia_lobby_router) # /mafia и лобби
main_router.include_router(mafia_game_router)  # Ночные голоса, чат мафии и т.д.

# Роутер пользовательских команд (user_router) должен идти последним,
# так как он содержит "общие" хэндлеры, которые могут 
# перехватывать FSM-состояния, если их поставить раньше.
main_router.include_router(user_router)
