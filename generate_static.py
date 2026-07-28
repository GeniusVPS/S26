#!/usr/bin/env python3
"""讀取 news.db → 生成靜態 JSON 放 docs/data/ 俾 GitHub Pages"""
import sqlite3, json, os, shutil, pathlib, yfinance as yf
from datetime import datetime, timedelta

# ── Stock sector mapping ──
SECTORS = {
    "0700.HK": {"sector": "科技·互聯網", "sub": "社交·遊戲·支付"},
    "9988.HK": {"sector": "科技·電商", "sub": "電商·雲端·物流"},
    "1810.HK": {"sector": "消費電子", "sub": "手機·IoT·電動車"},
    "3690.HK": {"sector": "科技·本地生活", "sub": "外賣·到店·旅遊"},
    "9618.HK": {"sector": "科技·電商", "sub": "電商·物流·科技"},
    "1211.HK": {"sector": "汽車·新能源", "sub": "電動車·電池"},
    "9999.HK": {"sector": "科技·遊戲", "sub": "遊戲·音樂·教育"},
    "0388.HK": {"sector": "金融", "sub": "交易所·市場數據"},
    "0005.HK": {"sector": "金融·銀行", "sub": "零售·財富管理"},
    "9888.HK": {"sector": "科技·互聯網", "sub": "搜尋·AI·自動駕駛"},
    "1024.HK": {"sector": "半導體", "sub": "AI晶片"},
    "NVDA":   {"sector": "半導體·AI", "sub": "GPU·AI晶片"},
    "AAPL":   {"sector": "消費電子", "sub": "iPhone·Mac·服務"},
    "TSLA":   {"sector": "電動車", "sub": "電動車·能源·AI"},
    "MSFT":   {"sector": "科技·軟件", "sub": "雲端·Office·AI"},
    "AMZN":   {"sector": "科技·電商/雲端", "sub": "電商·AWS"},
    "GOOGL":  {"sector": "科技·互聯網", "sub": "搜尋·廣告·AI"},
    "META":   {"sector": "科技·社交", "sub": "社交平台·VR·AI"},
    "BABA":   {"sector": "科技·電商", "sub": "電商·雲端"},
}

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
hot_raw = query("""
    SELECT ns.stock_code, ns.company_name, COUNT(*) as count
    FROM news_stocks ns JOIN news n ON ns.news_id = n.id
    WHERE n.published_at >= ?
    GROUP BY ns.stock_code ORDER BY count DESC LIMIT ?
""", (since_hot, TOP_N,))

# Fetch prices for all hot stocks
tickers = [s["stock_code"] for s in hot_raw]
price_data = {}
if tickers:
    try:
        prices = yf.download(tickers, period="2d", auto_adjust=True, progress=False)
        close = prices["Close"] if "Close" in prices.columns else prices.get("Close", None)
        if close is not None and len(close) > 0:
            for t in tickers:
                try:
                    if len(close) >= 2:
                        current, prev = close[t].iloc[-1], close[t].iloc[-2]
                        pct = round((current - prev) / prev * 100, 1)
                    elif len(close) == 1:
                        current = close[t].iloc[-1]
                        prev = None
                        pct = 0
                    else:
                        current = prev = pct = None
                    price_data[t] = {
                        "price": round(current, 2) if current else None,
                        "change_pct": pct
                    }
                except:
                    price_data[t] = {"price": None, "change_pct": None}
    except Exception as e:
        print(f"⚠ Price fetch failed: {e}")
        for t in tickers:
            price_data[t] = {"price": None, "change_pct": None}

