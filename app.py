#!/usr/bin/env python3
"""S26 — 手機友好股票新聞熱榜 (Streamlit)"""

import sqlite3
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta
import plotly.express as px
import plotly.graph_objects as go

DB_PATH = "/Users/user/stock-system/news.db"

st.set_page_config(page_title="S26 股票熱榜", page_icon="📈", layout="centered")

st.title("📈 S26 股票新聞熱榜")
st.caption("新聞驅動 · 自動更新")

# Sidebar
hrs = st.sidebar.slider("時間範圍（小時）", 1, 72, 24)
st.sidebar.write(f"顯示過去 {hrs} 小時")

@st.cache_data(ttl=60)
def load_data(hours):
    conn = sqlite3.connect(DB_PATH)
    cutoff = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")

    # Hot list
    hot = pd.read_sql(f"""
        SELECT ns.stock_code AS 代碼, ns.company_name AS 公司, COUNT(*) AS 提及次數
        FROM news_stocks ns JOIN news n ON ns.news_id = n.id
        WHERE ns.matched_at >= '{cutoff}'
        GROUP BY ns.stock_code ORDER BY 提及次數 DESC
    """, conn)

    # Recent matched news
    recent = pd.read_sql(f"""
        SELECT n.title AS 標題, n.source AS 來源,
               COALESCE(ns.stock_code || ' ' || ns.company_name, '') AS 關聯股票
        FROM news n LEFT JOIN news_stocks ns ON ns.news_id = n.id
        WHERE ns.matched_at >= '{cutoff}' OR n.fetched_at >= '{cutoff}'
        ORDER BY n.fetched_at DESC LIMIT 30
    """, conn)

    # Charts: mentions over time (last 24h)
    timeline = pd.read_sql(f"""
        SELECT ns.stock_code AS 代碼, DATE(ns.matched_at) AS 日期, COUNT(*) AS 次數
        FROM news_stocks ns
        WHERE ns.matched_at >= '{cutoff}'
        GROUP BY ns.stock_code, DATE(ns.matched_at)
        ORDER BY 日期
    """, conn)

    stats = pd.read_sql("SELECT source, COUNT(*) as cnt FROM news GROUP BY source", conn)

    total_news = conn.execute("SELECT COUNT(*) FROM news").fetchone()[0]
    total_matched = conn.execute("SELECT COUNT(*) FROM news_stocks").fetchone()[0]
    conn.close()
    return hot, recent, timeline, stats, total_news, total_matched

hot, recent, timeline, stats, total_news, total_matched = load_data(hrs)

# Summary cards
col1, col2, col3 = st.columns(3)
col1.metric("📰 新聞總數", total_news)
col2.metric("🔗 股票關聯", total_matched)
col3.metric("🕐 時段", f"{hrs}h")

# Hot list
st.subheader("🔥 熱門股票排行")
if not hot.empty:
    # Bar chart
    fig = px.bar(hot.head(10), x="公司", y="提及次數", color="提及次數",
                 text="提及次數", color_continuous_scale="Reds")
    fig.update_traces(textposition="outside")
    fig.update_layout(height=350, margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(fig, use_container_width=True)

    # Table
    st.dataframe(hot.head(10), use_container_width=True, hide_index=True)
else:
    st.info("暫無數據，等新聞收集器繼續工作...")

# Timeline chart
if not timeline.empty:
    st.subheader("📅 提及趨勢")
    fig2 = px.line(timeline, x="日期", y="次數", color="代碼",
                   markers=True, height=300)
    fig2.update_layout(margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(fig2, use_container_width=True)

# Source stats
if not stats.empty:
    st.subheader("📡 新聞來源")
    fig3 = px.pie(stats, names="source", values="cnt", height=250)
    fig3.update_layout(margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(fig3, use_container_width=True)

# Recent news
st.subheader("📋 近期新聞")
if not recent.empty:
    for _, row in recent.iterrows():
        with st.expander(row["標題"][:60]):
            st.write(f"**來源:** {row['來源']}")
            if row["關聯股票"]:
                st.write(f"**關聯股票:** {row['關聯股票']}")
else:
    st.info("暫無新聞")

st.caption("S26 v1.0 · Data updated every 2 minutes")
