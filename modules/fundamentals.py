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

SCREENING QUALITY/VALUE (esteso): 9 criteri richiesti dall'operatore.
  P/E<20, PEG<1, EPS up 5Y, net margin>=10%, OCF margin>=30%, current ratio>=1,
  cash/LT-debt>=1.5, insider buying, insider ownership>=10%.
  Filosofia: SOFT SCORING, non hard gate. Ogni criterio produce un argomento
  BULL (passato) o BEAR (fallito) per debate.py; NON e' un veto, finche' non
  sara' backtestato in backtest_v3.py. Metriche non recuperabili a costo zero
  restituiscono None + nota onesta (mai un PEG calcolato su crescita finta).
  Esenzione settoriale: per i finanziari (banche/assicurazioni) OCF margin,
  current ratio e cash/LT-debt sono N/A (metriche non sensate per il settore),
  non un fallimento — salva MB.MI e GS da esclusioni insensate.

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

# ===========================================================================
# SCREENING QUALITY/VALUE — i 9 criteri operatore. SOFT SCORING, non gate.
# ===========================================================================
# Soglie operative (modificabili in un punto solo).
SCREEN_THRESHOLDS = {
    "pe_max":            20.0,   # P/E < 20
    "peg_max":           1.0,    # PEG < 1
    "net_margin_min":    0.10,   # net profit margin >= 10%
    "ocf_margin_min":    0.30,   # operating cash flow margin >= 30%
    "current_ratio_min": 1.0,    # current ratio >= 1
    "cash_ltdebt_min":   1.5,    # cash / long-term debt >= 1.5
    "insider_own_min":   0.10,   # insider ownership >= 10%
}

# Parole chiave per riconoscere un titolo finanziario (settore in cui OCF margin,
# current ratio e cash/LT-debt NON sono metriche sensate -> N/A, non fallimento).
_FINANCE_KEYWORDS = (
    "bank", "banca", "banc", "insurance", "assicur", "financial services",
    "capital markets", "asset management", "diversified financ",
)
# Override per ticker noti dove il sector di yfinance puo' essere ambiguo.
_FINANCE_TICKERS = {"MB.MI", "GS", "BNP.PA", "ISP.MI", "UCG.MI", "BPE.MI", "ACA.PA", "GLE.PA"}

def is_financial(ticker, info=None, finnhub_profile=None):
    """
    True se il titolo e' un finanziario (banca/assicurazione/cap markets).
    Usa: override per ticker noti, poi sector/industry da yfinance info,
    poi finnhubIndustry dal profilo Finnhub. In dubbio -> False (non esenta).
    """
    if ticker in _FINANCE_TICKERS:
        return True
    blobs = []
    if info:
        blobs.append(str(info.get("sector", "")))
        blobs.append(str(info.get("industry", "")))
    if finnhub_profile:
        blobs.append(str(finnhub_profile.get("finnhubIndustry", "")))
    hay = " ".join(blobs).lower()
    return any(k in hay for k in _FINANCE_KEYWORDS)

def _crit(value, passed, source, note=""):
    """Costruisce un risultato-criterio uniforme."""
    return {"value": value, "pass": passed, "source": source, "note": note}

def _crit_na(source, note):
    """Criterio non applicabile (esenzione settoriale) o non recuperabile."""
    return {"value": None, "pass": None, "source": source, "note": note}

