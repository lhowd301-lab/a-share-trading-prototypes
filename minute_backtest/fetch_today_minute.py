
from pathlib import Path as _PublicPath
_PUBLIC_ROOT = _PublicPath(__file__).resolve().parents[1]
import requests, json, os, time as _time
import pandas as pd
import numpy as np
from datetime import datetime

CODE = "300136"
OUT_DIR = str(_PUBLIC_ROOT / 'minute_backtest/data')
os.makedirs(OUT_DIR, exist_ok=True)

def _sma(s, p):
    return s.rolling(window=p).mean()

def _std(s, p):
    return s.rolling(window=p).std(ddof=0)

def _ema(s, p):
    return s.ewm(span=p, adjust=False).mean()

def boll(df, period=20, std=2.0):
    m = _sma(df["close"], period)
    s = _std(df["close"], period)
    return m + std * s, m, m - std * s

def rsi(series, p=14):
    d = series.diff()
    g = d.where(d > 0, 0)
    l = (-d).where(d < 0, 0)
    ag = g.ewm(span=p, adjust=False).mean()
    al = l.ewm(span=p, adjust=False).mean()
    return 100 - 100 / (1 + ag / al.replace(0, float("nan")))

def macd(s, fast=12, slow=26, signal=9):
    ef = _ema(s, fast)
    es = _ema(s, slow)
    d = ef - es
    return d, _ema(d, signal), 2 * (d - _ema(d, signal))

def atr(df, p=14):
    hl = df["high"] - df["low"]
    hc = (df["high"] - df["close"].shift()).abs()
    lc = (df["low"] - df["close"].shift()).abs()
    return pd.concat([hl, hc, lc], axis=1).max(axis=1).rolling(window=p).mean()

