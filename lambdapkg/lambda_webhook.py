# lambdapkg/lambda_webhook.py
import os, json, logging, sys, time


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
from scraper.site_monitor import load_sites_yaml
from notifiers.telegram_bot import handle_update  # SENİN mevcut fonksiyonun

logging.getLogger().setLevel(logging.INFO)

SECRET_HEADER    = "X-Telegram-Bot-Api-Secret-Token"
EXPECTED_SECRET  = os.environ.get("TELEGRAM_SECRET_TOKEN")  # setWebhook ile verdiğin gizli token

# (İsteğe bağlı) sıcak durumda tekrar kullanmak için cache
_SITES_CACHE = None

def lambda_handler(event, context):
    # 1) Secret doğrulama (opsiyonel ama önerilir)
    headers = { (k or "").lower(): v for k, v in (event.get("headers") or {}).items() }
    if EXPECTED_SECRET and headers.get(SECRET_HEADER.lower()) != EXPECTED_SECRET:
        logging.warning("Invalid secret token")
        return {"statusCode": 403, "body": "forbidden"}

    # 2) Payload
    try:
        update = json.loads(event.get("body") or "{}")
    except Exception:
        return {"statusCode": 400, "body": "bad request"}

    # 3) DB bağlantısı
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN yok")
    conn = init_db(DB_PATH)

    # 4) Token değiştiyse offset reset (webhook'ta zorunlu değil ama güvenli)
    tok_h = text_hash(TELEGRAM_BOT_TOKEN)[:16]
    if (get_state(conn, "token_hash") or "") != tok_h:
        del_state(conn, "update_offset")
        set_state(conn, "token_hash", tok_h)
        logging.info("Token değişikliği tespit edildi; update_offset sıfırlandı.")

    # 5) Siteleri yükle (sıcak durumda cache'i kullan)
    global _SITES_CACHE
    if _SITES_CACHE is None:
        _SITES_CACHE = load_sites_yaml()
    sites_by_url = { s["url"]: s for s in _SITES_CACHE }

    # 6) Mevcut akışınla birebir: handle_update(...)
    try:
        handle_update(conn, update, sites_by_url)
        return {"statusCode": 200, "body": "ok"}
    finally:
        try:
            conn.close()
        except Exception:
            pass