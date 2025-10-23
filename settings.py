# settings.py
import logging
from database import Database

class SettingsManager:
    def __init__(self):
        # Значения по умолчанию, если в БД ничего нет
        self.beer_cooldown = 7200
        self.jackpot_chance = 150
        self.roulette_cooldown = 600
        self.roulette_min_bet = 5
        self.roulette_max_bet = 100
        self.ladder_min_bet = 5
        self.ladder_max_bet = 100

    async def load_settings(self, db: Database):
        logging.info("Загрузка настроек из БД...")
        try:
            settings_from_db = await db.get_all_settings()
            # Обновляем атрибуты класса, используя значения из БД
            for key, value in settings_from_db.items():
                if hasattr(self, key):
                    setattr(self, key, value)
            logging.info("Настройки успешно загружены.")
        except Exception as e:
            logging.error(f"Ошибка при загрузке настроек: {e}. Используются значения по умолчанию.")

    async def reload_setting(self, db: Database, key: str):
        try:
            value = await db.get_setting(key)
            if value is not None and hasattr(self, key):
                setattr(self, key, value)
                logging.info(f"Настройка '{key}' обновлена на {value}")
        except Exception as e:
            logging.error(f"Ошибка при перезагрузке настройки '{key}': {e}")
            
    def get_all_settings_text(self) -> str:
        # Собираем все текущие настройки в красивый текст
        return (
            f"<b>⚙️ Текущие настройки бота:</b>\n\n"
            f"<b>Игра: /beer</b>\n"
            f"  • Кулдаун: <code>{self.beer_cooldown}</code> сек\n"
            f"  • Шанс джекпота: <code>1 к {self.jackpot_chance}</code>\n\n"
            f"<b>Игра: Рулетка</b>\n"
            f"  • Кулдаун: <code>{self.roulette_cooldown}</code> сек\n"
            f"  • Мин. ставка: <code>{self.roulette_min_bet}</code> 🍺\n"
            f"  • Макс. ставка: <code>{self.roulette_max_bet}</code> 🍺\n\n"
            f"<b>Игра: Лесенка</b>\n"
            f"  • Мин. ставка: <code>{self.ladder_min_bet}</code> 🍺\n"
            f"  • Макс. ставка: <code>{self.ladder_max_bet}</code> 🍺"
        )

# Создаем единый экземпляр менеджера
settings_manager = SettingsManager()
