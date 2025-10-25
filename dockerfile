# Playwright + Python + Chromium hazır (Ubuntu Jammy, güvenlik patch’leri düzenli)
FROM mcr.microsoft.com/playwright/python:v1.47.2-jammy

# Çalışma dizini
WORKDIR /app

# Python bağımlılıkları
# Not: Bu imajda playwright zaten kurulu ve browserlar hazır.
# requirements.txt içinde "playwright" varsa da sorun olmaz ama imaj boyutunu büyütebilir.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Uygulama dosyaları
COPY . .

# Ortam
ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    DB_PATH=/data/monitor.db

# Veritabanını kalıcı disk olarak tutmak için volume
VOLUME ["/data"]

# Uygulama komutu
CMD ["python", "monitor.py"]
