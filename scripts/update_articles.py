import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

# 구글 뉴스 RSS를 통해 english.hani.co.kr 내 Kim Won-chul 기사 검색
QUERY = 'Kim Won-chul site:english.hani.co.kr'
RSS_URL = f"https://news.google.com/rss/search?q={urllib.parse.quote(QUERY)}&hl=en-US&gl=US&ceid=US:en"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

def clean_title(title, category_tag=None):
    # 한겨레 출처 꼬리표 및 카테고리 태그 정리
    t = re.sub(r"\s*-\s*The Hankyoreh.*$", "", title, flags=re.IGNORECASE)
    t = re.sub(r"\s*-\s*한겨레.*$", "", t, flags=re.IGNORECASE)
    if category_tag:
        t = re.sub(rf"\[?{category_tag}\]?\s*[:-]?\s*", "", t, flags=re.IGNORECASE)
    return t.strip()

def format_date(pub_date_str):
    # 'Mon, 15 Sep 2026 07:00:00 GMT' 형태를 'YYYY-MM-DD'로 변환
    months = {
        "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04",
        "May": "05", "Jun": "06", "Jul": "07", "Aug": "08",
        "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12"
    }
    m = re.search(r"(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})", pub_date_str)
    if m:
        day, mon, year = m.groups()
        return f"{year}-{months.get(mon, '01')}-{int(day):02d}"
    return ""

def fetch_articles():
    req = urllib.request.Request(RSS_URL, headers=HEADERS)
    xml_data = urllib.request.urlopen(req, timeout=15).read()
    root = ET.fromstring(xml_data)

    articles = []
    for item in root.findall(".//item"):
        title_raw = item.findtext("title", default="")
        link = item.findtext("link", default="")
        pub_date = item.findtext("pubDate", default="")

        title = clean_title(title_raw)
        date = format_date(pub_date)

        articles.append({
            "date": date,
            "title": title,
            "dek": title, # 기본 요약문으로 제목 활용
            "url": link
        })
    return articles

def run():
    fetched = fetch_articles()

    latest_list = []
    interview_list = []
    reportage_list = []

    for art in fetched:
        title = art["title"]
        lower_title = title.lower()

        if "interview" in lower_title:
            art_type = "Interview"
            clean_t = clean_title(title, "interview")
            interview_list.append({
                "date": art["date"],
                "title": clean_t,
                "headline": clean_t,
                "dek": art["dek"],
                "url": art["url"]
            })
        elif "reportage" in lower_title:
            art_type = "Reportage"
            clean_t = clean_title(title, "reportage")
            reportage_list.append({
                "date": art["date"],
                "title": clean_t,
                "dek": art["dek"],
                "url": art["url"]
            })
        else:
            art_type = "Analysis"

        latest_list.append({
            "date": art["date"],
            "type": art_type,
            "title": title,
            "dek": art["dek"],
            "url": art["url"]
        })

    output_js = (
        "window.portfolioArticles = "
        + json.dumps(
            {
                "reportage": reportage_list[:10],
                "interview": interview_list[:10],
                "column": [],
                "latest": latest_list[:10]
            },
            indent=2,
            ensure_ascii=False
        )
        + ";\n"
    )

    with open("assets/articles.js", "w", encoding="utf-8") as f:
        f.write(output_js)

    print(f"Successfully updated assets/articles.js with {len(latest_list)} articles.")

if __name__ == "__main__":
    run()
