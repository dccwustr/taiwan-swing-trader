#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交易前檢查（台股、波段）：勝算模擬、歷史回放、風險檢查、部位計算。
部位用風險法：股數 = 單筆可承受虧損 ÷ 每股到停損的虧損，再受單一個股資金上限約束（2026-11-10 取消 NT$10,000 上限）。

概念參考 Trader skill v2（github.com/Jakeschincariol/day-trader-skill，MIT），
程式為台股日 K 重寫：不含當沖、不會下單。結果只供顯示，不影響任何選股分數。
taiwan_swing_trader/trade_check.py 是這份的複本，修改時兩邊同步。
"""
from typing import Optional

import numpy as np

FEE_RATE = 0.001425     # 券商牌告手續費，買賣各一次（未計折扣與最低手續費）
TAX_RATE = 0.003        # 一般股票賣出證交稅（ETF 為 0.1%，這裡保守用 0.3%）
LIMIT_PCT = 0.10        # 單日漲跌停
MIN_BARS = 40           # 少於這個天數不模擬，樣本太少
HORIZON_DAYS = 20       # 持有上限（交易日）
DEFAULT_CAPITAL = 500_000     # 總資本（與波段 App risk.py 一致）
DEFAULT_RISK_PCT = 0.02       # 每筆最多虧總資本 2%
DEFAULT_MAX_POS_PCT = 0.30    # 單一個股最多 30% 資本
DEFAULT_BUDGET = int(DEFAULT_CAPITAL * DEFAULT_MAX_POS_PCT)    # NT$150,000 單檔上限
DEFAULT_MAX_LOSS = int(DEFAULT_CAPITAL * DEFAULT_RISK_PCT)     # NT$10,000 單筆最大虧損
MIN_NET_RR = 1.0        # 扣成本後報酬風險比低於此值 → BLOCK
GOOD_NET_RR = 1.5


def _net_r(exit_price, entry: float, stop: float):
    """扣手續費與證交稅後的損益，以「每股風險」為單位。"""
    pnl = exit_price * (1 - FEE_RATE - TAX_RATE) - entry * (1 + FEE_RATE)
    return pnl / (entry - stop)


def _valid_plan(entry, stop, target) -> bool:
    return bool(entry and stop and target) and 0 < stop < entry < target


def simulate_odds(df, entry: float, stop: float, target: float,
                  horizon: int = HORIZON_DAYS, replays: int = 3000, seed: int = 19) -> Optional[dict]:
    """
    從該股自己的日 K 隨機抽樣重組未來走勢，算先到目標 / 先到停損 / 期滿未到的比例。
    同一根 K 棒同時碰到停損與目標時算停損；跳空跌破停損以開盤價出場。
    這是模擬，不是預測；抽樣區間的多空趨勢會直接影響結果。
    """
    if df is None or not _valid_plan(entry, stop, target):
        return None
    d = df[["Open", "High", "Low", "Close"]].dropna()
    prev = d["Close"].shift(1)
    ratios = d.div(prev, axis=0).dropna().to_numpy(dtype=float)
    ratios = ratios[(ratios > 0).all(axis=1)]
    if len(ratios) < MIN_BARS:
        return None
    ratios = np.clip(ratios, 1 - LIMIT_PCT, 1 + LIMIT_PCT)

    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(ratios), size=(replays, horizon))
    price = np.full(replays, float(entry))
    exits = np.full(replays, np.nan)
    outcome = np.zeros(replays, dtype=np.int8)      # 1 目標、-1 停損、0 期滿未到

    for day in range(horizon):
        open_ = outcome == 0
        if not open_.any():
            break
        bar = ratios[draws[:, day]]
        o, h, l, c = (price * bar[:, k] for k in range(4))
        stop_hit = open_ & (l <= stop)
        target_hit = open_ & ~stop_hit & (h >= target)
        exits[stop_hit] = np.minimum(o[stop_hit], stop)
        exits[target_hit] = target
        outcome[stop_hit] = -1
        outcome[target_hit] = 1
        price = c

    still_open = outcome == 0
    exits[still_open] = price[still_open]
    avg_r = float(_net_r(exits, entry, stop).mean())
    return {
        "target_pct": round(float((outcome == 1).mean()) * 100, 1),
        "stop_pct": round(float((outcome == -1).mean()) * 100, 1),
        "neither_pct": round(float(still_open.mean()) * 100, 1),
        "avg_r": round(avg_r, 2),
        "verdict": "偏有利" if avg_r >= 0.15 else ("偏不利" if avg_r <= -0.15 else "接近打平"),
        "bars": len(ratios),
        "horizon": horizon,
        "replays": replays,
    }


def walk_forward(df, i: int, stop: float, target: float, horizon: int = HORIZON_DAYS) -> Optional[dict]:
    """第 i 天收盤進場後的真實結果。資料不足、尚未分出結果的回傳 None。"""
    entry = float(df["Close"].iloc[i])
    if not _valid_plan(entry, stop, target):
        return None
    last = min(i + horizon, len(df) - 1)
    for j in range(i + 1, last + 1):
        o, h, l = (float(df[k].iloc[j]) for k in ("Open", "High", "Low"))
        if l <= stop:
            return {"outcome": -1, "r": float(_net_r(min(o, stop), entry, stop)), "exit_idx": j}
        if h >= target:
            return {"outcome": 1, "r": float(_net_r(target, entry, stop)), "exit_idx": j}
    if i + horizon > len(df) - 1:
        return None
    return {"outcome": 0, "r": float(_net_r(float(df["Close"].iloc[last]), entry, stop)), "exit_idx": last}


def summarize_trades(results: list) -> dict:
    n = len(results)
    if n == 0:
        return {"n": 0, "target": 0, "stop": 0, "neither": 0, "avg_r": 0.0}
    return {
        "n": n,
        "target": sum(r["outcome"] == 1 for r in results),
        "stop": sum(r["outcome"] == -1 for r in results),
        "neither": sum(r["outcome"] == 0 for r in results),
        "avg_r": round(sum(r["r"] for r in results) / n, 2),
    }


def history_same_distance(df, entry: float, stop: float, target: float,
                          horizon: int = HORIZON_DAYS) -> Optional[dict]:
    """
    過去每個可進場日，用「相同百分比距離」的停損與目標實際走一次（不重疊計算）。
    注意：這是同距離、不是同訊號。同訊號回放見波段 App 的 scanner.replay_setup_history。
    """
    if df is None or not _valid_plan(entry, stop, target):
        return None
    d = df[["Open", "High", "Low", "Close"]].dropna()
    stop_ratio, target_ratio = stop / entry, target / entry
    results, i = [], 0
    while i < len(d) - 1:
        px = float(d["Close"].iloc[i])
        r = walk_forward(d, i, px * stop_ratio, px * target_ratio, horizon)
        if r is None:
            i += 1
            continue
        results.append(r)
        i = r["exit_idx"] + 1
    return summarize_trades(results)


def fmt_shares(n: int) -> str:
    """1,350 → '1 張 350 股'；不足 1 張只寫股數。"""
    lots, odd = divmod(int(n), 1000)
    if lots and odd:
        return f"{lots} 張 {odd} 股"
    return f"{lots} 張" if lots else f"{odd} 股"


def size_odd_lot(entry: float, stop: float, budget: float = DEFAULT_BUDGET,
                 max_loss: float = DEFAULT_MAX_LOSS) -> dict:
    """風險法股數：同時受單檔資金上限與單筆最大虧損限制，成本計入手續費與證交稅。"""
    buy_cost = entry * (1 + FEE_RATE)
    loss_each = buy_cost - stop * (1 - FEE_RATE - TAX_RATE)
    by_budget = int(budget // buy_cost)
    by_loss = int(max_loss // loss_each) if loss_each > 0 else 0
    shares = min(by_budget, by_loss)
    return {
        "shares": shares,
        "by_budget": by_budget,
        "by_loss": by_loss,
        "cost": round(shares * buy_cost),
        "loss_at_stop": round(shares * loss_each),
    }


def check_trade(entry: float, stop: float, target: float, budget: float = DEFAULT_BUDGET,
                max_loss: float = DEFAULT_MAX_LOSS, min_rr: float = MIN_NET_RR) -> dict:
    """進場前檢查，回傳 PASS 或 BLOCK 與原因。只產生提示，不會阻止任何操作。"""
    if not _valid_plan(entry, stop, target):
        return {"verdict": "BLOCK", "reasons": ["停損、進場、目標價順序不合理"], "warnings": [],
                "net_rr": 0.0, "size": {"shares": 0, "cost": 0, "loss_at_stop": 0}}
    buy_cost = entry * (1 + FEE_RATE)
    sell_keep = 1 - FEE_RATE - TAX_RATE
    net_rr = (target * sell_keep - buy_cost) / (buy_cost - stop * sell_keep)
    size = size_odd_lot(entry, stop, budget, max_loss)
    reasons, warnings = [], []

    if net_rr < min_rr:
        reasons.append(f"扣成本後報酬風險比 1:{net_rr:.2f}，低於 1:{min_rr:.1f}")
    elif net_rr < GOOD_NET_RR:
        warnings.append(f"報酬風險比 1:{net_rr:.2f} 偏低")
    if size["by_budget"] < 1:
        reasons.append(f"NT${budget:,.0f} 買不到 1 股")
    elif size["by_loss"] < 1:
        reasons.append(f"買 1 股的停損虧損就超過上限 NT${max_loss:,.0f}")
    if 1 - stop / entry > LIMIT_PCT:
        warnings.append(f"停損距離 {(1 - stop / entry) * 100:.1f}% 大於單日跌停幅度")

    return {"verdict": "BLOCK" if reasons else "PASS", "reasons": reasons, "warnings": warnings,
            "net_rr": round(float(net_rr), 2), "size": size}


def render_html(check: Optional[dict] = None, odds: Optional[dict] = None, hist: Optional[dict] = None,
                hist_label: str = "同距離歷史", max_loss: float = DEFAULT_MAX_LOSS) -> str:
    """深色卡片用的單行 HTML（Streamlit markdown 不可有空行或縮排）。"""
    parts = []
    if check is not None:
        ok = check["verdict"] == "PASS"
        col = "#69f0ae" if ok else "#ef5350"
        note = "；".join(check["reasons"] + check["warnings"])
        size = check["size"]
        size_txt = (f'{fmt_shares(size["shares"])}（約 NT${size["cost"]:,}，到停損約虧 NT${size["loss_at_stop"]:,}）'
                    if size["shares"] > 0 else "不建議建倉")
        parts.append(
            f'<div><b style="color:{col}">🛡 風險檢查 {check["verdict"]}</b>'
            + (f'　<span style="color:#ccc">{note}</span>' if note else "") + '</div>'
            f'<div style="color:#ccc">🧮 建議部位（單筆虧損上限 NT${max_loss:,.0f}）：{size_txt}</div>'
        )
    if odds is not None:
        vcol = {"偏有利": "#69f0ae", "偏不利": "#ef5350"}.get(odds["verdict"], "#ffd54f")
        parts.append(
            f'<div style="color:#ccc">🎲 模擬 {odds["horizon"]} 日：先到目標 <b>{odds["target_pct"]:.0f}%</b>　'
            f'先到停損 <b>{odds["stop_pct"]:.0f}%</b>　未分勝負 {odds["neither_pct"]:.0f}%　'
            f'平均 {odds["avg_r"]:+.2f}R <b style="color:{vcol}">{odds["verdict"]}</b></div>'
        )
    if hist is not None and hist["n"] > 0:
        parts.append(
            f'<div style="color:#ccc">📜 {hist_label} {hist["n"]} 次：到目標 {hist["target"]}　'
            f'到停損 {hist["stop"]}　未分勝負 {hist["neither"]}　平均 {hist["avg_r"]:+.2f}R</div>'
        )
    if not parts:
        return ""
    bars = f'近 {odds["bars"]} 個交易日、' if odds else ""
    parts.append(f'<div style="color:#777;font-size:10px">{bars}已扣手續費與證交稅。模擬不是預測，僅供參考。</div>')
    return ('<div style="background:#0a1020;border-radius:6px;padding:8px 12px;margin:6px 0;'
            'font-size:11px;line-height:1.7">' + "".join(parts) + '</div>')
