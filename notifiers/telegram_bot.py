import logging, requests
from typing import Dict, List, Tuple
from config import TELEGRAM_BOT_TOKEN
from storage.db import (get_update_offset, set_update_offset, upsert_user,
                        toggle_site_sub, get_user_subs, list_emails,
                        add_email, remove_email)
API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

def http_post_json(url, payload, timeout=20):
    return requests.post(url, json=payload, timeout=timeout)

def http_get(url, params=None, timeout=30):
    return requests.get(url, params=params, timeout=timeout)

def send_telegram(chat_id, text, reply_markup=None):
    data = {"chat_id": chat_id, "text": text, "parse_mode":"HTML", "disable_web_page_preview": True}
    if reply_markup: data["reply_markup"] = reply_markup
    try:
        r = http_post_json(f"{API}/sendMessage", data, timeout=20)
        if not r.ok:
            try: desc = r.json().get("description","")
            except: desc = r.text[:200]
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

def sites_keyboard(conn, chat_id, sites):
    subs = get_user_subs(conn, chat_id)
    kb = []
    for s in sites:
        url = s["url"]; name = s["name"]
        on = "✅" if url in subs else "➕"
        kb.append([{"text": f"{on} {name}", "callback_data": f"tog|{url}"}])
    kb.append([{"text":"📝 Mesaj abonelikleri", "callback_data":"list"}])
    kb.append([{"text":"📧 E-posta abonelikleri", "callback_data":"emails"}])
    return {"inline_keyboard": kb}

def emails_keyboard(conn, chat_id):
    emails = list_emails(conn, chat_id)
    if not emails:
        txt = "Kayıtlı e-posta yok.\n`/email add adres@example.com` ile ekleyebilirsin."
        return txt, {"inline_keyboard":[[{"text":"↩️ Geri", "callback_data":"back"}]]}
    rows = [[{"text": f"❌ {em}", "callback_data": f"emailrm|{em}"}] for em in emails]
    rows.append([{"text":"➕ Ekle: /email add adres", "callback_data":"noop"}])
    rows.append([{"text":"↩️ Geri", "callback_data":"back"}])
    return "E-posta aboneliklerin:", {"inline_keyboard": rows}

def handle_update(conn, upd, sites_by_url):
    if "message" in upd:
        msg = upd["message"]
        chat_id = msg["chat"]["id"]
        username = msg["from"].get("username") or ""
        upsert_user(conn, chat_id, username)

        text = (msg.get("text","") or "").strip()
        if text.startswith("/start"):
            send_telegram(chat_id,
                "Merhaba! 👋 Aşağıdan takip etmek istediğin siteleri seçebilirsin.\n\n"
                "Komutlar: /sites - Siteleri yönet, /emails - E-posta abonelikleri, ",
                reply_markup=sites_keyboard(conn, chat_id, list(sites_by_url.values()))
            )
        elif text.startswith("/sites"):
            send_telegram(chat_id,
                "Takip etmek istediğin siteleri seç/toggle et:",
                reply_markup=sites_keyboard(conn, chat_id, list(sites_by_url.values()))
            )
        elif text.startswith("/emails"):
            txt, kb = emails_keyboard(conn, chat_id)
            send_telegram(chat_id, txt, reply_markup=kb)
        elif text.startswith("/email "):
            parts = text.split()
            if len(parts) >= 3:
                cmd, addr = parts[1].lower(), parts[2].strip()
                if cmd == "add":
                    ok, msgt = add_email(conn, chat_id, addr); send_telegram(chat_id, msgt)
                elif cmd in ("remove","rm","del"):
                    ok, msgt = remove_email(conn, chat_id, addr); send_telegram(chat_id, msgt)
                else:
                    send_telegram(chat_id, "Kullanım: /email add <adres> | /email remove <adres>")
            else:
                send_telegram(chat_id, "Kullanım: /email add <adres> | /email remove <adres>")
        else:
            send_telegram(chat_id, "Komutlar: /start, /sites, /emails, /email add <a>, /email remove <a>")

    elif "callback_query" in upd:
        cb = upd["callback_query"]; cb_id = cb["id"]
        data = cb.get("data",""); chat_id = cb["message"]["chat"]["id"]
        if data == "list":
            subs = get_user_subs(conn, chat_id)
            if not subs: txt = "Seçili siten yok."
            else:
                names = [sites_by_url[u]["name"] for u in subs if u in sites_by_url]
                txt = "Seçili sitelerin:\n• " + "\n• ".join(names)
            answer_callback_query(cb_id, "Liste")
            send_telegram(chat_id, txt); return
        if data == "emails":
            txt, kb = emails_keyboard(conn, chat_id)
            answer_callback_query(cb_id, "E-posta")
            send_telegram(chat_id, txt, reply_markup=kb); return
        if data == "back":
            answer_callback_query(cb_id, "Geri")
            send_telegram(chat_id, "Menü:", reply_markup=sites_keyboard(conn, chat_id, list(sites_by_url.values()))); return
        if data == "noop":
            answer_callback_query(cb_id, "Komutu yaz: /email add <adres>"); return
        if data.startswith("emailrm|"):
            em = data.split("|",1)[1]
            remove_email(conn, chat_id, em)
            txt, kb = emails_keyboard(conn, chat_id)
            answer_callback_query(cb_id, "Silindi")
            send_telegram(chat_id, txt, reply_markup=kb); return
        if data.startswith("tog|"):
            site_url = data.split("|",1)[1]
            if site_url not in sites_by_url:
                answer_callback_query(cb_id, "Site bulunamadı"); return
            toggle_site_sub(conn, chat_id, site_url)
            answer_callback_query(cb_id, "Güncellendi")
            send_telegram(chat_id, "Güncellendi ✔️",
                reply_markup=sites_keyboard(conn, chat_id, list(sites_by_url.values()))
            )

def bot_poll_loop(conn, sites, get_updates_fn=http_get, set_off_fn=set_update_offset, get_off_fn=get_update_offset):
    sites_by_url = {s["url"]: s for s in sites}
    offset = get_off_fn(conn)
    logging.info("Bot loop started.")
    while True:
        try:
            r = get_updates_fn(f"{API}/getUpdates", params={"timeout": 25, "offset": offset+1}, timeout=30)
            if r.ok:
                data = r.json()
                for upd in data.get("result", []):
                    offset = max(offset, upd["update_id"])
                    handle_update(conn, upd, sites_by_url)
                set_off_fn(conn, offset)
        except Exception:
            logging.exception("Bot loop error")
