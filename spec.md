# S26 — 手機 HTML 熱榜介面

## 目標
建立一個手機友好嘅 HTML 介面，替代 Streamlit，所有靜態檔案放喺 `~/stock-system/`。

## 規格

### 架構
- 純前後端分離：Python backend (FastAPI/Flask) + HTML/JS 前端
- 或者全靜態 HTML + Python 產生 JSON API
- backend run 喺 `0.0.0.0:8501`（覆蓋原有 Streamlit）

### 後端 (Python)
- 讀 `~/stock-system/news.db` (SQLite)
- API endpoints:
  - `GET /api/hot?hours=24` — 傳回 top 10 熱門股票 JSON (stock_code, company_name, count)
  - `GET /api/recent?limit=20` — 近期新聞 JSON (title, source, related_stocks, url)
  - `GET /api/stats` — 新聞總數、股票總數、來源統計
  - `GET /api/timeline?hours=24` — 趨勢 JSON (by day)

### 前端 (HTML/CSS/JS)
- 手機優先 responsive design
- 唔用 framework，純 vanilla HTML + CSS + JS
- 深色/淺色主題（跟 system preference）
- 頁面結構：
  1. Header: S26 標題 + 時間範圍選擇器 (6h/12h/24h/48h/72h)
  2. Stats card: 新聞總數、股票關聯數
  3. 熱門排行: Bar chart (用 Chart.js CDN 或者純 CSS bar)
  4. 提及趨勢圖表
  5. 新聞來源分佈
  6. 近期新聞列表（可摺疊）

### 技術要求
- Python 3.11+ (已安裝 flask/fastapi)
- SQLite `~/stock-system/news.db`
- 全部檔案放 `~/stock-system/` 目錄
- 寫一個 `run.sh` 啟動 backend server

## 輸出
- `backend.py` — Backend API server
- `index.html` — 前端頁面
- `run.sh` — 啟動腳本
