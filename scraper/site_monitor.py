import yaml, logging, re
from bs4 import BeautifulSoup
from typing import Dict, List, Tuple
from scraper.fetcher import fetch, fetch_js, needs_js, absolute_url
from formatters.textfmt import clean_text, try_parse_tr_date

def load_sites_yaml():
    with open("sites.yaml","r",encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data["sites"]

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
        if not url or len(title) < 5: continue
        links.append({"title": title, "url": url})
    seen, uniq = set(), []
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
    soup = BeautifulSoup(html_text, "html.parser")
    node = soup.select_one(detail_selector) if detail_selector else None
    if not node:
        candidates = soup.select("article, main, .content, .post, .entry, #content, .gdlr-core-single-blog-content, .gdlr-core-blog-content") or [soup.body or soup]
        node = max(candidates, key=lambda n: len(n.get_text(strip=True)))
    # başlık
    title = None
    h = node.find(["h1","h2","h3"]) if node else None
    if h: title = h.get_text(strip=True)

    # tarih
    date_text = None
    date_node = soup.select_one(".gdlr-core-blog-info-date, .date, time")
    if date_node:
        date_text = date_node.get_text(" ", strip=True)
    else:
        date_text = try_parse_tr_date(soup.get_text(" ", strip=True))
    if date_text:
        parsed = try_parse_tr_date(date_text)
        if parsed: date_text = parsed

    snippet = node.get_text(separator="\n").strip() if node else soup.get_text(separator="\n").strip()
    return (title or None), clean_text(snippet, limit=1600), (date_text or None)

def fetch_list_html(url: str):
    html_list = ""
    try:
        html_list = fetch(url)
    except Exception as e:
        logging.warning("Statik çekilemedi: %s", e)
    if not html_list or needs_js(html_list):
        try:
            html_list = fetch_js(url)
        except Exception as e:
            logging.warning("Playwright başarısız: %s", e)
            return None
    return html_list
