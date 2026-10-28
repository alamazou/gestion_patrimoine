#!/usr/bin/env python3
"""Prepare and audit constant-maturity VIX futures from raw CBOE contract CSVs.

Run from the repository root:
    python3 prepare_vix_constant_maturity.py

Inputs:  vix_futures_cboe/input_data_raw/*.csv
Outputs: vix_futures_cboe/constant_maturity_review/*.csv

VX_CM30/90/180 are *interpolated futures prices*, NOT CBOE VIX/VIX3M/VIX6M.
No extrapolation and no automatic liquidity cutoff. For pre-2014 CFE files,
expiry dates are ESTIMATED and must be independently validated.
"""
from __future__ import annotations

import argparse
import calendar
import re
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

MONTH_CODES = dict(zip("FGHJKMNQUVXZ", range(1, 13)))
TARGETS = (30, 90, 180)


def estimated_expiry(year: int, month: int) -> pd.Timestamp:
    """30 days before the third Friday of the month after the contract month."""
    ny, nm = (year + 1, 1) if month == 12 else (year, month + 1)
    first = date(ny, nm, 1)
    third_friday = first + timedelta(days=(4 - first.weekday()) % 7 + 14)
    return pd.Timestamp(third_friday - timedelta(days=30))


def read_contract(path: Path) -> pd.DataFrame | None:
    old = re.fullmatch(r"CFE_([FGHJKMNQUVXZ])(\d{2})_VX", path.stem, re.I)
    new = re.fullmatch(r"VX_(\d{4}-\d{2}-\d{2})", path.stem, re.I)
    if not (old or new):
        return None
    if new:
        expiry = pd.Timestamp(new.group(1))
        expiry_type = "actual_from_filename"
    else:
        expiry = estimated_expiry(2000 + int(old.group(2)), MONTH_CODES[old.group(1).upper()])
        expiry_type = "estimated_pre2014"
    lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    start = next((i for i, line in enumerate(lines)
                  if "trade date" in line.lower() or line.lower().startswith("date,")), None)
    if start is None:
        raise ValueError("No trade date header")
    import io
    header = lines[start]
    width = len(header.split(","))
    valid = [header] + [line for line in lines[start + 1:]
                        if line.strip() and len(line.split(",")) == width]
    raw = pd.read_csv(io.StringIO("\n".join(valid)))
    raw.columns = [re.sub(r"[^a-z0-9]", "", str(c).lower()) for c in raw.columns]

    def pick(*names):
        return next((n for n in names if n in raw.columns), None)

    date_col = pick("tradedate", "date")
    settle_col = pick("settle", "settlement", "settlementprice")
    if not date_col or not settle_col:
        raise ValueError(f"Missing date/settle columns: {list(raw.columns)}")
    vol_col = pick("volume", "totalvolume", "vol")
    oi_col = pick("openinterest", "openint", "oi")
    out = pd.DataFrame({
        "Date": pd.to_datetime(raw[date_col], errors="coerce").dt.normalize(),
        "Expiry": expiry,
        "Settle": pd.to_numeric(raw[settle_col], errors="coerce"),
        "Volume": pd.to_numeric(raw[vol_col], errors="coerce") if vol_col else np.nan,
        "Open_Interest": pd.to_numeric(raw[oi_col], errors="coerce") if oi_col else np.nan,
        "Expiry_Source": expiry_type,
        "Source_File": path.name,
    })
    if old:
        out.loc[out["Date"] < pd.Timestamp("2007-03-26"), "Settle"] /= 10.0
    return out.dropna(subset=["Date", "Settle"]).query("Settle > 0 and Date < Expiry")