def build_screen(f, financial=False):
    """
    Valuta i 9 criteri sui campi gia' presenti nel dict fondamentali f.
    Ritorna dict screen[criterio] = {value, pass(True/False/None), source, note}.

    pass == True  -> criterio soddisfatto  (argomento BULL)
    pass == False -> criterio fallito       (argomento BEAR)
    pass == None  -> non valutabile (N/A settoriale o dato assente): NESSUN argomento.

    NB: nessun criterio e' un veto. Lo scoring resta soft fino al backtest.
    """
    T = SCREEN_THRESHOLDS
    s = {}
    src = f.get("source", "?")

    # 1) P/E < 20 -------------------------------------------------------------
    pe = _num(f.get("pe"))
    if pe is None:
        s["pe_lt_20"] = _crit_na(src, "P/E non disponibile")
    else:
        s["pe_lt_20"] = _crit(round(pe, 2), pe < T["pe_max"], src,
                              f"P/E {pe:.1f} {'<' if pe < T['pe_max'] else '>='} {T['pe_max']:.0f}")

    # 2) PEG < 1 --------------------------------------------------------------
    peg = _num(f.get("peg"))
    if peg is None:
        s["peg_lt_1"] = _crit_na(src, "PEG non disponibile a costo zero (mai stimato su crescita finta)")
    else:
        s["peg_lt_1"] = _crit(round(peg, 2), peg < T["peg_max"], src,
                              f"PEG {peg:.2f} {'<' if peg < T['peg_max'] else '>='} {T['peg_max']:.1f}")

    # 3) EPS in crescita su 5 anni -------------------------------------------
    g5 = _num(f.get("eps_growth_5y"))  # frazione: 0.12 = +12% CAGR (o crescita cumulata)
    if g5 is None:
        s["eps_up_5y"] = _crit_na(src, "crescita EPS 5Y non disponibile")
    else:
        s["eps_up_5y"] = _crit(round(g5, 4), g5 > 0, src,
                               f"EPS 5Y {'in crescita' if g5 > 0 else 'in calo'} ({g5*100:+.1f}%)")

    # 4) Net profit margin >= 10% --------------------------------------------
    nm = _num(f.get("net_margin"))  # frazione
    if nm is None:
        s["net_margin_10"] = _crit_na(src, "net margin non disponibile")
    else:
        s["net_margin_10"] = _crit(round(nm, 4), nm >= T["net_margin_min"], src,
                                   f"net margin {nm*100:.1f}% {'>=' if nm >= T['net_margin_min'] else '<'} 10%")

    # 5) Operating cash flow margin >= 30%  (N/A per finanziari) --------------
    if financial:
        s["ocf_margin_30"] = _crit_na(src, "N/A: OCF margin non sensato per un finanziario")
    else:
        ocfm = _num(f.get("ocf_margin"))  # frazione
        if ocfm is None:
            s["ocf_margin_30"] = _crit_na(src, "OCF margin non disponibile")
        else:
            s["ocf_margin_30"] = _crit(round(ocfm, 4), ocfm >= T["ocf_margin_min"], src,
                                       f"OCF margin {ocfm*100:.1f}% {'>=' if ocfm >= T['ocf_margin_min'] else '<'} 30%")

    # 6) Current ratio >= 1  (N/A per finanziari) ----------------------------
    if financial:
        s["current_ratio_1"] = _crit_na(src, "N/A: current ratio non sensato per un finanziario")
    else:
        cr = _num(f.get("current_ratio"))
        if cr is None:
            s["current_ratio_1"] = _crit_na(src, "current ratio non disponibile")
        else:
            s["current_ratio_1"] = _crit(round(cr, 2), cr >= T["current_ratio_min"], src,
                                         f"current ratio {cr:.2f} {'>=' if cr >= T['current_ratio_min'] else '<'} 1")

    # 7) Cash / LT debt >= 1.5  (N/A per finanziari) -------------------------
    if financial:
        s["cash_ltdebt_15"] = _crit_na(src, "N/A: cash/LT-debt non sensato per un finanziario (leva strutturale)")
    else:
        cltd = _num(f.get("cash_to_lt_debt"))
        if cltd is None:
            s["cash_ltdebt_15"] = _crit_na(src, "cash/LT-debt non disponibile")
        else:
            s["cash_ltdebt_15"] = _crit(round(cltd, 2), cltd >= T["cash_ltdebt_min"], src,
                                        f"cash/LT-debt {cltd:.2f} {'>=' if cltd >= T['cash_ltdebt_min'] else '<'} 1.5")

    # 8) Insider buying / net purchase up  (solo USA via SEC Form 4) ---------
    ib = f.get("insider_net_buying")  # True/False/None; valorizzato esternamente da insider_us.csv
    if ib is None:
        if is_european(f.get("ticker", "")):
            s["insider_buying"] = _crit_na(src, "insider buying non coperto a costo zero per EU")
        else:
            s["insider_buying"] = _crit_na(src, "nessun dato insider (Form 4) per il ticker")
    else:
        s["insider_buying"] = _crit(bool(ib), bool(ib), "sec_form4",
                                    "insider net buying" if ib else "insider net selling")

    # 9) Insider ownership >= 10% --------------------------------------------
    io = _num(f.get("insider_ownership"))  # frazione
    if io is None:
        s["insider_own_10"] = _crit_na(src, "insider ownership non disponibile")
    else:
        s["insider_own_10"] = _crit(round(io, 4), io >= T["insider_own_min"], src,
                                    f"insider ownership {io*100:.1f}% {'>=' if io >= T['insider_own_min'] else '<'} 10%")

    return s

