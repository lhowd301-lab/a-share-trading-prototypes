"""
data_fetcher.py — 获取分钟级行情数据（akshare）
"""
import os
import pandas as pd
import akshare as ak
from datetime import datetime, timedelta
from typing import Optional
from config import CFG, TICKER, EXCHANGE, FULL_TICKER


def fetch_intraday_minutes(
    ticker: str = TICKER,
    exchange: str = EXCHANGE,
    period: str = "1min",
    save_raw: bool = True
) -> Optional[pd.DataFrame]:
    """拉取当日分钟 K 线
    返回 DataFrame，列：时间, 开盘, 收盘, 最高, 最低, 成交量, 成交额
    """
    try:
        df = ak.stock_zh_a_hist_min_em(
            symbol=ticker,
            period=period,
            adjust=""
        )
        if df is None or df.empty:
            return None

        # 统一列名
        df.columns = [c.strip() for c in df.columns]
        rename_map = {
            "时间": "time",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "volume",
            "成交额": "amount",
        }
        df.rename(columns=rename_map, inplace=True)
        df["time"] = pd.to_datetime(df["time"])
        df.sort_values("time", inplace=True)

        if save_raw:
            os.makedirs(CFG.exec.data_dir, exist_ok=True)
            today = datetime.now().strftime("%Y%m%d")
            path = os.path.join(CFG.exec.data_dir, f"{ticker}_{period}_{today}.csv")
            df.to_csv(path, index=False, encoding="utf-8-sig")

        return df

    except Exception as e:
        print(f"[数据获取失败] {e}")
        return None


def fetch_history_minutes(
    ticker: str = TICKER,
    period: str = "1min",
    days: int = 5,
) -> Optional[pd.DataFrame]:
    """拉取最近 N 日分钟 K 线（用于日内指标预热）"""
    try:
        df = ak.stock_zh_a_hist_premin_em(
            symbol=ticker,
            period=period,
            start_date=(datetime.now() - timedelta(days=days)).strftime("%Y%m%d"),
            end_date=datetime.now().strftime("%Y%m%d"),
        )
        if df is not None and not df.empty:
            df.columns = [c.strip() for c in df.columns]
            rename_map = {
                "时间": "time", "开盘": "open", "收盘": "close",
                "最高": "high", "最低": "low", "成交量": "volume",
                "成交额": "amount",
            }
            df.rename(columns=rename_map, inplace=True)
            df["time"] = pd.to_datetime(df["time"])
            df.sort_values("time", inplace=True)
        return df
    except Exception as e:
        print(f"[历史数据获取失败] {e}")
        return None


def get_current_price(ticker: str = TICKER) -> Optional[float]:
    """获取实时价格（盘口）"""
    try:
        df = ak.stock_zh_a_spot_em()
        row = df[df["代码"] == ticker]
        if row.empty:
            return None
        return float(row.iloc[0]["最新价"])
    except Exception as e:
        print(f"[实时价格获取失败] {e}")
        return None


if __name__ == "__main__":
    df = fetch_intraday_minutes()
    if df is not None:
        print(df.tail())

# ── 腾讯行情 API（更稳定，推荐用于实时价） ───────────────────────────
def get_price_via_tencent(ticker: str = "300136", exchange: str = "sz") -> dict | None:
    """通过腾讯行情 API 获取实时报价

    返回示例:
        {"price": 66.03, "open": 64.31, "high": 66.15, "low": 55.78,
         "prev_close": 63.18, "change_pct": 4.51, "time": "20260721114527",
         "volume": 685974}
    """
    import requests
    import re
    code = f"{exchange}{ticker}"
    url = f"https://qt.gtimg.cn/q={code}"
    try:
        r = requests.get(url, timeout=5, headers={"User-Agent": "Mozilla/5.0"})
        parts = r.text.strip().split("~")
        if len(parts) < 35:
            return None
        return {
            "price": float(parts[3]),
            "prev_close": float(parts[4]),
            "open": float(parts[5]),
            "high": float(parts[33]),
            "low": float(parts[34]),
            "change_pct": float(parts[32]),
            "time": parts[30],
            "volume": int(parts[6]) if parts[6] else 0,
        }
    except Exception as e:
        print(f"[腾讯行情获取失败] {e}")
        return None
