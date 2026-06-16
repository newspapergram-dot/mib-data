"""volume_tools.py — Validazione volume + fallback stooq + OBV/CMF/VWAP."""
import numpy as np
import pandas as pd


def validate_volume(df: pd.DataFrame, vol_col="volume", min_nonzero_frac=0.8) -> dict:
    if vol_col not in df.columns or df.empty:
        return {"reliable": False, "reason": "no_volume_column", "nonzero_frac": 0.0}
    vol = pd.to_numeric(df[vol_col], errors="coerce")
    n = len(vol)
    nonzero = ((vol.notna()) & (vol > 0)).sum()
    frac = nonzero / n if n else 0.0
    reliable = frac >= min_nonzero_frac
    return {"reliable": bool(reliable),
            "reason": "ok" if reliable else "too_many_zero_or_nan",
            "nonzero_frac": round(float(frac), 3)}


def fetch_stooq_fallback(ticker_yf: str):
    try:
        from pandas_datareader import data as web
    except ImportError:
        return None
    mapping = {".MI": ".IT", ".PA": ".FR", ".L": ".UK", ".DE": ".DE", ".AS": ".NL"}
    stq = ticker_yf
    for k, v in mapping.items():
        if ticker_yf.endswith(k):
            stq = ticker_yf[:-len(k)] + v
            break
    try:
        df = web.DataReader(stq, "stooq")
        return df.sort_index()
    except Exception:
        return None


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    direction = np.sign(close.diff()).fillna(0)
    return (direction * volume).cumsum()


def cmf(high, low, close, volume, period=20) -> pd.Series:
    rng = (high - low).replace(0, np.nan)
    mfm = (((close - low) - (high - close)) / rng).fillna(0)
    mfv = mfm * volume
    return mfv.rolling(period).sum() / volume.rolling(period).sum()


def vwap(high, low, close, volume) -> pd.Series:
    tp = (high + low + close) / 3.0
    return (tp * volume).cumsum() / volume.cumsum()


def volume_quality_report(px: pd.DataFrame, out_path="data/volume_quality.csv"):
    import os
    rows = []
    for tk in px["ticker"].unique():
        g = px[px["ticker"] == tk].tail(60)
        v = validate_volume(g)
        rows.append({"ticker": tk, "volume_reliable": v["reliable"],
                     "nonzero_frac": v["nonzero_frac"], "reason": v["reason"]})
    out = pd.DataFrame(rows)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    out.to_csv(out_path, index=False)
    print(f"[volume] {out['volume_reliable'].sum()}/{len(out)} ticker affidabili -> {out_path}")
    return out


if __name__ == "__main__":
    import urllib.request, io
    base = "https://raw.githubusercontent.com/newspapergram-dot/mib-data/refs/heads/main/data/"
    px = pd.read_csv(io.StringIO(urllib.request.urlopen(base+"mib_data.csv", timeout=60).read().decode("utf-8","replace")))
    volume_quality_report(px)
