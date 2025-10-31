
# config.py
import os
from dataclasses import dataclass
from dotenv import load_dotenv

# --- Оставляем ADMIN_ID, так как database.py его импортирует ---
# (В идеале, его тоже стоит вынести в .env, но 'database.py' 
# импортирует его напрямую, так что пока оставим так, 
# чтобы не сломать 'init_db')
ADMIN_ID = 5658493362 


@dataclass
class Config:
    """
    Класс конфигурации для хранения токена.
    """
    bot_token: str

# --- ДОБАВЛЯЕМ НЕДОСТАЮЩУЮ ФУНКЦИЮ 'load_config' ---
def load_config() -> Config:
    """
    Загружает конфигурацию из .env файла.
    """
    load_dotenv() # Загружаем переменные из .env

    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        # Эта ошибка скажет, если ты забыл токен в .env
        raise ValueError("Не найден BOT_TOKEN в .env файле!")

    return Config(
        bot_token=bot_token
    )
