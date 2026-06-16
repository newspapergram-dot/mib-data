"""patterns.py — Riconoscimento algoritmico pattern grafici e figure di continuazione."""
import numpy as np
import pandas as pd
from indicators import adx, rsi_wilder, atr_wilder


def _slope(series: pd.Series) -> float:
    y = series.dropna().values
    if len(y) < 3:
        return 0.0
    x = np.arange(len(y))
    return float(np.polyfit(x, y, 1)[0] / (np.mean(y) + 1e-9))


def _swing_points(series: pd.Series, order: int = 3):
    highs, lows = [], []
    v = series.values
    for i in range(order, len(v) - order):
        win = v[i - order:i + order + 1]
        if v[i] == win.max():
            highs.append((i, v[i]))
        if v[i] == win.min():
            lows.append((i, v[i]))
    return highs, lows


def detect_patterns(g: pd.DataFrame) -> dict:
    out = {"trend": None, "trend_strength": None, "structure": None,
           "continuation": None, "breakout": None, "pullback": False,
           "rsi_divergence": None, "bollinger": None, "notes": ""}
    if len(g) < 60:
        out["notes"] = "storia insufficiente"
        return out
    high, low, close = g["high"], g["low"], g["close"]
    vol = g["volume"] if "volume" in g.columns else None
    cur = close.iloc[-1]

    adf = adx(high, low, close)
    adx_v = adf["adx"].iloc[-1]
    pdi, mdi = adf["plus_di"].iloc[-1], adf["minus_di"].iloc[-1]
    if adx_v >= 25:
        out["trend"] = "rialzista" if pdi > mdi else "ribassista"
        out["trend_strength"] = "forte" if adx_v >= 40 else "moderato"
    else:
        out["trend"] = "laterale"; out["trend_strength"] = "debole"

    hi, lo = _swing_points(close.tail(40), order=3)
    if len(hi) >= 2 and len(lo) >= 2:
        hh, hl = hi[-1][1] > hi[-2][1], lo[-1][1] > lo[-2][1]
        lh, ll = hi[-1][1] < hi[-2][1], lo[-1][1] < lo[-2][1]
        if hh and hl: out["structure"] = "HH-HL (rialzista)"
        elif lh and ll: out["structure"] = "LH-LL (ribassista)"
        else: out["structure"] = "mista"

    sma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    bb_up, bb_dn = sma20 + 2 * std20, sma20 - 2 * std20
    bb_width = ((bb_up - bb_dn) / sma20).iloc[-1]
    bb_width_ma = ((bb_up - bb_dn) / sma20).rolling(60).mean().iloc[-1]
    if bb_width < 0.7 * bb_width_ma: out["bollinger"] = "squeeze (compressione volatilita')"
    elif cur > bb_up.iloc[-1]: out["bollinger"] = "walk upper band (forza)"
    elif cur < bb_dn.iloc[-1]: out["bollinger"] = "walk lower band (debolezza)"
    else: out["bollinger"] = "dentro le bande"

    dist_sma20 = (cur / sma20.iloc[-1] - 1) * 100
    if out["trend"] == "rialzista" and -3 <= dist_sma20 <= 2:
        out["pullback"] = True

    atr = atr_wilder(high, low, close).iloc[-1]
    recent = g.tail(10)
    rng_atr = (recent["high"].max() - recent["low"].min()) / atr if atr > 0 else 99
    impulse_before = (close.iloc[-11] / close.iloc[-31] - 1) * 100 if len(close) > 31 else 0
    if impulse_before > 8 and rng_atr < 3.5:
        out["continuation"] = "flag/pennant rialzista (consolidamento dopo impulso)"
    elif impulse_before < -8 and rng_atr < 3.5:
        out["continuation"] = "flag/pennant ribassista"

    hi20, lo20 = _swing_points(close.tail(30), order=2)
    if len(hi20) >= 2 and len(lo20) >= 2:
        sh, sl = hi20[-1][1] - hi20[-2][1], lo20[-1][1] - lo20[-2][1]
        if abs(sh) < atr and sl > 0:
            out["continuation"] = (out["continuation"] or "") + " | ascending triangle"
        elif sh < 0 and abs(sl) < atr:
            out["continuation"] = (out["continuation"] or "") + " | descending triangle"

    range_high = g["high"].iloc[-21:-1].max()
    range_low = g["low"].iloc[-21:-1].min()
    if cur > range_high:
        vol_conf = ""
        if vol is not None and vol.tail(20).mean() > 0:
            vr = vol.iloc[-1] / vol.tail(20).mean()
            vol_conf = f" (vol {vr:.1f}x)" if vr >= 1.2 else f" (vol debole {vr:.1f}x)"
        out["breakout"] = f"breakout rialzista sopra {range_high:.2f}{vol_conf}"
    elif cur < range_low:
        out["breakout"] = f"breakdown sotto {range_low:.2f}"

    rsi = rsi_wilder(close)
    rsi_hi, _ = _swing_points(rsi.tail(40), order=3)
    px_hi, _ = _swing_points(close.tail(40), order=3)
    if len(rsi_hi) >= 2 and len(px_hi) >= 2:
        if px_hi[-1][1] > px_hi[-2][1] and rsi_hi[-1][1] < rsi_hi[-2][1]:
            out["rsi_divergence"] = "bearish (prezzo nuovo max, RSI no)"
    _, rsi_lo = _swing_points(rsi.tail(40), order=3)
    _, px_lo = _swing_points(close.tail(40), order=3)
    if len(rsi_lo) >= 2 and len(px_lo) >= 2:
        if px_lo[-1][1] < px_lo[-2][1] and rsi_lo[-1][1] > rsi_lo[-2][1]:
            out["rsi_divergence"] = "bullish (prezzo nuovo min, RSI no)"
    return out


def build_patterns(px: pd.DataFrame, tickers=None, out_path="data/patterns.csv"):
    import os
    if tickers is None:
        tickers = px["ticker"].unique()
    rows = []
    for tk in tickers:
        g = px[px["ticker"] == tk].sort_values("date")
        try:
            p = detect_patterns(g); p["ticker"] = tk; rows.append(p)
        except Exception as e:
            rows.append({"ticker": tk, "notes": f"errore: {e}"})
    cols = ["ticker", "trend", "trend_strength", "structure", "continuation",
            "breakout", "pullback", "rsi_divergence", "bollinger", "notes"]
    out = pd.DataFrame(rows)
    out = out[[c for c in cols if c in out.columns]]
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    out.to_csv(out_path, index=False)
    print(f"[patterns] salvato {out_path}: {len(out)} ticker")
    return out


if __name__ == "__main__":
    import urllib.request, io
    base = "https://raw.githubusercontent.com/newspapergram-dot/mib-data/refs/heads/main/data/"
    px = pd.read_csv(io.StringIO(urllib.request.urlopen(base+"mib_data.csv", timeout=60).read().decode("utf-8","replace")))
    px["date"] = pd.to_datetime(px["date"])
    build_patterns(px)
