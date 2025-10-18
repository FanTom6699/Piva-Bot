# utils.py
from datetime import timedelta

def format_time_delta(delta: timedelta) -> str:
    """Форматирует timedelta в строку 'Ч ч М м С с'."""
    parts = []
    total_seconds = int(delta.total_seconds())
    
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    if hours > 0:
        parts.append(f"{hours} ч")
    if minutes > 0:
        parts.append(f"{minutes} мин")
    if seconds > 0 or not parts:
        parts.append(f"{seconds} сек")
        
    return " ".join(parts)
