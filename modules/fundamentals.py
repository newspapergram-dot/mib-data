"""
fundamentals.py — Recupero fondamentali con strategia ASIMMETRICA USA/EU.

Esito della ricerca (giugno 2026): NON esiste una fonte gratuita unica e
affidabile che copra bene sia USA sia Europa. Quindi:

  - USA  -> dati gratuiti ottimi. Fonte primaria Finnhub (P/E, EPS, mktcap,
            earnings date, consenso analisti), API key gratuita. Fallback yfinance.
  - EU   -> nessuna fonte gratuita affidabile. Si usa yfinance come UNICO ripiego,
            ma con VALIDAZIONE severa: se i dati sono incoerenti o stantii,
            il modulo li SCARTA e restituisce data_reliable=False invece di
            propagare numeri sbagliati (lezione MB.MI: meglio "non affidabile"
            che un P/E vecchio spacciato per fresco).

Principio guida: mai un fondamentale "con l'aria di essere fresco" se non lo e'.
Ogni valore esce accompagnato da fonte, data del dato, e flag di affidabilita'.

Dipendenze: requests (per Finnhub), yfinance (gia' usata nella pipeline).
API key Finnhub: gratuita su finnhub.io, va messa in env FINNHUB_API_KEY
(in GitHub Actions: repo secret). Se assente, il ramo USA usa solo yfinance.
"""
import os
import time
import datetime
import math

# ---------------------------------------------------------------------------
# Classificazione mercato (coerente con regime_filter.market_of)
# ---------------------------------------------------------------------------
def market_of(ticker):
    if ticker.endswith(".MI"):
        return "IT"
    if ticker.endswith(".PA") or ticker.endswith(".AS"):
        return "FR"
    return "US"

def is_european(ticker):
    return market_of(ticker) in ("IT", "FR")

# ---------------------------------------------------------------------------
# VALIDAZIONE — il cuore del modulo. Boccia i dati sospetti.
# ---------------------------------------------------------------------------
# Range di sanita': valori fuori da qui sono quasi certamente errati/stantii.
SANITY = {
    "pe":        (0.0, 200.0),    # P/E plausibile (negativo gestito a parte)
    "forward_pe":(0.0, 200.0),
    "eps":       (-1000.0, 5000.0),
    "market_cap":(1e7, 1e13),     # 10M - 10.000 mld
}

def _num(x):
    """Converte in float gestendo None/NaN/stringhe vuote."""
    if x is None:
        return None
    try:
        v = float(x)
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    except (ValueError, TypeError):
        return None

def _in_range(val, key):
    lo, hi = SANITY[key]
    return val is not None and lo <= val <= hi

def validate_fundamentals(f, price_now=None, max_age_days=120):
    """
    f: dict grezzo con campi pe, forward_pe, eps, market_cap, currency,
       price_asof (prezzo a cui il dato fa riferimento, se noto), source, asof_date.
    price_now: prezzo corrente reale (dalla pipeline mib_data) per cross-check.
    max_age_days: oltre questa eta' il dato e' considerato stantio.

    Ritorna (reliable: bool, reasons: list[str]). Non modifica f.
    """
    reasons = []

    # 1. almeno P/E o EPS devono esserci e essere nel range
    pe = _num(f.get("pe"))
    eps = _num(f.get("eps"))
    if pe is None and eps is None:
        reasons.append("nessun P/E ne EPS disponibile")
    if pe is not None and not _in_range(pe, "pe"):
        reasons.append(f"P/E fuori range plausibile ({pe})")
    if eps is not None and not _in_range(eps, "eps"):
        reasons.append(f"EPS fuori range plausibile ({eps})")

    # 2. market cap plausibile (se presente)
    mc = _num(f.get("market_cap"))
    if mc is not None and not _in_range(mc, "market_cap"):
        reasons.append(f"market cap implausibile ({mc})")

    # 3. cross-check prezzo: se il dato porta un price_asof e differisce troppo
    #    dal prezzo reale corrente, il fondamentale e' probabilmente STANTIO
    #    (esattamente il caso MB.MI: dato a 20.35 mentre il prezzo reale e 26.29)
    pa = _num(f.get("price_asof"))
    if price_now is not None and pa is not None and pa > 0:
        drift = abs(pa - price_now) / price_now
        if drift > 0.15:  # oltre 15% di scarto = dato non attuale
            reasons.append(f"prezzo di riferimento del dato ({pa}) lontano "
                           f"dal prezzo reale ({price_now}): scarto {drift*100:.0f}% -> dato stantio")

    # 4. coerenza interna P/E ~= price / eps (se ho tutti e tre)
    if pe is not None and eps is not None and eps > 0 and price_now:
        implied_pe = price_now / eps
        if implied_pe > 0 and abs(implied_pe - pe) / pe > 0.30:
            reasons.append(f"P/E dichiarato ({pe:.1f}) incoerente con prezzo/EPS "
                           f"({implied_pe:.1f}): possibile disallineamento")

    # 5. eta' del dato
    asof = f.get("asof_date")
    if asof:
        try:
            d = datetime.date.fromisoformat(str(asof)[:10])
            age = (datetime.date.today() - d).days
            if age > max_age_days:
                reasons.append(f"dato vecchio ({age}g, soglia {max_age_days}g)")
        except (ValueError, TypeError):
            pass

    return (len(reasons) == 0), reasons

