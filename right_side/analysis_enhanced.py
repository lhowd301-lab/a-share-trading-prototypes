# analysis_enhanced.py - ?????/???????
import os, sys, warnings
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
import akshare as ak
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import CFG, TICKER, HOLDING_SHARES, AVG_COST, AVAILABLE_CASH
from indicators import compute_all
pd.set_option("display.max_columns", None)
pd.set_option("display.width", 120)
warnings.filterwarnings("ignore")
TODAY = datetime.now().strftime("%Y-%m-%d")

def fetch_data(days=7):
    end = datetime.now()
    start = end - timedelta(days=days)
    df = ak.stock_zh_a_hist_min_em(
        symbol="300136",
        start_date=start.strftime("%Y-%m-%d 09:30:00"),
        end_date=end.strftime("%Y-%m-%d 15:00:00"),
        period="1", adjust=""
    )
    col_map = {}
    col_map["\u65f6\u95f4"] = "time"
    col_map["\u5f00\u76d8"] = "open"
    col_map["\u6536\u76d8"] = "close"
    col_map["\u6700\u9ad8"] = "high"
    col_map["\u6700\u4f4e"] = "low"
    col_map["\u6210\u4ea4\u91cf"] = "volume"
    col_map["\u6210\u4ea4\u989d"] = "amount"
    avail = [c for c in col_map if c in df.columns]
    df = df.rename(columns={c: col_map[c] for c in avail})
    df["time"] = pd.to_datetime(df["time"])
    return df.sort_values("time").reset_index(drop=True)

def calc_indicators(df):
    df = compute_all(df)
    close = df["close"].values
    high = df["high"].values
    low = df["low"].values
    n = len(df)

    # ATR
    tr = np.zeros(n)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        tr[i] = max(high[i]-low[i], abs(high[i]-close[i-1]), abs(low[i]-close[i-1]))
    df["atr"] = pd.Series(tr).rolling(14).mean().values
    df["atr_pct"] = df["atr"]/df["close"]*100

    # MACD
    ema12 = pd.Series(close).ewm(span=12).mean().values
    ema26 = pd.Series(close).ewm(span=26).mean().values
    df["macd"] = ema12 - ema26
    df["macd_sig"] = pd.Series(df["macd"]).ewm(span=9).mean().values
    df["macd_hist"] = df["macd"] - df["macd_sig"]
    return df

def detect_buy(df):
    sigs = []
    n = len(df)
    low_vals = df["low"].values
    vol_vals = df["volume"].values

    for i in range(20, n-4):
        row = df.iloc[i]
        score = 0.0
        facts = []

        touch = row["low"] <= row["boll_lower"]
        if touch:
            score += 0.35
            facts.append("BollingerLower")

        rsi_v = row["rsi"]
        if not np.isnan(rsi_v) and rsi_v <= 30:
            score += 0.15
            facts.append("RSIOversold")
            if rsi_v <= 20:
                score += 0.10
                facts.append("RSIExtreme")

        if i > 20:
            prev = df.iloc[max(0,i-20):i+1]
            min_idx = prev["low"].idxmin()
            if min_idx < i:
                if row["low"] < df.loc[min_idx, "low"] and row["macd"] > df.loc[min_idx, "macd"]:
                    score += 0.20
                    facts.append("MACDDivergence")

        vol5 = pd.Series(vol_vals).rolling(5).mean().iloc[i]
        vr = row["volume"]/max(vol5, 1)
        if vr >= 1.2:
            score += 0.10
            facts.append("VolumeSurge")

        support = pd.Series(low_vals).rolling(60).quantile(0.1).iloc[i]
        if not np.isnan(support):
            if abs(row["close"]-support)/support*100 < 1:
                score += 0.10
                facts.append("SupportLevel")

        td = row["trend_direction"]
        if td == 1:
            score += 0.05
        elif td == -1:
            score -= 0.10

        if touch and score >= 0.35:
            future = df.iloc[i+1:i+4]
            if future["low"].min() >= row["low"]:
                sigs.append({
                    "idx": i, "time": row["time"], "price": float(row["close"]),
                    "score": float(score), "lower": float(row["boll_lower"]),
                    "rsi": float(rsi_v) if not np.isnan(rsi_v) else 50, "facts": facts
                })
    return sigs

def detect_sell_for(df, buy):
    idx = buy["idx"]
    price = buy["price"]
    atr = df.iloc[idx]["atr"]
    if np.isnan(atr): atr = 0.5
    upper = df.iloc[idx]["boll_upper"]

    tp = price + 1.0 * atr
    tp_pct = max(0.5, (tp/price-1)*100)

    post = df.iloc[idx+1:]
    highest = price
    high_ret = 0.0

    for j, (_, row) in enumerate(post.iterrows()):
        ret = (row["close"]/price-1)*100
        if row["close"] > highest:
            highest = row["close"]
            high_ret = ret
        if ret >= tp_pct:
            return {"time":row["time"],"price":float(row["close"]),"ret":float(ret),"reason":"ATR_TP","bars":j+1}
        if not np.isnan(upper) and row["close"] >= upper:
            return {"time":row["time"],"price":float(row["close"]),"ret":float(ret),"reason":"UpperBand","bars":j+1}
        if high_ret >= 1.5 and (row["close"]/highest-1)*100 <= -0.5:
            return {"time":row["time"],"price":float(row["close"]),"ret":float(ret),"reason":"Retrace","bars":j+1}
        rsi_v = row["rsi"]
        if not np.isnan(rsi_v) and rsi_v >= 70:
            return {"time":row["time"],"price":float(row["close"]),"ret":float(ret),"reason":"RSIOverbought","bars":j+1}
        if j+1 >= 120:
            return {"time":row["time"],"price":float(row["close"]),"ret":float(ret),"reason":"TimeStop","bars":j+1}
        if ret <= -1.5:
            return {"time":row["time"],"price":float(row["close"]),"ret":float(ret),"reason":"StopLoss","bars":j+1}

    if len(post) > 0:
        last = post.iloc[-1]
        ret = (last["close"]/price-1)*100
        return {"time":last["time"],"price":float(last["close"]),"ret":float(ret),"reason":"ForceClose","bars":len(post)}
    return None