def screen_to_debate_args(screen):
    """
    Trasforma lo screen nei due elenchi di argomenti per debate.py.
    SOLO criteri valutati (pass True/False) generano argomenti; i None vengono
    riassunti a parte come 'dati non disponibili' (trasparenza, non rumore).
    Ritorna (bull_args, bear_args, na_notes, n_pass, n_total_valutati).
    """
    labels = {
        "pe_lt_20":        "P/E < 20",
        "peg_lt_1":        "PEG < 1",
        "eps_up_5y":       "EPS in crescita 5Y",
        "net_margin_10":   "net margin >= 10%",
        "ocf_margin_30":   "OCF margin >= 30%",
        "current_ratio_1": "current ratio >= 1",
        "cash_ltdebt_15":  "cash/LT-debt >= 1.5",
        "insider_buying":  "insider buying",
        "insider_own_10":  "insider ownership >= 10%",
    }
    bull, bear, na = [], [], []
    n_pass = n_val = 0
    for k, lab in labels.items():
        c = screen.get(k)
        if not c:
            continue
        if c["pass"] is True:
            bull.append(f"{lab}: {c['note']}")
            n_pass += 1; n_val += 1
        elif c["pass"] is False:
            bear.append(f"{lab} non soddisfatto: {c['note']}")
            n_val += 1
        else:  # None
            na.append(f"{lab}: {c['note']}")
    return bull, bear, na, n_pass, n_val

def screen_summary_line(screen):
    """Riga sintetica leggibile: 'fondamentali 4/6 criteri (2 N/A)'."""
    _, _, na, n_pass, n_val = screen_to_debate_args(screen)
    return f"screening qualita': {n_pass}/{n_val} criteri soddisfatti" + \
           (f", {len(na)} non valutabili" if na else "")

# ---------------------------------------------------------------------------
# FONTE USA — SEC EDGAR PIT (primaria) con fallback Finnhub/yfinance
# ---------------------------------------------------------------------------

_PIT_CACHE = None

def _load_pit_csv(path="data/fundamentals_pit.csv"):
    """Carica il CSV PIT in un dict {ticker: row_dict}. Cachato per sessione."""
    global _PIT_CACHE
    if _PIT_CACHE is not None:
        return _PIT_CACHE
    _PIT_CACHE = {}
    if not os.path.exists(path):
        return _PIT_CACHE
    import csv
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            _PIT_CACHE[row["ticker"]] = row
    return _PIT_CACHE


