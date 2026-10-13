"""
Weekly article updater for the172.github.io

Sources (both are used; duplicates are removed):
  1. Hankyoreh English search  (search.hani.co.kr/english, newest first)  <- main
  2. Google News RSS                                                     <- backup

For every NEW article it:
  - opens the article page and keeps it only if the byline is Kim Won-chul
  - classifies it by the title tag:
      [Reportage] -> reportage, [Interview] -> interview,
      [Correspondent's column] -> column, no tag -> Latest only
  - adds it to assets/articles.js (existing entries are never overwritten)
Lists are sorted newest first; the Latest tab keeps the newest 9.

Standard library only. No pip install needed.
"""
import datetime
import html
import json
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

ARTICLES_JS = "assets/articles.js"
LATEST_LIMIT = 9           # items in the Latest tab
SEARCH_PAGES = 3           # Hankyoreh search result pages to scan per run
MAX_NEW_CHECKS = 120       # max new articles to open per run
SEARCH_WORD = "kim won-chul"
RSS_QUERIES = [
    '"Kim Won-chul" site:english.hani.co.kr',
    '"Kim Won-chul" Hankyoreh English Edition',
]

# Byline must look like a byline, not just a mention of the name in the text
BYLINE_PATTERNS = [
    r"\bby\s+(?:[A-Z][\w'-]+(?:\s+[A-Z][\w'-]+)*\s*(?:,|and|&)\s*)*kim\s+won[-\s]?chul",
    r"interview(?:ed)?\s+by\s+kim\s+won[-\s]?chul",
    r"kim\s+won[-\s]?chul\s*,\s*(?:washington\s+)?(?:correspondent|staff\s+reporter|bureau\s+chief)",
    r"kim\s+won[-\s]?chul\s*\|\s*(?:washington\s+)?(?:correspondent|bureau)",
    r"wonchul@hani\.co\.kr",
    r"김원철\s*(?:특파원|기자)",
]

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
ARTICLE_URL_RE = re.compile(
    r"(?:https?:)?(?://(?:www\.|english\.)?hani\.co\.kr)?(/arti/[^\"'\s<>?#]*?/(\d{5,})\.html)")


