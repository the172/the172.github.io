import json
import re
import urllib.parse
import urllib.request
from bs4 import BeautifulSoup

BASE_URL = "https://english.hani.co.kr"
SEARCH_URL = f"{BASE_URL}/arti/search?search_keyword={urllib.parse.quote('Kim Won-chul')}&sort_field=date"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


def fetch_articles():
    req = urllib.request.Request(SEARCH_URL, headers=HEADERS)
    html = urllib.request.urlopen(req, timeout=15).read().decode("utf-8")
    soup = BeautifulSoup(html, "html.parser")

    articles = []
    # 한겨레 기사 목록 파싱
    for item in soup.select("ul.article-list > li, div.article-area, li.article"):
        a_tag = item.select_one("a[href*='/arti/']")
        if not a_tag:
            continue

        raw_title = a_tag.get_text(strip=True)
        link = a_tag["href"]
        if not link.startswith("http"):
            link = BASE_URL + link

        # 요약문(dek) 및 날짜 추출
        dek_el = item.select_one("p.lead, p.desc, div.lead, span.lead")
        dek = dek_el.get_text(strip=True) if dek_el else ""

        date_el = item.select_one("span.date, span.time, em.date")
        date_str = date_el.get_text(strip=True) if date_el else ""
        date_match = re.search(r"\d{4}[-.]\d{2}[-.]\d{2}", date_str)
        date = date_match.group(0).replace(".", "-") if date_match else ""

        articles.append(
            {
                "date": date,
                "title": raw_title,
                "dek": dek,
                "url": link,
            }
        )
    return articles


def clean_title(title, category_tag):
    cleaned = re.sub(
        rf"\[?{category_tag}\]?\s*[:-]?\s*", "", title, flags=re.IGNORECASE
    )
    return cleaned.strip()


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
            interview_list.append(
                {
                    "date": art["date"],
                    "title": clean_t,
                    "headline": clean_t,
                    "dek": art["dek"],
                    "url": art["url"],
                }
            )
        elif "reportage" in lower_title:
            art_type = "Reportage"
            clean_t = clean_title(title, "reportage")
            reportage_list.append(
                {
                    "date": art["date"],
                    "title": clean_t,
                    "dek": art["dek"],
                    "url": art["url"],
                }
            )
        else:
            art_type = "Analysis"

        latest_list.append(
            {
                "date": art["date"],
                "type": art_type,
                "title": title,
                "dek": art["dek"],
                "url": art["url"],
            }
        )

    output_js = (
        "window.portfolioArticles = "
        + json.dumps(
            {
                "reportage": reportage_list[:10],
                "interview": interview_list[:10],
                "column": [],
                "latest": latest_list[:10],
            },
            indent=2,
            ensure_ascii=False,
        )
        + ";\n"
    )

    with open("assets/articles.js", "w", encoding="utf-8") as f:
        f.write(output_js)

    print("Successfully updated assets/articles.js")


if __name__ == "__main__":
    run()
