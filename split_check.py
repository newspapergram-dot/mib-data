"""
split_check.py — Rilevamento split azionari recenti / anomalie di prezzo.

Doppio rilevatore, perche' uno split puo' manifestarsi in due modi nei dati:
  1. SALTO ANOMALO: se la fonte NON ha aggiustato i prezzi storici, lo split
     1:N produce un crollo improvviso (~ -1/N) in un solo giorno, non dovuto
     al mercato. Lo rileviamo come variazione giornaliera oltre soglia.
  2. DATA NOTA: se splits_calendar.csv (o un dict passato) contiene una data
     di split recente per il ticker, segnaliamo comunque i dati come "da
     verificare" anche se la fonte sembra averli aggiustati, perche' RSI/ADX
     calcolati a cavallo dello split possono restare distorti per alcune sedute.

Output per ticker: dict con flag e motivo, da usare come ESCLUSIONE prudenziale
o come argomento BEAR nel dibattito.
"""
import pandas as pd
import numpy as np


def detect_price_jump(df_ticker, lookback=10, jump_threshold=0.35):
    """
    Rileva un salto giornaliero anomalo (possibile split non aggiustato) nelle
    ultime `lookback` sedute. jump_threshold=0.35 -> variazione >35% in un giorno.
    Una vera notizia societaria raramente muove un large/mid cap oltre il 35%
    intraday; uno split 1:2 (-50%), 1:3 (-66%), 1:10 (-90%) si',  vistosamente.
    Ritorna (bool, dettaglio).
    """
    d = df_ticker.sort_values("date").tail(lookback + 1).copy()
    if len(d) < 2:
        return False, None
    chg = d["close"].pct_change().abs()
    mx = chg.max()
    if mx >= jump_threshold:
        idx = chg.idxmax()
        return True, {"date": str(d.loc[idx, "date"]),
                      "jump_pct": round(float(chg.loc[idx]) * 100, 1)}
    return False, None


# Indici e simboli non-azionari: lo split non si applica, e i salti sono normali
NON_EQUITY_PREFIXES = ("^",)
NON_EQUITY_TICKERS = {"FTSEMIB.MI", "VIX"}

def _is_equity(ticker):
    if ticker.startswith(NON_EQUITY_PREFIXES):
        return False
    if ticker in NON_EQUITY_TICKERS:
        return False
    return True

def split_flag(ticker, df_ticker, split_dates=None, recent_days=15):
    """
    ticker: simbolo
    df_ticker: DataFrame OHLCV di QUEL ticker (colonne date, close, ...)
    split_dates: dict {ticker: 'YYYY-MM-DD'} di split noti (da splits_calendar.csv
                 o inserito a mano). Opzionale.
    recent_days: una data di split entro questa finestra rende i dati "sospetti".

    Ritorna dict:
      {"ticker", "data_reliable" (bool), "reason", "action"}
      action: "ok" | "verify" | "exclude"
    """
    reasons = []
    action = "ok"

    # Rilevatore 1: salto di prezzo anomalo (solo per azioni, non indici/volatilita')
    jumped, jdet = (False, None)
    if _is_equity(ticker):
        jumped, jdet = detect_price_jump(df_ticker)
    if jumped:
        reasons.append(f"salto anomalo {jdet['jump_pct']}% il {jdet['date'][:10]} "
                       f"(possibile split NON aggiustato)")
        action = "exclude"  # dati quasi certamente distorti -> non operare

    # Rilevatore 2: data di split nota recente
    if split_dates and ticker in split_dates:
        try:
            sd = pd.to_datetime(split_dates[ticker])
            last = pd.to_datetime(df_ticker["date"]).max()
            age = (last - sd).days
            if 0 <= age <= recent_days:
                reasons.append(f"split noto il {sd.date()} ({age}g fa): "
                               f"indicatori a cavallo possibilmente distorti")
                if action != "exclude":
                    action = "verify"  # verifica manuale, non esclusione automatica
        except (ValueError, TypeError):
            pass

    reliable = (action == "ok")
    return {"ticker": ticker,
            "data_reliable": reliable,
            "reason": "; ".join(reasons) if reasons else "ok",
            "action": action}


def split_report(px, split_dates=None, out_path="data/split_check.csv"):
    """
    px: DataFrame con tutti i ticker (colonne: ticker, date, close...).
    Scrive un CSV con il flag split per ogni ticker.
    """
    import os
    rows = []
    for tk in px["ticker"].unique():
        g = px[px["ticker"] == tk]
        rows.append(split_flag(tk, g, split_dates=split_dates))
    out = pd.DataFrame(rows)
    if out_path:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        out.to_csv(out_path, index=False)
        n_excl = (out["action"] == "exclude").sum()
        n_ver = (out["action"] == "verify").sum()
        print(f"[split] {n_excl} da escludere, {n_ver} da verificare -> {out_path}")
    return out


if __name__ == "__main__":
    import urllib.request, io
    base = "https://raw.githubusercontent.com/newspapergram-dot/mib-data/refs/heads/main/data/"
    px = pd.read_csv(io.StringIO(urllib.request.urlopen(base+"mib_data.csv", timeout=60).read().decode("utf-8","replace")))
    # Split noti inseribili a mano o da un futuro splits_calendar.csv:
    known_splits = {"TIT.MI": "2026-06-15"}  # split 1:10 annunciato
    split_report(px, split_dates=known_splits)
