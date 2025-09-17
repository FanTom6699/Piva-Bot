import sqlite3

def init_db():
    conn = sqlite3.connect("game.db", check_same_thread=False)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS players (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id TEXT UNIQUE,
            username TEXT,
            beer_points INTEGER DEFAULT 0,
            last_beer INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    return conn
