import configparser
import hashlib
import json
import os
import re
import sys
from datetime import datetime
from urllib.parse import urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

MRSKIN_BASE = "https://www.mrskin.com"
MRMAN_BASE  = "https://www.mrman.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}

SCRIPT_DIR  = os.path.dirname(os.path.realpath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "config.ini")
DEFAULT_CONFIG = """\
[MrSkin]
# Log in at mrskin.com, open DevTools → Application → Cookies → www.mrskin.com
# Copy each cookie value and paste below. All are optional but more = better auth.
# _mr_skin_new_session cookie (may be absent if remember_customer_token is set)
mrskin_session =
# remember_customer_token cookie (persistent login)
mrskin_remember =
# csrf_token cookie
mrskin_csrf =
# cf_clearance cookie (Cloudflare — IP-bound, expires ~30min, grab fresh before scraping)
mrskin_cf_clearance =
# _acct_state cookie
mrskin_acct_state =

[MrMan]
# Log in at mrman.com, open DevTools → Application → Cookies → www.mrman.com
mrman_session =
mrman_remember =
mrman_csrf =
mrman_cf_clearance =
mrman_acct_state =
"""


def load_config():
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "w") as f:
            f.write(DEFAULT_CONFIG)
    cfg = configparser.RawConfigParser()
    cfg.read(CONFIG_FILE)
    return cfg


def session_cookies(site):
    """Return (cookies dict, extra_headers dict) for the given site."""
    cfg = load_config()
    if site == "mrman":
        session    = cfg.get("MrMan", "mrman_session",      fallback="").strip()
        remember   = cfg.get("MrMan", "mrman_remember",     fallback="").strip()
        csrf       = cfg.get("MrMan", "mrman_csrf",         fallback="").strip()
        cf         = cfg.get("MrMan", "mrman_cf_clearance", fallback="").strip()
        acct_state = cfg.get("MrMan", "mrman_acct_state",   fallback="").strip()
        cookies = {}
        if session:    cookies["_mr_man_new_session"]    = session
        if remember:   cookies["remember_customer_token"] = remember
        if csrf:       cookies["csrf_token"]              = csrf
        if cf:         cookies["cf_clearance"]            = cf
        if acct_state: cookies["_acct_state"]             = acct_state
        headers = {"X-CSRF-Token": csrf} if csrf else {}
        return cookies, headers
    session    = cfg.get("MrSkin", "mrskin_session",      fallback="").strip()
    remember   = cfg.get("MrSkin", "mrskin_remember",     fallback="").strip()
    csrf       = cfg.get("MrSkin", "mrskin_csrf",         fallback="").strip()
    cf         = cfg.get("MrSkin", "mrskin_cf_clearance", fallback="").strip()
    acct_state = cfg.get("MrSkin", "mrskin_acct_state",   fallback="").strip()
    cookies = {}
    if session:    cookies["_mr_skin_new_session"]    = session
    if remember:   cookies["remember_customer_token"] = remember
    if csrf:       cookies["csrf_token"]              = csrf
    if cf:         cookies["cf_clearance"]            = cf
    if acct_state: cookies["_acct_state"]             = acct_state
    headers = {"X-CSRF-Token": csrf} if csrf else {}
    return cookies, headers

HAIR_MAP = {
    "brunette": "BROWN",
    "brown": "BROWN",
    "blonde": "BLONDE",
    "black": "BLACK",
    "red": "RED",
    "auburn": "AUBURN",
    "grey": "GREY",
    "gray": "GREY",
    "white": "WHITE",
    "bald": "BALD",
    "strawberry": "RED",
    "dirty blonde": "BLONDE",
}

ETHNICITY_LABEL = {
    "white": "WHITE",
    "caucasian": "WHITE",
    "black": "BLACK",
    "african": "BLACK",
    "asian": "ASIAN",
    "latina": "LATIN",
    "hispanic": "LATIN",
    "latin": "LATIN",
    "middle eastern": "MIDDLE_EASTERN",
    "middle-eastern": "MIDDLE_EASTERN",
    "indian": "INDIAN",
    "mixed": "MIXED",
}

