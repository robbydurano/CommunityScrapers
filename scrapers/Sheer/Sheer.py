import json
import re
import sys
from datetime import datetime, timedelta

sys.path.insert(0, "..")
from py_common import log
import requests
from bs4 import BeautifulSoup

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

SHEER_BASE = "https://www.sheer.com"


def fetch(url):
    log.debug(f"Fetching: {url}")
    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
    if r.status_code != 200:
        log.error(f"HTTP {r.status_code} for {url}")
        sys.exit(1)
    return r.text


def parse_relative_date(text):
    """
    Convert relative dates like '20 hours ago', '3 days ago', '2 weeks ago'
    to YYYY-MM-DD. Falls back to today if unparseable.
    """
    text = text.strip().lower()
    now = datetime.now()

    m = re.match(r"(\d+)\s+(second|minute|hour|day|week|month|year)s?\s+ago", text)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        if unit == "second":
            delta = timedelta(seconds=n)
        elif unit == "minute":
            delta = timedelta(minutes=n)
        elif unit == "hour":
            delta = timedelta(hours=n)
        elif unit == "day":
            delta = timedelta(days=n)
        elif unit == "week":
            delta = timedelta(weeks=n)
        elif unit == "month":
            delta = timedelta(days=n * 30)
        elif unit == "year":
            delta = timedelta(days=n * 365)
        else:
            delta = timedelta(0)
        return (now - delta).strftime("%Y-%m-%d")

    # Try absolute formats
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%Y-%m-%d", "%b. %d, %Y",
                "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass

    # Try partial date like "March 31" or "31 March" — assume current year
    for fmt in ("%b %d", "%B %d", "%d %b", "%d %B"):
        try:
            d = datetime.strptime(text, fmt)
            return d.replace(year=now.year).strftime("%Y-%m-%d")
        except ValueError:
            pass

    log.warning(f"Could not parse date: {text!r}")
    return None


def parse_post(html, post_url):
    soup = BeautifulSoup(html, "html.parser")
    scrape = {}

    # Title
    el = soup.select_one("h3.post__title")
    if el:
        scrape["title"] = el.get_text(strip=True)
    else:
        og = soup.find("meta", property="og:title") or soup.find("meta", {"name": "og:title"})
        if og:
            scrape["title"] = og.get("content", "").strip()

    # Date — try <time datetime="..."> first, then relative text
    time_el = soup.find("time")
    if time_el and time_el.get("datetime"):
        scrape["date"] = time_el["datetime"][:10]
    else:
        date_el = soup.select_one(".post__date-text")
        if date_el:
            parsed = parse_relative_date(date_el.get_text(strip=True))
            if parsed:
                scrape["date"] = parsed

    # Details
    el = soup.select_one(".post__text")
    if el:
        scrape["details"] = el.get_text(strip=True)
    else:
        og = soup.find("meta", property="og:description") or soup.find("meta", {"name": "og:description"})
        if og:
            scrape["details"] = og.get("content", "").strip()

    # Image — use og:image (poster) not the blurred SFW preview
    og_img = soup.find("meta", property="og:image") or soup.find("meta", {"name": "twitter:image"})
    if og_img:
        scrape["image"] = og_img.get("content", "")

    # Performers
    performers = []
    for a in soup.select(".post__featuring-models__list-item"):
        name = a.get_text(strip=True)
        if name:
            performers.append({"name": name})
    if performers:
        scrape["performers"] = performers

    # Tags — in <template> tag, need to parse its innerHTML
    tags = []
    template = soup.find("template", id="post-tags__template")
    if template:
        # BeautifulSoup parses <template> content as a string in .string or via children
        tmpl_html = str(template)
        tmpl_soup = BeautifulSoup(tmpl_html, "html.parser")
        for a in tmpl_soup.select(".post-tags__link"):
            name = a.get_text(strip=True)
            if name:
                tags.append({"name": name})
    # Also try rendered tags (visible on page if JS has run)
    for a in soup.select(".post-tags .post-tags__link"):
        name = a.get_text(strip=True)
        if name and {"name": name} not in tags:
            tags.append({"name": name})
    if tags:
        scrape["tags"] = tags

    # Studio
    studio_name_el = soup.select_one(".profile-header__title")
    studio_link_el = soup.select_one(".post__profile-name--link")
    if studio_link_el:
        studio_name = studio_link_el.get_text(strip=True)
        studio_url  = studio_link_el.get("href", "")
        if studio_url and not studio_url.startswith("http"):
            studio_url = SHEER_BASE + studio_url
    elif studio_name_el:
        studio_name = studio_name_el.get_text(strip=True)
        studio_url  = post_url.rsplit("/post/", 1)[0]
    else:
        studio_name = None
        studio_url  = post_url.rsplit("/post/", 1)[0]

    if studio_name:
        scrape["studio"] = {"name": studio_name, "url": studio_url}

    scrape["urls"] = [post_url]

    return scrape


def by_url(url):
    html = fetch(url)
    return parse_post(html, url)


if __name__ == "__main__":
    fragment = json.loads(sys.stdin.read())
    log.debug(f"Input: {fragment}")

    url = fragment.get("url", "")
    if not url:
        log.error("No URL provided")
        sys.exit(1)

    result = by_url(url)
    log.debug(f"Result: {result}")
    print(json.dumps(result))