
from pathlib import Path as _PublicPath
_PUBLIC_ROOT = _PublicPath(__file__).resolve().parents[1]
# crawler_minute.py - 信维通信1分钟数据爬虫
# 多数据源轮询，盘中能拿到1分钟数据
import requests, json, time, os, sys
import pandas as pd
from datetime import datetime, date

CODE = "300136"
TARGET_DATE = date(2026, 7, 21)
HEADERS = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
OUT_DIR = str(_PUBLIC_ROOT / 'minute_backtest/信维通信7.21')

def save_csv(df, name):
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, name)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"  [OK] 已保存: {path} ({len(df)}行, {os.path.getsize(path)}字节)")
    return path

def parse_eastmoney_klines(klines):
    rows = []
    for k in klines:
        p = k.split(",")
        if len(p) >= 7:
            dt_str = p[0]
            rows.append({
                "time": pd.to_datetime(dt_str),
                "open": float(p[1]), "close": float(p[2]),
                "high": float(p[3]), "low": float(p[4]),
                "volume": float(p[5]), "amount": float(p[6])
            })
    return pd.DataFrame(rows)

def parse_tencent_klines(klines):
    rows = []
    for k in klines:
        if len(k) >= 6:
            rows.append({
                "time": pd.to_datetime(k[0]),
                "open": float(k[1]), "close": float(k[4]),
                "high": float(k[2]), "low": float(k[3]),
                "volume": float(k[5])
            })
    return pd.DataFrame(rows)

def parse_sina_klines(data):
    rows = []
    for d in data:
        rows.append({
            "time": pd.to_datetime(d["day"]),
            "open": float(d["open"]), "close": float(d["close"]),
            "high": float(d["high"]), "low": float(d["low"]),
            "volume": float(d["volume"])
        })
    return pd.DataFrame(rows)

results = {}

# ── Source 1: EastMoney push2his (1-minute, best in-session) ──
print("[1/5] EastMoney push2his (1分钟)...", end=" ")
try:
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "secid": f"0.{CODE}", "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "1", "fqt": "1", "end": "20260721", "lmt": "480"
    }
    r = requests.get(url, params=params, timeout=15, headers=HEADERS)
    kl = r.json().get("data", {}).get("klines", [])
    if kl:
        df = parse_eastmoney_klines(kl)
        df = df[df["time"].dt.date == TARGET_DATE].sort_values("time").reset_index(drop=True)
        if len(df) > 0:
            results["eastmoney_1min"] = df
            save_csv(df, f"300136_1min_{TARGET_DATE}_eastmoney.csv")
            print(f"{len(df)}根K线 [OK]")
        else:
            print("无目标日期数据")
    else:
        print("空返回")
except Exception as e:
    print(f"[X] {type(e).__name__}: {str(e)[:60]}")

# ── Source 2: Sina 1-minute API (if exists) ──
print("[2/5] Sina 1分钟...", end=" ")
try:
    url = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
    r = requests.get(url, params={"symbol":"sz300136","scale":"1","datalen":"480"}, timeout=10, headers=HEADERS)
    d = r.json()
    if d and len(d) > 0:
        df = parse_sina_klines(d)
        df = df[df["time"].dt.date == TARGET_DATE].sort_values("time").reset_index(drop=True)
        if len(df) > 0:
            results["sina_1min"] = df
            save_csv(df, f"300136_1min_{TARGET_DATE}_sina.csv")
            print(f"{len(df)}根K线 [OK]")
        else:
            print("无目标日期数据")
    else:
        print("空返回")
except Exception as e:
    print(f"[X] {type(e).__name__}")

# ── Source 3: Tencent Finance (today's 1-minute) ──
print("[3/5] Tencent Finance (1分钟)...", end=" ")
try:
    url = "https://web.ifzq.gtimg.cn/appstock/app/minute/query"
    r = requests.get(url, params={"code":"sz300136"}, timeout=10, headers=HEADERS)
    d = r.json()
    minutes = d["data"]["sz300136"]["data"]
    if minutes:
        df = parse_tencent_klines(minutes)
        df = df[df["time"].dt.date == TARGET_DATE].sort_values("time").reset_index(drop=True)
        if len(df) > 0:
            results["tencent_1min"] = df
            save_csv(df, f"300136_1min_{TARGET_DATE}_tencent.csv")
            print(f"{len(df)}根K线 [OK]")
        else:
            print("无目标日期数据")
    else:
        print("空返回")
except Exception as e:
    print(f"[X] {type(e).__name__}")

# ── Source 4: Sinajs scraping (tick-level from minute page) ──
print("[4/5] Sina页面抓取...", end=" ")
try:
    url = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Public_MinKLine_1"
    r = requests.get(url, params={"code":"sz300136","start":str(TARGET_DATE),"end":str(TARGET_DATE)}, timeout=10, headers=dict(HEADERS,**{"Referer":"https://finance.sina.com.cn"}))
    content = r.content.decode("gbk", errors="replace")
    try:
        d = json.loads(content)
    except:
        d = None
    if d and isinstance(d, list) and len(d) > 0:
        print(f"返回{len(d)}条记录，格式:", str(d[0])[:100])
    elif isinstance(d, dict) and "__ERROR" in d:
        print(f"API返回错误: {d}")
    else:
        print(f"返回:{str(content)[:100]}")
except Exception as e:
    print(f"[X] {type(e).__name__}: {str(e)[:50]}")

# ── Source 5: Baostock (5-min, always available) ──
print("[5/5] Baostock (5分钟, 备用)...", end=" ")
try:
    import baostock as bs
    bs.login()
    rs = bs.query_history_k_data_plus("sz.300136",
        "date,time,open,high,low,close,volume",
        start_date=str(TARGET_DATE), end_date=str(TARGET_DATE),
        frequency="5", adjustflag="3")
    rows = []
    while rs.next():
        r = rs.get_row_data()
        if r[1]:
            t = pd.to_datetime(r[0] + " " + r[1])
            rows.append({"time":t, "open":float(r[2]), "high":float(r[3]),
                         "low":float(r[4]), "close":float(r[5]), "volume":float(r[6])})
    bs.logout()
    if rows:
        df = pd.DataFrame(rows).sort_values("time").reset_index(drop=True)
        results["baostock_5min"] = df
        save_csv(df, f"300136_5min_{TARGET_DATE}_baostock.csv")
        print(f"{len(df)}根K线 [OK]")
    else:
        print("无数据")
except Exception as e:
    print(f"[X] {type(e).__name__}")

# ── 汇总 ──
print(f"\n{'='*50}")
print("爬取结果汇总")
print(f"{'='*50}")
for src, df in results.items():
    src_name = {"eastmoney_1min":"EastMoney 1分钟","sina_1min":"Sina 1分钟",
                 "tencent_1min":"腾讯 1分钟","baostock_5min":"Baostock 5分钟"}
    print(f"  {src_name.get(src, src)}: {len(df)}根K线")

if not results:
    print("\n[!]️ 盘后所有1分钟API均不可用，仅5分钟数据源可用")
    print("  明天9:30开盘后运行本脚本，EastMoney和富途的1分钟数据都会有")
