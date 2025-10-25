import os
from dotenv import load_dotenv
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHECK_INTERVAL_SEC = int(os.getenv("CHECK_INTERVAL_SEC", "600"))
DB_PATH = os.getenv("DB_PATH", "monitor.db")

# Global email (opsiyonel)
SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "").strip()
SMTP_PASS = os.getenv("SMTP_PASS", "").strip()
FROM_EMAIL = os.getenv("FROM_EMAIL", "").strip()
TO_EMAIL   = os.getenv("TO_EMAIL", "").strip()  # virgüllü global alıcılar

ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "").strip()
USER_AGENT = "duyuru-monitor/2.0 (+github.com/you)"
