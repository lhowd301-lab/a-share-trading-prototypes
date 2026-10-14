# data_fetcher.py — 实时行情数据获取（新浪+akshare+yfinance 三级后备）

import akshare as ak
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import os
import json
import requests
import concurrent.futures
import yfinance as yf
import time as _time

from config import TICKER, MARKET_CACHE_DIR, BAR_INTERVAL

# yfinance 限流控制（全局）
_yf_rate_limit_until = 0.0


def get_realtime_quote() -> Optional[Dict[str, Any]]:
    """获取信维通信实时行情（新浪→akshare→yfinance 三级后备）"""
    # 1. 新浪接口（主数据源，不限流）
    q = _get_sina_quote()
    if q:
        return q
    
    # 2. akshare 东方财富
    try:
        df = ak.stock_zh_a_spot_em()
        df = df[df["代码"] == TICKER]
        if not df.empty:
            row = df.iloc[0]
            return {
                "price": float(row.get("最新价", 0)),
                "open": float(row.get("今开", 0)),
                "high": float(row.get("最高", 0)),
                "low": float(row.get("最低", 0)),
                "pre_close": float(row.get("昨收", 0)),
                "volume": int(row.get("成交量", 0)),
                "amount": float(row.get("成交额", 0)),
                "change": float(row.get("涨跌额", 0)),
                "change_pct": float(row.get("涨跌幅", 0)),
                "turnover_rate": float(row.get("换手率", 0)),
                "time": datetime.now().strftime("%H:%M:%S"),
            }
    except Exception as e:
        print(f"[data_fetcher] akshare失败: {e}")
    
    # 3. yfinance（带限流保护）
    return _get_yf_quote()


def _get_sina_quote() -> Optional[Dict[str, Any]]:
    """通过新浪财经接口获取实时行情（速度最快，不限流）"""
    try:
        url = f"http://hq.sinajs.cn/list=sz{TICKER}"
        resp = requests.get(url, timeout=5, headers={"Referer": "https://finance.sina.com.cn"})
        resp.encoding = "gbk"  # 新浪接口用GBK编码
        text = resp.text.strip()
        if not text or "=" not in text:
            return None
        data = text.split('"')[1].split(',')
        if len(data) < 10:
            return None
        price = float(data[3])    # 当前价
        pre_close = float(data[2]) # 昨收
        change = price - pre_close
        change_pct = (change / pre_close * 100) if pre_close > 0 else 0
        return {
            "price": price,
            "open": float(data[1]),   # 今开
            "high": float(data[4]),   # 最高
            "low": float(data[5]),    # 最低
            "pre_close": round(pre_close, 2),
            "volume": int(data[8]) if data[8] else 0,    # 成交量
            "amount": float(data[9]) if data[9] else 0,  # 成交额
            "change": round(change, 2),
            "change_pct": round(change_pct, 2),
            "time": datetime.now().strftime("%H:%M:%S"),
        }
    except Exception as e:
        print(f"[data_fetcher] 新浪接口失败: {e}")
        return None


def _get_yf_quote() -> Optional[Dict[str, Any]]:
    """yfinance 后备（带限流保护）"""
    global _yf_rate_limit_until
    now = _time.time()
    if now < _yf_rate_limit_until:
        return None  # 限流中，跳过
    
    def _fetch():
        try:
            df = yf.download(tickers=TICKER + ".SZ", period="1d", interval="1m", progress=False)
            if df is None or df.empty:
                return None
            last = df.iloc[-1]
            prev = df.iloc[-2] if len(df) > 1 else last
            price = float(last["Close"])
            prev_close = float(prev["Close"])
            change = price - prev_close
            change_pct = (change / prev_close * 100) if prev_close > 0 else 0
            return {
                "price": price,
                "open": float(last["Open"]),
                "high": float(last["High"]),
                "low": float(last["Low"]),
                "pre_close": round(prev_close, 2),
                "volume": int(last["Volume"]) if "Volume" in df.columns else 0,
                "amount": 0,
                "change": round(change, 2),
                "change_pct": round(change_pct, 2),
                "time": str(last.name)[-8:] if hasattr(last.name, "strftime") else datetime.now().strftime("%H:%M:%S"),
            }
        except Exception as e:
            return None
    
    executor = concurrent.futures.ThreadPoolExecutor()
    try:
        future = executor.submit(_fetch)
        result = future.result(timeout=8)
        if result is None:
            _yf_rate_limit_until = now + 120  # 限流了，2分钟后再试
        return result
    except concurrent.futures.TimeoutError:
        _yf_rate_limit_until = now + 60  # 超时，1分钟后再试
        return None
    finally:
        executor.shutdown(wait=False)


def get_latest_minute_quote() -> Optional[Dict[str, Any]]:
    """从最新一分钟K线获取行情（备用）"""
    try:
        df = ak.stock_zh_a_hist_min_em(
            symbol=TICKER, period="1", adjust="qfq"
        )
        if df.empty:
            return None
        last = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else last
        price = float(last["收盘"])
        prev_close = float(prev["收盘"])
        change = price - prev_close
        change_pct = (change / prev_close * 100) if prev_close > 0 else 0
        return {
            "price": price,
            "open": float(last["开盘"]),
            "high": float(last["最高"]),
            "low": float(last["最低"]),
            "pre_close": prev_close,
            "volume": int(last["成交量"]),
            "amount": float(last["成交额"]),
            "change": round(change, 2),
            "change_pct": round(change_pct, 2),
            "time": str(last["时间"])[-8:],
        }
    except Exception as e:
        print(f"[data_fetcher] 分钟K线后备也失败: {e}")
        return None


def get_historical_minute(days: int = 5) -> Optional[pd.DataFrame]:
    """获取历史分钟K线数据（带重试）"""
    import time as _time
    for attempt in range(3):
        try:
            df = ak.stock_zh_a_hist_min_em(
                symbol=TICKER, period=str(BAR_INTERVAL), adjust="qfq"
            )
            if df is not None and not df.empty:
                df.rename(columns={
                    "时间": "time", "开盘": "open", "收盘": "close",
                    "最高": "high", "最低": "low",
                    "成交量": "volume", "成交额": "amount",
                }, inplace=True)
                df["time"] = pd.to_datetime(df["time"])
                cutoff = datetime.now() - timedelta(days=days)
                df = df[df["time"] >= cutoff].copy()
                for col in ["open", "close", "high", "low", "volume", "amount"]:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
                df.sort_values("time", inplace=True)
                df.reset_index(drop=True, inplace=True)
                return df
        except Exception as e:
            print(f"[data_fetcher] 分钟K线获取失败(尝试{attempt+1}/3): {e}")
            if attempt < 2:
                _time.sleep(1)
            continue
    return None


def is_market_open() -> bool:
    """判断当前是否在交易时段"""
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    t = now.time()
    from config import (
        TRADING_SESSION_MORNING_START, TRADING_SESSION_MORNING_END,
        TRADING_SESSION_AFTERNOON_START, TRADING_SESSION_AFTERNOON_END,
    )
    if TRADING_SESSION_MORNING_START <= t <= TRADING_SESSION_MORNING_END:
        return True
    if TRADING_SESSION_AFTERNOON_START <= t <= TRADING_SESSION_AFTERNOON_END:
        return True
    return False
