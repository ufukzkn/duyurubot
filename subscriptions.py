import sqlite3, hashlib, logging

def init_db(DB_PATH: str):
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS seen_item(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        site_url TEXT,
        item_hash TEXT UNIQUE,
        title TEXT,
        url TEXT,
        first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS users(
        chat_id INTEGER PRIMARY KEY,
        username TEXT,
        first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS user_subs(
        chat_id INTEGER,
        site_url TEXT,
        PRIMARY KEY(chat_id, site_url)
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS emails(
        chat_id INTEGER,
        email TEXT,
        PRIMARY KEY(chat_id, email)
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS bot_state(
        key TEXT PRIMARY KEY,
        value TEXT
    )""")
    conn.commit()
    return conn

def text_hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def get_subscribers(conn, site_url):
    cur = conn.cursor()
    cur.execute("SELECT chat_id FROM user_subs WHERE site_url=?", (site_url,))
    return [row[0] for row in cur.fetchall()]

def upsert_user(conn, chat_id, username):
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO users(chat_id, username) VALUES(?,?)", (chat_id, username))
    conn.commit()

def toggle_sub(conn, chat_id, site_url):
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM user_subs WHERE chat_id=? AND site_url=?", (chat_id, site_url))
    if cur.fetchone():
        cur.execute("DELETE FROM user_subs WHERE chat_id=? AND site_url=?", (chat_id, site_url))
        conn.commit()
        return False
    else:
        cur.execute("INSERT OR IGNORE INTO user_subs(chat_id, site_url) VALUES(?,?)", (chat_id, site_url))
        conn.commit()
        return True

def get_user_subs(conn, chat_id):
    cur = conn.cursor()
    cur.execute("SELECT site_url FROM user_subs WHERE chat_id=?", (chat_id,))
    return {row[0] for row in cur.fetchall()}

def add_email(conn, chat_id, email: str):
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO emails(chat_id, email) VALUES(?,?)", (chat_id, email))
    conn.commit()

def remove_email(conn, chat_id, email: str):
    cur = conn.cursor()
    cur.execute("DELETE FROM emails WHERE chat_id=? AND email=?", (chat_id, email))
    conn.commit()

def list_emails(conn, chat_id):
    cur = conn.cursor()
    cur.execute("SELECT email FROM emails WHERE chat_id=? ORDER BY email", (chat_id,))
    return [row[0] for row in cur.fetchall()]

def emails_for_site(conn, site_url):
    # get all emails for users subscribed to this site
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT e.email
        FROM emails e
        JOIN user_subs us ON us.chat_id = e.chat_id
        WHERE us.site_url = ?
    """, (site_url,))
    return [row[0] for row in cur.fetchall()]
