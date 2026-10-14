# signals.py — 三策略信号判定

from typing import Dict, Any, Optional, List
from datetime import datetime
import pandas as pd

from config import (
    TREND_MA_PERIOD, TREND_RSI_LOW, TREND_RSI_HIGH,
    TREND_PROXIMITY, TREND_ORDER_SIZE, GRID_RSI_EXIT, SELL_PER_SIGNAL,
    REVERSION_RSI_OVERSOLD, REVERSION_POSITION_STOP, GRID_VOLUME_LEVELS,
)


def check_trend_following(indicators: Dict[str, Any], df: pd.DataFrame,
                           current_position: int) -> Optional[Dict[str, Any]]:
    """上涨行情 → 趋势跟踪策略信号
    
    买入：价格回踩MA20，缩量，RSI适中
    卖出：跌破MA20或RSI超买或冲高回落
    """
    if len(df) < 30:
        return None
    
    last = df.iloc[-1]
    prev = df.iloc[-2]
    price = last["close"]
    ma20 = last.get(f"MA{TREND_MA_PERIOD}", price)
    rsi = last.get("RSI", 50)
    vol_ma20 = last.get("VOL_MA20", last["volume"])
    
    signals = []
    
    # === 买入信号 ===
    buy_conditions = []
    
    # 条件A：价格在MA20上方
    if price > ma20:
        buy_conditions.append("price_above_ma20")
    
    # 条件B：MA20向上
    if last.get(f"MA{TREND_MA_PERIOD}") and prev.get(f"MA{TREND_MA_PERIOD}"):
        if last[f"MA{TREND_MA_PERIOD}"] >= prev[f"MA{TREND_MA_PERIOD}"]:
            buy_conditions.append("ma20_rising")
    
    # 条件C：价格回踩MA20（接近但不跌破）
    proximity = ma20 * TREND_PROXIMITY
    if last["low"] <= ma20 * (1 + TREND_PROXIMITY) and last["high"] >= ma20 * (1 - TREND_PROXIMITY):
        buy_conditions.append("price_near_ma20")
    
    # 条件D：RSI在40~55区间
    if TREND_RSI_LOW <= rsi <= TREND_RSI_HIGH:
        buy_conditions.append("rsi_moderate")
    
    # 条件E：缩量
    if vol_ma20 > 0 and last["volume"] <= vol_ma20 * 1.0:
        buy_conditions.append("volume_shrink")
    
    if len(buy_conditions) == 5:
        score = len(buy_conditions) / 5.0
        signals.append({
            "type": "BUY",
            "strategy": "趋势跟踪",
            "price": round(price, 2),
            "quantity": TREND_ORDER_SIZE,
            "reason": " | ".join(buy_conditions),
            "strength": round(score, 2),
            "time": datetime.now().strftime("%H:%M:%S"),
        })
    
    # === 卖出信号 ===
    # 条件A：跌破MA20
    if price < ma20:
        signals.append({
            "type": "SELL",
            "strategy": "趋势跟踪",
            "price": round(price, 2),
            "quantity": SELL_PER_SIGNAL,
            "reason": "跌破MA20均线",
            "strength": 0.8,
            "time": datetime.now().strftime("%H:%M:%S"),
        })
    
    return signals[0] if signals else None


