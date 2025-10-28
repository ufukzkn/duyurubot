import time
import threading
import logging
import html

from config import (
    TELEGRAM_BOT_TOKEN,
    CHECK_INTERVAL_SEC,
    DB_PATH,
    ADMIN_CHAT_ID,
    SMTP_HOST,
    TO_EMAIL,
)
from storage.db import (
    init_db,
    insert_seen,
    get_subscribers,
    get_user_subs,
    get_state,
    set_state,
    del_state,
)
from storage import db as dbmod
from scraper.site_monitor import (
    load_sites_yaml,
    fetch_list_html,
    extract_list_links,
    filter_links,
    extract_detail,
)
from formatters.textfmt import text_hash, clean_text, format_telegram, email_html
from notifiers.telegram_bot import bot_poll_loop, send_telegram
from notifiers.emailer import send_email_single

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def notify_one_site(conn, site) -> int:
    """
    Verilen siteyi tarar, yeni bulunan duyuruları bildirir.
    Dönüş: new_count (yeni duyuru sayısı)
    """
    base = site["url"]
    list_selector = site.get("list_selector", "").strip()
    item_link_selector = site.get("item_link_selector", "a").strip()
    include_url_regex = site.get("include_url_regex")
    exclude_text_regex = site.get("exclude_text_regex")
    detail_selector = site.get("detail_selector")

    logging.info("Kontrol: %s", base)

    html_list = fetch_list_html(base)
    if not html_list:
        logging.info("Liste HTML alınamadı: %s", base)
        return 0

    items = extract_list_links(html_list, list_selector, item_link_selector, base)
    items = filter_links(items, include_url_regex, exclude_text_regex)
    if not items:
        logging.info("Item yok/filtre sonrası boş: %s", base)
        return 0

    new_count = 0

    for it in items:
        link = it["url"]
        title_from_list = it.get("title", "")[:200]

        # Detay sayfasını çek
        list_html = fetch_list_html(link)
        if not list_html:
            continue

        title_det, body, date_str = extract_detail(list_html, detail_selector)
        final_title = (title_det or title_from_list or "").strip()[:200]
        snippet = clean_text(body, limit=1000)

        # Link bazlı tekilleştirme
        h = text_hash(link)
        if not insert_seen(conn, base, h, final_title, link):
            # zaten görülmüş
            continue

        new_count += 1

        # Telegram bildirimleri
        subscribers = get_subscribers(conn, base)
        if subscribers:
            text_msg = format_telegram(site.get("name", ""), final_title, link, snippet, date_str)
            for cid in subscribers:
                send_telegram(cid, text_msg)

        # E-posta (kullanıcıların kendi kayıtları + opsiyonel global TO_EMAIL)
        if SMTP_HOST:
            email_set = set()

            # 1) Abone e-postalarını çek (psycopg3 için ANY(%s), sqlite için IN (?))
            if subscribers:
                try:
                    cur = conn.cursor()
                    try:
                        # psycopg3 (Postgres) yolu
                        cur.execute(
                            "SELECT email FROM email_subs WHERE chat_id = ANY(%s)",
                            (list(subscribers),)
                        )
                    except Exception:
                        # sqlite geri dönüş yolu
                        q = "SELECT email FROM email_subs WHERE chat_id IN ({})".format(
                            ",".join(["?"] * len(subscribers))
                        )
                        cur.execute(q, tuple(subscribers))
                    for row in cur.fetchall():
                        em = row[0]
                        if em:
                            email_set.add(em)
                except Exception:
                    logging.exception("email_subs fetch failed")

            # 2) Global TO_EMAIL (virgülle çoklu)
            if TO_EMAIL:
                for em in [a.strip() for a in TO_EMAIL.split(",") if a.strip()]:
                    email_set.add(em)

            # 3) Gönder
            if email_set:
                em_html = email_html(site.get("name", ""), final_title, link, snippet, date_str)
                subject = f"Yeni duyuru - {site.get('name')}"
                for em in sorted(email_set):
                    ok = send_email_single(subject, em_html, em)
                    if ok:
                        logging.info("SMTP sent to %s", em)
                    else:
                        logging.warning("SMTP send failed to %s", em)

    logging.info("Tamam: %s (yeni: %d)", base, new_count)
    return new_count


def monitor_once(conn) -> int:
    """
    Tek TUR tarama yapar ve toplam yeni duyuru sayısını döndürür.
    - AWS Lambda + EventBridge (cron) tetiklerinde bu fonksiyon çağrılacaktır.
    - Sonsuz döngü yoktur.
    """
    logging.info("Monitor ONCE started.")
    sites = load_sites_yaml()
    total_new = 0
    for idx, s in enumerate(sites, start=1):
        try:
            new_items = notify_one_site(conn, s)
            total_new += new_items
            logging.info(
                "[%d/%d] %s → yeni: %d",
                idx,
                len(sites),
                s.get("name", s.get("url")),
                new_items,
            )
        except Exception:
            logging.exception("Site işlenirken hata")
        # Lambda'da genellikle gecikme istemeyiz; gerekiyorsa kaldırılabilir.
        # time.sleep(1.2)
    logging.info("Monitor ONCE bitti. Toplam yeni: %d", total_new)
    return total_new


def monitor_loop(conn):
    """
    LOKAL/EC2/Heroku worker çalışma modu:
    Sonsuz döngü ile CHECK_INTERVAL_SEC periyodunda sürekli tarama yapar.
    """
    logging.info("Monitor loop started.")
    while True:
        sites = load_sites_yaml()
        total_new = 0
        for idx, s in enumerate(sites, start=1):
            try:
                new_items = notify_one_site(conn, s)
                total_new += new_items
                logging.info(
                    "[%d/%d] %s → yeni: %d",
                    idx,
                    len(sites),
                    s.get("name", s.get("url")),
                    new_items,
                )
            except Exception:
                logging.exception("Site işlenirken hata")
            time.sleep(1.2)
        logging.info("Tur bitti. Toplam yeni: %d. %d sn uyku.", total_new, CHECK_INTERVAL_SEC)
        time.sleep(CHECK_INTERVAL_SEC)


if __name__ == "__main__":
    if not TELEGRAM_BOT_TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN .env'de yok.")

    conn = init_db(DB_PATH)

    # Token değiştiyse offset’i sıfırla (aynı update'in tekrar gelmesini önlemek için)
    tok_h = text_hash(TELEGRAM_BOT_TOKEN)[:16]
    if (get_state(conn, "token_hash") or "") != tok_h:
        del_state(conn, "update_offset")
        set_state(conn, "token_hash", tok_h)
        logging.info("Token değişikliği tespit edildi; update_offset sıfırlandı.")

    sites = load_sites_yaml()

    # (opsiyonel) admin seed
    if ADMIN_CHAT_ID and ADMIN_CHAT_ID.isdigit():
        cur = conn.cursor()
        cur.execute(
            "INSERT OR IGNORE INTO users(chat_id, username) VALUES(?,?)",
            (int(ADMIN_CHAT_ID), "admin"),
        )
        for s in sites:
            cur.execute(
                "INSERT OR IGNORE INTO user_subs(chat_id, site_url) VALUES(?,?)",
                (int(ADMIN_CHAT_ID), s["url"]),
            )
        conn.commit()
        logging.info("ADMIN_CHAT_ID seedlendi: %s", ADMIN_CHAT_ID)

    # LOKAL/EC2 çalıştırma modu (thread + sonsuz loop)
    t1 = threading.Thread(target=bot_poll_loop, args=(conn, sites), daemon=True)
    t1.start()
    monitor_loop(conn)