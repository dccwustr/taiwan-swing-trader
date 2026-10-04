#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
風險管理與部位紀錄
Position sizing, trade logging, drawdown monitoring, P&L tracking.
Persists trades to data/trades.json.
"""
import json, os
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
import math

TST = timezone(timedelta(hours=8))
_TRADES_PATH = os.path.join(os.path.dirname(__file__), "data", "trades.json")

CAPITAL = 500_000           # NT$ total capital
RISK_PER_TRADE_PCT = 0.02   # 2% of capital max loss per trade → NT$10,000
MAX_NOTIONAL_PCT   = 0.30   # 30% per position → NT$150,000
MAX_POSITIONS      = 4      # max concurrent open positions
DAILY_LOSS_LIMIT   = 20_000 # NT$ — stop trading if exceeded
MONTHLY_LOSS_LIMIT = 75_000 # NT$ — full review if exceeded


# ─────────────────────────────────────────────────────────────────────────────
#  Position Sizing
# ─────────────────────────────────────────────────────────────────────────────

def calc_position_size(entry: float, stop: float,
                       capital: int = CAPITAL,
                       risk_pct: float = RISK_PER_TRADE_PCT,
                       max_notional_pct: float = MAX_NOTIONAL_PCT,
                       lot_size: int = 1000) -> dict:
    """
    Kelly/Fixed-fraction position sizing.
    entry: 進場價
    stop: 停損價
    Returns dict with shares (in lots), notional, risk_nwd, stop_pct.
    """
    if entry <= 0 or stop >= entry:
        return {"shares": 0, "lots": 0, "notional": 0, "risk_nwd": 0, "stop_pct": 0}

    max_risk  = capital * risk_pct
    risk_per  = entry - stop
    max_nw    = capital * max_notional_pct

    shares_by_risk = int(max_risk / risk_per)
    shares_by_cap  = int(max_nw / entry)
    shares         = min(shares_by_risk, shares_by_cap)
    shares         = max(shares, 1)

    lots     = max(1, (shares // lot_size)) * lot_size
    notional = round(lots * entry)
    actual_risk = round((entry - stop) * lots)
    stop_pct = round((stop - entry) / entry * 100, 2)

    return {
        "shares":   lots,
        "lots":     lots // lot_size,
        "notional": notional,
        "risk_nwd": actual_risk,
        "stop_pct": stop_pct,
    }


def calc_target_prices(entry: float, stop: float, rr_targets=(1.5, 2.0, 3.0)) -> dict:
    """R:R based target prices."""
    risk = entry - stop
    return {
        f"target_rr{str(rr).replace('.','_')}": round(entry + risk * rr, 1)
        for rr in rr_targets
    }


# ─────────────────────────────────────────────────────────────────────────────
#  Trade Journal
# ─────────────────────────────────────────────────────────────────────────────

def _load_db() -> dict:
    try:
        with open(_TRADES_PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
        if "trades" not in d:
            d["trades"] = []
        if "closed" not in d:
            d["closed"] = []
        return d
    except Exception:
        return {"trades": [], "closed": []}


def _save_db(db: dict):
    os.makedirs(os.path.dirname(_TRADES_PATH), exist_ok=True)
    with open(_TRADES_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)


def open_trade(ticker: str, name: str, entry: float, stop: float,
               target: float, shares: int, trade_type: str = "swing",
               setup_type: str = "", notes: str = "") -> dict:
    """Add a new open trade to the journal."""
    db   = _load_db()
    now  = datetime.now(tz=TST).isoformat()
    risk = round((entry - stop) * shares)
    rr   = round((target - entry) / (entry - stop), 2) if (entry - stop) > 0 else 0
    trade = {
        "id":        f"{ticker}_{now[:10]}_{len(db['trades'])+len(db['closed'])+1}",
        "ticker":    ticker,
        "name":      name,
        "entry":     entry,
        "stop":      stop,
        "target":    target,
        "shares":    shares,
        "notional":  round(entry * shares),
        "risk_nwd":  risk,
        "rr":        rr,
        "type":      trade_type,
        "setup":     setup_type,
        "notes":     notes,
        "opened_at": now,
        "status":    "open",
    }
    db["trades"].append(trade)
    _save_db(db)
    return trade


def close_trade(trade_id: str, exit_price: float, exit_note: str = "") -> Optional[dict]:
    """Close a trade and move to closed list."""
    db = _load_db()
    idx = next((i for i, t in enumerate(db["trades"]) if t["id"] == trade_id), None)
    if idx is None:
        return None

    t = db["trades"][idx]
    now    = datetime.now(tz=TST).isoformat()
    pnl    = round((exit_price - t["entry"]) * t["shares"])
    pnl_pct = round((exit_price - t["entry"]) / t["entry"] * 100, 2)
    outcome = "win" if pnl > 0 else ("be" if pnl == 0 else "loss")

    t.update({
        "exit_price": exit_price,
        "exit_note":  exit_note,
        "closed_at":  now,
        "pnl":        pnl,
        "pnl_pct":    pnl_pct,
        "outcome":    outcome,
        "status":     "closed",
    })
    db["closed"].append(t)
    db["trades"].pop(idx)
    _save_db(db)
    return t


def update_stop(trade_id: str, new_stop: float) -> bool:
    """Update stop loss (trailing stop)."""
    db = _load_db()
    for t in db["trades"]:
        if t["id"] == trade_id:
            t["stop"] = new_stop
            t["risk_nwd"] = round((t["entry"] - new_stop) * t["shares"])
            _save_db(db)
            return True
    return False


def get_open_trades() -> List[dict]:
    return _load_db()["trades"]


def get_closed_trades() -> List[dict]:
    return _load_db()["closed"]


# ─────────────────────────────────────────────────────────────────────────────
#  P&L Analytics
# ─────────────────────────────────────────────────────────────────────────────

def compute_stats(closed: List[dict], capital: int = CAPITAL) -> dict:
    if not closed:
        return {
            "total_trades": 0, "wins": 0, "losses": 0,
            "win_rate": 0.0, "profit_factor": 0.0,
            "total_pnl": 0, "avg_win": 0, "avg_loss": 0,
            "max_drawdown_pct": 0.0, "largest_win": 0, "largest_loss": 0,
            "avg_hold_days": 0, "monthly_pnl": {},
        }

    wins   = [t for t in closed if t.get("pnl", 0) > 0]
    losses = [t for t in closed if t.get("pnl", 0) <= 0]
    total  = len(closed)

    win_rate = len(wins) / total
    avg_win  = sum(t["pnl"] for t in wins)  / len(wins)  if wins   else 0
    avg_loss = sum(t["pnl"] for t in losses) / len(losses) if losses else 0
    gross_profit = sum(t["pnl"] for t in wins)
    gross_loss   = abs(sum(t["pnl"] for t in losses)) or 1
    pf = gross_profit / gross_loss

    total_pnl = sum(t.get("pnl", 0) for t in closed)

    # Max drawdown from equity curve
    equity = capital
    peak   = capital
    max_dd = 0.0
    for t in sorted(closed, key=lambda x: x.get("closed_at", "")):
        equity += t.get("pnl", 0)
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak * 100
        if dd > max_dd:
            max_dd = dd

    # Hold time
    hold_days = []
    for t in closed:
        try:
            open_dt  = datetime.fromisoformat(t["opened_at"])
            close_dt = datetime.fromisoformat(t["closed_at"])
            hold_days.append((close_dt - open_dt).days)
        except Exception:
            pass
    avg_hold = round(sum(hold_days) / len(hold_days)) if hold_days else 0

    # Monthly P&L
    monthly: Dict[str, int] = {}
    for t in closed:
        try:
            mo = t.get("closed_at", "")[:7]  # "YYYY-MM"
            monthly[mo] = monthly.get(mo, 0) + t.get("pnl", 0)
        except Exception:
            pass

    return {
        "total_trades":    total,
        "wins":            len(wins),
        "losses":          len(losses),
        "win_rate":        round(win_rate * 100, 1),
        "profit_factor":   round(pf, 2),
        "total_pnl":       total_pnl,
        "avg_win":         round(avg_win),
        "avg_loss":        round(avg_loss),
        "max_drawdown_pct": round(max_dd, 1),
        "largest_win":     max((t["pnl"] for t in wins), default=0),
        "largest_loss":    min((t["pnl"] for t in losses), default=0),
        "avg_hold_days":   avg_hold,
        "monthly_pnl":     dict(sorted(monthly.items())),
    }


def daily_risk_check(capital: int = CAPITAL) -> dict:
    """Check today's P&L and open risk vs daily limits."""
    closed = get_closed_trades()
    open_t = get_open_trades()
    today  = datetime.now(tz=TST).strftime("%Y-%m-%d")

    today_pnl   = sum(t.get("pnl", 0) for t in closed if t.get("closed_at", "")[:10] == today)
    open_risk   = sum(abs(t.get("risk_nwd", 0)) for t in open_t)
    open_count  = len(open_t)
    open_notional = sum(t.get("notional", 0) for t in open_t)

    can_trade = (
        today_pnl > -DAILY_LOSS_LIMIT and
        open_count < MAX_POSITIONS
    )

    return {
        "today_pnl":       today_pnl,
        "open_count":      open_count,
        "open_risk":       open_risk,
        "open_notional":   open_notional,
        "capital_deployed_pct": round(open_notional / capital * 100, 1),
        "can_trade":       can_trade,
        "daily_limit_hit": today_pnl <= -DAILY_LOSS_LIMIT,
        "positions_full":  open_count >= MAX_POSITIONS,
    }
