import smtplib, logging
from email.message import EmailMessage
from typing import Iterable
from config import SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, FROM_EMAIL

def send_email_single(subject: str, body_html: str, recipient: str) -> bool:
    if not (SMTP_HOST and SMTP_USER and SMTP_PASS and FROM_EMAIL and recipient):
        return False
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = FROM_EMAIL
    msg["To"] = recipient
    msg.set_content("HTML istemcisi olmayanlar için düz metin.")
    msg.add_alternative(body_html, subtype="html")
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as smtp:
            smtp.starttls()
            smtp.login(SMTP_USER, SMTP_PASS)
            smtp.send_message(msg, from_addr=FROM_EMAIL, to_addrs=[recipient])
        return True
    except Exception:
        logging.exception("SMTP error to %s", recipient)
        return False
