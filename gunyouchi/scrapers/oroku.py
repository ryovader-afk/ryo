"""オロク商会 軍用地スクレイパー"""

import re
import time
import logging

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

LIST_URL = "https://oroku.co.jp/orokupr/bukken/gunyouchi/"
DETAIL_BASE = "https://oroku.co.jp"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}
REQUEST_INTERVAL = 2


def _parse_int(text):
    m = re.search(r"([\d,]+)", text)
    if m:
        return int(m.group(1).replace(",", ""))
    return None


def _parse_float(text):
    m = re.search(r"([\d,.]+)", text)
    if m:
        return float(m.group(1).replace(",", ""))
    return None


def _parse_area_m2(text):
    m = re.search(r"([\d,.]+)\s*[㎡mM]", text)
    if m:
        return float(m.group(1).replace(",", ""))
    return None


def _parse_area_tsubo(text):
    m = re.search(r"[（(]([\d,.]+)\s*[)）]?\s*坪", text)
    if m:
        return float(m.group(1).replace(",", ""))
    return None


def _parse_rise_rate(text):
    m = re.search(r"上昇率[：:]?\s*([\d.]+)\s*[%％]", text)
    if m:
        return float(m.group(1))
    return None


def _scrape_detail(session, url):
    """Scrape detail page for full property data."""
    try:
        resp = session.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        table = soup.find("table", id="list_other")
        if not table:
            return {}

        data = {}
        rows = table.find_all("tr")
        for row in rows:
            ths = row.find_all("th")
            tds = row.find_all("td")
            for i, th in enumerate(ths):
                label = th.get_text(strip=True)
                if i < len(tds):
                    value = tds[i].get_text(strip=True)
                    data[label] = value

        result = {}

        if "施設名" in data:
            result["facility"] = data["施設名"]
        if "価格" in data:
            result["price_manyen"] = _parse_int(data["価格"])
        if "倍率" in data:
            result["bairitsu"] = _parse_float(data["倍率"])
        if "賃借料/年" in data:
            result["annual_rent"] = _parse_int(data["賃借料/年"])
        if "土地面積" in data:
            result["area_m2"] = _parse_area_m2(data["土地面積"])
            result["area_tsubo"] = _parse_area_tsubo(data["土地面積"])
        if "固定資産税" in data:
            result["property_tax"] = _parse_int(data["固定資産税"])
        if "地目" in data:
            result["land_category"] = data["地目"]
        if "物件番号" in data:
            result["property_id"] = data["物件番号"]

        tokki = data.get("特記事項", "")
        result["rise_rate"] = _parse_rise_rate(tokki)
        result["notes"] = tokki

        if "返還予定" in tokki:
            m = re.search(r"返還予定[：:]?\s*(\S+)", tokki)
            if m:
                result["return_plan"] = m.group(1)

        return result
    except Exception:
        logger.exception("oroku: failed detail %s", url)
        return {}


def _get_total_pages(soup):
    nav = soup.find("div", id="nav-above1")
    if not nav:
        return 1
    nav_next = nav.find("div", class_="nav-next")
    if not nav_next:
        return 1
    links = nav_next.find_all("a")
    max_page = 1
    for a in links:
        href = a.get("href", "")
        m = re.search(r"paged=(\d+)", href)
        if m:
            max_page = max(max_page, int(m.group(1)))
    return max_page


def _parse_list_page(soup):
    articles = soup.find_all("article", class_="hentry")
    items = []
    for article in articles:
        title_el = article.find("span", class_="top_title")
        title = title_el.get_text(strip=True) if title_el else ""

        price_el = article.find("span", class_="dpoint4")
        price_text = price_el.get_text(strip=True) if price_el else ""

        address_el = article.find("div", class_="list_address")
        address = address_el.get_text(strip=True).replace("所在地:", "") if address_el else ""

        detail_url = ""
        img_link = article.find("div", class_="list_picsam_img")
        if img_link:
            a = img_link.find("a", href=True)
            if a:
                detail_url = a["href"]

        items.append({
            "name": title,
            "price_manyen": _parse_int(price_text),
            "address": address,
            "detail_url": detail_url,
        })
    return items


def scrape(max_pages=None, target_facilities=None):
    """Scrape オロク商会 listings.

    Args:
        max_pages: Max pages to scrape. None = all.
        target_facilities: List of facility name substrings to filter.
    """
    session = requests.Session()

    resp = session.get(LIST_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    total_pages = _get_total_pages(soup)
    if max_pages:
        total_pages = min(total_pages, max_pages)

    logger.info("oroku: total %d pages", total_pages)

    all_items = _parse_list_page(soup)

    for page in range(2, total_pages + 1):
        time.sleep(REQUEST_INTERVAL)
        try:
            url = f"https://oroku.co.jp/orokupr/?bukken=gunyouchi&paged={page}&so=pm&ord=d&s="
            resp = session.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")
            items = _parse_list_page(soup)
            all_items.extend(items)
            logger.info("oroku: page %d/%d, %d items", page, total_pages, len(items))
        except Exception:
            logger.exception("oroku: failed page %d", page)

    all_listings = []
    for item in all_items:
        if not item.get("detail_url"):
            continue

        time.sleep(REQUEST_INTERVAL)
        detail = _scrape_detail(session, item["detail_url"])

        listing = {
            "source": "oroku",
            "name": item["name"],
            "facility": detail.get("facility", ""),
            "address": item.get("address", ""),
            "price_manyen": detail.get("price_manyen") or item.get("price_manyen"),
            "annual_rent": detail.get("annual_rent"),
            "bairitsu": detail.get("bairitsu"),
            "area_m2": detail.get("area_m2"),
            "area_tsubo": detail.get("area_tsubo"),
            "property_tax": detail.get("property_tax"),
            "land_category": detail.get("land_category"),
            "rise_rate": detail.get("rise_rate"),
            "return_plan": detail.get("return_plan"),
            "notes": detail.get("notes", ""),
            "detail_url": item["detail_url"],
            "property_id": detail.get("property_id", ""),
        }
        all_listings.append(listing)

    if target_facilities:
        all_listings = [
            l for l in all_listings
            if any(f in l.get("facility", "") or f in l.get("name", "")
                   for f in target_facilities)
        ]

    logger.info("oroku: total %d listings", len(all_listings))
    return all_listings
