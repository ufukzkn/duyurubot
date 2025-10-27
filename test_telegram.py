import os, requests
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_IDS_RAW = os.getenv("TELEGRAM_CHAT_ID", "")

def parse_chat_ids(raw: str):
    # "id1,id2 ; id3" gibi değerleri parçala, boşları ayıkla, sırayı koruyarak tekilleştir
    parts = [p.strip() for p in raw.replace(";", ",").split(",")]
    parts = [p for p in parts if p]
    # sırayı koruyarak tekilleştir
    return list(dict.fromkeys(parts))

def send_telegram(text: str) -> bool:
    if not TOKEN:
        print("TOKEN yok.")
        return False
    chat_ids = parse_chat_ids(CHAT_IDS_RAW)
    if not chat_ids:
        print("CHAT_ID yok.")
        return False

    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    all_ok = True
    for cid in chat_ids:
        try:
            r = requests.post(
                url,
                data={"chat_id": cid, "text": text, "parse_mode": "HTML"},
                timeout=10,
            )
            print(f"[{cid}] HTTP {r.status_code} {r.text[:200]}")
            all_ok = all_ok and r.ok
        except Exception as e:
            print(f"[{cid}] Telegram hatası:", e)
            all_ok = False
    return all_ok

if __name__ == "__main__":
    ok = send_telegram("✅ Telegram testi: Merhaba!")
    print("Sonuç:", ok)
