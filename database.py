# database.py
import aiosqlite
from datetime import datetime

class Database:
    def __init__(self, db_name='bot_database.db'):
        self.db_name = db_name

    async def initialize(self):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    first_name TEXT,
                    last_name TEXT,
                    username TEXT,
                    beer_rating INTEGER DEFAULT 0,
                    last_beer_time TEXT
                )
            ''')
            await db.commit()
    
    async def user_exists(self, user_id):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute('SELECT 1 FROM users WHERE user_id = ?', (user_id,))
            return await cursor.fetchone() is not None

    async def add_user(self, user_id, first_name, last_name, username):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                'INSERT INTO users (user_id, first_name, last_name, username, beer_rating) VALUES (?, ?, ?, ?, ?)',
                (user_id, first_name, last_name, username, 0)
            )
            await db.commit()

    async def get_user_beer_rating(self, user_id):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute('SELECT beer_rating FROM users WHERE user_id = ?', (user_id,))
            result = await cursor.fetchone()
            return result[0] if result else 0
            
    async def get_last_beer_time(self, user_id):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute('SELECT last_beer_time FROM users WHERE user_id = ?', (user_id,))
            result = await cursor.fetchone()
            return datetime.fromisoformat(result[0]) if result and result[0] else None

    async def update_beer_data(self, user_id, new_rating):
        current_time_iso = datetime.now().isoformat()
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                'UPDATE users SET beer_rating = ?, last_beer_time = ? WHERE user_id = ?',
                (new_rating, current_time_iso, user_id)
            )
            await db.commit()

    async def get_top_users(self, limit=10):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                'SELECT first_name, last_name, beer_rating FROM users ORDER BY beer_rating DESC LIMIT ?',
                (limit,)
            )
            return await cursor.fetchall()
