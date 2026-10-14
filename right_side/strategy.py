"""
strategy.py — 右侧交易核心逻辑（修复版）

核心思想：
  1. 股价下探布林下轨（支撑位）
  2. 等待确认止跌（连续 N 根 K 线不再创新低）
  3. 右侧确认后发出买入信号
  4. 附加过滤器：量能、RSI 超卖、大趋势方向

关键修复：
  - evaluate() 不再检查最新 K 线（无未来数据），而是向后看
    confirm_bars 根，找已可确认的触轨点
"""
from dataclasses import dataclass, field
from typing import List, Optional
import numpy as np
import pandas as pd
from config import CFG


@dataclass
class Signal:
    timestamp: str
    price: float
    reason: str
    strength: float
    lower_band: float
    filters_passed: List[str] = field(default_factory=list)
    filters_failed: List[str] = field(default_factory=list)


# ── 内部检查函数 ─────────────────────────────────────────────────────────

def _check_touch_lower(df: pd.DataFrame, i: int) -> bool:
    low, lower = df["low"].iloc[i], df["boll_lower"].iloc[i]
    return low <= lower


def _check_confirmation(df: pd.DataFrame, i: int) -> bool:
    """确认止跌：从触轨位置往后看 confirm_bars 根 K 线

    条件：此后 confirm_bars 根 K 线不再创新低。
    换言之，每次最低价都 >= 触轨时的最低价。
    """
    cfg = CFG.bollinger
    bars = cfg.confirm_bars

    if i + 1 + bars > len(df):
        return False  # 未来数据不够

    touch_low = df["low"].iloc[i]
    segment = df.iloc[i + 1: i + 1 + bars]
    no_new_low = segment["low"].min() >= touch_low
    return no_new_low


def _check_filters(df: pd.DataFrame, i: int) -> tuple:
    """返回 (passed_bool, passed_list, failed_list)"""
    passed, failed = [], []

    if CFG.filters.use_volume_filter:
        vr = df["volume_ratio"].iloc[i]
        if not np.isnan(vr) and vr >= CFG.filters.volume_ratio_min:
            passed.append("volume_ok")
        else:
            failed.append("volume_low")

    if CFG.filters.use_rsi_filter:
        r = df["rsi"].iloc[i]
        if not np.isnan(r) and r <= CFG.filters.rsi_oversold:
            passed.append("rsi_oversold")
        else:
            failed.append("rsi_not_oversold")

    if CFG.filters.use_trend_filter:
        td = df["trend_direction"].iloc[i]
        if td == -1:
            passed.append("trend_cautious")
        elif td == 1:
            passed.append("trend_favorable")
        else:
            passed.append("trend_neutral")

    filters_used = sum([CFG.filters.use_volume_filter, CFG.filters.use_rsi_filter])
    core_passed = any("volume" in p or "rsi" in p for p in passed) if filters_used > 0 else True
    return core_passed, passed, failed


# ── 核心评估函数 ─────────────────────────────────────────────────────────

