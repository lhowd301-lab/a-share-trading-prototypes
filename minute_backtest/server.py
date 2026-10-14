# server.py - FastAPI + WebSocket
# Engine runs in a dedicated thread (sync), async server polls shared status.
import asyncio
import sys
import threading
import time

# Windows Python 3.12: use SelectorEventLoop (ProactorEventLoop has bugs)
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

from engine import TradingEngine

# ── Engine in background thread ──
eng = TradingEngine()
_status = {}
_lock = threading.Lock()
_clients = set()

def _engine_loop():
    global _status
    cnt = 0
    while True:
        try:
            eng.tick_q()
            cnt += 1
            if cnt >= 20:
                eng.tick_k()
                cnt = 0
            with _lock:
                _status = eng.gs()
        except Exception:
            pass
        time.sleep(3)

t = threading.Thread(target=_engine_loop, daemon=True)
t.start()

# ── FastAPI app ──
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.get("/")
async def root():
    with open("dashboard.html", "r", encoding="utf-8-sig") as f:
        return HTMLResponse(f.read())

@app.get("/api/status")
async def get_status():
    with _lock:
        return dict(_status)

async def pusher():
    while True:
        await asyncio.sleep(3)
        with _lock:
            s = dict(_status)
        dead = set()
        for ws in list(_clients):
            try: await ws.send_json(s)
            except: dead.add(ws)
        for ws in dead:
            _clients.discard(ws)

@app.on_event("startup")
async def startup():
    asyncio.create_task(pusher())

@app.websocket("/ws")
async def ws(ws: WebSocket):
    await ws.accept()
    _clients.add(ws)
    try:
        while True: await ws.receive_text()
    except WebSocketDisconnect:
        _clients.discard(ws)

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8700)
