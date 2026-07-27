#!/usr/bin/env python3
import sqlite3
import os, json, subprocess, time
from datetime import datetime, timedelta
from flask import Flask, jsonify, request, send_from_directory
import yfinance as yf

app = Flask(__name__)
DB_PATH = os.path.expanduser("~/stock-system/news.db")
CONFIG_PATH = os.path.expanduser("~/stock-system/config.json")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def load_config():
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except:
        return {}

def save_config(cfg):
    with open(CONFIG_PATH, 'w') as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

@app.route("/")
def index():
    return send_from_directory(".", "index.html")

@app.route("/news")
def news_page():
    return send_from_directory(".", "news.html")


@app.route("/settings")
def settings():
    return send_from_directory(".", "settings.html")

@app.route("/api/config", methods=["GET", "POST"])
def api_config():
    if request.method == "POST":
        data = request.get_json()
        # Merge with existing config rather than full replace
        existing = load_config()
        for section in data:
            if section in existing and isinstance(existing[section], dict) and isinstance(data[section], dict):
                existing[section].update(data[section])
            else:
                existing[section] = data[section]
        save_config(existing)
        return jsonify({"status": "ok", "config": existing})
    return jsonify(load_config())

@app.route("/api/logs")
def api_logs():
    """Return latest fetch log entries"""
    db = get_db()
    rows = db.execute("""
        SELECT source, fetched_count, new_count, fetched_at
        FROM fetch_log ORDER BY id DESC LIMIT 20
    """).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/status")
def api_status():
    """System health status"""
    cfg = load_config()
    # Check collector process
    import subprocess
    result = subprocess.run(
        ["ps", "aux"], capture_output=True, text=True
    )
    collector_running = "collector.py" in result.stdout
    last_log = {}
    try:
        db = get_db()
        last = db.execute("SELECT * FROM fetch_log ORDER BY id DESC LIMIT 1").fetchone()
        if last:
            last_log = dict(last)
        db.close()
    except:
        pass

    return jsonify({
        "collector_running": collector_running,
        "last_fetch": last_log,
        "config": cfg
    })

@app.route("/api/sources")
def api_sources_list():
    """List distinct news sources"""
    db = get_db()
    rows = db.execute("SELECT DISTINCT source FROM news ORDER BY source").fetchall()
    db.close()
    return jsonify([r["source"] for r in rows])


@app.route("/api/hot")
def api_hot():
    hours = request.args.get("hours", 24, type=int)
    since = (datetime.utcnow() - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    db = get_db()
    rows = db.execute("""
        SELECT s.stock_code, s.company_name, COUNT(*) as count
        FROM news_stocks s
        JOIN news n ON n.id = s.news_id
        WHERE n.published_at >= ?
        GROUP BY s.stock_code, s.company_name
        ORDER BY count DESC
        LIMIT 10
    """, (since,)).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/recent")
def api_recent():
    limit = request.args.get("limit", 20, type=int)
    db = get_db()
    rows = db.execute("""
        SELECT n.id, n.title, n.source, n.link, n.published_at,
               GROUP_CONCAT(s.stock_code || '|' || s.company_name, ',') as stocks
        FROM news n
        LEFT JOIN news_stocks s ON s.news_id = n.id
        GROUP BY n.id
        ORDER BY n.published_at DESC
        LIMIT ?
    """, (limit,)).fetchall()
    db.close()
    result = []
    for r in rows:
        d = dict(r)
        stocks_raw = d.pop("stocks", "") or ""
        d["related_stocks"] = []
        if stocks_raw:
            for item in stocks_raw.split(","):
                code, name = item.split("|", 1)
                d["related_stocks"].append({"stock_code": code, "company_name": name})
        result.append(d)
    return jsonify(result)

@app.route("/api/stats")
def api_stats():
    db = get_db()
    news_count = db.execute("SELECT COUNT(*) FROM news").fetchone()[0]
    stock_count = db.execute("SELECT COUNT(DISTINCT stock_code) FROM news_stocks").fetchone()[0]
    sources = db.execute("SELECT source, COUNT(*) as count FROM news GROUP BY source ORDER BY count DESC").fetchall()
    db.close()
    return jsonify({
        "total_news": news_count,
        "total_stocks": stock_count,
        "sources": [dict(r) for r in sources]
    })

@app.route("/api/timeline")
def api_timeline():
    hours = request.args.get("hours", 24, type=int)
    since = (datetime.utcnow() - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    db = get_db()
    rows = db.execute("""
        SELECT DATE(n.published_at) as date, COUNT(DISTINCT s.stock_code) as stock_mentions
        FROM news n
        JOIN news_stocks s ON s.news_id = n.id
        WHERE n.published_at >= ?
        GROUP BY DATE(n.published_at)
        ORDER BY date
    """, (since,)).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])