def evaluate(df: pd.DataFrame, last_signal_time: Optional[str] = None) -> Optional[Signal]:
    """评估最新一批 K 线中是否有可执行的右侧信号

    时序逻辑（关键）：
      实盘中最新 K 线无未来数据，因此从"当前时间 - confirm_bars"位置
      寻找触轨 + 已可确认的组合。

    Parameters
    ----------
    df : pd.DataFrame
        含全部指标的分钟 K 线
    last_signal_time : str or None
        上次已触发的信号时间戳，用于防重复

    Returns
    -------
    Signal or None
    """
    if df is None or len(df) < CFG.bollinger.period + CFG.bollinger.confirm_bars:
        return None

    df = df.reset_index(drop=True)
    i = len(df) - 1

    # 从 i - confirm_bars 开始往回扫描，找触轨 + 已可确认的位置
    max_lookback = min(CFG.bollinger.confirm_bars * 2, i - CFG.bollinger.period)
    for offset in range(CFG.bollinger.confirm_bars, max_lookback + 1):
        touch_idx = i - offset
        if touch_idx < 0:
            break

        # 防重复
        if last_signal_time is not None:
            touch_time = str(df["time"].iloc[touch_idx])
            if touch_time <= last_signal_time:
                continue

        # 1. 触轨
        if not _check_touch_lower(df, touch_idx):
            continue

        # 2. 有足够未来数据可确认
        if not _check_confirmation(df, touch_idx):
            continue

        # 3. 过滤器
        passed, pl, fl = _check_filters(df, touch_idx)

        # 4. 信号强度
        strength = _calc_strength(df, touch_idx, passed)

        return Signal(
            timestamp=str(df["time"].iloc[touch_idx]),
            price=float(df["close"].iloc[touch_idx]),
            reason="右侧触下轨 + 止跌确认",
            strength=strength,
            lower_band=float(df["boll_lower"].iloc[touch_idx]),
            filters_passed=pl,
            filters_failed=fl,
        )

    return None


# ── 信号强度评分 ─────────────────────────────────────────────────────────

def _calc_strength(df: pd.DataFrame, idx: int, _: bool) -> float:
    score = 0.5

    width = df["boll_width"].iloc[idx]
    if not np.isnan(width):
        if width < 3:
            score += 0.2
        elif width > 8:
            score -= 0.1

    r = df["rsi"].iloc[idx]
    if not np.isnan(r):
        if r <= 20:
            score += 0.2
        elif r <= 25:
            score += 0.1
        elif r >= 40:
            score -= 0.1

    close, lower = df["close"].iloc[idx], df["boll_lower"].iloc[idx]
    dist = (close - lower) / max(lower, 0.01) * 100
    if dist < 0.5:
        score += 0.1

    td = df["trend_direction"].iloc[idx]
    if td == 1:
        score += 0.1
    elif td == -1:
        score -= 0.1

    return float(np.clip(score, 0.0, 1.0))


# ── 批量扫描（用于回测/回放） ────────────────────────────────────────────

def scan_recent_signals(df: pd.DataFrame, lookback: int = 50) -> List[Signal]:
    signals = []
    df = df.reset_index(drop=True)

    start = max(CFG.bollinger.period, len(df) - lookback)
    for i in range(start, len(df)):
        if not _check_touch_lower(df, i):
            continue
        if not _check_confirmation(df, i):
            continue
        passed, pl, fl = _check_filters(df, i)
        strength = _calc_strength(df, i, passed)
        sig = Signal(
            timestamp=str(df["time"].iloc[i]),
            price=float(df["close"].iloc[i]),
            reason="回扫发现右侧信号",
            strength=strength,
            lower_band=float(df["boll_lower"].iloc[i]),
            filters_passed=pl,
            filters_failed=fl,
        )
        signals.append(sig)

    return signals


# ── 简单测试 ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    np.random.seed(42)
    test = pd.DataFrame({
        "time": pd.date_range("2026-07-21 09:31", periods=200, freq="min"),
        "close": 95 + np.cumsum(np.random.randn(200) * 0.4),
        "high": 95 + np.cumsum(np.random.randn(200) * 0.4) + 0.2,
        "low": 95 + np.cumsum(np.random.randn(200) * 0.4) - 0.2,
        "volume": np.random.randint(5000, 20000, 200),
        "open": 95 + np.cumsum(np.random.randn(200) * 0.4),
        "amount": np.random.randint(500000, 2000000, 200),
    })
    from indicators import compute_all
    test = compute_all(test)

    sig = evaluate(test)
    if sig:
        print("当前信号:", sig)
    else:
        print("当前无信号")

    all_sigs = scan_recent_signals(test, lookback=100)
    print(f"\n历史回扫发现 {len(all_sigs)} 个信号")
    for s in all_sigs[-5:]:
        print(f"  {s.timestamp}  @ {s.price:.2f}  强度 {s.strength:.2f}")
