import time, threading, logging, html
from config import (TELEGRAM_BOT_TOKEN, CHECK_INTERVAL_SEC, DB_PATH, ADMIN_CHAT_ID,
                    SMTP_HOST, TO_EMAIL)
from storage.db import (init_db, insert_seen, get_subscribers, get_user_subs)
from storage import db as dbmod
from scraper.site_monitor import (load_sites_yaml, fetch_list_html, extract_list_links,
                                  filter_links, extract_detail)
from formatters.textfmt import text_hash, clean_text, format_telegram, email_html
from notifiers.telegram_bot import bot_poll_loop, send_telegram
from notifiers.emailer import send_email_single

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

def notify_one_site(conn, site):
    base = site["url"]
    list_selector = site.get("list_selector","").strip()
    item_link_selector = site.get("item_link_selector","a").strip()
    include_url_regex = site.get("include_url_regex")
    exclude_text_regex = site.get("exclude_text_regex")
    detail_selector    = site.get("detail_selector")

    logging.info("Kontrol: %s", base)
    html_list = fetch_list_html(base)
    if not html_list: return

    items = extract_list_links(html_list, list_selector, item_link_selector, base)
    items = filter_links(items, include_url_regex, exclude_text_regex)
    if not items:
        logging.info("Item yok/filtre sonrası boş: %s", base)
        return

    for it in items:
        link = it["url"]; title_from_list = it["title"][:200]
        # detay
        list_html = fetch_list_html(link)
        if not list_html: continue
        title_det, body, date_str = extract_detail(list_html, detail_selector)
        final_title = (title_det or title_from_list or "").strip()[:200]
        snippet = clean_text(body, limit=1000)
        h = text_hash(link)

        if not insert_seen(conn, base, h, final_title, link):
            continue  # daha önce görülmüş

        # Telegram
        subscribers = get_subscribers(conn, base)
        if subscribers:
            text_msg = format_telegram(site.get('name',''), final_title, link, snippet, date_str)
            for cid in subscribers:
                send_telegram(cid, text_msg)

        # E-posta (kullanıcıların kendi kayıtları + opsiyonel global TO_EMAIL)
        if SMTP_HOST:
            email_set = set()
            if subscribers:
                q = "SELECT email FROM email_subs WHERE chat_id IN ({})".format(
                    ",".join(["?"]*len(subscribers))
                )
                cur = conn.cursor(); cur.execute(q, tuple(subscribers))
                for (em,) in cur.fetchall(): email_set.add(em)
            if TO_EMAIL:
                for em in [a.strip() for a in TO_EMAIL.split(",") if a.strip()]:
                    email_set.add(em)
            if email_set:
                em_html = email_html(site.get('name',''), final_title, link, snippet, date_str)
                subject = f"Yeni duyuru - {site.get('name')}"
                for em in sorted(email_set):
                    send_email_single(subject, em_html, em)

def monitor_loop(conn):
    logging.info("Monitor loop started.")
    while True:
        sites = load_sites_yaml()
        for s in sites:
            try:
                notify_one_site(conn, s)
            except Exception:
                logging.exception("Site işlenirken hata")
            time.sleep(1.2)
        logging.info("Tüm siteler tarandı. %d sn uyku.", CHECK_INTERVAL_SEC)
        time.sleep(CHECK_INTERVAL_SEC)

if __name__ == "__main__":
    if not TELEGRAM_BOT_TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN .env'de yok.")

    conn = init_db(DB_PATH)
    sites = load_sites_yaml()

    # (opsiyonel) admin seed
    if ADMIN_CHAT_ID.isdigit():
        cur = conn.cursor()
        cur.execute("INSERT OR IGNORE INTO users(chat_id, username) VALUES(?,?)", (int(ADMIN_CHAT_ID), "admin"))
        for s in sites:
            cur.execute("INSERT OR IGNORE INTO user_subs(chat_id, site_url) VALUES(?,?)", (int(ADMIN_CHAT_ID), s["url"]))
        conn.commit()
        logging.info("ADMIN_CHAT_ID seedlendi: %s", ADMIN_CHAT_ID)

    # bot + monitor paralel
    t1 = threading.Thread(target=bot_poll_loop, args=(conn, sites), daemon=True)
    t1.start()
    monitor_loop(conn)
