# main.py — FastAPI 后端入口
# 信维通信 右侧交易实时监控平台

import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional
import os

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from config import TICKER_NAME, REFRESH_INTERVAL, MARKET_CLOSE, TRADING_SESSION_AFTERNOON_END, BAR_INTERVAL, LOG_DIR
from data_fetcher import get_realtime_quote, get_historical_minute, get_latest_minute_quote, is_market_open
from indicators import (
    calc_all_indicators, get_latest_indicators, get_classifier_score,
)
from signals import check_all_signals
from portfolio import (
    get_portfolio_state, update_portfolio_price, execute_trade,
    save_daily_snapshot, reset_daily_state, set_portfolio_state,
)
from daily_logger import save_signal_log, load_daily_records, load_signal_log
from state_store import save_signal_fired, load_signal_fired, save_portfolio_state, load_portfolio_state

# ========== 日志 ==========
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "app.log"), encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

app = FastAPI(title="信维通信 右侧交易监控平台")

# ========== 全局状态 ==========
market_data = {
    "bars": [],          # K线数据（给前端绘图）
    "latest_quote": {},  # 最新行情
    "indicators": {},    # 最新指标
    "classifier": {},    # 行情分类
    "signals": [],       # 信号列表
    "portfolio": {},     # 持仓
    "daily_records": [], # 每日记录
    "signal_log": [],    # 信号日志
    "chart_data": {},    # 绘图数据
    "market_open": False,
    "last_update": "",
}

_persistent_df = None  # 持久化的DataFrame
_signal_fired = load_signal_fired()  # 已触发的信号去重


# ========== 数据引擎核心 ==========
async def update_market_data():
    """拉取最新数据、计算指标、生成信号"""
    global _persistent_df, _signal_fired
    
    # 1. 获取实时行情
    quote = get_realtime_quote()
    if not quote:
        logger.warning("实时行情获取失败")
        market_data["market_open"] = is_market_open()
        market_data["last_update"] = datetime.now().strftime("%H:%M:%S") + " (行情暂未更新)"
        return
    market_data["latest_quote"] = quote
    price = quote["price"]
    
    # 2. 获取历史K线
    df = get_historical_minute(days=10)
    old_df = _persistent_df
    if df is not None and len(df) > 0:
        _persistent_df = df
        # 转为前端格式
        market_data["bars"] = json.loads(df.tail(240).to_json(orient="records", date_format="iso"))
    elif _persistent_df is not None:
        df = _persistent_df
    else:
        # 数据源挂的时候，保留旧数据，只更新时间
        market_data["market_open"] = is_market_open()
        market_data["last_update"] = datetime.now().strftime("%H:%M:%S") + " (数据暂未更新)"
        logger.warning("历史数据获取失败，保留旧数据")
        return
    
    # 3. 计算技术指标
    df_with_ind = calc_all_indicators(df)
    indicators = get_latest_indicators(df_with_ind)
    market_data["indicators"] = indicators
    
    # 4. 行情分类
    classifier = get_classifier_score(indicators)
    market_data["classifier"] = classifier
    
    # 5. 更新持仓估值
    portfolio = update_portfolio_price(price)
    market_data["portfolio"] = portfolio
    
    # 6. 生成交易信号
    new_signals = check_all_signals(indicators, df_with_ind, portfolio, classifier)
    for sig in new_signals:
        # 去重：同类型+同策略+价格在0.5%范围内不重复触发
        sig_key = f"{sig['type']}_{sig['strategy']}_{round(sig['price']/0.5)*0.5}"
        if sig_key not in _signal_fired:
            _signal_fired.add(sig_key)
            # 自动执行交易
            trade_result = execute_trade(sig)
            if trade_result["success"]:
                sig["executed"] = True
                sig["shares"] = trade_result.get("trade", {}).get("shares", 0)
                save_signal_fired(_signal_fired)
                save_portfolio_state(get_portfolio_state())
                save_signal_log(sig)
                logger.info(f"信号执行: {sig}")
            else:
                sig["executed"] = False
                sig["message"] = trade_result["message"]
                logger.warning(f"信号执行失败: {sig}")
            market_data["signals"].insert(0, sig)
    
    # 保留最近20条信号
    market_data["signals"] = market_data["signals"][:20]
    
    # 7. 准备绘图数据
    market_data["chart_data"] = prepare_chart_data(df_with_ind)
    
    # 8. 历史记录
    dr = load_daily_records()
    if not dr.empty:
        market_data["daily_records"] = json.loads(dr.tail(30).to_json(orient="records"))
    sl = load_signal_log()
    if not sl.empty:
        market_data["signal_log"] = json.loads(sl.tail(50).to_json(orient="records"))
    
    market_data["market_open"] = is_market_open()
    market_data["last_update"] = datetime.now().strftime("%H:%M:%S")


