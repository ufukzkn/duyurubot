import os, logging, time, html, re
from dotenv import load_dotenv
import requests

load_dotenv()

TELEGRAM_BOT_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
if not TELEGRAM_BOT_TOKEN:
    raise SystemExit("TELEGRAM_BOT_TOKEN .env'de yok.")

API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

TR_MONTHS = {
    "ocak":1,"şubat":2,"mart":3,"nisan":4,"mayıs":5,"haziran":6,
    "temmuz":7,"ağustos":8,"eylül":9,"ekim":10,"kasım":11,"aralık":12
}

def http_post_json(url, payload, timeout=20):
    return requests.post(url, json=payload, timeout=timeout)

def http_get(url, params=None, timeout=30):
    return requests.get(url, params=params, timeout=timeout)

def try_parse_tr_date(text: str):
    if not text: return None
    t = text.lower()
    m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})(?:\s+(\d{1,2}:\d{2}(?::\d{2})?))?", t)
    if m:
        d, mo, y = map(int, m.groups()[:3])
        hhmm = m.group(4) or ""
        try:
            date_part = f"{d:02d}.{mo:02d}.{y}"
            return (date_part + (f" {hhmm}" if hhmm else "")).strip()
        except:
            pass
    m = re.search(r"(\d{1,2})\s+([a-zçğıöşü]+)\s+(\d{4})", t, flags=re.I)
    if m:
        d = int(m.group(1)); mon = m.group(2).strip(" ,()."); y = int(m.group(3))
        mon_no = TR_MONTHS.get(mon.lower())
        if mon_no:
            return f"{d:02d}.{mon_no:02d}.{y}"
    return None

def format_tg(site_name, title, link, snippet, date_str=None):
    # Remove duplicate date lines from preview
    title = (title or "").strip()
    lines = [l.strip() for l in (snippet or "").splitlines() if l.strip()]
    cleaned = []
    for l in lines:
        if date_str and (l == date_str or try_parse_tr_date(l) == date_str):
            continue
        if l.lower() == title.lower():
            continue
        cleaned.append(l)
    preview = cleaned[:5]
    parts = []
    parts.append(f"📢 <b>{html.escape(site_name or 'Yeni duyuru')}</b>")
    parts.append(f"<b>{html.escape(title)}</b>")
    if date_str:
        parts.append(f"<i>🗓️ {html.escape(date_str)}</i>")
    parts.append(html.escape(link))
    if preview:
        parts.append("")
        bullets = "\n".join(f"• {html.escape(p)}" for p in preview)
        parts.append(bullets)
    return "\n".join(parts)

def send_telegram(chat_id, text, reply_markup=None):
    data = {"chat_id": chat_id, "text": text, "parse_mode":"HTML", "disable_web_page_preview": True}
    if reply_markup:
        data["reply_markup"] = reply_markup
    try:
        for attempt in range(3):
            r = http_post_json(f"{API}/sendMessage", data, timeout=20)
            if r.status_code == 429:
                retry_after = 3
                try:
                    retry_after = int(r.headers.get("Retry-After", "3"))
                except Exception:
                    pass
                time.sleep(min(5, max(1, retry_after)))
                continue
            if not r.ok:
                desc = ""
                try:
                    payload = r.json()
                    desc = payload.get("description", "")
                    if payload.get("error_code") == 403 and "can't initiate conversation" in desc:
                        logging.warning("Telegram: Kullanıcı botu başlatmamış (chat_id=%s)", chat_id)
                except Exception:
                    desc = r.text[:200]
                logging.warning("Telegram send fail %s %s", r.status_code, desc)
            return r
        return r
    except Exception:
        logging.exception("Telegram error")
        return None

def answer_callback_query(cb_id, text=""):
    try:
        http_post_json(f"{API}/answerCallbackQuery", {"callback_query_id": cb_id, "text": text}, timeout=10)
    except Exception:
        pass
