"""fundamentals_eu.py — Fondamentali EU (best-effort), per estendere la copertura oltre gli USA.

CONTESTO E LIMITE STRUTTURALE: la SEC (fundamentals_pit.py) copre solo i filer USA. Per l'EU
NON esiste un equivalente gratuito e unificato di data.sec.gov: l'ESEF e' depositato presso le
autorita' nazionali senza un'API aggregata aperta. Qui si usa l'endpoint pubblico Yahoo
fundamentals-timeseries (host query1, gia' in allowlist) come UNICO ripiego praticabile.

DIFFERENZA CRUCIALE DAGLI USA (da dichiarare sempre):
  - NON e' point-in-time vero. Yahoo espone `asOfDate` = FINE PERIODO, non la data di deposito,
    e i valori sono RESTATED (vista corrente), non come-originariamente-pubblicati.
  - Per il backtest si APPROSSIMA la data di disponibilita' = asOfDate + LAG_GG (lag regolatorio
    EU: bilancio annuale entro 4 mesi dalla chiusura, Transparency Directive -> 120gg, prudente).
    Cosi' il dato entra nel backtest solo BEN DOPO la chiusura, evitando lookahead grossolano.
  - Fonte marcata `yahoo_ts` e history con form `AR` (annual report) per distinguerla dal PIT SEC.

USO: per lo screening CORRENTE (portfolio_builder) i fondamentali restated vanno bene. Per il
backtest vanno trattati come approssimazione (lag-shift), MAI come il PIT esatto degli USA.

Output: data/fundamentals_eu.csv (snapshot) + data/fundamentals_eu_history.csv (lag-approx PIT).
"""
import json
import datetime
import os
import csv
import time

import requests
from fetch_data import TICKERS
from modules.fmp_source import _BROWSER_HEADERS

LAG_GG = 120   # lag regolatorio EU per il bilancio annuale (Transparency Directive, 4 mesi)

# Serie annuali richieste all'endpoint timeseries (prefisso 'annual').
TS_TYPES = {
    "revenue": "annualTotalRevenue",
    "net_income": "annualNetIncome",
    "gross_profit": "annualGrossProfit",
    "ocf": "annualOperatingCashFlow",
    "current_assets": "annualCurrentAssets",
    "current_liabilities": "annualCurrentLiabilities",
    "cash": "annualCashAndCashEquivalents",
    "long_term_debt": "annualLongTermDebt",
    "stockholders_equity": "annualStockholdersEquity",
    "eps_diluted": "annualDilutedEPS",
}

EU_TICKERS = [t for t in TICKERS
              if t.endswith((".MI", ".PA", ".AS")) and not t.startswith("^") and "MIB" not in t]

LOG = []
def log(m):
    print(m)
    LOG.append(m)


def _num(x):
    if x is None:
        return None
    try:
        v = float(x)
        return v if v == v and abs(v) != float("inf") else None
    except (ValueError, TypeError):
        return None


def fetch_timeseries(symbol):
    """Storico annuale dei fondamentali via Yahoo timeseries. Ritorna {field: {year: val}} o None."""
    types = ",".join(TS_TYPES.values())
    url = f"https://query1.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/{symbol}"
    params = {"symbol": symbol, "type": types,
              "period1": 1262304000, "period2": int(time.time()) + 86400, "merge": "false"}
    try:
        r = requests.get(url, params=params, headers=_BROWSER_HEADERS, timeout=30)
        if r.status_code != 200:
            log(f"[EU] {symbol}: HTTP {r.status_code}")
            return None
        res = r.json().get("timeseries", {}).get("result", [])
    except Exception as e:
        log(f"[EU] {symbol}: ERR {repr(e)[:80]}")
        return None

    rev_map = {v: k for k, v in TS_TYPES.items()}   # yahoo-type -> nostro campo
    out = {f: {} for f in TS_TYPES}
    for s in res:
        ytype = s.get("meta", {}).get("type", [None])[0]
        field = rev_map.get(ytype)
        if not field:
            continue
        for pt in s.get(ytype, []) or []:
            if not pt:
                continue
            d = pt.get("asOfDate")
            val = _num((pt.get("reportedValue") or {}).get("raw"))
            if d and val is not None:
                out[field][d] = val   # chiave = data fine periodo (YYYY-MM-DD)
    return out if any(out[f] for f in out) else None


