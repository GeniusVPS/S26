#!/usr/bin/env python3
import sqlite3
import os
from datetime import datetime, timedelta
from flask import Flask, jsonify, request, send_from_directory

app = Flask(__name__)
DB_PATH = os.path.expanduser("~/stock-system/news.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

@app.route("/")
def index():
    return send_from_directory(".", "index.html")

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
