# storage/db.py  -- PostgreSQL (psycopg3) uyarlaması
import os, logging, re
from typing import Iterable, List, Set, Optional

import psycopg
from psycopg.rows import tuple_row

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
if not DATABASE_URL:
    # Lambda'da DATABASE_URL şart; lokal geliştirmede env'e koy.
    raise RuntimeError("DATABASE_URL boş. Neon/Supabase DSN'ini env'e ekleyin.")

EMAIL_RE = re.compile(r"^[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}$", re.I)

# --- INIT ---
def init_db(_db_path_ignored: str = ""):
    """
    PostgreSQL'e bağlanır ve tablo şemasını (gerekirse) oluşturur.
    """
    conn = psycopg.connect(DATABASE_URL, autocommit=True)
    with conn.cursor() as cur:
        # users
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users(
            chat_id    BIGINT PRIMARY KEY,
            username   TEXT,
            first_seen TIMESTAMPTZ DEFAULT NOW()
        );
        """)

        # user_subs
        cur.execute("""
        CREATE TABLE IF NOT EXISTS user_subs(
            chat_id  BIGINT NOT NULL REFERENCES users(chat_id) ON DELETE CASCADE,
            site_url TEXT   NOT NULL,
            PRIMARY KEY(chat_id, site_url)
        );
        """)

        # email_subs
        cur.execute("""
        CREATE TABLE IF NOT EXISTS email_subs(
            chat_id BIGINT NOT NULL REFERENCES users(chat_id) ON DELETE CASCADE,
            email   TEXT   NOT NULL,
            PRIMARY KEY(chat_id, email)
        );
        """)

        # seen_item
        cur.execute("""
        CREATE TABLE IF NOT EXISTS seen_item(
            id         BIGSERIAL PRIMARY KEY,
            site_url   TEXT NOT NULL,
            item_hash  TEXT NOT NULL UNIQUE,
            title      TEXT,
            url        TEXT,
            first_seen TIMESTAMPTZ DEFAULT NOW()
        );
        """)

        # bot_state
        cur.execute("""
        CREATE TABLE IF NOT EXISTS bot_state(
            key   TEXT PRIMARY KEY,
            value TEXT
        );
        """)

        # Performans için birkaç index (opsiyonel ama faydalı)
        cur.execute("CREATE INDEX IF NOT EXISTS ix_seen_item_site ON seen_item(site_url);")
        cur.execute("CREATE INDEX IF NOT EXISTS ix_user_subs_site ON user_subs(site_url);")
    return conn


# --- bot state / offsets ---
def get_update_offset(conn) -> int:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT value FROM bot_state WHERE key=%s;", ("update_offset",))
        row = cur.fetchone()
        try:
            return int(row[0]) if row else 0
        except:
            return 0

def set_update_offset(conn, offset: int):
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO bot_state(key,value) VALUES(%s,%s)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
        """, ("update_offset", str(offset)))


def get_state(conn, key: str) -> Optional[str]:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT value FROM bot_state WHERE key=%s;", (key,))
        row = cur.fetchone()
        return row[0] if row else None

def set_state(conn, key: str, value: str):
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO bot_state(key,value) VALUES(%s,%s)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
        """, (key, value))

def del_state(conn, key: str):
    with conn.cursor() as cur:
        cur.execute("DELETE FROM bot_state WHERE key=%s;", (key,))


# --- users & subs ---
def upsert_user(conn, chat_id: int, username: str):
    """
    İlk kez gelirse ekler. Varsa ve yeni username boş değilse günceller.
    """
    username = (username or "").strip()
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO users(chat_id, username) VALUES (%s, %s)
            ON CONFLICT (chat_id) DO UPDATE SET
              username = CASE
                           WHEN COALESCE(EXCLUDED.username, '') <> '' THEN EXCLUDED.username
                           ELSE users.username
                         END;
        """, (chat_id, username))

def toggle_site_sub(conn, chat_id: int, site_url: str) -> bool:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT 1 FROM user_subs WHERE chat_id=%s AND site_url=%s;", (chat_id, site_url))
        exists = cur.fetchone() is not None
    with conn.cursor() as cur:
        if exists:
            cur.execute("DELETE FROM user_subs WHERE chat_id=%s AND site_url=%s;", (chat_id, site_url))
            return False
        else:
            cur.execute("""
                INSERT INTO user_subs(chat_id, site_url) VALUES(%s,%s)
                ON CONFLICT DO NOTHING;
            """, (chat_id, site_url))
            return True

def get_user_subs(conn, chat_id: int) -> Set[str]:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT site_url FROM user_subs WHERE chat_id=%s;", (chat_id,))
        return {row[0] for row in cur.fetchall()}

def get_subscribers(conn, site_url: str) -> List[int]:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT chat_id FROM user_subs WHERE site_url=%s;", (site_url,))
        return [row[0] for row in cur.fetchall()]


# --- email subs ---
def add_email(conn, chat_id: int, email: str):
    if not EMAIL_RE.match(email or ""):
        return False, "Geçersiz e-posta adresi."
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO email_subs(chat_id, email) VALUES(%s,%s)
                ON CONFLICT DO NOTHING;
            """, (chat_id, (email or "").lower()))
        return True, "E-posta eklendi."
    except Exception:
        logging.exception("add_email")
        return False, "E-posta eklenemedi."

def remove_email(conn, chat_id: int, email: str):
    with conn.cursor() as cur:
        cur.execute("DELETE FROM email_subs WHERE chat_id=%s AND email=%s;",
                    (chat_id, (email or "").lower()))
    return True, "E-posta kaldırıldı."

def list_emails(conn, chat_id: int):
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT email FROM email_subs WHERE chat_id=%s;", (chat_id,))
        return [row[0] for row in cur.fetchall()]


# --- seen items ---
def insert_seen(conn, site_url: str, item_hash: str, title: str, url: str) -> bool:
    """
    Gerçekten yeni mi önce kontrol et → yeni ise INSERT.
    Böylece gereksiz INSERT denemeleri sequence'i tüketmez.
    """
    try:
        with conn.cursor() as cur:
            # URL ya da hash zaten var mı?
            cur.execute(
                "SELECT 1 FROM seen_item WHERE url = %s OR item_hash = %s LIMIT 1",
                (url, item_hash)
            )
            if cur.fetchone():
                return False

            # Gerçekten yeni → ekle
            cur.execute(
                "INSERT INTO seen_item(site_url, item_hash, title, url) VALUES (%s, %s, %s, %s)",
                (site_url, item_hash, title, url)
            )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        logging.exception("insert_seen failed")
        return False