def fetch_us_sec(ticker):
    """Fondamentali USA da SEC EDGAR PIT (data/fundamentals_pit.csv).
    Ritorna dict nello schema del modulo, oppure None se il ticker non e' nel CSV."""
    pit = _load_pit_csv()
    row = pit.get(ticker)
    if not row:
        return None

    out = {"ticker": ticker, "source": "sec_edgar", "asof_date": row.get("filed_date", ""),
           "pe": None, "forward_pe": None, "eps": None, "market_cap": None,
           "revenue": None, "currency": "USD", "next_earnings": None,
           "analyst_consensus": None, "price_asof": None,
           "peg": None, "eps_growth_5y": None, "net_margin": None,
           "ocf_margin": None, "current_ratio": None, "cash_to_lt_debt": None,
           "insider_net_buying": None, "insider_ownership": None,
           "_is_financial": None}

    out["eps"] = _num(row.get("eps_diluted"))
    out["revenue"] = _num(row.get("revenue"))
    out["market_cap"] = _num(row.get("total_assets"))
    out["net_margin"] = _num(row.get("net_margin"))
    out["ocf_margin"] = _num(row.get("ocf_margin"))
    out["current_ratio"] = _num(row.get("current_ratio"))
    out["cash_to_lt_debt"] = _num(row.get("cash_to_lt_debt"))
    out["eps_growth_5y"] = _num(row.get("eps_cagr_5y"))
    out["_is_financial"] = is_financial(ticker)

    return out


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
    """Fondamentali USA: SEC EDGAR PIT (primario) -> Finnhub (fallback).
    Se SEC ha i dati, li usa come base e integra solo analisti/earnings da Finnhub."""
    sec = fetch_us_sec(ticker)
    if sec and sec.get("eps") is not None:
        _enrich_from_finnhub(sec, ticker)
        return sec

    out = {"ticker": ticker, "source": "finnhub", "asof_date": datetime.date.today().isoformat(),
           "pe": None, "forward_pe": None, "eps": None, "market_cap": None,
           "revenue": None, "currency": "USD", "next_earnings": None,
           "analyst_consensus": None, "price_asof": None,
           # campi screening:
           "peg": None, "eps_growth_5y": None, "net_margin": None,
           "ocf_margin": None, "current_ratio": None, "cash_to_lt_debt": None,
           "insider_net_buying": None, "insider_ownership": None,
           "_is_financial": None}

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
        # --- campi screening da Finnhub /stock/metric ---
        out["peg"] = _num(m.get("pegTTM") or m.get("pegRatio"))
        # crescita EPS 5Y: Finnhub la espone come percentuale annua -> frazione
        g5 = _num(m.get("epsGrowth5Y"))
        out["eps_growth_5y"] = (g5 / 100.0) if g5 is not None else None
        # net margin TTM: Finnhub in percentuale -> frazione
        nm = _num(m.get("netProfitMarginTTM") or m.get("netMarginTTM"))
        out["net_margin"] = (nm / 100.0) if nm is not None else None
        # current ratio (quarterly se presente, poi annual)
        out["current_ratio"] = _num(m.get("currentRatioQuarterly") or m.get("currentRatioAnnual"))

    # OCF margin e cash/LT-debt: calcolati da financials-reported (piu' robusto)
    out["ocf_margin"], out["cash_to_lt_debt"] = _finnhub_cashflow_balance(ticker)

    # ownership insider: Finnhub non lo da' free in modo affidabile -> yfinance
    out["insider_ownership"] = _yf_insider_ownership(ticker)

    # profilo per classificazione settoriale
    prof = _finnhub_get("stock/profile2", {"symbol": ticker})
    out["_is_financial"] = is_financial(ticker, finnhub_profile=prof or {})

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

def _enrich_from_finnhub(out, ticker):
    """Integra il dict SEC con analisti e earnings date da Finnhub (se disponibile)."""
    rec = _finnhub_get("stock/recommendation", {"symbol": ticker})
    if rec and isinstance(rec, list) and rec:
        latest = rec[0]
        out["analyst_consensus"] = {
            "buy": latest.get("buy"), "hold": latest.get("hold"),
            "sell": latest.get("sell"), "strongBuy": latest.get("strongBuy"),
            "strongSell": latest.get("strongSell"), "period": latest.get("period"),
        }
    cal = _finnhub_get("calendar/earnings", {"symbol": ticker})
    if cal and cal.get("earningsCalendar"):
        future = [e for e in cal["earningsCalendar"]
                  if e.get("date", "") >= datetime.date.today().isoformat()]
        if future:
            out["next_earnings"] = sorted(future, key=lambda e: e["date"])[0]["date"]
    out["insider_ownership"] = _yf_insider_ownership(ticker)


def _finnhub_cashflow_balance(ticker):
    """
    Ritorna (ocf_margin, cash_to_lt_debt) da Finnhub financials-reported (annual).
    OCF margin = operating cash flow / revenue (ultimo anno disponibile).
    cash/LT-debt = cash & equivalents / long-term debt.
    Robusto ai nomi-campo variabili: cerca per chiavi note. None se non ricavabile.
    """
    data = _finnhub_get("stock/financials-reported", {"symbol": ticker, "freq": "annual"})
    if not data or not data.get("data"):
        return None, None
    try:
        rep = data["data"][0]["report"]  # piu' recente
        cf = rep.get("cf", []) or []
        ic = rep.get("ic", []) or []
        bs = rep.get("bs", []) or []

        def _find(items, needles):
            for it in items:
                label = str(it.get("label", "")).lower() + " " + str(it.get("concept", "")).lower()
                if any(n in label for n in needles):
                    v = _num(it.get("value"))
                    if v is not None:
                        return v
            return None

        ocf = _find(cf, ["net cash provided by operating", "cash from operating",
                         "operating activities"])
        rev = _find(ic, ["total revenue", "revenues", "net sales"])
        cash = _find(bs, ["cash and cash equivalents", "cash and equivalents"])
        ltd = _find(bs, ["long-term debt", "long term debt", "longtermdebtnoncurrent"])

        ocf_margin = (ocf / rev) if (ocf is not None and rev and rev != 0) else None
        cash_ltd = (cash / ltd) if (cash is not None and ltd and ltd != 0) else None
        return ocf_margin, cash_ltd
    except Exception:
        return None, None

