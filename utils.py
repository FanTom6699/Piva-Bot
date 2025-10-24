# utils.py
import asyncio
from typing import Dict
from datetime import timedelta # <-- Это из твоего файла

# --- НОВЫЙ СЛОВАРЬ ДЛЯ ТАЙМЕРОВ МАФИИ ---
# Мы будем хранить здесь задачи, чтобы иметь возможность их отменить
# Ключ: chat_id, Значение: asyncio.Task
active_lobby_timers: Dict[int, asyncio.Task] = {}


# --- ЭТО ТВОЯ СУЩЕСТВУЮЩАЯ ФУНКЦИЯ ---
# (Я немного исправил ее, чтобы она правильно показывала "0 с", если время вышло)
def format_time_delta(delta: timedelta) -> str:
    """Форматирует timedelta в строку 'Ч ч М м С с'."""
    parts = []
    total_seconds = int(delta.total_seconds())
    
    if total_seconds <= 0:
        return "0 с"
        
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    
    if hours > 0:
        parts.append(f"{hours} ч")
    if minutes > 0:
        parts.append(f"{minutes} м")
    if seconds > 0 or not parts:
        parts.append(f"{seconds} с")
        
    return " ".join(parts)


# --- ЭТО НОВАЯ ФУНКЦИЯ ДЛЯ ТАЙМЕРА ЛОББИ ---
# Она форматирует int (например, "90" -> "1м 30с")
def format_time_left(seconds: int) -> str:
    """
    Превращает секунды в строку вида "1м 30с".
    """
    if seconds <= 0:
        return "0с"
    
    minutes, sec = divmod(seconds, 60)
    
    if minutes > 0:
        return f"{minutes}м {sec}с"
    else:
        return f"{sec}с"
