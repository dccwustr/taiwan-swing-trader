#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
台灣科技股盤前分析系統 v1.0
Taiwan Tech Stock Pre-Market Analysis Widget
晶片・記憶體・AI — NVIDIA / AMD / Apple 上游供應鏈深度追蹤
每日早上 8:00 執行，分析最有可能大漲的5支股票
"""

import sys, re, json, time, warnings, argparse
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
import requests
import pandas as pd
import numpy as np
from bs4 import BeautifulSoup

warnings.filterwarnings("ignore")

try:
    import yfinance as yf
    HAS_YF = True
except Exception:
    HAS_YF = False
    yf = None  # type: ignore

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.text import Text
    from rich import box
    from rich.rule import Rule
    from rich.columns import Columns
    from rich.align import Align
    from rich.progress import Progress, SpinnerColumn, TextColumn
    HAS_RICH = True
except Exception:
    HAS_RICH = False

# Safe console: falls back to a no-op when rich is unavailable (e.g. Streamlit Cloud)
if HAS_RICH:
    console = Console(width=130)
else:
    class _FakeConsole:
        def print(self, *a, **kw): pass
        def rule(self, *a, **kw): pass
    console = _FakeConsole()  # type: ignore

# ═══════════════════════════════════════════════════════════════════════════════
#  持股設定
# ═══════════════════════════════════════════════════════════════════════════════
MY_HOLDINGS = {}

# ═══════════════════════════════════════════════════════════════════════════════
#  股票池：全產業（科技 + 金融 + 航運 + 生技 + 消費 + 綠能 + 傳產…）
#  原則：只要有潛力，不限產業
# ═══════════════════════════════════════════════════════════════════════════════
TECH_UNIVERSE: Dict[str, Dict] = {

    # ════════════════════════════════════════════════════════════════════════
    #  科技業 Technology
    # ════════════════════════════════════════════════════════════════════════

    # ── 晶圓代工 Foundry ────────────────────────────────────────────────────
    "2330.TW": {"name":"台積電",    "en":"TSMC",              "sector":"晶圓代工",  "supply":["NVIDIA","AMD","Apple","AI","CoWoS"]},
    "2303.TW": {"name":"聯電",      "en":"UMC",               "sector":"晶圓代工",  "supply":[]},
    "6770.TW": {"name":"力積電",    "en":"PSMC",              "sector":"晶圓代工",  "supply":[]},
    # ── IC設計 Fabless ──────────────────────────────────────────────────────
    "2454.TW": {"name":"聯發科",    "en":"MediaTek",          "sector":"IC設計",    "supply":["AI","AMD"]},
    "3034.TW": {"name":"聯詠",      "en":"Novatek",           "sector":"IC設計",    "supply":["Apple"]},
    "2379.TW": {"name":"瑞昱",      "en":"Realtek",           "sector":"IC設計",    "supply":[]},
    "6415.TW": {"name":"矽力-KY",   "en":"Silergy",           "sector":"IC設計",    "supply":["AI"]},
    "2458.TW": {"name":"義隆電",    "en":"Elan Micro",        "sector":"IC設計",    "supply":["Apple"]},
    "2401.TW": {"name":"凌陽",      "en":"Sunplus",           "sector":"IC設計",    "supply":[]},
    # ── 記憶體 Memory ───────────────────────────────────────────────────────
    "2344.TW": {"name":"華邦電",    "en":"Winbond",           "sector":"記憶體",    "supply":[]},
    "2408.TW": {"name":"南亞科",    "en":"Nanya Tech",        "sector":"DRAM",      "supply":[]},
    "8299.TW": {"name":"群聯",      "en":"Phison",            "sector":"NAND控制器","supply":["AI"]},
    # ── 矽晶圓 Silicon Wafer ─────────────────────────────────────────────────
    "6488.TW": {"name":"環球晶",    "en":"GlobalWafers",      "sector":"矽晶圓",    "supply":["AI","NVIDIA"]},
    "5483.TW": {"name":"中美晶",    "en":"Sino-American Si",  "sector":"矽晶圓",    "supply":["AI"]},
    "3532.TW": {"name":"台勝科",    "en":"Sino-American TW",  "sector":"矽晶圓",    "supply":["AI"]},
    # ── 先進封裝 / 封測 Packaging ───────────────────────────────────────────
    "3711.TW": {"name":"日月光投控","en":"ASE Technology",    "sector":"封測",      "supply":["NVIDIA","AMD","Apple","CoWoS"]},
    "2449.TW": {"name":"京元電子",  "en":"KYEC",              "sector":"IC測試",    "supply":[]},
    "6239.TW": {"name":"力成科技",  "en":"Powertech Tech",    "sector":"記憶體封測","supply":["AI","HBM"]},
    # ── IC載板 / PCB ────────────────────────────────────────────────────────
    "3037.TW": {"name":"欣興",      "en":"Unimicron",         "sector":"IC載板",    "supply":["NVIDIA","AMD","CoWoS"]},
    "3044.TW": {"name":"健鼎",      "en":"Tripod Tech",       "sector":"PCB",       "supply":["NVIDIA","AI"]},
    "4958.TW": {"name":"臻鼎-KY",   "en":"Zhen Ding Tech",    "sector":"高階PCB",   "supply":["NVIDIA","AI"]},
    "3189.TW": {"name":"景碩科技",  "en":"Chipbond",          "sector":"IC載板",    "supply":["AI","CoWoS"]},
    "6213.TW": {"name":"聯茂電子",  "en":"Elite Material",    "sector":"PCB材料",   "supply":["AI","NVIDIA"]},
    # ── 玻纖布 / PCB原材料 Glass Fiber / CCL ─────────────────────────────────
    "1802.TW": {"name":"台灣玻璃",  "en":"Taiwan Glass",      "sector":"玻纖布",    "supply":["NVIDIA","AI"]},
    "1815.TW": {"name":"富喬工業",  "en":"Fû Chiao Ind",     "sector":"玻纖布",    "supply":["AI"]},
    "5475.TW": {"name":"德宏工業",  "en":"Deh Horng Ind",     "sector":"玻纖布",    "supply":["AI"]},
    # ── AI伺服器 / ODM ──────────────────────────────────────────────────────
    "6669.TW": {"name":"緯穎",      "en":"Wiwynn",            "sector":"AI伺服器",  "supply":["NVIDIA","AI"]},
    "2382.TW": {"name":"廣達",      "en":"Quanta",            "sector":"伺服器ODM", "supply":["NVIDIA","AI","Apple"]},
    "3231.TW": {"name":"緯創",      "en":"Wistron",           "sector":"ODM",       "supply":["Apple","AI"]},
    "4938.TW": {"name":"和碩",      "en":"Pegatron",          "sector":"ODM",       "supply":["Apple"]},
    "2317.TW": {"name":"鴻海",      "en":"Foxconn",           "sector":"EMS/ODM",   "supply":["Apple","NVIDIA","AI"]},
    "2324.TW": {"name":"仁寶",      "en":"Compal",            "sector":"ODM",       "supply":["Apple","AI"]},
    # ── 被動元件 Passive Components ─────────────────────────────────────────
    "2327.TW": {"name":"國巨",      "en":"Yageo",             "sector":"被動元件",  "supply":["NVIDIA","Apple","AI"]},
    "2492.TW": {"name":"華新科",    "en":"Walsin Tech",       "sector":"被動元件",  "supply":["AI"]},
    "3236.TW": {"name":"千如電機",  "en":"Chilisin Elec",     "sector":"被動元件",  "supply":["AI"]},
    "2472.TW": {"name":"立隆電子",  "en":"Lelon Electronics", "sector":"被動元件",  "supply":[]},
    # ── 連接器 Connectors ────────────────────────────────────────────────────
    "3533.TW": {"name":"嘉澤",      "en":"Lotes",             "sector":"連接器",    "supply":["AI","NVIDIA"]},
    # ── 光學 Optics ─────────────────────────────────────────────────────────
    "3008.TW": {"name":"大立光",    "en":"Largan",            "sector":"光學鏡頭",  "supply":["Apple"]},
    "3406.TW": {"name":"玉晶光",    "en":"Genius Optical",    "sector":"光學鏡頭",  "supply":["Apple"]},
    # ── 電源 / 散熱 Power & Thermal ─────────────────────────────────────────
    "2308.TW": {"name":"台達電",    "en":"Delta Electronics",  "sector":"電源散熱",  "supply":["NVIDIA","AI","綠能"]},
    "3017.TW": {"name":"奇鋐科技",  "en":"Asia Vital Comp",    "sector":"散熱模組",  "supply":["NVIDIA","AI"]},
    "3324.TW": {"name":"雙鴻科技",  "en":"Auras Technology",   "sector":"散熱模組",  "supply":["NVIDIA","AI"]},
    "8163.TW": {"name":"達方電子",  "en":"Darfon Electronics", "sector":"散熱/鍵盤", "supply":[]},
    "1626.TW": {"name":"艾美特",    "en":"Airmate",            "sector":"散熱風扇",  "supply":[]},
    "2369.TW": {"name":"菱生精密",  "en":"Lingsen Precision",  "sector":"精密零件",  "supply":[]},
    # ── 功率半導體 / 第三代半導體 Power & Compound Semiconductors ──────────────
    "3016.TW": {"name":"嘉晶電子",  "en":"Episil-Precision",  "sector":"化合物半導體","supply":["EV","AI"]},
    "8261.TW": {"name":"富鼎先進",  "en":"ASMPT Power",       "sector":"功率IC",    "supply":["AI","EV"]},
    # ── AI/特殊IC ────────────────────────────────────────────────────────────
    "3661.TW": {"name":"世芯-KY",   "en":"Alchip Technologies","sector":"ASIC設計",  "supply":["NVIDIA","AI","AMD"]},
    "3443.TW": {"name":"創意電子",  "en":"Global Unichip",     "sector":"ASIC設計",  "supply":["AI","NVIDIA","TSMC"]},
    "5274.TW": {"name":"信驊科技",  "en":"ASPEED Technology",  "sector":"伺服器IC",  "supply":["AI"]},
    "4966.TW": {"name":"譜瑞-KY",   "en":"Parade Technologies","sector":"顯示IC",    "supply":["Apple","AI"]},
    "4919.TW": {"name":"新唐科技",  "en":"Nuvoton Technology", "sector":"MCU/嵌入式","supply":[]},
    # ── 未來潛力股 Future Giants ──────────────────────────────────────────────
    "6138.TW": {"name":"茂達",      "en":"Mosfet Electronics",  "sector":"電源IC",    "supply":["AI"]},
    "8046.TW": {"name":"南電",      "en":"Nan Ya PCB",           "sector":"IC載板",    "supply":["AI","CoWoS"]},
    "3707.TW": {"name":"漢磊",      "en":"Han Lei Tech",         "sector":"化合物半導體","supply":["EV","AI"]},
    "3363.TW": {"name":"上詮",      "en":"Applied Optoelec",     "sector":"矽光子/CPO","supply":["AI","TSMC"]},
    "5289.TW": {"name":"宜鼎",      "en":"InnoDisk",             "sector":"邊緣AI儲存","supply":["AI"]},
    "4931.TW": {"name":"新盛力",    "en":"Shinergy Tech",        "sector":"BBU儲能",   "supply":["AI"]},
    "6282.TW": {"name":"康舒",      "en":"Acbel Polytech",       "sector":"伺服器電源","supply":["AI"]},
    "6230.TW": {"name":"尼得科超眾","en":"Nidec Surpass",        "sector":"液冷散熱",  "supply":["AI"]},
    # ── 伺服器ODM 補充 ───────────────────────────────────────────────────────
    "2356.TW": {"name":"英業達",    "en":"Inventec",           "sector":"伺服器ODM", "supply":["NVIDIA","AI"]},
    "2301.TW": {"name":"光寶科技",  "en":"Lite-On Technology", "sector":"電源/伺服器","supply":["AI"]},
    # ── 封測補充 ─────────────────────────────────────────────────────────────
    "8150.TW": {"name":"南茂科技",  "en":"ChipMOS Technologies","sector":"IC封測",   "supply":[]},
    "6271.TW": {"name":"同欣電子",  "en":"Tong Hsing Electronic","sector":"IC封測",  "supply":[]},
    # ── 晶圓代工補充 ──────────────────────────────────────────────────────────
    "5347.TW": {"name":"世界先進",  "en":"Vanguard Intl Semi", "sector":"晶圓代工",  "supply":[]},
    # ── 網通設備 ─────────────────────────────────────────────────────────────
    "2345.TW": {"name":"智邦科技",  "en":"Accton Technology",  "sector":"網通設備",  "supply":["AI"]},
    "6277.TW": {"name":"宏正自動",  "en":"ATEN International", "sector":"KVM/網通",  "supply":[]},
    "2332.TW": {"name":"友訊科技",  "en":"D-Link",             "sector":"網通設備",  "supply":[]},
    "3062.TW": {"name":"建漢科技",  "en":"CyberTAN Technology","sector":"網通ODM",   "supply":["AI"]},
    "3706.TW": {"name":"神基科技",  "en":"MiTAC Holdings",     "sector":"網通/電腦", "supply":[]},
    # ── 遊戲 Gaming ──────────────────────────────────────────────────────────
    "5478.TW": {"name":"智冠科技",  "en":"Soft-World Int'l",   "sector":"遊戲發行",  "supply":[]},
    "6180.TW": {"name":"加奇數位",  "en":"Gamania Digital",    "sector":"手遊",      "supply":[]},
    "6111.TW": {"name":"大宇資訊",  "en":"Softstar Entertainment","sector":"電腦遊戲","supply":[]},
    "4943.TW": {"name":"康控-KY",   "en":"Concraft Holding",   "sector":"精密電子",  "supply":[]},
    # ── 應用軟體 / IT服務 ────────────────────────────────────────────────────
    "6510.TW": {"name":"精誠資訊",  "en":"Systex Corporation", "sector":"IT服務",    "supply":["AI"]},
    "6104.TW": {"name":"創惟科技",  "en":"Genesys Logic",      "sector":"USB/橋接IC","supply":["Apple"]},
    "2353.TW": {"name":"宏碁",      "en":"Acer",               "sector":"3C品牌",    "supply":[]},
    # ── 電動車 EV ────────────────────────────────────────────────────────────
    "1590.TW": {"name":"亞德客-KY", "en":"Airtac Int'l",       "sector":"氣動元件",  "supply":["EV"]},
    "1537.TW": {"name":"廣隆電池",  "en":"Kung Long Batteries","sector":"EV電池",    "supply":["EV"]},
    "5536.TW": {"name":"聖暉工程",  "en":"Saint-Gobain TW?",   "sector":"EV充電基礎","supply":["EV","綠能"]},
    # ── 綠能 Green Energy ────────────────────────────────────────────────────
    "3576.TW": {"name":"聯合再生",  "en":"United Renewable Energy","sector":"太陽能", "supply":["綠能"]},
    "6443.TW": {"name":"元晶太陽能","en":"TSEC Corporation",   "sector":"太陽能電池","supply":["綠能"]},
    "6412.TW": {"name":"奇士達",    "en":"Chicony Power Tech", "sector":"電源模組",  "supply":["AI","綠能"]},
    "1519.TW": {"name":"華城電機",  "en":"Fortune Electric",   "sector":"電力系統",  "supply":["綠能"]},
    "3519.TW": {"name":"碩天科技",  "en":"Voltronic Power",    "sector":"UPS/電源",  "supply":["綠能"]},
    # ── 生技醫療 Biotech ─────────────────────────────────────────────────────
    "4743.TW": {"name":"合一生技",  "en":"CHC Healthcare",     "sector":"生技",      "supply":["生技"]},
    "6547.TW": {"name":"高端疫苗",  "en":"Medigen Vaccine",    "sector":"疫苗/生技", "supply":["生技"]},
    "4119.TW": {"name":"旭富製藥",  "en":"SCI Pharmtech",      "sector":"原料藥",    "supply":["生技"]},
    "1786.TW": {"name":"科妍生醫",  "en":"SciVision Biotech",  "sector":"醫美/生技", "supply":["生技"]},
    "4166.TW": {"name":"智擎生技",  "en":"PharmaEngine",       "sector":"新藥",      "supply":["生技"]},
    "4110.TW": {"name":"東洋製藥",  "en":"TTY Biopharm",       "sector":"學名藥",    "supply":["生技"]},
    # ── 手機供應鏈補充 ──────────────────────────────────────────────────────
    "6285.TW": {"name":"華通電腦",  "en":"WNC Corporation",    "sector":"無線模組",  "supply":["Apple"]},
    # ── 面板 Displays ────────────────────────────────────────────────────────
    "2409.TW": {"name":"友達",      "en":"AUO",               "sector":"面板",      "supply":["Apple"]},
    "3481.TW": {"name":"群創",      "en":"Innolux",           "sector":"面板",      "supply":[]},
    # ── 機殼 Enclosures ──────────────────────────────────────────────────────
    "2474.TW": {"name":"可成",      "en":"Catcher Tech",      "sector":"金屬機殼",  "supply":["Apple"]},
    # ── 品牌 / 主機板 ────────────────────────────────────────────────────────
    "2376.TW": {"name":"技嘉",      "en":"Gigabyte",          "sector":"主機板",    "supply":["NVIDIA","AMD","AI"]},
    "2357.TW": {"name":"華碩",      "en":"ASUS",              "sector":"3C品牌",    "supply":["NVIDIA","AMD","AI"]},
    "2395.TW": {"name":"研華",      "en":"Advantech",         "sector":"工業電腦",  "supply":["AI"]},
    # ── ETF ─────────────────────────────────────────────────────────────────
    "0052.TW": {"name":"富邦科技",  "en":"Fubon Tech ETF",    "sector":"ETF",       "supply":["ETF"]},

    # ════════════════════════════════════════════════════════════════════════
    #  金融 Financial
    # ════════════════════════════════════════════════════════════════════════
    "2881.TW": {"name":"富邦金",    "en":"Fubon Financial",   "sector":"金融",      "supply":["金融"]},
    "2882.TW": {"name":"國泰金",    "en":"Cathay Financial",  "sector":"金融",      "supply":["金融"]},
    "2884.TW": {"name":"玉山金",    "en":"E.Sun Financial",   "sector":"金融",      "supply":["金融"]},
    "2891.TW": {"name":"中信金",    "en":"CTBC Financial",    "sector":"金融",      "supply":["金融"]},
    "2886.TW": {"name":"兆豐金",    "en":"Mega Financial",    "sector":"金融",      "supply":["金融"]},
    "2892.TW": {"name":"第一金",    "en":"First Financial",   "sector":"金融",      "supply":["金融"]},
    "2880.TW": {"name":"華南金",    "en":"Hua Nan Financial", "sector":"金融",      "supply":["金融"]},
    "2883.TW": {"name":"開發金",    "en":"CDIB Financial",    "sector":"金融",      "supply":["金融"]},

    # ════════════════════════════════════════════════════════════════════════
    #  航運 Shipping
    # ════════════════════════════════════════════════════════════════════════
    "2603.TW": {"name":"長榮",      "en":"Evergreen Marine",  "sector":"航運",      "supply":["航運"]},
    "2609.TW": {"name":"陽明",      "en":"Yang Ming Marine",  "sector":"航運",      "supply":["航運"]},
    "2615.TW": {"name":"萬海",      "en":"Wan Hai Lines",     "sector":"航運",      "supply":["航運"]},
    "2610.TW": {"name":"華航",      "en":"China Airlines",    "sector":"航空",      "supply":["航空"]},
    "2618.TW": {"name":"長榮航",    "en":"EVA Air",           "sector":"航空",      "supply":["航空"]},

    # ════════════════════════════════════════════════════════════════════════
    #  國防 / 無人機 Defense / Drone
    # ════════════════════════════════════════════════════════════════════════
    "8033.TW": {"name":"雷虎科技",  "en":"Thunder Tiger",     "sector":"無人機",    "supply":["國防"]},
    "2634.TW": {"name":"漢翔航空",  "en":"AIDC",              "sector":"航太/國防", "supply":["國防"]},
    "2630.TW": {"name":"亞洲航空",  "en":"Asia Air Survey",   "sector":"國防航太",  "supply":["國防"]},
    "5371.TW": {"name":"中光電",    "en":"Coretronic Corp",   "sector":"無人機模組","supply":["國防","AI"]},
    "5222.TW": {"name":"全訊科技",  "en":"Accton Sys Tech",   "sector":"微波/國防", "supply":["國防"]},
    "6753.TW": {"name":"龍德造船",  "en":"Long De Shipbldg",  "sector":"造船/國防", "supply":["國防"]},

    # ════════════════════════════════════════════════════════════════════════
    #  鋼鐵 / 石化 / 原材料 Steel / Petrochem / Materials
    # ════════════════════════════════════════════════════════════════════════
    "2002.TW": {"name":"中鋼",      "en":"China Steel",       "sector":"鋼鐵",      "supply":["原物料"]},
    "2015.TW": {"name":"豐興",      "en":"Feng Hsin Steel",   "sector":"鋼鐵",      "supply":["原物料"]},
    "2023.TW": {"name":"燁聯",      "en":"Yieh United Steel", "sector":"鋼鐵",      "supply":["原物料"]},
    "1301.TW": {"name":"台塑",      "en":"Formosa Plastics",  "sector":"石化",      "supply":["原物料","石化"]},
    "1303.TW": {"name":"南亞",      "en":"Nan Ya Plastics",   "sector":"石化",      "supply":["原物料","石化"]},
    "1326.TW": {"name":"台化",      "en":"Formosa Chemicals", "sector":"石化",      "supply":["原物料","石化"]},

    # ════════════════════════════════════════════════════════════════════════
    #  電信 Telecom
    # ════════════════════════════════════════════════════════════════════════
    "2412.TW": {"name":"中華電",    "en":"Chunghwa Telecom",  "sector":"電信",      "supply":[]},
    "3045.TW": {"name":"台灣大",    "en":"Taiwan Mobile",     "sector":"電信",      "supply":[]},
    "4904.TW": {"name":"遠傳",      "en":"Far EasTone",       "sector":"電信",      "supply":[]},

    # ════════════════════════════════════════════════════════════════════════
    #  消費 / 零售 Consumer / Retail
    # ════════════════════════════════════════════════════════════════════════
    "2912.TW": {"name":"統一超",    "en":"President Chain",   "sector":"零售",      "supply":[]},
    "5903.TW": {"name":"全家",      "en":"FamilyMart TW",     "sector":"零售",      "supply":[]},
    "5904.TW": {"name":"寶雅",      "en":"Poya",              "sector":"零售",      "supply":[]},
    "2758.TW": {"name":"路易莎",    "en":"Louisa Coffee",     "sector":"餐飲",      "supply":[]},
    "2207.TW": {"name":"和泰車",    "en":"Hotai Motor",       "sector":"汽車",      "supply":[]},

    # ════════════════════════════════════════════════════════════════════════
    #  建設 / 不動產 Construction / Real Estate
    # ════════════════════════════════════════════════════════════════════════
    "5522.TW": {"name":"遠雄",      "en":"Farglory",          "sector":"建設",      "supply":["建設"]},
    "2542.TW": {"name":"興富發",    "en":"Highwealth Const",  "sector":"建設",      "supply":["建設"]},
    "2504.TW": {"name":"國產",      "en":"Kuo Chan Const",    "sector":"建設",      "supply":["建設"]},

    # ════════════════════════════════════════════════════════════════════════
    #  生技醫療 Biotech / Medical
    # ════════════════════════════════════════════════════════════════════════
    "6446.TW": {"name":"藥華藥",    "en":"PharmaEngine",      "sector":"生技",      "supply":["生技"]},
    "6472.TW": {"name":"保瑞",      "en":"Bora Pharma",       "sector":"生技",      "supply":["生技"]},
    "1789.TW": {"name":"神隆",      "en":"ScinoPharm",        "sector":"生技",      "supply":["生技"]},
    "1707.TW": {"name":"葡萄王",    "en":"Grape King Bio",    "sector":"保健",      "supply":[]},
    "4171.TW": {"name":"瑞基",      "en":"Reber Genetics",    "sector":"生技",      "supply":["生技"]},

    # ════════════════════════════════════════════════════════════════════════
    #  綠能 / 電力 Green Energy / Power
    # ════════════════════════════════════════════════════════════════════════
    "1513.TW": {"name":"中興電",    "en":"CENS",              "sector":"電機",      "supply":["綠能"]},
    "1504.TW": {"name":"東元",      "en":"Teco Electric",     "sector":"電機",      "supply":["綠能"]},
    "1101.TW": {"name":"台泥",      "en":"Taiwan Cement",     "sector":"水泥/綠能", "supply":["綠能"]},

    # ════════════════════════════════════════════════════════════════════════
    #  食品 Food
    # ════════════════════════════════════════════════════════════════════════
    "1216.TW": {"name":"統一",      "en":"Uni-President",     "sector":"食品",      "supply":[]},
    "1210.TW": {"name":"大成",      "en":"Great Wall Ent",    "sector":"食品",      "supply":[]},

    # ════════════════════════════════════════════════════════════════════════
    #  觀光 / 餐飲 Tourism / Hospitality
    # ════════════════════════════════════════════════════════════════════════
    "2707.TW": {"name":"晶華",      "en":"Regent Hotel",      "sector":"觀光",      "supply":[]},
    "2727.TW": {"name":"王品",      "en":"Wowprime",          "sector":"餐飲",      "supply":[]},
    "2731.TW": {"name":"雄獅",      "en":"Lion Travel",       "sector":"觀光",      "supply":[]},

    # ════════════════════════════════════════════════════════════════════════
    #  水泥 / 基建 Cement / Infrastructure
    # ════════════════════════════════════════════════════════════════════════
    "1102.TW": {"name":"亞泥",      "en":"Asia Cement",       "sector":"水泥",      "supply":[]},
}

# ── 新聞催化劑關鍵字（科技 + 多元產業）──────────────────────────────────────
CATALYST_MAP = {
    # 科技主題
    "NVIDIA": ["NVIDIA","輝達","Blackwell","GB200","GB300","H100","H200","NVL72","B200","Hopper","HGX","DGX"],
    "AMD":    ["AMD","超微","MI300","MI350","MI400","EPYC","Instinct"],
    "Apple":  ["Apple","蘋果","iPhone","iPad","Vision Pro","M4","A18","蘋果鏈"],
    "AI":     ["AI","人工智慧","生成式","LLM","大模型","算力","推論","訓練","GPU","NPU","機器人"],
    "CoWoS":  ["CoWoS","先進封裝","SoIC","2.5D","3D封裝","晶片堆疊"],
    "記憶體": ["HBM","記憶體","DRAM","NAND","高頻寬","HBM3E","High Bandwidth Memory"],
    "漲價":   ["漲價","調漲","報價提升","price hike","報價上調","Q3漲價","全面漲價","規格漲價"],
    "訂單":   ["接單","新訂單","出貨","交貨","獲利","業績","法說"],
    "外資":   ["外資買超","法人買超","外資大買","外資連買","外資持續買超","QFII"],
    # 非科技主題
    "降息":   ["Fed降息","降息","利率下降","rate cut","FOMC寬鬆","貨幣寬鬆","央行降息"],
    "升息":   ["升息","利率上升","rate hike","緊縮","FOMC升息"],
    "航運":   ["運費","貨櫃","航運景氣","SCFI","FBX","BDI","集運","缺艙","運力"],
    "生技":   ["FDA","新藥","藥證","臨床試驗","解盲","NDA","IND","藥品核准","解禁"],
    "綠能":   ["離岸風電","太陽能","儲能","綠能","再生能源","風電","淨零","碳中和","電動車","EV"],
    "原物料": ["鋼價","銅價","鐵礦石","原油","油價","鋼鐵漲","煤炭","原物料"],
    "建設":   ["房地產","房市","捷運","新青安","都更","危老重建","土地"],
    # 新增主題
    "玻纖布": ["玻纖布","Low Dk","CCL","銅箔基板","電子玻纖","glass fiber cloth","低損耗","PCB材料缺貨"],
    "無人機": ["無人機","UAV","drone","FPV","國防採購","特別預算","國機國造","軍購","蒼鷹","軍用無人機","無人機標案"],
    "石化回升":["台塑","南亞","台化","石化景氣","塑化景氣","乙烯","苯乙烯","PVC","石化轉盈","石化升評","塑化升評"],
    "載板漲價":["載板漲價","ABF缺貨","ABF基板","substrate price","载板供不應求","ABF shortage","載板報價"],
    "HBM":    ["HBM","HBM3E","High Bandwidth Memory","高頻寬記憶體","HBM供不應求"],
    "CPO":    ["CPO","共封裝光學","co-packaged optics","矽光子","silicon photonics","800G","1.6T光模組"],
    "液冷":   ["液冷","water cooling","浸沒式冷卻","冷卻板","liquid cooling","CDU","冷板式"],
    "月營收":  ["月營收","月銷售額","月業績","單月營收","營收年增","創歷史新高","創同期最高","創新高","逐月成長","月份業績","本月營收"],
    "投信買超":["投信買超","投信大買","投信持續買","國內投信","基金買超","投信連買","內資買超","投信法人"],
}

# 催化劑觸發的受益股票（科技 + 多元產業）
CATALYST_BENEFICIARIES = {
    # 科技
    "NVIDIA":  ["2330.TW","3711.TW","3037.TW","6669.TW","2382.TW","2308.TW","3044.TW","2327.TW","3533.TW","6488.TW",
                "4958.TW","3189.TW","3017.TW","3324.TW"],
    "AMD":     ["2330.TW","3711.TW","3037.TW","2376.TW","2357.TW"],
    "Apple":   ["2330.TW","4938.TW","2317.TW","3008.TW","3406.TW","2474.TW","3034.TW","2382.TW","2324.TW"],
    "AI":      ["2330.TW","2454.TW","6669.TW","2382.TW","2308.TW","8299.TW","3037.TW","3533.TW","6488.TW","5483.TW",
                "3661.TW","3443.TW","3017.TW","3324.TW","2345.TW","6138.TW","8046.TW","5289.TW"],
    "CoWoS":   ["2330.TW","3711.TW","3037.TW","3189.TW","8046.TW","6239.TW"],
    "記憶體":  ["2344.TW","2408.TW","8299.TW","6488.TW","6239.TW"],
    "漲價":    ["2330.TW","2454.TW","3008.TW","2344.TW","2408.TW","2002.TW","1301.TW","2327.TW","2492.TW",
                "3037.TW","8046.TW","1802.TW"],
    "訂單":    ["2330.TW","2454.TW","6669.TW","2382.TW","2317.TW","2603.TW","2609.TW"],
    # 非科技（新增）
    "降息":    ["2881.TW","2882.TW","2884.TW","2891.TW","2886.TW","2892.TW","2880.TW","2883.TW",
                "5522.TW","2542.TW","2504.TW"],
    "升息":    ["2412.TW","3045.TW","4904.TW","2881.TW","2882.TW"],
    "航運":    ["2603.TW","2609.TW","2615.TW","2610.TW","2618.TW"],
    "生技":    ["6446.TW","6472.TW","1789.TW","4171.TW"],
    "綠能":    ["1513.TW","1504.TW","1101.TW","2308.TW","3533.TW"],
    "原物料":  ["2002.TW","2015.TW","2023.TW","1301.TW","1303.TW","1326.TW"],
    "建設":    ["5522.TW","2542.TW","2504.TW","1102.TW","1101.TW"],
    # 新增主題受益股
    "玻纖布":  ["1802.TW","1815.TW","5475.TW","3037.TW","4958.TW","3044.TW","6213.TW"],
    "無人機":  ["8033.TW","2634.TW","2630.TW","5371.TW","5222.TW","6753.TW"],
    "石化回升":["1301.TW","1303.TW","1326.TW","2002.TW"],
    "載板漲價":["3037.TW","8046.TW","3189.TW","4958.TW"],
    "HBM":    ["2408.TW","2344.TW","6239.TW","6488.TW","2330.TW"],
    "CPO":    ["3363.TW","2345.TW"],
    "液冷":    ["3017.TW","3324.TW","6230.TW","2308.TW"],
    "月營收":  ["2330.TW","2454.TW","3661.TW","3443.TW","6669.TW","2382.TW","3037.TW","8046.TW",
                "2345.TW","3533.TW","3017.TW","3324.TW","6488.TW","2327.TW","3008.TW","1802.TW",
                "8299.TW","6239.TW","5289.TW","6138.TW"],
    "投信買超":["2330.TW","2454.TW","3661.TW","3443.TW","6669.TW","2382.TW","3037.TW","8046.TW",
                "1802.TW","3533.TW","2308.TW","2345.TW","8299.TW","6239.TW","3017.TW","3324.TW"],
}

# ── 動態查詢股票名稱快取（搜尋非宇宙內股票時由 TWSE live API 填入）───────────────
_TW_STOCK_NAMES: Dict[str, str] = {}

# ═══════════════════════════════════════════════════════════════════════════════
#  技術指標計算
# ═══════════════════════════════════════════════════════════════════════════════

def calc_rsi(close: pd.Series, period: int = 14) -> float:
    delta = close.diff()
    up   = delta.clip(lower=0)
    down = (-delta).clip(lower=0)
    avg_up   = up.ewm(alpha=1/period, min_periods=period).mean()
    avg_down = down.ewm(alpha=1/period, min_periods=period).mean()
    rs = avg_up / avg_down
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1]) if not rsi.empty else 50.0

def calc_macd(close: pd.Series) -> Tuple[float, float]:
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd  = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    hist   = macd - signal
    return float(hist.iloc[-1]) if not hist.empty else 0.0, float(hist.iloc[-2]) if len(hist) > 1 else 0.0

def calc_atr(df: pd.DataFrame, period: int = 14) -> float:
    high, low, close = df["High"], df["Low"], df["Close"]
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs()
    ], axis=1).max(axis=1)
    atr = tr.ewm(span=period, adjust=False).mean()
    return float(atr.iloc[-1]) if not atr.empty else 0.0

def volume_ratio(vol: pd.Series, period: int = 20) -> float:
    avg = vol.iloc[-period-1:-1].mean()
    if avg == 0 or np.isnan(avg):
        return 1.0
    return float(vol.iloc[-1] / avg)

def ma_score(close: pd.Series) -> int:
    """Price above MA5, MA20, MA60 → score 0-3"""
    score = 0
    last  = float(close.iloc[-1])
    for n in [5, 20, 60]:
        if len(close) >= n and last > float(close.rolling(n).mean().iloc[-1]):
            score += 1
    return score


def calc_ma_alignment(close: pd.Series) -> dict:
    """
    均線多頭/空頭排列分析（Weinstein Stage + Minervini SEPA MA200 criteria）
    Stage 2 (advancing): MA5 > MA20 > MA60, price > MA60, MA60 slope rising
    Stage 4 (declining): price < MA60, MA60 slope falling
    SEPA bonus: Minervini 5-criteria check adds +3 when MA200 confirms uptrend
    Returns: stage(1-4), label, bonus(-4 to +9), is_aligned(bool),
             ma5/ma20/ma60/ma150/ma200, sepa_count(0-5)
    """
    if len(close) < 65:
        return {"stage": 0, "label": "資料不足", "bonus": 0, "is_aligned": False,
                "ma5": 0.0, "ma20": 0.0, "ma60": 0.0, "ma150": None, "ma200": None,
                "sepa_count": 0}
    last   = float(close.iloc[-1])
    ma5    = float(close.rolling(5).mean().iloc[-1])
    ma20   = float(close.rolling(20).mean().iloc[-1])
    ma60   = float(close.rolling(60).mean().iloc[-1])
    ma60_4w_ago = float(close.rolling(60).mean().iloc[-21])
    ma60_rising = ma60 > ma60_4w_ago

    ma150 = float(close.rolling(150).mean().iloc[-1]) if len(close) >= 150 else None
    ma200 = float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else None
    ma200_1mo = float(close.rolling(200).mean().iloc[-21]) if len(close) >= 221 else None
    ma200_rising = (ma200 > ma200_1mo) if (ma200 is not None and ma200_1mo is not None) else None

    # Minervini SEPA: count criteria met (0-5)
    sepa_count = 0
    if ma200 is not None and last > ma200:    sepa_count += 1  # price > MA200
    if ma150 is not None and last > ma150:    sepa_count += 1  # price > MA150
    if ma150 is not None and ma200 is not None and ma150 > ma200: sepa_count += 1  # MA150 > MA200
    if ma200_rising is True:                  sepa_count += 1  # MA200 trending up
    if ma60_rising:                           sepa_count += 1  # MA60 trending up

    # Classify Weinstein stage
    if last > ma60 and ma5 > ma20 > ma60 and ma60_rising:
        stage, label, bonus = 2, "📈 多頭排列（Stage 2）", 6
        is_aligned = True
    elif last > ma20 and ma5 > ma20 and ma60_rising:
        stage, label, bonus = 2, "📈 均線偏多", 3
        is_aligned = True
    elif last > ma60 and not (ma5 > ma20) and not ma60_rising:
        stage, label, bonus = 3, "⚠️ 頭部整理（Stage 3）", -2
        is_aligned = False
    elif last < ma60 and not ma60_rising:
        stage, label, bonus = 4, "📉 空頭排列（Stage 4）", -4
        is_aligned = False
    else:
        stage, label, bonus = 1, "🔄 底部整理（Stage 1）", 0
        is_aligned = False

    # SEPA upgrade: Minervini full-criteria confirmation adds +3 on top of Weinstein Stage 2
    if is_aligned and sepa_count >= 4:
        bonus += 3
        label = label.replace("Stage 2", "Stage 2 ★SEPA")

    return {"stage": stage, "label": label, "bonus": bonus, "is_aligned": is_aligned,
            "ma5": round(ma5, 1), "ma20": round(ma20, 1), "ma60": round(ma60, 1),
            "ma150": round(ma150, 1) if ma150 else None,
            "ma200": round(ma200, 1) if ma200 else None,
            "sepa_count": sepa_count}


def calc_market_direction(taiex_close: Optional[pd.Series]) -> Dict:
    """
    CANSLIM M factor: O'Neil rule — 3 out of 4 stocks follow the general market.
    Penalty applied to ALL scores when TAIEX is in correction/bear market.

    Returns {"status": "bull"|"neutral"|"bear", "penalty": int, "label": str,
             "dist_days": int, "ma50": float, "ma200": float}
    """
    if taiex_close is None or len(taiex_close) < 22:
        return {"status": "neutral", "penalty": 0, "label": "", "dist_days": 0,
                "ma50": 0.0, "ma200": 0.0}
    close = taiex_close.dropna()
    last  = float(close.iloc[-1])
    ma20  = float(close.rolling(20).mean().iloc[-1])
    ma50  = float(close.rolling(min(50, len(close))).mean().iloc[-1])
    ma200 = float(close.rolling(min(200, len(close))).mean().iloc[-1])

    # Distribution days: high-volume down-days signal institutional selling
    dist_days = 0
    if len(close) >= 26:
        pct_chg   = close.pct_change()
        dist_days = int((pct_chg.iloc[-25:] < -0.015).sum())

    if last > ma50 and last > ma200 and ma50 > ma200:
        if dist_days >= 5:
            status, penalty = "neutral", -8
            label = f"大盤多頭但出貨壓力({dist_days}日) ⚠️"
        else:
            status, penalty = "bull", 0
            label = "大盤多頭 ✅"
    elif last < ma50 and last < ma200:
        status, penalty = "bear", -20
        label = "大盤空頭 — 慎買 ⛔"
    elif last < ma50:
        status, penalty = "neutral", -8
        label = "大盤修正中 ⚠️"
    else:
        status, penalty = "neutral", -5
        label = "大盤整理中"

    return {"status": status, "penalty": penalty, "label": label,
            "dist_days": dist_days,
            "ma50": round(ma50, 0), "ma200": round(ma200, 0)}


def calc_bollinger(close: pd.Series, period: int = 20, std_mult: float = 2.0) -> dict:
    """
    布林通道 (Bollinger Bands) — 進場時機偵測
    pct_b: 0=下軌, 1=上軌; <0.15=買入區, >0.85=超買區
    squeeze: 帶寬壓縮 → 即將爆發（Mark Minervini VCP 變形）
    """
    if len(close) < period:
        return {"pct_b": 0.5, "signal": "neutral", "squeeze": False,
                "upper": 0.0, "middle": 0.0, "lower": 0.0, "band_width": 0.0}
    ma  = close.rolling(period).mean()
    sd  = close.rolling(period).std(ddof=0)
    upper  = float((ma + std_mult * sd).iloc[-1])
    middle = float(ma.iloc[-1])
    lower  = float((ma - std_mult * sd).iloc[-1])
    last   = float(close.iloc[-1])
    bw     = (upper - lower) / middle if middle > 0 else 0.0
    pct_b  = (last - lower) / (upper - lower) if upper != lower else 0.5

    # Squeeze: current width < 60% of 50-day average width
    squeeze = False
    if len(close) >= 50:
        bw_hist = ((close.rolling(period).std(ddof=0) * 2 * std_mult)
                   / close.rolling(period).mean()).dropna()
        avg_bw  = float(bw_hist.iloc[-50:].mean())
        squeeze = bw < avg_bw * 0.60 if avg_bw > 0 else False

    if pct_b <= 0.15:
        signal = "buy_zone"      # 貼近下軌 → 超賣買入區
    elif pct_b >= 0.85 and bw > 0.04:
        signal = "overbought"    # 貼近上軌 + 帶寬擴張 → 超買
    elif squeeze and pct_b >= 0.5:
        signal = "breakout"      # 帶寬壓縮突破 → 爆發前
    elif squeeze:
        signal = "squeeze"       # 帶寬壓縮但方向未明
    else:
        signal = "neutral"

    return {"pct_b": round(pct_b, 3), "signal": signal, "squeeze": squeeze,
            "upper": round(upper, 1), "middle": round(middle, 1), "lower": round(lower, 1),
            "band_width": round(bw, 4)}


def calc_stochastic(df: pd.DataFrame, k_period: int = 9, d_period: int = 3) -> dict:
    """
    KD 隨機指標 (Stochastic Oscillator) — 台灣最常見進出場指標
    Golden cross oversold (<20) = 最強買入訊號
    Death cross overbought (>80) = 最強賣出訊號
    """
    if len(df) < k_period + d_period + 2:
        return {"K": 50.0, "D": 50.0, "signal": "neutral"}
    high  = df["High"]
    low   = df["Low"]
    close = df["Close"]
    ll    = low.rolling(k_period).min()
    hh    = high.rolling(k_period).max()
    denom = (hh - ll).replace(0, np.nan)
    raw_k = 100 * (close - ll) / denom
    K     = raw_k.ewm(span=d_period, adjust=False).mean()
    D     = K.ewm(span=d_period, adjust=False).mean()
    k_val  = float(K.iloc[-1]) if not K.empty and not np.isnan(K.iloc[-1]) else 50.0
    d_val  = float(D.iloc[-1]) if not D.empty and not np.isnan(D.iloc[-1]) else 50.0
    k_prev = float(K.iloc[-2]) if len(K) > 1 else k_val
    d_prev = float(D.iloc[-2]) if len(D) > 1 else d_val
    golden = k_prev <= d_prev and k_val > d_val
    death  = k_prev >= d_prev and k_val < d_val
    if   golden and k_val < 25:  signal = "golden_cross_oversold"   # 超賣黃金交叉 — 最強
    elif golden:                  signal = "golden_cross"             # 黃金交叉
    elif k_val < 20:              signal = "oversold"                 # 超賣
    elif death and k_val > 75:   signal = "death_cross_overbought"   # 超買死亡交叉
    elif death:                   signal = "death_cross"              # 死亡交叉
    elif k_val > 80:              signal = "overbought"               # 超買
    else:                         signal = "neutral"
    return {"K": round(k_val, 1), "D": round(d_val, 1), "signal": signal}


def calc_obv_trend(df: pd.DataFrame, period: int = 10) -> str:
    """
    OBV (On-Balance Volume) 量價背離偵測
    OBV 上升但價格橫盤 → 悄悄建倉（買入訊號）
    Returns: "rising" | "falling" | "diverge_up" | "flat"
    """
    if len(df) < period + 2:
        return "flat"
    close = df["Close"].values.astype(float)
    vol   = df["Volume"].values.astype(float)
    obv   = np.zeros(len(close))
    for i in range(1, len(close)):
        if close[i] > close[i-1]:   obv[i] = obv[i-1] + vol[i]
        elif close[i] < close[i-1]: obv[i] = obv[i-1] - vol[i]
        else:                        obv[i] = obv[i-1]
    obv_recent = obv[-period:]
    obv_slope  = float(np.polyfit(range(period), obv_recent, 1)[0])
    price_chg  = (close[-1] - close[-period]) / close[-period] * 100 if close[-period] > 0 else 0
    if obv_slope > 0 and price_chg <= 0.5:
        return "diverge_up"   # 量增但價不漲 → 悄悄建倉
    elif obv_slope > 0:
        return "rising"
    elif obv_slope < 0:
        return "falling"
    return "flat"


def calc_relative_strength(close: pd.Series, market_close: pd.Series) -> dict:
    """
    O'Neil CANSLIM 相對強度 (RS) — 個股 vs 台灣加權指數 (TAIEX)
    比較5日/20日報酬率差異：股票跑贏大盤 → 正RS，跑輸 → 負RS。

    O'Neil 研究：RS評級前20%的股票，比大盤報酬高出3-4倍。
    短線交易核心邏輯：選強不選弱，在同板塊內挑最強的那支。

    Returns: {"rs5d", "rs20d", "rs_composite", "bonus"(-6~+8), "label"}
    """
    if close is None or len(close) < 22:
        return {"rs5d": 0.0, "rs20d": 0.0, "rs_composite": 0.0, "bonus": 0, "label": ""}
    if market_close is None or len(market_close) < 22:
        return {"rs5d": 0.0, "rs20d": 0.0, "rs_composite": 0.0, "bonus": 0, "label": ""}

    def _pct(s: pd.Series, n: int) -> float:
        if len(s) > n and float(s.iloc[-n - 1]) > 0:
            return (float(s.iloc[-1]) / float(s.iloc[-n - 1]) - 1) * 100
        return 0.0

    stock_5d   = _pct(close, 5)
    market_5d  = _pct(market_close, 5)
    stock_20d  = _pct(close, 20)
    market_20d = _pct(market_close, 20)

    rs5d  = stock_5d  - market_5d    # +% = outperforming market over 5 days
    rs20d = stock_20d - market_20d   # +% = outperforming market over 20 days

    # 20日主導（中期趨勢），5日給近期動能加權
    rs_composite = rs20d * 0.65 + rs5d * 0.35

    if   rs_composite >= 15: bonus, label = 8, "💪 大幅跑贏大盤 (RS強)"
    elif rs_composite >= 8:  bonus, label = 5, "📈 跑贏大盤"
    elif rs_composite >= 3:  bonus, label = 2, "↗️ 微幅跑贏大盤"
    elif rs_composite >= -3: bonus, label = 0, ""
    elif rs_composite >= -8: bonus, label = -3, "📉 弱於大盤"
    else:                    bonus, label = -6, "⬇️ 嚴重落後大盤"

    return {"rs5d": round(rs5d, 1), "rs20d": round(rs20d, 1),
            "rs_composite": round(rs_composite, 1), "bonus": bonus, "label": label}


def calc_52w_position(close: pd.Series) -> dict:
    """
    Mark Minervini SEPA: 52週位置分析
    理想進場：距52週低點 >30%（已離底）、距52週高點 <25%（靠近突破區）
    """
    if len(close) < 52:
        return {"position_pct": 50.0, "label": "資料不足", "bonus": 0}
    w52_high = float(close.iloc[-252:].max()) if len(close) >= 252 else float(close.max())
    w52_low  = float(close.iloc[-252:].min()) if len(close) >= 252 else float(close.min())
    last     = float(close.iloc[-1])
    rng      = w52_high - w52_low
    pos_pct  = (last - w52_low) / rng * 100 if rng > 0 else 50.0

    from_low  = (last - w52_low)  / w52_low  * 100 if w52_low > 0 else 0
    from_high = (w52_high - last) / w52_high * 100 if w52_high > 0 else 0

    # Minervini sweet spot: 30-75% of 52w range
    if pos_pct >= 98:
        # Price AT or ABOVE 52-week high: highest-probability breakout setup (O'Neil Stage 2 breakout)
        bonus, label = 8, "🚀 突破52週新高！"
    elif 30 <= pos_pct <= 75 and from_low >= 25:
        bonus, label = 4, "✨ 52週甜蜜區間"
    elif pos_pct > 75 and from_high < 10:
        bonus, label = 2, "🚀 靠近52週高點（突破前）"
    elif pos_pct < 20:
        bonus, label = -3, "⬇️ 靠近52週低點（下跌趨勢中）"
    else:
        bonus, label = 0, ""
    return {"position_pct": round(pos_pct, 1), "label": label, "bonus": bonus,
            "w52_high": round(w52_high, 1), "w52_low": round(w52_low, 1)}


def detect_52w_breakout(df: pd.DataFrame) -> Dict:
    """
    O'Neil 突破進場訊號：52週新高突破 + 成交量確認
    - 確認突破 (Volume ≥ 1.4x MA20): +15 ← O'Neil #1 買點
    - 新高但量不足:                   +8
    - 距年高 3%以內:                  +6
    - 距年高 7%以內:                  +3
    - 底部25%以下:                   -6 (避免接刀)
    """
    if df is None or len(df) < 22:
        return {"score": 0, "type": "none", "label": "",
                "pct_vs_high": 0.0, "vol_surge": 1.0}

    close  = df["Close"]
    volume = df["Volume"]
    n      = len(close)

    # Prior 52w high (exclude last 5 days to detect fresh breakouts)
    lookback   = min(252, n)
    prior_slice = close.iloc[-lookback:-5] if n > 5 else close.iloc[-lookback:]
    prior_high  = float(prior_slice.max()) if len(prior_slice) > 0 else float(close.max())
    low52w      = float(close.iloc[-lookback:].min())

    last       = float(close.iloc[-1])
    vol_ma20   = float(volume.rolling(20).mean().iloc[-1])
    vol_latest = float(volume.iloc[-1])
    vol_surge  = vol_latest / vol_ma20 if vol_ma20 > 0 else 1.0

    if prior_high <= 0:
        return {"score": 0, "type": "none", "label": "", "pct_vs_high": 0.0, "vol_surge": round(vol_surge, 2)}

    pct_vs_high  = (last / prior_high - 1) * 100
    pct_above_low = (last - low52w) / (prior_high - low52w) if prior_high != low52w else 0.5

    if pct_vs_high >= 0:
        if vol_surge >= 1.4:
            score, btype = 15, "breakout"
            label = f"突破52週新高 📈 量{vol_surge:.1f}x"
        else:
            score, btype = 8, "near_high"
            label = f"新52週高（量{vol_surge:.1f}x 待放量）"
    elif pct_vs_high >= -3:
        score, btype = 6, "near_high"
        label = f"逼近年高 -{abs(pct_vs_high):.1f}%"
    elif pct_vs_high >= -7:
        score, btype = 3, "none"
        label = ""
    elif pct_above_low < 0.25:
        score, btype = -6, "none"
        label = "52週低位 ⚠️"
    else:
        score, btype = 0, "none"
        label = ""

    return {"score": score, "type": btype, "label": label,
            "pct_vs_high": round(pct_vs_high, 1),
            "prior_high52w": round(prior_high, 1),
            "vol_surge": round(vol_surge, 2)}


def calc_kbar_pattern(df: pd.DataFrame) -> Tuple[int, str]:
    """
    K線形態識別（台灣慣例：陽線=紅/上漲，陰線=綠/下跌）
    Returns (score 0-12, pattern_name)

    形態優先級（由強到弱）：
    1. 早晨之星 / 曙光初現  (+10) — 底部翻轉最強信號
    2. 看漲吞噬 / 穿頭破腳  (+9)  — 強力翻轉信號
    3. 三白兵 / 連三陽      (+8)  — 多頭確認
    4. 鎚子線 / 倒鎚        (+7)  — 底部反彈信號
    5. 孕線多頭              (+5)  — 盤整後轉強
    6. 量增價漲陽線          (+4)  — 動量延續
    7. 無明確形態            (+0)
    形態虧空（空頭形態 → 扣分）：
    8. 流星線 / 上吊線       (-4)  — 頭部警告
    9. 看跌吞噬              (-6)  — 強力翻轉空頭
    """
    if len(df) < 5:
        return 0, "無資料"

    o  = df["Open"].values.astype(float)
    h  = df["High"].values.astype(float)
    l  = df["Low"].values.astype(float)
    c  = df["Close"].values.astype(float)
    v  = df["Volume"].values.astype(float)
    n  = len(df)

    # Latest and prior candles (index -1 = today, -2 = yesterday, -3 = 前天)
    c0, o0, h0, l0, v0 = c[-1], o[-1], h[-1], l[-1], v[-1]
    c1, o1, h1, l1     = c[-2], o[-2], h[-2], l[-2]
    c2, o2, h2, l2     = (c[-3], o[-3], h[-3], l[-3]) if n >= 3 else (c1, o1, h1, l1)

    body0   = abs(c0 - o0)
    range0  = h0 - l0 if h0 > l0 else 1e-6
    lower0  = min(c0, o0) - l0
    upper0  = h0 - max(c0, o0)
    body1   = abs(c1 - o1)
    range1  = h1 - l1 if h1 > l1 else 1e-6

    bull0   = c0 > o0   # today bullish (陽線)
    bear0   = c0 < o0   # today bearish (陰線)
    bull1   = c1 > o1   # yesterday bullish
    bear1   = c1 < o1   # yesterday bearish
    bear2   = c2 < o2   # day-before bearish

    avg_v20 = float(np.mean(v[-21:-1])) if n >= 21 else float(np.mean(v[:-1])) if n > 1 else v0

    # ── 1. 早晨之星 (Morning Star) ──────────────────────────────────────────
    # Day1: 長陰線, Day2: 小實體, Day3: 陽線收回Day1上半部
    if n >= 3:
        small_body1 = body1 < range1 * 0.35
        if bear2 and (c2 - o2) > range1 * 1.2 and small_body1 and bull0 and c0 > (o2 + c2) / 2:
            return 10, "🌅 早晨之星（底部翻轉）"

    # ── 2. 看漲吞噬 (Bullish Engulfing) ───────────────────────────────────
    if bear1 and bull0 and o0 <= c1 and c0 >= o1 and body0 > body1 * 1.0:
        return 9, "🕯️ 看漲吞噬（多頭翻轉）"

    # ── 3. 三白兵 (Three White Soldiers) ──────────────────────────────────
    if n >= 3 and bull0 and bull1 and (c2 > o2) and c0 > c1 > c2 and o0 > o1 > o2:
        return 8, "🚀 連三陽（多頭確認）"

    # ── 4. 鎚子線 (Hammer) ────────────────────────────────────────────────
    # 小實體, 長下影線 > 2倍實體, 上影線短
    if body0 < range0 * 0.35 and lower0 > body0 * 2.0 and upper0 < range0 * 0.15:
        # Only bullish if at a potential bottom (5-day low area)
        if l0 <= float(np.min(l[-6:-1])) * 1.02:
            return 7, "🔨 鎚子線（底部反彈）"

    # ── 5. 孕線多頭 (Bullish Harami) ──────────────────────────────────────
    if bear1 and bull0 and o0 >= c1 and c0 <= o1 and body1 > 0 and body0 < body1 * 0.5:
        return 5, "🤰 多頭孕線（盤整轉強）"

    # ── 6. 量增價漲陽線 (Volume Surge + Bullish) ──────────────────────────
    if bull0 and v0 > avg_v20 * 1.5 and body0 > range0 * 0.5:
        return 4, "📊 量增價漲（動量延續）"

    # ── 空頭形態 (Bearish) ────────────────────────────────────────────────

    # 看跌吞噬 (Bearish Engulfing)
    if bull1 and bear0 and o0 >= c1 and c0 <= o1 and body0 > body1:
        return -6, "⚠️ 看跌吞噬（空頭翻轉）"

    # 流星線 / 上吊線 (Shooting Star / Hanging Man)
    if body0 < range0 * 0.35 and upper0 > body0 * 2.0 and lower0 < range0 * 0.15:
        if h0 >= float(np.max(h[-6:-1])) * 0.98:
            return -4, "🌠 流星線（頭部警告）"

    # 無特定形態
    if bull0:
        return 2, "陽線（無特定形態）"
    elif bear0:
        return -1, "陰線（無特定形態）"
    return 0, "十字線"


def calc_support_resistance(df: pd.DataFrame) -> dict:
    """
    支撐與壓力區計算
    1. 標準樞紐點（Pivot Points）：前日 H/L/C → PP, R1~R3, S1~S3
    2. 近20日擺動高低（Swing High/Low）
    3. 費波那契回撤（52週高低區間）
    """
    empty = {"pivot": 0.0, "R1": 0.0, "R2": 0.0, "R3": 0.0,
             "S1": 0.0, "S2": 0.0, "S3": 0.0,
             "fib_618": 0.0, "fib_50": 0.0, "fib_382": 0.0,
             "swing_high_20d": 0.0, "swing_low_20d": 0.0}
    if len(df) < 20:
        return empty

    prev_h = float(df["High"].iloc[-2])
    prev_l = float(df["Low"].iloc[-2])
    prev_c = float(df["Close"].iloc[-2])
    if prev_h == 0:
        return empty

    pivot = (prev_h + prev_l + prev_c) / 3
    r1 = 2 * pivot - prev_l
    r2 = pivot + (prev_h - prev_l)
    r3 = prev_h + 2 * (pivot - prev_l)
    s1 = 2 * pivot - prev_h
    s2 = pivot - (prev_h - prev_l)
    s3 = prev_l - 2 * (prev_h - pivot)

    n52 = min(252, len(df))
    high_52 = float(df["High"].tail(n52).max())
    low_52  = float(df["Low"].tail(n52).min())
    fib_rng = high_52 - low_52
    fib_618 = high_52 - fib_rng * 0.618
    fib_50  = high_52 - fib_rng * 0.500
    fib_382 = high_52 - fib_rng * 0.382

    swing_h = float(df["High"].tail(20).max())
    swing_l = float(df["Low"].tail(20).min())

    return {
        "pivot":         round(pivot, 1),
        "R1":            round(r1, 1),
        "R2":            round(r2, 1),
        "R3":            round(r3, 1),
        "S1":            round(s1, 1),
        "S2":            round(s2, 1),
        "S3":            round(s3, 1),
        "fib_618":       round(fib_618, 1),
        "fib_50":        round(fib_50, 1),
        "fib_382":       round(fib_382, 1),
        "swing_high_20d": round(swing_h, 1),
        "swing_low_20d":  round(swing_l, 1),
    }


def calc_trading_signal(sres: dict) -> dict:
    """
    綜合買進/持有/賣出訊號
    聚合：信心指數、RSI、KD、布林通道、Weinstein Stage、OBV、突破
    回傳：signal(BUY/HOLD/SELL), confidence(0-100), reasons(list)
    """
    score   = sres.get("score", 0)
    rsi     = sres.get("rsi", 50)
    kd_sig  = sres.get("kd_signal", "neutral")
    bb_sig  = sres.get("bb_signal", "neutral")
    bb_sq   = sres.get("bb_squeeze", False)
    stage   = sres.get("stage", 1)
    obv     = sres.get("obv_trend", "flat")
    bo_type = sres.get("bo_type", "none")
    sepa    = sres.get("sepa_count", 0)
    mom20d  = sres.get("mom20d", 0)
    fi_stk  = sres.get("trust_bonus", 0)   # 投信連買最強信號

    buy_cnt = 0
    sell_cnt = 0
    reasons: List[str] = []

    # ── 信心指數 ─────────────────────────────────────────────────────────────
    if score >= 78:
        buy_cnt += 2;  reasons.append(f"信心指數 {score}/100 強勢")
    elif score >= 62:
        buy_cnt += 1;  reasons.append(f"信心指數 {score}/100 偏多")
    elif score < 45:
        sell_cnt += 2; reasons.append(f"信心指數 {score}/100 偏弱")

    # ── RSI ─────────────────────────────────────────────────────────────────
    if 40 <= rsi <= 68:
        buy_cnt += 1;  reasons.append(f"RSI {rsi:.0f} 甜蜜進場區")
    elif rsi >= 78:
        sell_cnt += 2; reasons.append(f"RSI {rsi:.0f} 嚴重超買")
    elif rsi >= 72:
        sell_cnt += 1; reasons.append(f"RSI {rsi:.0f} 偏熱追高風險")
    elif rsi <= 30:
        sell_cnt += 1; reasons.append(f"RSI {rsi:.0f} 超賣仍在下跌")

    # ── KD ──────────────────────────────────────────────────────────────────
    if kd_sig == "golden_cross_oversold":
        buy_cnt += 2;  reasons.append("KD 超賣黃金交叉（最強買點）")
    elif kd_sig == "golden_cross":
        buy_cnt += 1;  reasons.append("KD 黃金交叉")
    elif kd_sig == "death_cross_overbought":
        sell_cnt += 2; reasons.append("KD 超買死亡交叉（最強賣點）")
    elif kd_sig == "death_cross":
        sell_cnt += 1; reasons.append("KD 死亡交叉")

    # ── 布林通道 ─────────────────────────────────────────────────────────────
    if bb_sig == "buy_zone":
        buy_cnt += 1;  reasons.append("布林下軌買入區")
    elif bb_sig in ("breakout",) or bb_sq:
        buy_cnt += 1;  reasons.append("布林帶壓縮突破")
    elif bb_sig == "overbought":
        sell_cnt += 1; reasons.append("布林上軌超買")

    # ── Weinstein Stage ──────────────────────────────────────────────────────
    if stage == 2:
        buy_cnt += 1;  reasons.append("Stage 2 多頭排列")
    elif stage == 4:
        sell_cnt += 2; reasons.append("Stage 4 空頭排列")

    # ── 52週突破 ─────────────────────────────────────────────────────────────
    if bo_type in ("confirmed", "near"):
        buy_cnt += 2;  reasons.append("52週高點突破確認")

    # ── OBV 量價 ─────────────────────────────────────────────────────────────
    if obv == "diverge_up":
        buy_cnt += 1;  reasons.append("OBV 量增機構悄悄吸貨")
    elif obv == "falling":
        sell_cnt += 1; reasons.append("OBV 量縮機構出清")

    # ── 投信連買 ─────────────────────────────────────────────────────────────
    if fi_stk >= 5:
        buy_cnt += 1;  reasons.append("投信連買 5+ 天")

    # ── 判斷訊號 ─────────────────────────────────────────────────────────────
    net = buy_cnt - sell_cnt
    if buy_cnt >= 5 or (net >= 3 and score >= 62):
        signal = "BUY"
        confidence = min(95, 55 + buy_cnt * 7)
    elif sell_cnt >= 4 or (net <= -3 and score < 52):
        signal = "SELL"
        confidence = min(92, 55 + sell_cnt * 7)
    else:
        signal = "HOLD"
        confidence = 45 + abs(net) * 5

    return {
        "signal":     signal,
        "confidence": int(confidence),
        "buy_cnt":    buy_cnt,
        "sell_cnt":   sell_cnt,
        "reasons":    reasons[:5],
    }


def calc_strategy_stats(df: pd.DataFrame, hold_days: int = 5) -> dict:
    """
    策略回測統計（向量化，快速）
    訊號：RSI 40-70 且 MACD 柱線正 且 收盤 > MA20
    正向回報：hold_days 後收盤價 > 進場價
    回傳：win_rate(%), profit_factor, max_drawdown(%), total_trades
    """
    empty = {"win_rate": 0.0, "profit_factor": 0.0,
             "max_drawdown": 0.0, "total_trades": 0}
    if len(df) < 50:
        return empty

    close = df["Close"].astype(float)
    high  = df["High"].astype(float)

    # 向量化指標
    delta    = close.diff()
    up_s     = delta.clip(lower=0).ewm(alpha=1/14, min_periods=14).mean()
    dn_s     = (-delta).clip(lower=0).ewm(alpha=1/14, min_periods=14).mean()
    rsi_s    = 100 - 100 / (1 + up_s / dn_s.replace(0, 1e-10))
    ema12    = close.ewm(span=12, adjust=False).mean()
    ema26    = close.ewm(span=26, adjust=False).mean()
    macd_h   = (ema12 - ema26) - (ema12 - ema26).ewm(span=9, adjust=False).mean()
    ma20     = close.rolling(20).mean()

    # 訊號：RSI 40-70, MACD > 0, 收盤 > MA20（無訊號重疊：取第一根）
    raw_sig  = rsi_s.between(40, 70) & (macd_h > 0) & (close > ma20)
    # 避免連續訊號重疊（keep only new entries after hold_days gap）
    entries  = raw_sig & ~raw_sig.shift(1, fill_value=False)

    fwd_ret  = close.shift(-hold_days) / close - 1
    ret_vals = fwd_ret[entries].dropna()
    if len(ret_vals) < 3:
        return empty

    wins   = ret_vals[ret_vals > 0]
    losses = ret_vals[ret_vals <= 0]
    win_rate = len(wins) / len(ret_vals)

    avg_win  = float(wins.mean())          if len(wins)   > 0 else 0.0
    avg_loss = abs(float(losses.mean()))   if len(losses) > 0 else 1e-6
    n_win    = len(wins)
    n_loss   = len(losses)
    pf       = (avg_win * n_win) / (avg_loss * n_loss + 1e-10) if n_loss > 0 else min(avg_win * n_win / 1e-4, 9.99)

    eq   = (1 + ret_vals.clip(lower=-0.15)).cumprod()
    peak = eq.cummax()
    dd   = float(((peak - eq) / peak).max())

    return {
        "win_rate":      round(win_rate * 100, 1),
        "profit_factor": round(min(float(pf), 9.99), 2),
        "max_drawdown":  round(dd * 100, 1),
        "total_trades":  int(len(ret_vals)),
    }


def build_trading_plan(sres: dict, sr: dict) -> dict:
    """
    四階段交易計劃
    ① 盤前掃描  ② 開牌策略  ③ 盤中調整  ④ 收盤策略
    """
    last   = sres.get("last_price", 0.0)
    atr    = sres.get("atr", last * 0.02) or last * 0.02
    score  = sres.get("score", 50)
    rsi    = sres.get("rsi", 50)
    stage  = sres.get("stage", 1)
    ma5    = sres.get("ma5", last)
    ma20   = sres.get("ma20", last)
    ma60   = sres.get("ma60", last)
    target = sres.get("target_price", round(last * 1.05, 1))
    stop   = sres.get("stop_loss", round(last - 1.5 * atr, 1))
    tgt_pct= sres.get("target_pct", 5.0)
    mom1d  = sres.get("mom1d", 0.0)
    vr     = sres.get("vol_ratio", 1.0)
    bo_type= sres.get("bo_type", "none")
    kd_sig = sres.get("kd_signal", "neutral")
    s1     = sr.get("S1", round(last * 0.98, 1))
    s2     = sr.get("S2", round(last * 0.96, 1))
    r1     = sr.get("R1", round(last * 1.02, 1))
    r2     = sr.get("R2", round(last * 1.04, 1))
    fib50  = sr.get("fib_50", round(last * 0.98, 1))
    pivot  = sr.get("pivot", last)

    # ① 盤前掃描
    pre_parts = []
    if mom1d >= 4:
        pre_parts.append(f"昨日強漲 {mom1d:.1f}%，今日注意高開追價風險——RSI 偏熱時不追")
    elif mom1d <= -4:
        pre_parts.append(f"昨日大跌 {abs(mom1d):.1f}%，低開可能測試支撐 S1=NT${s1}，跌破勿接")
    else:
        pre_parts.append(f"盤前無重大跳空，重點觀察大盤指數方向與美股盤後訊號")
    pre_parts.append(f"壓力區：R1 NT${r1}、R2 NT${r2}　支撐區：S1 NT${s1}、S2 NT${s2}")
    if vr >= 1.5:
        pre_parts.append(f"量比 {vr:.1f}x 明顯放大，留意是否有法人佈局動作")
    if bo_type in ("confirmed", "near"):
        pre_parts.append("52週高點突破訊號，留意今日能否放量站穩")
    pre_market = "　".join(pre_parts)

    # ② 開牌策略
    if mom1d >= 3:
        if score >= 70:
            opening = (f"高開強勢：開盤前5分K若站穩 NT${pivot:.1f}（樞紐點）且量能 > 均量1.2x，"
                       f"可分兩批進場（各五成），第一目標 NT${r1}，達標後看 R2 NT${r2}")
        else:
            opening = (f"高開但信心指數僅 {score}，等開盤後第一根15分K收紅確認再進；"
                       f"站穩 NT${ma5:.1f}（MA5）為進場條件，破則不進")
    elif mom1d <= -3:
        opening = (f"低開觀察：先等股價在 NT${s1}（S1）附近止穩，出現紅K且量能回升才考慮進場；"
                   f"若開盤即跌破 S2 NT${s2}，當日不進場")
    else:
        opening = (f"平開策略：開盤5分鐘若收盤 > NT${ma5:.1f}（MA5）且量比 > 1.0x，"
                   f"可小量試探；止損設在 NT${stop:.1f}（−1.5×ATR）")

    # ③ 盤中調整
    if stage == 2 and rsi < 65:
        intraday = (f"多頭排列（Stage 2）——回調至 MA20（NT${ma20:.1f}）附近，"
                    f"若 KD 未死叉可加碼；Fib 50% 支撐 NT${fib50} 為強支撐，跌破才停損")
    elif score >= 75:
        intraday = (f"高分強勢：盤中回測 NT${pivot:.1f}（樞紐點）可持倉，"
                    f"量能萎縮至均量 0.8x 以下時減半；上漲超過 {tgt_pct:.0f}% 考慮分批了結")
    elif kd_sig in ("death_cross", "death_cross_overbought"):
        intraday = (f"KD 死叉警示：建議盤中減倉至三成，"
                    f"等 KD K值 < 30 再考慮重新佈局；持倉止損收緊至 NT${round(last - atr, 1)}")
    else:
        intraday = (f"中性觀察：股價守住 MA20（NT${ma20:.1f}）可持倉，"
                    f"若量縮於均量 0.7x 以下則減碼，等量能回升再加")

    # ④ 收盤策略
    if score >= 80 and rsi < 70:
        closing = (f"強勢可隔夜：目標 NT${target:.1f}（+{tgt_pct:.0f}%）未達前持倉，"
                   f"止損 NT${stop:.1f}（跌破 ATR 1.5倍出場）")
    elif rsi >= 72:
        closing = (f"RSI {rsi:.0f} 偏熱：收盤前先出一半獲利，"
                   f"隔日若 RSI 回落至 65 以下且價格未破 MA20，可再考慮佈局")
    elif stage == 4:
        closing = "Stage 4 空頭：當日收盤無論如何出清，不留隔夜風險"
    else:
        closing = (f"標準收盤：收盤前確認仍站上 MA20（NT${ma20:.1f}），"
                   f"若破則出清；達目標價 NT${target:.1f} 了結至少五成")

    return {
        "pre_market": pre_market,
        "opening":    opening,
        "intraday":   intraday,
        "closing":    closing,
    }


def build_longterm_plan(sres: dict, sr: dict) -> dict:
    """
    長期持有（5-10年）四階段計劃，適合零股小資戶分批建倉
    ① 建倉前評估  ② 零股建倉策略  ③ 持倉管理  ④ 停利/停損準則
    與 build_trading_plan 的短線版本不同：以月/季為單位，強調複利累積
    """
    last   = sres.get("last_price", 0.0)
    atr    = sres.get("atr", last * 0.02) or last * 0.02
    score  = sres.get("score", 50)
    rsi    = sres.get("rsi", 50)
    stage  = sres.get("stage", 1)
    ma20   = sres.get("ma20", last)
    ma60   = sres.get("ma60", last)
    ma200  = sres.get("ma200")
    sepa   = sres.get("sepa_count", 0)
    mom20d = sres.get("mom20d", 0)
    vr     = sres.get("vol_ratio", 1.0)
    bo_type= sres.get("bo_type", "none")
    s1     = sr.get("S1", round(last * 0.97, 1))
    s2     = sr.get("S2", round(last * 0.94, 1))
    r1     = sr.get("R1", round(last * 1.03, 1))
    fib618 = sr.get("fib_618", round(last * 0.95, 1))
    fib50  = sr.get("fib_50",  round(last * 0.97, 1))
    pivot  = sr.get("pivot", last)

    # ① 建倉前評估
    if stage == 4:
        assess = (f"⛔ 空頭排列（Stage 4）——目前不宜建倉，等股價站回 MA60（NT${ma60:.1f}）且趨勢轉平，"
                  f"才是長期佈局開始的訊號。急著在下跌趨勢中買進，複利起點會虧損。")
    elif stage == 2 and sepa >= 4:
        assess = (f"✅ 多頭強勢（Stage 2 + SEPA {sepa}/5）——現在是理想的長期建倉視窗。"
                  f"MA200={f'NT${ma200:.1f}' if ma200 else '—'}，股價站穩均線之上，趨勢確立。"
                  f"可啟動零股月定投。")
    elif stage in (1, 2):
        assess = (f"🟡 偏多整理中（Stage {stage}）——基本面進入觀察期，可小量試探建倉。"
                  f"建議先買目標倉位的 20-30%，等 MA20 站穩後再加碼。")
    else:
        assess = (f"⚠️ 趨勢不明確——建議先觀察 1-2 個月。"
                  f"等均線多頭排列（MA5>MA20>MA60）才正式啟動建倉計劃。")

    # ② 零股建倉策略
    shares_10k = int(10000 / last) if last > 0 else 0
    shares_10k_str = f"約 {shares_10k} 股" if shares_10k > 0 else "股價過高，考慮更小單位"
    if rsi <= 55 and stage in (1, 2):
        accumulate = (f"現在可開始第一批零股：每月 NT$3,000-5,000 分批買入（NT$10,000 可買 {shares_10k_str}）。"
                      f"逢回測 Fib 61.8%（NT${fib618}）或 S1（NT${s1}）可加碼 1-2 倍月定投量。"
                      f"目標：6 個月內建立完整倉位。")
    elif rsi >= 70:
        accumulate = (f"RSI {rsi:.0f} 偏熱，短期追高風險高。建議暫緩首批，等回落至 RSI<60 再啟動。"
                      f"若已持有，維持現有倉位即可，暫停加碼。"
                      f"回測 NT${fib50}（Fib 50%）或 MA20（NT${ma20:.1f}）後再啟動定投。")
    else:
        accumulate = (f"可小量起步（每月 NT$2,000-3,000 定投）：NT$10,000 可買 {shares_10k_str}。"
                      f"在 S1（NT${s1}）到 S2（NT${s2}）之間逢低加大買入量，高過 R1（NT${r1}）時"
                      f"暫緩加碼。以季度（每3個月）回顧一次佈局進度。")

    # ③ 持倉管理
    if ma200 and last > ma200:
        hold_mgmt = (f"股價站穩 MA200（NT${ma200:.1f}）之上——多頭確認，持倉不動。"
                     f"每季檢視：若連續3個月月營收 YoY 轉負或外資連續賣超 10 日，考慮減倉 1/3。"
                     f"否則讓複利自行運作，不因短期波動操作。")
    elif stage == 2:
        hold_mgmt = (f"多頭排列中，持倉策略：跌破 MA60（NT${ma60:.1f}）以上可加碼，"
                     f"跌破 MA60 超過 5% 暫停加碼，等趨勢確認後再恢復定投。"
                     f"持有期間每季確認一次基本面（EPS 成長、本業獲利）是否如預期。")
    else:
        hold_mgmt = (f"持倉管理原則：以 MA20（NT${ma20:.1f}）為分界線，站上持有，跌破暫停定投。"
                     f"每月第一個週一檢視一次：確認 RSI 沒有連續 2 個月 < 35（系統性風險訊號）。"
                     f"每半年重新評估公司基本面與行業地位。")

    # ④ 停利/停損準則
    stop_lt = round(last * 0.85, 1)   # 15% from current for long-term
    target_3y = round(last * 2.0, 1)  # 100% 3-year target as rough benchmark
    if score >= 75:
        exit_rules = (f"停利：達 +50%（NT${round(last*1.5,1)}）賣出 1/3，達 +100%（NT${target_3y}）再賣 1/3，"
                      f"剩餘長期持有。停損：若基本面惡化（連續兩季 EPS 大幅下滑）"
                      f"+ 股價跌破 MA200 後 2 週未回，才考慮全面出場。"
                      f"技術止損線：NT${stop_lt}（−15%）。")
    else:
        exit_rules = (f"停利：達 +30%（NT${round(last*1.3,1)}）先出一半，等基本面確認後再決定其餘。"
                      f"停損：跌破買入均價 15%（NT${stop_lt}），或基本面出現重大惡化時出場。"
                      f"長期標的最忌頻繁進出——除非基本面故事改變，否則以持有為主。")

    return {
        "pre_market": assess,
        "opening":    accumulate,
        "intraday":   hold_mgmt,
        "closing":    exit_rules,
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  新聞抓取
# ═══════════════════════════════════════════════════════════════════════════════

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    "Accept": "application/json, text/html, */*",
}

# ═══════════════════════════════════════════════════════════════════════════════
#  早盤情報：訂單/合作/認證/外資動向 關鍵字庫
# ═══════════════════════════════════════════════════════════════════════════════

# 訂單/合作/認證 偵測關鍵字（越靠前優先級越高）
ORDER_SIGNAL_KW: List[Tuple[str, int]] = [
    # 直接訂單 (強度15)
    ("接獲訂單", 15), ("獲得訂單", 15), ("重大訂單", 15), ("大訂單", 14),
    ("長期合約", 14), ("年度訂單", 14), ("框架協議", 13), ("採購合約", 13),
    ("供應合約", 13), ("purchase order", 13), ("supply agreement", 13),
    ("multi-year contract", 13), ("bulk order", 12), ("大單", 12),
    ("訂單滿載", 12), ("訂單能見度", 11), ("order backlog", 11),
    # 合作/聯盟 (強度12)
    ("策略合作", 12), ("策略聯盟", 12), ("簽署MOU", 12), ("合作備忘錄", 12),
    ("合資協議", 12), ("共同開發", 11), ("技術授權", 11), ("授權協議", 11),
    ("合作協議", 11), ("partnership", 10), ("joint venture", 11),
    ("licensing agreement", 11), ("結盟", 10), ("合作案", 9),
    # 認證/入選 (強度10)
    ("通過認證", 10), ("獲得認證", 10), ("列入供應鏈", 10), ("入選供應商", 10),
    ("獨家供應", 12), ("首選供應商", 10), ("認可供應商", 10),
    ("certified supplier", 10), ("supply chain entry", 10), ("認證通過", 10),
    # 法人升評 (強度8)
    ("目標價調升", 8), ("上調目標", 8), ("外資升評", 9), ("升至買進", 9),
    ("price target raised", 8), ("outperform", 7), ("overweight", 7),
    ("外資大買", 10), ("外資連買", 10), ("外資大幅買超", 11),
    # 接單相關
    ("接單", 8), ("拿到", 7), ("獲選", 9), ("優先供應商", 10),
]

# 重磅合作對象（出現這些名字 → 新聞重要性倍增）
BIG_PARTNER_NAMES: List[Tuple[str, int]] = [
    ("NVIDIA", 15), ("輝達", 15), ("Apple", 15), ("蘋果", 15),
    ("Microsoft", 13), ("微軟", 13), ("Google", 13), ("Alphabet", 13),
    ("Amazon", 13), ("亞馬遜", 13), ("Meta", 12), ("Tesla", 12), ("特斯拉", 12),
    ("Intel", 11), ("英特爾", 11), ("AMD", 11), ("超微", 11),
    ("Qualcomm", 11), ("高通", 11), ("Samsung", 10), ("三星", 10),
    ("SK Hynix", 10), ("SK海力士", 10), ("Micron", 10), ("美光", 10),
    ("台積電", 10), ("TSMC", 10), ("ASML", 11), ("Broadcom", 10), ("博通", 10),
    ("SpaceX", 11), ("Boeing", 10), ("波音", 10), ("洛馬", 10), ("漢威", 9),
    ("AWS", 12), ("Azure", 11), ("GCP", 11), ("Snowflake", 9),
    ("OpenAI", 12), ("Anthropic", 11), ("xAI", 10),
]

# 金額規模表 (偵測文字中的數字+單位 → 估計訂單大小)
MAGNITUDE_TABLE: List[Tuple[str, str, str]] = [
    ("千億", "NT$1,000億+", "🚀超重磅"),
    ("百億", "NT$100億+",  "🔥重磅"),
    ("十億", "NT$10億+",   "⚡大單"),
    ("億",   "NT$1億+",    "📈"),
    ("千萬", "NT$千萬",    "📊"),
]


def fetch_technews_rss() -> List[Dict]:
    """科技新報 RSS — 台灣科技財經最快速更新"""
    url = "https://technews.tw/feed/"
    news: List[Dict] = []
    try:
        r = requests.get(url, headers={**HEADERS, "User-Agent": "Mozilla/5.0 (RSS reader)"}, timeout=8)
        try:
            soup = BeautifulSoup(r.content, "xml")
        except Exception:
            soup = BeautifulSoup(r.content, "html.parser")
        for item in soup.find_all("item")[:40]:
            t_el = item.find("title")
            title = t_el.get_text(strip=True) if t_el else ""
            d_el  = item.find("description")
            desc  = (d_el.get_text(strip=True) if d_el else "")[:200]
            p_el  = item.find("pubDate")
            age   = _rss_age_minutes(p_el.get_text(strip=True) if p_el else "") if p_el else -1
            if title and 0 <= age <= 720:
                news.append({"title": title, "summary": desc, "time": "--:--",
                             "source": "科技新報", "age_min": age})
    except Exception:
        pass
    return news


def fetch_google_news_tw_orders() -> List[Dict]:
    """Google News RSS — 掃描台灣股票訂單/合作/認證最新消息"""
    queries = [
        "台股 接獲訂單 OR 重大合作 OR 通過認證 OR 策略聯盟",
        "台灣 半導體 訂單 OR 合作 OR 認證 NVIDIA OR Apple OR Google OR 微軟",
        "台股 外資買超 OR 外資大買 OR 外資連買 升評",
    ]
    news: List[Dict] = []
    seen: set = set()
    for q in queries:
        try:
            import urllib.parse
            rss_url = ("https://news.google.com/rss/search"
                       f"?q={urllib.parse.quote(q)}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant")
            r = requests.get(rss_url, timeout=8,
                             headers={"User-Agent": "Mozilla/5.0 (compatible; newsbot/1.0)"})
            try:
                soup = BeautifulSoup(r.content, "xml")
            except Exception:
                soup = BeautifulSoup(r.content, "html.parser")
            for item in soup.find_all("item")[:20]:
                t_el  = item.find("title")
                title = t_el.get_text(strip=True) if t_el else ""
                p_el  = item.find("pubDate")
                age   = _rss_age_minutes(p_el.get_text(strip=True) if p_el else "")
                if title and title not in seen and 0 <= age <= 720:
                    seen.add(title)
                    src_el = item.find("source")
                    src    = src_el.get_text(strip=True) if src_el else "Google News"
                    news.append({"title": title, "summary": "", "time": "--:--",
                                 "source": src, "age_min": age})
        except Exception:
            pass
    return news


def fetch_yahoo_tw_news() -> List[Dict]:
    """
    Yahoo奇摩股市 RSS — 台灣股市即時財經新聞
    URL: https://tw.stock.yahoo.com/rss
    涵蓋：月營收、法人評等、訂單動態、外資動向、產業分析
    每篇新聞均含股票代號和公司名稱，適合關鍵字匹配
    """
    url = "https://tw.stock.yahoo.com/rss"
    news: List[Dict] = []
    try:
        r = requests.get(
            url,
            headers={**HEADERS, "User-Agent": "Mozilla/5.0 (RSS reader; compatible)"},
            timeout=10
        )
        try:
            soup = BeautifulSoup(r.content, "xml")
        except Exception:
            soup = BeautifulSoup(r.content, "html.parser")
        for item in soup.find_all("item")[:60]:
            t_el  = item.find("title")
            title = t_el.get_text(strip=True) if t_el else ""
            d_el  = item.find("description")
            desc  = (d_el.get_text(strip=True) if d_el else "")[:250]
            p_el  = item.find("pubDate")
            age   = _rss_age_minutes(p_el.get_text(strip=True) if p_el else "") if p_el else -1
            if title and 0 <= age <= 1440:   # 24小時內
                news.append({"title": title, "summary": desc, "time": "--:--",
                             "source": "Yahoo股市", "age_min": age})
    except Exception:
        pass
    return news


def fetch_ltn_news() -> List[Dict]:
    """
    自由財經 — 台灣財經重大新聞、法人動態、個股分析
    URL: breakingnews + securities 兩個列表頁，抓帶 /article/ 的連結
    涵蓋：外資/投信/自營買賣超、個股暴漲暴跌原因分析、月營收公告
    """
    urls = [
        "https://ec.ltn.com.tw/list/breakingnews",
        "https://ec.ltn.com.tw/list/securities",
    ]
    news: List[Dict] = []
    seen: set = set()
    for url in urls:
        try:
            r = requests.get(
                url,
                headers={**HEADERS,
                         "Referer": "https://ec.ltn.com.tw/",
                         "Accept": "text/html,application/xhtml+xml,*/*"},
                timeout=10
            )
            soup = BeautifulSoup(r.text, "html.parser")
            # 自由財經文章連結含 /article/ 路徑
            for a_tag in soup.find_all("a", href=True):
                if "/article/" not in a_tag.get("href", ""):
                    continue
                title = a_tag.get_text(strip=True)
                # Strip date prefix "2026/07/03 17:38" if present
                title = re.sub(r"^\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2}", "", title).strip()
                if not title or title in seen or len(title) < 8:
                    continue
                # Filter: keep finance/stock-relevant articles
                kw_ok = any(k in title for k in [
                    "股", "漲", "跌", "外資", "法人", "台積", "聯發", "AI", "半導體",
                    "營收", "獲利", "訂單", "合作", "市場", "指數", "主力", "投信",
                    "自營", "買超", "賣超", "漲停", "跌停", "基金", "景氣", "產業",
                    "電子", "科技", "金融", "航運", "能源", "記憶體", "晶圓"
                ])
                if not kw_ok:
                    continue
                seen.add(title)
                news.append({"title": title, "summary": "", "time": "--:--",
                             "source": "自由財經", "age_min": 0})
                if len(news) >= 40:
                    break
        except Exception:
            pass
    return news


def fetch_twse_foreign_multi_day(days: int = 5) -> Dict[str, List[float]]:
    """
    抓取最近 N 個交易日的外資買賣超資料。
    回傳 {ticker: [最新日, 前1日, 前2日, ...]}，正數=買超（千張），負數=賣超。
    用於判斷「外資連續買超/賣超 N 天」趨勢。
    """
    from datetime import timezone as _tz, timedelta as _td
    result: Dict[str, List[float]] = {}
    tw_now = datetime.now(tz=_tz(_td(hours=8)))

    # 嘗試最近10個日曆日，取到 days 個有效交易日
    dates_tried = 0
    dates_ok    = 0
    day_offset  = 0
    daily_data: List[Dict[str, float]] = []

    while dates_ok < days and dates_tried < 14:
        d = tw_now - _td(days=day_offset)
        day_offset += 1
        dates_tried += 1
        if d.weekday() >= 5:   # Skip Saturday / Sunday
            continue
        date_str = d.strftime("%Y%m%d")
        url = f"https://www.twse.com.tw/rwd/zh/fund/TWT53U?response=json&date={date_str}"
        try:
            r = requests.get(url, headers=HEADERS, timeout=8)
            data = r.json()
            rows = data.get("data", [])
            if not rows:
                continue   # holiday or no data
            day_dict: Dict[str, float] = {}
            for row in rows:
                if len(row) >= 5:
                    code = row[0].strip()
                    try:
                        net = float(row[4].replace(",", "").replace("+", ""))
                        day_dict[code + ".TW"] = net / 1000   # 千張
                    except (ValueError, IndexError):
                        pass
            daily_data.append(day_dict)
            dates_ok += 1
        except Exception:
            continue

    if not daily_data:
        return result

    # Transpose: result[ticker] = [day0_net, day1_net, ...]
    all_tickers = set(t for d in daily_data for t in d)
    for ticker in all_tickers:
        result[ticker] = [d.get(ticker, 0.0) for d in daily_data]

    return result


def calc_foreign_streak(multi_day: Dict[str, List[float]]) -> Dict[str, int]:
    """
    計算外資連續買超/賣超天數。
    回傳 {ticker: streak}，正數=連續買超天數，負數=連續賣超天數。
    例: +3 = 連續買超3天，-2 = 連續賣超2天
    """
    streaks: Dict[str, int] = {}
    for ticker, days_list in multi_day.items():
        if not days_list:
            streaks[ticker] = 0
            continue
        # Count consecutive same-direction from most recent day
        if days_list[0] > 0:
            streak = sum(1 for d in days_list if d > 0)
            # But must be consecutive from day0
            consecutive = 0
            for d in days_list:
                if d > 0: consecutive += 1
                else: break
            streaks[ticker] = consecutive
        elif days_list[0] < 0:
            consecutive = 0
            for d in days_list:
                if d < 0: consecutive -= 1
                else: break
            streaks[ticker] = consecutive
        else:
            streaks[ticker] = 0
    return streaks


def fetch_twse_trust_multi_day(days: int = 5) -> Dict[str, List[float]]:
    """
    抓取最近 N 個交易日的投信買賣超 (T86 欄位7: 投信淨買超千張)。
    回傳 {ticker: [最新日, 前1日, ...]}，用於計算連續買超/賣超天數。
    投信連續買超 = 台灣短線最強預測信號（比外資連買更精準）
    """
    from datetime import timezone as _tz, timedelta as _td
    result: Dict[str, List[float]] = {}
    tw_now    = datetime.now(tz=_tz(_td(hours=8)))
    daily_data: List[Dict[str, float]] = []
    dates_tried = dates_ok = day_offset = 0

    while dates_ok < days and dates_tried < 14:
        d = tw_now - _td(days=day_offset)
        day_offset += 1; dates_tried += 1
        if d.weekday() >= 5:
            continue
        date_str = d.strftime("%Y%m%d")
        url = (f"https://www.twse.com.tw/rwd/zh/fund/T86"
               f"?response=json&date={date_str}&selectType=ALLBUT0999")
        try:
            r = requests.get(url, headers=HEADERS, timeout=8)
            data = r.json()
            rows = data.get("data", [])
            if not rows:
                continue
            day_dict: Dict[str, float] = {}
            for row in rows:
                if len(row) < 8:
                    continue
                code = row[0].strip()
                if not code:
                    continue
                try:
                    net = float(str(row[7]).replace(",", "").replace("+", "")) / 1000
                    day_dict[code + ".TW"] = net
                except (ValueError, TypeError):
                    pass
            daily_data.append(day_dict)
            dates_ok += 1
        except Exception:
            continue

    if not daily_data:
        return result
    all_tickers = set(t for d in daily_data for t in d)
    for ticker in all_tickers:
        result[ticker] = [d.get(ticker, 0.0) for d in daily_data]
    return result


def calc_trust_streak(multi_day: Dict[str, List[float]]) -> Dict[str, int]:
    """
    計算投信連續買超/賣超天數。
    +N = 連買N天（最強短線多頭信號），-N = 連賣N天。
    """
    streaks: Dict[str, int] = {}
    for ticker, days_list in multi_day.items():
        if not days_list:
            streaks[ticker] = 0
            continue
        if days_list[0] > 0:
            consecutive = 0
            for d in days_list:
                if d > 0: consecutive += 1
                else: break
            streaks[ticker] = consecutive
        elif days_list[0] < 0:
            consecutive = 0
            for d in days_list:
                if d < 0: consecutive -= 1
                else: break
            streaks[ticker] = consecutive
        else:
            streaks[ticker] = 0
    return streaks


def detect_order_signals(news_list: List[Dict]) -> List[Dict]:
    """
    掃描所有新聞，偵測可能影響股價的訂單/合作/認證/升評訊號。

    回傳 list of {
        ticker, name, sector, signal_type, headline, source, age_min,
        partner, magnitude_label, magnitude_icon, base_score, entry_note
    } 按 base_score 排序（最重要的優先）。

    設計原則：
    • 只回傳 TECH_UNIVERSE 內的股票，或明確股票代號/名稱被點名的新聞
    • 新聞發布越新 → 分數越高（讓使用者第一時間看到）
    • 合作對象越重要 → 分數越高
    • 金額越大 → 分數越高
    """
    signals: List[Dict] = []
    seen_headlines: set = set()

    # Build a reverse lookup: Chinese name / EN name → ticker
    name_to_ticker: Dict[str, str] = {}
    for tk, info in TECH_UNIVERSE.items():
        nm = info.get("name", "")
        en = info.get("en", "")
        if nm: name_to_ticker[nm]       = tk
        if nm: name_to_ticker[nm[:2]]   = tk   # short alias (first 2 chars)
        if en and len(en) > 3: name_to_ticker[en.lower()] = tk

    for news in news_list:
        title   = news.get("title", "")
        summary = news.get("summary", "")
        source  = news.get("source", "")
        age_min = news.get("age_min", 999)
        combined = (title + " " + summary).strip()
        if not combined or title in seen_headlines:
            continue

        # ── Step 1: Does this news contain any order/cooperation signal? ────────
        best_kw_score = 0
        signal_type   = ""
        for kw, strength in ORDER_SIGNAL_KW:
            if kw.lower() in combined.lower():
                if strength > best_kw_score:
                    best_kw_score = strength
                    # Classify signal type
                    if any(x in kw for x in ["訂單","order","單"]):
                        signal_type = "📦 重大訂單"
                    elif any(x in kw for x in ["合作","MOU","聯盟","partner","joint","licensing","授權","結盟"]):
                        signal_type = "🤝 策略合作"
                    elif any(x in kw for x in ["認證","供應鏈","supplier","certified","入選","獲選"]):
                        signal_type = "✅ 供應鏈認證"
                    elif any(x in kw for x in ["升評","買進","target","outperform","overweight","外資大買","外資連買"]):
                        signal_type = "📈 外資/法人升評"
                    else:
                        signal_type = "📰 利多消息"

        if best_kw_score == 0:
            continue   # not an order/coop signal

        # ── Step 2: Find which stock is mentioned ────────────────────────────────
        matched_ticker = ""
        matched_name   = ""
        matched_sector = ""
        for nm, tk in name_to_ticker.items():
            if nm and len(nm) >= 2 and nm in combined:
                info = TECH_UNIVERSE.get(tk, {})
                matched_ticker = tk
                matched_name   = info.get("name", nm)
                matched_sector = info.get("sector", "")
                break

        if not matched_ticker:
            continue   # can't map to a known stock, skip

        # ── Step 3: Big partner bonus ────────────────────────────────────────────
        partner_bonus = 0
        partner_found = ""
        for partner, bonus in BIG_PARTNER_NAMES:
            if partner.lower() in combined.lower():
                if bonus > partner_bonus:
                    partner_bonus = bonus
                    partner_found = partner

        # ── Step 4: Magnitude detection ──────────────────────────────────────────
        magnitude_label = ""
        magnitude_icon  = ""
        mag_bonus       = 0
        for unit, label, icon in MAGNITUDE_TABLE:
            if unit in combined:
                magnitude_label = label
                magnitude_icon  = icon
                # Score based on magnitude
                mag_bonus = {"千億":20,"百億":15,"十億":10,"億":5,"千萬":2}.get(unit, 0)
                break

        # ── Step 5: Recency bonus ────────────────────────────────────────────────
        if   age_min < 60:    recency = 20
        elif age_min < 180:   recency = 15
        elif age_min < 360:   recency = 10
        elif age_min < 720:   recency = 5
        else:                  recency = 0

        # ── Step 6: Final score ──────────────────────────────────────────────────
        base_score = best_kw_score + partner_bonus + mag_bonus + recency

        # Entry note based on signal type and age
        if age_min < 60:
            entry_note = "⚡ 消息剛出！開盤前最佳布局時機"
        elif age_min < 180:
            entry_note = "🌅 早盤前消息，留意開盤跳空"
        elif age_min < 360:
            entry_note = "📌 今早消息，若尚未大漲可低接"
        else:
            entry_note = "📊 昨晚消息，開盤觀察量能確認"

        if partner_found:
            entry_note += f"　合作方：{partner_found}"

        seen_headlines.add(title)
        signals.append({
            "ticker":          matched_ticker,
            "name":            matched_name,
            "sector":          matched_sector,
            "signal_type":     signal_type,
            "headline":        title[:80],
            "source":          source,
            "age_min":         age_min,
            "partner":         partner_found,
            "magnitude_label": magnitude_label,
            "magnitude_icon":  magnitude_icon,
            "base_score":      base_score,
            "entry_note":      entry_note,
        })

    # Sort by score (desc), deduplicate by ticker (keep highest score per stock)
    signals.sort(key=lambda x: x["base_score"], reverse=True)
    seen_tickers: set = set()
    unique_signals: List[Dict] = []
    for s in signals:
        if s["ticker"] not in seen_tickers:
            seen_tickers.add(s["ticker"])
            unique_signals.append(s)
        if len(unique_signals) >= 8:
            break

    return unique_signals


def fetch_cnyes_news(limit: int = 60) -> List[Dict]:
    """鉅亨網科技財經新聞"""
    urls = [
        f"https://api.cnyes.com/media/api/v1/newslist/category/tw_stock?limit={limit}",
        f"https://api.cnyes.com/media/api/v1/newslist/category/technology?limit={limit}",
    ]
    news = []
    for url in urls:
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            r.raise_for_status()
            items = r.json().get("items", {}).get("data", [])
            for item in items:
                pub_ts = item.get("publishAt", 0)
                pub_dt = datetime.fromtimestamp(pub_ts)
                if datetime.now() - pub_dt > timedelta(hours=24):
                    continue
                news.append({
                    "title":   item.get("title", ""),
                    "summary": (item.get("summary") or "")[:120],
                    "time":    pub_dt.strftime("%H:%M"),
                    "source":  "鉅亨網",
                })
        except Exception:
            pass
    return news

def fetch_moneydj_news() -> List[Dict]:
    """MoneyDJ 財經新聞"""
    url = "https://www.moneydj.com/kline/fundsn/fundsn0003.djhtm"
    news = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.select("a[href*='djhtm']")[:20]:
            title = a.get_text(strip=True)
            if len(title) > 8:
                news.append({"title": title, "summary": "", "time": "--:--", "source": "MoneyDJ"})
    except Exception:
        pass
    return news

# Exchange mapping: stocks on OTC (櫃買) vs TSE (上市)
def _tw_limit_up(prev: float) -> float:
    """Taiwan ±10% limit, rounded to correct tick size."""
    price = prev * 1.10
    if price < 10:     tick = 0.01
    elif price < 50:   tick = 0.05
    elif price < 100:  tick = 0.10
    elif price < 500:  tick = 0.50
    elif price < 1000: tick = 1.00
    else:              tick = 5.00
    return round(price / tick) * tick

def _parse_ts(ts) -> str:
    """Convert a pandas Timestamp to Taipei HH:MM string."""
    try:
        from datetime import timezone as _tz, timedelta as _td
        if getattr(ts, "tzinfo", None):
            tw = ts.astimezone(_tz(_td(hours=8)))
        else:
            tw = pd.Timestamp(ts).tz_localize("UTC").tz_convert("Asia/Taipei")
        return tw.strftime("%H:%M")
    except Exception:
        return "--:--"

# 模組層級 TWSE session（初始化一次，保留 cookie）
_twse_session: Optional[requests.Session] = None

def _get_twse_session() -> requests.Session:
    global _twse_session
    if _twse_session is None:
        _twse_session = requests.Session()
        _twse_session.headers.update({
            **HEADERS,
            "Referer": "https://mis.twse.com.tw/stock/index.jsp",
        })
        try:
            _twse_session.get("https://mis.twse.com.tw/stock/index.jsp", timeout=5)
        except Exception:
            pass
    return _twse_session


def _fetch_live_twse(tickers: List[str]) -> Dict[str, Dict]:
    """
    即時股價 — TWSE MIS API（台灣交易所官方資料）
    優先用 z（成交價），z=- 時改用買賣掛單中間價（bid/ask midpoint），
    確保盤中每幾秒都有更新，遠比 yfinance 1分K即時。
    """
    result: Dict[str, Dict] = {}
    if not tickers:
        return result

    session = _get_twse_session()
    codes   = [t.replace(".TW", "").replace(".TWO", "").lower() for t in tickers]
    # 同時送出 tse_ 和 otc_ 前綴，API 自動忽略無效的那個
    ex_ch   = "|".join(f"tse_{c}.tw|otc_{c}.tw" for c in codes)
    url     = (f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
               f"?ex_ch={ex_ch}&json=1&delay=0")
    try:
        r = session.get(url, timeout=5)
        r.raise_for_status()
        for item in r.json().get("msgArray", []):
            code    = item.get("c", "")
            name_n  = item.get("n", "")   # Chinese name e.g. "台積電"
            ticker  = code + ".TW"
            if not code or ticker not in tickers:
                continue
            # Cache name for dynamically searched stocks not in TECH_UNIVERSE
            if name_n and ticker not in TECH_UNIVERSE:
                _TW_STOCK_NAMES[ticker] = name_n

            y_str = item.get("y", "")
            prev  = float(y_str) if y_str and y_str not in ("-", "0", "") else 0
            if prev == 0:
                continue

            # ── 1. 成交價 z（有撮合就用） ─────────────────────────────────────
            price = None
            z = item.get("z", "-")
            if z and z not in ("-", "0", ""):
                price = float(z)

            # ── 2. z=- 時改用買賣掛單中間價（bid/ask midpoint）──────────────
            if price is None:
                a_str = item.get("a", "")   # 賣：2315_2320_...
                b_str = item.get("b", "")   # 買：2310_2305_...
                try:
                    best_ask = float(a_str.split("_")[0]) if a_str else None
                    best_bid = float(b_str.split("_")[0]) if b_str else None
                    if best_ask and best_bid:
                        price = (best_ask + best_bid) / 2
                    elif best_bid:
                        price = best_bid
                    elif best_ask:
                        price = best_ask
                except (ValueError, IndexError):
                    pass

            # ── 3. 再退：今日最高 / 開盤 ─────────────────────────────────────
            if price is None:
                for fld in ("h", "o"):
                    val = item.get(fld, "-")
                    if val and val not in ("-", "0", ""):
                        price = float(val)
                        break

            if price is None:
                continue

            chg      = price - prev
            chg_pct  = (chg / prev * 100) if prev > 0 else 0
            vol_raw  = item.get("v", "0").replace(",", "")
            volume   = int(float(vol_raw)) // 1000 if vol_raw and vol_raw not in ("-", "") else 0
            u_str    = item.get("u", "-")
            limit_up = float(u_str) if u_str and u_str not in ("-", "0", "") else _tw_limit_up(prev)
            t_str    = item.get("t", "") or item.get("%", "--:--")

            result[ticker] = {
                "price":      round(price, 2),
                "prev":       prev,
                "chg":        round(chg, 2),
                "chg_pct":    round(chg_pct, 2),
                "volume":     volume,
                "limit_up":   limit_up,
                "limit_down": round(prev * 0.90, 0),
                "time":       t_str[:5] if len(t_str) >= 5 else t_str,
                "live":       True,
            }
    except Exception:
        pass
    return result


def _fetch_live_yf(tickers: List[str]) -> Dict[str, Dict]:
    """yfinance fallback（非交易時段 / TWSE API 未覆蓋時使用）"""
    import yfinance as yf
    result: Dict[str, Dict] = {}
    if not tickers:
        return result
    try:
        raw = yf.download(
            tickers=" ".join(tickers),
            period="2d",
            interval="1m",
            progress=False,
            auto_adjust=True,
            timeout=15,
        )
    except Exception:
        return result
    if raw is None or raw.empty:
        return result
    is_multi = isinstance(raw.columns, pd.MultiIndex)
    for t in tickers:
        try:
            close_s = raw["Close"][t].dropna() if is_multi else raw["Close"].dropna()
            vol_s   = raw["Volume"][t].dropna() if is_multi else raw["Volume"].dropna()
            if close_s.empty:
                continue
            last_price = float(close_s.iloc[-1])
            last_ts    = close_s.index[-1]
            if hasattr(last_ts, "date"):
                today_d    = last_ts.date()
                prev_bars  = close_s[[x.date() < today_d for x in close_s.index]]
                prev_close = float(prev_bars.iloc[-1]) if not prev_bars.empty else last_price
            else:
                prev_close = last_price
            chg     = last_price - prev_close
            chg_pct = (chg / prev_close * 100) if prev_close > 0 else 0
            vol_sum = int(vol_s.iloc[-30:].sum() / 1000) if not vol_s.empty else 0
            # 若最後一根 K 是今天的，就算「盤中延遲」也算 live
            from datetime import timezone as _tz, timedelta as _td
            _tw_now = datetime.now(_tz(_td(hours=8))).date()
            try:
                _bar_date = last_ts.astimezone(_tz(_td(hours=8))).date()
            except Exception:
                _bar_date = None
            is_today = (_bar_date == _tw_now) if _bar_date else False

            result[t] = {
                "price":      last_price,
                "prev":       prev_close,
                "chg":        chg,
                "chg_pct":    chg_pct,
                "volume":     vol_sum,
                "limit_up":   _tw_limit_up(prev_close),
                "limit_down": round(prev_close * 0.90, 0),
                "time":       _parse_ts(last_ts),
                "live":       is_today,
            }
        except Exception:
            pass
    return result


def fetch_live_prices(tickers: List[str]) -> Dict[str, Dict]:
    """
    即時股價主入口：
      1. 優先用 TWSE MIS API（官方即時，盤中幾秒更新）
      2. 沒拿到的 ticker 改用 yfinance 1分K補齊（非盤中時段）
    """
    if not tickers:
        return {}
    result  = _fetch_live_twse(tickers)
    missing = [t for t in tickers if t not in result]
    if missing:
        result.update(_fetch_live_yf(missing))
    return result

def analyze_holding_sell(df: pd.DataFrame) -> Dict:
    """
    分析持股最佳賣出時機。
    回傳：action, urgency, target_sell, stop_loss, upside, downside, reasons
    """
    if df is None or len(df) < 22:
        return {}

    close = df["Close"]
    high  = df["High"]
    last  = float(close.iloc[-1])

    rsi          = calc_rsi(close)
    macd_h, macd_prev = calc_macd(close)
    atr          = calc_atr(df)
    ma5          = float(close.rolling(5).mean().iloc[-1])
    ma20         = float(close.rolling(20).mean().iloc[-1])
    ma60         = float(close.rolling(min(60, len(close))).mean().iloc[-1])
    high_20      = float(high.tail(20).max())
    high_60      = float(high.tail(min(60, len(high))).max())
    high_52w     = float(high.tail(min(252, len(high))).max())

    reasons  = []
    urgency  = "低"
    action   = "目前可以繼續持有"

    # ── RSI ──────────────────────────────────────────────────────────────────
    if rsi >= 82:
        reasons.append(f"漲太多了（RSI {rsi:.0f}），很多人開始獲利了結")
        urgency = "高"; action = "建議賣掉或減少持股"
    elif rsi >= 75:
        reasons.append(f"漲勢偏強（RSI {rsi:.0f}），可以考慮先賣一部分")
        urgency = "中"; action = "可以先賣一半獲利"
    elif rsi >= 68:
        reasons.append(f"漲幅不小（RSI {rsi:.0f}），留意有沒有反轉跡象")
    elif rsi < 45:
        reasons.append(f"漲勢在減弱（RSI {rsi:.0f}），小心繼續跌")
        if urgency == "低": urgency = "中"
        if action == "目前可以繼續持有": action = "注意停損點，別讓虧損擴大"

    # ── MACD ─────────────────────────────────────────────────────────────────
    if macd_h < 0 and macd_prev >= 0:
        reasons.append("動能轉向向下，短線可能開始走弱")
        if urgency == "低": urgency = "中"
        if action == "目前可以繼續持有": action = "考慮找高點賣出"
    elif macd_h > 0 and macd_prev > 0 and macd_h < macd_prev * 0.6:
        reasons.append("上漲力道在縮減，後續漲幅可能有限")

    # ── MA position ──────────────────────────────────────────────────────────
    if last < ma20:
        reasons.append("股價跌破20日均線，短線轉弱")
        if urgency == "低": urgency = "中"
        if action == "目前可以繼續持有": action = "注意停損點，別讓虧損擴大"
    elif last > ma20 > ma60:
        reasons.append("均線向上排列，趨勢健康，可以繼續持有")

    # ── Resistance ───────────────────────────────────────────────────────────
    if last >= high_52w * 0.99:
        reasons.append(f"快到一年最高點 {high_52w:.1f} 了，這附近通常會有賣壓")
        if urgency == "低": urgency = "中"
    elif last >= high_20 * 0.985:
        reasons.append(f"接近近20天高點 {high_20:.1f}，短期可能遇到阻力")

    if not reasons:
        reasons.append("目前沒有明顯賣出訊號，可以繼續觀察")

    # ── Target & stop ─────────────────────────────────────────────────────────
    target_sell = round(min(last + 2.0 * atr, high_52w * 1.02), 1)
    stop_loss   = round(max(last - 1.5 * atr, ma20 * 0.97), 1)
    upside      = round((target_sell - last) / last * 100, 1)
    downside    = round((stop_loss   - last) / last * 100, 1)

    return {
        "action":      action,
        "urgency":     urgency,
        "target_sell": target_sell,
        "stop_loss":   stop_loss,
        "upside":      upside,
        "downside":    downside,
        "rsi":         round(rsi, 1),
        "above_ma20":  last > ma20,
        "macd_pos":    macd_h > 0,
        "reasons":     reasons[:3],
    }

def fetch_twse_foreign_buying(date_str: Optional[str] = None) -> Dict[str, float]:
    """抓取外資買超資料（千張）"""
    if not date_str:
        from datetime import timezone, timedelta
        date_str = datetime.now(tz=timezone(timedelta(hours=8))).strftime("%Y%m%d")
    url = f"https://www.twse.com.tw/rwd/zh/fund/TWT53U?response=json&date={date_str}"
    result = {}
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        data = r.json()
        rows = data.get("data", [])
        for row in rows:
            if len(row) >= 5:
                code = row[0].strip()
                try:
                    net = float(row[4].replace(",", "").replace("+", ""))
                    result[code + ".TW"] = net / 1000
                except (ValueError, IndexError):
                    pass
    except Exception:
        pass
    return result

def fetch_twse_market_summary() -> Dict:
    """抓取大盤概況"""
    url = "https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?response=json"
    try:
        r = requests.get(url, headers=HEADERS, timeout=8)
        data = r.json()
        rows = data.get("data", [])
        if rows:
            row = rows[-1]
            return {
                "date":   row[0] if len(row) > 0 else "--",
                "volume": row[1] if len(row) > 1 else "--",
                "amount": row[2] if len(row) > 2 else "--",
                "index":  row[4] if len(row) > 4 else "--",
                "change": row[5] if len(row) > 5 else "--",
            }
    except Exception:
        pass
    return {}


def fetch_twse_three_investors(date_str: Optional[str] = None) -> Dict[str, Dict]:
    """
    三大法人買賣超（外資 + 投信 + 自營）— TWSE T86 API
    台灣短線預測力：投信連買 > 外資連買 > 自營；三大法人同買 = 最強機構共識

    T86 欄位（0-indexed）:
      0: 代號  1: 名稱
      2-4: 外陸資 (買/賣/淨)
      5-7: 投信   (買/賣/淨)
      8-10: 自營(自行) (買/賣/淨)
      11-13: 自營(避險)(買/賣/淨)
      14: 三大法人合計淨買

    回傳 {ticker: {"trust": float, "dealer": float, "total": float}} (千張)
    """
    if not date_str:
        date_str = datetime.now(tz=timezone(timedelta(hours=8))).strftime("%Y%m%d")
    url = (f"https://www.twse.com.tw/rwd/zh/fund/T86"
           f"?response=json&date={date_str}&selectType=ALLBUT0999")
    result: Dict[str, Dict] = {}
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        data = r.json()
        rows = data.get("data", [])
        for row in rows:
            if len(row) < 15:
                continue
            code = row[0].strip()
            if not code:
                continue
            def _to_k(val: str) -> float:
                try:
                    return float(str(val).replace(",", "").replace("+", "")) / 1000
                except (ValueError, TypeError):
                    return 0.0
            trust_net  = _to_k(row[7])    # 投信淨買超（千張）
            dealer_own = _to_k(row[10])   # 自營(自行)淨買
            dealer_hdg = _to_k(row[13])   # 自營(避險)淨買
            total_net  = _to_k(row[14])   # 三大法人合計
            result[code + ".TW"] = {
                "trust":  trust_net,
                "dealer": dealer_own + dealer_hdg,
                "total":  total_net,
            }
    except Exception:
        pass
    return result


def calc_three_investors_bonus(trust_net: float, dealer_net: float, foreign_net: float) -> Dict:
    """
    三大法人買賣超共識評分 (-6 ~ +8)
    • 三大同買：機構合力建倉，勝率最高   → +8
    • 外資 + 投信同買：主要機構共識      → +6
    • 投信單獨買超：台灣短線最強預測信號  → +4
    • 外資單獨買超：已在 score_stock 計分，這裡補充 → +0 (避免重複)
    • 三大同賣：機構集體出清             → -6
    • 外資 + 投信同賣：機構共識看空      → -4

    trust_net / dealer_net / foreign_net 單位：千張（正=買超，負=賣超）
    """
    bonus = 0
    labels: List[str] = []

    fi_buy     = foreign_net > 0
    trust_buy  = trust_net   > 50    # 投信買超 50張以上（避免雜訊）
    dealer_buy = dealer_net  > 0
    fi_sell    = foreign_net < -100
    trust_sell = trust_net   < -50
    dealer_sell= dealer_net  < 0

    # ── 買超共識 ──────────────────────────────────────────────────────────────
    if fi_buy and trust_buy and dealer_buy:
        bonus += 8
        labels.append("🏆 三大法人同買（最強）")
    elif fi_buy and trust_buy:
        bonus += 6
        labels.append("💼 外資+投信同買")
    elif trust_buy:
        bonus += 4
        labels.append("📈 投信買超")

    # ── 賣超共識（懲罰）────────────────────────────────────────────────────────
    if fi_sell and trust_sell and dealer_sell:
        bonus -= 6
        labels.append("⚠️ 三大法人同賣")
    elif fi_sell and trust_sell:
        bonus -= 4
        labels.append("⬇️ 外資+投信同賣")
    elif trust_sell:
        bonus -= 2
        labels.append("📉 投信賣超")

    return {"bonus": max(-6, min(8, bonus)), "labels": labels,
            "trust_net": trust_net, "dealer_net": dealer_net}


def fetch_taiex_prices(period: str = "3mo") -> Optional[pd.Series]:
    """
    台灣加權指數 (^TWII) 收盤歷史 — O'Neil RS 計算的市場基準。
    Returns pd.Series (date index, close values), or None on failure.
    """
    if not HAS_YF:
        return None
    try:
        raw = yf.download("^TWII", period=period, auto_adjust=True,
                          progress=False, threads=False, timeout=15)
        if raw is None or raw.empty:
            return None
        if isinstance(raw.columns, pd.MultiIndex):
            close = raw["Close"]["^TWII"].dropna()
        else:
            close = raw["Close"].dropna()
        return close if len(close) >= 22 else None
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════════════
#  催化劑分析：從新聞中找出觸發因素與受益股
# ═══════════════════════════════════════════════════════════════════════════════

def analyze_catalysts(news_list: List[Dict]) -> Tuple[Dict[str, int], List[str]]:
    """
    回傳:
      catalyst_scores: {ticker: bonus_points}  ← 每日依新聞量動態計算，不再固定+20
      headlines:       最重要的5條新聞標題

    修正說明（2026-05）：
      原版給每個觸發催化劑固定+20，導致台積電等大股每天永遠吃滿分，
      推薦名單永遠不變。現改為：
        1. 依當日新聞篇數比例縮放（少=小分，多=大分）
        2. 用 max 累積（避免大股靠多主題堆疊）
        3. 個股直接被點名才能再疊加直接加分
    """
    catalyst_scores: Dict[str, int] = {}
    key_headlines: List[str] = []

    # ── 1. 計算每個催化劑今日新聞篇數 ─────────────────────────────────────────
    catalyst_counts: Dict[str, int] = {}
    for catalyst, keywords in CATALYST_MAP.items():
        count = sum(
            1 for n in news_list
            if any(kw.lower() in (n["title"] + " " + n["summary"]).lower() for kw in keywords)
        )
        if count > 0:
            catalyst_counts[catalyst] = count

    triggered = set(catalyst_counts.keys())

    # 找出最相關的新聞
    for news in news_list:
        combined = news["title"] + " " + news["summary"]
        for catalyst in triggered:
            for kw in CATALYST_MAP[catalyst]:
                if kw.lower() in combined.lower():
                    if news["title"] not in key_headlines:
                        key_headlines.append(f"[{news['time']}][{news['source']}] {news['title'][:60]}")
                    break

    # ── 2. 主題加分：依新聞篇數縮放，單催化劑上限15分 ─────────────────────────
    # 原本固定+20 → 現在依篇數動態給分，讓今日熱度決定分數
    def _theme_bonus(count: int) -> int:
        if count >= 12: return 15
        if count >= 6:  return 11
        if count >= 3:  return 7
        if count >= 1:  return 4
        return 0

    # 用 max（不用+）：每股只取最強的那個催化劑主題，避免台積電靠5個主題疊到滿
    for catalyst in triggered:
        bonus = _theme_bonus(catalyst_counts[catalyst])
        for ticker in CATALYST_BENEFICIARIES.get(catalyst, []):
            prev = catalyst_scores.get(ticker, 0)
            catalyst_scores[ticker] = max(prev, bonus)

    # ── 3. 個股直接被新聞標題點名 → 疊加直接加分（每篇+4分，上限15分）──────────
    for ticker, info in TECH_UNIVERSE.items():
        name = info.get("name", "")
        en   = info.get("en", "")
        direct = sum(
            1 for n in news_list
            if (name and name in n["title"])
            or (en and len(en) > 3 and en.lower() in n["title"].lower())
        )
        if direct > 0:
            direct_bonus = min(15, direct * 4)
            catalyst_scores[ticker] = catalyst_scores.get(ticker, 0) + direct_bonus

    # ── 4. 訂單/合作/認證新聞 → 巨型加分（最高+25），這是散戶最需要的情報 ──────
    # 個股名稱 + 訂單關鍵字同時出現在同一篇文章 → 直接加大量分數
    order_high_kw = [kw for kw, strength in ORDER_SIGNAL_KW if strength >= 10]
    for ticker, info in TECH_UNIVERSE.items():
        name = info.get("name", "")
        en   = info.get("en", "")
        for n in news_list:
            combined = (n["title"] + " " + n["summary"]).lower()
            name_hit = (name and name in combined) or (en and len(en) > 3 and en.lower() in combined)
            if not name_hit:
                continue
            for kw in order_high_kw:
                if kw.lower() in combined:
                    # 訂單/合作新聞與個股同篇 → 最高+25（超過正常催化劑上限，強制浮出）
                    order_boost = 25
                    catalyst_scores[ticker] = max(
                        catalyst_scores.get(ticker, 0),
                        catalyst_scores.get(ticker, 0) + order_boost
                    )
                    # 加入 headline（標記為重大）
                    hl = f"🔥[{n['time']}][{n['source']}] {n['title'][:60]}"
                    if hl not in key_headlines:
                        key_headlines.insert(0, hl)   # Push to top
                    break

    return catalyst_scores, key_headlines[:8]

def get_catalyst_labels(ticker: str, news_list: List[Dict]) -> List[str]:
    """為特定股票找出新聞催化劑標籤"""
    info  = TECH_UNIVERSE.get(ticker, {})
    # For non-universe stocks, fall back to dynamically cached name from TWSE live API
    name  = info.get("name", "") or _TW_STOCK_NAMES.get(ticker, "")
    en    = info.get("en", "")
    supply_chains = info.get("supply", [])
    labels = []

    all_text = " ".join(n["title"] + " " + n["summary"] for n in news_list).lower()

    # Guard: empty name/en must NOT match (every string contains "")
    if (name and name.lower() in all_text) or (en and len(en) > 3 and en.lower() in all_text):
        labels.append("📰直接受益")

    for sc in supply_chains:
        if sc in CATALYST_MAP:
            for kw in CATALYST_MAP[sc]:
                if kw.lower() in all_text:
                    labels.append(f"🔗{sc}鏈")
                    break

    return list(dict.fromkeys(labels))[:3]

# ═══════════════════════════════════════════════════════════════════════════════
#  新手即時操作建議
# ═══════════════════════════════════════════════════════════════════════════════

def calc_live_rsi(df: pd.DataFrame, live_price: float, period: int = 14) -> float:
    """
    即時 RSI：把當前成交價接在歷史日K後面重算。
    讓 RSI 在盤中隨股價變動，新手可看到 RSI 何時進入可買區。
    """
    if df is None or len(df) < period + 2:
        return calc_rsi(df["Close"]) if df is not None and len(df) > period else 50.0
    close = df["Close"].copy()
    # 用 live_price 取代（或附加）最後一根，模擬當前收盤
    close = pd.concat([close, pd.Series([live_price], index=[close.index[-1] + pd.Timedelta(days=1)])])
    return calc_rsi(close, period)


def get_beginner_advice(df: pd.DataFrame, live_price: float) -> Dict:
    """
    為新手產生清楚的操作建議，包含：
      - 即時 RSI 與進場信號
      - 建議買點區間（支撐位）
      - 止損價位
      - 目標價位
      - 文字說明
    """
    if df is None or len(df) < 22:
        return {}

    close  = df["Close"]
    high   = df["High"]
    ma5    = float(close.rolling(5).mean().iloc[-1])
    ma20   = float(close.rolling(20).mean().iloc[-1])
    ma60   = float(close.rolling(min(60, len(close))).mean().iloc[-1])
    atr    = calc_atr(df)
    rsi    = calc_live_rsi(df, live_price)
    high20 = float(high.tail(20).max())

    # ── 趨勢判斷 ──────────────────────────────────────────────────────────────
    if live_price > ma5 > ma20 > ma60:
        trend = "強勢上漲"
        trend_icon = "🚀"
        trend_col  = "#ef5350"
    elif live_price > ma20:
        trend = "上漲整理"
        trend_icon = "📈"
        trend_col  = "#ef5350"
    elif live_price > ma60:
        trend = "短線偏弱"
        trend_icon = "⚠️"
        trend_col  = "#ffd54f"
    else:
        trend = "下跌趨勢"
        trend_icon = "📉"
        trend_col  = "#aaa"

    # ── 建議買點（支撐區）─────────────────────────────────────────────────────
    if live_price > ma5:
        # 股價在MA5之上 → 回踩MA5為好買點
        buy_low  = round(ma5 * 0.99, 1)
        buy_high = round(ma5 * 1.005, 1)
        buy_note = f"等回踩 MA5 ({ma5:.1f}) 附近再進場，不要追高"
    elif live_price > ma20:
        # 介於MA5和MA20之間 → MA20支撐
        buy_low  = round(ma20 * 0.995, 1)
        buy_high = round(ma20 * 1.01, 1)
        buy_note = f"MA20 ({ma20:.1f}) 附近是支撐，可小量試單"
    else:
        # 跌破MA20 → 等待站回
        buy_low  = round(ma20 * 0.99, 1)
        buy_high = round(ma20 * 1.005, 1)
        buy_note = f"跌破均線，等站回 MA20 ({ma20:.1f}) 後再考慮"

    # ── 止損（新手建議稍寬一點，避免被洗出）─────────────────────────────────
    stop_loss = round(max(live_price - 2.0 * atr, ma20 * 0.95), 1)
    stop_pct  = round((stop_loss - live_price) / live_price * 100, 1)

    # ── 目標價（1:1.5 風險報酬）──────────────────────────────────────────────
    risk      = live_price - stop_loss
    target    = round(live_price + risk * 1.5, 1)
    target_pct = round((target - live_price) / live_price * 100, 1)

    # ── RSI 進場信號（新手最重要的指標）─────────────────────────────────────
    # 進場甜蜜區間 45–68；RSI < 73 才出現在「今日可進場」名單
    if rsi < 30:
        rsi_signal = "🟢 超賣！可分批進場"
        rsi_col    = "#00c853"
        rsi_action = "RSI 嚴重超賣，可分批零股買入，但留意是否仍在下跌趨勢"
    elif rsi < 45:
        rsi_signal = "🟢 低檔，適合進場"
        rsi_col    = "#00c853"
        rsi_action = "RSI 偏低，股價相對便宜，適合分批零股累積"
    elif rsi < 60:
        rsi_signal = "✅ 理想進場區間"
        rsi_col    = "#00c853"
        rsi_action = "RSI 在 45–60 最佳甜蜜區：趨勢向上但未過熱，現在進場最穩健"
    elif rsi < 68:
        rsi_signal = "✅ 趨勢向上，可進場"
        rsi_col    = "#7eb3ff"
        rsi_action = "RSI 60–68：多頭趨勢強，仍在合理範圍，可分批買入"
    elif rsi < 73:
        rsi_signal = "🟡 偏高，小量試探"
        rsi_col    = "#ffd54f"
        rsi_action = "RSI 68–72：偏熱邊緣，建議先買三成，等回調至 65 以下再加碼"
    elif rsi < 80:
        rsi_signal = "🟠 偏熱，等回落"
        rsi_col    = "#ff9800"
        rsi_action = "RSI 已超過 73，追高風險上升，建議等 RSI 回落至 68 以下再進場"
    else:
        rsi_signal = "🔴 超買！暫勿追高"
        rsi_col    = "#ef5350"
        rsi_action = "RSI 超過 80，短期嚴重超買，耐心等待回調，切勿追漲"

    return {
        "rsi":         round(rsi, 1),
        "rsi_signal":  rsi_signal,
        "rsi_col":     rsi_col,
        "rsi_action":  rsi_action,
        "trend":       trend,
        "trend_icon":  trend_icon,
        "trend_col":   trend_col,
        "buy_low":     buy_low,
        "buy_high":    buy_high,
        "buy_note":    buy_note,
        "stop_loss":   stop_loss,
        "stop_pct":    stop_pct,
        "target":      target,
        "target_pct":  target_pct,
        "ma5":         round(ma5, 1),
        "ma20":        round(ma20, 1),
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  美股隔夜 & 國際財經
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_us_overnight() -> Dict:
    """
    抓取美股隔夜收盤：S&P500、那斯達克、費城半導體（SOX）、VIX、
    TSMC ADR、NVDA、美元/台幣。
    計算對台股的綜合影響分數 macro_score（-15 ~ +15）。
    費半是台灣半導體股最關鍵的領先指標。
    """
    empty = {
        "sp500":   {"pct": 0.0, "val": 0.0},
        "nasdaq":  {"pct": 0.0, "val": 0.0},
        "sox":     {"pct": 0.0, "val": 0.0},
        "vix":     {"pct": 0.0, "val": 0.0},
        "usd_twd": {"pct": 0.0, "val": 0.0},
        "tsm_adr": {"pct": 0.0, "val": 0.0},
        "nvda":    {"pct": 0.0, "val": 0.0},
        "sentiment":   "neutral",
        "macro_score": 0,
        "summary":     "",
    }
    if not HAS_YF:
        return empty

    try:
        syms = ["^GSPC", "^IXIC", "^SOX", "^VIX", "USDTWD=X", "TSM", "NVDA"]
        raw = yf.download(syms, period="5d", progress=False,
                          auto_adjust=True, threads=True, timeout=15)
        if raw is None or raw.empty:
            return empty

        def _pct_val(sym: str):
            try:
                s = raw["Close"][sym].dropna() if isinstance(raw.columns, pd.MultiIndex) \
                    else raw["Close"].dropna()
                if len(s) >= 2:
                    return round((s.iloc[-1] / s.iloc[-2] - 1) * 100, 2), round(float(s.iloc[-1]), 2)
            except Exception:
                pass
            return 0.0, 0.0

        sp_pct,  sp_val  = _pct_val("^GSPC")
        nq_pct,  nq_val  = _pct_val("^IXIC")
        sox_pct, sox_val = _pct_val("^SOX")
        vix_pct, vix_val = _pct_val("^VIX")
        usd_pct, usd_val = _pct_val("USDTWD=X")
        tsm_pct, tsm_val = _pct_val("TSM")
        nvd_pct, nvd_val = _pct_val("NVDA")

        # ── 綜合評分（加權，費半最重要）────────────────────────────────────────
        macro = (
            sox_pct * 2.0    # 費半：直接反映半導體出口景氣，與台股相關係數 >0.8
          + nq_pct  * 1.0    # 那指：科技股整體氣氛
          + sp_pct  * 0.5    # 標普：市場廣度
          + nvd_pct * 0.5    # 輝達：AI板塊溫度計
          + tsm_pct * 0.5    # 台積電ADR：外資對台股科技的直接看法
        )
        # VIX 恐慌指數懲罰
        if   vix_val > 35: macro -= 12
        elif vix_val > 30: macro -= 8
        elif vix_val > 25: macro -= 4
        elif vix_val > 20: macro -= 1
        # 美元強勢微幅加分（台灣出口股受惠）
        if   usd_pct >  0.5: macro += 1
        elif usd_pct < -0.5: macro -= 1

        macro = max(-15.0, min(15.0, round(macro, 1)))

        sent = "bullish" if macro >= 6 else ("bearish" if macro <= -6 else "neutral")

        # 摘要文字
        movers = []
        if abs(sox_pct) >= 0.8:  movers.append(f"費半 {sox_pct:+.1f}%")
        if abs(nq_pct)  >= 0.8:  movers.append(f"那指 {nq_pct:+.1f}%")
        if abs(nvd_pct) >= 1.5:  movers.append(f"NVDA {nvd_pct:+.1f}%")
        if abs(tsm_pct) >= 1.0:  movers.append(f"TSM ADR {tsm_pct:+.1f}%")
        if vix_val > 25:         movers.append(f"VIX {vix_val:.0f} ⚠️")
        summary = "　".join(movers) if movers else "美股小幅波動，影響有限"

        return {
            "sp500":   {"pct": sp_pct,  "val": sp_val},
            "nasdaq":  {"pct": nq_pct,  "val": nq_val},
            "sox":     {"pct": sox_pct, "val": sox_val},
            "vix":     {"pct": vix_pct, "val": vix_val},
            "usd_twd": {"pct": usd_pct, "val": usd_val},
            "tsm_adr": {"pct": tsm_pct, "val": tsm_val},
            "nvda":    {"pct": nvd_pct, "val": nvd_val},
            "sentiment":   sent,
            "macro_score": macro,
            "summary":     summary,
        }
    except Exception:
        return empty


def us_macro_stock_bonus(ticker: str, us_data: Dict) -> int:
    """
    根據美股隔夜表現，計算個股的盤前加/減分（-10 ~ +10）。
    半導體/IC設計股與費半相關最高；金融/航運相關最低。
    """
    if not us_data:
        return 0
    macro  = float(us_data.get("macro_score", 0))
    sox    = float(us_data.get("sox",  {}).get("pct", 0))
    nvda   = float(us_data.get("nvda", {}).get("pct", 0))
    vix    = float(us_data.get("vix",  {}).get("val", 0))
    if macro == 0 and vix == 0:
        return 0

    info   = TECH_UNIVERSE.get(ticker, {})
    sector = info.get("sector", "")
    supply = info.get("supply", [])

    # Tier 1: directly in SOX basket — 半導體、記憶體、IC設計
    T1 = {"記憶體", "晶片", "IC設計", "網路/通訊IC"}
    # Tier 2: downstream supply chain
    T2 = {"PCB/被動元件", "封裝測試", "設備材料"}
    # Tier 3: low correlation
    T3 = {"金融", "航運", "生技", "消費"}

    if sector in T1 or any(s in supply for s in ("NVIDIA", "AMD", "Apple", "CoWoS")):
        base = sox * 1.5 + nvda * 0.5
    elif sector in T2:
        base = sox * 0.8 + macro * 0.2
    elif sector in T3:
        base = macro * 0.15
    else:
        base = macro * 0.5   # general tech

    # Extreme VIX overrides sector: if panic, cap at -3 or lower
    if   vix > 35: base = min(base, -8)
    elif vix > 30: base = min(base, -3)
    elif vix > 25: base = min(base,  0)

    return max(-10, min(10, round(base)))


def fetch_global_news() -> List[str]:
    """
    抓取國際財經新聞（yfinance Ticker.news），
    過濾出台灣科技相關主題（半導體、AI、供應鏈、關稅、Fed…）。
    """
    if not HAS_YF:
        return []
    KW = ["semiconductor", "chip", "TSMC", "NVIDIA", "AI", "Taiwan",
          "memory", "HBM", "packaging", "tariff", "Fed", "Apple",
          "supply chain", "Micron", "ASML", "foundry", "wafer"]
    seen: set = set()
    headlines: List[str] = []
    for sym in ["TSM", "NVDA", "MU", "AVGO", "^SOX"]:
        try:
            items = yf.Ticker(sym).news or []
            for item in items[:5]:
                # yfinance 0.2.x: item["title"] directly
                # yfinance 1.x:   item["content"]["title"]
                content = item.get("content", {})
                title = (
                    (content.get("title", "") if isinstance(content, dict) else "")
                    or item.get("title", "")
                )
                if not title or title in seen:
                    continue
                if any(k.lower() in title.lower() for k in KW):
                    seen.add(title)
                    headlines.append(title)
                if len(headlines) >= 8:
                    break
        except Exception:
            pass
        if len(headlines) >= 8:
            break
    return headlines


# ═══════════════════════════════════════════════════════════════════════════════
#  Breaking-news market alert surveillance
# ═══════════════════════════════════════════════════════════════════════════════
#
# Polls Google News RSS + BBC World RSS every time the fragment fires (every 3
# minutes in app.py).  Headlines are scored against two keyword lists:
#
#   CRITICAL — geopolitical events, market halts, bank collapses, nuclear/war
#   HIGH     — Fed decisions, oil shocks, major earnings, chip bans, recessions
#
# Returns a list of dicts sorted by (severity DESC, age ASC).

# Google News RSS search feeds — each query targets a specific risk cluster
_ALERT_FEEDS: List[tuple] = [
    (
        "https://news.google.com/rss/search?"
        "q=iran+attack+OR+airstrike+OR+%22missile+strike%22+OR+%22nuclear+test%22"
        "+OR+%22war+declared%22+OR+%22north+korea%22+missile"
        "&hl=en-US&gl=US&ceid=US:en",
        "Google News · 軍事地緣",
    ),
    (
        "https://news.google.com/rss/search?"
        "q=%22market+crash%22+OR+%22circuit+breaker%22+OR+%22trading+halted%22"
        "+OR+%22bank+collapse%22+OR+%22bank+failure%22+OR+%22fed+emergency%22"
        "&hl=en-US&gl=US&ceid=US:en",
        "Google News · 市場危機",
    ),
    (
        "https://news.google.com/rss/search?"
        "q=taiwan+invasion+OR+%22taiwan+strait%22+military+OR+%22pla+enters%22"
        "&hl=en-US&gl=US&ceid=US:en",
        "Google News · 台海",
    ),
    (
        "https://news.google.com/rss/search?"
        "q=fomc+OR+%22fed+rate+decision%22+OR+%22rate+hike%22+OR+%22rate+cut%22"
        "+OR+%22emergency+rate%22"
        "&hl=en-US&gl=US&ceid=US:en",
        "Google News · 聯準會",
    ),
    # BBC World — broad geopolitical coverage
    (
        "https://feeds.bbci.co.uk/news/world/rss.xml",
        "BBC World",
    ),
]

# Phrases whose presence anywhere in a headline → CRITICAL alert
_CRITICAL_KW: List[str] = [
    "airstrike", "air strike", "missile strike", "missile attack",
    "nuclear test", "nuclear weapon", "nuclear detonation",
    "war declared", "war begins", "invasion begins",
    "military strike", "armed attack",
    "circuit breaker", "market halted", "market halt", "trading halted",
    "market crash", "stock market crash",
    "bank run", "bank collapse", "bank failure",
    "fed emergency", "emergency rate cut", "emergency rate hike",
    "world war", "nuclear war",
]

# Phrases → HIGH alert (market-moving within hours, not minutes)
_HIGH_KW: List[str] = [
    "fomc", "rate hike", "rate cut", "interest rate decision",
    "oil embargo", "oil surge", "opec", "crude oil",
    "nvidia earnings", "tsmc earnings", "apple earnings",
    "trade war", "chip ban", "semiconductor ban",
    "recession declared", "gdp contraction",
    "taiwan military", "taiwan strait",
    "iran sanction", "iran nuclear", "north korea",
    "earthquake magnitude", "typhoon taiwan",
]


def _rss_age_minutes(pub_str: str) -> int:
    """Return how many minutes ago an RFC-2822 pubDate string was.  -1 if unparseable."""
    from email.utils import parsedate_to_datetime
    try:
        pub = parsedate_to_datetime(pub_str)
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - pub.astimezone(timezone.utc)
        return max(0, int(delta.total_seconds() / 60))
    except Exception:
        return -1


def fetch_market_alerts(hours_back: int = 6) -> List[Dict]:
    """
    Poll RSS feeds for market-critical breaking news from the last `hours_back` hours.

    Returns list of dicts sorted by severity then freshness:
        {title, source, link, severity: 'critical'|'high', age_min, alert_id}
    """
    import hashlib
    import re
    from bs4 import BeautifulSoup

    cutoff_min = hours_back * 60
    seen: set = set()
    alerts: List[Dict] = []

    for feed_url, feed_name in _ALERT_FEEDS:
        try:
            r = requests.get(
                feed_url, timeout=7,
                headers={"User-Agent": "Mozilla/5.0 (compatible; marketalert/1.0)"},
            )
            r.raise_for_status()
            try:
                soup = BeautifulSoup(r.content, "xml")
            except Exception:
                soup = BeautifulSoup(r.content, "html.parser")

            for item in soup.find_all("item")[:30]:
                # ── title ─────────────────────────────────────────────────────
                t_el = item.find("title")
                title = t_el.get_text(strip=True) if t_el else ""
                # Strip any residual HTML tags (Google News sometimes leaves them)
                title = re.sub(r"<[^>]+>", "", title).strip()
                if not title:
                    continue

                # ── link ──────────────────────────────────────────────────────
                l_el = item.find("link")
                link = l_el.get_text(strip=True) if l_el else ""

                # ── age ───────────────────────────────────────────────────────
                p_el = item.find("pubDate")
                pub_str = p_el.get_text(strip=True) if p_el else ""
                age_min = _rss_age_minutes(pub_str)
                if age_min != -1 and age_min > cutoff_min:
                    continue   # too old

                # ── deduplicate on first 55 chars ─────────────────────────────
                key = title.lower()[:55]
                if key in seen:
                    continue
                seen.add(key)

                # ── classify ──────────────────────────────────────────────────
                tl = title.lower()
                severity = None
                for kw in _CRITICAL_KW:
                    if kw in tl:
                        severity = "critical"
                        break
                if not severity:
                    for kw in _HIGH_KW:
                        if kw in tl:
                            severity = "high"
                            break

                if severity:
                    aid = hashlib.md5(title[:80].encode()).hexdigest()[:12]
                    alerts.append({
                        "title":    title,
                        "source":   feed_name,
                        "link":     link,
                        "severity": severity,
                        "age_min":  age_min if age_min != -1 else 0,
                        "alert_id": aid,
                    })
        except Exception:
            continue   # one feed failing should not kill the whole check

    # Critical first, then by freshness (youngest first)
    alerts.sort(key=lambda x: (
        0 if x["severity"] == "critical" else 1,
        x.get("age_min", 9999),
    ))
    return alerts[:12]


# ═══════════════════════════════════════════════════════════════════════════════
#  股票篩選引擎
# ═══════════════════════════════════════════════════════════════════════════════

def score_stock(ticker: str, df: pd.DataFrame, catalyst_bonus: int, foreign_net: float,
                macro_bonus: int = 0, fi_streak_val: int = 0,
                trust_streak_val: int = 0,
                margin_chg_pct: float = 0.0, short_margin_ratio: float = 0.0) -> Dict:
    """
    綜合評分 0-100：
      量能 30 + 動能 22 + 技術(含SEPA) + K棒形態 ±12 + 催化劑 30
      + 外資 ±8 + 外資連買 ±5 + 投信連買 ±7 + 52週突破 ±15 + 美股盤前 ±10
      + 融資融券籌碼 ±5 (contrarian: 融資暴增=-5, 融資大減=+4, 高券資比=+4)

    fi_streak_val:       外資連續買超天數，由 calc_foreign_streak() 提供
    trust_streak_val:    投信連續買超天數，由 calc_trust_streak() 提供
                         台灣最強短線預測信號 — 投信連買 > 外資連買 > 自營
    macro_bonus:         美股隔夜對個股影響（-10~+10）
    margin_chg_pct:      融資今日vs前日餘額% — 散戶逆向指標 (fetch_twse_margin_balance)
    short_margin_ratio:  融券/融資 × 100% — 高券資比潛在軋空 (fetch_twse_margin_balance)
    """
    if df is None or len(df) < 22:
        return {}

    close  = df["Close"]
    volume = df["Volume"]

    # 1. 量能分 (0-30)  — O'Neil CANSLIM S factor: volume surging on up days
    vr = volume_ratio(volume, 20)
    if   vr >= 3.0: vol_score = 30
    elif vr >= 2.0: vol_score = 24
    elif vr >= 1.5: vol_score = 18
    elif vr >= 1.2: vol_score = 12
    else:           vol_score = max(0, int(vr * 6))

    # 2. 價格動能 (0-22) — 加入20日中期趨勢（O'Neil RS + Minervini trend template）
    #    短視只看1d/5d容易錯判：一支回調中的好股因近期下跌被排名壓低
    #    加入 mom20d 讓「中期向上但近期回檔」的股票獲得合理分數
    mom1d  = (float(close.iloc[-1]) / float(close.iloc[-2])  - 1) * 100 if len(close) >= 2  else 0
    mom5d  = (float(close.iloc[-1]) / float(close.iloc[-6])  - 1) * 100 if len(close) >= 6  else 0
    mom20d = (float(close.iloc[-1]) / float(close.iloc[-21]) - 1) * 100 if len(close) >= 21 else mom5d
    # Weight: 20d(most important) > 5d > 1d; cap big single-day spike contribution
    mom_score = min(22, max(0, int(mom20d * 1.0 + mom5d * 0.7 + min(mom1d, 4.0) * 0.8)))

    # 3. 技術指標 — 多層次大師邏輯組合 (0-40, 實際影響視組合而定)
    rsi           = calc_rsi(close)
    macd_hist, macd_prev = calc_macd(close)
    mas           = ma_score(close)
    ma_info       = calc_ma_alignment(close)       # Weinstein Stage Analysis
    bb            = calc_bollinger(close)           # Bollinger Bands
    kd            = calc_stochastic(df)             # KD — 台灣最常用
    obv_tr        = calc_obv_trend(df)              # OBV 量價背離
    pos52w        = calc_52w_position(close)        # Minervini 52週位置

    tech = 0
    # ── RSI 進場區間 (0-8) — 偏好甜蜜區 45-68，避開超買 ──────────────────
    if   38 <= rsi <= 45: tech += 5   # 輕微超賣，回升中
    elif 45 <  rsi <= 68: tech += 8   # 甜蜜進場區
    elif 68 <  rsi <= 78: tech += 3   # 偏熱但可追
    # rsi > 78 → 不加分（app.py 另有 -12 to -30 懲罰）

    # ── MACD 柱狀線 (0-9) — O'Neil: 動能方向最重要 ───────────────────────
    if   macd_hist > 0 and macd_hist > macd_prev: tech += 9   # 柱線放大 = 多頭加速
    elif macd_hist > 0:                            tech += 5   # 柱線正值
    elif macd_hist > macd_prev:                    tech += 2   # 負值但在收斂

    # ── MA 位置 (0-6) ────────────────────────────────────────────────────
    tech += mas * 2   # 0/2/4/6: price above MA5/20/60

    # ── Weinstein Stage + 均線排列 (±6) ─────────────────────────────────
    tech += ma_info["bonus"]   # Stage2 多頭排列 +6; Stage4 空頭 -4

    # ── 布林通道 (Bollinger) (±5) ── 進場時機核心 ───────────────────────
    bb_sig = bb.get("signal", "neutral")
    if   bb_sig == "buy_zone":   tech += 5   # 靠近下軌 = 超賣買入區
    elif bb_sig == "breakout":   tech += 4   # 帶寬壓縮突破
    elif bb_sig == "overbought": tech -= 3   # 靠近上軌超買
    if bb.get("squeeze"):        tech += 2   # VCP 帶寬壓縮 (Minervini)

    # ── KD 隨機指標 (±6) — 台灣最常用進出場訊號 ─────────────────────────
    kd_sig = kd.get("signal", "neutral")
    if   kd_sig == "golden_cross_oversold": tech += 6   # 超賣黃金交叉 = 最強
    elif kd_sig == "golden_cross":          tech += 4   # 黃金交叉
    elif kd_sig == "oversold":              tech += 3   # 超賣（待交叉）
    elif kd_sig == "death_cross_overbought":tech -= 5   # 超買死亡交叉 = 最弱
    elif kd_sig == "death_cross":           tech -= 3   # 死亡交叉
    elif kd_sig == "overbought":            tech -= 2   # 超買

    # ── OBV 量價背離 (+3/-2) — 悄悄建倉 / 機構出貨偵測 ─────────────────
    if obv_tr == "diverge_up": tech += 3   # 量增價不漲 = 機構吸貨
    elif obv_tr == "rising":   tech += 1
    elif obv_tr == "falling":  tech -= 2   # 量價背離下跌 = 機構悄悄出清

    # ── 52週位置（不再加分，由下面 detect_52w_breakout 接管）──────────────
    # pos52w bonus removed: breakout detection below covers this with volume confirmation

    tech = max(-10, tech)   # floor（不讓負分無限累積）

    # 4. K棒形態 (±12) — 台灣慣例: 陽線=紅(漲), 陰線=綠(跌)
    kbar_score, kbar_pattern = calc_kbar_pattern(df)

    # 5. 催化劑 (0-30) + 外資今日淨買 ±8 + 外資連續天數 ±5 + 美股盤前影響
    cat_score  = min(30, catalyst_bonus)
    fi_bonus   = min(8, int(foreign_net / 500)) if foreign_net > 0 else max(-8, int(foreign_net / 500))
    # 外資連續天數（O'Neil CANSLIM I factor）
    if   fi_streak_val >= 5:  streak_bonus =  5
    elif fi_streak_val >= 3:  streak_bonus =  3
    elif fi_streak_val >= 2:  streak_bonus =  1
    elif fi_streak_val <= -5: streak_bonus = -5
    elif fi_streak_val <= -3: streak_bonus = -3
    elif fi_streak_val <= -2: streak_bonus = -1
    else:                      streak_bonus =  0

    # 投信連續天數（台灣最強短線預測信號 — 投信資訊優勢 > 外資）
    if   trust_streak_val >= 5:  trust_bonus =  7
    elif trust_streak_val >= 3:  trust_bonus =  5
    elif trust_streak_val >= 2:  trust_bonus =  2
    elif trust_streak_val <= -5: trust_bonus = -7
    elif trust_streak_val <= -3: trust_bonus = -5
    elif trust_streak_val <= -2: trust_bonus = -2
    else:                         trust_bonus =  0

    # 52週突破偵測（O'Neil #1 買點：量價齊揚突破年高）
    bo         = detect_52w_breakout(df)
    bo_score   = bo["score"]   # -6 (52w low) ~ +15 (confirmed breakout with volume)

    # 融資融券籌碼面 — 散戶逆向指標 (carsonchou/tw-stock-radar approach)
    # 融資暴增 = 散戶追高 = 頭部危險信號 (contrarian bearish)
    # 融資大減 = 弱手出清 = 潛在買點 (contrarian bullish)
    # 高券資比 = 空頭集中 = 潛在軋空燃料 (squeeze potential)
    margin_score = 0
    if   margin_chg_pct >= 25:  margin_score -= 5   # 融資單日暴增25%+，散戶瘋追
    elif margin_chg_pct >= 15:  margin_score -= 3   # 融資明顯增加
    elif margin_chg_pct >=  8:  margin_score -= 1
    elif margin_chg_pct <= -15: margin_score += 4   # 融資大減：弱手清倉，籌碼轉乾淨
    elif margin_chg_pct <=  -8: margin_score += 2   # 融資縮減：散戶離場
    if   short_margin_ratio >= 40: margin_score += 4   # 極高券資比：多頭被空頭壓制 → 潛在軋空
    elif short_margin_ratio >= 25: margin_score += 2   # 中高券資比：空頭有壓力
    elif short_margin_ratio <=  3 and margin_score >= 0: margin_score += 1  # 幾無空頭純多格局
    margin_score = max(-5, min(5, margin_score))

    macro_adj  = max(-10, min(10, int(macro_bonus)))
    total = min(100, max(0, vol_score + mom_score + tech + kbar_score + cat_score
                           + fi_bonus + streak_bonus + trust_bonus + bo_score + macro_adj
                           + margin_score))

    last_price = float(close.iloc[-1])
    atr        = calc_atr(df)
    target_pct = 5.0 if total < 75 else (7.0 if total < 88 else 10.0)

    # 預估賣出時間
    if total >= 88:
        sell_note = "當日收盤前（衝漲停留意）"
    elif total >= 75:
        sell_note = "開盤後達5-7%即可分批賣出"
    else:
        sell_note = "T+1 早盤高點賣出"

    # ── 支撐壓力 / 訊號 / 回測統計 / 四階段計劃 ────────────────────────────
    sr_levels  = calc_support_resistance(df)
    strat_stats = calc_strategy_stats(df)

    _partial = {
        "score": total, "rsi": round(rsi, 1),
        "kd_signal": kd_sig, "bb_signal": bb_sig, "bb_squeeze": bb.get("squeeze", False),
        "stage": ma_info["stage"], "obv_trend": obv_tr,
        "bo_type": bo["type"], "sepa_count": ma_info.get("sepa_count", 0),
        "mom20d": round(mom20d, 2), "trust_bonus": trust_bonus,
    }
    trade_sig  = calc_trading_signal(_partial)
    _partial.update({
        "last_price": last_price, "atr": round(atr, 2),
        "target_price": round(last_price * (1 + target_pct / 100), 2),
        "target_pct": target_pct,
        "stop_loss": round(last_price - 1.5 * atr, 2),
        "ma5": ma_info["ma5"], "ma20": ma_info["ma20"], "ma60": ma_info["ma60"],
        "mom1d": round(mom1d, 2), "vol_ratio": round(vr, 2),
        "kd_signal": kd_sig,
    })
    trade_plan = build_trading_plan(_partial, sr_levels)

    _tinfo     = TECH_UNIVERSE.get(ticker, {})
    _base_code = ticker.replace(".TW", "").replace(".TWO", "")
    return {
        "ticker":      ticker,
        "name":        _tinfo.get("name") or _TW_STOCK_NAMES.get(ticker) or _base_code,
        "en":          _tinfo.get("en", ""),
        "sector":      _tinfo.get("sector", ""),
        "supply":      _tinfo.get("supply", []),
        "score":        total,
        "vol_score":     vol_score,
        "mom_score":     mom_score,
        "tech_score":    tech,
        "kbar_score":    kbar_score,
        "kbar_pattern":  kbar_pattern,
        "cat_score":     cat_score,
        "macro_bonus":   macro_adj,
        "vol_ratio":     round(vr, 2),
        "rsi":           round(rsi, 1),
        "mom1d":         round(mom1d, 2),
        "mom5d":         round(mom5d, 2),
        "mom20d":        round(mom20d, 2),
        # ── 大師指標 ──
        "bb_signal":     bb_sig,
        "bb_pct_b":      bb.get("pct_b", 0.5),
        "bb_squeeze":    bb.get("squeeze", False),
        "bb_upper":      bb.get("upper", 0.0),
        "bb_lower":      bb.get("lower", 0.0),
        "kd_K":          kd.get("K", 50.0),
        "kd_D":          kd.get("D", 50.0),
        "kd_signal":     kd_sig,
        "obv_trend":     obv_tr,
        "stage":         ma_info["stage"],
        "stage_label":   ma_info["label"],
        "ma5":           ma_info["ma5"],
        "ma20":          ma_info["ma20"],
        "ma60":          ma_info["ma60"],
        "ma200":         ma_info.get("ma200"),
        "sepa_count":    ma_info.get("sepa_count", 0),
        "w52_pos":       pos52w["position_pct"],
        "w52_label":     pos52w["label"],
        "bo_type":       bo["type"],
        "bo_label":      bo["label"],
        "bo_pct_vs_high": bo["pct_vs_high"],
        "bo_vol_surge":  bo["vol_surge"],
        "trust_bonus":    trust_bonus,
        "margin_score":   margin_score,
        "margin_chg_pct": margin_chg_pct,
        "short_margin_ratio": short_margin_ratio,
        "last_price":    last_price,
        "atr":          round(atr, 2),
        "target_pct":   target_pct,
        "target_price": round(last_price * (1 + target_pct / 100), 2),
        "stop_loss":    round(last_price - 1.5 * atr, 2),
        "stop_pct":     round((-1.5 * atr / last_price) * 100, 2) if last_price > 0 else 0,
        "sell_note":    sell_note,
        "foreign_net":  foreign_net,
        # ── 新增：支撐壓力 / 交易訊號 / 策略統計 / 四階段計劃 ──
        "sr":           sr_levels,
        "signal":       trade_sig["signal"],
        "signal_conf":  trade_sig["confidence"],
        "signal_buy":   trade_sig["buy_cnt"],
        "signal_sell":  trade_sig["sell_cnt"],
        "signal_reasons": trade_sig["reasons"],
        "stats":        strat_stats,
        "plan":         trade_plan,
    }

# ═══════════════════════════════════════════════════════════════════════════════
#  批次抓取股價
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_prices_batch(tickers: List[str], period: str = "3mo") -> Dict[str, pd.DataFrame]:
    """
    批次下載 yfinance 日K資料。
    yfinance 對台灣股票的 .TW / .TWO 後綴分配不一致（部分上櫃股需用 .TWO）。
    第一輪嘗試原始後綴；第二輪對空白的 .TW ticker 自動改試 .TWO 補齊。
    結果統一以原始 ticker（.TW）為 key，保持上層邏輯一致。
    """
    data: Dict[str, pd.DataFrame] = {}
    chunk = 25

    def _download_chunk(batch: List[str], key_map: Dict[str, str]) -> None:
        """Download one batch; key_map maps download-ticker → storage-ticker."""
        try:
            raw = yf.download(batch, period=period, auto_adjust=True, progress=False, threads=True, timeout=20)
            if isinstance(raw.columns, pd.MultiIndex):
                for t in batch:
                    try:
                        df = raw.xs(t, axis=1, level=1).dropna()
                        if len(df) >= 22:
                            data[key_map[t]] = df
                    except Exception:
                        pass
            else:
                if len(batch) == 1 and len(raw) >= 22:
                    data[key_map[batch[0]]] = raw.dropna()
        except Exception:
            pass

    # ── Round 1: download with original tickers ────────────────────────────────
    for i in range(0, len(tickers), chunk):
        batch = tickers[i:i+chunk]
        _download_chunk(batch, {t: t for t in batch})

    # ── Round 2: retry any .TW ticker that came back empty with .TWO suffix ────
    # yfinance randomly assigns .TW vs .TWO for TPEx/OTC stocks — there is no
    # reliable pattern; the only safe strategy is to try the other suffix.
    failed_tw = [t for t in tickers if t not in data and t.endswith(".TW")]
    if failed_tw:
        two_tickers = [t[:-3] + ".TWO" for t in failed_tw]
        key_map = {two: orig for two, orig in zip(two_tickers, failed_tw)}
        for i in range(0, len(two_tickers), chunk):
            batch = two_tickers[i:i+chunk]
            _download_chunk(batch, key_map)

    return data

# ═══════════════════════════════════════════════════════════════════════════════
#  基本面資料：營收 / 盈利 / 股東會評分
#  Data source: yfinance .info + quarterly_income_stmt (full quarterly statements)
#  TWSE/MOPS opendata APIs return HTML errors — not usable from cloud servers.
# ═══════════════════════════════════════════════════════════════════════════════

def _parse_quarterly_stmt(stmt) -> Dict:
    """
    Extract scoring-ready metrics from yfinance quarterly_income_stmt DataFrame.
    Returns subset of: rev_qoq, rev_yoy_q, gross_margin_latest, gm_trend, ni_yoy_q.
    All fields are optional — absent when data is insufficient.
    """
    result: Dict = {}
    try:
        cols = sorted(stmt.columns, reverse=True)
        if len(cols) < 2:
            return result

        def _row(label):
            if label in stmt.index:
                s = stmt.loc[label, cols].dropna()
                return s if len(s) >= 2 else None
            return None

        rev = _row("Total Revenue") or _row("Operating Revenue")
        gp  = _row("Gross Profit")
        ni  = _row("Net Income")

        if rev is None:
            return result

        rev_latest = float(rev.iloc[0])
        rev_prev   = float(rev.iloc[1])

        if rev_prev > 0:
            result["rev_qoq"] = (rev_latest / rev_prev) - 1

        if len(rev) >= 5:
            base = float(rev.iloc[4])
            if base > 0:
                result["rev_yoy_q"] = (rev_latest / base) - 1

        if gp is not None and rev_latest > 0:
            gm_vals = []
            for i in range(min(4, len(gp), len(rev))):
                rv = float(rev.iloc[i])
                gv = float(gp.iloc[i])
                if rv > 0:
                    gm_vals.append(gv / rv)
            if gm_vals:
                result["gross_margin_latest"] = gm_vals[0]
                if len(gm_vals) >= 3:
                    recent = sum(gm_vals[:2]) / 2
                    prior  = sum(gm_vals[2:]) / len(gm_vals[2:])
                    if   recent > prior + 0.015: result["gm_trend"] = "improving"
                    elif recent < prior - 0.015: result["gm_trend"] = "declining"
                    else:                        result["gm_trend"] = "stable"
                elif len(gm_vals) >= 2:
                    if   gm_vals[0] > gm_vals[1] + 0.015: result["gm_trend"] = "improving"
                    elif gm_vals[0] < gm_vals[1] - 0.015: result["gm_trend"] = "declining"
                    else:                                   result["gm_trend"] = "stable"

        if ni is not None and len(ni) >= 5:
            ni_latest = float(ni.iloc[0])
            ni_base   = float(ni.iloc[4])
            if ni_base > 0 and ni_latest > 0:
                result["ni_yoy_q"] = (ni_latest / ni_base) - 1

    except Exception:
        pass
    return result


def fetch_yf_fundamentals_batch(tickers: List[str], max_workers: int = 6) -> Dict:
    """
    Parallel yfinance .info fetch for fundamental data.
    Returns {ticker: {"rev_growth": float|None, "earn_growth": float|None,
                       "profit_margin": float|None, "roe": float|None}}
    rev_growth / earn_growth are YoY ratios: 0.35 = +35%, -0.20 = -20%.

    Uses ThreadPoolExecutor with a hard wall-time cap (60s total).
    Tickers that don't respond in time are skipped — result still usable.
    All errors silently return {}.
    """
    from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
    import io, contextlib

    if not HAS_YF:
        return {}

    def _one(sym: str):
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                t = yf.Ticker(sym)
                info = t.info
            rg = info.get("revenueGrowth")
            eg = info.get("earningsGrowth")
            pm = info.get("profitMargins")
            roe = info.get("returnOnEquity")
            t_eps = info.get("trailingEps")
            f_eps = info.get("forwardEps")
            t_pe  = info.get("trailingPE")
            f_pe  = info.get("forwardPE")
            peg   = info.get("pegRatio")

            q_data: Dict = {}
            try:
                buf2 = io.StringIO()
                with contextlib.redirect_stdout(buf2), contextlib.redirect_stderr(buf2):
                    stmt = t.quarterly_income_stmt
                if stmt is not None and not stmt.empty:
                    q_data = _parse_quarterly_stmt(stmt)
            except Exception:
                pass

            if rg is None and eg is None and t_eps is None and not q_data:
                return sym, {"yf_error": True}
            return sym, {
                "rev_growth":    rg,
                "earn_growth":   eg,
                "profit_margin": pm,
                "roe":           roe,
                "trailing_eps":  t_eps,
                "forward_eps":   f_eps,
                "trailing_pe":   t_pe,
                "forward_pe":    f_pe,
                "peg_ratio":     peg,
                **q_data,
            }
        except Exception:
            return sym, {}

    result: Dict = {}
    # Submit all futures; collect completed ones within 60s wall time
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        pending = {ex.submit(_one, t): t for t in tickers}
        done, _ = wait(pending, timeout=90)
        for fut in done:
            try:
                sym, d = fut.result()
                if d:
                    result[sym] = d
            except Exception:
                pass
    return result


def fetch_twse_monthly_revenue() -> Dict[str, float]:
    """
    月營收年增率 from MOPS HTML (公開資訊觀測站)。
    URL: https://mops.twse.com.tw/nas/t21/{market}/t21sc03_{ROC_YEAR}_{MONTH}_0.html
    One request per market (sii/otc) gets ALL companies — far more efficient than per-ticker APIs.

    Returns {ticker: yoy_pct}, e.g. {"2330.TW": 42.5, "2454.TW": 18.3}
    Returns {} gracefully when MOPS is unreachable from cloud servers.

    MOPS column layout (0-indexed):
      0: 公司代號  1: 名稱  2: 當月營收  3: 上月  4: 去年同月
      5: 月增%  6: 年增%  7: 累計  8: 去年累計  9: 累計年增%
    """
    from bs4 import BeautifulSoup
    from datetime import timezone as _tz, timedelta as _td

    tw_now = datetime.now(tz=_tz(_td(hours=8)))
    # Revenue reports published by the 10th of each month; use prior month if < 10th
    if tw_now.day < 10:
        first_of_month = tw_now.replace(day=1)
        target = (first_of_month - _td(days=1))
    else:
        target = tw_now

    roc_year = target.year - 1911
    month    = target.month
    result: Dict[str, float] = {}

    for market, suffix in (("sii", ".TW"), ("otc", ".TWO")):
        url = (f"https://mops.twse.com.tw/nas/t21/{market}/"
               f"t21sc03_{roc_year}_{month}_0.html")
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code != 200:
                continue
            r.encoding = "big5"
            soup = BeautifulSoup(r.text, "lxml")
            for table in soup.find_all("table"):
                for row in table.find_all("tr"):
                    cols = row.find_all("td")
                    if len(cols) < 7:
                        continue
                    code = cols[0].get_text(strip=True)
                    if not code.isdigit() or len(code) != 4:
                        continue
                    yoy_raw = cols[6].get_text(strip=True).replace(",", "").replace("+", "")
                    try:
                        result[code + suffix] = float(yoy_raw)
                    except (ValueError, TypeError):
                        pass
        except Exception:
            pass
    return result


def fetch_tpex_monthly_revenue() -> Dict:
    """TPEx monthly revenue is included in fetch_twse_monthly_revenue() (otc market). Returns {}."""
    return {}


def fetch_twse_margin_balance() -> Dict[str, Dict]:
    """
    融資融券餘額 from TWSE MI_MARGN — one request, all listed stocks.
    URL: https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date=YYYYMMDD&selectType=ALL&response=json

    Key signals:
      margin_chg_pct   — 融資今日/前日比% (>+15% = 散戶追高 → negative; <-10% = 弱手出清 → positive)
      short_margin_ratio — 融券/融資 × 100% (>30% = 潛在軋空 → positive)

    Returns {ticker: {margin_bal, margin_prev, short_bal, margin_chg_pct, short_margin_ratio}}
    Returns {} gracefully on failure (holiday / geo-block).
    """
    from datetime import timezone as _tz, timedelta as _td

    tw_now = datetime.now(tz=_tz(_td(hours=8)))
    result: Dict[str, Dict] = {}

    def _n(v) -> int:
        s = str(v).strip().replace(",", "").replace("+", "").replace(" ", "")
        return 0 if s in ("", "-", "--", "X") else int(round(float(s))) if s.replace(".", "").replace("-", "").isdigit() else 0

    for day_offset in range(6):
        d = tw_now - _td(days=day_offset)
        if d.weekday() >= 5:
            continue
        url = (f"https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN"
               f"?date={d.strftime('%Y%m%d')}&selectType=ALL&response=json")
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code != 200:
                continue
            j = r.json()
            if j.get("stat") != "OK":
                continue
            tables = j.get("tables", [])
            # Pick the individual-stock detail table (most rows, 4-digit codes, ≥14 cols)
            best = None
            for t in tables:
                rows = t.get("data", [])
                fields = t.get("fields", [])
                if not rows or len(fields) < 12:
                    continue
                sample = sum(1 for row in rows[:20]
                             if row and len(str(row[0]).strip()) == 4 and str(row[0]).strip().isdigit())
                if sample >= 5:
                    if best is None or len(rows) > len(best.get("data", [])):
                        best = t
            if best is None:
                continue
            # Typical column layout (0-indexed):
            # 0=代號 1=名稱 | 融資: 2買 3賣 4現償 5前餘 6今餘 7限額 | 融券: 8買 9賣 10現償 11前餘 12今餘 13限額
            for row in best.get("data", []):
                if len(row) < 13:
                    continue
                code = str(row[0]).strip()
                if len(code) != 4 or not code.isdigit() or code.startswith("00"):
                    continue
                m_today = _n(row[6])
                m_prev  = _n(row[5])
                s_today = _n(row[12])
                if m_today <= 0 and s_today <= 0:
                    continue
                margin_chg_pct     = round((m_today - m_prev) / m_prev * 100, 1) if m_prev > 0 else 0.0
                short_margin_ratio = round(s_today / m_today * 100, 1) if m_today > 0 else 0.0
                result[code + ".TW"] = {
                    "margin_bal":          m_today,
                    "margin_prev":         m_prev,
                    "short_bal":           s_today,
                    "margin_chg_pct":      margin_chg_pct,
                    "short_margin_ratio":  short_margin_ratio,
                }
            if result:
                return result
        except Exception:
            continue
    return result


def fetch_twse_shareholder_meetings() -> Dict:
    """
    TWSE 股東常會日期。
    NOTE: openapi.twse.com.tw returns a static HTML 404 page for all endpoints
    when accessed from non-Taiwan IPs (e.g. Streamlit Cloud US servers).
    Returns {} gracefully; meeting data sourced from news catalysts instead.
    """
    return {}


def fetch_intraday_flow(ticker: str) -> Dict:
    """
    Wall-Street-style intraday order flow analysis for a single Taiwan stock.

    Method — candle-body delta (standard retail order-flow technique):
      buy_vol_per_bar  = volume × (close − low) / (high − low)
      sell_vol_per_bar = volume − buy_vol_per_bar
    This estimates what fraction of each bar's volume was buyer-initiated
    (aggressive market orders hitting the ask) vs seller-initiated (hitting bid).

    Key outputs:
      vwap          – Volume-Weighted Average Price; institutional benchmark
      buy_pct       – session buy vol as % of total estimated vol
      cum_delta     – running net (buy_vol − sell_vol) across session
      delta_trend   – "up" / "down" / "flat" for last 6 bars of delta
      bar_seq       – last 12 bars each "B" (bullish close) or "S" (bearish)
      signal        – composite directional label (6 tiers from 強力看多 to 空方壓制)
      signal_score  – raw int score driving the signal
      signal_reasons– list of human-readable Chinese explanations

    Returns {} on any error or if fewer than 3 bars available.
    Data source: yfinance period="1d" interval="5m" (falls back to 10-day daily if < 3 bars).
    """
    try:
        tk = yf.Ticker(ticker)
        df = tk.history(period="1d", interval="5m")
        is_daily_fallback = False

        # ── Fallback: use daily candles when intraday data is sparse ─────────
        if df is None or len(df) < 3:
            try:
                df_daily = tk.history(period="10d", interval="1d")
                if df_daily is not None and len(df_daily) >= 2:
                    df = df_daily.copy()
                    is_daily_fallback = True
                else:
                    return {}
            except Exception:
                return {}
        else:
            df = df.copy()

        # ── VWAP (typical-price × volume weighted) ────────────────────────
        df["tp"]     = (df["High"] + df["Low"] + df["Close"]) / 3.0
        df["tp_vol"] = df["tp"] * df["Volume"]
        total_vol    = float(df["Volume"].sum())
        vwap         = float(df["tp_vol"].sum() / total_vol) if total_vol > 0 else 0.0
        last_close   = float(df["Close"].iloc[-1])
        above_vwap   = last_close > vwap

        # ── Candle-body buy/sell estimation ──────────────────────────────
        def _buy_ratio(row: pd.Series) -> float:
            rng = float(row["High"]) - float(row["Low"])
            if rng <= 0:
                return 0.5
            return max(0.0, min(1.0, (float(row["Close"]) - float(row["Low"])) / rng))

        df["br"]       = df.apply(_buy_ratio, axis=1)
        df["buy_vol"]  = df["Volume"] * df["br"]
        df["sell_vol"] = df["Volume"] * (1.0 - df["br"])

        total_buy  = float(df["buy_vol"].sum())
        total_sell = float(df["sell_vol"].sum())
        total_est  = total_buy + total_sell
        buy_pct    = (total_buy / total_est * 100.0) if total_est > 0 else 50.0

        # ── Cumulative delta (running net buying pressure) ────────────────
        df["delta"]   = df["buy_vol"] - df["sell_vol"]
        df["cum_del"] = df["delta"].cumsum()
        cum_delta     = float(df["cum_del"].iloc[-1])
        delta_trend   = "flat"
        if len(df) >= 6:
            prev6 = float(df["cum_del"].iloc[-6])
            cur   = float(df["cum_del"].iloc[-1])
            if   abs(prev6) < 1:           delta_trend = "up" if cur > 0 else "down"
            elif cur > prev6 * 1.05:       delta_trend = "up"
            elif cur < prev6 * 0.95:       delta_trend = "down"

        # ── Last-12 bar classification ────────────────────────────────────
        recent  = df.tail(12)
        bar_seq = [
            "B" if float(r["Close"]) >= float(r["Open"]) else "S"
            for _, r in recent.iterrows()
        ]
        consec_buy = consec_sell = 0
        for b in reversed(bar_seq):
            if b == "B":
                if consec_sell > 0: break
                consec_buy += 1
            else:
                if consec_buy > 0: break
                consec_sell += 1

        # ── Volume pace vs 3-month daily average ─────────────────────────
        vol_pace_pct = 100
        try:
            avg_vol = tk.fast_info.three_month_average_volume or 0
            bars_in_session = 78        # TWSE 09:00–13:30 = 78 × 5 min
            bars_now = max(len(df), 1)
            if avg_vol > 0:
                projected    = total_vol * (bars_in_session / bars_now)
                vol_pace_pct = int(projected / avg_vol * 100)
        except Exception:
            pass

        # ── Multi-factor Wall Street directional signal ───────────────────
        sig = 0
        # 1. Buy-pressure weight
        if   buy_pct >= 65: sig += 3
        elif buy_pct >= 58: sig += 2
        elif buy_pct >= 52: sig += 1
        elif buy_pct <= 35: sig -= 3
        elif buy_pct <= 42: sig -= 2
        elif buy_pct <= 48: sig -= 1
        # 2. VWAP — single most important institutional benchmark
        if above_vwap: sig += 2
        else:          sig -= 2
        # 3. Bar-sequence momentum
        if   consec_buy  >= 4: sig += 1
        elif consec_sell >= 4: sig -= 1
        # 4. Cumulative delta direction
        if   delta_trend == "up":   sig += 1
        elif delta_trend == "down": sig -= 1
        # 5. Volume surge with directional confirmation
        if vol_pace_pct >= 130 and buy_pct >= 55:  sig += 1
        elif vol_pace_pct >= 130 and buy_pct <= 45: sig -= 1

        # Signal label + color (6 tiers)
        if   sig >= 5:  signal, sig_col = "強力看多 \U0001f680", "#00e676"
        elif sig >= 3:  signal, sig_col = "多方主導 \U0001f4c8", "#4caf7d"
        elif sig >= 1:  signal, sig_col = "偏多觀察 \U0001f7e1", "#ffd54f"
        elif sig >= -1: signal, sig_col = "多空均衡 ⚖️",  "#90a4ae"
        elif sig >= -3: signal, sig_col = "偏空謹慎 \U0001f536", "#ff9800"
        else:           signal, sig_col = "空方壓制 \U0001f4c9", "#ef5350"

        # ── Human-readable reasons ────────────────────────────────────────
        reasons: List[str] = []
        if   buy_pct >= 62:
            reasons.append(f"主動買單佔 {buy_pct:.0f}%，買方積極進場")
        elif buy_pct <= 38:
            reasons.append(f"主動賣單佔 {100-buy_pct:.0f}%，賣方出貨明顯")
        else:
            reasons.append(f"買賣盤接近均衡（買 {buy_pct:.0f}% / 賣 {100-buy_pct:.0f}%）")

        vd = abs(last_close - vwap) / vwap * 100 if vwap > 0 else 0
        if above_vwap:
            reasons.append(
                f"現價 NT${last_close:.1f} 站上 VWAP NT${vwap:.1f}"
                f"（+{vd:.1f}%），多方掌控節奏"
            )
        else:
            reasons.append(
                f"現價 NT${last_close:.1f} 跌破 VWAP NT${vwap:.1f}"
                f"（-{vd:.1f}%），空方主導"
            )

        if   consec_buy  >= 4:
            reasons.append(f"連續 {consec_buy} 根陽線，上升動能強勁")
        elif consec_buy  >= 2:
            reasons.append(f"連續 {consec_buy} 根陽線，短線偏多")
        elif consec_sell >= 4:
            reasons.append(f"連續 {consec_sell} 根陰線，下跌壓力持續")
        elif consec_sell >= 2:
            reasons.append(f"連續 {consec_sell} 根陰線，短線偏弱")

        if   vol_pace_pct >= 140:
            reasons.append(f"今日成交量節奏 {vol_pace_pct}%，資金大量湧入")
        elif vol_pace_pct >= 115:
            reasons.append(f"成交量活躍（{vol_pace_pct}% 正常節奏）")
        elif vol_pace_pct < 70:
            reasons.append(f"成交量清淡（{vol_pace_pct}%），市場觀望")

        if delta_trend == "up" and sig >= 2:
            reasons.append("累積買超持續擴大，機構資金逐步建倉")
        elif delta_trend == "down" and sig <= -2:
            reasons.append("累積賣超持續加大，法人可能逢高出清")

        return {
            "vwap":               round(vwap, 1),
            "last_price":         round(last_close, 1),
            "above_vwap":         above_vwap,
            "buy_pct":            round(buy_pct, 1),
            "sell_pct":           round(100.0 - buy_pct, 1),
            "cum_delta":          int(cum_delta),
            "delta_trend":        delta_trend,
            "bar_seq":            bar_seq,
            "consec_buy":         consec_buy,
            "consec_sell":        consec_sell,
            "vol_pace_pct":       vol_pace_pct,
            "signal":             signal,
            "signal_color":       sig_col,
            "signal_score":       sig,
            "signal_reasons":     reasons,
            "bars":               len(df),
            "is_daily_fallback":  is_daily_fallback,
        }
    except Exception:
        return {}


def calc_fundamental_bonus(ticker: str, fund_map: Dict, meeting_map: Dict) -> Dict:
    """
    基本面加權評分 (-15 ~ +30 分)。來源：yfinance 季報數據。

    ① 營收年增率 (revenueGrowth):     >=80% +15 ... <-20% -9
    ② 盈利年增率 (earningsGrowth):    >=80%  +8 ... <-20% -5
    ③ 高毛利    (profitMargins >=25%): +3
    ④ EPS 每股盈餘:
       - 虧損 (trailingEps < 0): -8
       - 前瞻 EPS 升級 >=50%: +6   >=20%: +3
       - 前瞻 EPS 下調 <-20%: -4
    ⑤ 估值 (forwardPE):
       <12 -> +4   <18 -> +2   >50 -> -3   >70 -> -6
    ⑥ PEG 比率: <0.8 -> +3   >3 -> -2

    Returns {"bonus", "labels", "rev_yoy", "earn_yoy",
             "trailing_eps", "forward_eps", "forward_pe", "peg_ratio"}
    """
    bonus = 0
    labels: List[str] = []
    rev_yoy  = 0.0
    earn_yoy = 0.0
    fund = fund_map.get(ticker, {})
    yf_error = fund.get("yf_error", False)

    if fund and not yf_error:
        rg    = fund.get("rev_growth")
        eg    = fund.get("earn_growth")
        pm    = fund.get("profit_margin")
        t_eps = fund.get("trailing_eps")
        f_eps = fund.get("forward_eps")
        f_pe  = fund.get("forward_pe")
        peg   = fund.get("peg_ratio")

        # -- Revenue YoY --
        if rg is not None:
            rev_yoy = rg * 100
            if   rg >= 0.80: bonus += 15; labels.append(f"\u71df\u6536\u5e74\u589e +{rev_yoy:.0f}% \U0001f680")
            elif rg >= 0.50: bonus += 12; labels.append(f"\u71df\u6536\u5e74\u589e +{rev_yoy:.0f}% \U0001f4c8")
            elif rg >= 0.30: bonus +=  9; labels.append(f"\u71df\u6536\u5e74\u589e +{rev_yoy:.0f}%")
            elif rg >= 0.15: bonus +=  6; labels.append(f"\u71df\u6536\u5e74\u589e +{rev_yoy:.0f}%")
            elif rg >= 0.05: bonus +=  3; labels.append(f"\u71df\u6536\u5e74\u589e +{rev_yoy:.0f}%")
            elif rg >= 0.00: bonus +=  1
            elif rg >= -0.10: bonus -= 3
            elif rg >= -0.20: bonus -= 6
            else:             bonus -= 9; labels.append(f"\u71df\u6536\u5e74\u6e1b {rev_yoy:.0f}% \u26a0\ufe0f")

        # -- Earnings YoY --
        if eg is not None:
            earn_yoy = eg * 100
            if   eg >= 0.80: bonus +=  8; labels.append(f"\u76c8\u5229\u5e74\u589e +{earn_yoy:.0f}% \U0001f4b0")
            elif eg >= 0.40: bonus +=  6; labels.append(f"\u76c8\u5229\u5e74\u589e +{earn_yoy:.0f}%")
            elif eg >= 0.20: bonus +=  4; labels.append(f"\u76c8\u5229\u5e74\u589e +{earn_yoy:.0f}%")
            elif eg >= 0.00: bonus +=  2
            elif eg >= -0.20: bonus -= 2
            else:             bonus -= 5; labels.append(f"\u76c8\u5229\u5e74\u6e1b {earn_yoy:.0f}% \u26a0\ufe0f")

        # -- Profit margin --
        if pm is not None and pm >= 0.25:
            bonus += 3
            labels.append(f"\u9ad8\u6bdb\u5229 {pm*100:.0f}%")

        # -- EPS --
        if t_eps is not None:
            if t_eps < 0:
                bonus -= 8
                labels.append(f"\u865f\u640d EPS {t_eps:.1f} \u26a0\ufe0f")
            elif f_eps is not None and t_eps > 0:
                eps_chg = (f_eps - t_eps) / abs(t_eps)
                if   eps_chg >= 0.50: bonus += 6; labels.append(f"EPS\u9810\u4f30\u5347 +{eps_chg*100:.0f}% \U0001f4b9")
                elif eps_chg >= 0.20: bonus += 3; labels.append(f"EPS\u9810\u4f30\u5347 +{eps_chg*100:.0f}%")
                elif eps_chg >= 0.00: bonus += 1
                elif eps_chg <= -0.20: bonus -= 4; labels.append(f"EPS\u9810\u4f30\u964d {eps_chg*100:.0f}%")

        # -- Forward PE --
        if f_pe is not None and f_pe > 0:
            if   f_pe < 12: bonus += 4; labels.append(f"\u4f4e\u672c\u76ca\u6bd4 {f_pe:.0f}x \U0001f48e")
            elif f_pe < 18: bonus += 2
            elif f_pe > 70: bonus -= 6
            elif f_pe > 50: bonus -= 3

        # -- PEG --
        if peg is not None and peg > 0:
            if   peg < 0.8: bonus += 3; labels.append(f"PEG {peg:.1f} \u4f4e\u4f30")
            elif peg > 3.0: bonus -= 2

        # -- \u6708\u71df\u6536\u5e74\u589e\u7387 (MOPS \u6700\u5373\u6642\u4fe1\u865f \u2014 \u6bd4\u5b63\u5831\u5feb2\u500b\u6708) --
        monthly_yoy = fund.get("monthly_rev_yoy")
        if monthly_yoy is not None:
            if   monthly_yoy >= 50: bonus += 8; labels.append(f"\u6708\u71df\u6536\u5e74\u589e +{monthly_yoy:.0f}% \U0001f680")
            elif monthly_yoy >= 30: bonus += 6; labels.append(f"\u6708\u71df\u6536\u5e74\u589e +{monthly_yoy:.0f}%")
            elif monthly_yoy >= 15: bonus += 4; labels.append(f"\u6708\u71df\u6536\u5e74\u589e +{monthly_yoy:.0f}%")
            elif monthly_yoy >=  5: bonus += 2
            elif monthly_yoy >= -10: bonus -= 2
            elif monthly_yoy >= -20: bonus -= 4
            else:                    bonus -= 6; labels.append(f"\u6708\u71df\u6536\u5e74\u6e1b {monthly_yoy:.0f}% \u26a0\ufe0f")

        # -- Quarterly gross margin trend (from quarterly_income_stmt) --
        gm_trend  = fund.get("gm_trend")
        gm_latest = fund.get("gross_margin_latest")
        if gm_trend == "improving":
            bonus += 4
            _gm_s = f" {gm_latest*100:.1f}%" if gm_latest else ""
            labels.append(f"\u6bdb\u5229\u7387\u64f4\u5f35\u2191{_gm_s}")
        elif gm_trend == "declining":
            bonus -= 3
            labels.append("\u6bdb\u5229\u7387\u6536\u7e2e\u2193 \u26a0\ufe0f")

        # -- Quarterly revenue QoQ (sequential acceleration signal) --
        rev_qoq = fund.get("rev_qoq")
        if rev_qoq is not None:
            if   rev_qoq >= 0.20: bonus += 5; labels.append(f"\u5b63\u71df\u6536\u74b0\u6bd4 +{rev_qoq*100:.0f}% \U0001f680")
            elif rev_qoq >= 0.10: bonus += 3; labels.append(f"\u5b63\u71df\u6536\u74b0\u6bd4 +{rev_qoq*100:.0f}%")
            elif rev_qoq >= 0.05: bonus += 1
            elif rev_qoq <= -0.20: bonus -= 4; labels.append(f"\u5b63\u71df\u6536\u74b0\u6bd4 {rev_qoq*100:.0f}% \u26a0\ufe0f")
            elif rev_qoq <= -0.10: bonus -= 2

        # -- Quarterly net income YoY (fills gap when earningsGrowth unavailable) --
        ni_yoy_q = fund.get("ni_yoy_q")
        if ni_yoy_q is not None and eg is None:
            earn_yoy = ni_yoy_q * 100
            if   ni_yoy_q >= 0.80: bonus += 7; labels.append(f"\u6de8\u5229\u5e74\u589e +{earn_yoy:.0f}% \U0001f4b0")
            elif ni_yoy_q >= 0.40: bonus += 5; labels.append(f"\u6de8\u5229\u5e74\u589e +{earn_yoy:.0f}%")
            elif ni_yoy_q >= 0.20: bonus += 3; labels.append(f"\u6de8\u5229\u5e74\u589e +{earn_yoy:.0f}%")
            elif ni_yoy_q >= 0.00: bonus += 1
            elif ni_yoy_q <= -0.20: bonus -= 4; labels.append(f"\u6de8\u5229\u5e74\u6e1b {earn_yoy:.0f}% \u26a0\ufe0f")

    # -- Shareholder meetings (API unavailable) --
    code = ticker.replace(".TW", "").replace(".TWO", "")
    days = meeting_map.get(code)
    if days is not None:
        if   days <= 14: bonus += 5; labels.append(f"\u80a1\u6771\u6703 {max(0,days)}\u65e5\u5f8c \U0001f5d3")
        elif days <= 30: bonus += 4; labels.append(f"\u80a1\u6771\u6703 {days}\u65e5\u5f8c")
        elif days <= 60: bonus += 2; labels.append(f"\u80a1\u6771\u6703 {days}\u65e5\u5f8c")

    return {
        "bonus":               max(-15, min(40, bonus)),
        "labels":              labels[:4],
        "rev_yoy":             rev_yoy,
        "earn_yoy":            earn_yoy,
        "trailing_eps":        fund.get("trailing_eps")        if (fund and not yf_error) else None,
        "forward_eps":         fund.get("forward_eps")         if (fund and not yf_error) else None,
        "forward_pe":          fund.get("forward_pe")          if (fund and not yf_error) else None,
        "peg_ratio":           fund.get("peg_ratio")           if (fund and not yf_error) else None,
        "gross_margin_latest": fund.get("gross_margin_latest") if (fund and not yf_error) else None,
        "gm_trend":            fund.get("gm_trend")            if (fund and not yf_error) else None,
        "rev_qoq":             fund.get("rev_qoq")             if (fund and not yf_error) else None,
        "yf_error":            yf_error,
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  持股分析
# ═══════════════════════════════════════════════════════════════════════════════

def analyze_holdings(price_data: Dict[str, pd.DataFrame]) -> List[Dict]:
    result = []
    for ticker, info in MY_HOLDINGS.items():
        df = price_data.get(ticker)
        if df is None or len(df) < 2:
            result.append({"ticker": ticker, "name": info["name"], "price": 0, "chg": 0, "error": True})
            continue
        p1 = float(df["Close"].iloc[-1])
        p0 = float(df["Close"].iloc[-2])
        chg = (p1 / p0 - 1) * 100
        wk_high = float(df["Close"].iloc[-5:].max()) if len(df) >= 5 else p1
        wk_low  = float(df["Close"].iloc[-5:].min()) if len(df) >= 5 else p1
        result.append({
            "ticker": ticker, "name": info["name"],
            "price": p1, "chg": chg,
            "wk_high": wk_high, "wk_low": wk_low,
            "error": False,
        })
    return result

# ═══════════════════════════════════════════════════════════════════════════════
#  顯示函數
# ═══════════════════════════════════════════════════════════════════════════════

def make_bar(score: int, width: int = 10) -> str:
    filled = round(score / 100 * width)
    color = "green" if score >= 75 else ("yellow" if score >= 55 else "red")
    bar = "█" * filled + "░" * (width - filled)
    return f"[{color}]{bar}[/{color}]"

def chg_color(pct: float) -> str:
    if pct >= 0.5:  return "bold green"
    if pct > 0:     return "green"
    if pct <= -0.5: return "bold red"
    return "red"

def supply_badge(supply: List[str]) -> str:
    badges = {
        "NVIDIA": "[bold cyan]NV[/bold cyan]",
        "AMD":    "[bold magenta]AMD[/bold magenta]",
        "Apple":  "[bold white]APL[/bold white]",
        "AI":     "[bold yellow]AI[/bold yellow]",
        "CoWoS":  "[bold green]CoW[/bold green]",
        "ETF":    "[dim]ETF[/dim]",
    }
    return " ".join(badges[s] for s in supply if s in badges) or "—"

def print_header(now: datetime):
    title = Text(justify="center")
    title.append("  台灣科技股盤前分析系統  ", style="bold white on blue")
    title.append(f"  {now.strftime('%Y-%m-%d  %H:%M')}  ", style="white on dark_blue")
    console.print()
    console.print(Align.center(title))
    console.print(Align.center(Text("晶片・記憶體・AI｜NVIDIA / AMD / Apple 上游供應鏈深度追蹤", style="dim")))
    console.print()

def print_market_summary(summary: Dict):
    if not summary:
        return
    console.print(Rule("[bold]大盤概況[/bold]", style="blue"))
    grid = Table.grid(padding=(0, 3))
    grid.add_row(
        f"[dim]加權指數[/dim]",
        f"[bold]{summary.get('index','--')}[/bold]",
        f"[dim]漲跌[/dim]",
        f"{summary.get('change','--')}",
        f"[dim]成交量[/dim]",
        f"{summary.get('amount','--')}",
    )
    console.print(Align.center(grid))
    console.print()

def print_holdings(holdings: List[Dict]):
    console.print(Rule("[bold yellow]我的持股[/bold yellow]", style="yellow"))
    t = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="bold")
    t.add_column("代號", style="bold", width=8)
    t.add_column("名稱", width=14)
    t.add_column("昨收", justify="right", width=10)
    t.add_column("漲跌%", justify="right", width=10)
    t.add_column("5日高", justify="right", width=10)
    t.add_column("5日低", justify="right", width=10)
    t.add_column("狀態", width=16)

    for h in holdings:
        if h.get("error"):
            t.add_row(h["ticker"], h["name"], "—", "—", "—", "—", "[dim]資料不足[/dim]")
            continue
        chg   = h["chg"]
        color = chg_color(chg)
        arrow = "▲" if chg >= 0 else "▼"
        sign  = "+" if chg >= 0 else ""
        p = h["price"]
        status = "🔥 強勢" if chg >= 3 else ("📈 上漲" if chg >= 0.5 else ("⚠ 弱勢" if chg < -1.5 else "➡ 持平"))
        t.add_row(
            h["ticker"].replace(".TW", ""),
            h["name"],
            f"{p:.1f}",
            f"[{color}]{arrow}{sign}{chg:.2f}%[/{color}]",
            f"{h.get('wk_high',0):.1f}",
            f"{h.get('wk_low',0):.1f}",
            status,
        )
    console.print(t)
    console.print()

def print_news(headlines: List[str]):
    console.print(Rule("[bold cyan]今日早盤新聞重點[/bold cyan]", style="cyan"))
    if not headlines:
        console.print("  [dim]新聞抓取中，請稍候…[/dim]\n")
        return
    for h in headlines[:8]:
        console.print(f"  [cyan]●[/cyan] {h}")
    console.print()

def print_recommendations(picks: List[Dict], news_list: List[Dict]):
    console.print(Rule(
        "[bold green]今日精選 5 支潛力股  （預估漲幅 5% ～ 漲停）[/bold green]",
        style="green"
    ))
    console.print()

    for rank, p in enumerate(picks, 1):
        catalyst_labels = get_catalyst_labels(p["ticker"], news_list)
        cat_str = "  ".join(catalyst_labels) if catalyst_labels else "技術面突破"

        supply_str = supply_badge(p.get("supply", []))
        chg_str = (
            f"[green]+{p['mom1d']:.2f}%[/green]" if p["mom1d"] >= 0
            else f"[red]{p['mom1d']:.2f}%[/red]"
        )
        fi_str = (
            f"[green]+{p['foreign_net']:.0f}千張[/green]" if p["foreign_net"] > 0
            else (f"[red]{p['foreign_net']:.0f}千張[/red]" if p["foreign_net"] < 0 else "[dim]N/A[/dim]")
        )

        header = (
            f" #{rank}  "
            f"[bold yellow]{p['ticker'].replace('.TW','')} {p['name']}[/bold yellow]"
            f"  [dim]{p['en']}[/dim]"
            f"  [{p['sector']}]"
            f"  {supply_str}"
        )

        body = Table.grid(padding=(0, 2))
        body.add_row(
            f"[dim]昨收[/dim] [bold]{p['last_price']:.1f}[/bold]",
            f"[dim]昨漲[/dim] {chg_str}",
            f"[dim]5日[/dim] [white]{p['mom5d']:+.1f}%[/white]",
            f"[dim]量比[/dim] [{'green' if p['vol_ratio']>=1.5 else 'white'}]{p['vol_ratio']:.1f}x[/{'green' if p['vol_ratio']>=1.5 else 'white'}]",
            f"[dim]RSI[/dim] {p['rsi']:.0f}",
            f"[dim]外資[/dim] {fi_str}",
        )
        body.add_row()
        body.add_row(
            f"[dim]目標[/dim] [bold green]{p['target_price']:.1f}  (+{p['target_pct']:.0f}%)[/bold green]",
            f"[dim]止損[/dim] [red]{p['stop_loss']:.1f}  ({p['stop_pct']:.1f}%)[/red]",
            f"[dim]建議賣出[/dim] [bold cyan]{p['sell_note']}[/bold cyan]",
            "", "", "",
        )
        body.add_row()
        body.add_row(
            f"[dim]催化劑[/dim] [italic]{cat_str}[/italic]",
            f"[dim]信心[/dim] {make_bar(p['score'])} {p['score']}/100",
            "", "", "", "",
        )

        score_breakdown = (
            f"量能{p['vol_score']} + 動能{p['mom_score']} + 技術{p['tech_score']} + 催化{p['cat_score']}"
        )
        body.add_row(f"[dim]評分細項  {score_breakdown}[/dim]", "", "", "", "", "")

        panel_color = "green" if p["score"] >= 80 else ("yellow" if p["score"] >= 65 else "white")
        console.print(Panel(body, title=header, border_style=panel_color, padding=(0, 1)))
        console.print()

def print_supply_chain_map():
    console.print(Rule("[bold]供應鏈地圖（快速參考）[/bold]", style="dim"))
    t = Table(box=box.MINIMAL, show_header=True, header_style="bold dim")
    t.add_column("客戶", width=10)
    t.add_column("台灣上游供應商", width=90)
    rows = [
        ("NVIDIA", "台積電(晶圓)・日月光(封測)・欣興(載板)・緯穎(AI伺服器)・廣達(伺服器ODM)・台達電(電源)・健鼎(PCB)・國巨(被動元件)"),
        ("AMD",    "台積電(晶圓)・日月光(封測)・欣興(載板)・技嘉・華碩(主機板)"),
        ("Apple",  "台積電(A/M晶片)・和碩/鴻海(組裝)・大立光/玉晶光(鏡頭)・可成(機殼)・聯詠(驅動IC)・義隆電(觸控)・廣達(Mac)"),
        ("AI全鏈", "台積電・聯發科(AI晶片)・力旺(NVM IP)・矽力(PMIC)・群聯(NAND)・緯穎・廣達・台達電"),
    ]
    for client, chain in rows:
        t.add_row(f"[bold]{client}[/bold]", chain)
    console.print(t)
    console.print()

def print_disclaimer():
    console.print()
    console.print(Panel(
        "[dim]⚠  本系統僅供技術分析參考，不構成投資建議。\n"
        "   台股漲停板為前日收盤價 ±10%。零股交易請注意流動性。\n"
        "   建議結合基本面、籌碼面與總經環境綜合判斷。[/dim]",
        style="dim", border_style="dim"
    ))

# ═══════════════════════════════════════════════════════════════════════════════
#  主程式
# ═══════════════════════════════════════════════════════════════════════════════

def main(args):
    now = datetime.now()
    print_header(now)

    all_tickers  = list(TECH_UNIVERSE.keys())
    holding_tickers = list(MY_HOLDINGS.keys())
    screen_tickers  = [t for t in all_tickers if t not in holding_tickers]

    with Progress(SpinnerColumn(), TextColumn("[bold blue]{task.description}"), transient=True) as prog:

        t1 = prog.add_task("抓取早盤新聞…", total=None)
        cnyes_news  = fetch_cnyes_news(60)
        moneydj_news = fetch_moneydj_news()
        all_news = cnyes_news + moneydj_news
        prog.update(t1, description=f"✅ 取得 {len(all_news)} 條新聞")
        time.sleep(0.3)

        t2 = prog.add_task("分析催化劑…", total=None)
        catalyst_scores, key_headlines = analyze_catalysts(all_news)
        prog.update(t2, description="✅ 催化劑分析完成")
        time.sleep(0.3)

        t3 = prog.add_task("抓取外資籌碼…", total=None)
        foreign_data = fetch_twse_foreign_buying()
        prog.update(t3, description=f"✅ 取得 {len(foreign_data)} 筆外資資料")
        time.sleep(0.3)

        t4 = prog.add_task("下載股價資料（約30秒）…", total=None)
        price_data = fetch_prices_batch(all_tickers, period="3mo")
        prog.update(t4, description=f"✅ 取得 {len(price_data)} 支股票")
        time.sleep(0.3)

        t5 = prog.add_task("大盤概況…", total=None)
        market_summary = fetch_twse_market_summary()
        prog.update(t5, description="✅ 大盤資料完成")
        time.sleep(0.2)

    # 評分
    scored = []
    for ticker in screen_tickers:
        df = price_data.get(ticker)
        bonus = catalyst_scores.get(ticker, 0)
        fi    = foreign_data.get(ticker, 0)
        res   = score_stock(ticker, df, bonus, fi)
        if res:
            scored.append(res)

    scored.sort(key=lambda x: x["score"], reverse=True)
    top5 = scored[:5]

    # ── 輸出 ──────────────────────────────────────────────────────────────────
    print_market_summary(market_summary)

    holding_info = analyze_holdings(price_data)
    print_holdings(holding_info)

    print_news(key_headlines)
    print_recommendations(top5, all_news)
    print_supply_chain_map()
    print_disclaimer()

    # 儲存 JSON 報告
    report = {
        "date":        now.strftime("%Y-%m-%d %H:%M"),
        "top5":        [{k: v for k, v in p.items() if k not in ("supply",)} for p in top5],
        "headlines":   key_headlines,
        "market":      market_summary,
    }
    import os
    log_dir = os.path.expanduser("~/taiwan_stock_widget/reports")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, f"{now.strftime('%Y%m%d_%H%M')}.json")
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    console.print(f"\n[dim]報告已儲存：{log_path}[/dim]")

# ═══════════════════════════════════════════════════════════════════════════════
#  AI 精選：Claude 財務智能代理
#  Role: Market Researcher + Earnings Reviewer + Valuation Reviewer
#  Cached per trading slot (epoch changes 4× per day) → at most 4 API calls/day
# ═══════════════════════════════════════════════════════════════════════════════

def ai_pick_of_day(picks: List[Dict], headlines: List[str], epoch: str) -> Dict:
    """
    Calls Claude (Haiku) as a trio of financial agents to pick the single best
    stock from today_picks. Returns a dict with ticker, reasoning, entry_note,
    and confidence. Falls back gracefully if API key is absent or call fails.

    Cache: callers should wrap with @st.cache_data(ttl=900) keyed on epoch.
    """
    import os
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        try:
            import streamlit as st
            api_key = st.secrets.get("ANTHROPIC_API_KEY", "")
        except Exception:
            pass
    if not api_key:
        return {"error": "no_key", "ticker": None}

    if not picks:
        return {"error": "no_picks", "ticker": None}

    try:
        import anthropic
    except ImportError:
        return {"error": "no_sdk", "ticker": None}

    top = picks[:5]

    def _fmt(p: Dict) -> str:
        supply = "・".join(p.get("supply", [])[:3]) or "無特定供應鏈"
        fund_labels = "・".join(p.get("fund_labels", [])[:3]) or "無"
        three_inv = "・".join(p.get("three_inv_labels", [])[:2]) or "無"
        return (
            f"【{p['name']} {p['ticker'].replace('.TW','')}】"
            f" 評分={p['score']} 板塊={p.get('sector','?')}"
            f" RSI={p.get('rsi',0):.1f} 量比={p.get('vol_ratio',0):.1f}x"
            f" 動能(1d/5d/20d)={p.get('mom1d',0):+.1f}%/{p.get('mom5d',0):+.1f}%/{p.get('mom20d',0):+.1f}%"
            f" Weinstein階段={p.get('stage_label','?')} BB={p.get('bb_signal','?')}"
            f" KD={p.get('kd_signal','?')} OBV={p.get('obv_trend','?')}"
            f" 52週位置={p.get('w52_label','?')}"
            f" 外資淨買={p.get('foreign_net',0):.0f}千張 宏觀加成={p.get('macro_bonus',0):+d}"
            f" 月營收YoY={p.get('rev_yoy') or '無'} 基本面={fund_labels}"
            f" 三大法人={three_inv}"
            f" 供應鏈={supply}"
            f" 目標={p.get('target_pct',0):.0f}% 現價=NT${p.get('last_price',0):.1f}"
        )

    stocks_text = "\n".join(_fmt(p) for p in top)
    news_text = "\n".join(f"- {h}" for h in headlines[:12]) if headlines else "（無）"

    prompt = f"""你是一個由三個專業角色組成的台股 AI 財務分析團隊，今天的任務是從以下精選股票中，選出**今日最值得小資零股買入的一支**。

