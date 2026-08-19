import json
import os
import textwrap

import requests
from dotenv import load_dotenv

from check_telegram_chat import (
    TelegramLookupError,
    chat_display_name,
    extract_usernames,
    get_chat,
)

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_IDS_RAW = os.getenv("TELEGRAM_CHAT_ID", "")
SEPARATOR = "=" * 72

def parse_chat_ids(raw: str):
    # "id1,id2 ; id3" gibi değerleri parçala, boşları ayıkla, sırayı koruyarak tekilleştir
    parts = [p.strip() for p in raw.replace(";", ",").split(",")]
    parts = [p for p in parts if p]
    # sırayı koruyarak tekilleştir
    return list(dict.fromkeys(parts))


def get_recipient_label(chat_id: str) -> tuple[str, str | None]:
    try:
        chat = get_chat(TOKEN, chat_id)
    except TelegramLookupError as exc:
        return "İsim alınamadı", str(exc)

    display_name = chat_display_name(chat)
    usernames = extract_usernames(chat)
    username = f"@{usernames[0]}" if usernames else None

    if display_name and username:
        return f"{display_name} ({username})", None
    if username:
        return username, None
    if display_name:
        return display_name, None
    return "İsimsiz sohbet", None


def format_response(response: requests.Response) -> str:
    try:
        content = json.dumps(response.json(), ensure_ascii=False, indent=2)
    except ValueError:
        content = response.text or "<boş yanıt>"
    if len(content) > 1500:
        content = content[:1500] + "\n... (yanıt kısaltıldı)"
    return textwrap.indent(content, "    ")


def send_telegram(text: str) -> bool:
    if not TOKEN:
        print("Hata: TELEGRAM_BOT_TOKEN tanımlı değil.")
        return False
    chat_ids = parse_chat_ids(CHAT_IDS_RAW)
    if not chat_ids:
        print("Hata: TELEGRAM_CHAT_ID içinde alıcı yok.")
        return False

    recipients = []
    for chat_id in chat_ids:
        label, lookup_error = get_recipient_label(chat_id)
        recipients.append((chat_id, label, lookup_error))

    print(f"\n{SEPARATOR}")
    print("TELEGRAM TEST GÖNDERİMİ")
    print(SEPARATOR)
    print(f"Mesaj       : {text}")
    print(f"Alıcı sayısı: {len(recipients)}")
    print("\nŞu alıcılara gönderiyorum:")
    for index, (chat_id, label, lookup_error) in enumerate(recipients, start=1):
        print(f"  {index}. {label}")
        print(f"     Chat ID: {chat_id}")
        if lookup_error:
            print(f"     İsim sorgusu uyarısı: {lookup_error}")

    print(f"\n{'-' * 72}")
    print("GÖNDERİM SONUÇLARI")
    print("-" * 72)

    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    success_count = 0
    successful_recipients: list[str] = []
    for index, (chat_id, label, _) in enumerate(recipients, start=1):
        print(f"\n[{index}/{len(recipients)}] {label}")
        print(f"  Chat ID : {chat_id}")
        try:
            response = requests.post(
                url,
                data={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
                timeout=10,
            )
            try:
                api_ok = response.json().get("ok") is True
            except (ValueError, AttributeError):
                api_ok = False
            succeeded = response.ok and api_ok
            if succeeded:
                success_count += 1
                successful_recipients.append(label)
            print(f"  Durum   : {'BAŞARILI' if succeeded else 'BAŞARISIZ'}")
            print(f"  HTTP    : {response.status_code}")
            print("  Yanıt   :")
            print(format_response(response))
        except requests.RequestException as exc:
            # İstisna metni token içeren Bot API URL'sini gösterebilir.
            print("  Durum   : BAŞARISIZ")
            print(f"  Hata    : Telegram bağlantı hatası ({type(exc).__name__})")

    failed_count = len(recipients) - success_count
    print(f"\n{SEPARATOR}")
    print("ÖZET")
    print(SEPARATOR)
    print(f"Başarılı   : {success_count}")
    print(f"Başarısız  : {failed_count}")
    print(f"Toplam     : {len(recipients)}")
    print("\nGönderilen isimler:")
    if successful_recipients:
        for index, label in enumerate(successful_recipients, start=1):
            print(f"  {index}. {label}")
    else:
        print("  (yok)")
    print(SEPARATOR)
    return failed_count == 0

if __name__ == "__main__":
    ok = send_telegram("✅ Telegram testi: Merhaba!")
    print("Genel sonuç:", "BAŞARILI" if ok else "BAŞARISIZ")
