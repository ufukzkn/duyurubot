# lambdapkg/lambda_scraper.py
import os, sys, json, logging, time

import os, sys
CURRENT_DIR  = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

VENDORED = os.path.join(PROJECT_ROOT, "vendored")
if os.path.isdir(VENDORED) and VENDORED not in sys.path:
    sys.path.append(VENDORED)
from config import TELEGRAM_BOT_TOKEN, DB_PATH
from storage.db import init_db, get_state, set_state, del_state
from formatters.textfmt import text_hash
from monitor import monitor_once  # monitor.py'de eklediğimiz tek tur fonksiyonu

logging.getLogger().setLevel(logging.INFO)

def lambda_handler(event, context):
    # Test: SMTP gönderimi (örn. Lambda Test event ile)
    if event and isinstance(event, dict) and event.get("email_test_to"):
        from notifiers.emailer import send_email_single
        to = str(event["email_test_to"]).strip()
        ok = bool(to) and send_email_single(
            "Duyurubot SMTP test",
            "<b>Lambda e-posta testi</b>",
            to,
        )
        return {"statusCode": 200 if ok else 500, "body": f"mail {'sent' if ok else 'fail'} to {to}"}

    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN yok")

    conn = init_db(DB_PATH)

    # Token değiştiyse offset'i bir kez sıfırla (eski update çakışmasın)
    tok_h = text_hash(TELEGRAM_BOT_TOKEN)[:16]
    if (get_state(conn, "token_hash") or "") != tok_h:
        del_state(conn, "update_offset")
        set_state(conn, "token_hash", tok_h)
        logging.info("Token değişikliği tespit edildi; update_offset sıfırlandı.")

    total = monitor_once(conn)

    try:
        conn.close()
    except Exception:
        pass

    return {"statusCode": 200, "body": f"ok:{total}"}