def _yf_insider_ownership(ticker):
    """heldPercentInsiders da yfinance (frazione). Spesso stantio/nullo: usato solo come stima."""
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info or {}
        return _num(info.get("heldPercentInsiders"))
    except Exception:
        return None

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
           "analyst_consensus": None, "price_asof": None,
           # campi screening:
           "peg": None, "eps_growth_5y": None, "net_margin": None,
           "ocf_margin": None, "current_ratio": None, "cash_to_lt_debt": None,
           "insider_net_buying": None, "insider_ownership": None,
           "_is_financial": None}
    try:
        import yfinance as yf
        tk = yf.Ticker(ticker)
        info = tk.info or {}
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

        # --- campi screening da yfinance info (quando presenti) ---
        out["peg"] = _num(info.get("pegRatio") or info.get("trailingPegRatio"))
        out["net_margin"] = _num(info.get("profitMargins"))  # gia' frazione
        out["current_ratio"] = _num(info.get("currentRatio"))
        out["insider_ownership"] = _num(info.get("heldPercentInsiders"))
        out["_is_financial"] = is_financial(ticker, info=info)

        # OCF margin (solo se non finanziario; per finanziari sara' N/A a valle)
        ocfm, cltd = _yf_cashflow_balance(tk, info)
        out["ocf_margin"] = ocfm
        out["cash_to_lt_debt"] = cltd

        # crescita EPS 5Y dai bilanci annuali (income statement)
        out["eps_growth_5y"] = _yf_eps_growth_5y(tk, info)

    except Exception as e:
        out["_error"] = f"{type(e).__name__}: {str(e)[:100]}"
    return out

def _yf_cashflow_balance(tk, info):
    """(ocf_margin, cash_to_lt_debt) da yfinance cashflow + balance sheet. None se assenti."""
    ocf_margin = cash_ltd = None
    try:
        cf = tk.cashflow
        rev = _num(info.get("totalRevenue"))
        if cf is not None and not cf.empty:
            for key in ("Operating Cash Flow", "Total Cash From Operating Activities"):
                if key in cf.index:
                    ocf = _num(cf.loc[key].iloc[0])
                    if ocf is not None and rev and rev != 0:
                        ocf_margin = ocf / rev
                    break
    except Exception:
        pass
    try:
        bs = tk.balance_sheet
        if bs is not None and not bs.empty:
            cash = None
            for key in ("Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments"):
                if key in bs.index:
                    cash = _num(bs.loc[key].iloc[0]); break
            ltd = None
            for key in ("Long Term Debt", "Long Term Debt And Capital Lease Obligation"):
                if key in bs.index:
                    ltd = _num(bs.loc[key].iloc[0]); break
            if cash is not None and ltd and ltd != 0:
                cash_ltd = cash / ltd
    except Exception:
        pass
    return ocf_margin, cash_ltd

def _yf_eps_growth_5y(tk, info):
    """
    Crescita EPS su 5 anni come CAGR dai net income annuali / shares.
    Approccio robusto: usa income_stmt (Diluted EPS se presente, altrimenti
    Net Income / shares). Ritorna frazione (0.10 = +10% CAGR) o None.
    Mai stimata: solo da dati storici reali.
    """
    try:
        fin = tk.income_stmt
        if fin is None or fin.empty:
            return None
        # preferisci Diluted EPS storico se disponibile
        series = None
        for key in ("Diluted EPS", "Basic EPS"):
            if key in fin.index:
                series = fin.loc[key].dropna()
                break
        if series is None or len(series) < 2:
            # ripiego: Net Income / shares correnti (approssimazione)
            if "Net Income" in fin.index:
                ni = fin.loc["Net Income"].dropna()
                sh = _num(info.get("sharesOutstanding"))
                if len(ni) >= 2 and sh and sh > 0:
                    series = ni / sh
            if series is None or len(series) < 2:
                return None
        # ordina dal piu' vecchio al piu' recente (colonne yfinance: recenti a sx)
        vals = list(series.values)[::-1]
        first, last = _num(vals[0]), _num(vals[-1])
        n_years = len(vals) - 1
        if first is None or last is None or first <= 0 or n_years <= 0:
            # se il primo EPS e' <=0 il CAGR non e' definito: segnala solo direzione
            if first is not None and last is not None:
                return None
            return None
        cagr = (last / first) ** (1.0 / n_years) - 1.0
        return cagr
    except Exception:
        return None

