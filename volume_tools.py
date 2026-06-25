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


def ad_line(high, low, close, volume) -> pd.Series:
    """Accumulation/Distribution Line (Williams).
    MFM = ((C-L)-(H-C))/(H-L); ADL = cumsum(MFM * volume).
    ADL crescente = accumulazione (denaro 'forte' in entrata); calante = distribuzione.
    Complementare a CMF (gia' presente): CMF e' oscillatore 20gg, ADL e' cumulata."""
    rng = (high - low).replace(0, np.nan)
    mfm = (((close - low) - (high - close)) / rng).fillna(0)
    return (mfm * volume).cumsum()


def volume_anomaly(df_ticker, lookback=20, mult=1.5) -> dict:
    """Anomalia di volume giornaliera: volume ultimo > mult x media a `lookback`.
    Intercetta l'impronta dei grandi fondi (spike di volume). Restituisce anche la
    direzione (up/down close) per distinguere accumulazione da distribuzione.
    df_ticker: OHLCV di UN ticker ordinato per data (colonne high/low/close/volume)."""
    d = df_ticker.dropna(subset=["volume", "close"])
    if len(d) < lookback + 1:
        return {"anomaly": False, "vol_ratio": None, "direction": None, "smart_flag": None}
    vol = pd.to_numeric(d["volume"], errors="coerce")
    avg = vol.rolling(lookback).mean().iloc[-2]   # media ESCLUSO il giorno corrente
    last_vol = float(vol.iloc[-1])
    ratio = (last_vol / avg) if avg and avg > 0 else None
    anomaly = bool(ratio is not None and ratio >= mult)
    chg = float(d["close"].iloc[-1] - d["close"].iloc[-2])
    direction = "up" if chg > 0 else ("down" if chg < 0 else "flat")
    # smart_flag: spike di volume su giornata positiva = accumulazione; su negativa = distribuzione
    smart_flag = None
    if anomaly:
        smart_flag = "accumulation" if direction == "up" else ("distribution" if direction == "down" else "neutral")
    return {"anomaly": anomaly,
            "vol_ratio": round(ratio, 2) if ratio is not None else None,
            "direction": direction, "smart_flag": smart_flag}


def smart_money_signal(df_ticker, lookback=20, slope_window=20) -> dict:
    """Segnale 'Smart Money' aggregato (Foreground) per UN ticker.
    Combina tre letture volume-ponderate, riusando i tool esistenti:
      - pendenza ADL (accumulazione/distribuzione strutturale)   -> ad_line()
      - CMF(20) (pressione netta mensile)                        -> cmf()  [riuso]
      - anomalia di volume + direzione (impronta dei fondi)      -> volume_anomaly()
    Ritorna uno score in [-1, +1] e un'etichetta leggibile."""
    d = df_ticker.dropna(subset=["high", "low", "close", "volume"])
    if len(d) < max(lookback, slope_window) + 5:
        return {"score": None, "label": "dati insufficienti",
                "adl_slope_pct": None, "cmf20": None, "vol_ratio": None, "smart_flag": None}
    adl = ad_line(d["high"], d["low"], d["close"], d["volume"])
    # pendenza ADL normalizzata sull'ampiezza recente (robusta alla scala)
    recent = adl.iloc[-slope_window:]
    span = (adl.iloc[-60:].max() - adl.iloc[-60:].min()) or 1.0
    adl_slope = float((recent.iloc[-1] - recent.iloc[0]) / abs(span))
    cmf20 = cmf(d["high"], d["low"], d["close"], d["volume"], 20).dropna()
    cmf_last = float(cmf20.iloc[-1]) if cmf20.size else 0.0
    va = volume_anomaly(d, lookback=lookback)
    spike = 0.0
    if va["smart_flag"] == "accumulation":
        spike = +0.34
    elif va["smart_flag"] == "distribution":
        spike = -0.34
    score = float(np.clip(0.45 * np.tanh(3 * adl_slope) + 0.45 * np.tanh(3 * cmf_last) + spike, -1, 1))
    if score >= 0.33:
        label = "ACCUMULAZIONE (smart money in entrata)"
    elif score <= -0.33:
        label = "DISTRIBUZIONE (smart money in uscita)"
    else:
        label = "neutro"
    return {"score": round(score, 3), "label": label,
            "adl_slope_pct": round(adl_slope * 100, 1), "cmf20": round(cmf_last, 3),
            "vol_ratio": va["vol_ratio"], "smart_flag": va["smart_flag"]}


