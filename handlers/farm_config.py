# handlers/farm_config.py

# --- КОДЫ ДЛЯ CALLBACK (Фикс 64 байт) ---
CROP_CODE_TO_ID = {
    "g": "семя_зерна", # g = grain (зерно)
    "h": "семя_хмеля", # h = hops (хмель)
}

# --- ✅ ФИКС: Полные имена ---
CROP_SHORT = {
    'зерно': "🌾 Зерно", # (Было: 🌾 ЗРН)
    'хмель': "🌱 Хмель", # (Было: 🌱 ХМЛ)
}

# --- ✅ ФИКС: Полные имена ---
FARM_ITEM_NAMES = {
    # Ресурсы
    'зерно': "🌾 Зерно", # (Было: 🌾 ЗРН)
    'хмель': "🌱 Хмель", # (Было: 🌱 ХМЛ)
    
    # Семена
    'семя_зерна': "Семена 🌾 Зерна",
    'семя_хмеля': "Семена 🌱 Хмеля",
}

# --- ПОСАДКА: ID Семени -> [ID Продукта, Время роста в минутах] ---
PLANT_IO = {
    'семя_зерна': ['зерно', 5],  # (Твой таймер: 5 мин)
    'семя_хмеля': ['хмель', 10], # (Твой таймер: 10 мин)
}

# --- ПИВОВАРНЯ: ID Ресурса -> Количество для 1 варки ---
BREWERY_RECIPE = {
    'зерно': 5,
    'хмель': 3,
}

# --- МАГАЗИН: ID Семени -> Цена в 🍺 ---
SHOP_PRICES = {
    'семя_зерна': 2,
    'семя_хмеля': 5,
}

# --- УЛУЧШЕНИЯ: ПОЛЕ ---
FIELD_UPGRADES = {
    # Lvl: {cost, time_h, plots, chance_x2}
    1:     {'cost': 0,     'time_h': 0, 'plots': 2, 'chance_x2': 0},
    2:     {'cost': 100,   'time_h': 1, 'plots': 2, 'chance_x2': 5},
    3:     {'cost': 250,   'time_h': 2, 'plots': 3, 'chance_x2': 5},
    4:     {'cost': 500,   'time_h': 3, 'plots': 3, 'chance_x2': 10},
    5:     {'cost': 1000,  'time_h': 4, 'plots': 4, 'chance_x2': 10},
    6:     {'cost': 2000,  'time_h': 5, 'plots': 4, 'chance_x2': 15},
    7:     {'cost': 4000,  'time_h': 6, 'plots': 5, 'chance_x2': 15},
    8:     {'cost': 7000,  'time_h': 8, 'plots': 5, 'chance_x2': 20},
    9:     {'cost': 10000, 'time_h': 10, 'plots': 6, 'chance_x2': 25},
    10:    {'cost': 15000, 'time_h': 12, 'plots': 6, 'chance_x2': 35},
}

# --- "БОЕВЫЕ" ТАЙМЕРЫ ПИВОВАРНИ ---
BREWERY_UPGRADES = {
    # Lvl: {cost, time_h, reward, brew_time_min}
    1:     {'cost': 0,     'time_h': 0, 'reward': 10, 'brew_time_min': 45}, 
    2:     {'cost': 150,   'time_h': 1, 'reward': 11, 'brew_time_min': 40}, 
    3:     {'cost': 300,   'time_h': 2, 'reward': 12, 'brew_time_min': 35}, 
    4:     {'cost': 600,   'time_h': 3, 'reward': 13, 'brew_time_min': 30}, 
    5:     {'cost': 1200,  'time_h': 4, 'reward': 15, 'brew_time_min': 25}, 
    6:     {'cost': 2500,  'time_h': 5, 'reward': 17, 'brew_time_min': 25}, 
    7:     {'cost': 5000,  'time_h': 6, 'reward': 20, 'brew_time_min': 20}, 
    8:     {'cost': 8000,  'time_h': 8, 'reward': 23, 'brew_time_min': 20}, 
    9:     {'cost': 12000, 'time_h': 10, 'reward': 27, 'brew_time_min': 15}, 
    10:    {'cost': 20000, 'time_h': 12, 'reward': 35, 'brew_time_min': 15}, 
}
# --- --- ---

# --- ФУНКЦИЯ ДЛЯ УЛУЧШЕНИЙ ---
def get_level_data(level: int, upgrade_data: dict) -> dict:
    data = upgrade_data.get(level, {})
    data['max_level'] = (level == max(upgrade_data.keys()))
    
    if not data['max_level']:
        next_level_data = upgrade_data.get(level + 1, {})
        data['next_cost'] = next_level_data.get('cost')
        data['next_time_h'] = next_level_data.get('time_h')
    
    return data
