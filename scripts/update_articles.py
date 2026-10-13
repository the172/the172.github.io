"""
Weekly article updater for the172.github.io

How it works
1. Reads assets/articles.js (the curated list is the database; hand edits are kept).
2. Searches Google News RSS for Kim Won-chul articles on The Hankyoreh English Edition.
3. Resolves each Google News link to the real hani.co.kr URL.
4. Opens the article and keeps it only if the byline is Kim Won-chul.
5. Classifies by the title tag:
   [Reportage] -> reportage, [Interview] -> interview,
   [Correspondent's column] -> column, everything else -> latest only.
6. Adds only NEW articles (existing entries are never overwritten), sorts newest first,
   and keeps the latest 9 in the "Latest" tab.

Standard library only. No pip install needed.
"""
import html
import json
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

ARTICLES_JS = "assets/articles.js"
LATEST_LIMIT = 9          # number of items in the Latest tab
MAX_NEW_CHECKS = 120      # max unseen RSS items to open per run
QUERIES = [
    '"Kim Won-chul" site:english.hani.co.kr',
    '"Kim Won-chul" Hankyoreh English Edition',
]
BYLINE_PATTERNS = [r"kim\s+won[-\s]?chul", r"wonchul\s+kim", r"김원철"]

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

TAGS = [
    ("column", r"\[\s*correspondent[’'`]?s\s+column\s*\]"),
    ("interview", r"\[\s*interview\s*\]"),
    ("reportage", r"\[\s*reportage\s*\]"),
]
TYPE_LABEL = {
    "column": "Correspondent’s Column",
    "interview": "Interview",
    "reportage": "Reportage",
    None: "Analysis",
}


# ---------------------------------------------------------------- helpers
def http_get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace"), r.geturl()


