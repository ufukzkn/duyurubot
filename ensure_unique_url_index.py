import os, psycopg

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise SystemExit("Set DATABASE_URL first")

# 1) Kopyaları temizle (tek transaksiyon içinde)
with psycopg.connect(DATABASE_URL) as conn:
    with conn.cursor() as cur:
        cur.execute("""
        DELETE FROM seen_item s
        USING (
          SELECT id
          FROM (
            SELECT id, ROW_NUMBER() OVER (PARTITION BY url ORDER BY id) AS rn
            FROM seen_item
          ) t
          WHERE t.rn > 1
        ) d
        WHERE s.id = d.id;
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS ix_user_subs_site ON user_subs (site_url);")
        cur.execute("CREATE INDEX IF NOT EXISTS ix_seen_item_site ON seen_item (site_url);")
    conn.commit()

# 2) UNIQUE index’i CONCURRENTLY kur (transaction dışında)
with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
    with conn.cursor() as cur:
        cur.execute("CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS ux_seen_item_url ON seen_item (url);")

print("Done.")