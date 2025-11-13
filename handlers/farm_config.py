# handlers/farm_config.py

# --- КОДЫ ДЛЯ CALLBACK (Фикс 64 байт) ---
CROP_CODE_TO_ID = {
    "g": "семя_зерна", # g = grain (зерно)
    "h": "семя_хмеля", # h = hops (хмель)
}

# --- Короткие имена для UI ---
CROP_SHORT = {
    'зерно': "🌾 Зерно",
    'хмель': "🌱 Хмель",
}

# --- НАЗВАНИЯ ПРЕДМЕТОВ ---
FARM_ITEM_NAMES = {
    # Ресурсы
    'зерно': "🌾 Зерно",
    'хмель': "🌱 Хмель",
    
    # Семена
    'семя_зерна': "Семена 🌾 Зерна",
    'семя_хмеля': "Семена 🌱 Хмеля",
}

# --- ID Продукта -> ID Семени (Обратный словарь) ---
PRODUCT_TO_SEED_ID = {
    'зерно': 'семя_зерна',
    'хмель': 'семя_хмеля',
}

# --- ID Семени -> ID Продукта (Старый словарь, но нужен для Сбора) ---
SEED_TO_PRODUCT_ID = {
    'семя_зерна': 'зерно',
    'семя_хмеля': 'хмель',
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
    # Lvl: {cost, time_h, plots, chance_x2, grow_time_min: {зерно, хмель}}
    1: {'cost': 0,     'time_h': 0, 'plots': 2, 'chance_x2': 0,  'grow_time_min': {'зерно': 20, 'хмель': 40}},
    2: {'cost': 100,   'time_h': 1, 'plots': 2, 'chance_x2': 5,  'grow_time_min': {'зерно': 20, 'хмель': 40}},
    3: {'cost': 250,   'time_h': 2, 'plots': 3, 'chance_x2': 5,  'grow_time_min': {'зерно': 18, 'хмель': 35}}, 
    4: {'cost': 500,   'time_h': 3, 'plots': 3, 'chance_x2': 10, 'grow_time_min': {'зерно': 18, 'хмель': 35}},
    5: {'cost': 1000,  'time_h': 4, 'plots': 4, 'chance_x2': 10, 'grow_time_min': {'зерно': 15, 'хмель': 30}}, 
    6: {'cost': 2000,  'time_h': 5, 'plots': 4, 'chance_x2': 15, 'grow_time_min': {'зерно': 15, 'хмель': 30}},
    7: {'cost': 4000,  'time_h': 6, 'plots': 5, 'chance_x2': 15, 'grow_time_min': {'зерно': 12, 'хмель': 25}}, 
    8: {'cost': 7000,  'time_h': 8, 'plots': 5, 'chance_x2': 20, 'grow_time_min': {'зерно': 12, 'хмель': 25}},
    9: {'cost': 10000, 'time_h': 10, 'plots': 6, 'chance_x2': 25, 'grow_time_min': {'зерно': 10, 'хмель': 20}}, 
    10:{'cost': 15000, 'time_h': 12, 'plots': 6, 'chance_x2': 35, 'grow_time_min': {'зерно': 10, 'хмель': 20}},
}

# --- ✅✅✅ (Piva Bot) ВОЗВРАЩАЕМ ТАЙМЕР (30 мин) ✅✅✅ ---
BREWERY_UPGRADES = {
    # Lvl: {cost, time_h, reward, brew_time_min}
    1:     {'cost': 0,     'time_h': 0, 'reward': 35, 'brew_time_min': 30},
    2:     {'cost': 150,   'time_h': 1, 'reward': 37, 'brew_time_min': 30},
    3:     {'cost': 300,   'time_h': 2, 'reward': 40, 'brew_time_min': 25},
    4:     {'cost': 600,   'time_h': 3, 'reward': 43, 'brew_time_min': 25},
    5:     {'cost': 1200,  'time_h': 4, 'reward': 45, 'brew_time_min': 20},
    6:     {'cost': 2500,  'time_h': 5, 'reward': 48, 'brew_time_min': 20},
    7:     {'cost': 5000,  'time_h': 6, 'reward': 52, 'brew_time_min': 15},
    8:     {'cost': 8000,  'time_h': 8, 'reward': 56, 'brew_time_min': 15},
    9:     {'cost': 12000, 'time_h': 10, 'reward': 60, 'brew_time_min': 10},
    10:    {'cost': 20000, 'time_h': 12, 'reward': 70, 'brew_time_min': 10},
}
# --- --- ---

# --- ФУНКЦИЯ ДЛЯ УЛУЧШЕНИЙ ---
# (Piva Bot: ФИКС, чтобы не падал на Уровне 11+)
def get_level_data(level: int, upgrade_data: dict) -> dict:
    data = upgrade_data.get(level, {}).copy() 
    
    max_level_num = max(upgrade_data.keys())
    
    data['max_level'] = (level == max_level_num)
    
    if not data and level > max_level_num:
        data = upgrade_data.get(max_level_num, {}).copy()
        data['max_level'] = True

    if not data.get('max_level', False):
        next_level_data = upgrade_data.get(level + 1, {})
        data['next_cost'] = next_level_data.get('cost')
        data['next_time_h'] = next_level_data.get('time_h')
    
    return data
