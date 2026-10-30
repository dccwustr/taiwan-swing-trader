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


# ─────────────────────────────────────────────────────────────────────────────
#  交易紀錄檢討 — 找出重複犯的錯、錯過的機會、行為偏誤，產出 3 條個人化規則
# ─────────────────────────────────────────────────────────────────────────────

def _initial_risk(t: dict) -> float:
    """開倉時每股風險。止損可能已上移，所以用 目標/R:R 反推原始風險。"""
    rr = t.get("rr", 0) or 0
    if rr > 0 and t.get("target", 0) > t.get("entry", 0):
        return (t["target"] - t["entry"]) / rr
    return max(t.get("entry", 0) - t.get("stop", 0), 0)


def review_trades(closed: List[dict], prices: Optional[dict] = None, n: int = 20) -> dict:
    """
    檢視最近 n 筆已平倉交易。
    prices: {ticker: DataFrame}（可省略）— 用來判斷提早出場後股價是否仍達目標。
    回傳 mistakes / missed / biases（各為字串清單）與 rules（最多 3 條）。
    """
    recent = sorted(closed, key=lambda x: x.get("closed_at", ""))[-n:]
    if len(recent) < 3:
        return {"count": len(recent), "mistakes": [], "missed": [], "biases": [], "rules": []}

    findings = []   # (priority, kind, text, rule)

    def _r(t):
        risk = _initial_risk(t)
        return (t.get("exit_price", t["entry"]) - t["entry"]) / risk if risk > 0 else 0.0

    wins   = [t for t in recent if t.get("pnl", 0) > 0]
    losses = [t for t in recent if t.get("pnl", 0) <= 0]

    # ① 沒守停損：出場價明顯低於停損價
    blown = [t for t in losses if t.get("exit_price", 0) < t.get("stop", 0) * 0.99]
    if blown:
        worst = min(_r(t) for t in blown)
        findings.append((1, "mistake",
            f"{len(blown)} 筆跌破停損才出場（最差 {worst:.1f}R），虧損超出計畫",
            "跌破停損價當天收盤前一定出場，不等反彈"))

    # ② 賺小賠大：平均獲利 R 小於平均虧損 R
    if wins and losses:
        avg_win_r  = sum(_r(t) for t in wins) / len(wins)
        avg_loss_r = abs(sum(_r(t) for t in losses) / len(losses))
        if avg_win_r < avg_loss_r:
            findings.append((2, "bias",
                f"賺小賠大：平均獲利 {avg_win_r:.1f}R，平均虧損 {avg_loss_r:.1f}R（處分效應）",
                "獲利單至少抱到 1.5R 或跌破追蹤止損才出場"))

    # ③ 抱虧損比抱獲利久
    def _days(t):
        try:
            return (datetime.fromisoformat(t["closed_at"]) - datetime.fromisoformat(t["opened_at"])).days
        except Exception:
            return None
    wd = [d for d in (_days(t) for t in wins) if d is not None]
    ld = [d for d in (_days(t) for t in losses) if d is not None]
    if wd and ld and sum(ld) / len(ld) > 1.5 * max(sum(wd) / len(wd), 1):
        findings.append((3, "bias",
            f"虧損單平均抱 {sum(ld)/len(ld):.0f} 天，獲利單只抱 {sum(wd)/len(wd):.0f} 天——不願認賠",
            "持倉超過 10 個交易日仍未達 1R，就減碼一半"))

    # ④ 報復性交易：虧損平倉當天又開新倉
    by_open = sorted(recent, key=lambda x: x.get("opened_at", ""))
    revenge = 0
    for lt in losses:
        day = lt.get("closed_at", "")[:10]
        if any(o.get("opened_at", "")[:10] == day and o.get("opened_at", "") > lt.get("closed_at", "")
               for o in by_open):
            revenge += 1
    if revenge:
        findings.append((2, "bias",
            f"{revenge} 次虧損出場後當天又開新倉（報復性交易）",
            "停損出場當天不開新倉，隔天盤前重新評估"))

    # ⑤ 進場時 R:R 不足
    low_rr = [t for t in recent if 0 < t.get("rr", 0) < 1.5]
    if low_rr:
        findings.append((4, "mistake",
            f"{len(low_rr)} 筆進場時風險報酬比低於 1:1.5",
            "R:R 未達 1:1.5 的設置一律不進場"))

    # ⑥ 設置類型表現：找出勝率最差的設置
    by_setup: Dict[str, List[dict]] = {}
    for t in recent:
        by_setup.setdefault(t.get("setup") or "未分類", []).append(t)
    rated = [(k, sum(1 for t in v if t.get("pnl", 0) > 0) / len(v), len(v))
             for k, v in by_setup.items() if len(v) >= 3]
    if len(rated) >= 2:
        worst_k, worst_wr, worst_n = min(rated, key=lambda x: x[1])
        best_k, best_wr, _ = max(rated, key=lambda x: x[1])
        if worst_wr < 0.4 and best_wr - worst_wr >= 0.2:
            findings.append((3, "mistake",
                f"「{worst_k}」設置 {worst_n} 筆勝率只有 {worst_wr*100:.0f}%，"
                f"「{best_k}」勝率 {best_wr*100:.0f}%",
                f"暫停「{worst_k}」設置，集中做「{best_k}」"))

    # ⑦ 錯過的機會：未達目標就出場，之後股價仍漲到目標
    missed = []
    if prices:
        for t in wins:
            if t.get("exit_price", 0) >= t.get("target", 0):
                continue
            df = prices.get(t["ticker"])
            if df is None or not len(df):
                continue
            try:
                idx = df.index.tz_localize(None) if df.index.tz is not None else df.index
                after = df["High"][idx > datetime.fromisoformat(t["closed_at"]).replace(tzinfo=None)].head(15)
            except Exception:
                continue
            if len(after) and float(after.max()) >= t["target"]:
                missed.append(f"{t.get('name', t['ticker'])}：NT${t['exit_price']} 出場，"
                              f"之後 15 日內漲到目標 NT${t['target']}")
        if len(missed) >= 2:
            findings.append((2, "missed",
                f"{len(missed)} 筆提早停利，之後股價仍達原目標",
                "到達 1R 後先出一半，剩下用追蹤止損抱到目標"))

    findings.sort(key=lambda x: x[0])
    rules = []
    for f in findings:
        if f[3] not in rules:
            rules.append(f[3])
    for default in ("每筆風險固定資本 2%，不因手感加碼",
                    "進場前寫下停損與目標，盤中不改計畫",
                    "連續 3 筆虧損後暫停交易一天"):
        if len(rules) >= 3:
            break
        if default not in rules:
            rules.append(default)

    return {
        "count":    len(recent),
        "mistakes": [f[2] for f in findings if f[1] == "mistake"],
        "missed":   missed,
        "biases":   [f[2] for f in findings if f[1] == "bias"],
        "rules":    rules[:3],
    }