# Country name / demonym → ISO 3166-1 alpha-2
COUNTRY_MAP = {
    "united states": "US", "usa": "US", "american": "US", "u.s.a.": "US",
    "united kingdom": "GB", "uk": "GB", "british": "GB", "england": "GB",
    "canada": "CA", "canadian": "CA",
    "australia": "AU", "australian": "AU",
    "brazil": "BR", "brazilian": "BR", "brasil": "BR",
    "france": "FR", "french": "FR",
    "germany": "DE", "german": "DE",
    "italy": "IT", "italian": "IT",
    "spain": "ES", "spanish": "ES",
    "mexico": "MX", "mexican": "MX",
    "argentina": "AR", "argentinian": "AR", "argentinean": "AR",
    "colombia": "CO", "colombian": "CO",
    "venezuela": "VE", "venezuelan": "VE",
    "russia": "RU", "russian": "RU",
    "ukraine": "UA", "ukrainian": "UA",
    "czech republic": "CZ", "czech": "CZ", "czechia": "CZ",
    "hungary": "HU", "hungarian": "HU",
    "poland": "PL", "polish": "PL",
    "romania": "RO", "romanian": "RO",
    "sweden": "SE", "swedish": "SE",
    "norway": "NO", "norwegian": "NO",
    "denmark": "DK", "danish": "DK",
    "netherlands": "NL", "dutch": "NL",
    "belgium": "BE", "belgian": "BE",
    "switzerland": "CH", "swiss": "CH",
    "austria": "AT", "austrian": "AT",
    "portugal": "PT", "portuguese": "PT",
    "japan": "JP", "japanese": "JP",
    "south korea": "KR", "korean": "KR",
    "china": "CN", "chinese": "CN",
    "india": "IN", "indian": "IN",
    "philippines": "PH", "filipino": "PH", "filipina": "PH",
    "thailand": "TH", "thai": "TH",
    "indonesia": "ID", "indonesian": "ID",
    "israel": "IL", "israeli": "IL",
    "south africa": "ZA", "south african": "ZA",
    "new zealand": "NZ",
    "ireland": "IE", "irish": "IE",
    "scotland": "GB", "scottish": "GB",
    "wales": "GB", "welsh": "GB",
    "puerto rico": "US",
    "cuba": "CU", "cuban": "CU",
    "chile": "CL", "chilean": "CL",
    "peru": "PE", "peruvian": "PE",
    # UK region abbreviations MrMan uses
    "eng": "GB", "sco": "GB", "wal": "GB", "nir": "GB",
}


def normalize_url(url):
    """Strip subpaths/query params to get the base performer URL."""
    m = re.match(r"(https?://(?:www\.)?mr(?:skin|man)\.com/[^/?#]+-(?:nude|sexy|naked|hot)-c\d+)", url)
    return m.group(1) if m else url


def gender_for_url(url, tags=None):
    is_mrman = "mrman.com" in url
    if tags and any(t.get("name", "").lower() == "transgender" for t in tags):
        return "TRANSGENDER_MALE" if is_mrman else "TRANSGENDER_FEMALE"
    return "MALE" if is_mrman else "FEMALE"


def search_base_for_url(url):
    return MRMAN_BASE if "mrman.com" in url else MRSKIN_BASE


def strip_cdn_params(url):
    if not url:
        return url
    parsed = urlparse(url)
    return urlunparse(parsed._replace(query=""))


def get_page(url):
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def extract_track_page(soup):
    for script in soup.find_all("script"):
        text = script.string or ""
        m = re.search(r"_track_page\s*=\s*(\{[^;]+\})", text)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
    return {}


def extract_jsonld_image(soup):
    """Pull performer image from JSON-LD, stripped of CDN params."""
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            # image may be top-level or inside "about"
            img = data.get("image") or data.get("about", {}).get("image")
            if img:
                return strip_cdn_params(img)
        except (json.JSONDecodeError, AttributeError):
            pass
    return None


