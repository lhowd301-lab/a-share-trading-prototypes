"""
risk_manager.py — 仓位管理与风险控制

功能：
  - 根据可用资金与信号强度计算买入量
  - 日内累计买入限额
  - 止损 / 移动止盈
  - 成本估算
"""
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional
from config import (
    CFG, AVG_COST, AVAILABLE_CASH, HOLDING_SHARES,
    MAX_BUY_SHARES_PER_MIN, MAX_DAILY_BUY_SHARES, MIN_TRADE_LOT
)
from strategy import Signal


# ── 日内状态 ─────────────────────────────────────────────────────────────────
@dataclass
class DailyState:
    """日内交易状态"""
    date: str = ""
    daily_bought_shares: int = 0     # 当日已买入股数
    daily_realized_pnl: float = 0.0  # 当日已实现盈亏（暂未用）
    daily_unrealized_pnl: float = 0.0  # 当日浮动盈亏
    buy_count: int = 0               # 当日买入次数
    last_buy_price: float = 0.0      # 上次买入均价
    is_paused: bool = False          # 是否因止损暂停

    def reset(self):
        """每日开盘重置"""
        self.daily_bought_shares = 0
        self.daily_realized_pnl = 0.0
        self.daily_unrealized_pnl = 0.0
        self.buy_count = 0
        self.last_buy_price = 0.0
        self.is_paused = False


DAILY = DailyState()


# ── 仓位计算 ─────────────────────────────────────────────────────────────────
def calc_buy_shares(
    signal: Signal,
    current_price: float,
    state: Optional[DailyState] = None,
) -> int:
    """根据信号强度和风控规则计算本次买入股数"""
    state = state or DAILY

    # 1. 检查是否暂停
    if state.is_paused:
        return 0

    # 2. 检查日限
    remaining_daily = MAX_DAILY_BUY_SHARES - state.daily_bought_shares
    if remaining_daily <= 0:
        return 0

    # 3. 可用资金约束
    max_shares_by_cash = int(AVAILABLE_CASH // (current_price * 100) * 100)

    # 4. 信号强度 → 仓位系数
    strength = signal.strength  # 0~1
    if strength >= 0.8:
        ratio = 1.0       # 强势信号，全仓
    elif strength >= 0.6:
        ratio = 0.6       # 中等信号，半仓以上
    elif strength >= 0.4:
        ratio = 0.3       # 一般信号，小仓
    else:
        ratio = 0.15      # 弱信号，试探仓

    # 5. 计算目标股数
    target = int(int(MAX_BUY_SHARES_PER_MIN * ratio) // MIN_TRADE_LOT * MIN_TRADE_LOT)

    # 6. 约束截断
    target = min(target, remaining_daily, max_shares_by_cash)
    target = max(target, 0)

    # 如果余量连 1 手都不够，放弃
    if target < MIN_TRADE_LOT:
        return 0

    return target


def estimate_new_cost(current_price: float, buy_shares: int) -> float:
    """估算买入后的持仓均价
    
    新均价 = (原持仓市值 + 新买入金额) / (原股数 + 新股数)
    """
    new_shares = HOLDING_SHARES + buy_shares
    new_value = HOLDING_SHARES * AVG_COST + buy_shares * current_price
    if new_shares <= 0:
        return 0.0
    return new_value / new_shares


def estimate_cost_to_target(target_cost: float, current_price: float) -> int:
    """估算将成本降低到 target_cost 所需的买入股数
    
    公式: target_cost = (H * C + X * P) / (H + X)
          → X = H * (C - target) / (target - P)
    """
    if current_price >= target_cost:
        return 0  # 现价高于目标价，买了反而拉高成本
    numerator = HOLDING_SHARES * (AVG_COST - target_cost)
    denominator = target_cost - current_price
    if denominator <= 0:
        return MAX_DAILY_BUY_SHARES
    needed = int(numerator / denominator)
    return int(needed // MIN_TRADE_LOT * MIN_TRADE_LOT)


# ── 止损判断 ─────────────────────────────────────────────────────────────────
def check_stop(state: Optional[DailyState] = None) -> bool:
    """检查当日是否触发止损，返回 True 代表应暂停"""
    state = state or DAILY
    if state.daily_unrealized_pnl < 0:
        loss_pct = abs(state.daily_unrealized_pnl) / AVAILABLE_CASH * 100
        if loss_pct >= abs(CFG.stops.stop_loss_pct):
            state.is_paused = True
            return True
    return False


def update_pnl(current_price: float, state: Optional[DailyState] = None):
    """更新日内浮动盈亏"""
    state = state or DAILY
    state.daily_unrealized_pnl = (
        HOLDING_SHARES * (current_price - AVG_COST)
        + state.daily_bought_shares * (current_price - state.last_buy_price)
    )


# ── 每日状态管理 ─────────────────────────────────────────────────────────────
def ensure_daily_reset(state: Optional[DailyState] = None):
    """检查是否需要跨日重置"""
    state = state or DAILY
    today = datetime.now().strftime("%Y-%m-%d")
    if state.date != today:
        state.reset()
        state.date = today


if __name__ == "__main__":
    # 测试：当前价 70，信号强度 0.7，想降到 90
    needed = estimate_cost_to_target(target_cost=90.0, current_price=70.0)
    print(f"目标成本 90，现价 70，需买入约 {needed} 股")
    print(f"买入后新均价 {estimate_new_cost(70.0, needed):.2f}")
