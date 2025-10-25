# monitor.py
import os, time, logging, threading, re, html, yaml, sqlite3
from dotenv import load_dotenv
from messaging import send_telegram, answer_callback_query, format_tg
from mailer import send_email
from scraper import fetch, fetch_js, needs_js, extract_list_links, filter_links, extract_detail, clean_text
from subscriptions import init_db, text_hash, get_subscribers, upsert_user, toggle_sub, get_user_subs, add_email, remove_email, list_emails, emails_for_site

# -------------------- ENV / CONFIG --------------------
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
if not TELEGRAM_BOT_TOKEN:
    raise SystemExit("TELEGRAM_BOT_TOKEN .env'de yok.")

CHECK_INTERVAL_SEC = int(os.getenv("CHECK_INTERVAL_SEC", "600"))
DB_PATH = os.getenv("DB_PATH", "monitor.db")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# -------------------- SITES LOADER --------------------
def load_sites():
    with open("sites.yaml","r",encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data["sites"]

# -------------------- DB INIT --------------------
def init_state_tables(conn):
    # add bot_state if not exists (for update offset)
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS bot_state(
        key TEXT PRIMARY KEY,
        value TEXT
    )""")
    conn.commit()

# -------------------- HELPERS --------------------
def safe_remove_subscription_on_forbidden(conn, chat_id, site_url, resp):
    try:
        if resp is None:
            return
        if resp.status_code in (400, 403):
            cur = conn.cursor()
            cur.execute("DELETE FROM user_subs WHERE chat_id=? AND site_url=?", (chat_id, site_url))
            conn.commit()
            logging.info("Abonelik silindi (geçersiz chat): chat_id=%s site=%s", chat_id, site_url)
    except Exception:
        logging.exception("Abonelik temizliği sırasında hata")

def list_to_markup(items):
    return "\n".join(f"• {html.escape(x)}" for x in items)


# -------------------- FORMAT HELPERS --------------------

def dedupe_lines(text: str) -> str:
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    out = []
    prev_lower = None
    for l in lines:
        low = l.lower()
        if prev_lower == low:
            continue
        out.append(l)
        prev_lower = low
    return "\n".join(out)

def is_valid_email(addr: str) -> bool:
    return bool(re.match(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$", addr))

def email_template(site_name, title, link, snippet, date_str=None):
    title = (title or "").strip()
    snippet = dedupe_lines(snippet or "")
    preview_lines = [l for l in snippet.splitlines() if l and l.lower() != title.lower()]
    preview = "\n".join(preview_lines[:12])
    date_html = f'<div style="color:#6b7280;font-style:italic;margin-top:2px">{html.escape(date_str)}</div>' if date_str else ""
    return f"""\
<!doctype html>
<html>
  <body style="margin:0;padding:0;background:#f7f7f7">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f7f7f7">
      <tr><td align="center" style="padding:24px">
        <table role="presentation" width="600" cellspacing="0" cellpadding="0" style="background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.05);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Ubuntu,'Helvetica Neue',Arial,sans-serif;color:#111827">
          <tr>
            <td style="padding:20px 24px;background:#111827;color:#ffffff;font-size:18px;font-weight:600;">
              {html.escape(site_name or "Yeni duyuru")}
            </td>
          </tr>
          <tr>
            <td style="padding:24px">
              <h1 style="margin:0 0 8px 0;font-size:20px;line-height:1.3;color:#111827">{html.escape(title)}</h1>
              {date_html}
              <p style="white-space:pre-wrap;margin:16px 0 20px 0;line-height:1.6;color:#111827">{html.escape(preview)}</p>
              <a href="{html.escape(link)}" style="display:inline-block;background:#2563eb;color:#ffffff;text-decoration:none;padding:10px 16px;border-radius:8px;font-weight:600">İlana git</a>
            </td>
          </tr>
          <tr>
            <td style="padding:16px 24px;color:#6b7280;font-size:12px">
              Bu e-posta otomatik gönderilmiştir.
            </td>
          </tr>
        </table>
      </td></tr>
    </table>
  </body>
</html>
"""

# -------------------- EXTRACTION --------------------
# (Tüm çıkarım ve fetch fonksiyonları scraper.py içinde; burada kullanılmıyor.)
 
# -------------------- SUBSCRIPTIONS --------------------
# (Abonelik işlemleri subscriptions.py içinde; burada tanımlı değil.)

# -------------------- TELEGRAM UI --------------------
def sites_keyboard(conn, chat_id, sites):
    subs = get_user_subs(conn, chat_id)
    kb = []
    for s in sites:
        url = s["url"]; name = s["name"]
        on = "✅" if url in subs else "➕"
        kb.append([{"text": f"{on} {name}", "callback_data": f"tog|{url}"}])
    kb.append([{"text":"📝 Seçili sitelerim", "callback_data":"list"}])
    return {"inline_keyboard": kb}

def handle_update(conn, upd, sites_by_url):
    if "message" in upd:
        msg = upd["message"]
        chat_id = msg["chat"]["id"]
        username = msg["from"].get("username") or ""
        upsert_user(conn, chat_id, username)

        text = msg.get("text","") or ""
        if text.startswith("/start"):
            send_telegram(chat_id,
                "Merhaba! 👋 Hangi sitelerden duyuru almak istiyorsun?\nAşağıdan seç/toggle et.",
                reply_markup=sites_keyboard(conn, chat_id, list(sites_by_url.values()))
            )
        elif text.startswith("/sites"):
            send_telegram(chat_id,
                "Takip etmek istediğin siteleri seç/toggle et:",
                reply_markup=sites_keyboard(conn, chat_id, list(sites_by_url.values()))
            )
        elif text.startswith("/email"):
            emails = list_emails(conn, chat_id)
            info = "Kayıtlı e-posta adreslerin yok." if not emails else ("E-posta adreslerin:\n" + list_to_markup(emails))
            help_text = "\n\nEkle: email add adres@ornek.com\nSil: email remove adres@ornek.com"
            send_telegram(chat_id, info + help_text)
        elif text.lower().startswith("email add "):
            addr = text.split(" ", 2)[2].strip()
            if is_valid_email(addr):
                add_email(conn, chat_id, addr)
                send_telegram(chat_id, f"✅ Eklendi: <b>{html.escape(addr)}</b>")
            else:
                send_telegram(chat_id, "❌ Geçersiz e-posta adresi.")
        elif text.lower().startswith("email remove "):
            addr = text.split(" ", 2)[2].strip()
            remove_email(conn, chat_id, addr)
            send_telegram(chat_id, f"🗑️ Silindi (varsa): <b>{html.escape(addr)}</b>")
        else:
            send_telegram(chat_id, "Komutlar: /start, /sites, /email\n(E-posta ekle/sil: email add/remove)")

    elif "callback_query" in upd:
        cb = upd["callback_query"]
        cb_id = cb["id"]
        data = cb.get("data","")
        chat_id = cb["message"]["chat"]["id"]
        if data == "list":
            subs = get_user_subs(conn, chat_id)
            if not subs: txt = "Seçili siten yok."
            else:
                names = [sites_by_url[u]["name"] for u in subs if u in sites_by_url]
                txt = "Seçili sitelerin:\n• " + "\n• ".join(names)
            answer_callback_query(cb_id, "Liste")
            send_telegram(chat_id, txt)
            return

        if data.startswith("tog|"):
            site_url = data.split("|",1)[1]
            if site_url not in sites_by_url:
                answer_callback_query(cb_id, "Site bulunamadı")
                return
            toggle_sub(conn, chat_id, site_url)
            answer_callback_query(cb_id, "Güncellendi")
            send_telegram(chat_id, "Güncellendi ✔️",
                reply_markup=sites_keyboard(conn, chat_id, list(sites_by_url.values()))
            )

def bot_loop(conn, sites):
    sites_by_url = {s["url"]: s for s in sites}
    cur = conn.cursor()
    cur.execute("SELECT value FROM bot_state WHERE key='update_offset'")
    row = cur.fetchone()
    offset = int(row[0]) if row else 0

    logging.info("Bot loop started.")
    while True:
        try:
            from messaging import http_get
            r = http_get(f"https://api.telegram.org/bot{os.getenv('TELEGRAM_BOT_TOKEN')}/getUpdates", params={"timeout": 25, "offset": offset+1}, timeout=30)
            if r.ok:
                data = r.json()
                for upd in data.get("result", []):
                    offset = max(offset, upd["update_id"])
                    handle_update(conn, upd, sites_by_url)
                cur.execute("INSERT OR REPLACE INTO bot_state(key,value) VALUES('update_offset',?)", (str(offset),))
                conn.commit()
        except Exception:
            logging.exception("Bot loop error")
            time.sleep(2)

# -------------------- MONITOR LOOP --------------------
def process_site(conn, site, notify=True):
    base = site["url"]
    list_selector = site.get("list_selector","").strip()
    item_link_selector = site.get("item_link_selector","a").strip()
    include_url_regex = site.get("include_url_regex")
    exclude_text_regex = site.get("exclude_text_regex")
    detail_selector    = site.get("detail_selector")

    logging.info("Kontrol: %s", base)

    html_list = ""
    try:
        html_list = fetch(base)
    except Exception as e:
        logging.warning("Statik çekilemedi: %s", e)

    if not html_list or needs_js(html_list):
        logging.info("JS render gerekli görünüyor, Playwright ile deniyorum.")
        try:
            html_list = fetch_js(base)
        except Exception as e:
            logging.warning("Playwright da başarısız: %s", e)
            return

    items = extract_list_links(html_list, list_selector, item_link_selector, base)
    items = filter_links(items, include_url_regex, exclude_text_regex)
    if not items:
        logging.info("Item yok/filtre sonrası boş: %s", base)
        return

    cur = conn.cursor()
    new_count = 0
    for it in items:
        link = it["url"]
        title_from_list = it["title"][:200]

        # Detay
        try:
            detail_html = fetch(link)
        except Exception:
            try:
                detail_html = fetch_js(link)
            except Exception as e:
                logging.warning("Detay getirilemedi: %s", e)
                continue

        title_det, body, date_str = extract_detail(detail_html, detail_selector)
        final_title = (title_det or title_from_list or "").strip()[:200]
        snippet = clean_text(body, limit=1000)

        # Link bazlı tekilleştirme
        h = text_hash(link)
        try:
            cur.execute("INSERT INTO seen_item(site_url,item_hash,title,url) VALUES(?,?,?,?)",
                        (base, h, final_title, link))
            conn.commit()
            new_count += 1

            if notify:
                # 1) Telegram sadece abone varsa gönderilsin
                subscribers = get_subscribers(conn, base)
                if subscribers:
                    text_msg = format_tg(site.get('name',''), final_title, link, snippet, date_str)
                    for chat_id in subscribers:
                        resp = send_telegram(chat_id, text_msg)
                        safe_remove_subscription_on_forbidden(conn, chat_id, base, resp)

                # 2) E-postayı siteye abone kullanıcıların e-postalarına gönder
                to_list = emails_for_site(conn, base)
                # ayrıca .env içindeki TO_EMAIL'i de isteğe bağlı eklemek isteyen olur diye destekleyebiliriz
                extra_to = (os.getenv("TO_EMAIL") or "").strip()
                if extra_to:
                    to_list = sorted(set(to_list + [e.strip() for e in extra_to.split(",") if e.strip()]))
                if to_list:
                    em_html = email_template(site.get('name',''), final_title, link, snippet, date_str)
                    ok_email = send_email(to_list, f"Yeni duyuru - {site.get('name')}", em_html)
                    logging.info("Email gönderimi: %s (adet=%d)", "OK" if ok_email else "FAIL", len(to_list))

        except sqlite3.IntegrityError:
            pass

    logging.info("Tamam: %s (yeni: %d)", base, new_count)

def monitor_loop(conn):
    logging.info("Monitor loop started.")
    while True:
        sites = load_sites()
        for s in sites:
            try:
                process_site(conn, s, notify=True)
            except Exception:
                logging.exception("Site işlenirken hata")
            time.sleep(1.2)
        logging.info("Tüm siteler tarandı. %d sn uyku.", CHECK_INTERVAL_SEC)
        time.sleep(CHECK_INTERVAL_SEC)

# -------------------- MAIN --------------------
if __name__ == "__main__":
    conn = init_db(DB_PATH)
    init_state_tables(conn)
    sites = load_sites()

    # (opsiyonel) ADMIN_CHAT_ID ile tohumla: /start demeden kayıt ve abonelik eklemek için
    ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "").strip()
    if ADMIN_CHAT_ID.isdigit():
        cur = conn.cursor()
        cur.execute("INSERT OR IGNORE INTO users(chat_id, username) VALUES(?,?)", (int(ADMIN_CHAT_ID), "admin"))
        for s in sites:
            cur.execute("INSERT OR IGNORE INTO user_subs(chat_id, site_url) VALUES(?,?)", (int(ADMIN_CHAT_ID), s["url"]))
        conn.commit()
        logging.info("ADMIN_CHAT_ID seedlendi ve tüm sitelere abone edildi: %s", ADMIN_CHAT_ID)

    t1 = threading.Thread(target=bot_loop, args=(conn, sites), daemon=True)
    t1.start()

    monitor_loop(conn)
