import logging
import random
import time

from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher.filters.builtin import CommandStart

from config import TOKEN, BEER_COOLDOWN, RATING_CHANGE
import db_manager as db

# Настройка логирования
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Инициализация бота и диспетчера
bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# --- Обработчики команд ---

@dp.message_handler(CommandStart())
async def cmd_start(message: types.Message):
    """Обработчик команды /start."""
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.full_name
    await db.add_new_user(user_id, username)
    await message.reply(
        "Привет! Я твой Пиво-бот. Набери /beer, чтобы попытать удачу, или /top, чтобы увидеть лучших игроков!"
    )

@dp.message_handler(commands=['beer'])
async def cmd_beer(message: types.Message):
    """Обработчик команды /beer."""
    user_id = message.from_user.id
    user = await db.get_user(user_id)

    if not user:
        await db.add_new_user(user_id, message.from_user.username or message.from_user.full_name)
        user = await db.get_user(user_id) # Снова получаем пользователя после добавления

    if user: # Проверяем, что пользователь существует
        _, _, current_rating, last_beer_time = user
        current_time = int(time.time())
        
        if current_time - last_beer_time < BEER_COOLDOWN:
            remaining_time = BEER_COOLDOWN - (current_time - last_beer_time)
            hours = remaining_time // 3600
            minutes = (remaining_time % 3600) // 60
            await message.reply(
                f"🤬🍻 Ты уже бахнул пива! Следующую попытку можно сделать через {hours} ч. {minutes} мин."
            )
        else:
            change = random.randint(1, RATING_CHANGE)
            if random.choice([True, False]): # 50% шанс на успех
                new_rating = current_rating + change
                response = f"😏🍻 Ты успешно бахнул! Твой рейтинг вырос на +{change}. Текущий рейтинг: {new_rating}."
            else:
                new_rating = current_rating - change
                response = f"🤬🍻 Братья Уизли отжали твоё пиво! Твой рейтинг упал на -{change}. Текущий рейтинг: {new_rating}."

            await db.update_user_data(user_id, new_rating, current_time)
            await message.reply(response)
    else:
        await message.reply("Произошла ошибка при получении данных пользователя. Попробуйте снова или свяжитесь с администратором.")
        logger.error(f"User {user_id} not found after add_new_user attempt.")


@dp.message_handler(commands=['top'])
async def cmd_top(message: types.Message):
    """Обработчик команды /top."""
    top_users = await db.get_top_users()
    if not top_users:
        await message.reply("Список игроков пока пуст.")
        return

    top_list = "🏆 **Топ-10 самых крутых пивных богов:** 🏆\n\n"
    for i, user_data in enumerate(top_users, 1):
        username, rating = user_data
        top_list += f"{i}. {username} — {rating} 🍻\n"

    await message.reply(top_list, parse_mode='Markdown')

# --- Запуск бота ---

async def on_startup(dp):
    """Функция, выполняющаяся при старте бота."""
    logger.info("Bot is starting...")
    await db.init_db()
    logger.info("Database is ready.")

if __name__ == '__main__':
    from aiogram import executor
    executor.start_polling(dp, on_startup=on_startup, skip_updates=True)