def cmf_mfi(df_ticker, cmf_window=20, mfi_window=14):
    """
    df_ticker: DataFrame OHLCV di UN SINGOLO ticker, ordinato per data,
               colonne: high, low, close, volume (stessi nomi di mib_data.csv)
    Ritorna: (cmf_ultimo, mfi_ultimo) -> ultimi valori validi, o (None, None)
             se la storia e' troppo corta per calcolarli.
    """
    d = df_ticker.copy()
    if len(d) < max(cmf_window, mfi_window) + 1:
        return None, None

    # --- CMF(20): Chaikin Money Flow ---
    rng = (d["high"] - d["low"]).replace(0, np.nan)
    mfm = ((d["close"] - d["low"]) - (d["high"] - d["close"])) / rng
    mfv = mfm * d["volume"]
    cmf_series = mfv.rolling(cmf_window).sum() / d["volume"].rolling(cmf_window).sum()

    # --- MFI(14): Money Flow Index ---
    tp = (d["high"] + d["low"] + d["close"]) / 3
    pos_mf = np.where(tp.diff() > 0, tp * d["volume"], 0.0)
    neg_mf = np.where(tp.diff() < 0, tp * d["volume"], 0.0)
    pos_sum = pd.Series(pos_mf, index=d.index).rolling(mfi_window).sum()
    neg_sum = pd.Series(neg_mf, index=d.index).rolling(mfi_window).sum()
    mfi_series = 100 - 100 / (1 + pos_sum / neg_sum.replace(0, np.nan))

    cmf_last = cmf_series.dropna().iloc[-1] if cmf_series.dropna().size else None
    mfi_last = mfi_series.dropna().iloc[-1] if mfi_series.dropna().size else None
    return (round(float(cmf_last), 4) if cmf_last is not None else None,
            round(float(mfi_last), 2) if mfi_last is not None else None)


def volume_quality_report(px: pd.DataFrame, out_path="data/volume_quality.csv"):
    import os
    rows = []
    for tk in px["ticker"].unique():
        g = px[px["ticker"] == tk].tail(60)
        v = validate_volume(g)
        cmf_val, mfi_val = cmf_mfi(g)
        rows.append({
            "ticker": tk,
            "volume_reliable": v["reliable"],
            "nonzero_frac": v["nonzero_frac"],
            "reason": v["reason"],
            "cmf20": cmf_val,
            "mfi14": mfi_val,
        })
    out = pd.DataFrame(rows)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    out.to_csv(out_path, index=False)
    print(f"[volume] {out['volume_reliable'].sum()}/{len(out)} ticker affidabili -> {out_path}")
    return out


if __name__ == "__main__":
    import os
    # Sorgente: file LOCALE fresco (come fetch_data/score_generator). Evita il
    # download da raw.githubusercontent/main, che e' (1) fragile (IncompleteRead su
    # file da MB) e (2) stale (classifica su dati del branch main, non su quelli
    # appena rigenerati). Download remoto solo come fallback estremo.
    local = "data/mib_data.csv"
    if os.path.exists(local):
        px = pd.read_csv(local)
    else:
        import urllib.request, io
        base = "https://raw.githubusercontent.com/newspapergram-dot/mib-data/refs/heads/main/data/"
        px = pd.read_csv(io.StringIO(
            urllib.request.urlopen(base+"mib_data.csv", timeout=60).read().decode("utf-8","replace")))
    volume_quality_report(px)
