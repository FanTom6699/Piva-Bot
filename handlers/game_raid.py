# handlers/game_raid.py
import asyncio
import random
import time
import html # --- ДОБАВЛЕНО: для экранирования имен ---
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from database import Database
from settings import SettingsManager
from utils import format_time_delta
from handlers.common import check_user_registered

game_router = Router()

# --- ИЗМЕНЕНИЕ 1: Тематические фразы для атак ---
RAID_ATTACK_PHRASES = {
    'normal': [
        "<i>{name} кинул в Вышибалу пустой кружкой! <b>-{damage}</b> ❤️</i>",
        "<i>{name} крикнул 'Твое пиво - вода!' и нанес <b>-{damage}</b> ❤️ урона!</i>",
        "<i>{name} ловко пнул Вышибалу под колено! <b>-{damage}</b> ❤️</i>"
    ],
    'strong': [
        "<i>{name} опрокинул на Вышибалу целый бочонок! <b>-{damage}</b> ❤️</i>",
        "<i>{name} разбил об Вышибалу барный стул! Мощно! <b>-{damage}</b> ❤️</i>",
        "<i>{name} провел серию ударов 'пьяного мастера'! <b>-{damage}</b> ❤️</i>"
    ],
    'fail': [
        "<i>{name} попытался ударить, но промахнулся...</i>",
        "<i>{name} замахнулся, но Вышибала поймал его за руку!</i>",
        "<i>{name} споткнулся на ровном месте. Вышибала смеется...</i>"
    ]
}
# --- КОНЕЦ ИЗМЕНЕНИЯ 1 ---

# Словарь для хранения активных рейдов {chat_id: Raid}
active_raids = {}
raid_tasks = {} # {chat_id: asyncio.Task}

class Raid:
    def __init__(self, chat_id, settings: SettingsManager):
        self.chat_id = chat_id
        self.max_health = random.randint(settings.raid_boss_min_hp, settings.raid_boss_max_hp)
        self.current_health = self.max_health
        self.reward = random.randint(settings.raid_reward_min, settings.raid_reward_max)
        self.duration = settings.raid_duration
        self.start_time = int(time.time())
        self.participants = set() # Храним user_id
        self.message_id = None
        self.lock = asyncio.Lock()
        self.last_attackers = [] # (user_name, text)

    @property
    def is_active(self):
        return self.current_health > 0 and (time.time() - self.start_time) < self.duration

    def add_attacker_log(self, name, text):
        safe_name = html.escape(name)
        self.last_attackers.append((safe_name, text))
        if len(self.last_attackers) > 5:
            self.last_attackers.pop(0)

# --- КОМАНДА ЗАПУСКА РЕЙДА (АДМИН) ---
@game_router.message(Command("raid"))
async def cmd_raid(message: Message, bot: Bot, db: Database, settings: SettingsManager):
    if message.chat.type == "private":
        return await message.answer("❌ Рейды можно запускать только в группах.")
    if not await db.is_admin(message.from_user.id):
        return await message.answer("⛔ Эту команду могут использовать только администраторы бота.")
    
    chat_id = message.chat.id
    if chat_id in active_raids and active_raids[chat_id].is_active:
        return await message.answer("🔥 Рейд уже идет!")

    # Проверка глобального кулдауна
    last_raid_time = await db.get_last_raid_time(chat_id)
    cooldown = settings.raid_global_cooldown
    current_time = int(time.time())
    
    if last_raid_time and (current_time - last_raid_time) < cooldown:
        remaining = cooldown - (current_time - last_raid_time)
        # --- ИЗМЕНЕНИЕ 2: Текст кулдауна рейда (тематический) ---
        return await message.answer(f"🍻 Бар еще не отошел от прошлого рейда!\nНовый 'Вышибала' появится через: {format_time_delta(remaining)}.")
        # --- КОНЕЦ ИЗМЕНЕНИЯ 2 ---

    raid = Raid(chat_id, settings)
    active_raids[chat_id] = raid
    await db.set_last_raid_time(chat_id, current_time)

    raid_message = await message.answer(
        generate_raid_message(raid),
        reply_markup=generate_raid_keyboard(raid, settings),
        parse_mode='HTML'
    )
    raid.message_id = raid_message.message_id
    
    # Запускаем таск, который будет обновлять сообщение и завершит рейд
    raid_tasks[chat_id] = asyncio.create_task(
        raid_updater(bot, db, raid, settings)
    )

