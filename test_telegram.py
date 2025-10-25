import os, requests
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram(text: str) -> bool:
    if not TOKEN or not CHAT_ID:
        print("TOKEN/CHAT_ID yok.")
        return False
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        r = requests.post(url, data={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=10)
        print("HTTP", r.status_code, r.text[:200])
        return r.ok
    except Exception as e:
        print("Telegram hatası:", e)
        return False

if __name__ == "__main__":
    ok = send_telegram("✅ Telegram testi: Merhaba!")
    print("Sonuç:", ok)
