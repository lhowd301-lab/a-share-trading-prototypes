# portfolio.py — 持仓与资金管理

import pandas as pd
import json
import os
from datetime import datetime
from typing import Dict, Any, Optional

from config import (
    INITIAL_SHARES, INITIAL_COST, AVAILABLE_CASH,
    MAX_POSITION_RATIO, MAX_DAILY_LOSS_RATIO, TRADING_QUOTA,
    DAILY_LOG_PATH,
)
TRADE_LOG_PATH = os.path.join(os.path.dirname(DAILY_LOG_PATH), "trade_log.csv")

# 核心底仓（永不卖出）
CORE_SHARES = INITIAL_SHARES - TRADING_QUOTA  # 25312股

# 内存中的持仓状态
_portfolio = {
    "initial_shares": INITIAL_SHARES,
    "initial_cost": INITIAL_COST,
    "current_shares": INITIAL_SHARES,
    "available_cash": AVAILABLE_CASH,
    "cost_basis": INITIAL_COST,
    "last_price": 0,
    "stock_value": 0,
    "total_value": AVAILABLE_CASH + INITIAL_SHARES * INITIAL_COST,
    "grid_positions": [],     # 网格加仓的各笔持仓 [{"shares": int, "price": float}]
    "reversion_position": {"shares": 0, "price": 0},  # 均值回归当前持仓
    "grid_avg_price": 0,
    "reversion_buy_price": 0,
    "daily_pnl": 0,
    "daily_trades": [],
    "last_updated": "",
}

TRADE_LOG_PATH = os.path.join(os.path.dirname(DAILY_LOG_PATH), "trade_log.csv")


def get_portfolio_state() -> Dict[str, Any]:
    """获取当前持仓状态"""
    return {**_portfolio}


def set_portfolio_state(state: Dict[str, Any]):
    """从持久化状态恢复持仓（用于重启恢复）"""
    global _portfolio
    for key in _portfolio:
        if key in state:
            _portfolio[key] = state[key]
    _portfolio["last_updated"] = datetime.now().strftime("%H:%M:%S")
    _portfolio["daily_trades"] = []


def update_portfolio_price(price: float) -> Dict[str, Any]:
    """根据最新股价更新持仓估值"""
    _portfolio["last_price"] = price
    _portfolio["stock_value"] = _portfolio["current_shares"] * price
    total = _portfolio["stock_value"] + _portfolio["available_cash"]
    _portfolio["total_value"] = total
    _portfolio["last_updated"] = datetime.now().strftime("%H:%M:%S")
    return get_portfolio_state()


def execute_trade(signal: Dict[str, Any]) -> Dict[str, Any]:
    """执行交易（模拟），更新持仓"""
    trade_type = signal["type"]
    price = signal["price"]
    quantity = signal.get("quantity", 0)
    strategy = signal.get("strategy", "")
    
    result = {"success": False, "message": "", "trade": None}
    
    if trade_type == "BUY":
        cost = price * quantity
        # 做T仓位上限保护
        max_buyable = max(0, (INITIAL_SHARES + TRADING_QUOTA) - _portfolio["current_shares"])
        quantity = min(quantity, max_buyable)
        if quantity <= 0:
            result["message"] = "做T仓位已达上限"
            return result
        if cost > _portfolio["available_cash"]:
            result["message"] = f"资金不足: 需{cost:.0f} 可用{_portfolio['available_cash']:.0f}"
            return result
        
        # 更新持仓
        total_cost_before = _portfolio["current_shares"] * _portfolio["cost_basis"]
        total_shares = _portfolio["current_shares"] + quantity
        _portfolio["cost_basis"] = (total_cost_before + cost) / total_shares if total_shares > 0 else 0
        _portfolio["current_shares"] = total_shares
        _portfolio["available_cash"] -= cost
        
        # 策略专用记录
        if strategy == "网格加仓":
            _portfolio["grid_positions"].append({"shares": quantity, "price": price})
            _portfolio["grid_avg_price"] = sum(p["shares"] * p["price"] for p in _portfolio["grid_positions"]) / \
                                           sum(p["shares"] for p in _portfolio["grid_positions"])
        elif strategy == "均值回归":
            _portfolio["reversion_position"] = {"shares": quantity, "price": price}
            _portfolio["reversion_buy_price"] = price
        
        result["success"] = True
        result["message"] = f"买入{quantity}股 @ {price:.2f}"
        
    elif trade_type == "SELL":
        quantity = min(quantity, _portfolio["current_shares"])
        # 保护底仓：最多只能卖做T部分
        max_sellable = max(0, _portfolio["current_shares"] - CORE_SHARES)
        quantity = min(quantity, max_sellable)
        if quantity <= 0:
            result["message"] = "无可卖持仓"
            return result
        
        revenue = price * quantity
        _portfolio["current_shares"] -= quantity
        _portfolio["available_cash"] += revenue
        
        # 清理策略记录
        if strategy == "网格加仓":
            _portfolio["grid_positions"] = []
            _portfolio["grid_avg_price"] = 0
        elif strategy == "均值回归":
            _portfolio["reversion_position"] = {"shares": 0, "price": 0}
            _portfolio["reversion_buy_price"] = 0
    
    result["success"] = True
    result["message"] = f"卖出{quantity}股 @ {price:.2f}"
    
    _portfolio["stock_value"] = _portfolio["current_shares"] * price
    _portfolio["total_value"] = _portfolio["stock_value"] + _portfolio["available_cash"]
    _portfolio["daily_trades"].append({
        "time": datetime.now().strftime("%H:%M:%S"),
        "type": trade_type,
        "price": price,
        "shares": quantity,
        "strategy": strategy,
    })
    
    result["trade"] = {
        "time": datetime.now().strftime("%H:%M:%S"),
        "type": trade_type,
        "price": round(price, 2),
        "shares": quantity,
        "strategy": strategy,
    }
    # 记录交易日志到CSV
    _write_trade_log(result["trade"])
    
    return result
