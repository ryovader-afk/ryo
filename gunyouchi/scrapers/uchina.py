"""うちなーらいふ 軍用地スクレイパー (API経由)"""

import re
import time
import logging

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://www.e-uchina.net"
API_URL = f"{BASE_URL}/api/search"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}
REQUEST_INTERVAL = 2


def _extract_facility(text):
    patterns = [
        r"名\s*称[：:]\s*([^\s（(・\n]+)",
        r"【([^】]+)】",
        r"(嘉手納飛行場|嘉手納弾薬庫地区|嘉手納弾薬庫|普天間飛行場|牧港補給地区|"
        r"陸上自衛隊\s*那覇駐屯地|那覇駐屯地|トリイ通信施設|キャンプ[・]?\s*\S+|"
        r"ホワイトビーチ|伊江島補助飛行場|泡瀬通信施設|那覇空港用地|那覇港湾施設)",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            return m.group(1).strip()
    return ""


def _extract_bairitsu(text):
    m = re.search(r"倍\s*率[：:]?\s*([\d.]+)\s*倍", text)
    if m:
        return float(m.group(1))
    m = re.search(r"([\d.]+)\s*倍", text)
    if m:
        val = float(m.group(1))
        if 10 <= val <= 200:
            return val
    return None


def _extract_rent(text):
    patterns = [
        r"年[間]?(?:地料|借地料|賃借料)[：:]\s*[約]?\s*([\d,]+)\s*円",
        r"年地料[：:]\s*[約]?\s*([\d,]+)\s*円",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            return int(m.group(1).replace(",", ""))
    return None


def _extract_rise_rate(text):
    m = re.search(r"上昇率[：:]?\s*([\d.]+)\s*[%％]", text)
    if m:
        return float(m.group(1))
    return None


def _extract_meigi(text):
    m = re.search(r"(単[独有]名義|共有名義|単有|共有)", text)
    if m:
        return m.group(1)
    return ""


def _parse_property(item):
    catch = item.get("catch_phrase_web", "") or ""
    biko = item.get("bukken_biko", "") or ""
    combined = f"{catch}\n{biko}"

    facility = _extract_facility(combined)
    bairitsu = _extract_bairitsu(combined)
    annual_rent = _extract_rent(combined)
    rise_rate = _extract_rise_rate(combined)
    meigi = _extract_meigi(combined)

    price = item.get("price_sort")
    if price is not None:
        try:
            price = int(price)
        except (ValueError, TypeError):
            price = None

    area_m2 = None
    area_tsubo = None
    if item.get("tochi_space_metr"):
        try:
            area_m2 = float(str(item["tochi_space_metr"]).replace(",", ""))
        except ValueError:
            pass
    if item.get("tochi_space_tubo"):
        try:
            area_tsubo = float(str(item["tochi_space_tubo"]).replace(",", ""))
        except ValueError:
            pass

    city = item.get("city_name", "")
    area = item.get("area_name", "")
    address = f"{city}{area}".strip()

    permalink = item.get("permalink", "")

    return {
        "source": "uchina",
        "name": catch.split("\n")[0][:100] if catch else "",
        "facility": facility,
        "address": address,
        "price_manyen": price,
        "annual_rent": annual_rent,
        "bairitsu": bairitsu,
        "area_m2": area_m2,
        "area_tsubo": area_tsubo,
        "rise_rate": rise_rate,
        "meigi": meigi,
        "notes": biko[:500] if biko else "",
        "detail_url": permalink,
        "property_id": item.get("bukken_hid", ""),
    }


def scrape(max_pages=None, target_facilities=None):
    session = requests.Session()

    session.get(f"{BASE_URL}/sonota", headers={
        "User-Agent": HEADERS["User-Agent"],
    }, timeout=30)

    params = {
        "searchType": "sonota",
        "kodawari": "option_gunyochi",
        "mode": "bukken",
        "page": 1,
        "perPage": 20,
        "sort": "update",
    }

    resp = session.get(API_URL, params=params, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    bukkens_data = data.get("data", {}).get("bukkens", {})
    total_pages = bukkens_data.get("last_page", 1)
    total = bukkens_data.get("total", 0)

    if max_pages:
        total_pages = min(total_pages, max_pages)

    logger.info("uchina: total %d items, %d pages", total, total_pages)

    all_listings = []

    items = bukkens_data.get("data", [])
    for item in items:
        listing = _parse_property(item)
        all_listings.append(listing)

    for page in range(2, total_pages + 1):
        time.sleep(REQUEST_INTERVAL)
        try:
            params["page"] = page
            resp = session.get(API_URL, params=params, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            items = data.get("data", {}).get("bukkens", {}).get("data", [])
            for item in items:
                listing = _parse_property(item)
                all_listings.append(listing)
            logger.info("uchina: page %d/%d, %d items", page, total_pages, len(items))
        except Exception:
            logger.exception("uchina: failed page %d", page)

    if target_facilities:
        all_listings = [
            l for l in all_listings
            if any(f in l.get("facility", "") or f in l.get("name", "")
                   for f in target_facilities)
        ]

    logger.info("uchina: total %d listings after filter", len(all_listings))
    return all_listings
