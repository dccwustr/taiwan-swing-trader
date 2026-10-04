#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
波段 & 當沖掃描引擎
Scanner for swing trades (3-15 day hold) and day trades (當沖).
Imports technical indicators from the existing taiwan_stock_widget/widget.py.
"""
import sys, os
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings("ignore")

# ── Reuse indicators from the existing app ──────────────────────────────────
_WIDGET_PATH = os.path.expanduser("~/taiwan_stock_widget")
if _WIDGET_PATH not in sys.path:
    sys.path.insert(0, _WIDGET_PATH)

from widget import (
    calc_rsi, calc_macd, calc_atr, calc_bollinger, calc_stochastic,
    calc_ma_alignment, calc_kbar_pattern, calc_obv_trend,
    calc_52w_position, detect_52w_breakout, volume_ratio,
    calc_support_resistance, calc_trading_signal, calc_strategy_stats,
    TECH_UNIVERSE,
    fetch_prices_batch, fetch_taiex_prices, fetch_cnyes_news,
    analyze_catalysts, fetch_twse_foreign_buying,
    fetch_twse_foreign_multi_day, calc_foreign_streak,
)

TST = timezone(timedelta(hours=8))

# ─────────────────────────────────────────────────────────────────────────────
#  SWING TRADE SETUPS
# ─────────────────────────────────────────────────────────────────────────────

SWING_SETUP_TYPES = {
    "breakout":  ("📈 突破建倉", "#ef5350"),
    "pullback":  ("🔄 回測買點", "#ffd54f"),
    "squeeze":   ("💥 帶寬壓縮爆發", "#69f0ae"),
    "kd_reversal": ("🔔 KD超賣反轉", "#90caf9"),
    "daytrade_gap": ("⚡ 當沖缺口", "#ff9800"),
    "daytrade_orb": ("🎯 當沖 ORB", "#ce93d8"),
}


def _swing_score(setup: dict) -> int:
    """Composite score for ranking setups (higher = better)."""
    s = 0
    s += min(30, setup.get("vol_ratio", 1.0) * 10)
    s += setup.get("rsi_score", 0)
    s += setup.get("macd_score", 0)
    s += setup.get("ma_score", 0)
    s += setup.get("breakout_score", 0)
    s += setup.get("kd_score", 0)
    return int(s)


def _calc_position_info(last: float, stop: float, target: float, capital: int = 500_000,
                         risk_pct: float = 0.02) -> dict:
    """
    Position sizing based on 2% capital risk per trade.
    risk_pct=0.02 → max NT$10,000 loss per trade on NT$500,000 capital.
    """
    max_risk_nwd = capital * risk_pct        # NT$10,000
    risk_per_share = last - stop
    if risk_per_share <= 0 or last <= 0:
        return {"shares": 0, "notional": 0, "risk_nwd": 0, "rr": 0, "shares_1k": 0}

    shares = int(max_risk_nwd / risk_per_share)
    # Cap at 30% of capital per position
    max_notional = int(capital * 0.30)
    shares = min(shares, int(max_notional / last))
    shares = max(shares, 1)

    # Round to nearest 1,000 for full lots; keep raw for 零股 reference too
    shares_1k = max(1000, (shares // 1000) * 1000)
    notional = round(shares * last)
    reward   = target - last
    rr       = round(reward / risk_per_share, 2) if risk_per_share > 0 else 0
    actual_risk = round(risk_per_share * shares)

    return {
        "shares":    shares,
        "shares_1k": shares_1k,
        "notional":  notional,
        "risk_nwd":  actual_risk,
        "rr":        rr,
    }


def scan_swing_setups(prices: Dict[str, pd.DataFrame],
                      cat_scores: dict = None,
                      capital: int = 500_000) -> List[dict]:
    """
    Scan TECH_UNIVERSE for swing trade setups.
    Returns list of setup dicts sorted by composite score desc.
    """
    cat_scores = cat_scores or {}
    setups = []

    for ticker, df in prices.items():
        if df is None or len(df) < 30:
            continue
        close  = df["Close"]
        last   = float(close.iloc[-1])
        if last <= 0:
            continue

        # ── Core indicators ──────────────────────────────────────────────
        rsi          = calc_rsi(close)
        macd_h, mprev = calc_macd(close)
        atr          = calc_atr(df)
        vr           = volume_ratio(df["Volume"], 20)
        ma_info      = calc_ma_alignment(close)
        bb           = calc_bollinger(close)
        kd           = calc_stochastic(df)
        obv          = calc_obv_trend(df)
        bo           = detect_52w_breakout(df)
        kbar_s, kbar = calc_kbar_pattern(df)
        sr           = calc_support_resistance(df)
        ma5          = ma_info["ma5"]
        ma20         = ma_info["ma20"]
        ma60         = ma_info["ma60"]
        stage        = ma_info["stage"]
        kd_sig       = kd.get("signal", "neutral")
        bb_sig       = bb.get("signal", "neutral")

        # ── Setup 1: 52-週突破建倉 ──────────────────────────────────────
        if bo["type"] in ("confirmed", "near") and vr >= 1.5 and rsi < 72 and stage == 2:
            stop   = round(max(last * 0.96, ma20 * 0.99, last - 2 * atr), 1)
            target = round(min(last * 1.12, last + 3 * atr), 1)
            pos    = _calc_position_info(last, stop, target, capital)
            if pos["rr"] >= 1.5:
                setups.append({
                    "ticker": ticker, "type": "breakout",
                    "last": last, "stop": stop, "target": target,
                    "rsi": round(rsi, 1), "vr": round(vr, 2),
                    "stage": stage, "kbar": kbar,
                    "sr": sr, "atr": round(atr, 2),
                    "rr": pos["rr"], "shares": pos["shares_1k"],
                    "notional": pos["notional"], "risk_nwd": pos["risk_nwd"],
                    "reasons": [f"52週突破({'確認' if bo['type']=='confirmed' else '接近'})",
                                f"量比 {vr:.1f}x", f"Stage 2 多頭排列"],
                    "vol_ratio": vr, "rsi_score": 8 if 45 <= rsi <= 65 else 4,
                    "macd_score": 9 if macd_h > 0 and macd_h > mprev else 0,
                    "ma_score": ma_info["bonus"],
                    "breakout_score": bo["score"],
                    "kd_score": 6 if kd_sig == "golden_cross_oversold" else 3,
                })

        # ── Setup 2: Stage 2 回測 MA20 買點 ────────────────────────────
        if (stage == 2 and 38 <= rsi <= 58 and
                abs(last - ma20) / ma20 < 0.03 and
                macd_h > 0 and vr >= 0.8):
            stop   = round(max(last * 0.96, ma60 * 0.98, last - 1.5 * atr), 1)
            target = round(last * 1.10, 1)
            pos    = _calc_position_info(last, stop, target, capital)
            if pos["rr"] >= 1.8:
                setups.append({
                    "ticker": ticker, "type": "pullback",
                    "last": last, "stop": stop, "target": target,
                    "rsi": round(rsi, 1), "vr": round(vr, 2),
                    "stage": stage, "kbar": kbar,
                    "sr": sr, "atr": round(atr, 2),
                    "rr": pos["rr"], "shares": pos["shares_1k"],
                    "notional": pos["notional"], "risk_nwd": pos["risk_nwd"],
                    "reasons": [f"Stage 2 回測 MA20（NT${ma20}）",
                                f"RSI {rsi:.0f} 冷卻至甜蜜區",
                                f"MACD 正柱{'放大' if macd_h > mprev else '持平'}"],
                    "vol_ratio": vr, "rsi_score": 8,
                    "macd_score": 7 if macd_h > mprev else 4,
                    "ma_score": ma_info["bonus"],
                    "breakout_score": 0,
                    "kd_score": 4 if kd_sig in ("golden_cross", "oversold") else 0,
                })

        # ── Setup 3: 布林帶壓縮爆發 (VCP-like) ─────────────────────────
        if (bb.get("squeeze") and bb_sig in ("breakout", "buy_zone") and
                vr >= 1.3 and macd_h > 0 and stage in (1, 2)):
            stop   = round(max(bb.get("lower", last * 0.96), last - 2 * atr), 1)
            target = round(bb.get("upper", last * 1.06) * 1.02, 1)
            pos    = _calc_position_info(last, stop, target, capital)
            if pos["rr"] >= 1.5:
                setups.append({
                    "ticker": ticker, "type": "squeeze",
                    "last": last, "stop": stop, "target": target,
                    "rsi": round(rsi, 1), "vr": round(vr, 2),
                    "stage": stage, "kbar": kbar,
                    "sr": sr, "atr": round(atr, 2),
                    "rr": pos["rr"], "shares": pos["shares_1k"],
                    "notional": pos["notional"], "risk_nwd": pos["risk_nwd"],
                    "reasons": ["布林帶壓縮 → 即將爆發",
                                f"量比 {vr:.1f}x 放大確認",
                                f"MACD 柱線轉正"],
                    "vol_ratio": vr, "rsi_score": 6,
                    "macd_score": 8 if macd_h > mprev else 4,
                    "ma_score": ma_info["bonus"],
                    "breakout_score": 5,
                    "kd_score": 4 if kd_sig in ("golden_cross", "golden_cross_oversold") else 0,
                })

        # ── Setup 4: KD 超賣黃金交叉反轉 ───────────────────────────────
        if (kd_sig == "golden_cross_oversold" and
                kd.get("K", 50) < 30 and rsi < 42 and
                stage in (1, 2) and kbar_s >= 5):
            stop   = round(last - 2 * atr, 1)
            target = round(min(last * 1.08, ma60 * 0.99), 1)
            pos    = _calc_position_info(last, stop, target, capital)
            if pos["rr"] >= 1.5:
                setups.append({
                    "ticker": ticker, "type": "kd_reversal",
                    "last": last, "stop": stop, "target": target,
                    "rsi": round(rsi, 1), "vr": round(vr, 2),
                    "stage": stage, "kbar": kbar,
                    "sr": sr, "atr": round(atr, 2),
                    "rr": pos["rr"], "shares": pos["shares_1k"],
                    "notional": pos["notional"], "risk_nwd": pos["risk_nwd"],
                    "reasons": [f"KD 超賣黃金交叉（K={kd.get('K',0):.0f}）",
                                f"RSI {rsi:.0f} 超賣",
                                f"K棒：{kbar}"],
                    "vol_ratio": vr, "rsi_score": 8,
                    "macd_score": 3 if macd_h > mprev else 0,
                    "ma_score": ma_info["bonus"],
                    "breakout_score": 0,
                    "kd_score": 10,
                })

    # Score and sort
    for s in setups:
        s["setup_score"] = _swing_score(s)
        s["name"] = TECH_UNIVERSE.get(s["ticker"], {}).get("name", s["ticker"].replace(".TW", ""))
        s["sector"] = TECH_UNIVERSE.get(s["ticker"], {}).get("sector", "")

    setups.sort(key=lambda x: x["setup_score"], reverse=True)
    return setups


# ─────────────────────────────────────────────────────────────────────────────
#  DAY TRADE (當沖) SETUPS
# ─────────────────────────────────────────────────────────────────────────────

def scan_daytrade_setups(prices: Dict[str, pd.DataFrame],
                         capital: int = 500_000) -> List[dict]:
    """
    當沖機會掃描：
    1. Gap & Go — 開盤跳空 > 2% + 量放大，追多
    2. Gap Reversal — 跳空低開後回彈（強支撐接力）
    台灣當沖注意：需開通當沖帳戶；稅率 0.3%（vs 一般 0.15%）
    """
    daytrades = []

    for ticker, df in prices.items():
        if df is None or len(df) < 10:
            continue
        close  = df["Close"]
        last   = float(close.iloc[-1])
        prev   = float(close.iloc[-2])
        if last <= 0 or prev <= 0:
            continue

        gap_pct = (last - prev) / prev * 100
        atr     = calc_atr(df)
        vr      = volume_ratio(df["Volume"], 20)
        rsi     = calc_rsi(close)
        ma20    = float(close.rolling(20).mean().iloc[-1])
        sr      = calc_support_resistance(df)
        r1      = sr.get("R1", last * 1.02)
        s1      = sr.get("S1", last * 0.98)
        kbar_s, kbar = calc_kbar_pattern(df)

        # ── Gap & Go: 跳空漲開 ──────────────────────────────────────────
        if (gap_pct >= 2.5 and vr >= 2.0 and rsi < 72 and
                last > ma20 and kbar_s >= 2):
            # Target: R1 or +5%, whichever is closer
            target = round(min(r1, last * 1.055), 1)
            stop   = round(max(last * 0.985, last - 0.8 * atr), 1)
            risk   = last - stop
            reward = target - last
            rr     = round(reward / risk, 2) if risk > 0 else 0
            if rr >= 1.5 and risk > 0:
                # Day trade position: 40% of capital max
                max_pos = int(capital * 0.40)
                shares  = min(int((capital * 0.02) / risk), int(max_pos / last))
                shares  = max(1000, (shares // 1000) * 1000)
                daytrades.append({
                    "ticker":   ticker,
                    "type":     "daytrade_gap",
                    "last":     last,
                    "stop":     stop,
                    "target":   target,
                    "rsi":      round(rsi, 1),
                    "vr":       round(vr, 2),
                    "gap_pct":  round(gap_pct, 2),
                    "rr":       rr,
                    "shares":   shares,
                    "notional": round(shares * last),
                    "risk_nwd": round(risk * shares),
                    "sr":       sr, "atr": round(atr, 2),
                    "reasons":  [f"跳空 +{gap_pct:.1f}%（前日收 NT${prev:.1f}）",
                                 f"量比 {vr:.1f}x 量能確認",
                                 f"日標 R1 NT${r1}"],
                    "strategy": "開盤確認站上 VWAP 後追多，目標 R1；若5分K收跌回缺口價立即止損",
                    "name":   TECH_UNIVERSE.get(ticker, {}).get("name", ticker.replace(".TW", "")),
                    "sector": TECH_UNIVERSE.get(ticker, {}).get("sector", ""),
                    "setup_score": int(vr * 8 + gap_pct * 3 + (8 if rsi < 65 else 2)),
                })

        # ── Gap Reversal: 跳空低開後反彈 ──────────────────────────────
        elif (gap_pct <= -2.5 and vr >= 1.8 and rsi < 35 and
              last >= s1 * 0.98 and kbar_s >= 5):
            target = round(min(last * 1.04, float(close.rolling(5).mean().iloc[-1])), 1)
            stop   = round(last - 0.6 * atr, 1)
            risk   = last - stop
            reward = target - last
            rr     = round(reward / risk, 2) if risk > 0 else 0
            if rr >= 1.5 and risk > 0:
                max_pos = int(capital * 0.30)
                shares  = min(int((capital * 0.015) / risk), int(max_pos / last))
                shares  = max(1000, (shares // 1000) * 1000)
                daytrades.append({
                    "ticker":   ticker,
                    "type":     "daytrade_gap",
                    "last":     last,
                    "stop":     stop,
                    "target":   target,
                    "rsi":      round(rsi, 1),
                    "vr":       round(vr, 2),
                    "gap_pct":  round(gap_pct, 2),
                    "rr":       rr,
                    "shares":   shares,
                    "notional": round(shares * last),
                    "risk_nwd": round(risk * shares),
                    "sr":       sr, "atr": round(atr, 2),
                    "reasons":  [f"跳空低開 {gap_pct:.1f}% 後在 S1 NT${s1} 止穩",
                                 f"RSI {rsi:.0f} 超賣 + 強K棒：{kbar}",
                                 f"反彈目標 MA5"],
                    "strategy": "等開盤15分K站上S1且收紅K才進場；目標回填缺口MA5；嚴格1%止損",
                    "name":   TECH_UNIVERSE.get(ticker, {}).get("name", ticker.replace(".TW", "")),
                    "sector": TECH_UNIVERSE.get(ticker, {}).get("sector", ""),
                    "setup_score": int(vr * 7 + abs(gap_pct) * 2 + (kbar_s * 3)),
                })

    daytrades.sort(key=lambda x: x["setup_score"], reverse=True)
    return daytrades


# ─────────────────────────────────────────────────────────────────────────────
#  MONTHLY RETURN SIMULATOR
# ─────────────────────────────────────────────────────────────────────────────

def simulate_monthly_return(capital: int = 500_000,
                             trades_per_month: int = 12,
                             win_rate: float = 0.58,
                             avg_win_pct: float = 0.08,
                             avg_loss_pct: float = 0.04,
                             position_pct: float = 0.28) -> dict:
    """
    Monte Carlo estimate of monthly P&L distribution.
    Returns expected, p25 (bear), p75 (bull) scenarios.
    """
    np.random.seed(42)
    position_size = capital * position_pct
    n_sim = 5000

    monthly_pnls = []
    for _ in range(n_sim):
        pnl = 0.0
        for _ in range(trades_per_month):
            win = np.random.random() < win_rate
            ret = (avg_win_pct if win else -avg_loss_pct)
            ret += np.random.normal(0, 0.02)   # ±2% noise
            pnl += position_size * ret
        # Transaction costs: 0.285% per round trip × trades
        costs = trades_per_month * position_size * 0.00285
        monthly_pnls.append(pnl - costs)

    arr = np.array(monthly_pnls)
    return {
        "expected":   int(np.mean(arr)),
        "p10_bear":   int(np.percentile(arr, 10)),
        "p25":        int(np.percentile(arr, 25)),
        "p50_median": int(np.median(arr)),
        "p75_bull":   int(np.percentile(arr, 75)),
        "p90":        int(np.percentile(arr, 90)),
        "prob_target":float(np.mean(arr >= 50_000)),
        "prob_loss":  float(np.mean(arr < 0)),
        "max_loss":   int(np.min(arr)),
    }
