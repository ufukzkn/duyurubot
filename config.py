# config.py
import os

# .env sadece lokal geliştirmede iş görsün; Lambda'da yoksa sessizce atla
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except Exception:
    pass

# --- Telegram ---
TELEGRAM_BOT_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_SECRET_TOKEN = os.getenv("TELEGRAM_SECRET_TOKEN", "").strip()  # webhook güvenliği (opsiyonel)

# --- Zamanlama ---
CHECK_INTERVAL_SEC   = int(os.getenv("CHECK_INTERVAL_SEC", "600"))

# --- Veritabanı ---
# Postgres kullanıyorsak: DATABASE_URL (Neon/Supabase pooled DSN)
# Yoksa geriye dönük olarak DB_PATH (örn. lokal/EC2 için SQLite) kullanılabilir.
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
DB_PATH      = os.getenv("DB_PATH", "monitor.db").strip()  # Lambda testinde geçici olarak /tmp/duyuru.db kullanabilirsin

# --- SMTP / E-posta ---
SMTP_HOST   = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT   = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER   = os.getenv("SMTP_USER", "").strip()
SMTP_PASS   = os.getenv("SMTP_PASS", "").strip()
FROM_EMAIL  = os.getenv("FROM_EMAIL", "").strip()
TO_EMAIL    = os.getenv("TO_EMAIL", "").strip()  # virgülle ayrılmış global alıcılar (opsiyonel)

# --- Diğer ---
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "").strip()
USER_AGENT    = os.getenv("USER_AGENT", "duyuru-monitor/2.0 (+github.com/you)").strip()