"""
fundamentals_pit.py — Fondamentali Point-In-Time da SEC EDGAR (XBRL).

Fonte: data.sec.gov/api/xbrl/companyfacts/ (gratuito, ufficiale, no API key).
Ogni dato esce con la data di FILING (quando il mercato lo ha potuto vedere),
non la data del periodo — fondamentale per backtesting senza lookahead bias.

Copre SOLO i ticker USA (i titoli EU non depositano alla SEC).
Per ogni ticker estrae dai 10-K/10-Q piu' recenti:
  - Revenue, Net Income, EPS diluted, Gross Profit, Operating Income
  - Assets, Liabilities, Equity, Current Assets/Liabilities
  - Cash, Long-Term Debt, Operating Cash Flow
  - Metriche derivate: net margin, OCF margin, current ratio, cash/LT-debt
  - Crescita EPS (YoY e CAGR 5Y) point-in-time

Output: data/fundamentals_pit.csv  (una riga per ticker, dati piu' recenti)
        data/fundamentals_pit_history.csv (tutte le osservazioni per backtesting)

Rispetta il rate limit SEC: 10 req/s, User-Agent con email reale.
"""
import json
import time
import datetime
import math
import os
import csv
import urllib.request

UA = {"User-Agent": "MIB Pipeline newspaper.gram@gmail.com"}

# Ticker USA dalla pipeline (solo quelli che depositano alla SEC)
US_TICKERS = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN",
    "META", "AVGO", "TSLA", "LLY", "JPM",
    "V", "UNH", "XOM", "COST", "HD",
    "PG", "JNJ", "ORCL", "BAC", "NFLX",
    "AMD", "CRM", "KO", "CVX", "MRK",
    "WMT", "PLTR", "GE", "CAT", "GS",
    "ADBE", "QCOM", "TXN", "ABBV", "PEP",
    "MCD", "ACN", "INTC", "CSCO", "NOW",
    "AMAT", "DIS", "TMO", "ABT", "LIN",
]

LOG = []
def log(m):
    print(m)
    LOG.append(m)


def get(url, tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=90) as r:
                d = r.read()
            time.sleep(0.12)
            return d.decode("utf-8", "ignore")
        except Exception as e:
            if i == tries - 1:
                raise
            time.sleep(2.0 * (i + 1))


# ---- Mappa ticker -> CIK (cachata per la sessione) ----
_T2C = None

def ticker_to_cik():
    global _T2C
    if _T2C is not None:
        return _T2C
    raw = json.loads(get("https://www.sec.gov/files/company_tickers.json"))
    _T2C = {v["ticker"]: str(v["cik_str"]).zfill(10) for v in raw.values()}
    log(f"[PIT] ticker->CIK: {len(_T2C)} mappati")
    return _T2C


# ---- Concetti XBRL da estrarre ----
# (nome_campo, [concept candidati in ordine di preferenza], tipo)
# tipo: "duration" = ha start/end (income, cashflow), "instant" = solo end (balance sheet)
CONCEPTS = [
    # Income Statement (duration)
    ("revenue", [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
        "SalesRevenueServicesNet",
    ], "duration"),
    ("net_income", [
        "NetIncomeLoss",
        "NetIncomeLossAvailableToCommonStockholdersBasic",
    ], "duration"),
    ("eps_diluted", [
        "EarningsPerShareDiluted",
    ], "duration"),
    ("eps_basic", [
        "EarningsPerShareBasic",
    ], "duration"),
    ("gross_profit", [
        "GrossProfit",
    ], "duration"),
    ("operating_income", [
        "OperatingIncomeLoss",
    ], "duration"),

    # Balance Sheet (instant)
    ("total_assets", [
        "Assets",
    ], "instant"),
    ("total_liabilities", [
        "Liabilities",
    ], "instant"),
    ("stockholders_equity", [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ], "instant"),
    ("current_assets", [
        "AssetsCurrent",
    ], "instant"),
    ("current_liabilities", [
        "LiabilitiesCurrent",
    ], "instant"),
    ("cash", [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsAndShortTermInvestments",
    ], "instant"),
    ("long_term_debt", [
        "LongTermDebtNoncurrent",
        "LongTermDebt",
    ], "instant"),
    ("shares_outstanding", [
        "CommonStockSharesOutstanding",
        "EntityCommonStockSharesOutstanding",
    ], "instant"),

    # Cash Flow Statement (duration)
    ("ocf", [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ], "duration"),
]


