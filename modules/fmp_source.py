"""fmp_source.py — Fallback dati via Financial Modeling Prep (FMP).

Motivazione (Run #2, 2026-06-25): nell'ambiente sandbox yfinance e' bloccato dal
proxy (HTTP 403 sul CONNECT verso Yahoo) e la fonte finnhub restituisce P/E/EPS
vuoti per i big USA. FMP funziona ed e' qui usato come sorgente di ripiego per:
  - prezzi EOD (OHLCV)            -> get_eod()
  - fondamentali TTM (P/E, EPS..) -> get_fundamentals()

Richiede la variabile d'ambiente FMP_API_KEY. Se assente o se la rete non e'
disponibile, le funzioni ritornano None senza sollevare eccezioni: il chiamante
deve gestire il fallback in modo grazioso.

NB sui piani FMP: gli endpoint con filtro date e i mercati EU (.MI/.PA) possono
essere riservati ai piani superiori (lower-tier: US ok, EU gated). In tal caso
la funzione ritorna None per quel simbolo.
"""
import os
import pandas as pd

try:
    import requests
except Exception:  # requests assente
    requests = None

BASE = "https://financialmodelingprep.com/stable"


def _key():
    return os.environ.get("FMP_API_KEY")


def _get(path, params=None):
    if requests is None or not _key():
        return None
    params = dict(params or {})
    params["apikey"] = _key()
    try:
        r = requests.get(f"{BASE}/{path}", params=params, timeout=20)
        if r.status_code != 200:
            return None
        data = r.json()
        return data if data else None
    except Exception:
        return None


def get_eod(symbol, from_date, to_date):
    """Barre EOD OHLCV per `symbol` in [from_date, to_date].
    Ritorna un DataFrame [ticker,date,open,high,low,close,volume] o None."""
    data = _get("historical-price-eod/full",
                {"symbol": symbol, "from": from_date, "to": to_date})
    if not data:
        return None
    df = pd.DataFrame(data)
    cols = {"open", "high", "low", "close", "volume", "date"}
    if not cols.issubset(df.columns):
        return None
    df["ticker"] = symbol
    return df[["ticker", "date", "open", "high", "low", "close", "volume"]]


def get_eod_eu(symbol, from_date=None, to_date=None):
    """Sblocca i mercati EU (.MI/.PA/...) con una catena di ripiego pulita:
       1) FMP nativo (get_eod)              -- se il piano copre l'exchange EU
       2) stooq via volume_tools            -- RIUSO di fetch_stooq_fallback (no duplicazione)
    Ritorna un DataFrame [ticker,date,open,high,low,close,volume] o None se tutte
    le fonti sono irraggiungibili (es. egress policy che blocca yahoo/stooq, o
    piano FMP che esclude i listini EU). Non solleva eccezioni."""
    df = get_eod(symbol, from_date, to_date)            # 1) FMP nativo
    if df is not None and not df.empty:
        return df
    try:                                                # 2) stooq (riuso del tool esistente)
        from volume_tools import fetch_stooq_fallback
    except Exception:
        return None
    sq = fetch_stooq_fallback(symbol)
    if sq is None or sq.empty:
        return None
    sq = sq.reset_index().rename(columns={
        "Date": "date", "Open": "open", "High": "high",
        "Low": "low", "Close": "close", "Volume": "volume"})
    sq["ticker"] = symbol
    keep = [c for c in ["ticker", "date", "open", "high", "low", "close", "volume"] if c in sq.columns]
    out = sq[keep]
    if from_date:
        out = out[out["date"].astype(str) >= str(from_date)]
    if to_date:
        out = out[out["date"].astype(str) <= str(to_date)]
    return out if not out.empty else None


def get_fundamentals(symbol):
    """P/E, EPS, market cap, revenue (TTM) per `symbol`. Dict o None.
    Combina metrics-ratios-ttm (P/E, EPS, P/S) e key-metrics-ttm (market cap)."""
    ratios = _get("ratios-ttm", {"symbol": symbol})
    kmet = _get("key-metrics-ttm", {"symbol": symbol})
    if not ratios:
        return None
    r = ratios[0]
    pe = r.get("priceToEarningsRatioTTM")
    eps = r.get("netIncomePerShareTTM")
    ps = r.get("priceToSalesRatioTTM")
    mc = (kmet[0].get("marketCap") if kmet else None)
    rev = (mc / ps) if (mc and ps) else None
    plausible = bool(pe and 0 < pe < 100)
    return {
        "ticker": symbol, "source": "fmp", "pe": pe, "forward_pe": None,
        "eps": eps, "market_cap": mc, "revenue": rev, "currency": "USD",
        "data_reliable": plausible,
        "reliability_notes": ("ok (fonte FMP TTM)" if plausible
                              else f"P/E fuori range plausibile ({pe})"),
    }