def _metrics_for_year(ts, end_date):
    """Calcola le metriche di qualita' per un dato anno (end_date)."""
    def g(field):
        return ts.get(field, {}).get(end_date)
    rev = g("revenue"); ni = g("net_income"); gp = g("gross_profit")
    ocf = g("ocf"); ca = g("current_assets"); cl = g("current_liabilities")
    cash = g("cash"); ltd = g("long_term_debt"); eq = g("stockholders_equity")
    eps = g("eps_diluted")
    net_margin = (ni / rev) if (ni is not None and rev and rev > 0) else None
    ocf_margin = (ocf / rev) if (ocf is not None and rev and rev > 0) else None
    current_ratio = (ca / cl) if (ca is not None and cl and cl != 0) else None
    cash_to_ltd = (cash / ltd) if (cash is not None and ltd and ltd != 0) else None
    roe = (ni / eq) if (ni is not None and eq and eq != 0) else None
    return dict(revenue=rev, net_income=ni, eps_diluted=eps, ocf=ocf,
                net_margin=_r(net_margin, 4), ocf_margin=_r(ocf_margin, 4),
                current_ratio=_r(current_ratio, 2), cash_to_lt_debt=_r(cash_to_ltd, 2),
                roe=_r(roe, 4))


def _r(v, n):
    return round(v, n) if v is not None else None


def _avail_date(end_date):
    """Data di disponibilita' approssimata = fine periodo + lag regolatorio (no lookahead)."""
    try:
        d = datetime.date.fromisoformat(end_date)
        return (d + datetime.timedelta(days=LAG_GG)).isoformat()
    except ValueError:
        return None


def process(symbol, ts):
    """Ritorna (snapshot_row, history_rows) per un ticker EU."""
    # tutte le date-fine-periodo presenti (unione tra le serie)
    all_years = sorted({d for f in ts for d in ts[f]})
    if not all_years:
        return None, []

    history = []
    for end_date in all_years:
        m = _metrics_for_year(ts, end_date)
        if m["revenue"] is None and m["net_income"] is None:
            continue
        filed = _avail_date(end_date)
        history.append(dict(ticker=symbol, filed=filed, form="AR", fp="FY",
                            fy=int(end_date[:4]), **m))

    if not history:
        return None, []

    last = history[-1]
    snapshot = dict(ticker=symbol, entity=symbol, source="yahoo_ts",
                    filed_date=last["filed"], period_end=all_years[-1],
                    revenue=last["revenue"], net_income=last["net_income"],
                    eps_diluted=last["eps_diluted"], ocf=last["ocf"],
                    net_margin=last["net_margin"], ocf_margin=last["ocf_margin"],
                    current_ratio=last["current_ratio"],
                    cash_to_lt_debt=last["cash_to_lt_debt"], roe=last["roe"])
    return snapshot, history


def main():
    os.makedirs("data", exist_ok=True)
    snap_rows, hist_rows, errors = [], [], []

    for tk in EU_TICKERS:
        ts = fetch_timeseries(tk)
        time.sleep(0.15)
        if not ts:
            errors.append(tk)
            continue
        snap, hist = process(tk, ts)
        if snap is None:
            errors.append(tk)
            continue
        snap_rows.append(snap)
        hist_rows.extend(hist)
        log(f"[EU] {tk:10s} nm={_pct(snap['net_margin'])} cr={snap['current_ratio']} "
            f"roe={_pct(snap['roe'])} end={snap['period_end']} ({len(hist)} anni)")

    if snap_rows:
        _write("data/fundamentals_eu.csv", snap_rows)
        log(f"[EU] scritto data/fundamentals_eu.csv ({len(snap_rows)} ticker)")
    if hist_rows:
        _write("data/fundamentals_eu_history.csv", hist_rows)
        log(f"[EU] scritto data/fundamentals_eu_history.csv ({len(hist_rows)} osservazioni, "
            f"filed = fine periodo + {LAG_GG}gg)")
    if errors:
        log(f"[EU] senza dati ({len(errors)}): {errors}")

    with open("data/eu_fund_log.txt", "w") as f:
        f.write(datetime.datetime.utcnow().isoformat() + "Z\n" + "\n".join(LOG))
    log(f"[EU] completato: {len(snap_rows)}/{len(EU_TICKERS)} ticker")


def _write(path, rows):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)


def _pct(v):
    return "N/A" if v is None else f"{float(v)*100:.0f}%"


if __name__ == "__main__":
    main()