# ---------------------------------------------------------------- helpers
def http_get(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept-Language": "en-US,en;q=0.9,ko;q=0.8"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        charset = r.headers.get_content_charset() or "utf-8"
        return raw.decode(charset, errors="replace"), r.geturl()


def http_post(url, body, timeout=25):
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


def clean_text(t):
    t = html.unescape(re.sub(r"<[^>]+>", " ", t or ""))
    return re.sub(r"\s+", " ", t).strip()


def strip_suffix(t):
    t = re.sub(r"\s*[-|:]\s*(The\s+)?Hankyoreh.*$", "", t or "", flags=re.I)
    t = re.sub(r"\s*[-|:]\s*한겨레.*$", "", t)
    return t.strip()


def classify(*titles):
    for title in titles:
        for cat, pat in TAGS:
            if title and re.search(pat, title, flags=re.I):
                return cat
    return None


def strip_tags(title):
    t = title or ""
    for _, pat in TAGS:
        t = re.sub(pat, "", t, flags=re.I)
    t = re.sub(r"^\s*\[[^\]]{1,40}\]\s*", "", t)   # any other leading [Tag]
    return re.sub(r"\s{2,}", " ", t).strip(" -:")


def canonical(path):
    return "https://english.hani.co.kr" + path


# --------------------------------------------- source 1: Hankyoreh search
class LinkParser(HTMLParser):
    """Collects (article path, anchor text) from a search result page."""
    def __init__(self):
        super().__init__()
        self.links = {}     # path -> longest anchor text
        self.order = []
        self._href = None
        self._buf = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href") or ""
            m = ARTICLE_URL_RE.search(href)
            self._href = m.group(1) if m else None
            self._buf = []

    def handle_data(self, data):
        if self._href:
            self._buf.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href:
            text = clean_text(" ".join(self._buf))
            if self._href not in self.links:
                self.links[self._href] = ""
                self.order.append(self._href)
            if len(text) > len(self.links[self._href]):
                self.links[self._href] = text
            self._href = None


def fetch_hani_search():
    today = datetime.date.today().strftime("%Y.%m.%d")
    items = []
    seen = set()
    for page in range(1, SEARCH_PAGES + 1):
        params = {"searchword": SEARCH_WORD, "startdate": "1988.01.01",
                  "enddate": today, "sort": "desc"}
        if page > 1:
            params["page"] = str(page)
        url = "https://search.hani.co.kr/english?" + urllib.parse.urlencode(
            params, quote_via=urllib.parse.quote)
        try:
            page_html, _ = http_get(url)
        except Exception as e:
            print(f"! Hankyoreh search page {page} failed: {e}")
            break
        p = LinkParser()
        p.feed(page_html)
        paths = list(p.order)
        # links that are not inside <a> tags (e.g. in scripts) as a fallback
        for m in ARTICLE_URL_RE.finditer(page_html):
            if m.group(1) not in p.links:
                p.links[m.group(1)] = ""
                paths.append(m.group(1))
        new = [x for x in paths if x not in seen]
        print(f"  Hankyoreh search page {page}: {len(new)} article links")
        if not new:
            break
        for path in new:
            seen.add(path)
            items.append({"url": canonical(path), "title": p.links.get(path, ""),
                          "date": ""})
        time.sleep(1)
    return items


# ---------------------------------------------- source 2: Google News RSS
def rss_date(s):
    months = {m: i for i, m in enumerate(
        "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), 1)}
    m = re.search(r"(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})", s or "")
    if not m:
        return ""
    d, mon, y = m.groups()
    return f"{y}-{months.get(mon, 1):02d}-{int(d):02d}"


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


def fetch_rss():
    items, seen = [], set()
    for q in RSS_QUERIES:
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
            items.append({"url": it.findtext("link", ""), "title": title,
                          "date": rss_date(it.findtext("pubDate", ""))})
    items.sort(key=lambda x: x["date"], reverse=True)
    print(f"  Google News RSS: {len(items)} items")
    return items


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
    body = re.sub(r"<script.*?</script>|<style.*?</style>", " ", page, flags=re.S | re.I)
    text = clean_text(body)
    byline_ok = any(re.search(b, text, flags=re.I) for b in BYLINE_PATTERNS) or \
        "wonchul@hani.co.kr" in page.lower()

    # every place a headline (with its [Tag]) may appear
    heads = [html.unescape(p.meta.get("og:title", ""))]
    m = re.search(r"<title[^>]*>(.*?)</title>", page, flags=re.S | re.I)
    if m:
        heads.append(clean_text(m.group(1)))
    heads += [clean_text(h) for h in re.findall(r"<h[1-3][^>]*>(.*?)</h[1-3]>", page,
                                                flags=re.S | re.I)[:4]]

    date = ""
    for k in ("article:published_time", "og:regDate", "pubdate", "date"):
        m = re.search(r"(\d{4})[-.]?(\d{2})[-.]?(\d{2})", p.meta.get(k, ""))
        if m:
            date = "-".join(m.groups())
            break
    if not date:
        m = re.search(r"(20\d{2})[-.](\d{2})[-.](\d{2})\s+\d{1,2}:\d{2}", text)
        if m:
            date = "-".join(m.groups())
    return {
        "url": final,
        "heads": [h for h in heads if h],
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
    data.setdefault("_seen", [])   # ids already checked (not shown on the site)
    return data


def save_data(data):
    for k in ("reportage", "interview", "column", "latest"):
        data[k].sort(key=lambda a: a.get("date", ""), reverse=True)
    data["latest"] = data["latest"][:LATEST_LIMIT]
    data["_seen"] = sorted(set(data["_seen"]), key=lambda x: (len(x), x), reverse=True)
    out = ("// Auto-updated weekly by scripts/update_articles.py.\n"
           "// Hand edits are kept: the script only ADDS new articles.\n"
           "window.portfolioArticles = "
           + json.dumps(data, indent=2, ensure_ascii=False) + ";\n")
    with open(ARTICLES_JS, "w", encoding="utf-8") as f:
        f.write(out)


# ------------------------------------------------------------------ main
def run():
    data = load_data()
    known_keys, known_titles = set(), set()
    known_keys.update(data["_seen"])
    for k in ("reportage", "interview", "column", "latest"):
        for a in data[k]:
            known_keys.add(article_key(a.get("url", ""), a.get("title", "")))
            for f in ("title", "headline"):
                if a.get(f):
                    known_titles.add(norm_title(strip_tags(a[f])))

    candidates = fetch_hani_search() + fetch_rss()
    added = checked = 0
    for it in candidates:
        raw = strip_suffix(it["title"])
        if "news.google.com" not in it["url"] and article_key(it["url"]) in known_keys:
            continue
        if raw and norm_title(strip_tags(raw)) in known_titles:
            continue
        if checked >= MAX_NEW_CHECKS:
            break
        checked += 1
        try:
            real = decode_google_news(it["url"])
            if real != it["url"]:
                time.sleep(1)
            if not real or "hani.co.kr" not in real:
                print(f"- skip (not Hankyoreh / undecodable): {raw}")
                continue
            if article_key(real) in known_keys:
                continue
            info = read_hani(real)
            time.sleep(1)
        except Exception as e:
            print(f"! error on {raw or it['url']}: {e}")
            continue

        key = article_key(info["url"])
        if key in known_keys:
            continue
        headline = strip_suffix(info["heads"][0] if info["heads"] else raw)
        if not info["byline_ok"]:
            print(f"- skip (byline not Kim Won-chul): {headline or real}")
            known_keys.add(key)
            data["_seen"].append(key)
            continue

        cat = classify(raw, *info["heads"])
        title = strip_tags(headline or raw)
        entry = {"date": info["date"] or it["date"], "title": title,
                 "dek": info["dek"], "url": info["url"]}
        if cat:
            data[cat].append(dict(entry))
        data["latest"].append(dict(entry, type=TYPE_LABEL[cat]))
        known_keys.add(key)
        data["_seen"].append(key)
        known_titles.add(norm_title(title))
        added += 1
        print(f"+ added [{TYPE_LABEL[cat]}] {entry['date']} {title}")

    save_data(data)
    print(f"Done. checked={checked}, added={added}")


if __name__ == "__main__":
    run()

