"""ET 历史策略的信号提取版；不连接券商、不提交订单。"""
import requests

import numpy as np

STOCK_CODE = '600968'

SECID = '1.600968'

BB_PERIOD = 20

BB_STD = 2

SESSION = requests.Session()

def get_minute_klines_eastmoney(secid, count=100):
    """东方财富接口"""
    url = 'https://push2his.eastmoney.com/api/qt/stock/kline/get'
    params = {
        'fields1': 'f1,f2,f3,f4,f5,f6',
        'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61',
        'ut': '7eea3edcaed734beae4a6b2b322b7456',
        'klt': '1', 'fqt': '1',
        'secid': secid, 'beg': '0', 'end': '20500101', 'lmt': count,
    }
    r = SESSION.get(url, params=params, timeout=10)
    klines = r.json()['data']['klines']
    closes, times = [], []
    for line in klines:
        parts = line.split(',')
        times.append(parts[0])
        closes.append(float(parts[2]))
    return np.array(closes), times

def get_minute_klines_tencent(code, count=100):
    """腾讯接口"""
    code_str = f'sh{code}' if code.startswith('6') else f'sz{code}'
    url = 'http://ifzq.gtimg.cn/appstock/app/kline/mkline'
    params = {'param': f'{code_str},m1,,{count}'}
    r = SESSION.get(url, params=params, timeout=10)
    data = r.json()
    klines = data['data'][code_str]['m1']
    closes, times = [], []
    for line in klines:
        ts = line[0]  # 202607241130
        times.append(f'{ts[:4]}-{ts[4:6]}-{ts[6:8]} {ts[8:10]}:{ts[10:12]}')
        closes.append(float(line[3]))  # 收盘价
    return np.array(closes), times

def get_minute_klines(secid, count=100):
    """获取分钟K线，自动切换可用接口"""
    for fetcher in [get_minute_klines_eastmoney, get_minute_klines_tencent]:
        try:
            return fetcher(STOCK_CODE if fetcher == get_minute_klines_tencent else secid, count)
        except Exception:
            continue
    raise RuntimeError('所有行情接口均不可用')

def calc_bollinger(closes):
    """返回 中轨、上轨、下轨"""
    ma = np.mean(closes[-BB_PERIOD:])
    std = np.std(closes[-BB_PERIOD:])
    return ma, ma + BB_STD * std, ma - BB_STD * std