def fetch_minute_data(lmt=480):
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {"secid": f"0.{CODE}", "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "1", "fqt": "1", "end": "20500101", "lmt": str(lmt)}
    r = requests.get(url, params=params, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
    klines = r.json().get("data", {}).get("klines", [])
    rows = []
    for k in klines:
        p = k.split(",")
        if len(p) >= 7:
            rows.append({"time": p[0], "open": float(p[1]), "close": float(p[2]),
                "high": float(p[3]), "low": float(p[4]),
                "volume": float(p[5]), "amount": float(p[6])})
    return pd.DataFrame(rows)

def fetch_today_quote():
    url = "https://push2.eastmoney.com/api/qt/stock/get"
    params = {"secid": f"0.{CODE}", "fields": "f43,f44,f45,f46,f47,f48,f50,f55,f57,f58,f60,f170,f117"}
    r = requests.get(url, params=params, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
    d = r.json().get("data", {})
    if not d or "f43" not in d:
        return None
    return {"price": d["f43"] / 100, "high": d.get("f44", 0) / 100,
        "low": d.get("f45", 0) / 100, "open": d.get("f46", 0) / 100,
        "volume": d.get("f47", 0), "amount": d.get("f48", 0),
        "change": d.get("f55", 0) / 100 if d.get("f55") else 0}

def calculate_indicators(df):
    df = df.copy()
    if len(df) < 50:
        print("数据不足50根K线，无法计算指标")
        return df
    u, m, l = boll(df, 20, 2.0)
    df["boll_upper"] = u
    df["boll_mid"] = m
    df["boll_lower"] = l
    df["boll_width"] = (u - l) / m * 100
    df["rsi6"] = rsi(df["close"], 6)
    df["rsi12"] = rsi(df["close"], 12)
    df["rsi14"] = rsi(df["close"], 14)
    df["rsi24"] = rsi(df["close"], 24)
    macd_line, signal_line, hist = macd(df["close"])
    df["macd"] = macd_line
    df["macd_signal"] = signal_line
    df["macd_hist"] = hist
    df["atr14"] = atr(df, 14)
    df["sma20"] = _sma(df["close"], 20)
    df["sma20_slope"] = df["sma20"] - df["sma20"].shift(10)
    df["volume_ma20"] = _sma(df["volume"], 20)
    df["volume_ratio"] = df["volume"] / df["volume_ma20"].replace(0, float("nan"))
    df["boll_pos"] = ((df["close"] - df["boll_lower"]) /
                      (df["boll_upper"] - df["boll_lower"]) * 100)
    return df

def classify_market(df):
    if len(df) < 30:
        return "sideways"
    last = df.iloc[-1]
    score = 0
    slp = last.get("sma20_slope", 0)
    if pd.notna(slp):
        if slp > 0.05: score += 30
        elif slp > 0: score += 15
        elif slp > -0.05: score -= 15
        else: score -= 30
    pos = last.get("boll_pos", 50)
    if pd.notna(pos):
        if pos > 70: score += 30
        elif pos > 55: score += 15
        elif pos > 45: score += 0
        elif pos > 30: score -= 15
        else: score -= 30
    rv = last.get("rsi14", 50)
    if pd.notna(rv):
        score += round((rv - 50) * 0.4)
    md = last.get("macd_hist", 0)
    if pd.notna(md):
        md_sc = md * 50
        if md_sc > 20: md_sc = 20
        elif md_sc < -20: md_sc = -20
        score += round(md_sc)
    if score > 20: return "uptrend"
    elif score < -20: return "downtrend"
    else: return "sideways"

def main():
    print("=== 信维通信(300136) 分钟级数据爬取 ===")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    quote = fetch_today_quote()
    if quote:
        print(f"实时报价: {quote['price']:.2f} 涨跌: {quote['change']:+.2f}")
    else:
        print("实时报价: 获取失败")
    print()
    df = fetch_minute_data(480)
    if len(df) == 0:
        print("错误: 无K线数据")
        return
    df["time"] = pd.to_datetime(df["time"])
    today = datetime.now().strftime("%Y-%m-%d")
    today_df = df[df["time"].dt.strftime("%Y-%m-%d") == today].copy()
    if len(today_df) == 0:
        print(f"错误: 无今日({today})数据")
        return
    tr = f"{today_df['time'].iloc[0].strftime('%H:%M')} - {today_df['time'].iloc[-1].strftime('%H:%M')}"
    print(f"分钟K线: {len(today_df)}根 ({tr})")
    today_df = calculate_indicators(today_df)
    regime = classify_market(today_df)
    print(f"行情分类: {regime}")
    print()
    print("=== 最近5根K线 ===")
    hdr = f"{'时间':>8} {'开盘':>6} {'收盘':>6} {'最高':>6} {'最低':>6} {'量':>8} {'上轨':>7} {'中轨':>7} {'下轨':>7} {'RSI14':>6} {'MACD柱':>8}"
    print(hdr)
    print("-" * 90)
    for _, r in today_df.tail(5).iterrows():
        t = r["time"].strftime("%H:%M")
        print(f"{t:>8} {r['open']:>6.2f} {r['close']:>6.2f} {r['high']:>6.2f} {r['low']:>6.2f} {r['volume']:>8.0f} "
              f"{r.get('boll_upper', 0):>7.2f} {r.get('boll_mid', 0):>7.2f} {r.get('boll_lower', 0):>7.2f} "
              f"{r.get('rsi14', 0):>6.1f} {r.get('macd_hist', 0):>8.4f}")
    csv_path = os.path.join(OUT_DIR, f"{CODE}_1min_{today}_with_indicators.csv")
    today_df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    print(f"\n已保存含指标数据: {csv_path}")
    old_path = os.path.join(OUT_DIR, f"{CODE}_1min_{today}.csv")
    today_df[["time","open","close","high","low","volume","amount"]].to_csv(old_path, index=False, encoding="utf-8-sig")
    print(f"已保存原始数据:   {old_path}")
    if len(today_df) >= 20:
        last = today_df.iloc[-1]
        print()
        print("--- 最新技术指标 ---")
        print(f"BOLL(20,2): 上={last.get('boll_upper', 'N/A'):.2f} 中={last.get('boll_mid', 'N/A'):.2f} 下={last.get('boll_lower', 'N/A'):.2f}")
        print(f"RSI: 6={last.get('rsi6', 'N/A'):.1f} 12={last.get('rsi12', 'N/A'):.1f} 14={last.get('rsi14', 'N/A'):.1f} 24={last.get('rsi24', 'N/A'):.1f}")
        print(f"MACD: {last.get('macd', 'N/A'):.4f} 信号={last.get('macd_signal', 'N/A'):.4f} 柱={last.get('macd_hist', 'N/A'):.4f}")
        print(f"ATR(14): {last.get('atr14', 'N/A'):.2f}")
        print(f"SMA20: {last.get('sma20', 'N/A'):.2f} 斜率={last.get('sma20_slope', 'N/A'):.4f}")
        print(f"量比: {last.get('volume_ratio', 'N/A'):.1f}x")
        print(f"布林位置: {last.get('boll_pos', 'N/A'):.1f}%")
        print(f"行情分类: {regime}")

if __name__ == "__main__":
    main()
