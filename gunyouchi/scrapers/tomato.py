"""とまとハウジング 軍用地スクレイパー"""

import re
import time
import logging

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BASE_URL = "https://www.tomato-okinawa.com/estate_gun"
DETAIL_BASE = "https://www.tomato-okinawa.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}
REQUEST_INTERVAL = 2


def _parse_price(text):
    m = re.search(r"([\d,]+)", text)
    if m:
        return int(m.group(1).replace(",", ""))
    return None


def _parse_rent(text):
    m = re.search(r"([\d,]+)", text)
    if m:
        return int(m.group(1).replace(",", ""))
    return None


def _parse_bairitsu(text):
    m = re.search(r"([\d.]+)", text)
    if m:
        return float(m.group(1))
    return None


def _parse_area_m2(text):
    m = re.search(r"([\d,.]+)\s*[㎡m]", text)
    if m:
        return float(m.group(1).replace(",", ""))
    return None


def _parse_area_tsubo(text):
    m = re.search(r"[（(]([\d,.]+)\s*坪", text)
    if m:
        return float(m.group(1).replace(",", ""))
    return None


def _get_csrf_token(session):
    resp = session.get(BASE_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    token_input = soup.find("input", {"name": "_token"})
    if token_input:
        return token_input["value"], soup
    return None, soup


def _parse_listing(li):
    estate = li.find("div", class_="estate")
    if not estate:
        return None

    name_el = estate.find("p", class_="name")
    name = name_el.get_text(strip=True) if name_el else ""

    price_el = estate.find("p", class_="price")
    price_text = price_el.get_text(strip=True) if price_el else ""
    price = _parse_price(price_text)

    details = estate.find("div", class_="estate-detail-wrapper")
    area_text = ""
    rent_text = ""
    bairitsu_text = ""
    if details:
        ps = details.find_all("p")
        for p in ps:
            spans = p.find_all("span")
            if len(spans) >= 2:
                label = spans[0].get_text(strip=True)
                value = spans[1].get_text(strip=True)
                if "面積" in label:
                    area_text = value
                elif "地料" in label or "借地" in label:
                    rent_text = value
                elif "倍率" in label:
                    bairitsu_text = value

    detail_link = ""
    detail_el = estate.find("div", class_="detail")
    if detail_el:
        a = detail_el.find("a", href=True)
        if a:
            detail_link = a["href"]
            if detail_link.startswith("/"):
                detail_link = DETAIL_BASE + detail_link

    facility = ""
    m = re.search(r"\(([^)]+)\)\s*$", name)
    if m:
        facility = m.group(1)

    return {
        "source": "tomato",
        "name": name,
        "facility": facility,
        "price_manyen": price,
        "annual_rent": _parse_rent(rent_text),
        "bairitsu": _parse_bairitsu(bairitsu_text),
        "area_m2": _parse_area_m2(area_text),
        "area_tsubo": _parse_area_tsubo(area_text),
        "detail_url": detail_link,
    }


def scrape(max_pages=None, target_facilities=None):
    """Scrape とまとハウジング listings.

    Args:
        max_pages: Max pages to scrape. None = all.
        target_facilities: List of facility name substrings to filter.
                          e.g. ["嘉手納飛行場", "嘉手納弾薬庫"]
    """
    session = requests.Session()
    token, first_soup = _get_csrf_token(session)
    if not token:
        logger.error("Failed to get CSRF token")
        return []

    all_listings = []

    first_items = first_soup.find_all("li", attrs={"data-v-638fd4ee": True})
    for li in first_items:
        listing = _parse_listing(li)
        if listing:
            all_listings.append(listing)

    paging = first_soup.find("div", class_="paging")
    total_pages = 1
    if paging:
        page_items = paging.find_all("td", class_="page-item")
        for td in page_items:
            dp = td.get("data-page")
            if dp and dp.isdigit():
                total_pages = max(total_pages, int(dp))

    if max_pages:
        total_pages = min(total_pages, max_pages)

    logger.info("tomato: total %d pages", total_pages)

    for page in range(2, total_pages + 1):
        time.sleep(REQUEST_INTERVAL)
        try:
            resp = session.post(
                BASE_URL,
                data={"_token": token, "page": page, "params": ""},
                headers=HEADERS,
                timeout=30,
            )
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")

            new_token = soup.find("input", {"name": "_token"})
            if new_token:
                token = new_token["value"]

            items = soup.find_all("li", attrs={"data-v-638fd4ee": True})
            for li in items:
                listing = _parse_listing(li)
                if listing:
                    all_listings.append(listing)

            logger.info("tomato: page %d/%d, %d items", page, total_pages, len(items))
        except Exception:
            logger.exception("tomato: failed page %d", page)

    if target_facilities:
        all_listings = [
            l for l in all_listings
            if any(f in l.get("facility", "") or f in l.get("name", "")
                   for f in target_facilities)
        ]

    return all_listings
