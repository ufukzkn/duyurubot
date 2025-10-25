import yaml, requests
from bs4 import BeautifulSoup

COMMON_HINTS = ['announ', 'duyur', 'news', 'post', 'item', 'list', 'entry', 'haber']

def load_sites():
    with open("sites.yaml","r",encoding="utf-8") as f:
        return yaml.safe_load(f)

def save_selector(site_url, selector):
    data = load_sites()
    for s in data["sites"]:
        if s["url"] == site_url:
            s["selector"] = selector
    with open("sites.yaml","w",encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True)

def candidate_selectors_from_dom(soup: BeautifulSoup):
    candidates = []

    # id ve class'larda ipucu içeren elemanlar
    for tag in soup.find_all(True, {"id": True}):
        idv = tag.get("id","")
        if any(h in idv.lower() for h in COMMON_HINTS):
            candidates.append(tag)

    for tag in soup.find_all(True, {"class": True}):
        cls_tokens = tag.get("class") or []
        cls = " ".join(cls_tokens[:3])
        if any(h in cls.lower() for h in COMMON_HINTS):
            candidates.append(tag)

    # liste gibi davranan büyük kapsayıcılar
    for node in soup.find_all(["ul","ol","div","section","main","article"]):
        kids = node.find_all(["li","article","div"], recursive=False)
        if len(kids) >= 3:
            candidates.append(node)

    # tekrarları basitçe ele
    unique = []
    seen = set()
    for c in candidates:
        key = (c.name, c.get("id"), tuple(c.get("class") or []), len((c.get_text() or "")))
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return unique

def guess_selector(node):
    if node.get("id"):
        return f"#{node.get('id')}"
    if node.get("class"):
        classes = node.get("class")
        # çok sınıf varsa ilk 2-3 taneyle başlayalım
        return "." + ".".join(classes[:2])
    # daha genel bir fallback
    return node.name

def show_candidates_for_url(url: str):
    headers = {"User-Agent":"duyuru-monitor/1.0"}
    r = requests.get(url, headers=headers, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    cands = candidate_selectors_from_dom(soup)
    out = []
    if not cands:
        print("⚠️ Otomatik aday bulunamadı. Muhtemelen sayfa JS ile yükleniyor veya içerik çok farklı.")
        return out
    print(f"\nAdaylar ({url}):")
    for i, node in enumerate(cands[:12], start=1):
        sel = guess_selector(node)
        text = (node.get_text(separator="\n") or "").strip()
        snippet = "\n".join(text.splitlines()[:8])
        print(f"\n[{i}] selector: {sel}\n--- snippet ---\n{snippet}\n-----------")
        out.append(sel)
    return out

def interactive():
    data = load_sites()
    for s in data["sites"]:
        if s.get("selector"):
            print(f"✓ {s['name']} zaten selector içeriyor: {s['selector']}")
            continue

        print(f"\n+++ {s['name']}\nURL: {s['url']}")
        try:
            options = show_candidates_for_url(s["url"])
        except Exception as e:
            print("Hata:", e)
            continue

        if not options:
            ch = input("Manuel CSS selector girmek ister misin? (y/n): ").strip().lower()
            if ch == "y":
                manual = input("CSS selector: ").strip()
                if manual:
                    save_selector(s["url"], manual)
                    print("Kaydedildi:", manual)
            continue

        choose = input("Seçmek için numara gir, manuel için 'm', atlamak için ENTER: ").strip().lower()
        if choose.isdigit():
            idx = int(choose) - 1
            if 0 <= idx < len(options):
                sel = options[idx]
                save_selector(s["url"], sel)
                print("Kaydedildi:", sel)
        elif choose == "m":
            manual = input("CSS selector: ").strip()
            if manual:
                save_selector(s["url"], manual)
                print("Kaydedildi:", manual)

if __name__ == "__main__":
    interactive()
