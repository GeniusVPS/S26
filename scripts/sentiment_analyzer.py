#!/usr/bin/env python3
"""Batch sentiment analysis for S26 news using llama-server (Qwen3.6-27B)"""
import sqlite3, json, re, os, sys, time

DB = os.path.expanduser("~/stock-system/news.db")
BATCH_SIZE = 20
SLEEP_BETWEEN = 0.5  # seconds between batches
SAMPLE_LIMIT = None  # None = all, set to small number for testing

def get_untagged(conn, limit=50):
    c = conn.execute(
        "SELECT id, title FROM news WHERE sentiment IS NULL OR sentiment = '' ORDER BY published_at DESC LIMIT ?",
        (limit,)
    )
    return c.fetchall()

def build_prompt(titles):
    """Build classification prompt"""
    items = []
    for i, (tid, title) in enumerate(titles):
        escaped = title.replace('"', "'").strip()
        items.append(f'{i}: "{escaped}"')
    
    prompt = f"""Classify each headline as positive, negative, or neutral.

Consider:
- Buyback/dividend/price up = positive
- Price down/losses/layoff/lawsuit = negative
- General market news/earnings reports/factual = neutral

Reply JSON only:
[
  {{"idx": 0, "sentiment": "positive"}},
  ...
]

Headlines:
{chr(10).join(items)}
"""
    return prompt

def parse_response(text, expected_count):
    """Parse JSON response, fallback to regex"""
    text = text.strip()
    # Try direct JSON
    try:
        data = json.loads(text)
        if isinstance(data, list) and len(data) == expected_count:
            return data
    except:
        pass
    
    # Try to find JSON block
    m = re.search(r'\[.*?\]', text, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group())
            if isinstance(data, list):
                return data
        except:
            pass
    
    return None

def analyze_batch(conn, items):
    """Analyze one batch of headlines via llama-server (port 8080)"""
    prompt = build_prompt(items)
    
    try:
        import urllib.request
        payload = json.dumps({
            "model": "/Users/user/qwen3.6-27b-q4_k_m.gguf",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 1024,
            "temperature": 0.1,
            "stream": False
        }).encode()
        
        req = urllib.request.Request(
            "http://127.0.0.1:8080/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json"}
        )
        
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read())
        
        raw = result.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        
        # Parse
        parsed = parse_response(raw, len(items))
        if parsed is None:
            print(f"  ⚠ Parse failed. Response: {raw[:200]}")
            return False
        
        # Update DB
        update_count = 0
        for entry in parsed:
            idx = entry.get("idx")
            sentiment = entry.get("sentiment", "")
            if idx is not None and sentiment in ("positive", "negative", "neutral"):
                actual_id = items[idx][0]
                conn.execute(
                    "UPDATE news SET sentiment = ? WHERE id = ?",
                    (sentiment, actual_id)
                )
                update_count += 1
        
        conn.commit()
        print(f"  ✓ {update_count}/{len(items)} tagged")
        return True
        
    except Exception as e:
        print(f"  ✗ Error: {e}")
        return False

def main():
    db_path = os.path.expanduser(DB)
    # Get absolute path for git repo detection
    if not os.path.exists(db_path):
        print(f"DB not found at {db_path}")
        sys.exit(1)
    
    conn = sqlite3.connect(db_path)
    
    # Count
    total = conn.execute("SELECT COUNT(*) FROM news").fetchone()[0]
    tagged = conn.execute("SELECT COUNT(*) FROM news WHERE sentiment IS NOT NULL AND sentiment != ''").fetchone()[0]
    print(f"News total: {total}, Tagged: {tagged}")
    
    limit = SAMPLE_LIMIT
    while True:
        items = get_untagged(conn, min(BATCH_SIZE, limit) if limit else BATCH_SIZE)
        if not items:
            print("✓ All done!")
            break
        
        ids_str = ", ".join(str(x[0]) for x in items[:3])
        print(f"  Processing {len(items)} items (e.g. IDs: {ids_str}…)")
        
        ok = analyze_batch(conn, items)
        if not ok:
            print("  Retrying next batch...")
            time.sleep(1)
        
        if limit:
            limit -= len(items)
            if limit <= 0:
                break
        
        time.sleep(SLEEP_BETWEEN)
    
    conn.close()
    
    # Final count
    conn2 = sqlite3.connect(db_path)
    final = conn2.execute("SELECT sentiment, COUNT(*) FROM news WHERE sentiment IS NOT NULL AND sentiment != '' GROUP BY sentiment").fetchall()
    print(f"\nFinal sentiment distribution:")
    for s, c in final:
        print(f"  {s}: {c}")
    untagged = conn2.execute("SELECT COUNT(*) FROM news WHERE sentiment IS NULL OR sentiment = ''").fetchone()[0]
    print(f"  untagged: {untagged}")
    conn2.close()

if __name__ == "__main__":
    main()
