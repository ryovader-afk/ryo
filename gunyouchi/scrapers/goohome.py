"""グーホーム沖縄 軍用地スクレイパー"""

import re
import time
import logging

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

LIST_URL = "https://goohome.jp/tochi/cities/"
DETAIL_BASE = "https://goohome.jp"
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


def _parse_area(text):
    m2 = None
    tsubo = None
    m = re.search(r"約?([\d,.]+)\s*[㎡mM]", text)
    if m:
        m2 = float(m.group(1).replace(",", ""))
    m = re.search(r"約?([\d,.]+)\s*坪", text)
    if m:
        tsubo = float(m.group(1).replace(",", ""))
    return m2, tsubo


def _extract_from_comment(text):
    result = {}

    m = re.search(r"([\d.]+)\s*倍", text)
    if m:
        val = float(m.group(1))
        if 10 <= val <= 200:
            result["bairitsu"] = val

    patterns = [
        r"年[間]?(?:地料|借地料|賃借料)[：:.]?\s*[約]?\s*([\d,]+)\s*円",
        r"年地料[：:.]?\s*[約]?\s*([\d,]+)\s*円",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            result["annual_rent"] = int(m.group(1).replace(",", ""))
            break

    m = re.search(r"上昇率[：:]?\s*([\d.]+)\s*[%％]", text)
    if m:
        result["rise_rate"] = float(m.group(1))

    facility_pattern = (
        r"(嘉手納飛行場|嘉手納弾薬庫地区|嘉手納弾薬庫|普天間飛行場|牧港補給地区|"
        r"那覇駐屯地|トリイ通信施設|キャンプ\S+|ホワイトビーチ|伊江島補助飛行場|"
        r"泡瀬通信施設|那覇空港用地|那覇港湾施設|陸軍貯油施設)"
    )
    m = re.search(facility_pattern, text)
    if m:
        result["facility"] = m.group(1)

    m = re.search(r"(単[独有]名義|共有名義|単有|共有)", text)
    if m:
        result["meigi"] = m.group(1)

    return result


def _scrape_detail(session, url):
    try:
        resp = session.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        result = {}

        tables = soup.find_all("table")
        for table in tables:
            rows = table.find_all("tr")
            for row in rows:
                th = row.find("th")
                td = row.find("td")
                if not th or not td:
                    continue
                label = th.get_text(strip=True)
                value = td.get_text(strip=True)

                if "倍率" in label:
                    m = re.search(r"([\d.]+)", value)
                    if m:
                        result["bairitsu"] = float(m.group(1))
                elif "固定資産税" in label:
                    result["property_tax"] = _parse_int(value)
                elif label == "地目":
                    result["land_category"] = value
                elif "備考" in label:
                    result["notes"] = value[:500]
                    extracted = _extract_from_comment(value)
                    if "annual_rent" not in result and "annual_rent" in extracted:
                        result["annual_rent"] = extracted["annual_rent"]
                    if "rise_rate" not in result and "rise_rate" in extracted:
                        result["rise_rate"] = extracted["rise_rate"]
                    if "facility" not in result and "facility" in extracted:
                        result["facility"] = extracted["facility"]
                    if "meigi" not in result and "meigi" in extracted:
                        result["meigi"] = extracted["meigi"]

        return result
    except Exception:
        logger.exception("goohome: failed detail %s", url)
        return {}


def _get_total_from_list(soup):
    count_el = soup.select_one("div.insp_est-count span.number")
    if count_el:
        try:
            return int(count_el.get_text(strip=True))
        except ValueError:
            pass
    return 0


def _parse_list_page(soup):
    items = []
    sections = soup.select("section.insp_caset")

    for section in sections:
        inside = section.select_one("div.inside_box")
        pno = inside.get("pno", "") if inside else ""

        price_el = section.select_one("span.price")
        price = _parse_int(price_el.get_text(strip=True)) if price_el else None

        area_text = ""
        dl_lbs = section.select("dl.dl_lb")
        if dl_lbs:
            first_dd = dl_lbs[0].find("dd")
            if first_dd:
                spans = first_dd.find_all("span", class_="text")
                if spans:
                    area_text = spans[0].get_text(strip=True)

        address = ""
        for dl in dl_lbs:
            dt = dl.find("dt")
            if dt and "所在地" in dt.get_text():
                dd = dl.find("dd")
                if dd:
                    address = dd.get_text(strip=True)
                break

        comment_el = section.select_one("div.comment.web_pr p")
        comment = comment_el.get_text(strip=True) if comment_el else ""

        detail_url = ""
        detail_link = section.select_one("div.detail_view a[href]")
        if detail_link:
            href = detail_link["href"]
            detail_url = DETAIL_BASE + href if href.startswith("/") else href

        m2, tsubo = _parse_area(area_text)
        comment_data = _extract_from_comment(comment)

        items.append({
            "pno": pno,
            "price_manyen": price,
            "area_m2": m2,
            "area_tsubo": tsubo,
            "address": address,
            "comment": comment,
            "comment_data": comment_data,
            "detail_url": detail_url,
        })

    return items


def scrape(max_pages=None, target_facilities=None):
    session = requests.Session()

    url = f"{LIST_URL}?kodawari=3307&page=1-100"
    resp = session.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    total = _get_total_from_list(soup)
    logger.info("goohome: total %d items", total)

    all_items = _parse_list_page(soup)

    page_links = soup.select("div.insp_page-n a[href]")
    page_nums = set()
    for a in page_links:
        m = re.search(r"page=(\d+)-", a.get("href", ""))
        if m:
            page_nums.add(int(m.group(1)))

    total_pages = max(page_nums) if page_nums else 1
    if max_pages:
        total_pages = min(total_pages, max_pages)

    for page in range(2, total_pages + 1):
        time.sleep(REQUEST_INTERVAL)
        try:
            url = f"{LIST_URL}?kodawari=3307&page={page}-100"
            resp = session.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")
            items = _parse_list_page(soup)
            all_items.extend(items)
            logger.info("goohome: page %d/%d, %d items", page, total_pages, len(items))
        except Exception:
            logger.exception("goohome: failed page %d", page)

    all_listings = []
    for item in all_items:
        detail = {}
        if item.get("detail_url"):
            time.sleep(REQUEST_INTERVAL)
            detail = _scrape_detail(session, item["detail_url"])

        cd = item.get("comment_data", {})

        listing = {
            "source": "goohome",
            "name": item.get("comment", "")[:100],
            "facility": detail.get("facility") or cd.get("facility", ""),
            "address": item.get("address", ""),
            "price_manyen": item.get("price_manyen"),
            "annual_rent": detail.get("annual_rent") or cd.get("annual_rent"),
            "bairitsu": detail.get("bairitsu") or cd.get("bairitsu"),
            "area_m2": item.get("area_m2"),
            "area_tsubo": item.get("area_tsubo"),
            "property_tax": detail.get("property_tax"),
            "land_category": detail.get("land_category", ""),
            "rise_rate": detail.get("rise_rate") or cd.get("rise_rate"),
            "return_plan": detail.get("return_plan", ""),
            "notes": detail.get("notes", ""),
            "detail_url": item.get("detail_url", ""),
            "property_id": item.get("pno", ""),
        }
        all_listings.append(listing)

    if target_facilities:
        all_listings = [
            l for l in all_listings
            if any(f in l.get("facility", "") or f in l.get("name", "")
                   for f in target_facilities)
        ]

    logger.info("goohome: total %d listings after filter", len(all_listings))
    return all_listings