# Build enhanced hot list
hot = []
for s in hot_raw:
    code = s["stock_code"]
    name = s["company_name"]
    count = s["count"]
    
    # Sentiment for this stock
    sent = query("""
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN n.sentiment = 'positive' THEN 1 ELSE 0 END) as pos,
            SUM(CASE WHEN n.sentiment = 'neutral' THEN 1 ELSE 0 END) as neu,
            SUM(CASE WHEN n.sentiment = 'negative' THEN 1 ELSE 0 END) as neg
        FROM news_stocks ns JOIN news n ON ns.news_id = n.id
        WHERE ns.stock_code = ? AND n.sentiment IS NOT NULL
    """, (code,))[0]
    
    sent_total = sent["total"]
    if sent_total > 0:
        sent_score = round((sent["pos"] - sent["neg"]) / sent_total * 100, 1)
    else:
        sent_score = None
    
    sector_info = SECTORS.get(code, {"sector": "其他", "sub": ""})
    
    # Build summary
    p = price_data.get(code, {})
    price_str = f"${p['price']}" if p.get('price') else ""
    change_str = f"{p['change_pct']:+.1f}%" if p.get('change_pct') is not None else ""
    sentiment_str = f"🧠 {sent_score}" if sent_score is not None else "🧠 N/A"
    summary = f"{price_str} {change_str} | {sector_info['sector']} | {sentiment_str}"
    
    hot.append({
        "code": code,
        "name": name,
        "count": count,
        "sector": sector_info["sector"],
        "sub": sector_info["sub"],
        "price": p.get("price"),
        "change_pct": p.get("change_pct"),
        "sentiment_score": sent_score,
        "summary": summary.strip()
    })

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
    SELECT n.id, n.title, n.source, n.link, n.published_at, n.sentiment
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
    article["sentiment"] = article.pop("sentiment", None)
    article.pop("id", None)
    all_news.append(article)

with open(os.path.join(DATA_DIR, "all_news.json"), "w") as f:
    json.dump(all_news, f, ensure_ascii=False)

# === 4b. Stats ===
total_news = query("SELECT COUNT(*) as cnt FROM news")[0]["cnt"]
stocks_24h = query("SELECT COUNT(DISTINCT stock_code) as cnt FROM news_stocks WHERE matched_at >= ?", (since_hot,))[0]["cnt"]
source_stats = query("SELECT source, COUNT(*) as count FROM news GROUP BY source ORDER BY count DESC")

sentiment_stats = query("""
    SELECT 
        SUM(CASE WHEN sentiment = 'positive' THEN 1 ELSE 0 END) as positive,
        SUM(CASE WHEN sentiment = 'negative' THEN 1 ELSE 0 END) as negative,
        SUM(CASE WHEN sentiment = 'neutral' THEN 1 ELSE 0 END) as neutral
    FROM news
""")[0]

stats = {
    "total_news": total_news,
    "total_stocks": stocks_24h,
    "sources": source_stats,
    "sentiment": {
        "positive": sentiment_stats["positive"] or 0,
        "negative": sentiment_stats["negative"] or 0,
        "neutral": sentiment_stats["neutral"] or 0
    }
}

# Sentiment score: positive% - negative%
pos_pct = stats["sentiment"]["positive"]
neg_pct = stats["sentiment"]["negative"]
total_s = pos_pct + neg_pct + stats["sentiment"]["neutral"]
sentiment_score = round((pos_pct - neg_pct) / total_s * 100, 1) if total_s > 0 else 0
if sentiment_score > 15:
    mood = "😊 樂觀"
elif sentiment_score > 5:
    mood = "🙂 偏樂觀"
elif sentiment_score > -5:
    mood = "😐 中性"
elif sentiment_score > -15:
    mood = "😟 偏悲觀"
else:
    mood = "😨 悲觀"
# Stock-level sentiment
stock_sent = query("""
    SELECT ns.stock_code, ns.company_name,
           COUNT(*) as total,
           SUM(CASE WHEN n.sentiment = 'positive' THEN 1 ELSE 0 END) as pos,
           SUM(CASE WHEN n.sentiment = 'neutral' THEN 1 ELSE 0 END) as neu,
           SUM(CASE WHEN n.sentiment = 'negative' THEN 1 ELSE 0 END) as neg
    FROM news_stocks ns JOIN news n ON ns.news_id = n.id
    WHERE n.sentiment IS NOT NULL
    GROUP BY ns.stock_code
    HAVING total > 5
    ORDER BY total DESC LIMIT 10
""")
stocks_with_sentiment = [{
    "code": r["stock_code"],
    "name": r["company_name"],
    "total": r["total"],
    "positive": r["pos"],
    "neutral": r["neu"],
    "negative": r["neg"],
    "score": round((r["pos"] - r["neg"]) / r["total"] * 100, 1)
} for r in stock_sent]
stats["stocks"] = stocks_with_sentiment
stats["sentiment_score"] = sentiment_score
stats["sentiment_mood"] = mood
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