# ---------------------------------------------------------------------------
# ORCHESTRATORE — sceglie la fonte per mercato, valida, restituisce esito onesto
# ---------------------------------------------------------------------------
def get_fundamentals(ticker, price_now=None, earnings_date_from_pipeline=None,
                     insider_net_buying=None):
    """
    API principale del modulo.
    ticker: simbolo (es. 'GS', 'MB.MI')
    price_now: prezzo corrente reale dalla pipeline (mib_data), per cross-check.
    earnings_date_from_pipeline: data trimestrale gia' nota da earnings_calendar.csv
        (fonte piu' affidabile della next_earnings dell'API per i titoli EU).
    insider_net_buying: True/False da insider_us.csv (SEC Form 4) se gia' noto
        a monte; per EU resta None (non coperto a costo zero).

    Ritorna dict con: tutti i campi + 'data_reliable' + 'reliability_notes'
    + 'screen' (i 9 criteri) + 'screen_pass'/'screen_total' di sintesi.
    """
    mkt = market_of(ticker)
    raw = fetch_us(ticker) if mkt == "US" else fetch_eu(ticker)

    # la data trimestrale della pipeline (yfinance earnings_calendar.csv) ha
    # precedenza: e' gia' validata nel flusso esistente
    if earnings_date_from_pipeline:
        raw["next_earnings"] = earnings_date_from_pipeline

    # insider buying dalla pipeline SEC Form 4 (USA): ha precedenza sul None interno
    if insider_net_buying is not None:
        raw["insider_net_buying"] = bool(insider_net_buying)

    reliable, reasons = validate_fundamentals(raw, price_now=price_now)
    raw["data_reliable"] = reliable
    raw["reliability_notes"] = "; ".join(reasons) if reasons else "ok"
    # i titoli EU partono con una nota di cautela strutturale anche se validi
    if mkt in ("IT", "FR") and reliable:
        raw["reliability_notes"] = "ok (fonte EU yfinance: affidabilita' strutturalmente inferiore, verificare se critico)"

    # screening qualita'/value (soft) — usa l'esenzione settoriale
    financial = bool(raw.get("_is_financial"))
    screen = build_screen(raw, financial=financial)
    raw["screen"] = screen
    _, _, _, n_pass, n_val = screen_to_debate_args(screen)
    raw["screen_pass"] = n_pass
    raw["screen_total"] = n_val
    raw["is_financial"] = financial
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
    line = f"{f['ticker']}: " + ", ".join(parts) + f"  [fonte {src}]"
    if f.get("screen"):
        line += " | " + screen_summary_line(f["screen"])
    return line


