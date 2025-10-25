import os, time, sqlite3, hashlib, logging, threading, requests, smtplib, html, re
from email.message import EmailMessage
from urllib.parse import urljoin
from bs4 import BeautifulSoup
import yaml
from dotenv import load_dotenv


# -------------------- ENV / CONFIG --------------------
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
CHECK_INTERVAL_SEC = int(os.getenv("CHECK_INTERVAL_SEC", "600"))
DB_PATH = os.getenv("DB_PATH", "monitor.db")

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
FROM_EMAIL = os.getenv("FROM_EMAIL", "")
TO_EMAIL   = os.getenv("TO_EMAIL", "")

HEADERS = {"User-Agent":"duyuru-monitor/1.2 (+github.com/you)"}
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

def send_telegram(chat_id, text, reply_markup=None):
    data = {"chat_id": chat_id, "text": text, "parse_mode":"HTML", "disable_web_page_preview": True}
    if reply_markup:
        data["reply_markup"] = reply_markup
    try:
        r = requests.post(f"{API}/sendMessage", json=data, timeout=15)
        if not r.ok:
            logging.warning("Telegram send fail %s %s", r.status_code, r.text[:200])
        return r.ok
    except Exception as e:
        logging.exception("Telegram error")
        return False

def answer_callback_query(cb_id, text=""):
    try:
        requests.post(f"{API}/answerCallbackQuery", json={"callback_query_id": cb_id, "text": text}, timeout=10)
    except Exception:
        pass

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
    # dedupe by url
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
    snippet = node.get_text(separator="\n").strip() if node else soup.get_text(separator="\n").strip()
    return (title or None), clean_text(snippet, limit=1600)

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
    # if exists -> remove, else add
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
    # footer
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
                reply_markup={"inline_keyboard": sites_keyboard(conn, chat_id, list(sites_by_url.values()))["inline_keyboard"]}
            )
        elif text.startswith("/sites"):
            send_telegram(chat_id,
                "Takip etmek istediğin siteleri seç/toggle et:",
                reply_markup={"inline_keyboard": sites_keyboard(conn, chat_id, list(sites_by_url.values()))["inline_keyboard"]}
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
            answer_callback_query(cb_id, "Liste güncellendi")
            send_telegram(chat_id, txt)
            return

        if data.startswith("tog|"):
            site_url = data.split("|",1)[1]
            if site_url not in sites_by_url:
                answer_callback_query(cb_id, "Site bulunamadı")
                return
            enabled = toggle_sub(conn, chat_id, site_url)
            answer_callback_query(cb_id, "Ayar güncellendi")
            # refresh menu
            send_telegram(chat_id, "Güncellendi ✔️",
                reply_markup={"inline_keyboard": sites_keyboard(conn, chat_id, list(sites_by_url.values()))["inline_keyboard"]}
            )

def bot_loop(conn, sites):
    # map for quick lookup
    sites_by_url = {s["url"]: s for s in sites}
    # load/update offset
    cur = conn.cursor()
    cur.execute("SELECT value FROM bot_state WHERE key='update_offset'")
    row = cur.fetchone()
    offset = int(row[0]) if row else 0

    logging.info("Bot loop started.")
    while True:
        try:
            r = requests.get(f"{API}/getUpdates", params={"timeout": 25, "offset": offset+1}, timeout=30)
            if r.ok:
                data = r.json()
                if data.get("ok") and data.get("result"):
                    for upd in data["result"]:
                        offset = max(offset, upd["update_id"])
                        handle_update(conn, upd, sites_by_url)
                    # save offset
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

        title_det, body = extract_detail(detail_html, detail_selector)
        final_title = (title_det or title_from_list or "").strip()[:200]
        snippet = clean_text(body, limit=800)
        preview = "\n".join(snippet.splitlines()[:2])

        # Link bazlı tekilleştirme
        h = text_hash(link)
        try:
            cur.execute("INSERT INTO seen_item(site_url,item_hash,title,url) VALUES(?,?,?,?)",
                        (base, h, final_title, link))
            conn.commit()
            new_count += 1

            if notify:
                subscribers = get_subscribers(conn, base)
                if not subscribers:
                    continue
                safe_title = html.escape(final_title)
                safe_prev  = html.escape(preview)
                text = f"📢 <b>{html.escape(site.get('name','Yeni duyuru'))}</b>\n{safe_title}\n{link}\n\n{safe_prev}"
                for chat_id in subscribers:
                    send_telegram(chat_id, text)

                # e-posta (opsiyonel)
                if SMTP_HOST:
                    em_html = f"""
                    <h2>Yeni duyuru: {html.escape(site.get('name',''))}</h2>
                    <h3>{safe_title}</h3>
                    <pre style="white-space:pre-wrap">{html.escape(snippet)}</pre>
                    <p><a href="{html.escape(link)}">İlana git</a></p>
                    """
                    send_email(f"Yeni duyuru - {site.get('name')}", em_html)

        except sqlite3.IntegrityError:
            # zaten görülmüş
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
    if not TELEGRAM_BOT_TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN .env'de yok.")

    conn = init_db()
    sites = load_sites()

    # Bot ve monitor'u paralel çalıştır
    t1 = threading.Thread(target=bot_loop, args=(conn, sites), daemon=True)
    t1.start()

    monitor_loop(conn)
