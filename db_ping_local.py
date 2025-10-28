# db_ping_local.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "vendored"))
import psycopg
dsn = os.environ["DATABASE_URL"]  # PowerShell'de export edip çalıştır
with psycopg.connect(dsn, connect_timeout=10) as conn:
    with conn.cursor() as cur:
        cur.execute("select now(), current_user, version()")
        print(cur.fetchone())
print("OK")