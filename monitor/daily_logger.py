# daily_logger.py — 每日数据自动记录

import csv
import os
from datetime import datetime
from typing import Dict, Any, List, Optional
import pandas as pd

from config import DAILY_LOG_PATH, SIGNAL_LOG_PATH


def save_daily_record(record: Dict[str, Any]):
    """保存每日持仓快照到CSV
    
    record格式:
        date, shares, cost_basis, stock_price, stock_value,
        available_cash, total_value, daily_pnl, trades
    """
    file_exists = os.path.exists(DAILY_LOG_PATH)
    fieldnames = [
        "date", "shares", "cost_basis", "stock_price",
        "stock_value", "available_cash", "total_value",
        "daily_pnl", "trades", "updated_at",
    ]
    
    with open(DAILY_LOG_PATH, mode="a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        
        writer.writerow({
            "date": record.get("date", datetime.now().strftime("%Y-%m-%d")),
            "shares": record.get("shares", 0),
            "cost_basis": round(record.get("cost_basis", 0), 3),
            "stock_price": round(record.get("stock_price", 0), 2),
            "stock_value": round(record.get("stock_value", 0), 2),
            "available_cash": round(record.get("available_cash", 0), 2),
            "total_value": round(record.get("total_value", 0), 2),
            "daily_pnl": round(record.get("daily_pnl", 0), 2),
            "trades": record.get("trades", 0),
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })


def save_signal_log(signal: Dict[str, Any]):
    """记录信号到CSV"""
    file_exists = os.path.exists(SIGNAL_LOG_PATH)
    fieldnames = ["time", "type", "strategy", "price", "quantity", "reason", "strength"]
    
    with open(SIGNAL_LOG_PATH, mode="a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow({
            "time": signal.get("time", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            "type": signal.get("type", ""),
            "strategy": signal.get("strategy", ""),
            "price": signal.get("price", 0),
            "quantity": signal.get("quantity", 0),
            "reason": signal.get("reason", ""),
            "strength": signal.get("strength", 0),
        })


def load_daily_records() -> pd.DataFrame:
    """读取每日记录"""
    if not os.path.exists(DAILY_LOG_PATH):
        return pd.DataFrame()
    return pd.read_csv(DAILY_LOG_PATH)


def load_signal_log() -> pd.DataFrame:
    """读取信号日志"""
    if not os.path.exists(SIGNAL_LOG_PATH):
        return pd.DataFrame()
    return pd.read_csv(SIGNAL_LOG_PATH)


def auto_save_market_close(portfolio_state: Dict[str, Any]):
    """收盘时自动保存（由调度器调用）"""
    if portfolio_state.get("current_shares", 0) > 0:
        print(f"[daily_logger] 收盘自动保存: 持仓{portfolio_state['current_shares']}股 "
              f"价值{portfolio_state['stock_value']:.0f}")
        save_daily_record({
            "date": datetime.now().strftime("%Y-%m-%d"),
            "shares": portfolio_state["current_shares"],
            "cost_basis": portfolio_state["cost_basis"],
            "stock_price": portfolio_state["last_price"],
            "stock_value": portfolio_state["stock_value"],
            "available_cash": portfolio_state["available_cash"],
            "total_value": portfolio_state["total_value"],
            "daily_pnl": portfolio_state.get("daily_pnl", 0),
            "trades": len(portfolio_state.get("daily_trades", [])),
        })
        print("[daily_logger] 收盘记录已保存")
    else:
        print("[daily_logger] 收盘无持仓，跳过记录")
