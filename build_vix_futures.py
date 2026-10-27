#!/usr/bin/env python3
"""Reconstruit VX1..VX4 à partir des CSV mensuels CBOE locaux.

Usage: python3 build_vix_futures.py
Entrée: vix_futures_cboe/*.csv
Sorties: vix_futures_cboe/VIX_FUTURES_HISTORIQUE.csv
         vix_futures_cboe/VIX_FUTURES_QA.csv
"""
from pathlib import Path
import re
import pandas as pd

ROOT = Path("vix_futures_cboe")
MONTH_CODES = dict(zip("FGHJKMNQUVXZ", range(1, 13)))
MIN_TENORS = 4


def clean_columns(frame):
    frame.columns = [re.sub(r"[^a-z0-9]", "", str(x).lower()) for x in frame.columns]
    return frame


def column(frame, *candidates):
    for name in candidates:
        if name in frame.columns:
            return name
    raise ValueError(f"Colonnes attendues {candidates}; colonnes reçues: {list(frame.columns)}")


def read_contract(path):
    # 2014+: VX_YYYY-MM-DD.csv; 2004-2013: CFE_F13_VX.csv
    recent = re.fullmatch(r"VX_(\\d{4}-\\d{2}-\\d{2})", path.stem)
    old = re.fullmatch(r"CFE_([FGHJKMNQUVXZ])(\\d{2})_VX", path.stem)
    if not (recent or old):
        return None
    if recent:
        expiry = pd.Timestamp(recent.group(1))
    else:
        year = 2000 + int(old.group(2))
        month = MONTH_CODES[old.group(1)]
        # Avant 2014, le nom donne le mois contractuel, pas la date
        # d'expiration exacte. Pour le classement, utiliser le 1er du mois
        # puis exclure les lignes après le dernier jour observé du contrat.
        expiry = pd.Timestamp(year, month, 1) + pd.offsets.MonthEnd(0)
    frame = clean_columns(pd.read_csv(path, low_memory=False))
    date_col = column(frame, "tradedate", "date")
    settle_col = column(frame, "settle", "settlement", "settlementprice")
    dates = pd.to_datetime(frame[date_col], errors="coerce")
    values = pd.to_numeric(frame[settle_col], errors="coerce")
    # Les derniers settlements sont parfois publiés sur le jour d'expiration:
    # on les conserve pour le diagnostic, mais pas dans la courbe négociable.
    out = pd.DataFrame({"Date": dates.dt.normalize(), "Expiry": expiry,
                        "Settle": values, "Source": path.name})
    out = out.dropna(subset=["Date", "Settle"])
    out = out[(out["Settle"] > 0) & (out["Date"] < expiry)]
    return out


def main():
    files = sorted(ROOT.glob("*.csv"))
    frames, errors = [], []
    for path in files:
        try:
            part = read_contract(path)
            if part is not None:
                frames.append(part)
        except Exception as exc:
            errors.append({"file": path.name, "error": str(exc)})
    if not frames:
        raise RuntimeError("Aucun CSV VX lisible : vérifier les en-têtes des fichiers.")
    long = pd.concat(frames, ignore_index=True)
    # Une même échéance peut apparaître dans deux archives : détecter les conflits.
    conflicts = (long.groupby(["Date", "Expiry"])["Settle"].nunique() > 1)
    if conflicts.any():
        print("AVERTISSEMENT :", int(conflicts.sum()), "prix divergents pour date/échéance.")
    long = long.sort_values(["Date", "Expiry", "Source"]).drop_duplicates(
        ["Date", "Expiry"], keep="last")
    long = long.sort_values(["Date", "Expiry"])
    long["Tenor"] = long.groupby("Date").cumcount() + 1
    front = long[long["Tenor"] <= MIN_TENORS]
    prices = front.pivot(index="Date", columns="Tenor", values="Settle")
    prices = prices.rename(columns=lambda n: f"VX{n}").sort_index()
    expiry = front.pivot(index="Date", columns="Tenor", values="Expiry")
    expiry = expiry.rename(columns=lambda n: f"VX{n}_Expiry")
    result = prices.join(expiry)
    result["Available_Contracts"] = long.groupby("Date").size()
    for i in range(1, MIN_TENORS):
        result[f"VX{i+1}_minus_VX{i}"] = result[f"VX{i+1}"] - result[f"VX{i}"]
    result["VX2_div_VX1_minus_1"] = result["VX2"] / result["VX1"] - 1
    result["VX1_Change_5D"] = result["VX1"].diff(5)
    result["VX1_Change_20D"] = result["VX1"].diff(20)
    result.index.name = "Date"
    result.to_csv(ROOT / "VIX_FUTURES_HISTORIQUE.csv", date_format="%Y-%m-%d")
    qa = result.groupby(result.index.year).agg(
        Days=("Available_Contracts", "size"),
        Days_with_4_contracts=("VX4", "count"),
        Min_contracts=("Available_Contracts", "min"),
        Max_contracts=("Available_Contracts", "max"))
    qa["Coverage_4_contracts_pct"] = (100 * qa["Days_with_4_contracts"] / qa["Days"]).round(1)
    qa.to_csv(ROOT / "VIX_FUTURES_QA.csv")
    if errors:
        pd.DataFrame(errors).to_csv(ROOT / "VIX_FUTURES_PARSE_ERRORS.csv", index=False)
        print("Fichiers non lus :", len(errors), "(voir VIX_FUTURES_PARSE_ERRORS.csv)")
    print("Période :", result.index.min().date(), "→", result.index.max().date())
    print("Séances :", len(result), "; avec VX1–VX4 :", result["VX4"].notna().sum())
    print(qa.to_string())
    print("Fichiers créés dans", ROOT.resolve())
    print("NOTE : pour 2004-2013, l'expiration exacte doit être validée.")
    print("NOTE : les différences VX1 sur les jours de roll ne sont pas des rendements de contrat constant.")


if __name__ == "__main__":
    main()
