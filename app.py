#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
波段 & 當沖交易系統
NT$500,000 資本 × 月目標 NT$50,000
Signal-based: App 給訊號，手動下單
"""
import sys, os, json, warnings
from datetime import datetime, timezone, timedelta
import streamlit as st
import pandas as pd
import numpy as np

warnings.filterwarnings("ignore")

TST = timezone(timedelta(hours=8))
NOW = datetime.now(tz=TST)

# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="波段/當沖交易系統",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Imports ──────────────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

try:
    from scanner import (
        scan_swing_setups, scan_daytrade_setups,
        simulate_monthly_return, SWING_SETUP_TYPES,
    )
    from risk import (
        calc_position_size, calc_target_prices,
        open_trade, close_trade, update_stop,
        get_open_trades, get_closed_trades, compute_stats, daily_risk_check,
        CAPITAL, RISK_PER_TRADE_PCT, DAILY_LOSS_LIMIT, MONTHLY_LOSS_LIMIT,
        MAX_POSITIONS,
    )
    from widget import (
        fetch_prices_batch, fetch_taiex_prices, calc_market_direction,
        TECH_UNIVERSE,
    )
except Exception as _e:
    st.error(f"載入失敗：{_e}")
    import traceback; st.code(traceback.format_exc())
    st.stop()

# ─────────────────────────────────────────────────────────────────────────────
#  CSS
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
  .stApp { background: #060d1a; color: #e0e0e0; }
  section[data-testid="stSidebar"] { background: #080f1e !important; }
  .metric-card {
    background: #0d1928; border: 1px solid #1a2a40; border-radius: 10px;
    padding: 14px 18px; margin-bottom: 10px;
  }
  .metric-title { font-size: 11px; color: #778; margin-bottom: 4px; font-weight: 600; letter-spacing: .5px; }
  .metric-val   { font-size: 22px; font-weight: 800; }
  .setup-card {
    background: #080f1e; border: 1px solid #1a2a4088; border-radius: 10px;
    padding: 14px 18px; margin-bottom: 12px;
  }
  .signal-buy  { color: #ef5350; font-weight: 700; }
  .signal-sell { color: #00c853; font-weight: 700; }
  .badge {
    display: inline-block; font-size: 11px; font-weight: 700;
    border-radius: 4px; padding: 2px 8px; margin-right: 4px;
  }
  .warn-box {
    background: #1a1200; border: 1px solid #8a6200; border-radius: 8px;
    padding: 12px 16px; font-size: 12.5px; color: #ffd54f; margin-bottom: 16px;
  }
  .rr-good  { color: #69f0ae; }
  .rr-ok    { color: #ffd54f; }
  .rr-bad   { color: #ef5350; }
  .divider  { border-top: 1px solid #1a2a40; margin: 14px 0; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
#  Sidebar Nav
# ─────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 📊 波段 / 當沖")
    st.caption(f"NT$500,000 資本　目標 NT$50,000/月")
    st.divider()
    view = st.radio("", ["🏠 今日儀表板", "📈 波段掃描", "⚡ 當沖機會",
                          "💼 部位管理", "📋 歷史績效", "🧮 部位計算機"], label_visibility="collapsed")
    st.divider()
    _rcheck = daily_risk_check(CAPITAL)
    today_pnl = _rcheck["today_pnl"]
    pnl_col = "#ef5350" if today_pnl > 0 else ("#00c853" if today_pnl < 0 else "#aaa")
    st.markdown(
        f'<div style="font-size:12px;color:#888">今日 P&L<br>'
        f'<span style="font-size:20px;font-weight:700;color:{pnl_col}">'
        f'{"+" if today_pnl >= 0 else ""}NT${today_pnl:,}</span></div>',
        unsafe_allow_html=True
    )
    if _rcheck["daily_limit_hit"]:
        st.error("⛔ 今日虧損已達上限，停止交易")
    elif _rcheck["positions_full"]:
        st.warning(f"⚠️ 已達 {MAX_POSITIONS} 個部位上限")
    else:
        open_cnt = _rcheck["open_count"]
        st.success(f"✅ 可交易　{open_cnt}/{MAX_POSITIONS} 部位開放")
    st.caption(f"資金使用率 {_rcheck['capital_deployed_pct']:.0f}%")

# ─────────────────────────────────────────────────────────────────────────────
#  Data Loading (cached)
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=900, show_spinner=False)
def load_prices(epoch: str):
    tickers = list(TECH_UNIVERSE.keys())
    return fetch_prices_batch(tickers, period="6mo")

@st.cache_data(ttl=1800, show_spinner=False)
def load_taiex(epoch: str):
    return fetch_taiex_prices()

def _epoch() -> str:
    n = datetime.now(tz=TST)
    base = n.strftime("%Y-%m-%d")
    slot = "pm" if n.hour >= 14 else ("am" if n.hour >= 9 else "pre")
    return f"{base}_{slot}"

ep = _epoch()

with st.spinner("載入市場資料…"):
    prices  = load_prices(ep)
    taiex   = load_taiex(ep)
    mkt_dir = calc_market_direction(taiex)

# Data quality check — show banner if most tickers failed to load
_loaded_count = sum(1 for df in prices.values() if df is not None and len(df) >= 30)
_total_count  = len(prices)
if _loaded_count < _total_count * 0.5:
    st.error(f"⚠️ 資料載入異常：只有 {_loaded_count}/{_total_count} 檔有效。可能是 Yahoo Finance 限流，請稍後重新整理。")
elif _loaded_count < _total_count * 0.8:
    st.warning(f"⚠️ 部分資料缺失（{_loaded_count}/{_total_count} 檔）：掃描結果可能不完整。")

# ─────────────────────────────────────────────────────────────────────────────
#  Live Price Fetcher (TWSE public API, no auth required)
# ─────────────────────────────────────────────────────────────────────────────
def fetch_live_prices(tickers: list, daily_prices: dict = None) -> dict:
    """
    Near-real-time prices via yfinance 5-min intraday bars.
    daily_prices: the 6mo daily cache — used to compute change vs. yesterday's close.
    Returns {ticker: {price, change, change_pct, open, high, low, volume, time, name}}
    """
    import yfinance as yf
    results = {}
    daily_prices = daily_prices or {}

    chunk_size = 20
    for i in range(0, len(tickers), chunk_size):
        chunk = tickers[i:i+chunk_size]
        try:
            raw = yf.download(
                chunk, period="1d", interval="5m",
                progress=False, auto_adjust=True,
                group_by="ticker", threads=True,
            )
            for ticker in chunk:
                try:
                    df_t = raw[ticker] if len(chunk) > 1 else raw
                    if df_t is None or len(df_t) == 0:
                        continue
                    price      = float(df_t["Close"].iloc[-1])
                    open_price = float(df_t["Open"].iloc[0])
                    high_day   = float(df_t["High"].max())
                    low_day    = float(df_t["Low"].min())
                    vol_day    = int(df_t["Volume"].sum())
                    bar_time   = df_t.index[-1]
                    bar_time_s = bar_time.tz_convert(TST).strftime("%H:%M") if hasattr(bar_time, "tz_convert") else str(bar_time)[-8:-3]

                    # Prev close from daily cache (index -2 = yesterday)
                    d_df = daily_prices.get(ticker)
                    if d_df is not None and len(d_df) >= 2:
                        prev_close = float(d_df["Close"].iloc[-2])
                    else:
                        prev_close = open_price

                    change     = round(price - prev_close, 2)
                    change_pct = round(change / prev_close * 100, 2) if prev_close > 0 else 0

                    results[ticker] = {
                        "price":      price,
                        "prev_close": prev_close,
                        "change":     change,
                        "change_pct": change_pct,
                        "open":       open_price,
                        "high":       high_day,
                        "low":        low_day,
                        "volume":     vol_day,
                        "time":       bar_time_s,
                        "name":       TECH_UNIVERSE.get(ticker, {}).get("name", ticker.replace(".TW", "")),
                    }
                except Exception:
                    pass
        except Exception:
            pass

    return results


def _is_market_open() -> bool:
    n = datetime.now(tz=TST)
    if n.weekday() >= 5:
        return False
    open_t  = n.replace(hour=9,  minute=0,  second=0, microsecond=0)
    close_t = n.replace(hour=13, minute=30, second=0, microsecond=0)
    return open_t <= n <= close_t


@st.cache_data(ttl=30, show_spinner=False)
def _cached_live_prices(tickers_key: str, _tickers: list, _daily: dict) -> dict:
    """30-second cached wrapper around fetch_live_prices."""
    return fetch_live_prices(_tickers, daily_prices=_daily)


# ─────────────────────────────────────────────────────────────────────────────
#  VIEW: 今日儀表板
# ─────────────────────────────────────────────────────────────────────────────
if "儀表板" in view:
    st.markdown("## 🏠 今日儀表板")
    st.caption(f"{NOW.strftime('%Y-%m-%d %H:%M')} TST　大盤：{mkt_dir.get('label', '—')}")

    # ── 月目標進度 ───────────────────────────────────────────────────────────
    closed = get_closed_trades()
    month_key = NOW.strftime("%Y-%m")
    month_pnl = sum(t.get("pnl", 0) for t in closed
                    if t.get("closed_at", "")[:7] == month_key)
    progress_pct = min(100, max(0, month_pnl / 50_000 * 100))
    prog_col = "#69f0ae" if month_pnl >= 50_000 else ("#ffd54f" if month_pnl >= 25_000 else "#ef9a9a")

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(
            f'<div class="metric-card"><div class="metric-title">本月 P&L</div>'
            f'<div class="metric-val" style="color:{prog_col}">{"+" if month_pnl >= 0 else ""}NT${month_pnl:,}</div>'
            f'<div style="font-size:11px;color:#555;margin-top:4px">目標 NT$50,000 ({progress_pct:.0f}%)</div>'
            f'<div style="background:#1a2a40;border-radius:4px;height:6px;margin-top:6px">'
            f'<div style="background:{prog_col};width:{progress_pct:.0f}%;height:6px;border-radius:4px"></div>'
            f'</div></div>', unsafe_allow_html=True)
    with c2:
        open_t = get_open_trades()
        at_risk = sum(t.get("risk_nwd", 0) for t in open_t)
        st.markdown(
            f'<div class="metric-card"><div class="metric-title">開放部位</div>'
            f'<div class="metric-val">{len(open_t)}/{MAX_POSITIONS}</div>'
            f'<div style="font-size:11px;color:#888;margin-top:4px">風險敞口 NT${at_risk:,}</div>'
            f'</div>', unsafe_allow_html=True)
    with c3:
        stats = compute_stats(closed, CAPITAL)
        wr_col = "#69f0ae" if stats["win_rate"] >= 55 else ("#ffd54f" if stats["win_rate"] >= 45 else "#ef9a9a")
        st.markdown(
            f'<div class="metric-card"><div class="metric-title">歷史勝率</div>'
            f'<div class="metric-val" style="color:{wr_col}">{stats["win_rate"]:.0f}%</div>'
            f'<div style="font-size:11px;color:#888;margin-top:4px">{stats["total_trades"]} 次交易　獲利因子 {stats["profit_factor"]:.2f}</div>'
            f'</div>', unsafe_allow_html=True)
    with c4:
        dd_col = "#ef5350" if stats["max_drawdown_pct"] >= 12 else ("#ffd54f" if stats["max_drawdown_pct"] >= 6 else "#69f0ae")
        st.markdown(
            f'<div class="metric-card"><div class="metric-title">最大回撤</div>'
            f'<div class="metric-val" style="color:{dd_col}">-{stats["max_drawdown_pct"]:.1f}%</div>'
            f'<div style="font-size:11px;color:#888;margin-top:4px">日限 NT${DAILY_LOSS_LIMIT:,}　月限 NT${MONTHLY_LOSS_LIMIT:,}</div>'
            f'</div>', unsafe_allow_html=True)

    # ── 月目標真實機率（蒙地卡羅） ──────────────────────────────────────────
    st.divider()
    st.markdown("#### 📊 月目標機率模擬（蒙地卡羅 5,000次）")
    sim_col = st.columns([1, 2])
    with sim_col[0]:
        wr_input  = st.slider("你的預估勝率 %", 40, 75, 58)
        rr_input  = st.slider("平均 R:R（獲利/虧損）", 1.0, 3.0, 2.0, step=0.1)
        tr_input  = st.slider("每月交易次數", 6, 20, 12)
    with sim_col[1]:
        avg_win  = 0.04 * rr_input
        avg_loss = 0.04
        sim = simulate_monthly_return(
            capital=CAPITAL, trades_per_month=tr_input,
            win_rate=wr_input/100, avg_win_pct=avg_win,
            avg_loss_pct=avg_loss, position_pct=0.28
        )
        s1, s2, s3 = st.columns(3)
        s1.metric("悲觀 (P25)",  f"NT${sim['p25']:+,}")
        s2.metric("中位數",       f"NT${sim['p50_median']:+,}")
        s3.metric("樂觀 (P75)",  f"NT${sim['p75_bull']:+,}")
        target_prob = sim["prob_target"]
        loss_prob   = sim["prob_loss"]
        t_col = "#69f0ae" if target_prob >= 0.40 else ("#ffd54f" if target_prob >= 0.25 else "#ef9a9a")
        st.markdown(
            f'<div class="warn-box" style="background:#071a0f;border-color:#1a6030">'
            f'達成 NT$50,000 目標機率：<b style="color:{t_col};font-size:16px">{target_prob:.0%}</b>　'
            f'月虧損機率：<b style="color:#ef9a9a">{loss_prob:.0%}</b>　'
            f'最壞情境（P10）：NT${sim["p10_bear"]:+,}'
            f'</div>', unsafe_allow_html=True)

    # ── 開放部位快覽 ─────────────────────────────────────────────────────────
    open_t = get_open_trades()
    if open_t:
        st.divider()
        st.markdown("#### 💼 開放部位")
        for t in open_t:
            ticker = t["ticker"]
            df     = prices.get(ticker)
            live   = float(df["Close"].iloc[-1]) if df is not None and len(df) >= 1 else t["entry"]
            unreal = round((live - t["entry"]) * t["shares"])
            unreal_pct = round((live - t["entry"]) / t["entry"] * 100, 2)
            u_col  = "#ef5350" if unreal >= 0 else "#00c853"
            dist_stop_pct = round((live - t["stop"]) / live * 100, 1)
            st.markdown(
                f'<div class="setup-card">'
                f'<span style="font-weight:700;font-size:15px">{t["ticker"].replace(".TW","")} {t["name"]}</span>'
                f'<span class="badge" style="background:#1a2a40;color:#7eb3ff;margin-left:8px">{t.get("setup","")}</span>'
                f'<span class="badge" style="background:#1a3010;color:#69f0ae">{t["type"]}</span>'
                f'<div style="display:flex;gap:20px;margin-top:8px;font-size:12px;flex-wrap:wrap">'
                f'<span>進場 NT${t["entry"]:.1f}</span>'
                f'<span style="color:{u_col};font-weight:700">現值 NT${live:.1f}　{unreal_pct:+.2f}%　NT${unreal:+,}</span>'
                f'<span style="color:#ff7043">止損 NT${t["stop"]:.1f}（距 {dist_stop_pct:.1f}%）</span>'
                f'<span style="color:#69f0ae">目標 NT${t["target"]:.1f}</span>'
                f'<span style="color:#888">{t["shares"]:,}股　R:R {t["rr"]}</span>'
                f'</div>'
                f'</div>', unsafe_allow_html=True)

    # ── 風險警告 ──────────────────────────────────────────────────────────────
    st.markdown(
        '<div class="warn-box">'
        '⚠️ <b>風控提醒</b>：每筆最大虧損 NT$10,000（資本2%）。'
        '日虧損達 NT$20,000 立即停手。月虧損達 NT$75,000 全面檢討策略。'
        ' 當沖需開通「當沖帳戶」，稅率 0.3%（一般 0.15%）。'
        ' 本 App 為訊號工具，不保證獲利，請自行判斷風險。'
        '</div>', unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
#  VIEW: 波段掃描
# ─────────────────────────────────────────────────────────────────────────────
elif "波段掃描" in view:
    st.markdown("## 📈 波段交易掃描")
    st.caption("策略：Stage 2 突破 / 回測 MA20 / 布林壓縮 / KD 超賣反轉。持倉目標 3-15 日。")

    # Market filter
    mkt_status = mkt_dir.get("status", "neutral")
    if mkt_status == "bear":
        st.error(f"⛔ 大盤空頭（{mkt_dir.get('label','')}）——波段做多勝率大幅降低，建議暫停或只做半倉")
    elif mkt_status == "neutral":
        st.warning(f"⚠️ 大盤整理中（{mkt_dir.get('label','')}）——部位控制在 2 個以內")

    with st.spinner("掃描波段設置中…"):
        swings = scan_swing_setups(prices, capital=CAPITAL)

    if not swings:
        st.info("今日尚無符合條件的波段設置，等待更好的進場訊號。")
    else:
        st.success(f"找到 {len(swings)} 個波段機會")

        # Filter UI
        setup_filter = st.multiselect(
            "設置類型篩選",
            options=list(SWING_SETUP_TYPES.keys()),
            default=list(SWING_SETUP_TYPES.keys()),
            format_func=lambda k: SWING_SETUP_TYPES[k][0],
        )
        filtered = [s for s in swings if s["type"] in setup_filter]

        # ── 即時報價條 (auto-refresh every 2s, data cached 30s) ───────────────
        _setup_tickers  = [s["ticker"] for s in filtered[:8]]
        _entry_map      = {s["ticker"]: s["last"]  for s in filtered[:8]}
        _name_map       = {s["ticker"]: s["name"]  for s in filtered[:8]}
        _color_map      = {s["ticker"]: SWING_SETUP_TYPES.get(s["type"], ("", "#7eb3ff"))[1]
                           for s in filtered[:8]}

        @st.fragment(run_every=1)
        def _scan_live():
            now = datetime.now(tz=TST)
            ck  = ",".join(sorted(_setup_tickers)) + "_" + now.strftime("%Y%m%d%H%M") + str(now.second // 30)
            live = _cached_live_prices(ck, _setup_tickers, prices)

            # Outside hours: fall back to last daily close
            if not live:
                for t in _setup_tickers:
                    df = prices.get(t)
                    if df is not None and len(df) >= 2:
                        p  = float(df["Close"].iloc[-1])
                        pc = float(df["Close"].iloc[-2])
                        live[t] = {"price": p, "change": round(p-pc,2),
                                   "change_pct": round((p-pc)/pc*100,2) if pc else 0,
                                   "time": "收盤"}

            freshness = "🟢 即時" if _is_market_open() else "🔴 收盤價"
            st.markdown(
                f'<div style="font-size:11px;color:#556;margin-bottom:6px">'
                f'📡 {freshness}　{now.strftime("%H:%M:%S")} TST</div>',
                unsafe_allow_html=True)

            rows_of_4 = [_setup_tickers[i:i+4] for i in range(0, len(_setup_tickers), 4)]
            for row in rows_of_4:
                cols = st.columns(len(row))
                for i, ticker in enumerate(row):
                    d = live.get(ticker, {})
                    price    = d.get("price", 0)
                    chg      = d.get("change", 0)
                    chg_pct  = d.get("change_pct", 0)
                    bar_time = d.get("time", "—")
                    entry    = _entry_map.get(ticker, price)
                    dist     = round((price - entry) / entry * 100, 2) if entry > 0 and price > 0 else 0

                    p_col = "#ef5350" if chg >= 0 else "#00c853"
                    c_col = _color_map.get(ticker, "#7eb3ff")

                    if price == 0:
                        entry_badge = '<span style="color:#444">—</span>'
                    elif abs(dist) <= 0.5:
                        entry_badge = '<span style="background:#ffd54f22;color:#ffd54f;padding:1px 6px;border-radius:3px;font-size:10px">● 進場區</span>'
                    elif dist > 0.5:
                        entry_badge = f'<span style="color:#888;font-size:10px">距進場 +{dist:.1f}%</span>'
                    else:
                        entry_badge = f'<span style="color:#69f0ae;font-size:10px">低於建議 {dist:.1f}%</span>'

                    with cols[i]:
                        st.markdown(
                            f'<div style="background:#080f1e;border:1px solid {c_col}55;'
                            f'border-radius:8px;padding:10px 14px;margin-bottom:6px">'
                            f'<div style="font-size:11px;color:#666;margin-bottom:2px">'
                            f'{ticker.replace(".TW","")} {_name_map.get(ticker,"")}</div>'
                            f'<div style="font-size:26px;font-weight:800;color:{p_col};line-height:1.1">'
                            f'NT${price:.1f}</div>'
                            f'<div style="font-size:12px;color:{p_col};margin-top:2px">'
                            f'{chg:+.2f} ({chg_pct:+.2f}%)</div>'
                            f'<div style="margin-top:5px">{entry_badge}</div>'
                            f'<div style="font-size:10px;color:#333;margin-top:3px">{bar_time}</div>'
                            f'</div>',
                            unsafe_allow_html=True)

        _scan_live()
        st.divider()

        for s in filtered[:8]:
            setup_label, setup_color = SWING_SETUP_TYPES.get(s["type"], ("設置", "#aaa"))
            rr_cls = "rr-good" if s["rr"] >= 2.0 else ("rr-ok" if s["rr"] >= 1.5 else "rr-bad")
            sr     = s.get("sr", {})

            st.markdown(
                f'<div class="setup-card" style="border-left:4px solid {setup_color}">'
                # Header
                f'<div style="display:flex;justify-content:space-between;align-items:center">'
                f'<span style="font-size:17px;font-weight:800">'
                f'{s["ticker"].replace(".TW","")} {s["name"]}</span>'
                f'<span class="badge" style="background:{setup_color}22;color:{setup_color};border:1px solid {setup_color}">{setup_label}</span>'
                f'</div>'
                f'<div style="font-size:11px;color:#888;margin-bottom:8px">{s["sector"]}</div>'
                # Price row
                f'<div style="display:flex;gap:20px;flex-wrap:wrap;font-size:13px;margin-bottom:8px">'
                f'<span>現價 <b style="color:#f0f0f0">NT${s["last"]:.1f}</b></span>'
                f'<span>進場 <span class="signal-buy">NT${s["last"]:.1f}</span></span>'
                f'<span>止損 <span class="signal-sell">NT${s["stop"]:.1f}</span>'
                f'  <span style="color:#888;font-size:11px">({round((s["stop"]-s["last"])/s["last"]*100,1)}%)</span></span>'
                f'<span>目標 <span style="color:#69f0ae">NT${s["target"]:.1f}</span>'
                f'  <span style="color:#888;font-size:11px">(+{round((s["target"]-s["last"])/s["last"]*100,1)}%)</span></span>'
                f'<span class="{rr_cls}">R:R 1:{s["rr"]}</span>'
                f'</div>'
                # Position sizing
                f'<div style="background:#0a1020;border-radius:6px;padding:8px 12px;font-size:12px;margin-bottom:8px">'
                f'🧮 建議部位：<b>{s["shares"]:,} 股</b>　'
                f'投入 NT${s["notional"]:,}　'
                f'最大風險 <span style="color:#ef9a9a">NT${s["risk_nwd"]:,}</span>'
                f'（資本 {s["risk_nwd"]/CAPITAL*100:.1f}%）'
                f'</div>'
                # Reasons
                f'<div style="font-size:12px;color:#aaa;margin-bottom:6px">'
                + "　".join(f'<span style="color:#7eb3ff">▸</span> {r}' for r in s.get("reasons", []))
                + f'</div>'
                # S/R
                f'<div style="font-size:11px;color:#555">'
                f'支撐 S1={sr.get("S1","—")} S2={sr.get("S2","—")}　'
                f'壓力 R1={sr.get("R1","—")} R2={sr.get("R2","—")}　'
                f'Fib 61.8%={sr.get("fib_618","—")}'
                f'</div>'
                f'</div>',
                unsafe_allow_html=True
            )
            # Quick open trade button
            with st.expander(f"📝 開倉 {s['ticker'].replace('.TW','')}（點擊展開）", expanded=False):
                _e = st.number_input("實際進場價", value=s["last"], step=0.1, key=f"e_{s['ticker']}")
                _s = st.number_input("止損價", value=s["stop"], step=0.1, key=f"s_{s['ticker']}")
                _t = st.number_input("目標價", value=s["target"], step=0.1, key=f"t_{s['ticker']}")
                _pos = calc_position_size(_e, _s, CAPITAL)
                st.caption(f"建議 {_pos['shares']:,} 股 ({_pos['lots']} 張)　投入 NT${_pos['notional']:,}　風險 NT${_pos['risk_nwd']:,}")
                _note = st.text_input("備注", key=f"n_{s['ticker']}")
                if st.button(f"✅ 開倉 {s['ticker'].replace('.TW','')}", key=f"open_{s['ticker']}"):
                    if not get_open_trades().__len__() >= MAX_POSITIONS:
                        trade = open_trade(
                            s["ticker"], s["name"], _e, _s, _t,
                            _pos["shares"], "swing", s["type"], _note
                        )
                        st.success(f"已開倉 {s['name']}　NT${_e} × {_pos['shares']:,} 股")
                        st.rerun()
                    else:
                        st.error(f"已達 {MAX_POSITIONS} 個部位上限，請先平倉後再開新倉")


# ─────────────────────────────────────────────────────────────────────────────
#  VIEW: 當沖機會
# ─────────────────────────────────────────────────────────────────────────────
elif "當沖" in view:
    st.markdown("## ⚡ 當沖機會掃描")
    st.caption("基於前日收盤 + 今日開盤跳空識別。當沖需開通券商當沖帳戶；稅率 0.3%（非 0.15%）。")

    st.markdown(
        '<div class="warn-box">'
        '📋 <b>台灣當沖規則提醒</b>：<br>'
        '① 須向券商申請開通「當日沖銷」帳戶<br>'
        '② 當沖交易稅 0.3%（是一般股票 0.15% 的 2 倍）<br>'
        '③ 同日買進賣出自動抵扣，若未賣出需 T+2 交割<br>'
        '④ 每筆最大風險建議 1.5%（NT$7,500）而非 2%，因當沖標的波動更大'
        '</div>', unsafe_allow_html=True)

    with st.spinner("掃描當沖機會…"):
        dayts = scan_daytrade_setups(prices, capital=CAPITAL)

    if not dayts:
        st.info("今日尚無顯著跳空或當沖訊號。可等開盤後前30分鐘再確認。")
    else:
        st.success(f"找到 {len(dayts)} 個潛在當沖標的（需開盤後確認量能）")

    for d in dayts[:6]:
        setup_label, setup_color = SWING_SETUP_TYPES.get(d["type"], ("當沖", "#ff9800"))
        gap_col = "#ef5350" if d["gap_pct"] > 0 else "#00c853"
        rr_cls  = "rr-good" if d["rr"] >= 2.0 else ("rr-ok" if d["rr"] >= 1.5 else "rr-bad")
        st.markdown(
            f'<div class="setup-card" style="border-left:4px solid {setup_color}">'
            f'<div style="display:flex;justify-content:space-between">'
            f'<span style="font-size:17px;font-weight:800">{d["ticker"].replace(".TW","")} {d["name"]}</span>'
            f'<span class="badge" style="background:{setup_color}22;color:{setup_color};border:1px solid {setup_color}">{setup_label}</span>'
            f'</div>'
            f'<div style="font-size:11px;color:#888;margin-bottom:8px">{d["sector"]}</div>'
            f'<div style="display:flex;gap:16px;flex-wrap:wrap;font-size:13px;margin-bottom:8px">'
            f'<span>昨收→今開 <b style="color:{gap_col}">{d["gap_pct"]:+.1f}%</b></span>'
            f'<span>現價 NT${d["last"]:.1f}</span>'
            f'<span style="color:#ff7043">止損 NT${d["stop"]:.1f}</span>'
            f'<span style="color:#69f0ae">目標 NT${d["target"]:.1f}</span>'
            f'<span class="{rr_cls}">R:R 1:{d["rr"]}</span>'
            f'<span style="color:#ffd54f">量比 {d["vr"]:.1f}x</span>'
            f'</div>'
            f'<div style="background:#0a1020;border-radius:6px;padding:8px 12px;font-size:12px;margin-bottom:8px">'
            f'🎯 操作指引：{d.get("strategy", "")}'
            f'</div>'
            f'<div style="background:#0a1020;border-radius:6px;padding:8px 12px;font-size:12px">'
            f'🧮 當沖部位：<b>{d["shares"]:,} 股</b>　'
            f'投入 NT${d["notional"]:,}　'
            f'最大風險 <span style="color:#ef9a9a">NT${d["risk_nwd"]:,}</span>'
            f'<br><span style="color:#888;font-size:11px">'
            f'⚠️ 當沖稅成本：NT${round(d["notional"]*0.003)}'
            f'（含來回券商手續費約 NT${round(d["notional"]*0.00285+d["notional"]*0.003)}）</span>'
            f'</div>'
            f'</div>',
            unsafe_allow_html=True
        )


# ─────────────────────────────────────────────────────────────────────────────
#  VIEW: 部位管理
# ─────────────────────────────────────────────────────────────────────────────
elif "部位管理" in view:
    st.markdown("## 💼 部位管理")

    open_t = get_open_trades()
    if not open_t:
        st.info("目前無開放部位。至「波段掃描」開倉。")
    else:
        for t in open_t:
            df   = prices.get(t["ticker"])
            live = float(df["Close"].iloc[-1]) if df is not None and len(df) else t["entry"]
            unreal = round((live - t["entry"]) * t["shares"])
            unreal_pct = round((live - t["entry"]) / t["entry"] * 100, 2)
            u_col = "#ef5350" if unreal >= 0 else "#00c853"
            dist_stop = round((live - t["stop"]) / live * 100, 1)
            dist_tgt  = round((t["target"] - live) / live * 100, 1)

            with st.expander(
                f"{t['ticker'].replace('.TW','')} {t['name']}　"
                f"{'↑' if unreal >= 0 else '↓'} NT${abs(unreal):,} ({unreal_pct:+.2f}%)",
                expanded=True
            ):
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("進場價",   f"NT${t['entry']:.1f}")
                col2.metric("現值",     f"NT${live:.1f}", f"{unreal_pct:+.2f}%")
                col3.metric("止損",     f"NT${t['stop']:.1f}", f"距 {dist_stop:.1f}%")
                col4.metric("目標",     f"NT${t['target']:.1f}", f"還差 {dist_tgt:.1f}%")

                st.caption(f"持倉：{t['shares']:,} 股　投入：NT${t['notional']:,}　風險：NT${t['risk_nwd']:,}　R:R {t['rr']}")

                sc1, sc2 = st.columns(2)
                with sc1:
                    new_stop = st.number_input("上移止損（追蹤止損）", value=t["stop"],
                                               step=0.1, key=f"ts_{t['id']}")
                    if st.button("更新止損", key=f"upd_{t['id']}"):
                        if new_stop > t["stop"]:
                            update_stop(t["id"], new_stop)
                            st.success("止損已上移")
                            st.rerun()
                        else:
                            st.warning("新止損必須高於現有止損")
                with sc2:
                    exit_p = st.number_input("平倉價格", value=live, step=0.1, key=f"ex_{t['id']}")
                    exit_n = st.text_input("平倉備注（停利/停損/其他）", key=f"en_{t['id']}")
                    if st.button("✅ 平倉", key=f"close_{t['id']}", type="primary"):
                        ct = close_trade(t["id"], exit_p, exit_n)
                        if ct:
                            pnl_s = f"+NT${ct['pnl']:,}" if ct['pnl'] >= 0 else f"NT${ct['pnl']:,}"
                            st.success(f"已平倉　{pnl_s}（{ct['pnl_pct']:+.2f}%）")
                            st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
#  VIEW: 歷史績效
# ─────────────────────────────────────────────────────────────────────────────
elif "歷史績效" in view:
    st.markdown("## 📋 歷史績效")

    closed = get_closed_trades()
    stats  = compute_stats(closed, CAPITAL)

    if not closed:
        st.info("尚無歷史交易紀錄。開始交易後績效會顯示在這裡。")
    else:
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("總交易次數", stats["total_trades"])
        c2.metric("勝率",       f"{stats['win_rate']:.1f}%",
                  f"{stats['wins']}勝 {stats['losses']}負")
        c3.metric("獲利因子",   stats["profit_factor"])
        c4.metric("最大回撤",   f"-{stats['max_drawdown_pct']:.1f}%")
        c5.metric("平均持倉",   f"{stats['avg_hold_days']} 天")

        st.divider()
        c1b, c2b = st.columns(2)
        c1b.metric("平均獲利",  f"NT${stats['avg_win']:,}")
        c2b.metric("平均虧損",  f"NT${stats['avg_loss']:,}")

        # Monthly P&L bar chart
        if stats["monthly_pnl"]:
            st.divider()
            st.markdown("#### 每月 P&L")
            df_m = pd.DataFrame([
                {"月份": k, "P&L": v} for k, v in stats["monthly_pnl"].items()
            ])
            st.bar_chart(df_m.set_index("月份")["P&L"])

        # Trade log table
        st.divider()
        st.markdown("#### 交易紀錄")
        rows = []
        for t in sorted(closed, key=lambda x: x.get("closed_at", ""), reverse=True):
            rows.append({
                "日期":     t.get("closed_at", "")[:10],
                "代號":     t.get("ticker", "").replace(".TW", ""),
                "名稱":     t.get("name", ""),
                "進場":     t.get("entry", 0),
                "出場":     t.get("exit_price", 0),
                "股數":     t.get("shares", 0),
                "P&L":      t.get("pnl", 0),
                "獲利%":    t.get("pnl_pct", 0),
                "結果":     "✅ 獲利" if t.get("outcome") == "win" else "❌ 虧損",
                "類型":     t.get("type", ""),
                "設置":     t.get("setup", ""),
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# ─────────────────────────────────────────────────────────────────────────────
#  VIEW: 部位計算機
# ─────────────────────────────────────────────────────────────────────────────
elif "計算機" in view:
    st.markdown("## 🧮 部位計算機")
    st.caption("輸入進場/止損/目標價，即時計算最佳部位大小與風險")

    pc1, pc2 = st.columns(2)
    with pc1:
        cap_input   = st.number_input("總資本 NT$", value=CAPITAL, step=10_000, format="%d")
        risk_pct_in = st.slider("每筆風險 %（建議 1.5-2%）", 0.5, 5.0, 2.0, step=0.1)
        entry_in    = st.number_input("進場價 NT$", value=100.0, step=0.5)
        stop_in     = st.number_input("止損價 NT$", value=96.0,  step=0.5)
        target_in   = st.number_input("目標價 NT$", value=110.0, step=0.5)

    with pc2:
        pos = calc_position_size(entry_in, stop_in, int(cap_input), risk_pct_in/100)
        tgt = calc_target_prices(entry_in, stop_in)
        rr  = round((target_in - entry_in) / (entry_in - stop_in), 2) if (entry_in - stop_in) > 0 else 0
        rr_col = "#69f0ae" if rr >= 2.0 else ("#ffd54f" if rr >= 1.5 else "#ef5350")

        st.markdown(
            f'<div class="metric-card">'
            f'<div class="metric-title">建議股數</div>'
            f'<div class="metric-val">{pos["shares"]:,} 股　({pos["lots"]} 張)</div>'
            f'<div style="margin-top:12px;font-size:13px">'
            f'<div>💰 投入金額：<b>NT${pos["notional"]:,}</b>'
            f'（占資本 {pos["notional"]/cap_input*100:.1f}%）</div>'
            f'<div style="color:#ef9a9a">⚠️ 最大風險：NT${pos["risk_nwd"]:,}'
            f'（{pos["risk_nwd"]/cap_input*100:.1f}%）</div>'
            f'<div style="color:{rr_col}">📊 R:R = 1:{rr}</div>'
            f'</div>'
            f'<div class="divider"></div>'
            f'<div style="font-size:12px;color:#aaa">'
            f'目標 R:R 1.5 → NT${tgt["target_rr1_5"]}&nbsp;&nbsp;'
            f'R:R 2.0 → NT${tgt["target_rr2_0"]}&nbsp;&nbsp;'
            f'R:R 3.0 → NT${tgt["target_rr3_0"]}'
            f'</div>'
            f'</div>', unsafe_allow_html=True)

        st.markdown(
            f'<div class="warn-box" style="margin-top:16px">'
            f'每筆風險原則：<br>'
            f'• NT$500,000 × 2% = <b>NT$10,000</b> 最大每筆虧損<br>'
            f'• 日虧損限 NT$20,000 → 當日停手<br>'
            f'• 月虧損限 NT$75,000 → 全面策略檢討<br>'
            f'• 同時持有最多 {MAX_POSITIONS} 個部位<br>'
            f'• 當沖每筆建議風險降至 1.5%（NT$7,500）'
            f'</div>', unsafe_allow_html=True)

        # Break-even analysis
        st.divider()
        st.markdown("#### 損益平衡分析")
        be_data = []
        for wr in [0.45, 0.50, 0.55, 0.60, 0.65]:
            for rr_v in [1.5, 2.0, 2.5, 3.0]:
                monthly = 12 * cap_input * 0.28 * (wr * rr_v * 0.04 - (1 - wr) * 0.04)
                be_data.append({"勝率": f"{wr:.0%}", f"R:R {rr_v}": int(monthly)})
        # Build pivot table
        df_be = pd.DataFrame(be_data).groupby("勝率").first().reset_index()
        st.caption("月 P&L 估算（12 次交易 × NT$140,000 部位）")
        st.dataframe(df_be, use_container_width=True, hide_index=True)
