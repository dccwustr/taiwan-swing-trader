#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
大盤急跌偵測 — 複製自 taiwan_stock_widget/dip_watch.py 的 market_drop()（同 widget.py 的做法），
門檻請兩邊同步修改。台股 App 那份另有反彈候補紀錄，這裡只用來判斷要不要建議半倉。
"""

DIP_ALERT_PCT = -2.0   # 加權指數單日跌幅 ≤ 此值 → 急跌日
DRAWDOWN_PCT  = -5.0   # 距 20 日高點跌幅 ≤ 此值 → 也算急跌（連續幾天小跌累積）


def market_drop(taiex_close) -> dict:
    """TAIEX 單日漲跌與距 20 日高點跌幅。資料不足時 chg1d/drawdown 為 None。"""
    out = {"chg1d": None, "drawdown": None, "alert": False}
    if taiex_close is None or len(taiex_close) < 21:
        return out
    close = taiex_close.dropna()
    last, prev = float(close.iloc[-1]), float(close.iloc[-2])
    high20 = float(close.iloc[-20:].max())
    out["chg1d"] = round((last / prev - 1) * 100, 2)
    out["drawdown"] = round((last / high20 - 1) * 100, 2)
    out["alert"] = out["chg1d"] <= DIP_ALERT_PCT or out["drawdown"] <= DRAWDOWN_PCT
    return out
