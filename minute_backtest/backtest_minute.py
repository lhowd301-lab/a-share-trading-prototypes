
from pathlib import Path as _PublicPath
_PUBLIC_ROOT = _PublicPath(__file__).resolve().parents[1]
import pandas as pd
import numpy as np
from datetime import datetime
import os

CODE = "300136"
NAME = "信维通信"
INITIAL_SHARES = 1000  # public demo
INITIAL_COST = 20.0  # public demo
INITIAL_CASH = 100000
COMMISSION_RATE = 0.0003  # 万三

DATA_PATH = str(_PUBLIC_ROOT / 'minute_backtest/data/300136_1min_2026-07-28_with_indicators.csv')
OUT_PATH = str(_PUBLIC_ROOT / 'minute_backtest/data/信维通信300136_20260728_回测v3.xlsx')

def backtest(df):
    s = INITIAL_SHARES        # total shares held
    c = INITIAL_COST          # avg cost
    a = INITIAL_CASH          # available cash
    gs = 0                    # grid shares (downtrend)
    gc = 0                    # grid avg cost
    gr = 0                    # grid highest price
    gt = None                 # grid start time
    t = None                  # regular position dict {price, shares, regime, high}
    rh = 0                    # position high

    trades = []
    prev_regime = None
    regime = "sideways"
    regime_change_time = None

    for i in range(len(df)):
        if i < 30:
            continue

        bar = df.iloc[i]
        ts = bar["time"]
        close = bar["close"]
        low = bar["low"]
        high = bar["high"]

        # Get indicators
        boll_u = bar.get("boll_upper")
        boll_m = bar.get("boll_mid")
        boll_l = bar.get("boll_lower")
        r14 = bar.get("rsi14")
        md = bar.get("macd_hist")
        sma = bar.get("sma20")
        slp = bar.get("sma20_slope")
        atr_ = bar.get("atr14")
        vol = bar.get("volume")
        vma = bar.get("volume_ma20")
        bpos = bar.get("boll_pos")

        # Skip if indicators not ready
        if pd.isna(boll_l) or pd.isna(r14) or pd.isna(atr_):
            continue

        # === Market classification ===
        score = 0
        if pd.notna(slp):
            if slp > 0.05: score += 30
            elif slp > 0: score += 15
            elif slp > -0.05: score -= 15
            else: score -= 30
        if pd.notna(bpos):
            if bpos > 70: score += 30
            elif bpos > 55: score += 15
            elif bpos > 45: score += 0
            elif bpos > 30: score -= 15
            else: score -= 30
        if pd.notna(r14):
            score += round((r14 - 50) * 0.4)
        if pd.notna(md):
            md_sc = md * 50
            if md_sc > 20: md_sc = 20
            elif md_sc < -20: md_sc = -20
            score += round(md_sc)

        old_regime = regime
        regime = "uptrend" if score > 20 else "downtrend" if score < -20 else "sideways"

        # Regime change -> reset tracking vars, keep shares (no sell)
        if regime != old_regime:
            t = None; rh = 0
            gs = 0; gc = 0; gr = 0; gt = None
            prev_regime = regime
            regime_change_time = ts

        # Update position high water mark
        if t is not None:
            rh = max(rh, high)
        if gs > 0:
            gr = max(gr, high)

        # === SELL checks ===
        sell_reason = None
        if regime == "uptrend" and t is not None:
            bp = t["price"]
            if close >= boll_u:
                sell_reason = "触及布林上轨"
            elif close >= bp + 1.5 * atr_:
                sell_reason = "ATR止盈"
            elif close <= bp - 2 * atr_:
                sell_reason = "止损"
            elif close <= sma:
                sell_reason = "跌破均线-趋势结束"
            elif r14 >= 75:
                sell_reason = "RSI超买"

        elif regime == "sideways" and t is not None:
            bp = t["price"]
            if close >= boll_u:
                sell_reason = "触及布林上轨"
            elif close >= bp + atr_:
                sell_reason = "ATR止盈"
            elif close <= bp * 0.985:
                sell_reason = "止损"
            elif r14 >= 70:
                sell_reason = "RSI超买"

        elif regime == "downtrend" and gs > 0:
            if close >= gc + atr_:
                sell_reason = "ATR止盈"
            elif close >= boll_u:
                sell_reason = "触及布林上轨"
            elif r14 >= 70:
                sell_reason = "RSI超买"
            # 尾盘清仓 not implemented for minutely backtest

        if sell_reason:
            if regime == "downtrend" and gs > 0:
                comm2 = close * gs * COMMISSION_RATE
                pnl = gs * (close - gc) - comm2
                a += close * gs - comm2
                s -= gs
                trades.append({
                    "time": ts, "type": "SELL", "regime": regime,
                    "reason": sell_reason, "price": close,
                    "shares": gs, "cost": gc, "pnl": round(pnl, 2),
                    "total_shares": s, "cash": round(a, 2)
                })
                gs = 0; gc = 0; gr = 0; gt = None
            elif t is not None:
                comm2 = t["shares"] * close * COMMISSION_RATE
                pnl = t["shares"] * (close - t["price"]) - comm2
                a += close * t["shares"] - comm2
                s -= t["shares"]
                trades.append({
                    "time": ts, "type": "SELL", "regime": regime,
                    "reason": sell_reason, "price": close,
                    "shares": t["shares"], "cost": t["price"], "pnl": round(pnl, 2),
                    "total_shares": s, "cash": round(a, 2)
                })
                t = None; rh = 0

        # === BUY checks ===
        buy_signal = None
        if regime == "uptrend" and t is None:
            if pd.notna(sma) and pd.notna(slp) and sma > 0 and slp > 0:
                if close <= sma and low <= sma * 1.005 and high >= sma * 0.995:
                    if 40 <= r14 <= 55:
                        if pd.notna(vma) and vma > 0 and vol <= vma:
                            buy_signal = ("回踩均线买入", 10000)

        elif regime == "sideways" and t is None:
            if low < boll_l:
                ok = True
                for j in range(1, 4):
                    if i - j >= 0 and df.iloc[i - j]["low"] < low:
                        ok = False; break
                if ok:
                    sc = 0.35
                    if r14 < 20: sc += 0.25
                    elif r14 < 30: sc += 0.15
                    # Check MACD divergence (simplified)
                    if i >= 25:
                        sub = df.iloc[i-20:i+1]
                        min_idx = sub["close"].iloc[:-1].idxmin()
                        if min_idx in sub.index and min_idx < i:
                            mc_val = sub.loc[min_idx, "macd_hist"]
                            if pd.notna(mc_val):
                                if close < sub.loc[min_idx, "close"] and md > mc_val:
                                    sc += 0.20
                    if pd.notna(vma) and vma > 0 and vol >= 1.5 * vma:
                        sc += 0.10
                    if sc >= 0.35:
                        sh = 20000 if sc >= 0.80 else 15000 if sc >= 0.70 else 10000 if sc >= 0.50 else 5000
                        buy_signal = (f"触下轨买入(sc={sc:.2f})", int(sh))

        elif regime == "downtrend" and gs == 0:
            if low < boll_l:
                ok = True
                for j in range(1, 4):
                    if i - j >= 0 and df.iloc[i - j]["low"] < low:
                        ok = False; break
                if ok:
                    buy_signal = ("触下轨加仓", 10000)

        if buy_signal:
            reason, shares = buy_signal
            cost_val = close * shares
            commission = cost_val * COMMISSION_RATE
            if cost_val + commission <= a:
                # Update total shares and cost
                total_cost_before = s * c
                s += shares
                c = (total_cost_before + cost_val) / s
                a -= cost_val + commission

                if regime == "downtrend":
                    total_gc = gs * gc + cost_val
                    gs += shares
                    gc = total_gc / gs
                    gr = high
                    gt = ts
                else:
                    t = {"price": close, "shares": shares, "regime": regime}
                    rh = high

                trades.append({
                    "time": ts, "type": "BUY", "regime": regime,
                    "reason": reason, "price": close,
                    "shares": shares, "cost": close, "pnl": 0,
                    "total_shares": s, "cash": round(a, 2)
                })

    return trades

