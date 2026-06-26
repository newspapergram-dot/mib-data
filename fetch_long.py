"""fetch_long.py — Storico LUNGO (default 2018->oggi) per analisi bear/ciclo completo.

Usa l'API JSON di Yahoo v8 con prezzi AGGIUSTATI (adjclose): su molti anni gli split
(NVDA, AMZN, ...) creano salti nel prezzo grezzo che falserebbero il backtest. Si usa
adjclose come close e si riscalano O/H/L con il fattore adjclose/close (preserva i range
intraday per l'ATR). Scrive un file SEPARATO (data/mib_data_long.csv): NON tocca il
dataset operativo a 14 mesi (data/mib_data.csv).
"""
import time
import numpy as np
import pandas as pd
import requests
from fetch_data import TICKERS
from modules.fmp_source import _BROWSER_HEADERS

START = "2018-01-01"
END = "2026-06-26"
OUT = "data/mib_data_long.csv"


def fetch(symbol, start=START, end=END):
    p1 = int(pd.Timestamp(start).timestamp())
    p2 = int(pd.Timestamp(end).timestamp())
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    try:
        r = requests.get(url, params={"period1": p1, "period2": p2, "interval": "1d"},
                         headers=_BROWSER_HEADERS, timeout=30)
        if r.status_code != 200:
            return None
        res = r.json()["chart"]["result"][0]
        ts = res["timestamp"]
        q = res["indicators"]["quote"][0]
        adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    except Exception as e:
        print(f"[long] {symbol}: {repr(e)[:80]}")
        return None
    df = pd.DataFrame({"date": pd.to_datetime(ts, unit="s").date,
                       "open": q["open"], "high": q["high"], "low": q["low"],
                       "close": q["close"], "volume": q["volume"]})
    if adj is not None:
        df["adj"] = adj
        f = df["adj"] / df["close"]                  # fattore di aggiustamento split+div
        for c in ("open", "high", "low"):
            df[c] = df[c] * f
        df["close"] = df["adj"]
        df = df.drop(columns="adj")
    df = df.dropna(subset=["close"])
    if df.empty:
        return None
    df["ticker"] = symbol
    df["date"] = df["date"].astype(str)
    return df[["ticker", "date", "open", "high", "low", "close", "volume"]]


if __name__ == "__main__":
    frames, failed = [], []
    for t in TICKERS:
        d = fetch(t)
        if d is None or d.empty:
            failed.append(t); continue
        frames.append(d)
    out = pd.concat(frames, ignore_index=True)
    for c in ["open", "high", "low", "close", "volume"]:
        out[c] = pd.to_numeric(out[c], errors="coerce")
    out = out.dropna(subset=["close"]).drop_duplicates(["ticker", "date"]).sort_values(["ticker", "date"])
    out.to_csv(OUT, index=False)
    print(f"Scritte {len(out)} righe ({out['ticker'].nunique()} ticker) in {OUT}")
    print(f"Range: {out['date'].min()} -> {out['date'].max()} | falliti: {failed}")
