import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from config import USER_AGENT
HEADERS = {"User-Agent": USER_AGENT}

def fetch(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=25)
    r.raise_for_status()
    return r.text

def fetch_js(url: str) -> str:
    # Playwright fallback (opsiyonel)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        page = b.new_page()
        page.goto(url, timeout=35000)
        page.wait_for_timeout(1500)
        htmlc = page.content()
        b.close()
    return htmlc

def needs_js(html_text: str) -> bool:
    soup = BeautifulSoup(html_text, "html.parser")
    body_txt = (soup.get_text() or "").strip()
    scripts = len(soup.find_all("script"))
    return scripts > 8 and len(body_txt) < 200

def absolute_url(base: str, href: str | None) -> str | None:
    if not href: return None
    if href.startswith("http://") or href.startswith("https://"): return href
    return urljoin(base, href)