def _num(x):
    if x is None:
        return None
    try:
        if isinstance(x, complex):
            return None
        v = float(x)
        return None if (math.isnan(v) or math.isinf(v)) else v
    except (ValueError, TypeError):
        return None


def _extract_facts(facts_json):
    """Estrae le serie storiche point-in-time dai companyfacts XBRL.

    Ritorna un dict: field_name -> list of {val, end, filed, form, fp, fy, [start]}
    ordinati per filed (data di deposito = quando il mercato ha potuto vedere il dato).
    """
    ns = facts_json.get("facts", {})
    gaap = ns.get("us-gaap", {})
    dei = ns.get("dei", {})
    pools = [gaap, dei]

    result = {}
    for field_name, concept_names, typ in CONCEPTS:
        entries = []
        for concept in concept_names:
            for pool in pools:
                if concept not in pool:
                    continue
                for unit_key, unit_entries in pool[concept].get("units", {}).items():
                    for e in unit_entries:
                        if e.get("form") not in ("10-K", "10-Q"):
                            continue
                        if typ == "duration" and "start" not in e:
                            continue
                        entries.append(e)
                if entries:
                    break
            if entries:
                break

        # Dedup per (accession, end): stesso filing puo' avere restated
        seen = set()
        deduped = []
        for e in entries:
            key = (e.get("accn"), e.get("end"))
            if key not in seen:
                seen.add(key)
                deduped.append(e)
        result[field_name] = sorted(deduped, key=lambda x: x.get("filed", ""))
    return result


def _latest_by_form(entries, form="10-K"):
    """Ultimo entry per un dato form type (10-K o 10-Q)."""
    matches = [e for e in entries if e.get("form") == form]
    return matches[-1] if matches else None


def _annualized_from_quarters(entries):
    """TTM: somma degli ultimi 4 trimestri (solo se fp in Q1-Q4 e contigui)."""
    quarterly = [e for e in entries
                 if e.get("form") == "10-Q" and e.get("fp") in ("Q1", "Q2", "Q3")]
    annual = [e for e in entries if e.get("form") == "10-K" and e.get("fp") == "FY"]
    if not quarterly:
        return _latest_by_form(entries, "10-K")

    last_q = quarterly[-1]
    fy = last_q.get("fy")
    fp = last_q.get("fp")

    # Per le metriche duration con start/end, un 10-K contiene gia' i 12 mesi.
    # Un 10-Q contiene i mesi dall'inizio dell'anno fiscale (cumulativo).
    # TTM = ultimo cumulativo Q + FY precedente - cumulativo Q dell'anno precedente.
    if "start" in last_q:
        q_val = _num(last_q.get("val"))
        prev_fy = [e for e in annual if e.get("fy") == fy - 1]
        if prev_fy and q_val is not None:
            fy_val = _num(prev_fy[-1].get("val"))
            # Q cumulativo dell'anno precedente con stesso fp
            prev_q = [e for e in quarterly
                      if e.get("fy") == fy - 1 and e.get("fp") == fp]
            pq_val = _num(prev_q[-1].get("val")) if prev_q else None
            if fy_val is not None and pq_val is not None:
                ttm_val = fy_val - pq_val + q_val
                return {**last_q, "val": ttm_val, "_ttm": True}
        return last_q

    return last_q


