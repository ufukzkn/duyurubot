# monitor.py
import os, time, sqlite3, hashlib, logging, threading, requests, smtplib, html, re
from email.message import EmailMessage
from urllib.parse import urljoin
from bs4 import BeautifulSoup
import yaml
from dotenv import load_dotenv

# -------------------- ENV / CONFIG --------------------
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
if not TELEGRAM_BOT_TOKEN:
    raise SystemExit("TELEGRAM_BOT_TOKEN .env'de yok.")

API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
CHECK_INTERVAL_SEC = int(os.getenv("CHECK_INTERVAL_SEC", "600"))
DB_PATH = os.getenv("DB_PATH", "monitor.db")

# E-posta (opsiyonel)
SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "").strip()
SMTP_PASS = os.getenv("SMTP_PASS", "").strip()
FROM_EMAIL = os.getenv("FROM_EMAIL", "").strip()
TO_EMAIL   = os.getenv("TO_EMAIL", "").strip()

HEADERS = {"User-Agent":"duyuru-monitor/1.4 (+github.com/you)"}
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# -------------------- SITES LOADER --------------------
def load_sites():
    with open("sites.yaml","r",encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data["sites"]

# -------------------- DB INIT --------------------
def init_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
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
    cur.execute("""CREATE TABLE IF NOT EXISTS bot_state(
        key TEXT PRIMARY KEY,
        value TEXT
    )""")
    conn.commit()
    return conn

# -------------------- HELPERS --------------------
def text_hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def http_post_json(url, payload, timeout=20):
    return requests.post(url, json=payload, timeout=timeout)

def http_get(url, params=None, timeout=30):
    return requests.get(url, params=params, timeout=timeout)

def send_telegram(chat_id, text, reply_markup=None):
    data = {"chat_id": chat_id, "text": text, "parse_mode":"HTML", "disable_web_page_preview": True}
    if reply_markup:
        data["reply_markup"] = reply_markup
    try:
        r = http_post_json(f"{API}/sendMessage", data, timeout=20)
        if not r.ok:
            desc = ""
            try:
                desc = r.json().get("description","")
            except:
                desc = r.text[:200]
            logging.warning("Telegram send fail %s %s", r.status_code, desc)
        return r
    except Exception:
        logging.exception("Telegram error")
        return None

def answer_callback_query(cb_id, text=""):
    try:
        http_post_json(f"{API}/answerCallbackQuery", {"callback_query_id": cb_id, "text": text}, timeout=10)
    except Exception:
        pass

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

def send_email(subject: str, body_html: str) -> bool:
    if not (SMTP_HOST and SMTP_USER and SMTP_PASS and FROM_EMAIL and TO_EMAIL):
        return False
    recipients = [a.strip() for a in TO_EMAIL.split(",") if a.strip()]
    if not recipients:
        return False
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = FROM_EMAIL
    msg["To"] = ", ".join(recipients)
    msg.set_content("HTML istemcisi olmayanlar için düz metin.")
    msg.add_alternative(body_html, subtype="html")
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as smtp:
            smtp.starttls()
            smtp.login(SMTP_USER, SMTP_PASS)
            smtp.send_message(msg, from_addr=FROM_EMAIL, to_addrs=recipients)
        return True
    except Exception:
        logging.exception("SMTP error")
        return False

def fetch(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=25)
    r.raise_for_status()
    return r.text

def fetch_js(url: str) -> str:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        page = b.new_page()
        page.goto(url, timeout=35000)
        page.wait_for_timeout(1500)
        htmlc = page.content()
        b.close()
    return htmlc

def needs_js(html_text: str) -> bool:
    soup = BeautifulSoup(html_text, "html.parser")
    body_txt = (soup.get_text() or "").strip()
    scripts = len(soup.find_all("script"))
    return scripts > 8 and len(body_txt) < 200

def absolute_url(base: str, href: str | None) -> str | None:
    if not href: return None
    if href.startswith("http://") or href.startswith("https://"): return href
    return urljoin(base, href)

def clean_text(s: str, limit=1200) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+\n", "\n", s)
    s = re.sub(r"[ \t]{2,}", " ", s)
    return s[:limit]

# -------------------- FORMAT HELPERS --------------------
TR_MONTHS = {
    "ocak":1,"şubat":2,"mart":3,"nisan":4,"mayıs":5,"haziran":6,
    "temmuz":7,"ağustos":8,"eylül":9,"ekim":10,"kasım":11,"aralık":12
}

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
    title = (title or "").strip()
    snippet = dedupe_lines(snippet or "")
    preview_lines = [l for l in snippet.splitlines() if l and l.lower() != title.lower()]
    preview = "\n".join(preview_lines[:3])
    parts = []
    parts.append(f"📢 <b>{html.escape(site_name or 'Yeni duyuru')}</b>")
    parts.append(f"<b>{html.escape(title)}</b>")
    if date_str:
        parts.append(f"<i>{html.escape(date_str)}</i>")
    parts.append(html.escape(link))
    if preview:
        parts.append("")
        parts.append(html.escape(preview))
    return "\n".join(parts)

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
def extract_list_links(full_html: str, list_selector: str, item_link_selector: str, base_url: str):
    soup = BeautifulSoup(full_html, "html.parser")
    container = soup.select_one(list_selector) if list_selector else soup
    if not container:
        return []
    links = []
    for a in container.select(item_link_selector):
        title = a.get_text(strip=True) or ""
        href  = a.get("href")
        url   = absolute_url(base_url, href)
        if not url or len(title) < 5:
            continue
        links.append({"title": title, "url": url})
    seen = set(); uniq = []
    for it in links:
        if it["url"] in seen: continue
        seen.add(it["url"]); uniq.append(it)
    return uniq

def filter_links(items, include_url_regex=None, exclude_text_regex=None):
    out = []
    inc = re.compile(include_url_regex, re.I) if include_url_regex else None
    exc = re.compile(exclude_text_regex, re.I) if exclude_text_regex else None
    for it in items:
        t = it["title"]; u = it["url"]
        if inc and not inc.search(u): continue
        if exc and (exc.search(t) or exc.search(u)): continue
        out.append(it)
    return out

def extract_detail(html_text: str, detail_selector: str | None):
    soup = BeautifulSoup(html_text, "html.parser")
    node = soup.select_one(detail_selector) if detail_selector else None
    if not node:
        candidates = soup.select("article, main, .content, .post, .entry, #content, .gdlr-core-single-blog-content, .gdlr-core-blog-content") or [soup.body or soup]
        node = max(candidates, key=lambda n: len(n.get_text(strip=True)))
    title = None
    h = node.find(["h1","h2","h3"]) if node else None
    if h: title = h.get_text(strip=True)

    # tarih yakalama
    date_text = None
    date_node = soup.select_one(".gdlr-core-blog-info-date, .date, time")
    if date_node:
        date_text = date_node.get_text(" ", strip=True)
    else:
        date_text = try_parse_tr_date(soup.get_text(" ", strip=True))
    if date_text:
        parsed = try_parse_tr_date(date_text)
        if parsed:
            date_text = parsed

    snippet = node.get_text(separator="\n").strip() if node else soup.get_text(separator="\n").strip()
    return (title or None), clean_text(snippet, limit=1600), (date_text or None)

# -------------------- SUBSCRIPTIONS --------------------
def get_subscribers(conn, site_url):
    cur = conn.cursor()
    cur.execute("SELECT chat_id FROM user_subs WHERE site_url=?", (site_url,))
    return [row[0] for row in cur.fetchall()]

def upsert_user(conn, chat_id, username):
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO users(chat_id, username) VALUES(?,?)", (chat_id, username))
    conn.commit()

def toggle_sub(conn, chat_id, site_url):
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM user_subs WHERE chat_id=? AND site_url=?", (chat_id, site_url))
    if cur.fetchone():
        cur.execute("DELETE FROM user_subs WHERE chat_id=? AND site_url=?", (chat_id, site_url))
        conn.commit()
        return False
    else:
        cur.execute("INSERT OR IGNORE INTO user_subs(chat_id, site_url) VALUES(?,?)", (chat_id, site_url))
        conn.commit()
        return True

def get_user_subs(conn, chat_id):
    cur = conn.cursor()
    cur.execute("SELECT site_url FROM user_subs WHERE chat_id=?", (chat_id,))
    return {row[0] for row in cur.fetchall()}

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
        else:
            send_telegram(chat_id, "Komutlar: /start, /sites")

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
            r = http_get(f"{API}/getUpdates", params={"timeout": 25, "offset": offset+1}, timeout=30)
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
                # 1) E-postayı abonelerden bağımsız gönder
                if SMTP_HOST:
                    em_html = email_template(site.get('name',''), final_title, link, snippet, date_str)
                    ok_email = send_email(f"Yeni duyuru - {site.get('name')}", em_html)
                    logging.info("Email gönderimi: %s", "OK" if ok_email else "FAIL")

                # 2) Telegram sadece abone varsa gönderilsin
                subscribers = get_subscribers(conn, base)
                if subscribers:
                    text_msg = format_tg(site.get('name',''), final_title, link, snippet, date_str)
                    for chat_id in subscribers:
                        resp = send_telegram(chat_id, text_msg)
                        safe_remove_subscription_on_forbidden(conn, chat_id, base, resp)

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
    conn = init_db()
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