def check_grid_strategy(indicators: Dict[str, Any], df: pd.DataFrame,
                         current_position: int, grid_avg_price: float) -> Optional[Dict[str, Any]]:
    """下跌行情 → 网格加仓策略信号
    
    买入：K线最低价 < 布林下轨 + 多因子评分 + 止跌确认
    卖出：价格 ≥ 网格均价 + ATR 或 布林上轨压制
    """
    if len(df) < 30:
        return None
    
    last = df.iloc[-1]
    prev_3 = df.iloc[-4:-1] if len(df) >= 4 else df.iloc[:-1]
    price = last["close"]
    boll_lower = last.get("BOLL_LOWER", 0)
    boll_upper = last.get("BOLL_UPPER", 0)
    rsi = last.get("RSI", 50)
    atr = last.get("ATR", 0)
    
    # === 买入：触轨 ===
    if boll_lower > 0 and last["low"] < boll_lower:
        # 多因子评分
        score = 0
        if rsi < 30: score += 0.3
        elif rsi < 40: score += 0.2
        if last.get("VOL_RATIO", 1) > 1.3: score += 0.2
        if last["close"] >= last["open"]: score += 0.15
        
        # 止跌确认：前3根K线最低价 >= 当前K线最低价
        if len(prev_3) > 0 and prev_3["low"].min() >= last["low"]:
            score += 0.2
        
        if score >= 0.35:
            return {
                "type": "BUY",
                "strategy": "网格加仓",
                "price": round(price, 2),
                "quantity": 0,  # 由portfolio计算
                "reason": f"触布林下轨({round(boll_lower,2)}) 评分{score:.2f}",
                "strength": round(score, 2),
                "time": datetime.now().strftime("%H:%M:%S"),
            }
    
    # === 卖出：止盈/止损 ===
    if current_position > 0 and grid_avg_price > 0:
        # ATR止盈
        if atr > 0 and price >= grid_avg_price + atr:
            return {
            "type": "SELL",
            "strategy": "网格加仓",
            "price": round(price, 2),
            "quantity": SELL_PER_SIGNAL,
            "reason": f"ATR止盈: 均价{grid_avg_price:.2f}+ATR{atr:.2f}={grid_avg_price+atr:.2f}",
            "strength": 1.0,
            "time": datetime.now().strftime("%H:%M:%S"),
            }
        # 上轨压制
        if boll_upper > 0 and price >= boll_upper:
            return {
            "type": "SELL",
            "strategy": "网格加仓",
            "price": round(price, 2),
            "quantity": SELL_PER_SIGNAL,
            "reason": f"上轨压制: 价{price:.2f}≥上轨{boll_upper:.2f}",
            "strength": 1.0,
            "time": datetime.now().strftime("%H:%M:%S"),
            }
        # RSI超买
        if rsi >= GRID_RSI_EXIT:
            return {
            "type": "SELL",
            "strategy": "网格加仓",
            "price": round(price, 2),
            "quantity": SELL_PER_SIGNAL,
            "reason": f"RSI超买: {rsi:.1f}≥{GRID_RSI_EXIT}",
            "strength": 0.8,
            "time": datetime.now().strftime("%H:%M:%S"),
            }
    
    return None


