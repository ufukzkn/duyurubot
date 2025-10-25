# duyurubot – Telegram + E‑posta ile duyuru takipçisi

Bu proje, belirlediğiniz web sitelerindeki yeni duyuruları periyodik olarak tarar, Telegram botu üzerinden abone olan kullanıcılara gönderir ve isteğe bağlı olarak SMTP ile e‑posta bildirimi yollar. İçerik tekilleştirilir (aynı link ikinci kez gönderilmez) ve basit bir abonelik arayüzü Telegram üzerinden sunulur.

## Özellikler

- Siteleri statik olarak çeker, gerekli görülürse Playwright ile JS render (opsiyonel fallback)
- Telegram bot arayüzü: /start, /sites, /emails, /email add/remove
- E‑posta bildirimi: Kişisel e‑posta abonelikleri + opsiyonel global TO_EMAIL
- SQLite veritabanı ile durum yönetimi (görülen öğeler, kullanıcılar, abonelikler, bot offset)

## Klasör yapısı

```text
config.py            # .env ve temel ayarlar (TOKEN, SMTP, vs.)
monitor.py           # Orkestrasyon: bot döngüsü + site izleme döngüsü

formatters/
  textfmt.py         # Metin düzenleme, tarih tespiti, Telegram/e‑posta formatları

notifiers/
  telegram_bot.py    # Telegram Bot API, komutlar ve inline menüler
  emailer.py         # SMTP ile tek alıcıya e‑posta gönderimi

scraper/
  fetcher.py         # HTTP çekme, JS fallback (Playwright), URL normalize
  site_monitor.py    # sites.yaml okumak, liste/detay çıkarımı, filtreleme

storage/
  db.py              # SQLite tablo kurulumları ve CRUD yardımcıları

sites.yaml           # İzlenecek siteler ve seçiciler
test_telegram.py     # Telegram gönderim testi
test_email.py        # SMTP testi
```

## Gerekli önkoşullar

- Python 3.10+ (önerilir)
- Windows PowerShell örnek komutları aşağıdadır

Gerekli paketleri kurun (requirements.txt boşsa):

```powershell
pip install requests beautifulsoup4 python-dotenv pyyaml
# JS ağırlıklı sayfalar için Playwright (opsiyonel)
pip install playwright
python -m playwright install
```

## .env ayarları (config.py tarafından okunur)

```ini
TELEGRAM_BOT_TOKEN=123456:ABCDEF...
CHECK_INTERVAL_SEC=600
DB_PATH=monitor.db

# SMTP (opsiyonel – e‑posta bildirimleri için)
SMTP_HOST=smtp.office365.com
SMTP_PORT=587
SMTP_USER=example@domain.com
SMTP_PASS=app_password_or_smtp_password
FROM_EMAIL=example@domain.com

# Opsiyonel: her e‑postaya eklenecek ekstra alıcı(lar) (virgülle ayır)
TO_EMAIL=me@domain.com,team@domain.com

# Opsiyonel: başlangıçta tüm sitelere abone edilecek kullanıcı
ADMIN_CHAT_ID=123456789
```

## sites.yaml formatı

```yaml
sites:
  - name: "Estü Kariyer Birimi"
    url: "https://kariyer.eskisehir.edu.tr/tr/Duyuru"
    list_selector: ""
    item_link_selector: ".gdlr-core-item-list .gdlr-core-blog-title a, .gdlr-core-item-list .gdlr-core-excerpt-read-more"
    include_url_regex: "/tr/Duyuru/Detay/"
    exclude_text_regex: "anasayfa|hakkımızda|ekibimiz|organizasyon|faaliyet|komisyon|türkçe|english"
    detail_selector: ".gdlr-core-single-blog-content, .gdlr-core-blog-content, .gdlr-core-pbf-element"

  - name: "Estü Ceng"
    url: "https://ceng.eskisehir.edu.tr/tr/Duyuru"
    list_selector: ""
    item_link_selector: ".gdlr-core-item-list .gdlr-core-blog-title a, .gdlr-core-item-list .gdlr-core-excerpt-read-more"
    include_url_regex: "/tr/Duyuru/Detay/"
    exclude_text_regex: "anasayfa|bölüm|müfredat|personel|english|türkçe"
    detail_selector: ".gdlr-core-single-blog-content, .gdlr-core-blog-content, .gdlr-core-pbf-element"
```

Alanlar:
- name: Bildirimlerde görünen site adı
- url: Liste sayfası (ve/veya detay linki kaynağı)
- list_selector: Liste container seçicisi (boş olursa tüm sayfa)
- item_link_selector: İlan linklerini seçmek için CSS seçici
- include_url_regex / exclude_text_regex: İsteğe bağlı filtreler
- detail_selector: Detay içeriği için spesifik container varsa

## Çalıştırma

```powershell
python monitor.py
```

İlk çalıştırmada ADMIN_CHAT_ID ayarlıysa bu kullanıcıyı tüm sitelere abone eder. Telegram üzerinden bota yazışmak için kullanıcının önce bota “/start” yazması gerekir; aksi halde bireysel mesajlarda 403 hatası alınır.

## Telegram bot komutları

- /start: Karşılama ve site seçimleri menüsü
- /sites: Takip etmek istediğiniz siteleri aç/kapat
- /emails: E‑posta aboneliklerini görüntüle/menü
- /email add adres@ornek.com
- /email remove adres@ornek.com

## Testler

Hızlı doğrulama için:

```powershell
python test_telegram.py   # Telegram test mesajı yollar
python test_email.py      # SMTP test e‑postası yollar
```

## Veritabanı ve kalıcılık

SQLite dosyası varsayılan olarak `monitor.db`:
- seen_item: Gönderilen/görülen linklerin tekilleştirilmesi
- users, user_subs: Telegram kullanıcıları ve site abonelikleri
- email_subs: Kullanıcı başına e‑posta abonelikleri
- bot_state: Telegram update offset

Tüm geçmişi sıfırlamak için `monitor.db` dosyasını silmek yeterli (uyarı: tüm geçmiş/abonelikler gider).

## Sorun giderme

- 403 (Forbidden) – “bot can’t initiate conversation with a user”:
	Kullanıcı bota önce `/start` yazmalı veya bir grup/kanal chat_id kullanılmalı.
- JS ağırlıklı sayfa yüklenmiyor:
	`pip install playwright` ve ardından `python -m playwright install` çalıştırın.
- E‑posta gelmiyor:
	SMTP bilgilerini (.env) ve `FROM_EMAIL`/`TO_EMAIL` değerlerini kontrol edin. Loglarda “SMTP error” varsa ayrıntıyı inceleyin.

## Mimari özet

- formatters/textfmt.py: Metin temizleme, tarih çıkarımı, Telegram/e‑posta mesajı oluşturma
- scraper/fetcher.py: requests ile çekme, Playwright fallback, URL normalize
- scraper/site_monitor.py: sites.yaml’a göre liste/detay çıkarımı ve filtreleme
- notifiers/telegram_bot.py: Bot arayüzü, komutlar ve gönderim
- notifiers/emailer.py: SMTP gönderimi
- storage/db.py: SQLite tablo yapıları ve yardımcılar
- monitor.py: Bot döngüsü + tarama döngüsü

