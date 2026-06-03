#!/usr/bin/env python3
"""沖縄軍用地検索ダッシュボード"""

import os
import sqlite3
import logging
import hashlib
from datetime import datetime

from flask import Flask, render_template, request, jsonify
from apscheduler.schedulers.background import BackgroundScheduler

from scrapers import tomato, oroku

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)

DB_DIR = os.environ.get("DATA_DIR", ".")
DB_PATH = os.path.join(DB_DIR, "gunyouchi.db")

TARGET_FACILITIES = ["嘉手納飛行場", "嘉手納弾薬庫"]
SCRAPE_MAX_PAGES = None
SCRAPE_INTERVAL_HOURS = 3


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS properties (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hash TEXT UNIQUE NOT NULL,
            source TEXT NOT NULL,
            name TEXT,
            facility TEXT,
            address TEXT,
            price_manyen INTEGER,
            annual_rent INTEGER,
            bairitsu REAL,
            area_m2 REAL,
            area_tsubo REAL,
            property_tax INTEGER,
            land_category TEXT,
            rise_rate REAL,
            return_plan TEXT,
            notes TEXT,
            detail_url TEXT,
            property_id TEXT,
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            is_active INTEGER DEFAULT 1
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scrape_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            source TEXT,
            total_found INTEGER,
            new_count INTEGER,
            updated_count INTEGER,
            status TEXT
        )
    """)
    conn.commit()
    conn.close()


def _make_hash(listing):
    key = f"{listing.get('source', '')}-{listing.get('detail_url', '')}-{listing.get('name', '')}"
    return hashlib.md5(key.encode()).hexdigest()


def upsert_listings(listings):
    conn = get_db()
    now = datetime.now().isoformat()
    new_count = 0
    updated_count = 0

    for l in listings:
        h = _make_hash(l)
        existing = conn.execute("SELECT id, price_manyen, bairitsu, annual_rent FROM properties WHERE hash = ?", (h,)).fetchone()

        if existing:
            conn.execute("""
                UPDATE properties SET
                    price_manyen = ?, annual_rent = ?, bairitsu = ?,
                    area_m2 = ?, area_tsubo = ?, property_tax = ?,
                    rise_rate = ?, notes = ?, last_seen = ?, is_active = 1
                WHERE hash = ?
            """, (
                l.get("price_manyen"), l.get("annual_rent"), l.get("bairitsu"),
                l.get("area_m2"), l.get("area_tsubo"), l.get("property_tax"),
                l.get("rise_rate"), l.get("notes", ""), now, h,
            ))
            updated_count += 1
        else:
            conn.execute("""
                INSERT INTO properties (hash, source, name, facility, address,
                    price_manyen, annual_rent, bairitsu, area_m2, area_tsubo,
                    property_tax, land_category, rise_rate, return_plan, notes,
                    detail_url, property_id, first_seen, last_seen, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """, (
                h, l.get("source", ""), l.get("name", ""), l.get("facility", ""),
                l.get("address", ""),
                l.get("price_manyen"), l.get("annual_rent"), l.get("bairitsu"),
                l.get("area_m2"), l.get("area_tsubo"), l.get("property_tax"),
                l.get("land_category", ""), l.get("rise_rate"),
                l.get("return_plan", ""), l.get("notes", ""),
                l.get("detail_url", ""), l.get("property_id", ""),
                now, now,
            ))
            new_count += 1

    conn.commit()
    conn.close()
    return new_count, updated_count


def run_scrape():
    logger.info("Starting scrape...")
    conn = get_db()
    now = datetime.now().isoformat()
    conn.execute("INSERT INTO scrape_log (started_at, status) VALUES (?, 'running')", (now,))
    conn.commit()
    log_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()

    all_listings = []
    sources_status = []

    for name, scraper in [("tomato", tomato), ("oroku", oroku)]:
        try:
            listings = scraper.scrape(
                max_pages=SCRAPE_MAX_PAGES,
                target_facilities=TARGET_FACILITIES,
            )
            all_listings.extend(listings)
            sources_status.append(f"{name}: {len(listings)}")
            logger.info("%s: found %d listings", name, len(listings))
        except Exception:
            logger.exception("Scrape failed: %s", name)
            sources_status.append(f"{name}: error")

    new_count, updated_count = upsert_listings(all_listings)

    conn = get_db()
    conn.execute("""
        UPDATE scrape_log SET finished_at = ?, source = ?, total_found = ?,
            new_count = ?, updated_count = ?, status = 'done'
        WHERE id = ?
    """, (datetime.now().isoformat(), ", ".join(sources_status),
          len(all_listings), new_count, updated_count, log_id))
    conn.commit()
    conn.close()

    logger.info("Scrape done: %d found, %d new, %d updated", len(all_listings), new_count, updated_count)


@app.route("/")
def index():
    return render_template("dashboard.html")


@app.route("/api/properties")
def api_properties():
    conn = get_db()

    facility = request.args.get("facility", "")
    sort_by = request.args.get("sort", "bairitsu")
    sort_order = request.args.get("order", "asc")
    min_bairitsu = request.args.get("min_bairitsu", "")
    max_bairitsu = request.args.get("max_bairitsu", "")
    min_rent = request.args.get("min_rent", "")
    max_rent = request.args.get("max_rent", "")
    source = request.args.get("source", "")

    allowed_sort = {"bairitsu", "price_manyen", "annual_rent", "rise_rate", "area_tsubo", "first_seen", "last_seen"}
    if sort_by not in allowed_sort:
        sort_by = "bairitsu"
    if sort_order not in ("asc", "desc"):
        sort_order = "asc"

    query = "SELECT * FROM properties WHERE is_active = 1"
    params = []

    if facility:
        query += " AND facility LIKE ?"
        params.append(f"%{facility}%")

    if min_bairitsu:
        query += " AND bairitsu >= ?"
        params.append(float(min_bairitsu))
    if max_bairitsu:
        query += " AND bairitsu <= ?"
        params.append(float(max_bairitsu))

    if min_rent:
        query += " AND annual_rent >= ?"
        params.append(int(min_rent))
    if max_rent:
        query += " AND annual_rent <= ?"
        params.append(int(max_rent))

    if source:
        query += " AND source = ?"
        params.append(source)

    query += f" ORDER BY {sort_by} IS NULL, {sort_by} {sort_order}"

    rows = conn.execute(query, params).fetchall()
    conn.close()

    properties = [dict(row) for row in rows]
    return jsonify(properties)


@app.route("/api/stats")
def api_stats():
    conn = get_db()

    total = conn.execute("SELECT COUNT(*) FROM properties WHERE is_active = 1").fetchone()[0]

    kadena_base = conn.execute(
        "SELECT COUNT(*) FROM properties WHERE is_active = 1 AND facility LIKE '%嘉手納飛行場%'"
    ).fetchone()[0]
    kadena_ammo = conn.execute(
        "SELECT COUNT(*) FROM properties WHERE is_active = 1 AND facility LIKE '%嘉手納弾薬庫%'"
    ).fetchone()[0]

    avg_bairitsu = conn.execute(
        "SELECT AVG(bairitsu) FROM properties WHERE is_active = 1 AND bairitsu IS NOT NULL"
    ).fetchone()[0]

    avg_rise = conn.execute(
        "SELECT AVG(rise_rate) FROM properties WHERE is_active = 1 AND rise_rate IS NOT NULL"
    ).fetchone()[0]

    last_scrape = conn.execute(
        "SELECT finished_at, total_found, new_count FROM scrape_log ORDER BY id DESC LIMIT 1"
    ).fetchone()

    conn.close()

    return jsonify({
        "total": total,
        "kadena_base": kadena_base,
        "kadena_ammo": kadena_ammo,
        "avg_bairitsu": round(avg_bairitsu, 1) if avg_bairitsu else None,
        "avg_rise_rate": round(avg_rise, 2) if avg_rise else None,
        "last_scrape": dict(last_scrape) if last_scrape else None,
    })


@app.route("/api/scrape", methods=["POST"])
def api_scrape():
    """Trigger manual scrape."""
    import threading
    t = threading.Thread(target=run_scrape)
    t.start()
    return jsonify({"status": "started"})


@app.route("/api/scrape-log")
def api_scrape_log():
    conn = get_db()
    rows = conn.execute("SELECT * FROM scrape_log ORDER BY id DESC LIMIT 20").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


init_db()

scheduler = BackgroundScheduler()
scheduler.add_job(run_scrape, "interval", hours=SCRAPE_INTERVAL_HOURS, id="scrape_job")
scheduler.start()

if __name__ == "__main__":
    app.run(debug=True, port=5002)
