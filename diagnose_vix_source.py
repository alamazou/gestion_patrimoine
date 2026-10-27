#!/usr/bin/env python3
"""Inspecte les prix bruts CBOE autour des anomalies; aucun prix modifié."""
from pathlib import Path
import pandas as pd
from build_vix_futures import read_contract
ROOT=Path("vix_futures_cboe")
DATES=pd.to_datetime(["2006-06-13","2006-06-14","2006-06-15","2007-03-23","2007-03-26","2007-03-27"])
rows=[]
for path in sorted(ROOT.glob("*.csv")):
    if not (path.name.startswith("CFE_") or path.name.startswith("VX_")):
        continue
    try:
        parsed=read_contract(path)
        if parsed is None: continue
        frame,_=parsed
        hit=frame[frame["Date"].isin(DATES)]
        if not hit.empty:
            rows.append(hit)
    except Exception as exc:
        print("Erreur",path.name,str(exc))
if not rows:
    raise RuntimeError("Aucune ligne CBOE correspondante")
out=pd.concat(rows,ignore_index=True).sort_values(["Date","Expiry","Source"])
out.to_csv(ROOT/"VIX_FUTURES_SOURCE_DIAGNOSTIC.csv",index=False)
print(out.to_string(index=False))
print("Rapport:",ROOT/"VIX_FUTURES_SOURCE_DIAGNOSTIC.csv")
