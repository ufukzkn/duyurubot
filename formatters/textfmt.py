import html, hashlib, re

TR_MONTHS = {
    "ocak":1,"şubat":2,"mart":3,"nisan":4,"mayıs":5,"haziran":6,
    "temmuz":7,"ağustos":8,"eylül":9,"ekim":10,"kasım":11,"aralık":12
}

def text_hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def clean_text(s: str, limit=1200) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+\n", "\n", s)
    s = re.sub(r"[ \t]{2,}", " ", s)
    return s[:limit]

def dedupe_lines(text: str) -> str:
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    out, seen = [], set()
    for l in lines:
        low = l.lower()
        if low in seen: continue
        seen.add(low); out.append(l)
    return "\n".join(out)

def try_parse_tr_date(text: str):
    if not text: return None
    t = text.lower()
    m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})(?:\s+(\d{1,2}:\d{2}(?::\d{2})?))?", t)
    if m:
        d, mo, y = map(int, m.groups()[:3]); hhmm = m.group(4) or ""
        return f"{d:02d}.{mo:02d}.{y}" + (f" {hhmm}" if hhmm else "")
    m = re.search(r"(\d{1,2})\s+([a-zçğıöşü]+)\s+(\d{4})", t, flags=re.I)
    if m:
        d = int(m.group(1)); mon = m.group(2).strip(" ,()."); y = int(m.group(3))
        mon_no = TR_MONTHS.get(mon.lower())
        if mon_no: return f"{d:02d}.{mon_no:02d}.{y}"
    return None

def strip_date_and_title_from_snippet(snippet: str, title: str, date_str: str | None):
    lines = [l.strip() for l in (snippet or "").splitlines() if l.strip()]
    out = []
    for l in lines:
        if title and l.lower() == title.strip().lower(): continue
        if date_str and l.strip() == (date_str or "").strip(): continue
        out.append(l)
    return "\n".join(out)

def bulletize(text: str, max_chars=280):
    """
    Metni tek parça halinde kırpar, sonuna '…' ekler.
    """
    clean = " ".join([l.strip() for l in (text or "").splitlines() if l.strip()])
    if len(clean) <= max_chars:
        return clean
    short = clean[:max_chars].rsplit(" ", 1)[0]
    return short.strip() + "…"

def format_telegram(site_name, title, link, snippet, date_str=None):
    title = (title or "").strip()
    snippet = dedupe_lines(snippet or "")
    snippet = strip_date_and_title_from_snippet(snippet, title, date_str)
    preview = bulletize(snippet, max_chars=280)
    parts = [
        f"📢 <b>{html.escape(site_name or 'Duyuru')}</b>",
        f"<b>{html.escape(title)}</b>",
    ]
    if date_str:
        parts.append(f"<i>{html.escape(date_str)}</i>")
    parts.append(f'<a href="{html.escape(link)}">İlana git</a>')
    if preview:
        parts.append("")
        parts.append(html.escape(preview))
    return "\n".join(parts)

def email_html(site_name, title, link, snippet, date_str=None):
    title = (title or "").strip()
    snippet = dedupe_lines(snippet or "")
    snippet = strip_date_and_title_from_snippet(snippet, title, date_str)
    preview = "\n".join([l for l in snippet.splitlines() if l.strip()][:12])
    date_html = f'<div style="color:#6b7280;font-style:italic;margin-top:2px">{html.escape(date_str)}</div>' if date_str else ""
    return f"""<!doctype html><html><body style="margin:0;padding:0;background:#f7f7f7">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f7f7f7">
    <tr><td align="center" style="padding:24px">
      <table role="presentation" width="600" cellspacing="0" cellpadding="0" style="background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.05);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Ubuntu,'Helvetica Neue',Arial,sans-serif;color:#111827">
        <tr><td style="padding:20px 24px;background:#111827;color:#ffffff;font-size:18px;font-weight:600;">{html.escape(site_name or "Yeni duyuru")}</td></tr>
        <tr><td style="padding:24px">
          <h1 style="margin:0 0 8px 0;font-size:20px;line-height:1.3;color:#111827">{html.escape(title)}</h1>
          {date_html}
          <p style="white-space:pre-wrap;margin:16px 0 20px 0;line-height:1.6;color:#111827">{html.escape(preview)}</p>
          <a href="{html.escape(link)}" style="display:inline-block;background:#2563eb;color:#ffffff;text-decoration:none;padding:10px 16px;border-radius:8px;font-weight:600">İlana git</a>
        </td></tr>
        <tr><td style="padding:16px 24px;color:#6b7280;font-size:12px">Bu e-posta otomatik gönderilmiştir.</td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""