def find_biopic_url(soup):
    """Prefer JSON-LD image, then preload link, then og:image — all CDN-param-stripped."""
    img = extract_jsonld_image(soup)
    if img:
        return img

    for tag in soup.find_all("link", rel="preload"):
        href = tag.get("href", "")
        if "_biopic.jpg" in href and "featured_image" not in href:
            return strip_cdn_params(href)

    for img_tag in soup.find_all("img"):
        src = img_tag.get("data-src") or img_tag.get("src") or ""
        if "_biopic.jpg" in src and "featured_image" not in src:
            return strip_cdn_params(src)

    og_img = soup.find("meta", property="og:image")
    if og_img:
        return strip_cdn_params(og_img.get("content", ""))

    return None


def parse_birthdate(raw):
    """Parse MrSkin date strings into YYYY-MM-DD."""
    raw = raw.strip()
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(raw, fmt)
            # %y maps 00-68 → 2000-2068; celebrities born in those years need correction
            if dt.year > datetime.now().year:
                dt = dt.replace(year=dt.year - 100)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            pass
    # "January 1990" → YYYY-MM
    m = re.match(r"(\w+)\s+(\d{4})", raw)
    if m:
        try:
            return datetime.strptime(f"{m.group(1)} {m.group(2)}", "%B %Y").strftime("%Y-%m")
        except ValueError:
            pass
    return raw


def country_from_birthplace(birthplace):
    """Extract ISO country code from 'São Paulo, Brazil' or 'Spokane, WA, US'."""
    if not birthplace:
        return None
    parts = [p.strip() for p in birthplace.split(",")]
    for candidate in reversed(parts):
        candidate = candidate.strip().rstrip(".")
        if re.match(r"^[A-Z]{2}$", candidate):
            return candidate
        key = candidate.lower()
        if key in COUNTRY_MAP:
            return COUNTRY_MAP[key]
    key = birthplace.lower().strip()
    if key in COUNTRY_MAP:
        return COUNTRY_MAP[key]
    return None


def parse_bio_rows(soup):
    """
    Parse performer bio rows. MrSkin uses two different structures:
      New: <p><strong>Label:</strong> <span>Value</span></p>
      Old: <li><span class='detail-type'>Label:</span><span class='detail-info'>Value</span></li>
    Returns dict of {lowercase_label: (value_text, value_element)}.
    """
    rows = {}

    # New structure: <p> with <strong> label
    for p in soup.find_all("p"):
        strong = p.find("strong")
        if not strong:
            continue
        label = strong.get_text(strip=True).rstrip(":").lower()
        # value is the remaining content after the <strong>
        val_el = p.find("span")
        val_text = val_el.get_text(" ", strip=True) if val_el else p.get_text(" ", strip=True).replace(strong.get_text(), "").strip()
        if label:
            rows[label] = (val_text, val_el or p)

    # Old structure: <li> with span.detail-type / span.detail-info
    for li in soup.find_all("li"):
        dt = li.find("span", class_="detail-type")
        di = li.find("span", class_="detail-info")
        if not dt or not di:
            continue
        label = dt.get_text(strip=True).rstrip(":").lower()
        val_text = di.get_text(" ", strip=True)
        if label and label not in rows:
            rows[label] = (val_text, di)

    return rows


def parse_keyword_links(el):
    """Extract (href, label) pairs from all btn-link anchors within an element."""
    if el is None:
        return []
    return [(a.get("href", ""), a.get_text(strip=True)) for a in el.find_all("a", class_="btn-link")]


