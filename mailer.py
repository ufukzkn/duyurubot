import os, logging, smtplib
from email.message import EmailMessage
from dotenv import load_dotenv

load_dotenv()

SMTP_HOST = (os.getenv("SMTP_HOST") or "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = (os.getenv("SMTP_USER") or "").strip()
SMTP_PASS = (os.getenv("SMTP_PASS") or "").strip()
FROM_EMAIL = (os.getenv("FROM_EMAIL") or "").strip()

def send_email(to_list, subject: str, body_html: str) -> bool:
    if not (SMTP_HOST and SMTP_USER and SMTP_PASS and FROM_EMAIL):
        logging.info("SMTP config eksik, mail atlanıyor.")
        return False
    recipients = [a.strip() for a in (to_list or []) if a and a.strip()]
    if not recipients:
        logging.info("E-posta alıcısı yok, atlanıyor.")
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
