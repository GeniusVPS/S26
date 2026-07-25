#!/usr/bin/env python3
"""Phase 1: 新聞收集器 + 股票實體提取"""

import json
import time
import os
import sqlite3
import feedparser
import requests
from datetime import datetime, timedelta

CONFIG_PATH = os.path.expanduser("~/stock-system/config.json")
DB_PATH = "news.db"
STOCKS_JSON = "stocks.json"

def load_config():
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except:
        return {}

def get_rss_sources():
    cfg = load_config()
    src_list = cfg.get("collector", {}).get("rss_sources", [
        {"name": "rthk", "url": "https://news.rthk.hk/rthk/en/rss/finance.xml", "enabled": True},
        {"name": "yahoo", "url": "https://finance.yahoo.com/news/rssindex", "enabled": True},
    ])
    return {s["name"]: s["url"] for s in src_list if s.get("enabled", True)}

def get_interval():
    cfg = load_config()
    return cfg.get("collector", {}).get("interval_minutes", 30)

def get_google_news_url():
    cfg = load_config()
    return cfg.get("collector", {}).get("google_news_url", "https://news.google.com/rss/search?q=港股&hl=zh-TW&gl=HK&ceid=HK:zh-Hant")


def init_db(conn):
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS news (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            title TEXT NOT NULL,
            link TEXT NOT NULL UNIQUE,
            summary TEXT,
            published_at TEXT,
            fetched_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS news_stocks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            news_id INTEGER NOT NULL REFERENCES news(id),
            stock_code TEXT NOT NULL,
            company_name TEXT NOT NULL,
            matched_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS fetch_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            fetched_count INTEGER DEFAULT 0,
            new_count INTEGER DEFAULT 0,
            fetched_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.commit()


def fetch_rss(url):
    """Parse RSS feed, return list of article dicts."""
    try:
        feed = feedparser.parse(url)
        articles = []
        for entry in feed.entries:
            published = ""
            if hasattr(entry, "published"):
                published = entry.published
            summary = ""
            if hasattr(entry, "summary"):
                summary = entry.summary
            articles.append({
                "title": entry.get("title", ""),
                "link": entry.get("link", ""),
                "summary": summary,
                "published_at": published,
            })
        return articles
    except Exception as e:
        print(f"  ✗ RSS fetch 錯誤: {e}")
        return []


def fetch_google_news(keyword="港股", rss_url=None):
    """Fetch Google News RSS with user-agent header."""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
        resp = requests.get(rss_url, headers=headers, timeout=15)
        resp.raise_for_status()
        feed = feedparser.parse(resp.text)
        articles = []
        for entry in feed.entries:
            published = ""
            if hasattr(entry, "published"):
                published = entry.published
            summary = ""
            if hasattr(entry, "summary"):
                summary = entry.summary
            articles.append({
                "title": entry.get("title", ""),
                "link": entry.get("link", ""),
                "summary": summary,
                "published_at": published,
            })
        return articles
    except Exception as e:
        print(f"  ✗ Google News fetch 錯誤: {e}")
        return []


def extract_stocks(title, summary, stocks_map):
    """Match keywords from stocks_map against title + summary."""
    text = f"{title} {summary}"
    matched = []
    seen_codes = set()
    for keyword in stocks_map:
        if keyword in text:
            info = stocks_map[keyword]
            if info["code"] not in seen_codes:
                seen_codes.add(info["code"])
                matched.append({"code": info["code"], "name": info["name"]})
    return matched


def normalize_date(date_str):
    """统一日期格式为 ISO-8601"""
    from email.utils import parsedate_to_datetime
    if not date_str:
        return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return date_str
    except (ValueError, TypeError):
        pass
    try:
        dt = parsedate_to_datetime(date_str)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, TypeError):
        return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def save_article(conn, source, article, stocks_map):
    """Insert article with dedup by link. Match stocks if new."""
    c = conn.cursor()
    try:
        c.execute(
            "INSERT INTO news (source, title, link, summary, published_at) VALUES (?, ?, ?, ?, ?)",
            (source, article["title"], article["link"], article["summary"], normalize_date(article["published_at"])),
        )
        news_id = c.lastrowid
        matched = extract_stocks(article["title"], article["summary"], stocks_map)
        for s in matched:
            c.execute(
                "INSERT INTO news_stocks (news_id, stock_code, company_name) VALUES (?, ?, ?)",
                (news_id, s["code"], s["name"]),
            )
        conn.commit()
        return True, matched
    except sqlite3.IntegrityError:
        return False, []