# ---------------------------------------------------------------------------
# FONTE USA — Finnhub (gratuito) con fallback yfinance
# ---------------------------------------------------------------------------
def _finnhub_get(path, params):
    import requests
    key = os.environ.get("FINNHUB_API_KEY", "")
    if not key:
        return None
    params = dict(params); params["token"] = key
    try:
        r = requests.get(f"https://finnhub.io/api/v1/{path}", params=params, timeout=20)
        if r.status_code == 200:
            return r.json()
    except Exception:
        return None
    return None

def fetch_us(ticker):
    """Fondamentali USA via Finnhub (primario). Ritorna dict grezzo + analisti."""
    out = {"ticker": ticker, "source": "finnhub", "asof_date": datetime.date.today().isoformat(),
           "pe": None, "forward_pe": None, "eps": None, "market_cap": None,
           "revenue": None, "currency": "USD", "next_earnings": None,
           "analyst_consensus": None, "price_asof": None}

    metrics = _finnhub_get("stock/metric", {"symbol": ticker, "metric": "all"})
    if metrics and "metric" in metrics:
        m = metrics["metric"]
        out["pe"] = _num(m.get("peTTM"))
        out["forward_pe"] = _num(m.get("peExclExtraAnnual"))
        out["eps"] = _num(m.get("epsTTM"))
        out["market_cap"] = _num(m.get("marketCapitalization"))
        if out["market_cap"]:
            out["market_cap"] *= 1e6  # Finnhub da' in milioni
        out["revenue"] = _num(m.get("revenuePerShareTTM"))

    # Consenso analisti (punto di forza Finnhub per USA)
    rec = _finnhub_get("stock/recommendation", {"symbol": ticker})
    if rec and isinstance(rec, list) and rec:
        latest = rec[0]
        out["analyst_consensus"] = {
            "buy": latest.get("buy"), "hold": latest.get("hold"),
            "sell": latest.get("sell"), "strongBuy": latest.get("strongBuy"),
            "strongSell": latest.get("strongSell"), "period": latest.get("period"),
        }

    # Data prossima trimestrale
    cal = _finnhub_get("calendar/earnings", {"symbol": ticker})
    if cal and cal.get("earningsCalendar"):
        future = [e for e in cal["earningsCalendar"] if e.get("date","") >= datetime.date.today().isoformat()]
        if future:
            out["next_earnings"] = sorted(future, key=lambda e: e["date"])[0]["date"]

    return out

