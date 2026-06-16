"""macro_calendar.py — Calendario macro eventi alto impatto (kill switch)."""
import os
import pandas as pd
from datetime import datetime

FOMC_2026 = ["2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
             "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09"]
ECB_2026 = ["2026-01-29", "2026-03-12", "2026-04-16", "2026-06-04",
            "2026-07-23", "2026-09-10", "2026-10-29", "2026-12-17"]


def build_static_macro() -> pd.DataFrame:
    rows = []
    for d in FOMC_2026:
        rows.append({"date": d, "time": "14:00 ET", "event": "FOMC Rate Decision",
                     "country": "US", "impact": "high",
                     "forecast": None, "previous": None, "source": "federalreserve.gov"})
    for d in ECB_2026:
        rows.append({"date": d, "time": "14:15 CET", "event": "ECB Rate Decision",
                     "country": "EU", "impact": "high",
                     "forecast": None, "previous": None, "source": "ecb.europa.eu"})
    return pd.DataFrame(rows)


def fetch_fmp_macro(api_key, frm, to):
    import requests
    r = requests.get("https://financialmodelingprep.com/api/v3/economic_calendar",
                     params={"from": frm, "to": to, "apikey": api_key}, timeout=20)
    df = pd.DataFrame(r.json())
    if df.empty:
        return df
    df = df[df["impact"].astype(str).str.lower() == "high"].copy()
    df["source"] = "FMP"
    return df


def build_macro_calendar(out_path="data/macro_calendar.csv", fmp_key=None):
    frames = [build_static_macro()]
    if fmp_key:
        try:
            frm = datetime.utcnow().strftime("%Y-%m-%d")
            to = (datetime.utcnow() + pd.Timedelta(days=21)).strftime("%Y-%m-%d")
            fmp = fetch_fmp_macro(fmp_key, frm, to)
            if not fmp.empty:
                frames.append(fmp)
        except Exception as e:
            print(f"[macro] FMP fallito (non bloccante): {e}")
    out = pd.concat(frames, ignore_index=True)
    today = pd.Timestamp(datetime.utcnow().date())
    def killswitch(d):
        try:
            days = (pd.to_datetime(d) - today).days
            return 0 <= days <= 14
        except Exception:
            return False
    out["killswitch_next_2w"] = out["date"].apply(killswitch)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    out.to_csv(out_path, index=False)
    print(f"[macro] salvato {out_path}: {len(out)} eventi, "
          f"{out['killswitch_next_2w'].sum()} kill switch prossime 2 settimane")
    return out

if __name__ == "__main__":
    build_macro_calendar(fmp_key=os.getenv("FMP_API_KEY"))
