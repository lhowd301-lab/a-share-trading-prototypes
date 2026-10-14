"""
信维通信 · 右侧交易策略 — 全局配置
"""
from dataclasses import dataclass, field
from typing import Literal


# ── 标的 & 持仓 ──────────────────────────────────────────────────────────────
TICKER = "300136"          # 信维通信，深交所
EXCHANGE = "SZ"            # SZ / SH
FULL_TICKER = f"{TICKER}.{EXCHANGE}"

HOLDING_SHARES = 1000  # public demo
AVG_COST = 20.0  # public demo
AVAILABLE_CASH = 100_000 # 可用资金（元）


# ── 交易参数 ────────────────────────────────────────────────────────────────
MAX_BUY_SHARES_PER_MIN = 20000
MAX_DAILY_BUY_SHARES = 40000
MIN_TRADE_LOT = 100


# ── 布林带参数 ───────────────────────────────────────────────────────────────
@dataclass
class BollingerConfig:
    """布林带配置"""
    period: int = 20
    std_multiplier: float = 2.0
    smoothing: Literal["sma", "ema"] = "sma"
    confirm_bars: int = 3          # 触下轨后需 N 根 K 线确认止跌
    confirm_threshold: float = 0.0 # 确认涨幅阈值（%）


# ── 附加过滤器 ────────────────────────────────────────────────────────────────
@dataclass
class FilterConfig:
    use_volume_filter: bool = True
    volume_ma_period: int = 5
    volume_ratio_min: float = 0.6
    use_rsi_filter: bool = True
    rsi_period: int = 14
    rsi_oversold: float = 30.0
    use_trend_filter: bool = True
    trend_ma_period: int = 60


# ── 止盈止损 ──────────────────────────────────────────────────────────────────
@dataclass
class StopConfig:
    """日内止损/止盈"""
    stop_loss_pct: float = -1.5
    take_profit_pct: float = 0.0
    trailing_stop_activate: float = 2.0
    trailing_stop_distance: float = 0.8


# ── 数据 & 执行 ───────────────────────────────────────────────────────────────
@dataclass
class ExecutionConfig:
    min_bar: Literal["1min", "5min"] = "1min"
    lookback_days: int = 5
    refresh_interval_sec: int = 60
    data_dir: str = "./data/raw"
    log_dir: str = "./logs"
    paper_trading: bool = True


# ── 整合配置 ──────────────────────────────────────────────────────────────────
@dataclass
class Config:
    bollinger: BollingerConfig = field(default_factory=BollingerConfig)
    filters: FilterConfig = field(default_factory=FilterConfig)
    stops: StopConfig = field(default_factory=StopConfig)
    exec_: ExecutionConfig = field(default_factory=ExecutionConfig)


CFG = Config()
