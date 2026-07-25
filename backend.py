#!/usr/bin/env python3
import sqlite3
import os, json, subprocess, time
from datetime import datetime, timedelta
from flask import Flask, jsonify, request, send_from_directory

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

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8501, debug=False)
