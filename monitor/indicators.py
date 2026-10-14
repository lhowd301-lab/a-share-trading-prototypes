# indicators.py — 技术指标计算

import pandas as pd
import numpy as np
from typing import Dict, Any, Optional

from config import (
    MA_PERIODS, BOLL_PERIOD, BOLL_STD, RSI_PERIOD,
    MACD_FAST, MACD_SLOW, MACD_SIGNAL,
    KDJ_K, KDJ_D,
    TREND_THRESHOLD, DECLINE_THRESHOLD,
)


def calc_all_indicators(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """计算全部技术指标，返回带指标列的DataFrame"""
    if df is None or df.empty or len(df) < 60:
        return df
    
    df = df.copy()
    
    # ========== 移动均线 ==========
    for p in MA_PERIODS:
        df[f"MA{p}"] = df["close"].rolling(window=p).mean()
    
    # ========== 布林带 ==========
    df["BOLL_MID"] = df["close"].rolling(BOLL_PERIOD).mean()
    df["BOLL_STD"] = df["close"].rolling(BOLL_PERIOD).std()
    df["BOLL_UPPER"] = df["BOLL_MID"] + BOLL_STD * df["BOLL_STD"]
    df["BOLL_LOWER"] = df["BOLL_MID"] - BOLL_STD * df["BOLL_STD"]
    df["BOLL_WIDTH"] = df["BOLL_UPPER"] - df["BOLL_LOWER"]
    df["BOLL_POS"] = (df["close"] - df["BOLL_LOWER"]) / df["BOLL_WIDTH"].replace(0, np.nan) * 100
    
    # ========== RSI ==========
    delta = df["close"].diff()
    gain = delta.where(delta > 0, 0)
    loss = (-delta).where(delta < 0, 0)
    avg_gain = gain.rolling(RSI_PERIOD).mean()
    avg_loss = loss.rolling(RSI_PERIOD).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["RSI"] = 100 - (100 / (1 + rs))
    df["RSI_BIAS"] = (df["RSI"] - 50) * 0.3
    
    # ========== MACD ==========
    ema_fast = df["close"].ewm(span=MACD_FAST, adjust=False).mean()
    ema_slow = df["close"].ewm(span=MACD_SLOW, adjust=False).mean()
    df["MACD_DIF"] = ema_fast - ema_slow
    df["MACD_DEA"] = df["MACD_DIF"].ewm(span=MACD_SIGNAL, adjust=False).mean()
    df["MACD_HIST"] = (df["MACD_DIF"] - df["MACD_DEA"]) * 2
    df["MACD_HIST_SCORE"] = df["MACD_HIST"].clip(-15, 15) * 50
    
    # ========== KDJ ==========
    low_min = df["low"].rolling(KDJ_K).min()
    high_max = df["high"].rolling(KDJ_K).max()
    df["RSV"] = (df["close"] - low_min) / (high_max - low_min).replace(0, np.nan) * 100
    df["K"] = df["RSV"].ewm(span=KDJ_D, adjust=False).mean()
    df["D"] = df["K"].ewm(span=KDJ_D, adjust=False).mean()
    df["J"] = 3 * df["K"] - 2 * df["D"]
    
    # ========== 均线斜率（20周期）==========
    df["MA20_SLOPE"] = df["MA20"].diff(periods=15) if len(df) > 15 else df["MA20"].diff()
    df["MA20_SLOPE_NORM"] = df["MA20_SLOPE"] / df["MA20"].replace(0, np.nan) * 100
    
    # ========== ATR（用于网格止盈）==========
    df["TR"] = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift(1)).abs(),
        (df["low"] - df["close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    df["ATR"] = df["TR"].rolling(14).mean()
    
    # ========== 成交量均线 ==========
    df["VOL_MA5"] = df["volume"].rolling(5).mean()
    df["VOL_MA20"] = df["volume"].rolling(20).mean()
    df["VOL_RATIO"] = df["volume"] / df["VOL_MA20"].replace(0, np.nan)
    
    return df


def get_latest_indicators(df: pd.DataFrame) -> Dict[str, Any]:
    """获取最新一行的所有指标值"""
    if df is None or df.empty:
        return {}
    df = calc_all_indicators(df)
    if len(df) < 2:
        return {}
    
    last = df.iloc[-1]
    prev = df.iloc[-2]
    
    ind = {}
    for col in df.columns:
        try:
            val = last[col]
            if isinstance(val, (int, float, np.integer, np.floating)):
                ind[col] = round(float(val), 4)
            elif isinstance(val, pd.Timestamp):
                ind[col] = str(val)
            else:
                ind[col] = val
        except:
            pass
    
    # 额外判断
    ind["MA20_DIRECTION"] = "up" if last["MA20"] >= prev["MA20"] else "down"
    ind["MACD_CROSS"] = "golden" if (last["MACD_DIF"] >= last["MACD_DEA"] 
                                       and prev["MACD_DIF"] < prev["MACD_DEA"]) else \
                        "death" if (last["MACD_DIF"] <= last["MACD_DEA"] 
                                     and prev["MACD_DIF"] > prev["MACD_DEA"]) else "none"
    
    return ind


def get_classifier_score(indicators: Dict[str, Any]) -> Dict[str, Any]:
    """计算行情分类器总分及各项得分
    
    Returns:
        dict: {score, category, details:{sma20_score, boll_score, rsi_score, macd_score}}
    """
    scores = {}
    
    # 1. SMA20斜率得分（权重25%）
    slope_val = indicators.get("MA20_SLOPE_NORM", 0) or 0
    scores["sma20_score"] = max(-10, min(10, slope_val * 5))
    
    # 2. 布林位置得分（权重25%）
    boll_pos = indicators.get("BOLL_POS", 50) or 50
    scores["boll_score"] = (boll_pos / 5) - 10
    scores["boll_score"] = max(-10, min(10, scores["boll_score"]))
    
    # 3. RSI偏向得分（权重15%）
    rsi = indicators.get("RSI", 50) or 50
    scores["rsi_score"] = max(-10, min(10, (rsi - 50) * 0.3))
    
    # 4. MACD柱得分（权重15%）
    macd_hist = indicators.get("MACD_HIST", 0) or 0
    scores["macd_score"] = max(-15, min(15, macd_hist * 50))
    scores["macd_score"] = max(-10, min(10, scores["macd_score"] / 15 * 10))
    
    # 总分
    total = (
        scores["sma20_score"] * 0.25 +
        scores["boll_score"] * 0.25 +
        scores["rsi_score"] * 0.15 +
        scores["macd_score"] * 0.15
    )
    scores["total_score"] = round(total, 2)
    
    # 行情分类
    if total >= TREND_THRESHOLD:
        category = "uptrend"
        label = "上涨行情 → 趋势跟踪策略"
    elif total <= DECLINE_THRESHOLD:
        category = "downtrend"
        label = "下跌行情 → 网格加仓策略"
    else:
        category = "sidelines"
        label = "横盘行情 → 均值回归策略"
    
    scores["category"] = category
    scores["label"] = label
    
    return scores