def check_mean_reversion(indicators: Dict[str, Any], df: pd.DataFrame,
                          current_position: int, buy_price: float = 0) -> Optional[Dict[str, Any]]:
    """横盘行情 → 均值回归策略信号
    
    买入：K线最低价 < 布林下轨 → 即买入，分数定数量
    卖出：价格接近上轨 或 从买入价反弹一定幅度
    """
    if len(df) < 30:
        return None
    
    last = df.iloc[-1]
    prev_3 = df.iloc[-4:-1] if len(df) >= 4 else df.iloc[:-1]
    price = last["close"]
    boll_lower = last.get("BOLL_LOWER", 0)
    boll_upper = last.get("BOLL_UPPER", 0)
    rsi = last.get("RSI", 50)
    
    # === 买入 ===
    if boll_lower > 0 and last["low"] < boll_lower:
        # 多因子评分：只定买入数量，不卡条件
        buy_score = 0.3  # 触轨基础分
        if rsi < 30:
            buy_score += 0.3  # 极度超卖加分
        elif rsi < 40:
            buy_score += 0.15
        if last.get("VOL_RATIO", 1) > 1.3:
            buy_score += 0.15  # 放量下杀加分（恐慌盘）
        if last["close"] >= last["open"]:
            buy_score += 0.1  # 阳线触轨加分
        if len(prev_3) > 0 and prev_3["low"].min() >= last["low"]:
            buy_score += 0.2  # 止跌确认加分
        buy_score = min(buy_score, 1.0)  # 上限1.0
        
        return {
            "type": "BUY",
            "strategy": "均值回归",
            "price": round(price, 2),
            "quantity": 0,
            "reason": f"触布林下轨({round(boll_lower,2)}) 评分{buy_score:.2f}",
            "strength": round(buy_score, 2),
            "time": datetime.now().strftime("%H:%M:%S"),
        }
    
    # === 卖出 ===
    if current_position > 0:
        # 价格接近上轨
        if boll_upper > 0 and boll_lower > 0:
            band_position = (price - boll_lower) / (boll_upper - boll_lower)
            if band_position >= 0.85:
                return {
                    "type": "SELL",
                    "strategy": "均值回归",
                    "price": round(price, 2),
                    "quantity": SELL_PER_SIGNAL,
                    "reason": f"接近布林上轨({round(boll_upper,2)}) 位置{band_position:.0%}",
                    "strength": 0.85,
                    "time": datetime.now().strftime("%H:%M:%S"),
                }
        # 硬止损
        if buy_price > 0:
            loss_ratio = (buy_price - price) / buy_price
            if loss_ratio >= REVERSION_POSITION_STOP:
                return {
                    "type": "SELL",
                    "strategy": "均值回归",
                    "price": round(price, 2),
                    "quantity": SELL_PER_SIGNAL,
                    "reason": f"硬止损: 买入{buy_price:.2f} 现价{price:.2f} 跌幅{loss_ratio*100:.1f}%",
                    "strength": 1.0,
                    "time": datetime.now().strftime("%H:%M:%S"),
                }
    
    return None


def check_all_signals(indicators: Dict[str, Any], df: pd.DataFrame,
                       portfolio_state: Dict[str, Any],
                       classifier: Dict[str, Any] = None) -> List[Dict[str, Any]]:
    """综合检查所有策略信号"""
    signals = []
    position = portfolio_state.get("current_shares", 0)
    grid_avg = portfolio_state.get("grid_avg_price", 0)
    reversion_buy = portfolio_state.get("reversion_buy_price", 0)
    
    # 根据分类器决定当前运行哪个策略
    category = classifier.get("category", "") if classifier else ""
    
    # 趋势跟踪
    if not category or category == "uptrend":
        sig = check_trend_following(indicators, df, position)
        if sig:
            if sig["type"] == "BUY":
                sig["quantity"] = TREND_ORDER_SIZE
                sig["shares"] = TREND_ORDER_SIZE
            signals.append(sig)
    
    # 网格加仓
    if not category or category == "downtrend":
        sig = check_grid_strategy(indicators, df, position, grid_avg)
        if sig:
            if sig["type"] == "BUY":
                # 按信号强度定买入数量
                for level, qty in GRID_VOLUME_LEVELS:
                    if sig["strength"] >= level:
                        sig["quantity"] = qty
                        sig["shares"] = qty
            if sig["type"] == "SELL":
                sig["quantity"] = SELL_PER_SIGNAL
                sig["shares"] = SELL_PER_SIGNAL
            signals.append(sig)
    
    # 均值回归
    if not category or category == "sidelines":
        sig = check_mean_reversion(indicators, df, position, reversion_buy)
        if sig:
            if sig["type"] == "BUY":
                # 按评分定买入数量：最少5000，最多10000
                qty = max(SELL_PER_SIGNAL, int(TREND_ORDER_SIZE * sig.get("strength", 0.5)))
                sig["quantity"] = qty
                sig["shares"] = qty
            if sig["type"] == "SELL":
                sig["quantity"] = SELL_PER_SIGNAL
                sig["shares"] = SELL_PER_SIGNAL
            signals.append(sig)
    
    return signals