@app.route("/api/news")
def api_news():
    """Search/filter news with pagination"""
    date_from = request.args.get("from", "")
    date_to = request.args.get("to", "")
    source = request.args.get("source", "")
    stock_code = request.args.get("stock", "")
    keyword = request.args.get("q", "")
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)
    sort_dir = request.args.get("sort", "desc")
    per_page = min(per_page, 200)
    offset = (page - 1) * per_page

    db = get_db()

    where_clauses = []
    params = []

    if date_from:
        where_clauses.append("n.published_at >= ?")
        params.append(date_from)
    if date_to:
        where_clauses.append("n.published_at <= ?")
        params.append(date_to + "T23:59:59Z")
    if source:
        where_clauses.append("n.source = ?")
        params.append(source)
    if stock_code:
        where_clauses.append("s.stock_code = ?")
        params.append(stock_code)
    if keyword:
        where_clauses.append("n.title LIKE ?")
        params.append(f"%{keyword}%")

    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

    # Count total (without stock filter to avoid subquery issues, handle separately)
    if stock_code:
        count_sql = f"""SELECT COUNT(DISTINCT n.id) FROM news n
                      JOIN news_stocks s ON s.news_id = n.id
                      WHERE {where_sql}"""
    else:
        count_sql = f"SELECT COUNT(*) FROM news n WHERE {where_sql}"

    total = db.execute(count_sql, params).fetchone()[0]

    # Fetch with stock filter join
    if stock_code:
        query = f"""SELECT n.id, n.title, n.source, n.link, n.published_at,
                        GROUP_CONCAT(DISTINCT s2.stock_code || '|' || s2.company_name, ',') as stocks
                     FROM news n
                     JOIN news_stocks s ON s.news_id = n.id
                     LEFT JOIN news_stocks s2 ON s2.news_id = n.id
                     WHERE {where_sql}
                     GROUP BY n.id
                     ORDER BY n.published_at {sort_dir}
                     LIMIT ? OFFSET ?"""
    else:
        query = f"""SELECT n.id, n.title, n.source, n.link, n.published_at,
                        GROUP_CONCAT(s.stock_code || '|' || s.company_name, ',') as stocks
                     FROM news n
                     LEFT JOIN news_stocks s ON s.news_id = n.id
                     WHERE {where_sql}
                     GROUP BY n.id
                     ORDER BY n.published_at {sort_dir}
                     LIMIT ? OFFSET ?"""

    rows = db.execute(query, params + [per_page, offset]).fetchall()
    db.close()

    result = []
    for r in rows:
        d = dict(r)
        stocks_raw = d.pop("stocks", "") or ""
        d["related_stocks"] = []
        if stocks_raw:
            for item in stocks_raw.split(","):
                parts = item.split("|", 1)
                if len(parts) == 2:
                    d["related_stocks"].append({"stock_code": parts[0], "company_name": parts[1]})
        result.append(d)

    return jsonify({
        "data": result,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page if total > 0 else 0
    })