def parse_performer(soup, url):
    track = extract_track_page(soup)

    name = track.get("starName") or ""
    if not name:
        title_tag = soup.find("title")
        if title_tag:
            m = re.match(r"See (.+?) Nude", title_tag.text)
            if m:
                name = m.group(1)

    image = find_biopic_url(soup)
    rows = parse_bio_rows(soup)

    hair_color = None
    ethnicity = None
    tags = []
    birthdate = None
    birthplace = None

    for label, (val_text, val_el) in rows.items():
        if "keyword" in label:
            for href, tag_label in parse_keyword_links(val_el):
                m = re.search(r"hair_color=([^&]+)", href)
                if m:
                    val = HAIR_MAP.get(m.group(1).lower())
                    if val:
                        hair_color = val.capitalize()

                if "ethnicity=" in href:
                    val = ETHNICITY_LABEL.get(tag_label.lower())
                    if val:
                        ethnicity = val.capitalize()

                if tag_label:
                    tags.append({"name": tag_label})

        elif "date of birth" in label or (label == "birth" or ("birth" in label and "place" not in label)):
            birthdate = parse_birthdate(val_text)

        elif "birthplace" in label or "born in" in label:
            birthplace = val_text

    # _track_page fallback for hair
    if not hair_color and track.get("hairColor"):
        val = HAIR_MAP.get(track["hairColor"].lower())
        if val:
            hair_color = val.capitalize()

    country = country_from_birthplace(birthplace)

    result = {"name": name, "url": url, "gender": gender_for_url(url, tags)}
    if image:
        result["images"] = [image]
    if hair_color:
        result["hair_color"] = hair_color
    if ethnicity:
        result["ethnicity"] = ethnicity
    if birthdate:
        result["birthdate"] = birthdate
    if country:
        result["country"] = country
    if tags:
        result["tags"] = tags

    return result


def search_performers(name, base):
    query = name.replace(" ", "+")
    url = f"{base}/search/celebs?q={query}"
    soup = get_page(url)

    results = []
    for item in soup.find_all("div", class_="thumbnail"):
        a = item.find("a", class_="title") or item.find("a", href=re.compile(r"-nude-c\d+"))
        if not a:
            continue
        href = a.get("href", "")
        celeb_name = a.get_text(strip=True)
        if not celeb_name or not href:
            continue
        full_url = href if href.startswith("http") else base + href
        img_tag = item.find("img")
        img_src = (img_tag.get("data-src") or img_tag.get("src")) if img_tag else None
        entry = {"name": celeb_name, "url": full_url}
        if img_src and "fallback" not in img_src:
            entry["images"] = [strip_cdn_params(img_src)]
        results.append(entry)

    return results


def parse_episode(ep_str):
    """'Ep. 08x09' or 'S8E9' → 'S08E09'."""
    m = re.search(r"(\d+)[xX](\d+)", ep_str)
    if m:
        return f"S{int(m.group(1)):02d}E{int(m.group(2)):02d}"
    m = re.search(r"[Ss](\d+)[Ee](\d+)", ep_str)
    if m:
        return f"S{int(m.group(1)):02d}E{int(m.group(2)):02d}"
    return None


def _clip_api_token(page_soup, scene_id):
    """
    Compute the HMAC-style token used by media.js module 62 to authenticate
    the clipplayer JSON endpoint.

    Algorithm (from media.js):
      e = 1500 * id / 2
      hash = MD5(customer-service-token + ":scene:" + e + ":eD3BCk1HLDT1RC4IJxFR")
    """
    meta = page_soup.find("meta", attrs={"name": re.compile(r"^cust.+-token$")})
    if not meta:
        return None
    token = meta.get("content", "")
    e_val = int(1500 * int(scene_id) / 2)
    hash_input = f"{token}:scene:{e_val}:eD3BCk1HLDT1RC4IJxFR"
    return hashlib.md5(hash_input.encode()).hexdigest()