def http_post(url, body, timeout=20):
    req = urllib.request.Request(
        url, data=body.encode("utf-8"), method="POST",
        headers={"User-Agent": UA,
                 "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def article_key(url, title=""):
    m = re.search(r"/(\d{5,})\.html", url or "")
    if m:
        return m.group(1)
    if url:
        return url
    return "t:" + norm_title(title)


def norm_title(t):
    return re.sub(r"[^a-z0-9]+", "", (t or "").lower())


def strip_suffix(t):
    t = re.sub(r"\s*[-|:]\s*(The\s+)?Hankyoreh.*$", "", t, flags=re.I)
    t = re.sub(r"\s*-\s*한겨레.*$", "", t)
    return t.strip()


def classify(title):
    for cat, pat in TAGS:
        if re.search(pat, title, flags=re.I):
            return cat
    return None


def strip_tags(title):
    t = title
    for _, pat in TAGS:
        t = re.sub(pat, "", t, flags=re.I)
    t = re.sub(r"^\s*\[[^\]]{1,40}\]\s*", "", t)   # any other leading [Tag]
    return re.sub(r"\s{2,}", " ", t).strip(" -:")


def rss_date(s):
    months = {m: i for i, m in enumerate(
        "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), 1)}
    m = re.search(r"(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})", s or "")
    if not m:
        return ""
    d, mon, y = m.groups()
    return f"{y}-{months.get(mon, 1):02d}-{int(d):02d}"


# ------------------------------------------------- Google News link decode
def decode_google_news(url):
    """Turn a news.google.com/rss/articles/... link into the publisher URL."""
    if "news.google.com" not in url:
        return url
    art_id = urllib.parse.urlparse(url).path.rstrip("/").split("/")[-1]
    page, _ = http_get(
        f"https://news.google.com/rss/articles/{art_id}?hl=en-US&gl=US&ceid=US:en")
    sg = re.search(r'data-n-a-sg="([^"]+)"', page)
    ts = re.search(r'data-n-a-ts="([^"]+)"', page)
    if not (sg and ts):
        return None
    ctx = [["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1, None, None,
            None, None, None, 0, 1], "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0]
    tsv = int(ts.group(1)) if ts.group(1).isdigit() else ts.group(1)
    inner = ["garturlreq", ctx, art_id, tsv, sg.group(1)]
    envelope = [[["Fbv4je", json.dumps(inner, separators=(",", ":")), None, "generic"]]]
    body = "f.req=" + urllib.parse.quote(json.dumps(envelope, separators=(",", ":")))
    text = http_post("https://news.google.com/_/DotsSplashUi/data/batchexecute", body)
    if "\n\n" in text:
        text = text.split("\n\n", 1)[1]
    text = text.lstrip()
    if text.startswith(")]}'"):
        text = text.split("\n", 1)[1] if "\n" in text else text[4:]
    for row in json.loads(text):
        if isinstance(row, list) and len(row) >= 3 and isinstance(row[2], str):
            try:
                payload = json.loads(row[2])
            except ValueError:
                continue
            if isinstance(payload, list) and payload and payload[0] == "garturlres":
                return payload[1]
    return None


# --------------------------------------------------- Hankyoreh page reader
class MetaParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.meta = {}

    def handle_starttag(self, tag, attrs):
        if tag != "meta":
            return
        a = dict(attrs)
        k = a.get("property") or a.get("name")
        if k and "content" in a and k not in self.meta:
            self.meta[k] = a["content"]


def read_hani(url):
    page, final = http_get(url)
    p = MetaParser()
    p.feed(page)
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", page, flags=re.S | re.I)
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    byline_ok = any(re.search(b, text, flags=re.I) for b in BYLINE_PATTERNS)
    date = ""
    for k in ("article:published_time", "og:regDate", "pubdate", "date"):
        m = re.search(r"(\d{4})[-.]?(\d{2})[-.]?(\d{2})", p.meta.get(k, ""))
        if m:
            date = "-".join(m.groups())
            break
    return {
        "url": final,
        "title": html.unescape(p.meta.get("og:title", "")),
        "dek": html.unescape(p.meta.get("og:description", "")).strip(),
        "date": date,
        "byline_ok": byline_ok,
    }


# ------------------------------------------------------------- data I/O
def load_data():
    with open(ARTICLES_JS, encoding="utf-8") as f:
        s = f.read()
    data = json.loads(s[s.index("{"): s.rindex("}") + 1])
    for k in ("reportage", "interview", "column", "latest"):
        data.setdefault(k, [])
    return data


def save_data(data):
    def sort_key(a):
        return a.get("date", "")
    for k in data:
        data[k].sort(key=sort_key, reverse=True)
    data["latest"] = data["latest"][:LATEST_LIMIT]
    out = ("// Auto-updated weekly by scripts/update_articles.py.\n"
           "// Hand edits are kept: the script only ADDS new articles.\n"
           "window.portfolioArticles = "
           + json.dumps(data, indent=2, ensure_ascii=False) + ";\n")
    with open(ARTICLES_JS, "w", encoding="utf-8") as f:
        f.write(out)


def fetch_rss():
    items, seen = [], set()
    for q in QUERIES:
        url = ("https://news.google.com/rss/search?q=" + urllib.parse.quote(q)
               + "&hl=en-US&gl=US&ceid=US:en")
        try:
            xml, _ = http_get(url)
        except Exception as e:
            print(f"! RSS failed for {q!r}: {e}")
            continue
        for it in ET.fromstring(xml).findall(".//item"):
            title = it.findtext("title", "")
            nt = norm_title(strip_tags(strip_suffix(title)))
            if nt in seen:
                continue
            seen.add(nt)
            items.append({"title": title, "link": it.findtext("link", ""),
                          "date": rss_date(it.findtext("pubDate", ""))})
    items.sort(key=lambda x: x["date"], reverse=True)
    return items


# ------------------------------------------------------------------ main
def run():
    data = load_data()
    known_keys, known_titles = set(), set()
    for lst in data.values():
        for a in lst:
            known_keys.add(article_key(a.get("url", ""), a.get("title", "")))
            for f in ("title", "headline"):
                if a.get(f):
                    known_titles.add(norm_title(strip_tags(a[f])))

    added, checked = 0, 0
    for it in fetch_rss():
        raw = strip_suffix(it["title"])
        if norm_title(strip_tags(raw)) in known_titles:
            continue
        if checked >= MAX_NEW_CHECKS:
            break
        checked += 1
        try:
            real = decode_google_news(it["link"])
            time.sleep(1)
            if not real or "hani.co.kr" not in real:
                print(f"- skip (not Hankyoreh / undecodable): {raw}")
                continue
            info = read_hani(real)
            time.sleep(1)
        except Exception as e:
            print(f"! error on {raw}: {e}")
            continue

        key = article_key(info["url"])
        if key in known_keys:
            continue
        if not info["byline_ok"]:
            print(f"- skip (byline not Kim Won-chul): {raw}")
            continue

        full = strip_suffix(info["title"] or raw)
        cat = classify(full) or classify(raw)
        title = strip_tags(full)
        entry = {"date": info["date"] or it["date"], "title": title,
                 "dek": info["dek"], "url": info["url"]}
        if cat:
            data[cat].append(dict(entry))
        data["latest"].append(dict(entry, type=TYPE_LABEL[cat]))
        known_keys.add(key)
        known_titles.add(norm_title(title))
        added += 1
        print(f"+ added [{TYPE_LABEL[cat]}] {entry['date']} {title}")

    save_data(data)
    print(f"Done. checked={checked}, added={added}")


if __name__ == "__main__":
    run()