## 三個角色的分工
1. **市場研究員（Market Researcher）**：評估新聞面、類股動能、供應鏈位置
2. **財報審查員（Earnings Reviewer）**：評估月營收年增、基本面標籤、三大法人共識
3. **估值審查員（Valuation Reviewer）**：評估 RSI 甜蜜區間、技術面（BB/KD/OBV/Weinstein）、量比與動能

## 今日候選股（已通過量化評分 ≥52 分）
{stocks_text}

## 今日重要新聞
{news_text}

## 任務
三個角色分別給出各自觀點後，共同決議出**今日最佳進場股**。

請以 JSON 格式回覆（僅輸出 JSON，不要額外文字）：
{{
  "ticker": "股票代號（如 2330.TW）",
  "name": "股票名稱",
  "reasoning": "100字以內的繁體中文理由，說明為什麼這支是今日最佳。涵蓋：技術面 + 基本面 + 新聞面",
  "entry_note": "30字以內的進場策略（例：今日 RSI 52，可分批零股買入，目標 +7%）",
  "confidence": "high/medium/low",
  "agent_consensus": "三個角色的簡短共識（各15字以內）：市場研究員：X｜財報審查員：Y｜估值審查員：Z"
}}"""

    try:
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw)
        result["error"] = None
        return result
    except Exception as e:
        return {"error": str(e)[:80], "ticker": None}


# ═══════════════════════════════════════════════════════════════════════════════
#  AI 長期潛力股：Thesis Tracker + CIM Builder + Technical Timing
#  Uses Claude Opus 4.7 with adaptive thinking for deep fundamental analysis.
#  Cache: 24 hr (theses are long-term, not intraday noise).
# ═══════════════════════════════════════════════════════════════════════════════

def ai_longterm_picks(scored: List[Dict], fund_map: Dict, headlines: List[str], date_str: str) -> Dict:
    """
    Identifies 2-3 long-term holds (3-12 months) using three skill frameworks:
      - Thesis Tracker: core thesis, pillars, risks, catalysts, conviction
      - CIM Builder:    moat assessment, financial quality, valuation
      - Technical:      Weinstein stage, foreign flow, RSI timing

    Calls Claude Opus 4.7 with adaptive thinking. Cache at 24 hr by callers.
    Returns {"longterm_picks": [...], "portfolio_note": "...", "error": None}.
    """
    import os
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        try:
            import streamlit as st
            api_key = st.secrets.get("ANTHROPIC_API_KEY", "")
        except Exception:
            pass
    if not api_key:
        return {"error": "no_key", "longterm_picks": []}

    candidates = [s for s in scored if s.get("score", 0) >= 50][:20]
    if not candidates:
        return {"error": "no_candidates", "longterm_picks": []}

    try:
        import anthropic
    except ImportError:
        return {"error": "no_sdk", "longterm_picks": []}

    def _fmt_lt(s: Dict) -> str:
        fund = fund_map.get(s["ticker"], {})
        rev_g  = fund.get("rev_growth")
        earn_g = fund.get("earn_growth")
        pm     = fund.get("profit_margin")
        f_pe   = fund.get("forward_pe")
        peg    = fund.get("peg_ratio")
        t_eps  = fund.get("trailing_eps")
        f_eps  = fund.get("forward_eps")
        rev_str  = f"{rev_g*100:+.0f}%"  if rev_g  is not None else "N/A"
        earn_str = f"{earn_g*100:+.0f}%" if earn_g is not None else "N/A"
        pm_str   = f"{pm*100:.0f}%"      if pm     is not None else "N/A"
        pe_str   = f"{f_pe:.0f}x"        if f_pe               else "N/A"
        peg_str  = f"{peg:.2f}"          if peg                else "N/A"
        eps_str  = (f"${t_eps:.2f}→${f_eps:.2f}" if t_eps and f_eps else "N/A")
        supply   = "・".join(s.get("supply", [])[:3]) or "一般"
        return (
            f"【{s['name']} {s['ticker'].replace('.TW','')}】評分={s['score']}"
            f" 板塊={s.get('sector','?')} 現價=NT${s.get('last_price',0):.1f}"
            f" RSI={s.get('rsi',0):.0f} Weinstein={s.get('stage_label','?')}"
            f" 動能(1M/3M)={s.get('mom20d',0):+.1f}%/{s.get('mom60d',0):+.1f}%"
            f" 外資連買={s.get('foreign_streak',0)}天"
            f" 營收YoY={rev_str} 盈利YoY={earn_str} 毛利={pm_str}"
            f" 預估PE={pe_str} PEG={peg_str} EPS={eps_str}"
            f" 供應鏈={supply}"
        )

    candidates_text = "\n".join(_fmt_lt(s) for s in candidates)
    news_text = "\n".join(f"- {h}" for h in headlines[:10]) if headlines else "（無）"

    prompt = f"""你是一個台股長期投資 AI 分析團隊，整合三個專業框架，為小資零股投資人找出 2-3 支**值得長期持有（3-12個月）**的潛力股。