def _write_trade_log(trade: Dict[str, Any]):
    """写入交易日志到CSV"""
    import csv
    file_exists = os.path.exists(TRADE_LOG_PATH)
    fieldnames = ["time", "type", "strategy", "price", "shares",
                  "position_after", "cash_after", "reason"]
    try:
        with open(TRADE_LOG_PATH, mode="a", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            writer.writerow({
                "time": trade.get("time", ""),
                "type": trade.get("type", ""),
                "strategy": trade.get("strategy", ""),
                "price": trade.get("price", 0),
                "shares": trade.get("shares", 0),
                "position_after": _portfolio.get("current_shares", 0),
                "cash_after": round(_portfolio.get("available_cash", 0), 2),
                "reason": trade.get("reason", ""),
            })
    except Exception as e:
        print(f"[portfolio] 写入交易日志失败: {e}")


def reset_daily_state():
    """重置日内交易状态"""
    global _portfolio
    _portfolio["daily_trades"] = []
    _portfolio["grid_positions"] = []
    _portfolio["grid_avg_price"] = 0
    _portfolio["reversion_position"] = {"shares": 0, "price": 0}
    _portfolio["reversion_buy_price"] = 0
    _portfolio["last_updated"] = datetime.now().strftime("%H:%M:%S")


def load_previous_position():
    """从每日记录加载上一日的持仓"""
    if not os.path.exists(DAILY_LOG_PATH):
        return
    try:
        df = pd.read_csv(DAILY_LOG_PATH)
        if df.empty:
            return
        last_row = df.iloc[-1]
        _portfolio["current_shares"] = int(last_row.get("持仓股数", INITIAL_SHARES))
        _portfolio["cost_basis"] = float(last_row.get("成本价", INITIAL_COST))
        _portfolio["available_cash"] = float(last_row.get("可用资金", AVAILABLE_CASH))
        print(f"[portfolio] 从历史记录加载: 持仓{_portfolio['current_shares']}股 "
              f"成本{_portfolio['cost_basis']:.3f} 现金{_portfolio['available_cash']:.0f}")
    except Exception as e:
        print(f"[portfolio] 加载历史持仓失败: {e}")


def save_daily_snapshot(price: float):
    """保存每日持仓快照"""
    from daily_logger import save_daily_record
    save_daily_record({
        "date": datetime.now().strftime("%Y-%m-%d"),
        "shares": _portfolio["current_shares"],
        "cost_basis": _portfolio["cost_basis"],
        "stock_price": price,
        "stock_value": _portfolio["current_shares"] * price,
        "available_cash": _portfolio["available_cash"],
        "total_value": _portfolio["current_shares"] * price + _portfolio["available_cash"],
        "daily_pnl": _portfolio["daily_pnl"],
        "trades": len(_portfolio["daily_trades"]),
    })


# 改为由 state_store 管理持仓持久化
# load_previous_position()  # 禁用，避免覆盖 state_store
