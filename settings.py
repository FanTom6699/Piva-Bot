# settings.py
import logging
from database import Database

# Названия настроек на русском языке для /admin
SETTINGS_NAMES = {
    "beer_cooldown": "Кулдаун /beer (сек)",
    "jackpot_chance": "Шанс Джекпота (1 к X)",
    "roulette_cooldown": "Кулдаун Рулетки (сек)",
    "roulette_min_bet": "Мин. ставка Рулетки",
    "roulette_max_bet": "Макс. ставка Рулетки",
    "ladder_min_bet": "Мин. ставка Лесенки",
    "ladder_max_bet": "Макс. ставка Лесенки",
    "raid_boss_health": "Здоровье Рейд-Босса",
    "raid_reward_pool": "Награда Рейд-Босса",
    "raid_duration_hours": "Длительность Рейда (часы)",
    "raid_hit_cooldown_minutes": "Кулдаун удара (мин)",
    "raid_strong_hit_cost": "Цена сильного удара",
    "raid_strong_hit_damage_min": "Мин. урон (сильный)",
    "raid_strong_hit_damage_max": "Макс. урон (сильный)",
    "raid_normal_hit_damage_min": "Мин. урон (обычный)",
    "raid_normal_hit_damage_max": "Макс. урон (обычный)",
    "raid_reminder_hours": "Напоминание о Рейде (часы)",
    # --- НОВЫЕ НАСТРОЙКИ МАФИИ ---
    "mafia_lobby_timer": "Таймер Лобби Мафии (сек)",
    "mafia_min_players": "Мин. игроков Мафии",
    "mafia_max_players": "Макс. игроков Мафии",
    "mafia_night_timer": "Таймер Ночи (сек)",
    "mafia_day_timer": "Таймер Дня (обсужд, сек)",
    "mafia_vote_timer": "Таймер Голосования (сек)",
    "mafia_win_reward": "Награда Мафии (Победа, 🍺)",
    "mafia_lose_reward": "Награда Мафии (Утеш, 🍺)",
    "mafia_win_authority": "Авторитет (Победа, 🎩)",
    "mafia_lose_authority": "Авторитет (Пораж, 🎩)",
}

class SettingsManager:
    # __init__ НЕ ПРИНИМАЕТ 'db'
    def __init__(self):
        logging.info("Инициализация Менеджера Настроек...")
        # --- ОБЫЧНЫЕ ---
        self.beer_cooldown = 7200
        self.jackpot_chance = 150
        # --- РУЛЕТКА ---
        self.roulette_cooldown = 600
        self.roulette_min_bet = 5
        self.roulette_max_bet = 100
        # --- ЛЕСЕНКА ---
        self.ladder_min_bet = 5
        self.ladder_max_bet = 100
        # --- РЕЙДЫ ---
        self.raid_boss_health = 100000
        self.raid_reward_pool = 5000
        self.raid_duration_hours = 24
        self.raid_hit_cooldown_minutes = 30
        self.raid_strong_hit_cost = 100
        self.raid_strong_hit_damage_min = 500
        self.raid_strong_hit_damage_max = 1000
        self.raid_normal_hit_damage_min = 10
        self.raid_normal_hit_damage_max = 50
        self.raid_reminder_hours = 6
        # --- НОВЫЕ: МАФИЯ ---
        self.mafia_lobby_timer = 90
        self.mafia_min_players = 5
        self.mafia_max_players = 10
        self.mafia_night_timer = 90
        self.mafia_day_timer = 120
        self.mafia_vote_timer = 60
        self.mafia_win_reward = 100
        self.mafia_lose_reward = 25
        self.mafia_win_authority = 15
        self.mafia_lose_authority = -10

    # load_settings ПРИНИМАЕТ 'db'
    async def load_settings(self, db: Database):
        """Загружает все настройки из базы данных в экземпляр класса."""
        logging.info("Загрузка настроек из БД...")
        try:
            settings_data = await db.get_all_settings()
            for key, value in settings_data.items():
                if hasattr(self, key):
                    setattr(self, key, int(value))
            logging.info("Настройки успешно загружены.")
        except Exception as e:
            logging.error(f"Ошибка при загрузке настроек: {e}. Используются значения по умолчанию.")

    async def reload_setting(self, db: Database, key: str):
        """Перезагружает одну конкретную настройку из БД."""
        try:
            if hasattr(self, key):
                value = await db.get_setting(key)
                setattr(self, key, int(value))
                logging.info(f"Настройка '{key}' перезагружена. Новое значение: {value}")
        except Exception as e:
            logging.error(f"Ошибка при перезагрузке настройки '{key}': {e}")

    def _format_setting_line(self, key: str) -> str:
        """Форматирует одну строку настройки для вывода."""
        name = SETTINGS_NAMES.get(key, key)
        value = getattr(self, key, "N/A")
        return f"• <code>{name}</code>: <b>{value}</b>\n"

    def get_all_settings_text(self) -> str:
        """Возвращает отформатированный текст со всеми настройками для админ-панели."""
        text = "<b>⚙️ Текущие настройки Бота</b>\n\n"
        
        text += "<b>Общие:</b>\n"
        text += self._format_setting_line("beer_cooldown")
        text += self._format_setting_line("jackpot_chance")
        
        text += "\n<b>Мини-Игры:</b>\n"
        text += self._format_setting_line("roulette_cooldown")
        text += self._format_setting_line("roulette_min_bet")
        text += self._format_setting_line("roulette_max_bet")
        text += self._format_setting_line("ladder_min_bet")
        text += self._format_setting_line("ladder_max_bet")
        
        text += self.get_raid_settings_text() # Получаем блок настроек рейда
        
        text += "\n<b>🎲 Мафия 'Пивной Переполох':</b>\n"
        text += self._format_setting_line("mafia_min_players")
        text += self._format_setting_line("mafia_max_players")
        text += self._format_setting_line("mafia_lobby_timer")
        text += self._format_setting_line("mafia_night_timer")
        text += self._format_setting_line("mafia_day_timer")
        text += self._format_setting_line("mafia_vote_timer")
        text += self._format_setting_line("mafia_win_reward")
        text += self._format_setting_line("mafia_lose_reward")
        text += self._format_setting_line("mafia_win_authority")
        text += self._format_setting_line("mafia_lose_authority")

        return text

    def get_raid_settings_text(self) -> str:
        """Возвращает отформатированный текст только для настроек Рейда."""
        text = "\n<b>👹 Ивент 'Вышибала' (Рейд):</b>\n"
        text += self._format_setting_line("raid_boss_health")
        text += self._format_setting_line("raid_reward_pool")
        text += self._format_setting_line("raid_duration_hours")
        text += self._format_setting_line("raid_hit_cooldown_minutes")
        text += self._format_setting_line("raid_normal_hit_damage_min")
        text += self._format_setting_line("raid_normal_hit_damage_max")
        text += self._format_setting_line("raid_strong_hit_cost")
        text += self._format_setting_line("raid_strong_hit_damage_min")
        text += self._format_setting_line("raid_strong_hit_damage_max")
        text += self._format_setting_line("raid_reminder_hours")
        return text