# --- ГЕНЕРАЦИЯ ГЛАВНОГО СООБЩЕНИЯ РЕЙДА ---
def generate_raid_message(raid: Raid) -> str:
    health_percent = (raid.current_health / raid.max_health) * 100
    health_bar = "█" * int(health_percent / 10) + "░" * (10 - int(health_percent / 10))
    
    health = raid.current_health
    if health < 0: health = 0
    
    time_left = raid.start_time + raid.duration - int(time.time())
    time_str = format_time_delta(time_left) if time_left > 0 else "0 сек"

    attack_log = "\n".join(f"• {name}: {text}" for name, text in raid.last_attackers)
    if not attack_log:
        attack_log = "<i>(Пока никто не рискнул...)</i>"

    # --- ИЗМЕНЕНИЕ 3: Главный текст рейда (атмосфера + мотивация) ---
    text = (
        f"🚨 <b>ВЫШИБАЛА В БАРЕ!</b> 🚨\n\n"
        f"Этот громила <b>не пускает никого к стойке!</b> Нужно разобраться с ним всем вместе!\n\n"
        f"❤️ <b>Здоровье:</b> <code>{health_bar}</code>\n"
        f"({health} / {raid.max_health})\n\n"
        f"💰 <b>Общая награда:</b> <b>{raid.reward} 🍺</b>\n"
        f"⏳ <b>Уйдет сам через:</b> <b>{time_str}</b>\n\n"
        f"<b>Последние события:</b>\n{attack_log}"
    )
    # --- КОНЕЦ ИЗМЕНЕНИЯ 3 ---
    return text

# --- ГЕНЕРАЦИЯ КНОПОК РЕЙДА ---
def generate_raid_keyboard(raid: Raid, settings: SettingsManager) -> InlineKeyboardMarkup:
    # --- ИЗМЕНЕНИЕ 4: Текст кнопок (тематический) ---
    buttons = [
        [
            InlineKeyboardButton(text="💥 Кинуть кружкой (Беспл.)", callback_data="raid_attack_normal"),
            InlineKeyboardButton(text=f"🪑 Ударить стулом ({settings.raid_strong_attack_cost} 🍺)", callback_data="raid_attack_strong")
        ],
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="raid_refresh")]
    ]
    # --- КОНЕЦ ИЗМЕНЕНИЯ 4 ---
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# --- ТАСК ОБНОВЛЕНИЯ РЕЙДА ---
async def raid_updater(bot: Bot, db: Database, raid: Raid, settings: SettingsManager):
    update_interval = 15 # Обновляем сообщение каждые 15 сек
    end_time = raid.start_time + raid.duration
    
    while raid.is_active:
        await asyncio.sleep(update_interval)
        if not raid.is_active: break # Могли убить до таймера
        
        try:
            await bot.edit_message_text(
                chat_id=raid.chat_id,
                message_id=raid.message_id,
                text=generate_raid_message(raid),
                reply_markup=generate_raid_keyboard(raid, settings),
                parse_mode='HTML'
            )
        except Exception:
            pass # Ошибки (удаленное сообщение и т.д.)

    # Рейд завершен
    if raid.chat_id in active_raids:
        del active_raids[raid.chat_id]
    if raid.chat_id in raid_tasks:
        del raid_tasks[raid.chat_id]
        
    await check_raid_status(bot, db, raid)

# --- ПРОВЕРКА СТАТУСА (ПОБЕДА/ПОРАЖЕНИЕ) ---
async def check_raid_status(bot: Bot, db: Database, raid: Raid):
    if raid.current_health <= 0:
        # Победа
        reward_per_user = 0
        if raid.participants:
            reward_per_user = raid.reward // len(raid.participants)
            
        winners_list = []
        for user_id in raid.participants:
            await db.update_user_beer_rating(user_id, reward_per_user)
            try:
                # Пытаемся получить имя, но если юзер вышел - не страшно
                user = await bot.get_chat_member(raid.chat_id, user_id)
                winners_list.append(html.escape(user.user.full_name))
            except Exception:
                winners_list.append(f"Игрок (ID: {user_id})")
        
        # --- ИЗМЕНЕНИЕ 5: Текст победы (тематический) ---
        text = (
            f"🏆 <b>ПОБЕДА!</b> 🏆\n\n"
            f"Вышибала повержен! <b>Путь к бару свободен!</b>\n\n"
            f"Все, кто участвовал в 'убеждении', делят <b>{raid.reward} 🍺</b> (по <b>{reward_per_user} 🍺</b> каждому).\n\n"
            f"<b>Герои дня:</b>\n" + "\n".join(f"• {name}" for name in winners_list)
        )
        # --- КОНЕЦ ИЗМЕНЕНИЯ 5 ---
        
    else:
        # Поражение
        # --- ИЗМЕНЕНИЕ 6: Текст поражения (тематический) ---
        text = (
            f"⌛ <b>ВЫШИБАЛА УШЕЛ!</b> ⌛\n\n"
            f"Время вышло. Вышибала отряхнулся, хмыкнул и ушел сам...\n"
            f"Награда (<b>{raid.reward} 🍺</b>) никому не достается.\n\n"
            f"<i>В следующий раз бейте сильнее!</i>"
        )
        # --- КОНЕЦ ИЗМЕНЕНИЯ 6 ---

    try:
        await bot.edit_message_text(
            chat_id=raid.chat_id,
            message_id=raid.message_id,
            text=text,
            reply_markup=None,
            parse_mode='HTML'
        )
    except Exception:
        pass # Сообщение могло быть удалено