def scrape_scene(url, site="mrskin"):
    base_site = MRMAN_BASE if site == "mrman" else MRSKIN_BASE
    scene_id_m = re.search(r"/clipplayer/(\d+)", url)
    if not scene_id_m:
        return {}
    scene_id = scene_id_m.group(1)

    cookies, extra_headers = session_cookies(site)
    cookie_name = "_mr_man_new_session" if site == "mrman" else "_mr_skin_new_session"
    has_auth = cookies.get(cookie_name) or cookies.get("remember_customer_token")
    if not has_auth:
        print(
            f"No auth cookies — add {cookie_name} and/or remember_customer_token "
            f"(+cf_clearance) to config.ini after logging in at {base_site}.",
            file=sys.stderr,
        )
        print("{}")
        sys.exit(0)

    req_headers = {**HEADERS, **extra_headers, "Referer": base_site + "/"}

    # Step 1: fetch clipplayer HTML (auth required)
    # The server renders <title> and the customer-service-token meta tag.
    r = requests.get(url, headers=req_headers, cookies=cookies, timeout=15)
    if r.status_code in (401, 403, 404):
        print(
            f"HTTP {r.status_code} on clipplayer — session may be expired. "
            f"Refresh {cookie_name} + cf_clearance in config.ini.",
            file=sys.stderr,
        )
        print("{}")
        sys.exit(0)
    r.raise_for_status()

    page_soup = BeautifulSoup(r.text, "html.parser")
    raw_title = page_soup.title.get_text(strip=True) if page_soup.title else ""

    if re.search(r"log.?in|sign.?in", raw_title, re.IGNORECASE):
        print(f"Session expired (got login page). Refresh {cookie_name} in config.ini.", file=sys.stderr)
        print("{}")
        sys.exit(0)

    # Title fallback: "Mr. Skin - Levy Tran in Shameless (2011-2021)"
    title_m = re.search(r"Mr\. (?:Skin|Man)\s*[-–]\s*(.+?)\s+in\s+(.+?)(?:\s*\(|$)", raw_title)
    performer_name = title_m.group(1).strip() if title_m else ""
    show_name_hint = title_m.group(2).strip() if title_m else ""
    print(f"[MrSkin] scene {scene_id}: performer={performer_name!r} show={show_name_hint!r}", file=sys.stderr)

    # Step 2: call the authenticated JSON API used by the Backbone media player.
    # URL: /clipplayer/{md5_token}/{scene_id}  (media.js module 62)
    clip_json = {}
    rating_stars = None
    api_hash = _clip_api_token(page_soup, scene_id)
    if api_hash:
        api_url = f"{base_site}/clipplayer/{api_hash}/{scene_id}"
        json_headers = {
            **HEADERS,
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": url,
        }
        try:
            jr = requests.get(api_url, headers=json_headers, cookies=cookies, timeout=15)
            if jr.status_code == 200 and "application/json" in jr.headers.get("Content-Type", ""):
                clip_json = jr.json().get("model", {})
                print(f"[MrSkin] JSON API success", file=sys.stderr)
            else:
                print(f"[MrSkin] JSON API {jr.status_code}", file=sys.stderr)
        except Exception as exc:
            print(f"[MrSkin] JSON API error: {exc}", file=sys.stderr)
    else:
        print(f"[MrSkin] customer-service-token not found in page", file=sys.stderr)

    # Step 3: parse everything from the JSON API response.
    nude_pat = re.compile(r"-(?:nude|sexy|naked|hot)-c\d+")
    performers = []
    show_name = show_name_hint
    show_url = None
    ep_label = None
    desc_text = ""
    tags = []

    if clip_json:
        # title HTML: <a href="/levy-tran-nude-c25827">Levy Tran</a>,
        #             <a href="/lynsey-taylor-mackay-nude-c23658">Lynsey Taylor Mackay</a> in
        #             <a class="title" href="/shameless-nude-scenes-t47576">Shameless</a>
        title_soup = BeautifulSoup(clip_json.get("title", ""), "html.parser")
        for a in title_soup.find_all("a", href=nude_pat):
            href = a.get("href", "")
            p_url = href if href.startswith("http") else base_site + href
            performers.append({"name": a.get_text(strip=True), "url": p_url})
        for a in title_soup.find_all("a", class_="title"):
            show_name = a.get_text(strip=True)
            href = a.get("href", "")
            show_url = href if href.startswith("http") else base_site + href
            break

        # description HTML: <span class="text-muted">Ep. 08x09 | 00:05:16</span> Some great ...
        desc_soup = BeautifulSoup(clip_json.get("description", ""), "html.parser")
        muted = desc_soup.find("span", class_="text-muted")
        if muted:
            ep_label = parse_episode(muted.get_text())
            muted.decompose()
        desc_text = desc_soup.get_text(" ", strip=True).strip()

        # tags and rating from clean JSON array
        inner = clip_json.get("json", {})
        for tag_name in inner.get("tags", []):
            if tag_name:
                tags.append({"name": tag_name})
        rating_stars = inner.get("rating")  # 1-4 scale, None if unrated

        # actress_id fallback via celebrity_redirect_path if title links were missing
        if not performers:
            actress_ids = inner.get("actress_id", [])
            for aid in actress_ids:
                try:
                    redir = requests.get(
                        f"{base_site}/celebrity/{aid}",
                        headers=HEADERS, allow_redirects=False, timeout=10,
                    )
                    if redir.status_code in (301, 302, 307, 308):
                        loc = redir.headers.get("Location", "")
                        if nude_pat.search(loc):
                            p_url = loc if loc.startswith("http") else base_site + loc
                            performers.append({"url": p_url})
                            print(f"[MrSkin] performer via celebrity_redirect: {p_url}", file=sys.stderr)
                except Exception:
                    pass

    if performers:
        print(f"[MrSkin] performers={[p.get('url', p.get('name')) for p in performers]}", file=sys.stderr)
    else:
        print(f"[MrSkin] no performers found — partial result", file=sys.stderr)

    # Use first performer name for title, all names for display
    first_name = performers[0].get("name") if performers else performer_name
    all_names  = ", ".join(p["name"] for p in performers if p.get("name")) or performer_name
    parts = [p for p in [show_name, ep_label, all_names] if p]
    title = " - ".join(parts) if parts else (raw_title or f"Scene {scene_id}")

    result = {"title": title, "url": url}
    if desc_text:
        result["details"] = desc_text
    if rating_stars:
        result["rating100"] = rating_stars * 25  # MrSkin 4-star → Stash rating100
    if performers:
        result["performers"] = performers
    if show_name:
        group_entry = {"name": show_name}
        if show_url:
            group_entry["url"] = show_url
            slug_m = re.search(r"/([^/?#]+)$", show_url)
            if slug_m:
                group_entry["code"] = slug_m.group(1)
        result["groups"] = [group_entry]
    if tags:
        result["tags"] = tags

    return result


