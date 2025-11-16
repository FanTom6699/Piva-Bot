# handlers/farm_config.py
import random # ✅ НОВЫЙ ИМПОРТ

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

# --- Магазин (Твой сбалансированный) ---
SHOP_PRICES = {
    'семя_зерна': 1, 
    'семя_хмеля': 3, 
}
# (Себестоимость 1 варки: (5*1) + (3*3) = 14 🍺)
# --- ---

# --- ✅ СБАЛАНСИРОВАННЫЕ УЛУЧШЕНИЯ ПОЛЯ ✅ ---
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

# --- ✅ СБАЛАНСИРОВАННЫЕ УЛУЧШЕНИЯ ПИВОВАРНИ ✅ ---
BREWERY_UPGRADES = {
    # Lvl: {cost, time_h, reward, brew_time_min}
    1:     {'cost': 0,     'time_h': 0, 'reward': 35, 'brew_time_min': 30},
    2:     {'cost': 100,   'time_h': 1, 'reward': 40, 'brew_time_min': 25}, 
    3:     {'cost': 250,   'time_h': 2, 'reward': 48, 'brew_time_min': 20},
    4:     {'cost': 500,   'time_h': 3, 'reward': 55, 'brew_time_min': 18},
    5:     {'cost': 1000,  'time_h': 4, 'reward': 65, 'brew_time_min': 15},
    6:     {'cost': 2000,  'time_h': 5, 'reward': 75, 'brew_time_min': 12},
    7:     {'cost': 4000,  'time_h': 6, 'reward': 90, 'brew_time_min': 10},
    8:     {'cost': 7000,  'time_h': 8, 'reward': 110, 'brew_time_min': 8},
    9:     {'cost': 11000, 'time_h': 10,'reward': 130, 'brew_time_min': 6},
    10:    {'cost': 18000, 'time_h': 12,'reward': 150, 'brew_time_min': 5},
}
# --- --- ---

# --- ФУНКЦИЯ ДЛЯ УЛУЧШЕНИЙ ---
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

# --- ✅✅✅ НОВЫЙ КОД: ДОСКА ЗАКАЗОВ ✅✅✅ ---
# Пул всех заданий, из которых бот будет выбирать 3.
FARM_ORDER_POOL = {
    # (Заказы на Зерно)
    'grain_10': {
        'text': "Нужно 10 🌾 Зерна на закуску", 
        'item_id': 'зерно', 'item_amount': 10, 
        'reward_type': 'beer', 'reward_amount': 30
    },
    'grain_25': {
        'text': "Заказ на 25 🌾 Зерна", 
        'item_id': 'зерно', 'item_amount': 25, 
        'reward_type': 'beer', 'reward_amount': 80
    },
    'grain_50': {
        'text': "Крупная поставка: 50 🌾 Зерна", 
        'item_id': 'зерно', 'item_amount': 50, 
        'reward_type': 'beer', 'reward_amount': 175
    },
    
    # (Заказы на Хмель)
    'hops_10': {
        'text': "Нужно 10 🌱 Хмеля для аромата", 
        'item_id': 'хмель', 'item_amount': 10, 
        'reward_type': 'beer', 'reward_amount': 50
    },
    'hops_25': {
        'text': "Заказ на 25 🌱 Хмеля", 
        'item_id': 'хмель', 'item_amount': 25, 
        'reward_type': 'beer', 'reward_amount': 130
    },
    'hops_50': {
        'text': "Крупная поставка: 50 🌱 Хмеля", 
        'item_id': 'хмель', 'item_amount': 50, 
        'reward_type': 'beer', 'reward_amount': 280
    },
    
    # (Заказы на Семена - награда 🍺)
    'seed_g_5': {
        'text': "Нужны 5 Семян 🌾 Зерна", 
        'item_id': 'семя_зерна', 'item_amount': 5, 
        'reward_type': 'beer', 'reward_amount': 20
    },
    'seed_h_3': {
        'text': "Нужны 3 Семя 🌱 Хмеля", 
        'item_id': 'семя_хмеля', 'item_amount': 3, 
        'reward_type': 'beer', 'reward_amount': 30
    },
    
    # (Обмен Зерна на Семена Хмеля)
    'trade_g_h': {
        'text': "Обмен: 30 🌾 Зерна на Семена", 
        'item_id': 'зерно', 'item_amount': 30, 
        'reward_type': 'item', 'reward_id': 'семя_хмеля', 'reward_amount': 2
    },
    # (Обмен Хмеля на Семена Зерна)
    'trade_h_g': {
        'text': "Обмен: 15 🌱 Хмеля на Семена", 
        'item_id': 'хмель', 'item_amount': 15, 
        'reward_type': 'item', 'reward_id': 'семя_зерна', 'reward_amount': 5
    }
}

def get_random_orders(count=3) -> list:
    """Возвращает N случайных ID заказов из пула."""
    all_order_keys = list(FARM_ORDER_POOL.keys())
    if len(all_order_keys) < count:
        return all_order_keys 
    return random.sample(all_order_keys, count)
# --- --- ---