# ---------------------------------------------------------------------------
# FONTE EU — yfinance UNICO ripiego, con validazione severa a valle
# ---------------------------------------------------------------------------
def fetch_eu(ticker):
    """
    Fondamentali EU via yfinance (unico ripiego gratuito).
    NB: i dati vanno SEMPRE passati a validate_fundamentals() prima di fidarsi.
    """
    out = {"ticker": ticker, "source": "yfinance", "asof_date": datetime.date.today().isoformat(),
           "pe": None, "forward_pe": None, "eps": None, "market_cap": None,
           "revenue": None, "currency": "EUR", "next_earnings": None,
           "analyst_consensus": None, "price_asof": None}
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info or {}
        out["pe"] = _num(info.get("trailingPE"))
        out["forward_pe"] = _num(info.get("forwardPE"))
        out["eps"] = _num(info.get("trailingEps"))
        out["market_cap"] = _num(info.get("marketCap"))
        out["revenue"] = _num(info.get("totalRevenue"))
        out["currency"] = info.get("currency", "EUR")
        # prezzo a cui yfinance aggancia il dato: serve al cross-check anti-stantio
        out["price_asof"] = _num(info.get("currentPrice") or info.get("regularMarketPrice"))
        # consenso analisti: spesso assente/parziale per EU -> non garantito
        rk = info.get("recommendationKey")
        if rk and rk != "none":
            out["analyst_consensus"] = {"recommendationKey": rk,
                                        "numberOfAnalystOpinions": info.get("numberOfAnalystOpinions")}
    except Exception as e:
        out["_error"] = f"{type(e).__name__}: {str(e)[:100]}"
    return out

# ---------------------------------------------------------------------------
# ORCHESTRATORE — sceglie la fonte per mercato, valida, restituisce esito onesto
# ---------------------------------------------------------------------------
def get_fundamentals(ticker, price_now=None, earnings_date_from_pipeline=None):
    """
    API principale del modulo.
    ticker: simbolo (es. 'GS', 'MB.MI')
    price_now: prezzo corrente reale dalla pipeline (mib_data), per cross-check.
    earnings_date_from_pipeline: data trimestrale gia' nota da earnings_calendar.csv
        (fonte piu' affidabile della next_earnings dell'API per i titoli EU).

    Ritorna dict con: tutti i campi + 'data_reliable' (bool) + 'reliability_notes'.
    """
    mkt = market_of(ticker)
    raw = fetch_us(ticker) if mkt == "US" else fetch_eu(ticker)

    # la data trimestrale della pipeline (yfinance earnings_calendar.csv) ha
    # precedenza: e' gia' validata nel flusso esistente
    if earnings_date_from_pipeline:
        raw["next_earnings"] = earnings_date_from_pipeline

    reliable, reasons = validate_fundamentals(raw, price_now=price_now)
    raw["data_reliable"] = reliable
    raw["reliability_notes"] = "; ".join(reasons) if reasons else "ok"
    # i titoli EU partono con una nota di cautela strutturale anche se validi
    if mkt in ("IT", "FR") and reliable:
        raw["reliability_notes"] = "ok (fonte EU yfinance: affidabilita' strutturalmente inferiore, verificare se critico)"
    return raw

def fundamentals_summary_line(f):
    """Riga sintetica leggibile per il report / dibattito."""
    if not f.get("data_reliable"):
        return f"{f['ticker']}: fondamentali NON affidabili ({f['reliability_notes']}) -> esclusi dall'analisi"
    pe = f.get("pe"); fpe = f.get("forward_pe"); eps = f.get("eps")
    parts = []
    if pe is not None: parts.append(f"P/E {pe:.1f}")
    if fpe is not None: parts.append(f"fwd P/E {fpe:.1f}")
    if eps is not None: parts.append(f"EPS {eps:.2f}")
    if f.get("next_earnings"): parts.append(f"trimestrale {f['next_earnings']}")
    cons = f.get("analyst_consensus")
    if cons:
        if "recommendationKey" in cons:
            parts.append(f"consenso {cons['recommendationKey']}")
        elif cons.get("buy") is not None:
            parts.append(f"analisti B{cons.get('strongBuy',0)+cons.get('buy',0)}/H{cons.get('hold',0)}/S{cons.get('sell',0)+cons.get('strongSell',0)}")
    src = f.get("source")
    return f"{f['ticker']}: " + ", ".join(parts) + f"  [fonte {src}]"