def scrape_group(url, site="mrskin"):
    base_site = MRMAN_BASE if site == "mrman" else MRSKIN_BASE
    cookies, extra_headers = session_cookies(site)
    req_headers = {**HEADERS, **extra_headers}

    try:
        r = requests.get(url, headers=req_headers, cookies=cookies, timeout=15)
        r.raise_for_status()
    except Exception as exc:
        print(f"[MrSkin] scrape_group error: {exc}", file=sys.stderr)
        return {}

    soup = BeautifulSoup(r.text, "html.parser")
    result = {"urls": [url]}

    # Name: og:title or <h1>, strip trailing "Nude Scenes" suffix
    og_title = soup.find("meta", property="og:title")
    name = og_title.get("content", "") if og_title else ""
    if not name:
        h1 = soup.find("h1")
        name = h1.get_text(strip=True) if h1 else ""
    name = re.sub(r"\s+Nude\s+Scenes?$", "", name, flags=re.IGNORECASE).strip()
    if name:
        result["name"] = name

    # Synopsis: og:description
    og_desc = soup.find("meta", property="og:description")
    if og_desc:
        result["synopsis"] = og_desc.get("content", "")

    # Cover image: og:image (CDN params stripped)
    og_img = soup.find("meta", property="og:image")
    if og_img:
        result["front_image"] = strip_cdn_params(og_img.get("content", ""))

    return result


if __name__ == "__main__":
    load_config()  # ensures config.ini is created if missing
    input_data = json.loads(sys.stdin.read())
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    # sys.argv[2] is the site hint passed from the yml ("mrskin" or "mrman")
    site = sys.argv[2] if len(sys.argv) > 2 else "mrskin"
    base = MRMAN_BASE if site == "mrman" else MRSKIN_BASE

    if action == "performerByURL":
        url = normalize_url(input_data.get("url", ""))
        soup = get_page(url)
        result = parse_performer(soup, url)
        print(json.dumps(result))

    elif action == "performerByName":
        query = input_data.get("name", "")
        results = search_performers(query, base)
        print(json.dumps(results))

    elif action == "sceneByURL":
        url = input_data.get("url", "")
        result = scrape_scene(url, site)
        print(json.dumps(result))

    elif action == "groupByURL":
        url = input_data.get("url", "")
        result = scrape_group(url, site)
        print(json.dumps(result))

    else:
        print(json.dumps({}))