## 分析框架

### 框架一：Thesis Tracker（投資論點追蹤器）
為每支入選股建立：
- **核心論點**：一句話說明長期看多原因（含產業位置、競爭優勢）
- **三大支柱**：支持論點的3個關鍵驅動因素
- **主要風險**：2個可能使論點失效的風險
- **關鍵催化劑**：未來3-6個月的觸發事件
- **確信程度**：high / medium / low（附簡短理由）

### 框架二：CIM Builder（商業質量評估）
從買方盡職調查視角評估護城河：
- **商業模式質量**：供應鏈位置、定價能力（護城河強/中/弱）
- **財務質量**：營收/盈利成長性、毛利率可持續性、EPS趨勢
- **估值合理性**：相對同業 PE/PEG 是否有安全邊際

### 框架三：技術面擇時
- Weinstein 階段2（多頭上升）優先
- 外資連續淨買 ≥3天為正面訊號
- RSI < 68 避免追高

## 候選股（量化評分 ≥50，已由高到低排序）
{candidates_text}

## 今日市場背景
{news_text}

## 投資限制（必須遵守）
- 小資零股戶，每筆金額有限，偏好長線持有3-12個月
- 禁止當沖建議，禁止高槓桿
- 最多選3支，寧缺勿濫，高確信優先

