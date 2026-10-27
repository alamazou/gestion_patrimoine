#!/usr/bin/env python3
"""Audit des variations VX1-VX4 : ne modifie jamais les prix source."""
from pathlib import Path
import numpy as np
import pandas as pd

ROOT=Path("vix_futures_cboe")
df=pd.read_csv(ROOT/"VIX_FUTURES_HISTORIQUE.csv",parse_dates=["Date"]).set_index("Date").sort_index()
flags=[]
def flag(dt,field,kind,value,threshold,detail=""):
    flags.append(dict(Date=dt.strftime("%Y-%m-%d"),Series=field,Anomaly=kind,
                      Value=float(value) if pd.notna(value) else None,
                      Threshold=float(threshold) if pd.notna(threshold) else None,
                      Detail=detail))
for i in range(1,5):
    name=f"VX{i}"
    px=pd.to_numeric(df[name],errors="coerce")
    exp=pd.to_datetime(df[f"{name}_Expiry"],errors="coerce")
    for dt in df.index[px.isna() | (px<=0)]:
        flag(dt,name,"MISSING_OR_NONPOSITIVE",px.loc[dt],0)
    for dt in df.index[exp.notna() & (exp<=df.index)]:
        flag(dt,name,"EXPIRED_CONTRACT",px.loc[dt],0,str(exp.loc[dt]))
    # Compare daily changes ONLY when the contract expiration stays identical.
    same=(exp==exp.shift(1)) & px.notna() & px.shift(1).notna()
    delta=px.diff()
    pct=px.pct_change(fill_method=None)
    # Robust trailing threshold computed from past observations only; no future leakage.
    history=delta.abs().where(same).shift(1)
    rolling=history.rolling(252,min_periods=60).quantile(.995)
    suspicious=same & ((delta.abs()>np.maximum(8.,rolling*2)) | (pct.abs()>.45))
    for dt in df.index[suspicious.fillna(False)]:
        flag(dt,name,"EXTREME_SAME_CONTRACT_MOVE",delta.loc[dt],
             max(8.,rolling.loc[dt]*2) if pd.notna(rolling.loc[dt]) else 8.,
             f"pct={pct.loc[dt]:.1%}; expiry={exp.loc[dt].date()}")
    # Explicit roll flag: large discontinuities at contract switch are not market returns.
    roll=(exp!=exp.shift(1)) & exp.notna() & exp.shift(1).notna()
    large_roll=roll & (delta.abs()>3)
    for dt in df.index[large_roll.fillna(False)]:
        flag(dt,name,"ROLL_DISCONTINUITY",delta.loc[dt],3,
             f"{exp.shift(1).loc[dt].date()} -> {exp.loc[dt].date()}")
for i in range(1,4):
    a,b=df[f"VX{i}"],df[f"VX{i+1}"]
    spread=b-a
    for dt in df.index[(spread.abs()>25).fillna(False)]:
        flag(dt,f"VX{i+1}-VX{i}","EXTREME_CURVE_SPREAD",spread.loc[dt],25)
out=pd.DataFrame(flags,columns=["Date","Series","Anomaly","Value","Threshold","Detail"])
out.to_csv(ROOT/"VIX_FUTURES_ANOMALIES.csv",index=False)
summary=out.groupby(["Series","Anomaly"]).size().rename("Count").reset_index() if len(out) else pd.DataFrame(columns=["Series","Anomaly","Count"])
summary.to_csv(ROOT/"VIX_FUTURES_ANOMALIES_SUMMARY.csv",index=False)
print("Observations:",len(df)," | Alertes:",len(out))
print(summary.to_string(index=False))
print("Rapport:",ROOT/"VIX_FUTURES_ANOMALIES.csv")