def build(input_dir: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    frames, errors = [], []
    for path in sorted(input_dir.glob("*.csv")):
        try:
            frame = read_contract(path)
            if frame is not None:
                frames.append(frame)
        except Exception as exc:
            errors.append({"Source_File": path.name, "Error": str(exc)})
    pd.DataFrame(errors, columns=["Source_File", "Error"]).to_csv(output_dir / "PARSE_ERRORS.csv", index=False)
    if not frames:
        raise RuntimeError(f"No recognized CBOE contract CSVs in {input_dir}")
    contracts = pd.concat(frames, ignore_index=True)
    conflicts = (contracts.groupby(["Date", "Expiry"])["Settle"].nunique().reset_index(name="Distinct_Settles"))
    conflicts.query("Distinct_Settles > 1").to_csv(output_dir / "CONFLICTS.csv", index=False)
    contracts = (contracts.sort_values(["Date", "Expiry", "Source_File"])
                 .drop_duplicates(["Date", "Expiry"], keep="last"))
    contracts["Days_To_Expiry"] = (contracts["Expiry"] - contracts["Date"]).dt.days
    contracts = contracts.sort_values(["Date", "Days_To_Expiry"])
    contracts["Tenor"] = contracts.groupby("Date").cumcount() + 1
    contracts.to_csv(output_dir / "CONTRACTS_DAILY.csv", index=False)

    audits = []
    for day, group in contracts.groupby("Date", sort=True):
        g = group.sort_values("Days_To_Expiry")
        for target in TARGETS:
            lower = g[g["Days_To_Expiry"] <= target].tail(1)
            upper = g[g["Days_To_Expiry"] >= target].head(1)
            row = {"Date": day, "Target_Days": target,
                   "Available_Contracts": len(g), "VX_CM": np.nan,
                   "Status": "no_bracket"}
            if not lower.empty and not upper.empty:
                lo, hi = lower.iloc[0], upper.iloc[0]
                t1, t2 = int(lo["Days_To_Expiry"]), int(hi["Days_To_Expiry"])
                w = 0.0 if t1 == t2 else (target - t1) / (t2 - t1)
                row.update({
                    "VX_CM": float(lo["Settle"] + w * (hi["Settle"] - lo["Settle"])),
                    "Status": "ok", "Lower_Tenor": int(lo["Tenor"]),
                    "Upper_Tenor": int(hi["Tenor"]),
                    "Lower_Expiry": lo["Expiry"], "Upper_Expiry": hi["Expiry"],
                    "Lower_Days": t1, "Upper_Days": t2,
                    "Lower_Settle": lo["Settle"], "Upper_Settle": hi["Settle"],
                    "Lower_Volume": lo["Volume"], "Upper_Volume": hi["Volume"],
                    "Lower_OI": lo["Open_Interest"], "Upper_OI": hi["Open_Interest"],
                    "Weight_Upper": w,
                    "Expiry_Estimated": (lo["Expiry_Source"] == "estimated_pre2014"
                                         or hi["Expiry_Source"] == "estimated_pre2014"),
                })
            audits.append(row)
    audit = pd.DataFrame(audits)
    audit.to_csv(output_dir / "INTERPOLATION_AUDIT.csv", index=False)
    wide = audit.pivot(index="Date", columns="Target_Days", values="VX_CM")
    wide = wide.rename(columns=lambda n: f"VX_CM{n}").reset_index()
    wide.to_csv(output_dir / "VIX_CONSTANT_MATURITY.csv", index=False)
    summary = (audit.groupby("Target_Days")
               .agg(Days=("Date", "size"), Calculable=("VX_CM", "count")))
    summary["Coverage_Pct"] = (100 * summary["Calculable"] / summary["Days"]).round(2)
    summary.to_csv(output_dir / "COVERAGE_SUMMARY.csv")
    print(f"Read {len(frames)} contract files; {len(contracts)} date/contract observations")
    print(summary.to_string())
    print(f"Review outputs: {output_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path,
                        default=Path("vix_futures_cboe/input_data_raw"))
    parser.add_argument("--output-dir", type=Path,
                        default=Path("vix_futures_cboe/constant_maturity_review"))
    args = parser.parse_args()
    build(args.input_dir, args.output_dir)


if __name__ == "__main__":
    main()