def process_ticker(ticker, facts_json):
    """Processa i companyfacts per un ticker. Ritorna (latest_row, history_rows)."""
    entity = facts_json.get("entityName", ticker)
    data = _extract_facts(facts_json)

    # --- Riga piu' recente (snapshot) ---
    def val_latest(field, prefer_ttm=False):
        entries = data.get(field, [])
        if not entries:
            return None, None, None
        if prefer_ttm:
            ttm = _annualized_from_quarters(entries)
            if ttm:
                return _num(ttm.get("val")), ttm.get("filed"), ttm.get("form") + ("*" if ttm.get("_ttm") else "")
        last = entries[-1]
        return _num(last.get("val")), last.get("filed"), last.get("form")

    rev, rev_filed, rev_form = val_latest("revenue", prefer_ttm=True)
    ni, ni_filed, ni_form = val_latest("net_income", prefer_ttm=True)
    eps_d, eps_filed, _ = val_latest("eps_diluted", prefer_ttm=True)
    eps_b, _, _ = val_latest("eps_basic", prefer_ttm=True)
    gp, _, _ = val_latest("gross_profit", prefer_ttm=True)
    oi, _, _ = val_latest("operating_income", prefer_ttm=True)
    ta, ta_filed, _ = val_latest("total_assets")
    tl, _, _ = val_latest("total_liabilities")
    eq, _, _ = val_latest("stockholders_equity")
    ca, _, _ = val_latest("current_assets")
    cl, _, _ = val_latest("current_liabilities")
    cash, _, _ = val_latest("cash")
    ltd, _, _ = val_latest("long_term_debt")
    sh, _, _ = val_latest("shares_outstanding")
    ocf, _, _ = val_latest("ocf", prefer_ttm=True)

    # Metriche derivate
    net_margin = (ni / rev) if (ni is not None and rev and rev != 0) else None
    ocf_margin = (ocf / rev) if (ocf is not None and rev and rev != 0) else None
    current_ratio = (ca / cl) if (ca is not None and cl and cl != 0) else None
    cash_ltd_ratio = (cash / ltd) if (cash is not None and ltd and ltd != 0) else None
    gross_margin = (gp / rev) if (gp is not None and rev and rev != 0) else None
    roe = (ni / eq) if (ni is not None and eq and eq != 0) else None
    debt_equity = (tl / eq) if (tl is not None and eq and eq != 0) else None

    # Crescita EPS YoY e CAGR 5Y (point-in-time: usa solo 10-K)
    eps_growth_yoy, eps_cagr_5y = _eps_growth(data.get("eps_diluted", []))

    latest = {
        "ticker": ticker,
        "entity": entity,
        "source": "sec_edgar",
        "filed_date": eps_filed or ni_filed or rev_filed or ta_filed,
        "revenue": rev,
        "net_income": ni,
        "eps_diluted": eps_d,
        "eps_basic": eps_b,
        "gross_profit": gp,
        "operating_income": oi,
        "total_assets": ta,
        "total_liabilities": tl,
        "stockholders_equity": eq,
        "current_assets": ca,
        "current_liabilities": cl,
        "cash": cash,
        "long_term_debt": ltd,
        "shares_outstanding": sh,
        "ocf": ocf,
        "net_margin": _round(net_margin, 4),
        "gross_margin": _round(gross_margin, 4),
        "ocf_margin": _round(ocf_margin, 4),
        "current_ratio": _round(current_ratio, 2),
        "cash_to_lt_debt": _round(cash_ltd_ratio, 2),
        "roe": _round(roe, 4),
        "debt_to_equity": _round(debt_equity, 2),
        "eps_growth_yoy": _round(eps_growth_yoy, 4),
        "eps_cagr_5y": _round(eps_cagr_5y, 4),
    }

    # --- Storia per backtesting (una riga per filing 10-K/10-Q) ---
    history = _build_history(ticker, entity, data)

    return latest, history


def _round(v, n):
    if v is None or isinstance(v, complex):
        return None
    try:
        return round(float(v), n)
    except (ValueError, TypeError):
        return None


def _eps_growth(eps_entries):
    """Crescita EPS YoY e CAGR 5Y dai soli 10-K (point-in-time)."""
    annual = [e for e in eps_entries if e.get("form") == "10-K" and e.get("fp") == "FY"]
    annual = sorted(annual, key=lambda x: x.get("fy", 0))

    yoy = None
    if len(annual) >= 2:
        curr = _num(annual[-1].get("val"))
        prev = _num(annual[-2].get("val"))
        if curr is not None and prev is not None and prev > 0:
            yoy = (curr - prev) / prev

    cagr5 = None
    if len(annual) >= 6:
        last = _num(annual[-1].get("val"))
        first = _num(annual[-6].get("val"))
        if last is not None and first is not None and first > 0:
            cagr5 = (last / first) ** (1.0 / 5.0) - 1.0

    return yoy, cagr5


