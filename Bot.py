import os
import telebot
import random
import time
import sqlite3

# Получаем токен из переменных окружения
TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    raise ValueError("❌ BOT_TOKEN не найден! Установи его в переменных окружения.")

bot = telebot.TeleBot(TOKEN)

# Подключение к SQLite
conn = sqlite3.connect("beer.db", check_same_thread=False)
cursor = conn.cursor()

# Создание таблицы
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    balance INTEGER DEFAULT 0,
    last_used REAL DEFAULT 0
)
""")
conn.commit()

COOLDOWN = 3 * 60 * 60  # 3 часа

def get_user(user_id, username):
    """Получить или создать игрока"""
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    if not user:
        cursor.execute("INSERT INTO users (user_id, username, balance, last_used) VALUES (?, ?, ?, ?)",
                       (user_id, username, 0, 0))
        conn.commit()
        return (user_id, username, 0, 0)
    return user


@bot.message_handler(commands=['beer'])
def beer_game(message):
    user_id = message.from_user.id
    username = message.from_user.first_name
    now = time.time()

    user = get_user(user_id, username)
    balance = user[2]
    last_used = user[3]

    # Проверка кулдауна
    if now - last_used < COOLDOWN:
        remaining = int(COOLDOWN - (now - last_used))
        hours = remaining // 3600
        minutes = (remaining % 3600) // 60
        seconds = remaining % 60
        bot.reply_to(message, f"⏳ Жди ещё {hours:02}:{minutes:02}:{seconds:02} до следующего пива!")
        return

    # Событие
    if random.choice([True, False]):
        value = random.randint(1, 10)
        balance -= value
        text = f"🤬🍻 Братья Уизли отжали твоё пиво!\nСливочное пиво: -{value}\n📊 Баланс: {balance}"
    else:
        value = random.randint(1, 10)
        balance += value
        text = f"😏🍻 Ты успешно бахнул!\nСливочное пиво: +{value}\n📊 Баланс: {balance}"

    # Обновляем БД
    cursor.execute("UPDATE users SET balance = ?, last_used = ?, username = ? WHERE user_id = ?",
                   (balance, now, username, user_id))
    conn.commit()

    bot.reply_to(message, text)


@bot.message_handler(commands=['rating'])
def show_rating(message):
    cursor.execute("SELECT username, balance FROM users ORDER BY balance DESC LIMIT 10")
    top_players = cursor.fetchall()

    if not top_players:
        bot.reply_to(message, "📉 Пока никто не бахал пива!")
        return

    text = "🏆 ТОП-10 по пиву 🍺\n\n"
    for i, (username, balance) in enumerate(top_players, start=1):
        text += f"{i}. {username} — {balance}\n"

    bot.reply_to(message, text)


@bot.message_handler(commands=['mybeer'])
def my_beer(message):
    user_id = message.from_user.id
    username = message.from_user.first_name
    user = get_user(user_id, username)
    balance = user[2]

    bot.reply_to(message, f"🍺 {username}, твой баланс: {balance}")


print("✅ Бот запущен...")
bot.polling(none_stop=True)