# ---------------------------------------------------------------------------
# EXPORT CSV
# ---------------------------------------------------------------------------
def export_fundamentals_csv(tickers, price_data=None, earnings_data=None,
                            insider_data=None, out_path="data/fundamentals.csv"):
    """
    Genera CSV con i fondamentali validati per una lista di ticker.
    price_data: dict {ticker: prezzo_corrente} per cross-check (dalla pipeline mib_data).
    earnings_data: dict {ticker: data_prossima_trimestrale} (da earnings_calendar.csv).
    insider_data: dict {ticker: bool net_buying} (da insider_us.csv, SEC Form 4).
    """
    import os
    import csv
    rows = []
    for t in tickers:
        price = price_data.get(t) if price_data else None
        earn_date = earnings_data.get(t) if earnings_data else None
        ib = insider_data.get(t) if insider_data else None
        f = get_fundamentals(t, price_now=price, earnings_date_from_pipeline=earn_date,
                             insider_net_buying=ib)
        sc = f.get("screen", {})
        def _sv(key):  # screen value
            c = sc.get(key); return "" if not c or c["value"] is None else c["value"]
        def _sp(key):  # screen pass (True/False/'' per N/A)
            c = sc.get(key); return "" if not c or c["pass"] is None else c["pass"]
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
            # --- screening ---
            "is_financial": f.get("is_financial"),
            "screen_pass": f.get("screen_pass"),
            "screen_total": f.get("screen_total"),
            "peg": f.get("peg"),
            "eps_growth_5y": f.get("eps_growth_5y"),
            "net_margin": f.get("net_margin"),
            "ocf_margin": f.get("ocf_margin"),
            "current_ratio": f.get("current_ratio"),
            "cash_to_lt_debt": f.get("cash_to_lt_debt"),
            "insider_net_buying": f.get("insider_net_buying"),
            "insider_ownership": f.get("insider_ownership"),
            "pass_pe_lt_20": _sp("pe_lt_20"),
            "pass_peg_lt_1": _sp("peg_lt_1"),
            "pass_eps_up_5y": _sp("eps_up_5y"),
            "pass_net_margin_10": _sp("net_margin_10"),
            "pass_ocf_margin_30": _sp("ocf_margin_30"),
            "pass_current_ratio_1": _sp("current_ratio_1"),
            "pass_cash_ltdebt_15": _sp("cash_ltdebt_15"),
            "pass_insider_buying": _sp("insider_buying"),
            "pass_insider_own_10": _sp("insider_own_10"),
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
            # insider net buying da insider_us.csv (SEC Form 4), se presente
            insider_map = {}
            if os.path.exists("insider_us.csv"):
                try:
                    iu = pd.read_csv("insider_us.csv")
                    # somma netta per ticker: buy positivo, sell negativo (colonne attese)
                    col_t = "ticker" if "ticker" in iu.columns else iu.columns[0]
                    if "net_value" in iu.columns:
                        agg = iu.groupby(col_t)["net_value"].sum()
                        insider_map = {t: (float(v) > 0) for t, v in agg.items()}
                    elif {"transaction_type", "value"}.issubset(iu.columns):
                        for t, g in iu.groupby(col_t):
                            net = g.apply(lambda r: r["value"] if str(r["transaction_type"]).upper().startswith("P")
                                          else -r["value"], axis=1).sum()
                            insider_map[t] = (float(net) > 0)
                except Exception as e:
                    print(f"[fundamentals] insider_us.csv non interpretato: {e}")
            export_fundamentals_csv(list(price_map.keys()), price_data=price_map,
                                   earnings_data=earn_map, insider_data=insider_map,
                                   out_path="data/fundamentals.csv")
        except Exception as e:
            print(f"[fundamentals] Errore workflow: {e}")
        sys.exit(0)

    # Altrimenti: test offline della VALIDAZIONE + SCREENING (non richiede rete).
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
    print("=== Test SCREENING — GS (finanziario): OCF/current/cash N/A attesi ===")
    gs_raw = {"ticker":"GS","source":"finnhub","pe":16.97,"eps":55.39,
              "peg":1.4,"eps_growth_5y":0.08,"net_margin":0.27,
              "ocf_margin":None,"current_ratio":None,"cash_to_lt_debt":None,
              "insider_net_buying":False,"insider_ownership":0.02}
    sc = build_screen(gs_raw, financial=True)
    bull, bear, na, npass, nval = screen_to_debate_args(sc)
    print(f"  {screen_summary_line(sc)}")
    print(f"  BULL: {bull}")
    print(f"  BEAR: {bear}")
    print(f"  N/A : {na}")

    print()
    print("=== Test SCREENING — titolo industriale ipotetico (tutti valutati) ===")
    ind = {"ticker":"XX","source":"finnhub","pe":15.0,"peg":0.8,"eps_growth_5y":0.12,
           "net_margin":0.14,"ocf_margin":0.33,"current_ratio":1.6,
           "cash_to_lt_debt":2.1,"insider_net_buying":True,"insider_ownership":0.15}
    sc = build_screen(ind, financial=False)
    bull, bear, na, npass, nval = screen_to_debate_args(sc)
    print(f"  {screen_summary_line(sc)}")
    print(f"  BULL ({len(bull)}): {bull}")
    print(f"  BEAR ({len(bear)}): {bear}")

    print()
    print("=== Test validazione (P/E assurdo) ===")
    junk = {"ticker":"XX","pe":9999,"eps":None,"asof_date":datetime.date.today().isoformat()}
    rel, notes = validate_fundamentals(junk, price_now=10.0)
    print(f"  P/E 9999 -> affidabile={rel}")
    for n in notes: print(f"    - {n}")
