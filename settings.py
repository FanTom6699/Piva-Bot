# settings.py
import logging

class SettingsManager:
    # --- ЗНАЧЕНИЯ ПО УМОЛЧАНИЮ ---
    # Общие
    beer_cooldown: int = 7200
    jackpot_chance: int = 100
    
    # Рулетка
    roulette_cooldown: int = 300
    roulette_min_bet: int = 10
    roulette_max_bet: int = 1000
    
    # Лесенка
    ladder_min_bet: int = 10
    ladder_max_bet: int = 1000
    
    # Рейд
    raid_boss_health: int = 5000
    raid_reward_pool: int = 10000
    raid_duration_hours: int = 24
    raid_hit_cooldown_minutes: int = 60
    raid_strong_hit_cost: int = 100
    raid_strong_hit_damage_min: int = 150
    raid_strong_hit_damage_max: int = 300
    raid_normal_hit_damage_min: int = 10
    raid_normal_hit_damage_max: int = 50
    raid_reminder_hours: int = 6
    
    def __init__(self, db):
        self.db = db
        logging.info("Менеджер настроек инициализирован.")

    async def load_settings(self):
        """Загружает все настройки из БД."""
        logging.info("Загрузка настроек из БД...")
        settings_data = await self.db.get_all_settings()
        for key, value in settings_data:
            if hasattr(self, key):
                try:
                    setattr(self, key, int(value))
                except ValueError:
                    logging.warning(f"Не удалось загрузить настройку {key}: неверный тип значения {value}.")
        logging.info("Настройки успешно загружены.")
        
    async def reload_setting(self, db, key: str):
        """Перезагружает одну настройку из БД."""
        value = await db.get_setting(key)
        if value is not None:
            if hasattr(self, key):
                setattr(self, key, int(value))
                logging.info(f"Настройка '{key}' перезагружена. Новое значение: {value}")
        
    def get_all_settings_text(self) -> str:
        """Возвращает форматированный текст текущих настроек (старая версия)."""
        return (
            f"<b>⚙️ Текущие настройки:</b>\n\n"
            f"<b>/beer:</b>\n"
            f"  Кулдаун: {self.beer_cooldown} сек.\n"
            f"  Шанс джекпота: 1 к {self.jackpot_chance}\n\n"
            f"<b>Рулетка:</b>\n"
            f"  Кулдаун: {self.roulette_cooldown} сек.\n"
            f"  Мин. ставка: {self.roulette_min_bet} 🍺\n"
            f"  Макс. ставка: {self.roulette_max_bet} 🍺\n\n"
            f"<b>Лесенка:</b>\n"
            f"  Мин. ставка: {self.ladder_min_bet} 🍺\n"
            f"  Макс. ставка: {self.ladder_max_bet} 🍺\n"
        )
        
    def get_raid_settings_text(self) -> str:
        """Возвращает текст настроек Рейда."""
        return (
            f"<b>👹 Настройки Рейд-Босса:</b>\n\n"
            f"Здоровье: {self.raid_boss_health} ❤️\n"
            f"Награда: {self.raid_reward_pool} 🍺\n"
            f"Длительность: {self.raid_duration_hours} ч.\n"
            f"КД удара: {self.raid_hit_cooldown_minutes} мин.\n"
            f"Цена сильного удара: {self.raid_strong_hit_cost} 🍺\n"
            f"Урон (сильный): {self.raid_strong_hit_damage_min}-{self.raid_strong_hit_damage_max}\n"
            f"Урон (обычный): {self.raid_normal_hit_damage_min}-{self.raid_normal_hit_damage_max}\n"
        )