# ---------------------------------------------------------------------------
# EXPORT CSV
# ---------------------------------------------------------------------------
def export_fundamentals_csv(tickers, price_data=None, earnings_data=None, out_path="data/fundamentals.csv"):
    """
    Genera CSV con i fondamentali validati per una lista di ticker.
    price_data: dict {ticker: prezzo_corrente} per cross-check (dalla pipeline mib_data).
    earnings_data: dict {ticker: data_prossima_trimestrale} (da earnings_calendar.csv).
    """
    import os
    import csv
    rows = []
    for t in tickers:
        price = price_data.get(t) if price_data else None
        earn_date = earnings_data.get(t) if earnings_data else None
        f = get_fundamentals(t, price_now=price, earnings_date_from_pipeline=earn_date)
        rows.append({
            "ticker": f.get("ticker"),
            "source": f.get("source"),
            "pe": f.get("pe"),
            "forward_pe": f.get("forward_pe"),
            "eps": f.get("eps"),
            "market_cap": f.get("market_cap"),
            "revenue": f.get("revenue"),
            "currency": f.get("currency"),
            "next_earnings": f.get("next_earnings"),
            "data_reliable": f.get("data_reliable"),
            "reliability_notes": f.get("reliability_notes"),
            "analyst_consensus": str(f.get("analyst_consensus")) if f.get("analyst_consensus") else "",
            "asof_date": f.get("asof_date"),
        })
    if out_path:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", newline="") as csvf:
            w = csv.DictWriter(csvf, fieldnames=rows[0].keys() if rows else [])
            w.writeheader()
            w.writerows(rows)
        print(f"[fundamentals] {len(rows)} ticker scritti -> {out_path}")
    return rows


if __name__ == "__main__":
    import sys
    import pandas as pd
    
    # Se lanciato da workflow: leggi i dati della pipeline e genera il CSV
    if len(sys.argv) > 1 and sys.argv[1] == "--workflow":
        try:
            px = pd.read_csv("mib_data.csv")
            ec = pd.read_csv("earnings_calendar.csv") if os.path.exists("earnings_calendar.csv") else pd.DataFrame()
            price_map = {t: float(px[px["ticker"]==t]["close"].iloc[-1]) 
                        for t in px["ticker"].unique() if len(px[px["ticker"]==t]) > 0}
            earn_map = {r["ticker"]: r["next_earnings_date"] 
                       for _, r in ec.iterrows() if pd.notna(r.get("next_earnings_date"))}
            export_fundamentals_csv(list(price_map.keys()), price_data=price_map, 
                                   earnings_data=earn_map, out_path="data/fundamentals.csv")
        except Exception as e:
            print(f"[fundamentals] Errore workflow: {e}")
        sys.exit(0)
    
    # Altrimenti: test offline della VALIDAZIONE (non richiede rete): e' la parte critica.
    print("=== Test validazione (caso MB.MI stantio reale) ===")
    mb_stale = {"ticker":"MB.MI","source":"yfinance","pe":14.7,"eps":1.271,
                "market_cap":1.7e10,"price_asof":20.35,"asof_date":"2026-05-09"}
    rel, notes = validate_fundamentals(mb_stale, price_now=26.29)
    print(f"  MB.MI dato a 20.35 vs prezzo reale 26.29 -> affidabile={rel}")
    for n in notes: print(f"    - {n}")

    print()
    print("=== Test validazione (caso GS fresco coerente) ===")
    gs_ok = {"ticker":"GS","source":"finnhub","pe":16.97,"eps":55.39,
             "market_cap":3.0e11,"price_asof":1099.0,"asof_date":datetime.date.today().isoformat()}
    rel, notes = validate_fundamentals(gs_ok, price_now=1099.14)
    print(f"  GS dato coerente -> affidabile={rel}  note={notes}")

    print()
    print("=== Test validazione (P/E assurdo) ===")
    junk = {"ticker":"XX","pe":9999,"eps":None,"asof_date":datetime.date.today().isoformat()}
    rel, notes = validate_fundamentals(junk, price_now=10.0)
    print(f"  P/E 9999 -> affidabile={rel}")
    for n in notes: print(f"    - {n}")
