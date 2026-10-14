# engine.py - ???? 300136 ?????? (v2 direct HTTP)
import os,json,time,datetime as dt
from pathlib import Path
import numpy as np
import pandas as pd
import requests

CODE="300136";NAME="????"
INITIAL_SHARES = 1000  # public demo
BB_PERIOD=20;BB_STD=2.0;RSI_PERIOD=14;MACD_FAST=12;MACD_SLOW=26;MACD_SIGNAL=9;ATR_PERIOD=14
VOLUME_MA_PERIOD=20;VOLUME_THRESHOLD=1.5;MIN_SCORE=0.35;BUY_CONFIRM_BARS=3
HARD_STOP_LOSS=0.985;MAX_HOLD_MINUTES=120;SURGE_THRESHOLD=0.015;PULLBACK_THRESHOLD=0.005
LOGS_DIR=Path(__file__).parent/"logs";STATE_FILE=Path(__file__).parent/"state.json"
_HDS={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

def _ema(s,p): return s.ewm(span=p,adjust=False).mean()
def _sma(s,p): return s.rolling(window=p).mean()
def _std(s,p): return s.rolling(window=p).std(ddof=0)
def is_market(): n=dt.datetime.now(); return False if n.weekday()>=5 else (570<=n.hour*60+n.minute<=690)or(780<=n.hour*60+n.minute<=900)

def boll(df): m=_sma(df["close"],BB_PERIOD);s=_std(df["close"],BB_PERIOD);return m+BB_STD*s,m,m-BB_STD*s
def rsi(series,p=RSI_PERIOD):
 d=series.diff();g=d.where(d>0,0);l=(-d).where(d<0,0)
 ag=g.ewm(span=p,adjust=False).mean();al=l.ewm(span=p,adjust=False).mean()
 return 100-100/(1+ag/al.replace(0,float("nan")))
def macd(s): ef=_ema(s,MACD_FAST);es=_ema(s,MACD_SLOW);d=ef-es;return d,_ema(d,MACD_SIGNAL),2*(d-_ema(d,MACD_SIGNAL))
def atr(df,p=ATR_PERIOD):
 hl=df["high"]-df["low"];hc=(df["high"]-df["close"].shift()).abs();lc=(df["low"]-df["close"].shift()).abs()
 return pd.concat([hl,hc,lc],axis=1).max(axis=1).rolling(window=p).mean()
def macd_div(df,lb=20):
 if len(df)<lb+5: return False
 _,_,h=macd(df["close"]);r=df.iloc[-lb:];rh=h.iloc[-lb:]
 if len(r)<3: return False
 i=r["close"].iloc[:-1].idxmin()
 return bool(r["close"].iloc[-1]<r.loc[i,"close"] and rh.iloc[-1]>rh.loc[i])

def _fk_h(code=CODE,lmt=240):
 try:
  r=requests.get("https://push2his.eastmoney.com/api/qt/stock/kline/get",
   params={"secid":"0."+code,"fields1":"f1,f2,f3,f4,f5,f6","fields2":"f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61","klt":"1","fqt":"1","end":"20500101","lmt":str(lmt)},
   timeout=15,headers=_HDS)
  d=r.json().get("data",{}).get("klines",[])
  if not d: return None
  out=[]
  for k in d:
   p=k.split(",")
   if len(p)>=7: out.append({"time":p[0],"open":float(p[1]),"close":float(p[2]),"high":float(p[3]),"low":float(p[4]),"volume":float(p[5]),"amount":float(p[6])})
  return out
 except: return None

def _fs_h(code=CODE):
 try:
  r=requests.get("https://push2.eastmoney.com/api/qt/stock/get",
   params={"secid":"0."+code,"fields":"f43,f44,f45,f46,f47,f48,f50,f55,f57,f58,f60,f170,f117"},
   timeout=10,headers=_HDS)
  d=r.json().get("data",{})
  if not d or "f43" not in d: return None
  return {"price":d["f43"]/100,"high":d.get("f44",0)/100,"low":d.get("f45",0)/100,"open":d.get("f46",0)/100,"volume":d.get("f47",0),"amount":d.get("f48",0),"change":d.get("f55",0)}
 except: return None

class TradingEngine:
 def __init__(self):
  self.code=CODE;self.s=INITIAL_SHARES;self.c=INITIAL_COST;self.a=INITIAL_CASH
  self.gs_=0;self.gc=0;self.gr=0;self.gt=None;self.k=pd.DataFrame();self.lt=None
  self.p=None;self.cp=None;self.lb=None;self.ls=None
  self.t=None;self.rh=0.0;self.ts=None
  self.reg="sideways";self.rs=0;self.rt=None
  self.tt=[];self.td=dt.date.today().isoformat();self._cache={};self._bs=None;self._bs=None
  self._load();self._initk()

 def _initk(self):
  rows=_fk_h(lmt=240)
  if rows and len(rows)>0:
   df=pd.DataFrame(rows);df["time"]=pd.to_datetime(df["time"])
   self.k=df.tail(240).reset_index(drop=True)
   self.lt=self.k["time"].iloc[-1].isoformat()

 def _fs(self): return _fs_h()
 def _fk(self,lmt=240):
  rows=_fk_h(lmt=lmt)
  if not rows: return None
  df=pd.DataFrame(rows);df["time"]=pd.to_datetime(df["time"]);return df

 def _ci(self):
  if len(self.k)<BB_PERIOD+5: return {}
  d=self.k;u,m,l=boll(d);rs=rsi(d["close"]);df,_,_=macd(d["close"]);a_=atr(d);lt=d.iloc[-1]
  sma20=_sma(d["close"],20).iloc[-1] if len(d)>=20 else 0
  slp=(sma20-_sma(d["close"],20).shift(10).iloc[-1]) if len(d)>=30 else 0
  pos=((lt["close"]-l.iloc[-1])/(u.iloc[-1]-l.iloc[-1])*100) if (u.iloc[-1]-l.iloc[-1])>0 else 50
  self._cache={"bu":round(float(u.iloc[-1]),2),"bm":round(float(m.iloc[-1]),2),"bl":round(float(l.iloc[-1]),2),"rsi":round(float(rs.iloc[-1]),2),"macd":round(float(df.iloc[-1]),4),"atr":round(float(a_.iloc[-1]),2),"vr":round(float(lt["volume"]/max(d["volume"].tail(20).mean(),1)),2),"sma20":round(float(sma20),2),"slp":round(float(slp),4),"pos":round(float(pos),1)}
  return self._cache

 def _classify(self):
  if not self._cache: return "sideways"
  c=self._cache; s=0
  if "slp" in c:
   slp=c["slp"]
   if slp>0.05: s+=25
   elif slp>0: s+=10
   elif slp>-0.05: s-=10
   else: s-=25
  if "pos" in c:
   pos=c["pos"]
   if pos>70: s+=25
   elif pos>55: s+=15
   elif pos>45: s+=0
   elif pos>30: s-=15
   else: s-=25
  if "rsi" in c: s+=round((c["rsi"]-50)*0.3)
  if "macd" in c:
   md=c["macd"]*50
   if md>15: md=15
   elif md<-15: md=-15
   s+=round(md)
  self.rs=s; old=self.reg
  self.reg="uptrend" if s>20 else "downtrend" if s<-20 else "sideways"
  if self.reg!=old:
   self.t=None;self.gs_=0;self.gc=0;self.gr=0;self.gt=None;self.rh=0;self.ts=None
   now=dt.datetime.now()
   self.tt.append({"t":now.isoformat(),"d":"策略","s":0,"p":self.p or 0,"sc":self.rs,"r":old+"->"+self.reg,"pnl":0,"h":self.s})
   fp=LOGS_DIR/"trades.csv"
   pd.DataFrame([self.tt[-1]]).to_csv(fp,mode="a" if fp.exists() else "w",header=False if fp.exists() else True,index=False,encoding="utf-8-sig")
  return self.reg

 def _classify(self):
  if not self._cache: return "sideways"
  c=self._cache; s=0
  if "slp" in c:
   slp=c["slp"]
   if slp>0.05: s+=25
   elif slp>0: s+=10
   elif slp>-0.05: s-=10
   else: s-=25
  if "pos" in c:
   pos=c["pos"]
   if pos>70: s+=25
   elif pos>55: s+=15
   elif pos>45: s+=0
   elif pos>30: s-=15
   else: s-=25
  if "rsi" in c: s+=round((c["rsi"]-50)*0.3)
  if "macd" in c:
   md=c["macd"]*50
   if md>15: md=15
   elif md<-15: md=-15
   s+=round(md)
  self.rs=s; old=self.reg
  self.reg="uptrend" if s>20 else "downtrend" if s<-20 else "sideways"
  if self.reg!=old:
   self.t=None;self.gs_=0;self.gc=0;self.gr=0;self.gt=None;self.rh=0;self.ts=None
   now=dt.datetime.now()
   self.tt.append({"t":now.isoformat(),"d":"策略","s":0,"p":self.p or 0,"sc":self.rs,"r":old+"->"+self.reg,"pnl":0,"h":self.s})
   fp=LOGS_DIR/"trades.csv"
   pd.DataFrame([self.tt[-1]]).to_csv(fp,mode="a" if fp.exists() else "w",header=False if fp.exists() else True,index=False,encoding="utf-8-sig")
  return self.reg

 def _buy(self):
  d=self.k;last=d.iloc[-1]
  if len(d)<25: return None
  if self.reg=="uptrend":
   if self.t is not None: return None
   c=self._cache
   if not c or "sma20" not in c: return None
   sma=c["sma20"];slp=c.get("slp",0)
   if last["close"]<=sma or slp<=0: return None
   if not (last["low"]<=sma*1.005 and last["high"]>=sma*0.995): return None
   rv=c.get("rsi",50)
   if not (40<=rv<=55): return None
   vm=d["volume"].tail(20).mean()
   if vm>0 and last["volume"]>vm: return None
   return {"p":False,"sc":0.5,"sh":10000,"pr":float(last["close"]),"rs":"回踩均线买入"}
  if self.reg=="sideways":
   if self.t is not None: return None
   _,_,l=boll(d);rs=rsi(d["close"]);lt=d.iloc[-1]
   if lt["low"]>=l.iloc[-1]: return None
   tl=lt["low"];ok=True
   for j in range(1,4):
    idx=len(d)-1-j
    if idx>=0 and d.iloc[idx]["low"]<tl: ok=False;break
   if not ok: return {"p":True}
   sc=0.35;rv=rs.iloc[-1]
   if rv<20: sc+=0.25
   elif rv<30: sc+=0.15
   if macd_div(d): sc+=0.20
   vm=d["volume"].tail(20).mean()
   if vm>0 and lt["volume"]>=1.5*vm: sc+=0.10
   if sc<0.35: return None
   sh=20000 if sc>=0.80 else 15000 if sc>=0.70 else 10000 if sc>=0.50 else 5000
   return {"p":False,"sc":round(sc,2),"sh":sh,"pr":float(lt["close"]),"rs":"side"}
  if self.reg=="downtrend":
   _,_,l=boll(d);lt=d.iloc[-1]
   if lt["low"]>=l.iloc[-1]: return None
   tl=lt["low"];ok=True
   for j in range(1,4):
    idx=len(d)-1-j
    if idx>=0 and d.iloc[idx]["low"]<tl: ok=False;break
   if not ok: return {"p":True}
   return {"p":False,"sc":0.5,"sh":10000,"pr":float(lt["close"]),"rs":"触下轨加仓"}
  return None
 def _sell(self):
  d=self.k;cp=self.p
  if cp is None or len(d)<ATR_PERIOD: return None
  a_=atr(d).iloc[-1];u,_,_=boll(d);rs=rsi(d["close"]).iloc[-1]
  now=dt.datetime.now();eod=(now.hour==14 and now.minute>=50)
  if self.reg=="uptrend" and self.t is not None:
   bp=self.t["bp"]
   if cp>=u.iloc[-1]: return {"r":"触及布林上轨","tr":cp}
   if cp>=bp+1.5*float(a_): return {"r":"ATR止盈","tr":cp}
   if cp<=bp-2*float(a_): return {"r":"止损","tr":cp}
   if cp<=self._cache.get("sma20",0): return {"r":"跌破均线-趋势结束","tr":cp}
   if rs>=75: return {"r":"RSI超买","tr":cp}
   if eod: return {"r":"尾盘清仓","tr":cp}
  if self.reg=="sideways" and self.t is not None:
   bp=self.t["bp"]
   if cp>=u.iloc[-1]: return {"r":"触及布林上轨","tr":cp}
   if cp>=bp+float(a_): return {"r":"ATR止盈","tr":cp}
   if self.rh>0:
    sg=(self.rh-bp)/bp;pb=(self.rh-cp)/bp
    if sg>=0.015 and pb>=0.005: return {"r":"冲高回落","tr":cp}
   if rs>=70: return {"r":"RSI超买","tr":cp}
   if cp<=bp*0.985: return {"r":"止损","tr":cp}
   if self.ts and (time.time()-self.ts)/60>=120: return {"r":"时间止损","tr":cp}
   if eod: return {"r":"尾盘清仓","tr":cp}
  if self.reg=="downtrend" and self.gs_>0:
   bp=self.gc
   if cp>=bp+float(a_): return {"r":"ATR止盈","tr":cp}
   if cp>=u.iloc[-1]: return {"r":"触及布林上轨","tr":cp}
   if self.gr>0:
    sg=(self.gr-bp)/bp;pb=(self.gr-cp)/bp
    if sg>=0.015 and pb>=0.005: return {"r":"冲高回落","tr":cp}
   if rs>=70: return {"r":"RSI超买","tr":cp}
   if eod: return {"r":"尾盘清仓","tr":cp}
  return None
 def _eb(self,sig):
  pr=sig["pr"];sh=sig["sh"];sc=sig["sc"];co=pr*sh
  if co>self.a: sh=int(self.a/pr);co=pr*sh
  if sh<=0: return
  tcb=self.s*self.c;self.s+=sh;self.c=(tcb+co)/self.s;self.a-=co
  if self.reg=="downtrend":
   tgb=self.gs_*self.gc;self.gs_+=sh;self.gc=(tgb+co)/self.gs_ if self.gs_>0 else 0
   self.gr=pr
   if self.gt is None: self.gt=time.time()
  elif self.t is None:
   self.t={"bt":dt.datetime.now().isoformat(),"bp":pr,"bs":sh,"bsc":sc,"br":sig["rs"]}
   self.rh=pr;self.ts=time.time()
  self._log("B",pr,sh,sc,sig["rs"])
  self.lb={"t":dt.datetime.now().isoformat(),"p":pr,"s":sh,"sc":sc,"r":sig.get("rs","")}
 def _es(self,sig):
  pr=sig["tr"];rn=sig["r"]
  if self.reg=="downtrend" and self.gs_>0:
   sh=self.gs_;self.a+=pr*sh;self.s-=sh
   if self.s<=0: self.s=0;self.c=0
   pnl=(pr*sh)-(sh*self.gc)
   self._log("S",pr,sh,0,rn,pnl=pnl)
   self.ls={"t":dt.datetime.now().isoformat(),"p":pr,"s":sh,"r":rn,"pnl":round(pnl,2)}
   self.gs_=0;self.gc=0;self.gr=0;self.gt=None
  elif self.t is not None:
   sh=self.t["bs"];self.a+=pr*sh;self.s-=sh
   if self.s<=0: self.s=0;self.c=0
   pnl=(pr*sh)-(sh*self.t["bp"])
   self._log("S",pr,sh,0,rn,pnl=pnl)
   self.ls={"t":dt.datetime.now().isoformat(),"p":pr,"s":sh,"r":rn,"pnl":round(pnl,2)}
   self.t=None;self.rh=0;self.ts=None
 def _log(self,d,pr,sh,sc,rn,pnl=0.0):
  LOGS_DIR.mkdir(parents=True,exist_ok=True);fp=LOGS_DIR/"trades.csv";now=dt.datetime.now()
  r=pd.DataFrame([{"t":now.isoformat(),"d":d,"s":sh,"p":round(pr,2),"sc":round(sc,2),"r":rn,"pnl":round(pnl,2),"h":self.s}])
  r.to_csv(fp,mode="a" if fp.exists() else "w",header=False if fp.exists() else True,index=False,encoding="utf-8-sig")
  self.tt.append(r.iloc[0].to_dict())

 def _wds(self):
  LOGS_DIR.mkdir(parents=True,exist_ok=True);fp=LOGS_DIR/"daily_summary.csv"
  tpnl=sum(t.get("pnl",0) for t in self.tt if t.get("d")=="S");pv=self.s*(self.p or 0)
  r=pd.DataFrame([{"d":self.td,"s":self.s,"pv":round(pv,2),"a":round(self.a,2),"c":round(self.c,3),"pnl":round(tpnl,2),"n":len(self.tt)}])
  r.to_csv(fp,mode="a" if fp.exists() else "w",header=False if fp.exists() else True,index=False,encoding="utf-8-sig")

 def _save(self):
  try:
   with open(STATE_FILE,"w",encoding="utf-8") as f:
    json.dump({"s":self.s,"c":self.c,"a":self.a,"gs_":self.gs_,"gc":self.gc,"reg":self.reg,"rs":self.rs,"tt":self.tt,"td":self.td},f,ensure_ascii=False,indent=2)
  except: pass

 def _load(self):
  if not STATE_FILE.exists(): return
  try:
   s=json.load(open(STATE_FILE,"r",encoding="utf-8"))
   self.s=s.get("s",INITIAL_SHARES);self.c=s.get("c",INITIAL_COST);self.a=s.get("a",INITIAL_CASH);self.gs_=s.get("gs_",0);self.gc=s.get("gc",0);self.reg=s.get("reg","sideways");self.rs=s.get("rs",0);self.tt=s.get("tt",[]);self.td=s.get("td",dt.date.today().isoformat())
  except: pass

 def _check_buy_rt(self):
  if not self._cache or self.p is None: return None
  if self.reg!="downtrend" and self.t is not None: return None
  if self.reg=="downtrend" and self.gs_>0: return None
  if self.p>=self._cache.get("bl",0): return None
  sc=0.35;rsl=["bb_rt"];rv=self._cache.get("rsi",50)
  if rv<20: sc+=0.25;rsl.append(f"rsi{rv:.0f}+0.25")
  elif rv<30: sc+=0.15;rsl.append(f"rsi{rv:.0f}+0.15")
  if len(self.k)>=25:
    if macd_div(self.k): sc+=0.20;rsl.append("div+0.20")
    vm=self.k["volume"].tail(20).mean();lt=self.k.iloc[-1]
    if vm>0 and lt["volume"]>=VOLUME_THRESHOLD*vm: sc+=0.10;rsl.append("vol"+str(round(lt["volume"]/vm,1))+"x+0.10")
  if sc<MIN_SCORE: return None
  sh=20000 if sc>=0.80 else 15000 if sc>=0.70 else 10000 if sc>=0.50 else 5000 if sc>=0.35 else 0
  return {"p":False,"sc":round(sc,2),"sh":sh,"pr":self.p,"rs":"; ".join(rsl)}

 def tick_q(self):
  s=self._fs()
  if s is None: return {"type":"q","ok":False}
  self.p=s["price"];self.cp=s["change"]
  if self.gs_>0: self.gr=max(self.gr,s["price"])
  if self.t is not None: self.rh=max(self.rh,s["price"])
  ss=self._sell() if self.gs_>0 else None
  if ss: self._es(ss)
  rb=self._check_buy_rt()
  self._bs=rb
  if rb and not rb.get("p"): self._eb(rb)
  return {"type":"q","ok":True,"p":self.p,"ch":self.cp,"ss":ss}

 def tick_k(self):
  td=dt.date.today().isoformat()
  if td!=self.td: self._wds();self.td=td;self.tt=[]
  d=self._fk(lmt=240)
  if d is None or len(d)==0: return {"type":"k","ok":False}
  lt=d["time"].iloc[-1]
  if self.lt is not None and lt<=pd.Timestamp(self.lt): return {"type":"k","ok":True,"nb":False}
  nb=d[d["time"]>pd.Timestamp(self.lt)] if self.lt else d
  self.k=pd.concat([self.k,nb],ignore_index=True);self.k=self.k.tail(500).reset_index(drop=True);self.lt=lt.isoformat()
  ind=self._ci()
  now=dt.datetime.now()
  if self.rt is None or (now-self.rt).total_seconds()>=1800:
   self._classify();self.rt=now
  bs=self._buy()
  if bs: self._bs=bs
  if bs and not bs.get("p"): self._eb(bs)
  ss=self._sell() if self.gs_>0 else None
  if ss: self._es(ss)
  self._save()
  return {"type":"k","ok":True,"nb":True,"ind":ind,"bs":bs,"ss":ss}

 def gs(self):
  kd=[]
  if len(self.k)>0:
   tl=self.k.tail(120)
   for _,r in tl.iterrows(): kd.append({"t":r["time"].strftime("%H:%M"),"o":round(float(r["open"]),2),"h":round(float(r["high"]),2),"l":round(float(r["low"]),2),"c":round(float(r["close"]),2),"v":float(r["volume"])})
  bd={"u":[],"m":[],"l":[]};rd=[]
  if len(self.k)>=BB_PERIOD:
   u,m,l=boll(self.k);rs=rsi(self.k["close"]);tl=self.k.tail(120)
   for i in range(len(tl)):
    j=tl.index[i]
    bd["u"].append(round(float(u.loc[j]),2) if j in u.index else None)
    bd["m"].append(round(float(m.loc[j]),2) if j in m.index else None)
    bd["l"].append(round(float(l.loc[j]),2) if j in l.index else None)
    rd.append(round(float(rs.loc[j]),2) if j in rs.index else None)
  pv=self.s*(self.p or 0);ta=pv+self.a;ti=None
  if self.gs_>0:
   bp=self.gc;av=0
   if len(self.k)>=ATR_PERIOD: av=round(float(atr(self.k).iloc[-1]),2)
   ti={"bp":round(bp,2),"s":self.gs_,"tp":round(bp+av,2),"rh":round(self.gr,2),"el":round((time.time()-self.gt)/60,0) if self.gt else 0}
  return {"t":dt.datetime.now().isoformat(),"mo":is_market(),"ts":self.s,"ac":round(self.c,3),"av":round(self.a,2),"pv":round(pv,2),"ta":round(ta,2),"pp":round((self.p or 0)/self.c-1,4) if self.c>0 else 0,"p":self.p,"ch":self.cp,"k":kd,"b":bd,"rs":rd,"ind":self._ci() if len(self.k)>=BB_PERIOD else {},"ct":ti,"lbs":self.lb,"lss":self.ls,"bs_rt":self._bs,"rg":self.reg,"rs_":self.rs,"tt":self.tt[-20:]}