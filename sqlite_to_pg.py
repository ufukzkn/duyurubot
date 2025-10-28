# sqlite_to_pg.py  -- Windows'ta lokalde çalıştır
import os, sys, sqlite3, argparse

try:
    import psycopg  # v3
    _connect = lambda dsn: psycopg.connect(dsn, autocommit=True)
except ImportError:
    import psycopg2  # v2 fallback
    def _connect(dsn):
        c = psycopg2.connect(dsn)
        c.autocommit = True
        return c

def resolve_sqlite_path(p: str | None) -> str:
    # 1) Arg > 2) ENV(DB_PATH) > 3) ./monitor.db
    base_dir = os.path.dirname(os.path.abspath(__file__))
    cand = p or os.environ.get("DB_PATH") or "monitor.db"
    if not os.path.isabs(cand):
        cand = os.path.join(base_dir, cand)
    cand = os.path.normpath(cand)
    return cand

def require_file(path: str):
    if not os.path.exists(path):
        print(f"SQLite dosyası bulunamadı: {path}", file=sys.stderr)
        print("İpucu: python sqlite_to_pg.py --sqlite .\\monitor.db", file=sys.stderr)
        sys.exit(2)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sqlite", help="SQLite DB yolu (varsayılan: ./monitor.db)")
    ap.add_argument("--dsn", help="PostgreSQL DSN (varsayılan: env DATABASE_URL)")
    args = ap.parse_args()

    sqlite_path = resolve_sqlite_path(args.sqlite)
    require_file(sqlite_path)
    dsn = args.dsn or os.environ.get("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL boş. --dsn veya env ile verin.", file=sys.stderr)
        sys.exit(2)

    # Read-only aç; yanlışlıkla yazma olmasın
    conn_sqlite = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    conn_pg     = _connect(dsn)

    cur_s = conn_sqlite.cursor()
    cur_p = conn_pg.cursor()

    def copy_table(select_sql, insert_sql):
        for row in cur_s.execute(select_sql):
            cur_p.execute(insert_sql, row)

    # users(chat_id, username)
    copy_table(
        "SELECT chat_id, username FROM users",
        "INSERT INTO users(chat_id, username) VALUES(%s,%s) ON CONFLICT DO NOTHING"
    )

    copy_table(
        "SELECT chat_id, site_url FROM user_subs",
        "INSERT INTO user_subs(chat_id, site_url) VALUES(%s,%s) ON CONFLICT DO NOTHING"
    )

    copy_table(
        "SELECT chat_id, email FROM email_subs",
        "INSERT INTO email_subs(chat_id, email) VALUES(%s,%s) ON CONFLICT DO NOTHING"
    )

    copy_table(
        "SELECT site_url, item_hash, title, url FROM seen_item",
        "INSERT INTO seen_item(site_url, item_hash, title, url) VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING"
    )

    print("Tamam.")
    conn_pg.close()
    conn_sqlite.close()

if __name__ == "__main__":
    main()