def _build_history(ticker, entity, data):
    """Costruisce la storia point-in-time: una riga per ogni 10-K/10-Q depositato.

    Per ogni filing, i valori di balance sheet sono quelli del filing stesso (instant),
    e i valori income/cashflow sono cumulativi come riportati.
    Il campo 'filed' e' la data in cui il dato e' diventato pubblico.
    """
    # Raccogli tutte le date di filing distinte
    all_filings = set()
    for field_entries in data.values():
        for e in field_entries:
            key = (e.get("accn"), e.get("filed"), e.get("form"), e.get("fp"), e.get("fy"))
            all_filings.add(key)

    if not all_filings:
        return []

    # Per ogni campo, indicizza per accession number
    indexed = {}
    for field_name, entries in data.items():
        for e in entries:
            accn = e.get("accn")
            if accn not in indexed:
                indexed[accn] = {}
            indexed[accn][field_name] = _num(e.get("val"))

    rows = []
    for accn, filed, form, fp, fy in sorted(all_filings, key=lambda x: x[1] or ""):
        if not filed:
            continue
        vals = indexed.get(accn, {})
        if not vals:
            continue
        rev = vals.get("revenue")
        ni = vals.get("net_income")
        ocf_v = vals.get("ocf")
        ca = vals.get("current_assets")
        cl = vals.get("current_liabilities")
        cash_v = vals.get("cash")
        ltd_v = vals.get("long_term_debt")
        eq = vals.get("stockholders_equity")
        rows.append({
            "ticker": ticker,
            "filed": filed,
            "form": form,
            "fp": fp,
            "fy": fy,
            "revenue": rev,
            "net_income": ni,
            "eps_diluted": vals.get("eps_diluted"),
            "ocf": ocf_v,
            "net_margin": _round((ni / rev) if (ni and rev and rev != 0) else None, 4),
            "ocf_margin": _round((ocf_v / rev) if (ocf_v and rev and rev != 0) else None, 4),
            "current_ratio": _round((ca / cl) if (ca and cl and cl != 0) else None, 2),
            "cash_to_lt_debt": _round((cash_v / ltd_v) if (cash_v and ltd_v and ltd_v != 0) else None, 2),
            "roe": _round((ni / eq) if (ni and eq and eq != 0) else None, 4),
        })

    return rows


def main():
    os.makedirs("data", exist_ok=True)
    t2c = ticker_to_cik()

    latest_rows = []
    history_rows = []
    errors = []

    for tk in US_TICKERS:
        cik = t2c.get(tk)
        if not cik:
            log(f"[PIT] {tk}: CIK non trovato -> skip")
            errors.append(tk)
            continue
        try:
            raw = get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json")
            facts = json.loads(raw)
            latest, history = process_ticker(tk, facts)
            latest_rows.append(latest)
            history_rows.extend(history)
            eps = latest.get("eps_diluted")
            rev = latest.get("revenue")
            nm = latest.get("net_margin")
            filed = latest.get("filed_date")
            log(f"[PIT] {tk}: EPS={eps} rev={_fmt_big(rev)} nm={_pct(nm)} filed={filed} ({len(history)} obs)")
        except Exception as e:
            log(f"[PIT] {tk}: ERR {e}")
            errors.append(tk)

    # Scrivi CSV
    if latest_rows:
        _write_csv("data/fundamentals_pit.csv", latest_rows)
        log(f"[PIT] scritto data/fundamentals_pit.csv ({len(latest_rows)} ticker)")

    if history_rows:
        _write_csv("data/fundamentals_pit_history.csv", history_rows)
        log(f"[PIT] scritto data/fundamentals_pit_history.csv ({len(history_rows)} osservazioni)")

    if errors:
        log(f"[PIT] errori su: {errors}")

    # Log
    with open("data/pit_log.txt", "w") as f:
        f.write(datetime.datetime.utcnow().isoformat() + "Z\n" + "\n".join(LOG))

    log(f"[PIT] completato: {len(latest_rows)}/{len(US_TICKERS)} ticker, "
        f"{len(history_rows)} osservazioni storiche")


def _write_csv(path, rows):
    if not rows:
        return
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)


def _fmt_big(v):
    if v is None:
        return "N/A"
    if abs(v) >= 1e12:
        return f"{v/1e12:.1f}T"
    if abs(v) >= 1e9:
        return f"{v/1e9:.1f}B"
    if abs(v) >= 1e6:
        return f"{v/1e6:.0f}M"
    return f"{v:.0f}"


def _pct(v):
    if v is None:
        return "N/A"
    return f"{v*100:.1f}%"


if __name__ == "__main__":
    main()
