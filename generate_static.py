#!/usr/bin/env python3
"""讀取 news.db → 生成靜態 JSON 放 docs/data/ 俾 GitHub Pages"""
import sqlite3, json, os, shutil, pathlib
from datetime import datetime, timedelta

DB_PATH = os.path.expanduser("~/stock-system/news.db")
OUT_DIR = os.path.expanduser("~/stock-system/docs")
DATA_DIR = os.path.join(OUT_DIR, "data")
CONFIG_PATH = os.path.expanduser("~/stock-system/config.json")

def load_config():
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except:
        return {}

cfg = load_config().get("generate", {})
HOT_HOURS = cfg.get("hot_window_hours", 24)
RECENT_HOURS = cfg.get("recent_window_hours", 48)
TOP_N = cfg.get("top_n_hot", 20)

os.makedirs(DATA_DIR, exist_ok=True)

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

def query(sql, params=()):
    return [dict(r) for r in conn.execute(sql, params).fetchall()]

# === 1. Hot list (24h) ===
since_hot = (datetime.utcnow() - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
since_recent = (datetime.utcnow() - timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%SZ")
hot = query("""
    SELECT ns.stock_code, ns.company_name, COUNT(*) as count
    FROM news_stocks ns JOIN news n ON ns.news_id = n.id
    WHERE n.published_at >= ?
    GROUP BY ns.stock_code ORDER BY count DESC LIMIT ?
""", (since_hot, TOP_N,))
with open(os.path.join(DATA_DIR, "hot.json"), "w") as f:
    json.dump(hot, f, ensure_ascii=False)

# === 2. Timeline (per hour, total stock mentions across all stocks) ===
rows = query("""
    SELECT strftime('%Y-%m-%dT%H:00:00', n.published_at) as hour,
           COUNT(*) as count
    FROM news_stocks ns JOIN news n ON ns.news_id = n.id
    WHERE n.published_at >= ?
    GROUP BY hour ORDER BY hour
""", (since_hot,))
# Transform to {date, stock_mentions} format the HTML expects
timeline = [{"date": r["hour"], "stock_mentions": r["count"]} for r in rows]
with open(os.path.join(DATA_DIR, "timeline.json"), "w") as f:
    json.dump(timeline, f, ensure_ascii=False)

# === 3. Recent news (last 30) ===
# Get recent news with their stock associations (separate query to avoid SQL complications)
recent_raw = query("""
    SELECT n.id, n.title, n.source, n.link, n.published_at
    FROM news n
    WHERE n.published_at >= ?
    ORDER BY n.published_at DESC LIMIT 30
""", (since_recent,))
recent = []
for article in recent_raw:
    stocks = query(
        "SELECT stock_code, company_name FROM news_stocks WHERE news_id = ?",
        (article["id"],)
    )
    article["related_stocks"] = [{"stock_code": s["stock_code"], "company": s["company_name"]} for s in stocks]
    article.pop("id", None)
    recent.append(article)

with open(os.path.join(DATA_DIR, "recent.json"), "w") as f:
    json.dump(recent, f, ensure_ascii=False)

# === 4a. All news (full dump for static browsing) ===
all_news_raw = query("""
    SELECT n.id, n.title, n.source, n.link, n.published_at
    FROM news n
    ORDER BY n.published_at DESC
""")
all_news = []
for article in all_news_raw:
    stocks = query(
        "SELECT stock_code, company_name FROM news_stocks WHERE news_id = ?",
        (article["id"],)
    )
    article["related_stocks"] = [{"stock_code": s["stock_code"], "company": s["company_name"]} for s in stocks]
    article.pop("id", None)
    all_news.append(article)

with open(os.path.join(DATA_DIR, "all_news.json"), "w") as f:
    json.dump(all_news, f, ensure_ascii=False)

# === 4b. Stats ===
total_news = query("SELECT COUNT(*) as cnt FROM news")[0]["cnt"]
stocks_24h = query("SELECT COUNT(DISTINCT stock_code) as cnt FROM news_stocks WHERE matched_at >= ?", (since_hot,))[0]["cnt"]
source_stats = query("SELECT source, COUNT(*) as count FROM news GROUP BY source ORDER BY count DESC")

stats = {
    "total_news": total_news,
    "total_stocks": stocks_24h,
    "sources": source_stats
}
with open(os.path.join(DATA_DIR, "stats.json"), "w") as f:
    json.dump(stats, f, ensure_ascii=False)

# === 5. Static index.html already written to docs/index.html, no copy needed ===

# Just write a timestamp
with open(os.path.join(DATA_DIR, "generated_at.txt"), "w") as f:
    f.write(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

conn.close()
print(f"✅ 靜態檔案已生成:")
print(f"   {len(hot)} 隻股票 hot.json")
print(f"   {len(recent)} 篇新聞 recent.json")
print(f"   {len(timeline)} 個數據點 timeline.json")
print(f"   {len(all_news)} 條新聞 all_news.json")
print(f"   stats.json (總 {total_news} 條新聞)")

# Git commit & push
os.chdir(os.path.dirname(os.path.abspath(__file__)))
result = os.system('git add docs/ && git diff --staged --quiet || (git commit -m "🤖 auto-update $(date +\'%Y-%m-%d %H:%M\')" && git push)')
if result == 0:
    print("✅ Git push 完成")
else:
    print("⚠ Git push 跳過（無更新或出錯）")