def main():
    print("\n======= ????(300136.SZ) ?????? =======")
    print(f"Date: {TODAY}")
    print(f"Holdings: {HOLDING_SHARES}sh @ {AVG_COST:.3f}")
    print(f"Cash: {AVAILABLE_CASH:,}")

    df = fetch_data(7)
    print(f"Data: {len(df)} bars ({df.time.iloc[0].strftime('%m-%d')} to {df.time.iloc[-1].strftime('%m-%d')})")

    df = calc_indicators(df)
    print("Indicators computed.")

    buys = detect_buy(df)
    print(f"\nBuy signals: {len(buys)}")

    trades = []
    for b in buys:
        s = detect_sell_for(df, b)
        if s:
            bcopy = dict(b)
            bcopy.update(s)
            trades.append(bcopy)

    print(f"\n{'='*60}")
    print(f"RESULTS")
    print(f"{'='*60}")
    print(f"Buy signals:  {len(buys)}")
    print(f"Trades closed: {len(trades)}")

    if trades:
        rets = [t["ret"] for t in trades]
        wins = [r for r in rets if r > 0]
        losses = [r for r in rets if r <= 0]
        wr = len(wins)/len(rets)*100
        print(f"Win rate:     {wr:.0f}% ({len(wins)}W/{len(losses)}L)")
        print(f"Avg return:   {np.mean(rets):+.2f}%")
        if wins: print(f"Avg win:      {np.mean(wins):+.2f}%")
        if losses: print(f"Avg loss:     {np.mean(losses):+.2f}%")
        print(f"Max/Min:      {max(rets):+.2f}% / {min(rets):+.2f}%")

        print(f"\n--- Recent trades ---")
        for t in trades[-6:]:
            bt = str(t["time"])[11:16]
            st = str(t["sell_time"])[11:16] if "sell_time" in t else "?"
            print(f"  B{bt} @{t['price']:.2f} -> S{st} @{t['price']:.2f} | {t['ret']:+.2f}% | {t['reason']}")

        # Cost simulation
        print(f"\n{'='*60}")
        print(f"COST REDUCTION SIMULATION")
        print(f"{'='*60}")

        class Sim:
            def __init__(self):
                self.h = HOLDING_SHARES
                self.c = AVG_COST
                self.r = float(AVAILABLE_CASH)
                self.r0 = float(AVAILABLE_CASH)
            def trade(self, bp, sp, score):
                if score < 0.3: return 0
                ratio = min(0.35, 0.08 + score*0.35)
                shares = int(self.r * ratio / bp / 100) * 100
                if shares < 100: return 0
                br = self.r/self.r0
                shares = int(shares * (0.3+0.7*br) / 100) * 100
                if shares < 100: return 0
                buy_amt = shares*bp
                sell_amt = shares*sp
                self.r += sell_amt - buy_amt
                self.c = (self.h*self.c + buy_amt)/(self.h+shares)
                self.h += shares
                return 1

        sim = Sim()
        n_trades = 0
        for t in trades:
            n_trades += sim.trade(t["price"], t["price"], t["score"])

        print(f"Trades:      {n_trades}")
        print(f"Cost before: {AVG_COST:.3f}")
        print(f"Cost after:  {sim.c:.3f}")
        print(f"Reduction:   {AVG_COST-sim.c:.3f}")

    # Market status
    last = df.iloc[-1]
    pos = (last["close"]-last["boll_lower"])/(last["boll_upper"]-last["boll_lower"])*100
    print(f"\n{'='*60}")
    print(f"CURRENT MARKET STATUS")
    print(f"{'='*60}")
    print(f"Price:       {last['close']:.2f}")
    print(f"Bollinger:   L={last['boll_lower']:.1f} M={last['boll_mid']:.1f} U={last['boll_upper']:.1f}")
    print(f"Position:    {pos:.0f}% (0% = lower band)")
    print(f"RSI(14):     {last['rsi']:.0f}")
    print(f"ATR(14):     {last['atr']:.2f} ({last['atr_pct']:.1f}%)")
    td = {1:"Bull",-1:"Bear",0:"Neutral"}
    print(f"Trend:       {td.get(last['trend_direction'],'?')}")

    print(f"\nKey decision logic:")
    print(f"  BUY:  Bollinger lower band touch + RSI<=30 + MACD divergence + volume >=1.2x MA5")
    print(f"  SELL: ATR-based TP (bear 1.0x/bull 1.5x), upper band, RSI>=70, or time stop")
    print(f"\nDone.")

if __name__ == "__main__":
    main()