# --- ОБРАБОТЧИК КНОПОК РЕЙДА ---
@game_router.callback_query(F.data.startswith("raid_"))
async def raid_button_callback(callback: CallbackQuery, bot: Bot, db: Database, settings: SettingsManager):
    chat_id = callback.message.chat.id
    if chat_id not in active_raids:
        return await callback.answer("❌ Этот рейд уже закончился!", show_alert=True)
    
    raid = active_raids[chat_id]
    if not raid.is_active:
        return await callback.answer("❌ Этот рейд уже закончился!", show_alert=True)
        
    if callback.data == "raid_refresh":
        # Просто обновляем сообщение (защита от спама)
        await callback.answer()
        try:
            return await callback.message.edit_text(
                generate_raid_message(raid),
                reply_markup=generate_raid_keyboard(raid, settings),
                parse_mode='HTML'
            )
        except Exception:
            return # Не удалось обновить (обычно из-за "Message is not modified")

    # --- ЛОГИКА АТАКИ ---
    if not await check_user_registered(callback, bot, db):
        return

    user_id = callback.from_user.id
    current_time = int(time.time())
    
    # Кулдаун атаки
    last_attack_time = await db.get_user_last_raid_attack(user_id, raid.chat_id)
    cooldown = settings.raid_attack_cooldown
    if last_attack_time and (current_time - last_attack_time) < cooldown:
        remaining = cooldown - (current_time - last_attack_time)
        return await callback.answer(f"Ты пока отдыхаешь... Повторная атака через {remaining} сек.", show_alert=True)

    await db.set_user_last_raid_attack(user_id, raid.chat_id, current_time)

    # Выбор атаки
    if callback.data == "raid_attack_normal":
        damage = random.randint(settings.raid_normal_attack_min, settings.raid_normal_attack_max)
        attack_text = random.choice(RAID_ATTACK_PHRASES['normal']).format(name="{name}", damage=damage)
    
    elif callback.data == "raid_attack_strong":
        cost = settings.raid_strong_attack_cost
        user_rating = await db.get_user_beer_rating(user_id)
        if user_rating < cost:
            return await callback.answer(f"Не хватает 'пива' на 'удар стулом'! Нужно {cost} 🍺.", show_alert=True)
        
        await db.update_user_beer_rating(user_id, -cost)
        damage = random.randint(settings.raid_strong_attack_min, settings.raid_strong_attack_max)
        attack_text = random.choice(RAID_ATTACK_PHRASES['strong']).format(name="{name}", damage=damage)
    
    else:
        return await callback.answer() # Неизвестная кнопка

    # Шанс промаха
    if random.random() < settings.raid_attack_miss_chance:
        damage = 0
        attack_text = random.choice(RAID_ATTACK_PHRASES['fail']).format(name="{name}")
        await callback.answer("Промах!", show_alert=False)
    else:
        await callback.answer(f"Удар! {damage} урона!", show_alert=False)

    async with raid.lock:
        if not raid.is_active: return # Проверяем еще раз, вдруг убили пока ждали lock
        
        raid.current_health -= damage
        raid.participants.add(user_id)
        raid.add_attacker_log(callback.from_user.full_name, attack_text.format(name="", damage=damage).strip()) # Лог без имени

        if raid.current_health <= 0:
            # Юзер нанес победный удар! Немедленно завершаем.
            if raid_tasks.get(chat_id):
                raid_tasks[chat_id].cancel()
            await check_raid_status(bot, db, raid) # Запускаем завершение
            if chat_id in active_raids: del active_raids[chat_id]
            if chat_id in raid_tasks: del raid_tasks[chat_id]
        else:
            # Обновляем сообщение (если не убили)
            try:
                await callback.message.edit_text(
                    generate_raid_message(raid),
                    reply_markup=generate_raid_keyboard(raid, settings),
                    parse_mode='HTML'
                )
            except Exception:
                pass # "Message is not modified"
