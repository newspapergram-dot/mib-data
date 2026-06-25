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
import re
import time
import random
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


# Header da browser reale: alcune API pubbliche (es. Yahoo v8) rifiutano le
# richieste senza User-Agent. NB: questo serve a interrogare correttamente l'API,
# NON ad aggirare una egress policy: se l'host non e' nell'allowlist del proxy
# aziendale, il CONNECT viene rifiutato (403) a prescindere dagli header.
_BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}


def get_eod_eu_robust(symbol, from_date=None, to_date=None, range_="3mo"):
    """PIANO C per i dati EOD EU: interroga l'API pubblica JSON di Yahoo Finance
    (`query1.finance.yahoo.com/v8/finance/chart/<TICKER>`) con header da browser
    reale, usando il formato ticker Yahoo gia' in uso nel repo (es. 'ISP.MI').

    Approccio: si usa l'endpoint JSON ufficiale (non lo scraping HTML di
    Investing.com/MarketScreener, piu' fragile e spesso vietato dai ToS). Lo
    User-Agent serve perche' Yahoo rifiuta le richieste prive di UA — e' uso
    legittimo dell'API, non un tentativo di eludere controlli.

    Ritorna un DataFrame [ticker,date,open,high,low,close,volume] oppure None.
    Non solleva eccezioni e NON fabbrica dati: in caso di fallimento (incluso il
    403 della egress policy aziendale, che NON e' aggirabile via header) ritorna
    None e logga un avviso, lasciando al chiamante la gestione."""
    if requests is None:
        print(f"[EU-robust] requests non disponibile per {symbol}")
        return None
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {"range": range_, "interval": "1d"}
    try:
        r = requests.get(url, params=params, headers=_BROWSER_HEADERS, timeout=20)
    except Exception as e:
        # Tipico in sandbox: il proxy rifiuta il CONNECT con 403 (host non in allowlist).
        print(f"[EU-robust] {symbol}: rete/proxy non raggiungibile ({repr(e)[:120]})")
        return None
    if r.status_code != 200:
        print(f"[EU-robust] {symbol}: HTTP {r.status_code} (se 403 = egress policy: "
              f"host non in allowlist, non aggirabile via header)")
        return None
    try:
        res = r.json()["chart"]["result"][0]
        ts = res["timestamp"]
        q = res["indicators"]["quote"][0]
        df = pd.DataFrame({
            "date": pd.to_datetime(ts, unit="s").date,
            "open": q["open"], "high": q["high"], "low": q["low"],
            "close": q["close"], "volume": q["volume"],
        })
    except Exception as e:
        print(f"[EU-robust] {symbol}: payload Yahoo non interpretabile ({repr(e)[:120]})")
        return None
    df = df.dropna(subset=["close"])
    if df.empty:
        return None
    df["ticker"] = symbol
    df["date"] = df["date"].astype(str)
    if from_date:
        df = df[df["date"] >= str(from_date)]
    if to_date:
        df = df[df["date"] <= str(to_date)]
    df = df[["ticker", "date", "open", "high", "low", "close", "volume"]]
    return df if not df.empty else None


# Mappa ticker Yahoo -> ISIN usato nelle URL pubbliche di Borsa Italiana.
# Le schede sono indicizzate per ISIN (es. /scheda/IT0000072618.html), non per
# ticker: per i nomi qui assenti la funzione non puo' costruire l'URL e ritorna None.
_BORSAIT_ISIN = {
    "ISP.MI": "IT0000072618",   # Intesa Sanpaolo
    "ENEL.MI": "IT0003128367",  # Enel
    "ENI.MI": "IT0003132476",   # Eni
    "UCG.MI": "IT0005239360",   # UniCredit
    "STMMI.MI": "NL0000226223", # STMicroelectronics
    "G.MI": "IT0000062072",     # Generali
    "TIT.MI": "IT0003497168",   # Telecom Italia
    "SPM.MI": "IT0000068525",   # Saipem
}


def get_eod_eu_borsait(symbol, isin=None, pause=True):
    """PIANO D per i dati EOD EU: parsing della scheda pubblica di Borsa Italiana
    (`https://www.borsaitaliana.it/borsa/azioni/scheda/<ISIN>.html`).

    Fonte: il gestore ufficiale del mercato italiano, che pubblica i prezzi di
    chiusura/riferimento per il pubblico. Si estrae l'ultimo dato giornaliero
    (chiusura/prezzo di riferimento + eventuali O/H/L/volume se presenti in pagina).

    Note oneste:
      - Le schede sono indicizzate per ISIN, non per ticker: serve la mappa
        `_BORSAIT_ISIN` (o passare `isin=`). Per nomi non mappati -> None.
      - `pause=True` inserisce un breve ritardo di CORTESIA (rate-limit) per non
        gravare sul server pubblico: e' buona educazione verso l'host, NON una
        tecnica per eludere bot-detection o l'egress policy del proxy.
      - Rispettare i ToS/robots del sito: uso personale e a basso volume.
      - Non fabbrica dati: su qualsiasi errore ritorna None e logga il motivo
        specifico (incluso '403 Borsa Italiana') per distinguere endpoint vs policy.
    """
    if requests is None:
        print(f"[Borsa Italiana] requests non disponibile per {symbol}")
        return None
    isin = isin or _BORSAIT_ISIN.get(symbol)
    if not isin:
        print(f"[Borsa Italiana] {symbol}: ISIN non mappato -> impossibile costruire l'URL")
        return None
    url = f"https://www.borsaitaliana.it/borsa/azioni/scheda/{isin}.html?lang=it"
    if pause:
        time.sleep(random.uniform(1.0, 2.5))   # cortesia/rate-limit verso il server
    try:
        r = requests.get(url, headers=_BROWSER_HEADERS, timeout=25)
    except Exception as e:
        # In sandbox: il proxy rifiuta il CONNECT (host non in allowlist) -> ProxyError.
        print(f"[Borsa Italiana] {symbol}: rete/proxy non raggiungibile ({repr(e)[:120]})")
        return None
    if r.status_code != 200:
        tag = "403 Borsa Italiana" if r.status_code == 403 else f"HTTP {r.status_code}"
        print(f"[Borsa Italiana] {symbol}: {tag} (403 -> probabile policy/blocco host; "
              f"altri codici -> possibile endpoint/ISIN errato)")
        return None
    html = r.text
    # Parsing difensivo: le schede espongono coppie label/valore in tabella.
    def _num(label):
        m = re.search(label + r"\s*</span>.*?<span[^>]*>\s*([\d\.\,]+)", html,
                      re.IGNORECASE | re.DOTALL)
        if not m:
            m = re.search(label + r".{0,80}?([\d]{1,3}(?:\.\d{3})*,\d+)", html,
                          re.IGNORECASE | re.DOTALL)
        if not m:
            return None
        raw = m.group(1).replace(".", "").replace(",", ".")  # formato IT 1.234,56
        try:
            return float(raw)
        except ValueError:
            return None
    close = _num("Prezzo di Riferimento") or _num("Prezzo Ultimo") or _num("Ultimo Prezzo")
    if close is None:
        print(f"[Borsa Italiana] {symbol}: pagina raggiunta ma prezzo non individuato "
              f"(selettori da adeguare al markup corrente)")
        return None
    row = {
        "ticker": symbol,
        "date": pd.Timestamp.today().strftime("%Y-%m-%d"),
        "open": _num("Apertura"),
        "high": _num("Massimo"),
        "low": _num("Minimo"),
        "close": close,
        "volume": _num("Volume"),
    }
    return pd.DataFrame([row])[["ticker", "date", "open", "high", "low", "close", "volume"]]


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
