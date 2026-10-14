"""indicators.py — 技术指标计算"""
import numpy as np
import pandas as pd
from config import CFG


def bollinger_bands(df: pd.DataFrame) -> pd.DataFrame:
    cfg = CFG.bollinger
    close = df["close"]
    if cfg.smoothing == "ema":
        mid = close.ewm(span=cfg.period, adjust=False).mean()
    else:
        mid = close.rolling(cfg.period).mean()
    std = close.rolling(cfg.period).std(ddof=0)
    df = df.copy()
    df["boll_mid"] = mid
    df["boll_upper"] = mid + cfg.std_multiplier * std
    df["boll_lower"] = mid - cfg.std_multiplier * std
    df["boll_width"] = (df["boll_upper"] - df["boll_lower"]) / df["boll_mid"] * 100
    return df


def rsi(df: pd.DataFrame) -> pd.DataFrame:
    period = CFG.filters.rsi_period
    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df = df.copy()
    df["rsi"] = 100 - (100 / (1 + rs))
    df["rsi"] = df["rsi"].fillna(50.0)
    return df


def volume_ma(df: pd.DataFrame) -> pd.DataFrame:
    period = CFG.filters.volume_ma_period
    df = df.copy()
    df["volume_ma"] = df["volume"].rolling(period).mean()
    df["volume_ratio"] = df["volume"] / df["volume_ma"].replace(0, np.nan)
    return df


def trend_ma(df: pd.DataFrame) -> pd.DataFrame:
    period = CFG.filters.trend_ma_period
    df = df.copy()
    df["trend_ma"] = df["close"].rolling(period).mean()
    df["trend_direction"] = np.where(
        df["close"] > df["trend_ma"], 1,
        np.where(df["close"] < df["trend_ma"] * 0.98, -1, 0)
    )
    return df


def compute_all(df: pd.DataFrame) -> pd.DataFrame:
    df = bollinger_bands(df)
    df = rsi(df)
    df = volume_ma(df)
    df = trend_ma(df)
    return df
