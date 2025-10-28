# run_once.py
import logging
from config import DB_PATH, TELEGRAM_BOT_TOKEN
from storage.db import init_db, get_state, set_state, del_state
from formatters.textfmt import text_hash
from monitor import monitor_once

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

def main():
    if not TELEGRAM_BOT_TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN eksik.")

    conn = init_db(DB_PATH)

    # Prod'daki güvenli davranış: token değiştiyse offset sıfırla
    tok_h = text_hash(TELEGRAM_BOT_TOKEN)[:16]
    if (get_state(conn, "token_hash") or "") != tok_h:
        del_state(conn, "update_offset")
        set_state(conn, "token_hash", tok_h)
        logging.info("Token değişikliği tespit edildi; update_offset sıfırlandı.")

    total = monitor_once(conn)
    conn.close()
    print(f"DONE total_new={total}")

if __name__ == "__main__":
    main()
