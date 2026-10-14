"""live_scan.py — 实时扫描今日分钟数据，输出交易建议"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from datetime import datetime
import akshare as ak
import pandas as pd
import numpy as np

from config import CFG, TICKER, HOLDING_SHARES, AVG_COST, AVAILABLE_CASH
from indicators import compute_all
from strategy import evaluate, scan_recent_signals
from position_sizing import AllocationModel

print("=" * 60)
print(f"信维通信 · 实时扫描  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
print("=" * 60)

# 1. 拉历史数据预热
print("\n[1/4] 加载历史分钟线预热指标…")
try:
    hist = ak.stock_zh_a_hist_premin_em(
        symbol=TICKER, period="1min",
        start_date="20260715", end_date="20260721",
    )
    if hist is not None and not hist.empty:
        hist.columns = [c.strip() for c in hist.columns]
        hm = {"时间":"time","开盘":"open","收盘":"close","最高":"high",
              "最低":"low","成交量":"volume","成交额":"amount"}
        hist.rename(columns=hm, inplace=True)
        hist["time"] = pd.to_datetime(hist["time"])
        hist.sort_values("time", inplace=True)
        print(f"  历史数据: {len(hist)} 条")
    else:
        hist = None
        print("  无历史数据")
except Exception as e:
    print(f"  历史获取失败: {e}")
    hist = None

# 2. 拉今天分钟线
print("\n[2/4] 拉取今日分钟线…")
try:
    today = ak.stock_zh_a_hist_min_em(symbol=TICKER, period="1min", adjust="")
    if today is None or today.empty:
        print("  ❌ 今日无数据（可能休市或非交易时段）")
        sys.exit(1)
    today.columns = [c.strip() for c in today.columns]
    tm = {"时间":"time","开盘":"open","收盘":"close","最高":"high",
           "最低":"low","成交量":"volume","成交额":"amount"}
    today.rename(columns=tm, inplace=True)
    today["time"] = pd.to_datetime(today["time"])
    today.sort_values("time", inplace=True)
    print(f"  今日数据: {len(today)} 条")
    print(f"  时间范围: {today['time'].iloc[0]} ~ {today['time'].iloc[-1]}")
    print(f"  价格范围: {today['close'].min():.2f} ~ {today['close'].max():.2f}")
    print(f"  最新价:   {today['close'].iloc[-1]:.2f}")
except Exception as e:
    print(f"  ❌ 获取失败: {e}")
    sys.exit(1)

# 3. 合并 + 计算指标
print("\n[3/4] 计算技术指标…")
if hist is not None:
    df = pd.concat([hist, today], ignore_index=True).drop_duplicates(subset="time").reset_index(drop=True)
else:
    df = today.copy()
df = compute_all(df)
print(f"  总数据: {len(df)} 条")

# 打印布林带当前状态
last = df.iloc[-1]
print(f"\n  当前 K 线状态:")
print(f"    时间: {last['time']}")
print(f"    收盘: {last['close']:.2f}")
print(f"    最低: {last['low']:.2f}")
print(f"    布林中轨: {last['boll_mid']:.2f}")
print(f"    布林上轨: {last['boll_upper']:.2f}")
print(f"    布林下轨: {last['boll_lower']:.2f}")
print(f"    RSI:  {last['rsi']:.1f}")
print(f"    成交量比: {last['volume_ratio']:.2f}")
print(f"    趋势方向: {last['trend_direction']:.0f}  (1=多, -1=空, 0=横)")

# 判断当前价在布林带中的位置
pos = (last['close'] - last['boll_lower']) / (last['boll_upper'] - last['boll_lower']) * 100
print(f"    布林带位置: {pos:.1f}% （0%=下轨, 100%=上轨）")

# 4. 扫描信号
print("\n[4/4] 扫描右侧信号…")
# scan_recent_signals 扫描历史
sigs = scan_recent_signals(df, lookback=120)
today_sigs = [s for s in sigs if s.timestamp[:10] == datetime.now().strftime("%Y-%m-%d")]
print(f"  今日扫描到 {len(today_sigs)} 个右侧信号")

if today_sigs:
    print(f"\n  {'='*50}")
    print(f"  信号列表（由近到远）：")
    for i, s in enumerate(reversed(today_sigs)):
        print(f"    #{len(today_sigs)-i}  {s.timestamp[11:16]}  @ {s.price:.2f}  "
              f"强度 {s.strength:.2f}  下轨 {s.lower_band:.2f}")
        if s.filters_passed:
            print(f"       通过: {', '.join(s.filters_passed)}")
        if s.filters_failed:
            print(f"       未过: {', '.join(s.filters_failed)}")
else:
    print(f"  今日无信号")

# 5. 用最新信号跑分配模型
print(f"\n{'='*60}")
print(f"仓位分配建议")
print(f"{'='*60}")

if today_sigs:
    latest = today_sigs[-1]  # 时间上最晚（最新）的信号
    current_price = today['close'].iloc[-1]
    current_amt = current_price * HOLDING_SHARES

    print(f"\n  持仓: {HOLDING_SHARES} 股 @ {AVG_COST} = {current_amt:,.0f} 元")
    print(f"  可用: {AVAILABLE_CASH:,} 元")
    print(f"  浮亏: {(current_price/AVG_COST - 1)*100:.2f}%")
    print(f"\n  最新信号: {latest.timestamp[11:16]}  信号强度 {latest.strength:.2f}")

    model = AllocationModel()
    result = model.allocate(
        price=current_price,
        signal_strength=latest.strength,
        verbose=False
    )

    if result.shares >= 100:
        new_cost = (HOLDING_SHARES * AVG_COST + result.shares * current_price) / (HOLDING_SHARES + result.shares)
        print(f"\n  ╔══ 买入建议 ═══════════════════════════════╗")
        print(f"  ║  买入: {result.shares} 股（{result.lots} 手）")
        print(f"  ║  价格: {current_price:.2f}")
        print(f"  ║  金额: {result.cost:,.0f} 元")
        print(f"  ║  原均价 → 新均价: {AVG_COST:.3f} → {new_cost:.3f}")
        print(f"  ║  降幅: {AVG_COST - new_cost:.3f} 元/股")
        print(f"  ║  策略: {result.reason}")
        print(f"  ╚═══════════════════════════════════════════╝")

        # 如果连续买入的模拟
        print(f"\n  ── 模拟连续执行相同信号 5 次 ──")
        model5 = AllocationModel()
        for j in range(5):
            r = model5.allocate(price=current_price, signal_strength=latest.strength, verbose=False)
            if r.shares < 100:
                print(f"    第{j+1}次: 不满足条件 → 停止")
                break
            model5.commit(r, current_price)
            total = model5.H - HOLDING_SHARES
            total_cash = AVAILABLE_CASH - model5.R
            print(f"    第{j+1}次: 买{r.shares}股  均价{r.new_avg_cost:.2f}  "
                  f"累计{total}股  花{total_cash:,.0f}元")
    else:
        print(f"\n  模型拦截: 不分配")
        print(f"  理由: {result.reason}")

# 输出原始布林相关数据供参考
print(f"\n\n{'='*60}")
print(f"附录：今日 K 线明细（最近 10 根）")
print(f"{'='*60}")
recent = today.tail(10)[["time","close","low","boll_lower","boll_mid","boll_upper","rsi"]]
recent["time"] = recent["time"].dt.strftime("%H:%M")
recent.columns = ["时间","收盘","最低","下轨","中轨","上轨","RSI"]
print(recent.to_string(index=False))