def prepare_chart_data(df) -> Dict[str, Any]:
    """准备前端ECharts绘图数据"""
    if df is None or df.empty:
        return {}
    
    tail = df.tail(120)  # 最近120根K线
    times = tail["time"].dt.strftime("%H:%M").tolist()
    
    chart = {
        "time": times,
        "kline": {
            "open": tail["open"].tolist(),
            "close": tail["close"].tolist(),
            "high": tail["high"].tolist(),
            "low": tail["low"].tolist(),
        },
        "volume": {"time": times, "value": tail["volume"].tolist()},
        "indicators": {},
    }
    
    # 均线
    for p in [5, 10, 20, 30, 60]:
        col = f"MA{p}"
        if col in tail.columns:
            vals = tail[col].tolist()
            chart["indicators"][col] = {"time": times, "value": [round(v, 2) if v else None for v in vals]}
    
    # 布林带
    for key in ["BOLL_UPPER", "BOLL_MID", "BOLL_LOWER"]:
        if key in tail.columns:
            vals = tail[key].tolist()
            chart["indicators"][key] = {"time": times, "value": [round(v, 2) if v else None for v in vals]}
    
    # RSI
    if "RSI" in tail.columns:
        chart["indicators"]["RSI"] = {"time": times, "value": [round(v, 1) if not pd.isna(v) else None for v in tail["RSI"].tolist()]}
    
    # MACD
    for key in ["MACD_DIF", "MACD_DEA", "MACD_HIST"]:
        if key in tail.columns:
            chart["indicators"][key] = {"time": times, "value": [round(v, 3) if not pd.isna(v) else None for v in tail[key].tolist()]}
    
    # KDJ
    for key in ["K", "D", "J"]:
        if key in tail.columns:
            chart["indicators"][key] = {"time": times, "value": [round(v, 1) if not pd.isna(v) else None for v in tail[key].tolist()]}
    
    return chart


# ========== 导入需要 pd 的引用 ==========
import pandas as pd


# ========== WebSocket ==========
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    logger.info("WebSocket 客户端已连接")
    try:
        while True:
            # 接收客户端消息
            data = await websocket.receive_text()
            msg = json.loads(data)
            
            if msg.get("action") == "refresh":
                await update_market_data()
                await websocket.send_text(json.dumps({
                    "type": "market_update",
                    "data": market_data
                }, ensure_ascii=False))
            
            elif msg.get("action") == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
                
    except WebSocketDisconnect:
        logger.info("WebSocket 客户端已断开")
    except Exception as e:
        logger.error(f"WebSocket 错误: {e}")


# ========== HTTP 路由 ==========
@app.get("/")
async def get_dashboard():
    """返回监控面板页面"""
    html_path = "templates/dashboard.html"
    with open(html_path, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@app.get("/api/status")
async def get_status():
    """获取最新状态（HTTP轮询备用）"""
    return market_data


@app.get("/api/data")
async def get_all_data():
    """获取全量数据"""
    await update_market_data()
    return market_data


@app.post("/api/reset")
async def reset_state():
    """重置日内状态（次日开盘调用）"""
    reset_daily_state()
    global _signal_fired
    _signal_fired = load_signal_fired()
    return {"status": "ok", "message": "日内状态已重置"}


# ========== 后台任务 ==========
async def periodic_update():
    """定时推送数据"""
    while True:
        try:
            now = datetime.now()
            # 非交易时段每5分钟检查一次
            interval = REFRESH_INTERVAL if is_market_open() else 300
            
            # 收盘自动保存
            if now.hour == 15 and now.minute == 1 and now.second < 10:
                portfolio = get_portfolio_state()
                save_daily_snapshot(portfolio["last_price"] if portfolio["last_price"] > 0 else 0)
                global _signal_fired
                _signal_fired = load_signal_fired()
                logger.info("收盘自动保存完成")
            
            await update_market_data()
        except Exception as e:
            logger.error(f"定期更新失败: {e}")
        await asyncio.sleep(interval)


@app.on_event("startup")
async def startup_event():
    """启动时初始化数据"""
    global _signal_fired
    saved_state = load_portfolio_state()
    if saved_state:
        try:
            from portfolio import set_portfolio_state
            set_portfolio_state(saved_state)
            logger.info("从持久化文件恢复持仓状态")
        except Exception as e:
            logger.warning(f"恢复持仓状态失败: {e}")
    _signal_fired = load_signal_fired()
    logger.info(f"已加载 {len(_signal_fired)} 个已触发信号")
    logger.info(f"=== 信维通信 右侧交易监控平台 启动 ===")
    logger.info(f"初始持仓: {get_portfolio_state()['current_shares']}股 "
                f"成本: {get_portfolio_state()['cost_basis']:.3f} "
                f"现金: {get_portfolio_state()['available_cash']:.0f}")
    asyncio.create_task(periodic_update())


# ========== 启动入口 ==========
async def _background_init():
    """后台初始化：首次加载数据，设10秒超时"""
    try:
        await asyncio.wait_for(update_market_data(), timeout=10)
    except asyncio.TimeoutError:
        logger.warning("首次数据加载超时，后台将继续更新")


if __name__ == "__main__":
    import asyncio
    import os
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    # 不阻塞启动，在后台异步加载
    asyncio.run(_background_init())
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
    

