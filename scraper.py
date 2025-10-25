import re
from urllib.parse import urljoin
from bs4 import BeautifulSoup
import requests

HEADERS = {"User-Agent":"duyuru-monitor/1.5 (+github.com/you)"}

def fetch(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=25)
    r.raise_for_status()
    return r.text

def fetch_js(url: str) -> str:
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

def clean_text(s: str, limit=1200) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+\n", "\n", s)
    s = re.sub(r"[ \t]{2,}", " ", s)
    return s[:limit]

def extract_list_links(full_html: str, list_selector: str, item_link_selector: str, base_url: str):
    soup = BeautifulSoup(full_html, "html.parser")
    container = soup.select_one(list_selector) if list_selector else soup
    if not container:
        return []
    links = []
    for a in container.select(item_link_selector):
        title = a.get_text(strip=True) or ""
        href  = a.get("href")
        url   = absolute_url(base_url, href)
        if not url or len(title) < 5:
            continue
        links.append({"title": title, "url": url})
    seen = set(); uniq = []
    for it in links:
        if it["url"] in seen: continue
        seen.add(it["url"]); uniq.append(it)
    return uniq

def filter_links(items, include_url_regex=None, exclude_text_regex=None):
    out = []
    inc = re.compile(include_url_regex, re.I) if include_url_regex else None
    exc = re.compile(exclude_text_regex, re.I) if exclude_text_regex else None
    for it in items:
        t = it["title"]; u = it["url"]
        if inc and not inc.search(u): continue
        if exc and (exc.search(t) or exc.search(u)): continue
        out.append(it)
    return out

def extract_detail(html_text: str, detail_selector: str | None):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html_text, "html.parser")
    node = soup.select_one(detail_selector) if detail_selector else None
    if not node:
        candidates = soup.select("article, main, .content, .post, .entry, #content, .gdlr-core-single-blog-content, .gdlr-core-blog-content") or [soup.body or soup]
        node = max(candidates, key=lambda n: len(n.get_text(strip=True)))
    title = None
    h = node.find(["h1","h2","h3"]) if node else None
    if h: title = h.get_text(strip=True)

    # date (best-effort)
    date_text = None
    date_node = soup.select_one(".gdlr-core-blog-info-date, .date, time")
    if date_node:
        date_text = date_node.get_text(" ", strip=True)

    snippet = node.get_text(separator="\n").strip() if node else soup.get_text(separator="\n").strip()
    return (title or None), clean_text(snippet, limit=1600), (date_text or None)
