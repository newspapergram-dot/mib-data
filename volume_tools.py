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


def cmf_mfi(df_ticker, cmf_window=20, mfi_window=14):
    """
    df_ticker: DataFrame OHLCV di UN SINGOLO ticker, ordinato per data,
               colonne: high, low, close, volume (stessi nomi di mib_data.csv)
    Ritorna: (cmf_ultimo, mfi_ultimo) -> ultimi valori validi, o (None, None)
             se la storia e' troppo corta per calcolarli.
    """
    import pandas as pd
    import numpy as np

    d = df_ticker.copy()
    if len(d) < max(cmf_window, mfi_window) + 1:
        return None, None

    # --- CMF(20): Chaikin Money Flow ---
    rng = (d["high"] - d["low"]).replace(0, np.nan)
    mfm = ((d["close"] - d["low"]) - (d["high"] - d["close"])) / rng
    mfv = mfm * d["volume"]
    cmf = mfv.rolling(cmf_window).sum() / d["volume"].rolling(cmf_window).sum()

    # --- MFI(14): Money Flow Index ---
    tp = (d["high"] + d["low"] + d["close"]) / 3
    pos_mf = np.where(tp.diff() > 0, tp * d["volume"], 0.0)
    neg_mf = np.where(tp.diff() < 0, tp * d["volume"], 0.0)
    pos_sum = pd.Series(pos_mf, index=d.index).rolling(mfi_window).sum()
    neg_sum = pd.Series(neg_mf, index=d.index).rolling(mfi_window).sum()
    mfi = 100 - 100 / (1 + pos_sum / neg_sum.replace(0, np.nan))

    cmf_last = cmf.dropna().iloc[-1] if cmf.dropna().size else None
    mfi_last = mfi.dropna().iloc[-1] if mfi.dropna().size else None
    return (round(float(cmf_last), 4) if cmf_last is not None else None,
            round(float(mfi_last), 2) if mfi_last is not None else None)
    
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
    cmf_val, mfi_val = cmf_mfi(df_ticker)   # df_ticker = i dati OHLCV di QUEL ticker

row = {
    "ticker": ticker,
    "volume_reliable": reliable,      # campo che hai già
    "nonzero_frac": nonzero_frac,     # campo che hai già
    "reason": reason,                 # campo che hai già
    "cmf20": cmf_val,                 # NUOVO
    "mfi14": mfi_val,                 # NUOVO
}
    return out


if __name__ == "__main__":
    import urllib.request, io
    base = "https://raw.githubusercontent.com/newspapergram-dot/mib-data/refs/heads/main/data/"
    px = pd.read_csv(io.StringIO(urllib.request.urlopen(base+"mib_data.csv", timeout=60).read().decode("utf-8","replace")))
    volume_quality_report(px)
