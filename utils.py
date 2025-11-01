# utils.py
from datetime import timedelta

# --- ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ДЛЯ ИГР ---

# Хранит фоновые задачи для таймеров лобби Мафии {chat_id: asyncio.Task}
active_lobby_timers = {}

# Хранит активные игры (Рулетка, Лесенка) {chat_id: {...}}
# (Мы импортируем это в mafia_lobby.py, чтобы Мафия не запускалась поверх Рулетки)
active_games = {}
GAME_ACTIVE_KEY = "game_active"


# --- ФУНКЦИИ ФОРМАТИРОВАНИЯ ВРЕМЕНИ ---

def format_time_delta(time_delta: timedelta) -> str:
    """Форматирует timedelta в строку 'Ч ч М м С с'."""
    parts = []
    total_seconds = int(time_delta.total_seconds())
    
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    
    if hours > 0:
        parts.append(f"{hours} ч")
    if minutes > 0:
        parts.append(f"{minutes} м")
    if seconds > 0 or not parts:
        parts.append(f"{seconds} с")
        
    return " ".join(parts)

def format_time_left(total_seconds: int) -> str:
    """Форматирует секунды в строку 'М:СС' или 'Ч:ММ:СС' (нужно для Мафии)."""
    if total_seconds < 0:
        total_seconds = 0
        
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    
    if hours > 0:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    else:
        return f"{minutes}:{seconds:02d}"
