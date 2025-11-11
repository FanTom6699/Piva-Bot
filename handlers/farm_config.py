# handlers/farm_config.py

# --- КОДЫ ДЛЯ CALLBACK (Фикс 64 байт) ---
CROP_CODE_TO_ID = {
    "g": "семя_зерна",
    "h": "семя_хмеля",
}

# --- КОРОТКИЕ ИМЕНА ПРОДУКТОВ ---
CROP_SHORT = {
    "зерно": "🌾 Зерно",
    "хмель": "🌱 Хмель",
}

# --- НАЗВАНИЯ ПРЕДМЕТОВ ---
FARM_ITEM_NAMES = {
    "зерно": "🌾 Зерно",
    "хмель": "🌱 Хмель",

    "семя_зерна": "Семена 🌾 Зерна",
    "семя_хмеля": "Семена 🌱 Хмеля",
}

# =============================
#   ⏱ ВРЕМЯ ВЫРАЩИВАНИЯ (V2)
# =============================

# Время по уровню поля
FIELD_GROW_TIME = {
    1: 20,
    2: 15,
    3: 12,
    4: 10,
    5: 8,
    6: 5,
}

# Базовые культуры → что вырастает
PLANT_IO = {
    "семя_зерна": ("зерно"),
    "семя_хмеля": ("хмель"),
}

# --- ПИВОВАРНЯ ---
BREWERY_RECIPE = {
    "зерно": 5,
    "хмель": 3,
}

# Магазин
SHOP_PRICES = {
    "семя_зерна": 2,
    "семя_хмеля": 5,
}

# --- УЛУЧШЕНИЯ ---
FIELD_UPGRADES = {
    1:  {'cost': 0,     'time_h': 0, 'plots': 2, 'chance_x2': 0},
    2:  {'cost': 100,   'time_h': 1, 'plots': 2, 'chance_x2': 5},
    3:  {'cost': 250,   'time_h': 2, 'plots': 3, 'chance_x2': 5},
    4:  {'cost': 500,   'time_h': 3, 'plots': 3, 'chance_x2': 10},
    5:  {'cost': 1000,  'time_h': 4, 'plots': 4, 'chance_x2': 10},
    6:  {'cost': 2000,  'time_h': 5, 'plots': 4, 'chance_x2': 15},
    7:  {'cost': 4000,  'time_h': 6, 'plots': 5, 'chance_x2': 15},
    8:  {'cost': 7000,  'time_h': 8, 'plots': 5, 'chance_x2': 20},
    9:  {'cost': 10000, 'time_h': 10,'plots': 6, 'chance_x2': 25},
    10: {'cost': 15000, 'time_h': 12,'plots': 6, 'chance_x2': 35},
}

BREWERY_UPGRADES = {
    1:  {'cost': 0,     'time_h': 0,  'reward': 10, 'brew_time_min': 3},
    2:  {'cost': 150,   'time_h': 1,  'reward': 11, 'brew_time_min': 3},
    3:  {'cost': 300,   'time_h': 2,  'reward': 12, 'brew_time_min': 2},
    4:  {'cost': 600,   'time_h': 3,  'reward': 13, 'brew_time_min': 2},
    5:  {'cost': 1200,  'time_h': 4,  'reward': 15, 'brew_time_min': 1},
    6:  {'cost': 2500,  'time_h': 5,  'reward': 17, 'brew_time_min': 1},
    7:  {'cost': 5000,  'time_h': 6,  'reward': 20, 'brew_time_min': 1},
    8:  {'cost': 8000,  'time_h': 8,  'reward': 23, 'brew_time_min': 1},
    9:  {'cost': 12000, 'time_h': 10, 'reward': 27, 'brew_time_min': 1},
    10: {'cost': 20000, 'time_h': 12, 'reward': 35, 'brew_time_min': 1},
}

# --- Утилита ---
def get_level_data(level: int, upgrade_data: dict) -> dict:
    data = upgrade_data.get(level, {})
    data['max_level'] = (level == max(upgrade_data.keys()))
    if not data['max_level']:
        next_data = upgrade_data.get(level + 1, {})
        data['next_cost'] = next_data.get('cost')
        data['next_time_h'] = next_data.get('time_h')
    return data