def log_fetch(conn, source, fetched_count, new_count):
    c = conn.cursor()
    c.execute(
        "INSERT INTO fetch_log (source, fetched_count, new_count) VALUES (?, ?, ?)",
        (source, fetched_count, new_count),
    )
    conn.commit()


def print_hot_list(conn, hours=24):
    """Show top 10 most mentioned stocks in last N hours."""
    c = conn.cursor()
    cutoff = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    c.execute("""
        SELECT ns.stock_code, ns.company_name, COUNT(*) as cnt
        FROM news_stocks ns
        JOIN news n ON ns.news_id = n.id
        WHERE ns.matched_at >= ?
        GROUP BY ns.stock_code
        ORDER BY cnt DESC
        LIMIT 10
    """, (cutoff,))
    rows = c.fetchall()
    print("\n🔥 近 24 小時熱門股票 Top 10:")
    print("-" * 45)
    if rows:
        print(f"{'排名':<5} {'股票代碼':<12} {'公司名':<15} {'提及次數':<8}")
        print("-" * 45)
        for i, (code, name, cnt) in enumerate(rows, 1):
            print(f"{i:<5} {code:<12} {name:<15} {cnt:<8}")
    else:
        print("  （暫無數據）")
    print("-" * 45)


def main():
    with open(STOCKS_JSON, "r", encoding="utf-8") as f:
        stocks_map = json.load(f)

    conn = sqlite3.connect(DB_PATH)
    init_db(conn)
    print(f"✓ 已載入 {len(stocks_map)} 個股票關鍵字")
    print(f"✓ 資料庫: {DB_PATH}")
    print("=" * 50)

    try:
        round_num = 0
        while True:
            round_num += 1
            # Reload config each round so live edits take effect
            rss_sources = get_rss_sources()
            interval = get_interval()
            google_url = get_google_news_url()
            print(f"\n=== 第 {round_num} 輪抓取 ({datetime.now().strftime('%H:%M:%S')}) ===")

            # Fetch from each RSS source
            for source_name, rss_url in rss_sources.items():
                print(f"\n📡 正在抓取 {source_name}...")
                try:
                    articles = fetch_rss(rss_url)
                    new_count = 0
                    for art in articles:
                        is_new, matched = save_article(conn, source_name, art, stocks_map)
                        if is_new:
                            new_count += 1
                            if matched:
                                codes = ", ".join(f"{m['name']}({m['code']}" for m in matched)
                                print(f"  ★ 新文章: {art['title'][:40]}... → {codes})")
                    log_fetch(conn, source_name, len(articles), new_count)
                    print(f"  ✓ {source_name}: 共 {len(articles)} 篇, 新增 {new_count} 篇")
                except Exception as e:
                    print(f"  ✗ {source_name} 抓取失敗: {e}")
                    log_fetch(conn, source_name, 0, 0)

            # Google News
            print(f"\n📡 正在抓取 Google News (港股)...")
            try:
                articles = fetch_google_news("港股", google_url)
                new_count = 0
                for art in articles:
                    is_new, matched = save_article(conn, "google", art, stocks_map)
                    if is_new:
                        new_count += 1
                        if matched:
                            codes = ", ".join(f"{m['name']}({m['code']})" for m in matched)
                            print(f"  ★ 新文章: {art['title'][:40]}... → {codes}")
                log_fetch(conn, "google", len(articles), new_count)
                print(f"  ✓ google: 共 {len(articles)} 篇, 新增 {new_count} 篇")
            except Exception as e:
                print(f"  ✗ Google News 抓取失敗: {e}")
                log_fetch(conn, "google", 0, 0)

            # Print hot list
            print_hot_list(conn)
            print(f"\n⏰ 下次抓取: {interval} 分鐘後... (Ctrl+C 停止)")
            time.sleep(interval * 60)

    except KeyboardInterrupt:
        print("\n\n👋 已停止收集器。再見！")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
