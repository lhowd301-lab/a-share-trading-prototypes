
from pathlib import Path as _PublicPath
_PUBLIC_ROOT = _PublicPath(__file__).resolve().parents[1]
import urllib.request, json, sys
sys.stdout.reconfigure(encoding="utf-8")

def fetch(url):
    proxy = urllib.request.ProxyHandler({})
    opener = urllib.request.build_opener(proxy)
    urllib.request.install_opener(opener)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    resp = urllib.request.urlopen(req, timeout=15)
    return json.loads(resp.read().decode("utf-8"))

print("=== A股高频交易候选股票筛选 ===\n")

# Get top traded stocks
url = "https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=200&po=1&np=1&fltt=2&invt=2"
url += "&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048"
url += "&fields=f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f14,f15,f20,f21,f23,f37,f62,f115,f128,f140,f141,f136"
r = fetch(url)
data = r.get("data", {}).get("diff", [])

print(f"扫描: {len(data)}只A股\n")

# Filter candidates
candidates = []
for s in data:
    price = s.get("f2", 0) or 0
    amp = s.get("f23", 0) or 0
    turnover = (s.get("f6", 0) or 0) / 1e8
    tr = s.get("f8", 0) or 0
    vol_ratio = s.get("f10", 0) or 0
    chg = s.get("f3", 0) or 0
    chg20 = s.get("f136", 0) or 0
    chg60 = s.get("f140", 0) or 0

    if amp >= 3.0 and turnover >= 3 and tr >= 2 and 10 <= price <= 100:
        candidates.append({
            "code": s.get("f12", ""),
            "name": s.get("f14", ""),
            "price": price, "amp": amp, "turnover": turnover,
            "tr": tr, "vol_ratio": vol_ratio, "chg": chg,
            "chg20": chg20, "chg60": chg60,
        })

if not candidates:
    print("无候选股票")
else:
    candidates.sort(key=lambda x: x["turnover"], reverse=True)
    print(f"候选: {len(candidates)}只 (振幅>3%, 成交额>3亿, 换手率>2%, 价格10-100元)\n")

    hdr = f"{'代码':>6} {'名称':>6} {'最新':>6} {'振幅%':>6} {'成交额亿':>7} {'换手率%':>6}"
    print(hdr); print("-" * 45)
    for c in candidates[:20]:
        print(f"{c['code']:>6} {c['name']:>6} {c['price']:>6.2f} {c['amp']:>5.2f}% {c['turnover']:>6.2f} {c['tr']:>5.2f}%")

# 信维通信
print("\n\n=== 信维通信(300136) 当前指标 ===")
for s in data:
    if s.get("f12") == "300136":
        print(f"价格:{s.get('f2',0):.2f} 振幅:{s.get('f23',0):.2f}% 成交额:{(s.get('f6',0) or 0)/1e8:.2f}亿 换手率:{s.get('f8',0):.2f}%")
        break

# Score candidates for HFT
print("\n\n=== HFT综合评分 Top 10 ===")
scored = []
for c in candidates:
    score = c["amp"] * 0.3 + min(c["turnover"], 30) * 0.25 + min(c["tr"], 20) * 0.2 + min(c["vol_ratio"], 3) * 0.15
    scored.append((score, c))
scored.sort(reverse=True)

for score, c in scored[:10]:
    print(f"{c['code']:>6} {c['name']:>6} 评分{score:>5.1f} 振幅{c['amp']:>5.2f}% 成交额{c['turnover']:>6.1f}亿 换手率{c['tr']:>5.2f}%")

# Save to file
outpath = str(_PUBLIC_ROOT / 'data/高频选股分析.txt')
with open(outpath, "w", encoding="utf-8") as f:
    f.write("A股高频交易候选股票分析\n"); f.write("=" * 50 + "\n\n")
    f.write(f"筛选条件: 振幅>3% 成交额>3亿 换手率>2% 价格10-100元\n")
    f.write(f"候选数量: {len(candidates)}只\n\n")
    f.write("综合评分前10:\n")
    for score, c in scored[:10]:
        f.write(f"{c['code']} {c['name']} 评分{score:.1f} 振幅{c['amp']:.2f}% 成交额{c['turnover']:.1f}亿 换手率{c['tr']:.2f}%\n")
    f.write("\n\n信维通信对比:\n")
    for s in data:
        if s.get("f12") == "300136":
            f.write(f"价格:{s.get('f2',0):.2f} 振幅:{s.get('f23',0):.2f}% 成交额:{(s.get('f6',0) or 0)/1e8:.2f}亿 换手率:{s.get('f8',0):.2f}%\n")
            break

print(f"\n\n已保存: {outpath}")
