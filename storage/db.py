import sqlite3, logging
from typing import Iterable, List, Set

def init_db(db_path: str):
    conn = sqlite3.connect(db_path, check_same_thread=False)
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
    cur.execute("""CREATE TABLE IF NOT EXISTS email_subs(
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

# --- bot state ---
def get_update_offset(conn) -> int:
    cur = conn.cursor()
    cur.execute("SELECT value FROM bot_state WHERE key='update_offset'")
    row = cur.fetchone()
    return int(row[0]) if row else 0

def set_update_offset(conn, offset: int):
    cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO bot_state(key,value) VALUES('update_offset',?)", (str(offset),))
    conn.commit()

# --- users & subs ---
def upsert_user(conn, chat_id: int, username: str):
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO users(chat_id, username) VALUES(?,?)", (chat_id, username))
    conn.commit()

def toggle_site_sub(conn, chat_id: int, site_url: str) -> bool:
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM user_subs WHERE chat_id=? AND site_url=?", (chat_id, site_url))
    if cur.fetchone():
        cur.execute("DELETE FROM user_subs WHERE chat_id=? AND site_url=?", (chat_id, site_url))
        conn.commit()
        return False
    cur.execute("INSERT OR IGNORE INTO user_subs(chat_id, site_url) VALUES(?,?)", (chat_id, site_url))
    conn.commit()
    return True

def get_user_subs(conn, chat_id: int) -> Set[str]:
    cur = conn.cursor()
    cur.execute("SELECT site_url FROM user_subs WHERE chat_id=?", (chat_id,))
    return {row[0] for row in cur.fetchall()}

def get_subscribers(conn, site_url: str) -> List[int]:
    cur = conn.cursor()
    cur.execute("SELECT chat_id FROM user_subs WHERE site_url=?", (site_url,))
    return [row[0] for row in cur.fetchall()]

# --- email subs ---
import re
EMAIL_RE = re.compile(r"^[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}$", re.I)

def add_email(conn, chat_id: int, email: str):
    if not EMAIL_RE.match(email or ""):
        return False, "Geçersiz e-posta adresi."
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO email_subs(chat_id, email) VALUES(?,?)", (chat_id, email.lower()))
    conn.commit()
    return True, "E-posta eklendi."

def remove_email(conn, chat_id: int, email: str):
    cur = conn.cursor()
    cur.execute("DELETE FROM email_subs WHERE chat_id=? AND email=?", (chat_id, (email or "").lower()))
    conn.commit()
    return True, "E-posta kaldırıldı."

def list_emails(conn, chat_id: int):
    cur = conn.cursor()
    cur.execute("SELECT email FROM email_subs WHERE chat_id=?", (chat_id,))
    return [row[0] for row in cur.fetchall()]

# --- seen items ---
def insert_seen(conn, site_url: str, item_hash: str, title: str, url: str) -> bool:
    try:
        cur = conn.cursor()
        cur.execute("INSERT INTO seen_item(site_url,item_hash,title,url) VALUES(?,?,?,?)",
                    (site_url, item_hash, title, url))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
