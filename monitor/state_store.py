# state_store.py — 持久化存储交易状态

import json
import os
from typing import Set
from config import MARKET_CACHE_DIR

SIGNAL_STATE_PATH = os.path.join(MARKET_CACHE_DIR, "signal_fired.json")
PORTFOLIO_STATE_PATH = os.path.join(MARKET_CACHE_DIR, "portfolio_state.json")


def save_signal_fired(signals: Set[str]):
    os.makedirs(os.path.dirname(SIGNAL_STATE_PATH), exist_ok=True)
    with open(SIGNAL_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(list(signals), f, ensure_ascii=False)


def load_signal_fired() -> Set[str]:
    if not os.path.exists(SIGNAL_STATE_PATH):
        return set()
    try:
        with open(SIGNAL_STATE_PATH, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except:
        return set()


def save_portfolio_state(state: dict):
    os.makedirs(os.path.dirname(PORTFOLIO_STATE_PATH), exist_ok=True)
    import copy
    snap = copy.deepcopy(state)
    for key in ["daily_trades", "grid_positions", "last_updated"]:
        snap.pop(key, None)
    with open(PORTFOLIO_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, default=str)


def load_portfolio_state() -> dict:
    if not os.path.exists(PORTFOLIO_STATE_PATH):
        return {}
    try:
        with open(PORTFOLIO_STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}
