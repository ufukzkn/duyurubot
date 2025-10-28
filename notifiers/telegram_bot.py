import logging, requests, html
from typing import Dict, List, Tuple
from config import TELEGRAM_BOT_TOKEN
from storage.db import (get_update_offset, set_update_offset, upsert_user,
                        toggle_site_sub, get_user_subs, list_emails,
                        add_email, remove_email, get_last_items_for_user)

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

def _display_name(obj):
    """
    Kullanıcı adı belirler:
    - username varsa @username
    - yoksa first_name + last_name
    - en sonda boş string
    """
    if not obj: return ""
    u = obj.get("username") or ""
    if u: return u
    first = obj.get("first_name") or ""
    last  = obj.get("last_name") or ""
    full = (first + " " + last).strip()
    return full

def sites_keyboard(conn, chat_id, sites):
    subs = get_user_subs(conn, chat_id)
    kb = []
    for s in sites:
        url = s["url"]; name = s["name"]
        on = "✅" if url in subs else "➕"
        kb.append([{"text": f"{on} {name}", "callback_data": f"tog|{url}"}])
    kb.append([{"text":"📝 Mesaj abonelikleri", "callback_data":"list"}])
    kb.append([{"text":"📧 E-posta abonelikleri", "callback_data":"emails"}])
    # Yeni: Son duyurular
    kb.append([{"text":"🕘 Son duyurular", "callback_data":"last"}])
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
    # --- normal mesaj ---
    if "message" in upd:
        msg = upd["message"]
        chat_id = msg["chat"]["id"]

        # username üret ve kaydet (boşsa üzerine yazmayacağız; db fonksiyonu hallediyor)
        uname = _display_name(msg.get("from") or {}) or _display_name(msg.get("chat") or {})
        upsert_user(conn, chat_id, uname)

        text = (msg.get("text","") or "").strip()
        if text.startswith("/start"):
            send_telegram(
                chat_id,
                "Merhaba! 👋 Aşağıdan takip etmek istediğin siteleri seçebilirsin.\n\n"
                "Komutlar:\n"
                "/sites – Siteleri yönet\n"
                "/emails – E‑posta abonelikleri\n"
                "/email add &lt;e-posta&gt; – E‑posta aboneliği ekle\n"
                "/email remove &lt;e-posta&gt; – E‑posta aboneliği kaldır\n"
                "/last [n] [site:&lt;anahtar&gt;] – Son n duyuruyu göster (varsayılan n=5)",
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
        elif text.startswith("/last"):
            # /last [n] [site:<anahtar>]
            parts = text.split()
            want = 5
            site_kw = None

            # argümanları tara
            for p in parts[1:]:
                low = p.lower()
                if low.startswith("site:"):
                    site_kw = p.split(":", 1)[1].strip().lower()
                else:
                    try:
                        want = int(p)
                    except:
                        pass
            if want < 1: want = 1
            if want > 10: want = 10

            # abone olunan siteler
            subs = get_user_subs(conn, chat_id)
            if not subs:
                send_telegram(chat_id, "Seçili siten yok. Önce /sites ile seçim yap.")
                return

            # sites_by_url içinden filtre üret (name veya url içinde geçsin)
            def _match(url: str) -> bool:
                if not site_kw:
                    return True
                site = sites_by_url.get(url) or {}
                name = (site.get("name") or "").lower()
                return (site_kw in name) or (site_kw in url.lower())

            allowed = {u for u in subs if _match(u)}

            items = get_last_items_for_user(conn, chat_id, limit=want, allowed_site_urls=allowed if site_kw else None)

            if not items:
                send_telegram(chat_id, "Uygun duyuru bulunamadı.")
                return

            # Tek mesajda derle
            lines = ["🕘 <b>Son duyurular</b>"]
            for it in items:
                su = it.get("site_url") or ""
                nm = (sites_by_url.get(su) or {}).get("name") or su
                title = it.get("title") or ""
                url = it.get("url") or ""
                lines.append(
                    f"• <b>{html.escape(nm)}</b>\n  <a href=\"{html.escape(url)}\">{html.escape(title)}</a>"
                )

            if site_kw:
                lines.insert(1, f"(Filtre: <i>{html.escape(site_kw)}</i>, adet: {len(items)})")
            else:
                lines.insert(1, f"Abone olunan son {len(items)} duyuru:")

            # ↩️ Geri butonu (callback_data: back) — mevcut 'back' handler'ı yakalar
            back_kb = {"inline_keyboard": [[{"text": "↩️ Geri", "callback_data": "back"}]]}
            send_telegram(chat_id, "\n\n".join(lines), reply_markup=back_kb)
        else:
            send_telegram(chat_id, "Komutlar: /start, /sites, /emails, /email add <a>, /email remove <a>, /last")

    # --- inline callback ---
    elif "callback_query" in upd:
        cb = upd["callback_query"]; cb_id = cb["id"]
        data = cb.get("data",""); chat_id = cb["message"]["chat"]["id"]

        # callback'te de kullanıcı kaydını/username'ini tazele
        uname = _display_name(cb.get("from") or {}) or _display_name(cb.get("message", {}).get("chat") or {})
        upsert_user(conn, chat_id, uname)

        if data == "list":
            subs = get_user_subs(conn, chat_id)
            if not subs: txt = "Seçili siten yok."
            else:
                # Kaynak (sites.yaml) sırasını koru
                names = [s["name"] for s in sites_by_url.values() if s["url"] in subs]
                txt = "Son duyurularda listelenen ve bildirim almayı seçtiğin sitelerin:\n\n• " + "\n• ".join(names)
            kb = {"inline_keyboard": [[{"text": "↩️ Geri", "callback_data": "back"}]]}
            answer_callback_query(cb_id, "Liste")
            send_telegram(chat_id, txt, reply_markup=kb); return

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
        if data == "last":
            answer_callback_query(cb_id, "Son duyurular")
            # Abone olunan siteler
            subs = get_user_subs(conn, chat_id)
            if not subs:
                send_telegram(chat_id, "Seçili siten yok. Önce /sites ile seçim yap.",
                              reply_markup={"inline_keyboard": [[{"text":"↩️ Geri","callback_data":"back"}]]})
                return
            # Son 5 duyuru (abonelikler join ile zaten filtreli)
            items = get_last_items_for_user(conn, chat_id, limit=5)
            if not items:
                send_telegram(chat_id, "Uygun duyuru bulunamadı.",
                              reply_markup={"inline_keyboard": [[{"text":"↩️ Geri","callback_data":"back"}]]})
                return
            lines = ["🕘 <b>Son duyurular</b>", "Abone olunan son {} duyuru:".format(len(items))]
            for it in items:
                su = it.get("site_url") or ""
                nm = (sites_by_url.get(su) or {}).get("name") or su
                title = it.get("title") or ""
                url = it.get("url") or ""
                lines.append(f"• <b>{html.escape(nm)}</b>\n  <a href=\"{html.escape(url)}\">{html.escape(title)}</a>")
            back_kb = {"inline_keyboard": [[{"text": "↩️ Geri", "callback_data": "back"}]]}
            send_telegram(chat_id, "\n\n".join(lines), reply_markup=back_kb); return

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
                    # önce offset'i yükseltip kaydet (aynı update tekrar işlenmesin)
                    offset = max(offset, upd["update_id"])
                    set_off_fn(conn, offset)
                    # sonra işle
                    handle_update(conn, upd, sites_by_url)
        except Exception:
            logging.exception("Bot loop error")
