import os, smtplib
from email.message import EmailMessage
from dotenv import load_dotenv

load_dotenv()

SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT","587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
FROM_EMAIL = os.getenv("FROM_EMAIL")
TO_EMAIL   = os.getenv("TO_EMAIL")

def send_email(subject, body_html) -> bool:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = FROM_EMAIL
    msg["To"] = TO_EMAIL.split(",") 
    msg.set_content("HTML desteklemeyen istemciler için düz metin.")
    msg.add_alternative(body_html, subtype="html")
    
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as smtp:
            smtp.starttls()
            smtp.login(SMTP_USER, SMTP_PASS)
            smtp.send_message(msg)
        return True
    except Exception as e:
        print("SMTP hatası:", e)
        return False

if __name__ == "__main__":
    ok = send_email(
        "✅ SMTP Test",
        "<h2>SMTP testi başarılıysa bu mail geldi demektir.</h2><p>Selam!</p>"
    )
    print("Sonuç:", ok)
