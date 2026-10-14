"""
main.py — 主执行循环

流程：
  1. 初始化仓位模型
  2. 加载历史分钟线（预热指标）
  3. 进入实时循环
     a. 拉取最新分钟数据
     b. 计算指标
     c. 评估信号（含防重复）
     d. 有信号 → 用 AllocationModel 计算仓位 → 执行
     e. 更新模型内部状态
     f. 止损检查
  4. 收盘输出
"""
import time
import logging
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from config import CFG, TICKER, HOLDING_SHARES, AVG_COST, AVAILABLE_CASH
from data_fetcher import fetch_intraday_minutes, fetch_history_minutes, get_current_price
from indicators import compute_all
from strategy import evaluate
from position_sizing import AllocationModel
from risk_manager import check_stop, update_pnl, ensure_daily_reset, DAILY


# ── 日志 ──────────────────────────────────────────────────────────────────
def setup_logger():
    log_dir = Path(CFG.exec.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y%m%d")
    log_file = log_dir / f"trading_{today}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-5s | %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger(__name__)


logger = setup_logger()


# ── 全局状态 ──────────────────────────────────────────────────────────────
allocation_model = AllocationModel(H=HOLDING_SHARES, C=AVG_COST, R=AVAILABLE_CASH)
last_signal_time: str | None = None


# ── 预热 ──────────────────────────────────────────────────────────────────
def warmup_indicators() -> pd.DataFrame | None:
    logger.info("预热：加载最近 %d 天分钟数据…", CFG.exec.lookback_days)
    df = fetch_history_minutes(ticker=TICKER, period=CFG.exec.min_bar, days=CFG.exec.lookback_days)
    if df is None or df.empty:
        logger.warning("无历史数据")
        return None
    df = compute_all(df)
    logger.info("预热完成，共 %d 条 K 线", len(df))
    return df


# ── 单次循环 ─────────────────────────────────────────────────────────────
def run_once(minute_buffer: pd.DataFrame) -> pd.DataFrame:
    global last_signal_time

    # 1. 拉新数据
    new_df = fetch_intraday_minutes(ticker=TICKER, period=CFG.exec.min_bar, save_raw=True)
    if new_df is None or new_df.empty:
        return minute_buffer

    # 2. 增量追加
    if minute_buffer is not None and not minute_buffer.empty:
        last_time = minute_buffer["time"].iloc[-1]
        new_df = new_df[new_df["time"] > last_time]
        if new_df.empty:
            return minute_buffer
        minute_buffer = pd.concat([minute_buffer, new_df], ignore_index=True)
    else:
        minute_buffer = new_df

    # 3. 计算指标
    minute_buffer = compute_all(minute_buffer)

    # 4. 检查数据量
    min_required = CFG.bollinger.period + CFG.bollinger.confirm_bars
    if len(minute_buffer) < min_required:
        logger.info("等待 K 线积累… (%d/%d)", len(minute_buffer), min_required)
        return minute_buffer

    # 5. 获取当前价
    current_price = get_current_price(TICKER)
    if current_price is None:
        current_price = minute_buffer["close"].iloc[-1]

    # 6. 更新浮动盈亏 & 止损
    update_pnl(current_price)
    ensure_daily_reset()

    # 7. 止损检查
    if check_stop():
        logger.warning("⚠ 日内亏损达 %.2f%%，暂停买入",
                       abs(CFG.stops.stop_loss_pct))
        return minute_buffer

    # 8. 信号评估
    signal = evaluate(minute_buffer, last_signal_time)

    if signal is not None:
        # 更新防重复标记
        last_signal_time = signal.timestamp

        # 用 AllocationModel 算仓位
        result = allocation_model.allocate(
            price=current_price,
            signal_strength=signal.strength,
            boll_width=signal.lower_band,  # 实际是 - 这里传 lower_band 作为参考
            verbose=False,
        )

        if result.shares >= 100:
            logger.info(
                "\n" + result.summary()
            )

            # 执行
            if CFG.exec.paper_trading:
                _paper_buy(result.shares, current_price)
                allocation_model.commit(result, current_price)

                # 更新外部 DAILY 状态
                DAILY.daily_bought_shares += result.shares
                DAILY.buy_count += 1
                DAILY.last_buy_price = current_price
        else:
            logger.info("信号存在但被模型拦截（计算量不足 1 手）")
    else:
        last_close = minute_buffer["close"].iloc[-1]
        last_lower = minute_buffer["boll_lower"].iloc[-1]
        last_rsi = minute_buffer["rsi"].iloc[-1]
        logger.info(
            "等待信号  |  当前 %.2f  |  下轨 %.2f  |  RSI %.1f  |  均价 %s%.3f",
            last_close, last_lower, last_rsi,
            "" if allocation_model.C >= AVG_COST else "",
            allocation_model.C,
        )

    return minute_buffer


def _paper_buy(shares: int, price: float):
    amount = shares * price
    logger.info("[纸交易] 买入 %d 股 @ %.2f = %.2f 元", shares, price, amount)


def daily_summary():
    logger.info(
        "\n══════════════════ 日终总结 ══════════════════\n"
        "  日期      : %s\n"
        "  买入次数  : %d\n"
        "  本日买入  : %d 股\n"
        "  累计买入  : %d 股（不含底仓）\n"
        "  当前均价  : %.3f\n"
        "  可用剩余  : %.2f 万\n"
        "  暂停标记  : %s\n"
        "════════════════════════════════════════════════",
        DAILY.date,
        DAILY.buy_count,
        DAILY.daily_bought_shares,
        allocation_model.H - HOLDING_SHARES,
        allocation_model.C,
        allocation_model.R / 10000,
        "是" if DAILY.is_paused else "否",
    )


# ── 入口 ──────────────────────────────────────────────────────────────────
def main():
    logger.info("=" * 58)
    logger.info("  信维通信 · 右侧交易策略")
    logger.info("  底仓: %d 股 @ %.3f", HOLDING_SHARES, AVG_COST)
    logger.info("  可用: %.2f 万", AVAILABLE_CASH / 10000)
    logger.info("  模式: %s", "纸交易" if CFG.exec.paper_trading else "实盘")
    logger.info("=" * 58)

    buffer = warmup_indicators()

    try:
        while True:
            buffer = run_once(buffer)
            time.sleep(CFG.exec.refresh_interval_sec)
    except KeyboardInterrupt:
        logger.info("\n用户中断")
    finally:
        daily_summary()


if __name__ == "__main__":
    main()