@app.route("/api/prices")
def api_prices():
    """Fetch real-time/latest close prices for watchlist"""
    cfg = load_config()
    watchlist = cfg.get("stocks", {}).get("watchlist", [])
    tickers = [s["code"] for s in watchlist]

    result = []
    batch_size = 8
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i+batch_size]
        try:
            data = yf.download(
                batch,
                period="1d",
                progress=False,
                group_by="ticker",
                threads=True
            )
        except Exception as e:
            data = None

        for ticker in batch:
            stock_info = {}
            for s in watchlist:
                if s["code"] == ticker:
                    stock_info = s
                    break

            entry = {
                "code": ticker,
                "name": stock_info.get("name", ticker),
                "market": "HK" if ".HK" in ticker else "US"
            }

            try:
                t = yf.Ticker(ticker, session=None)
                info = t.info if hasattr(t, 'info') else {}
                # Try fast path first (yf.download results)
                if data is not None and ticker in data.columns.levels[0] if hasattr(data.columns, 'levels') else False:
                    try:
                        row = data[ticker]
                        entry["close"] = round(float(row["Close"].iloc[-1]), 2) if pd.notna(row["Close"].iloc[-1]) else None
                        entry["open"] = round(float(row["Open"].iloc[-1]), 2) if pd.notna(row["Open"].iloc[-1]) else None
                        entry["high"] = round(float(row["High"].iloc[-1]), 2) if pd.notna(row["High"].iloc[-1]) else None
                        entry["low"] = round(float(row["Low"].iloc[-1]), 2) if pd.notna(row["Low"].iloc[-1]) else None
                        entry["volume"] = int(row["Volume"].iloc[-1]) if pd.notna(row["Volume"].iloc[-1]) else None
                    except:
                        pass

                # Fallback: use ticker.info for prev close and current
                try:
                    prv = info.get("previousClose")
                    cur = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("price")
                    if prv is not None:
                        entry["prev_close"] = round(float(prv), 2)
                    if entry.get("close") is None and cur is not None:
                        entry["close"] = round(float(cur), 2)
                    if entry.get("open") is None:
                        opn = info.get("open") or info.get("regularMarketOpen")
                        if opn is not None:
                            entry["open"] = round(float(opn), 2)
                    if entry.get("high") is None:
                        hi = info.get("dayHigh") or info.get("regularMarketDayHigh")
                        if hi is not None:
                            entry["high"] = round(float(hi), 2)
                    if entry.get("low") is None:
                        lo = info.get("dayLow") or info.get("regularMarketDayLow")
                        if lo is not None:
                            entry["low"] = round(float(lo), 2)
                    if entry.get("volume") is None:
                        vol = info.get("volume") or info.get("regularMarketVolume")
                        if vol is not None:
                            entry["volume"] = int(vol)
                except:
                    pass

                # Calculate change
                if entry.get("close") and entry.get("prev_close"):
                    entry["change"] = round(entry["close"] - entry["prev_close"], 2)
                    entry["change_pct"] = round(entry["change"] / entry["prev_close"] * 100, 2)
            except Exception as e:
                entry["error"] = str(e)

            result.append(entry)

        time.sleep(0.5)  # Rate limit

    # Summary stats
    gainers = [s for s in result if s.get("change_pct", 0) > 0]
    losers = [s for s in result if s.get("change_pct", 0) < 0]
    flat = [s for s in result if s.get("change_pct", 0) == 0]

    return jsonify({
        "data": result,
        "summary": {
            "total": len(result),
            "gainers": len(gainers),
            "losers": len(losers),
            "flat": len(flat),
            "top_gainer": max(gainers, key=lambda x: x.get("change_pct", 0)) if gainers else None,
            "top_loser": min(losers, key=lambda x: x.get("change_pct", 0)) if losers else None,
            "fetched_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        }
    })


@app.route("/api/sources-test", methods=["POST"])
def api_sources_test():
    """Test if an RSS URL returns valid XML"""
    data = request.get_json()
    url = data.get("url", "")
    if not url:
        return jsonify({"ok": False, "error": "No URL provided"})
    try:
        import requests
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code != 200:
            return jsonify({"ok": False, "status": resp.status_code, "error": f"HTTP {resp.status_code}"})
        text = resp.text
        if "<rss" in text[:2000] or "<feed" in text[:2000] or "<feed " in text[:2000]:
            # Count items
            import xml.etree.ElementTree as ET
            try:
                root = ET.fromstring(text)
                # Handle both RSS 2.0 and Atom
                channel = root.find("channel")
                if channel is not None:
                    items = len(channel.findall("item"))
                else:
                    items = len(root.findall("{http://www.w3.org/2005/Atom}entry"))
                return jsonify({"ok": True, "url": url, "item_count": items, "size_bytes": len(text)})
            except ET.ParseError as e:
                return jsonify({"ok": True, "warning": "Valid RSS but XML parse error", "error": str(e)})
        else:
            return jsonify({"ok": False, "error": "Response is not RSS/Atom XML", "preview": text[:200]})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8501, debug=False)
