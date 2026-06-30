#!/usr/bin/env python3
"""fetch_sp500.py — Scarica dati OHLCV 2018-2026 per un universo S&P 500 rappresentativo.

Usa get_eod_eu_robust (Yahoo Finance v8 JSON, query1.finance.yahoo.com) che funziona
attraverso il proxy aziendale (testato). Non usa yfinance che richiede host aggiuntivi
bloccati dal proxy.

Universo: ~77 titoli multi-settore S&P 500 liquidi con continuità 2018-2026 + ^GSPC.
Output: data/sp500_data_long.csv (stesso schema di mib_data_long.csv).
"""
import sys, time
import pandas as pd

sys.path.insert(0, ".")
from modules.fmp_source import get_eod_eu_robust

START = "2018-01-01"
END   = "2026-06-26"
PAUSE = 0.5   # secondi tra richieste (cortesia all'API)

TICKERS = [
    # Indice (regime gate — obbligatorio per backtest gated)
    "^GSPC",
    # Technology (16)
    "AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN", "TSLA",
    "CRM",  "ADBE", "INTC", "AMD",  "QCOM", "TXN",  "ORCL", "CSCO", "AVGO",
    # Financials (11)
    "JPM",  "BAC",  "WFC",  "GS",   "MS",   "BLK",
    "V",    "MA",   "AXP",  "C",    "SCHW",
    # Healthcare (10)
    "JNJ",  "LLY",  "PFE",  "ABBV", "UNH",  "MRK",
    "TMO",  "DHR",  "ABT",  "BMY",
    # Consumer Staples (6)
    "PG",   "KO",   "PEP",  "WMT",  "COST", "CL",
    # Consumer Discretionary (6)
    "MCD",  "HD",   "NKE",  "SBUX", "TGT",  "LOW",
    # Communication Services (4)
    "DIS",  "NFLX", "T",    "VZ",
    # Energy (6)
    "XOM",  "CVX",  "COP",  "SLB",  "EOG",  "MPC",
    # Industrials (8)
    "BA",   "GE",   "MMM",  "HON",  "UPS",  "CAT",  "LMT",  "RTX",
    # Materials (4)
    "LIN",  "APD",  "NEM",  "FCX",
    # Utilities (3)
    "NEE",  "DUK",  "SO",
    # Real Estate (2)
    "AMT",  "PLD",
]


def main():
    out_path = "data/sp500_data_long.csv"
    frames = []
    missing = []
    n = len(TICKERS)

    print(f"Downloading {n} tickers ({START} -> {END}) ...")
    for i, tk in enumerate(TICKERS, 1):
        print(f"  [{i:02d}/{n}] {tk}", end="", flush=True)
        df = get_eod_eu_robust(tk, from_date=START, to_date=END)
        if df is None or df.empty:
            print("  WARN: nessun dato, skip")
            missing.append(tk)
        else:
            print(f"  {len(df)} barre  {df.date.min()} -> {df.date.max()}")
            frames.append(df)
        time.sleep(PAUSE)

    if not frames:
        print("ERROR: nessun dato scaricato")
        sys.exit(1)

    out = pd.concat(frames, ignore_index=True)
    out["date"] = pd.to_datetime(out["date"])
    out = out.sort_values(["ticker", "date"]).reset_index(drop=True)

    # report
    n_tickers = out["ticker"].nunique()
    bars_per = out.groupby("ticker").size()
    print(f"\nCopertura: {n_tickers} ticker | {len(out):,} righe")
    print(f"Barre per ticker: min={bars_per.min()} median={bars_per.median():.0f} max={bars_per.max()}")
    if missing:
        print(f"WARN ticker mancanti ({len(missing)}): {missing}")
    if "^GSPC" not in out["ticker"].values:
        print("ERROR: ^GSPC mancante — il regime gate non funzionera'")
        sys.exit(1)
    gspc_n = (out["ticker"] == "^GSPC").sum()
    print(f"^GSPC: {gspc_n} barre ok")

    out.to_csv(out_path, index=False)
    print(f"Salvato: {out_path} ({len(out):,} righe, {n_tickers} ticker)")


if __name__ == "__main__":
    main()