請以 JSON 格式回覆（僅輸出 JSON，不要任何說明文字）：
{{
  "longterm_picks": [
    {{
      "ticker": "股票代號（如 2330.TW）",
      "name": "股票名稱",
      "thesis": "核心論點（50字以內）",
      "pillars": ["支柱一（20字以內）", "支柱二（20字以內）", "支柱三（20字以內）"],
      "key_risks": ["風險一（15字以內）", "風險二（15字以內）"],
      "catalyst": "最重要近期催化劑（20字以內）",
      "moat": "強/中/弱",
      "valuation_note": "估值評語（20字以內，含PE或PEG）",
      "entry_strategy": "進場策略（25字以內：分批/等回調/RSI目標）",
      "conviction": "high/medium/low",
      "conviction_reason": "確信原因（20字以內）"
    }}
  ],
  "portfolio_note": "三支股票整體組合建議（50字以內，含板塊分散度）"
}}"""

    try:
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-opus-4-7",
            max_tokens=2048,
            thinking={"type": "adaptive"},
            messages=[{"role": "user", "content": prompt}],
        )
        raw = ""
        for block in msg.content:
            if getattr(block, "type", "") == "text":
                raw = block.text.strip()
                break
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw)
        result["error"] = None
        return result
    except Exception as e:
        return {"error": str(e)[:120], "longterm_picks": []}


# ═══════════════════════════════════════════════════════════════════════════════
#  啟動
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="台灣科技股盤前分析系統")
    parser.add_argument("--quick", action="store_true", help="跳過外資資料（較快）")
    args = parser.parse_args()
    main(args)
