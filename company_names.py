"""company_names.py — Mappa ticker -> nome azienda, per rendere i consigli operativi cercabili.

Fonti (in ordine): SEC entity (data/fundamentals_pit.csv, USA), Yahoo v8 meta longName/shortName
(EU e mancanti). Cache su data/ticker_names.csv per non rifare le chiamate ogni sessione.
"""
import os
import re
import csv

CACHE = "data/ticker_names.csv"

# Nomi indici/ETF (non hanno una "azienda"): etichette leggibili.
_STATIC = {
    "^GSPC": "S&P 500", "^NDX": "Nasdaq 100", "^VIX": "VIX (volatilita')",
    "FTSEMIB.MI": "FTSE MIB", "^FCHI": "CAC 40", "^STOXX50E": "Euro Stoxx 50",
    "SPY": "SPDR S&P 500 ETF", "XLF": "Financials ETF", "XLE": "Energy ETF",
    "XLK": "Technology ETF", "XLV": "Health Care ETF", "XLY": "Cons. Discretionary ETF",
    "XLP": "Cons. Staples ETF", "XLU": "Utilities ETF", "XLI": "Industrials ETF",
    "XLB": "Materials ETF", "XLRE": "Real Estate ETF", "XLC": "Communication ETF",
}


def _load_cache():
    m = {}
    if os.path.exists(CACHE):
        with open(CACHE, newline="") as f:
            for r in csv.DictReader(f):
                m[r["ticker"]] = r["name"]
    return m


def _save_cache(m):
    os.makedirs("data", exist_ok=True)
    with open(CACHE, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ticker", "name"])
        for tk in sorted(m):
            w.writerow([tk, m[tk]])


def _from_sec():
    m = {}
    for path in ("data/fundamentals_pit.csv",):
        if os.path.exists(path):
            with open(path, newline="") as f:
                for r in csv.DictReader(f):
                    ent = (r.get("entity") or "").strip()
                    if ent and ent != r["ticker"]:
                        m[r["ticker"]] = _titlecase(ent)
    return m


def _titlecase(s):
    """SEC scrive in MAIUSCOLO (MICROSOFT CORPORATION) -> Title Case leggibile.
    Rimuove anche il suffisso di stato di incorporazione (es. 'Inc /De' -> 'Inc'),
    un artefatto del filing SEC senza valore informativo per l'utente."""
    s = s.title() if s.isupper() else s
    return re.sub(r"\s*/\s*[A-Za-z]{2,3}$", "", s).strip()


def _from_yahoo(tickers):
    try:
        import requests
        from modules.fmp_source import _BROWSER_HEADERS
    except Exception:
        return {}
    out = {}
    for tk in tickers:
        try:
            r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{tk}",
                             params={"range": "5d", "interval": "1d"},
                             headers=_BROWSER_HEADERS, timeout=15)
            meta = r.json()["chart"]["result"][0]["meta"]
            name = meta.get("longName") or meta.get("shortName")
            if name:
                out[tk] = name.strip()
        except Exception:
            continue
    return out


def resolve(tickers, refresh_missing=True):
    """Ritorna {ticker: nome}. Usa cache; per i mancanti prova SEC poi Yahoo (se refresh)."""
    cache = _load_cache()
    names = dict(_STATIC)
    names.update(_from_sec())
    names.update(cache)              # la cache ha precedenza (gia' risolti/curati)
    missing = [t for t in tickers if t not in names]
    if missing and refresh_missing:
        fetched = _from_yahoo(missing)
        names.update(fetched)
        cache.update({k: v for k, v in names.items() if k in tickers})
        _save_cache(cache)
    return {t: names.get(t, t) for t in tickers}


def name(ticker):
    return resolve([ticker]).get(ticker, ticker)


if __name__ == "__main__":
    import sys
    # Risolve l'intero universo operativo e popola la cache.
    try:
        from fetch_data import TICKERS
        universe = TICKERS
    except Exception:
        universe = sys.argv[1:]
    res = resolve(universe)
    for tk in universe:
        print(f"{tk:12s} {res.get(tk, tk)}")
    print(f"\n[names] {len(res)} ticker risolti -> {CACHE}")
