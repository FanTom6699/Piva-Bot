# handlers/__init__.py
from aiogram import Router

# Импортируем все наши роутеры
from .admin import admin_router
from .common import common_router
from .user_commands import user_router
from .game_raid import raid_router
# --- НОВЫЙ ИМПОРТ ---
from .game_mafia_lobby import mafia_lobby_router

# Создаем главный роутер
main_router = Router()

# Регистрируем все роутеры в главном
main_router.include_router(admin_router)
main_router.include_router(common_router)
main_router.include_router(raid_router)
# --- НОВЫЙ РОУТЕР МАФИИ ---
main_router.include_router(mafia_lobby_router)

# Роутер пользовательских команд (user_router) должен идти последним,
# так как он содержит "общие" хэндлеры, которые могут 
# перехватывать FSM-состояния, если их поставить раньше.
# (Хотя, команды (/start) можно ставить и раньше).
# Давайте оставим его последним для безопасности.
main_router.include_router(user_router)
