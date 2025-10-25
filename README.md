# duyurubot – Telegram + E-posta duyuru takipçisi

## Özellikler
- Sitelerden yeni duyuruları periyodik olarak tarar (statik + gerekirse Playwright ile JS render)
- Telegram botu ile kullanıcılar abonelik yönetir (/start, /sites)
- Telegram’dan e-posta adresi yönetimi (/email, `email add`, `email remove`)
- Her site için abone olan kullanıcıların e-postalarına duyuru gönderir
- Duyurular tekilleştirilir (link bazlı) ve tekrar gönderilmez

## Kurulum (Windows, PowerShell)

- Python 3.10+ kurulu olsun.

- Gerekli paketleri yükleyin:
  - `pip install -r requirements.txt`
  - Playwright tarayıcılarını kurun: `python -m playwright install`

- .env dosyası oluşturun (aynı klasörde):

```ini
TELEGRAM_BOT_TOKEN=123456:ABCDEF...
CHECK_INTERVAL_SEC=600
DB_PATH=monitor.db

# SMTP (opsiyonel ama e-posta istiyorsanız gerekli)
SMTP_HOST=smtp.office365.com
SMTP_PORT=587
SMTP_USER=example@domain.com
SMTP_PASS=app_password_or_smtp_password
FROM_EMAIL=example@domain.com

# Opsiyonel: başlangıç için bir kullanıcıyı tüm sitelere abone et
# Bu kullanıcı Telegram’da bota /start demeden de abone edilir
ADMIN_CHAT_ID=123456789

# Opsiyonel: Tüm e-postalara ayrıca şu adresleri de ekle (virgülle ayır)
# Örn: TO_EMAIL=me@domain.com,team@domain.com
TO_EMAIL=
```

- `sites.yaml` dosyasını düzenleyin. Örnek yapı:

```yaml
sites:
  - name: "Birim Duyuruları"
    url: "https://ornek.edu.tr/duyurular"
    list_selector: "#duyuru-listesi"
    item_link_selector: "a"
    # include_url_regex / exclude_text_regex isteğe bağlı filtreler
    # detail_selector detay içeriği için spesifik bir container varsa belirtin
```

## Çalıştırma

- Bot ve monitor aynı süreçte çalışır:
  - `python monitor.py`

## Telegram bot komutları

- /start: Karşılama ve site seçimleri menüsü
- /sites: Takip etmek istediğiniz siteleri aç/kapat
- /email: Kayıtlı e-postaları listeler ve kullanım bilgisini gösterir
  - `email add adres@ornek.com`
  - `email remove adres@ornek.com`

## Notlar

- Telegram’dan bireysel kullanıcıya mesaj gönderebilmek için kullanıcının önce bota `/start` yazması gerekir. Aksi halde 403 hatası alınır.
- Duyurular link’e göre tekilleştirilir; aynı link ikinci kez gönderilmez.
- İlk testte veritabanını sıfırlamak isterseniz `monitor.db` dosyasını silin (uyarı: tüm geçmiş gider).

## Testler

- Telegram testi: `python test_telegram.py`
- E-posta testi: `python test_email.py`

## Sorun Giderme

- 403 (Forbidden) – “bot can’t initiate conversation with a user”: Kullanıcı bota `/start` yazmalı ya da bir grup/kanal chat_id kullanılmalı.
- JS ağırlıklı sayfa: Playwright otomatik devreye girer. Kurulu değilse `python -m playwright install` çalıştırın.
- E-posta gelmiyor: SMTP ayarlarını ve `FROM_EMAIL`/`TO_EMAIL` değerlerini kontrol edin. Loglarda “SMTP config eksik” mesajı görüyorsanız .env’i doldurun.

## Mimari

- messaging.py: Telegram API ve mesaj formatlama (HTML, 429 backoff)
- mailer.py: SMTP ile e-posta gönderimi
- scraper.py: HTTP çekme (requests), gerektiğinde Playwright, HTML parse (BeautifulSoup)
- subscriptions.py: SQLite ile durum ve abonelik yönetimi
- monitor.py: Orkestrasyon – bot döngüsü, tarama döngüsü, site işleme