def main():
    print("=== 信维通信300136 分钟级回测 ===")
    print(f"日期: 2026-07-28  手续费: 万三")
    print(f"初始持仓: {INITIAL_SHARES}股  成本: {INITIAL_COST}  可用资金: {INITIAL_CASH}")
    print()

    df = pd.read_csv(DATA_PATH, parse_dates=["time"])
    print(f"数据: {len(df)}根1分钟K线 ({df['time'].iloc[0]} ~ {df['time'].iloc[-1]})")

    trades = backtest(df)

    if not trades:
        print("\n无交易信号触发")
        return

    # 统计
    buy_trades = [t for t in trades if t["type"] == "BUY"]
    sell_trades = [t for t in trades if t["type"] == "SELL"]
    buy_count = len(buy_trades)
    sell_count = len(sell_trades)
    total_pnl = sum(t["pnl"] for t in sell_trades)
    win_trades = [t for t in sell_trades if t["pnl"] > 0]
    loss_trades = [t for t in sell_trades if t["pnl"] < 0]
    win_rate = len(win_trades) / len(sell_trades) * 100 if sell_trades else 0
    avg_pnl = total_pnl / len(sell_trades) if sell_trades else 0

    print(f"\n--- 交易统计 ---")
    print(f"买入: {buy_count}次")
    print(f"卖出: {sell_count}次")
    print(f"总盈亏: {total_pnl:+.2f}元")
    print(f"胜率: {win_rate:.1f}% ({len(win_trades)}胜/{len(loss_trades)}负)")
    print(f"平均每笔盈亏: {avg_pnl:+.2f}元")
    print(f"最大盈利: {max(t['pnl'] for t in sell_trades):+.2f}元" if sell_trades else "")
    print(f"最大亏损: {min(t['pnl'] for t in sell_trades):+.2f}元" if sell_trades else "")

    print(f"\n--- 交易明细 ---")
    print(f"{'时间':>16} {'类型':>4} {'策略':>8} {'价格':>8} {'股数':>6} {'盈亏':>10} {'原因'}")
    print("-" * 80)
    for t in trades:
        time_str = t["time"].strftime("%H:%M")
        print(f"{time_str:>16} {t['type']:>4} {t['regime']:>8} {t['price']:>8.2f} {t['shares']:>6} {t['pnl']:>+10.2f} {t['reason']}")

    # 保存到Excel
    trades_df = pd.DataFrame(trades)
    trades_df["time"] = trades_df["time"].dt.strftime("%Y-%m-%d %H:%M")
    for c in trades_df.select_dtypes(include=["float64"]).columns:
        trades_df[c] = trades_df[c].round(4)

    summary_df = pd.DataFrame([
        ["股票", f"{CODE} {NAME}"],
        ["日期", "2026-07-28"],
        ["手续费", "万三 (0.03%)"],
        ["初始持仓", f"{INITIAL_SHARES}股"],
        ["初始成本", f"{INITIAL_COST:.3f}元"],
        ["初始资金", f"{INITIAL_CASH:.0f}元"],
        ["数据量", f"{len(df)}根1分钟K线"],
        ["买入次数", buy_count],
        ["卖出次数", sell_count],
        ["总盈亏", f"{total_pnl:+.2f}元"],
        ["胜率", f"{win_rate:.1f}%"],
        ["平均盈亏", f"{avg_pnl:+.2f}元"],
    ], columns=["指标", "数值"])

    for sheet_name, data in [("回测汇总", summary_df), ("交易明细", trades_df)]:
        pass

    with pd.ExcelWriter(OUT_PATH, engine="openpyxl") as writer:
        summary_df.to_excel(writer, sheet_name="回测汇总", index=False)
        trades_df.to_excel(writer, sheet_name="交易明细", index=False)

    print(f"\n已保存回测结果: {OUT_PATH}")

if __name__ == "__main__":
    main()
