"""fundamentals_pit.py — Fondamentali POINT-IN-TIME da SEC EDGAR + validazione full-cycle.

Fonte: SEC EDGAR `companyfacts` (data.sec.gov) — valori XBRL storici CON la DATA DI DEPOSITO
(`filed`): l'unico modo gratuito e corretto per avere fondamentali senza lookahead. Si usa il
bilancio ANNUALE (10-K) reso disponibile PRIMA della data del segnale (PIT-clean).

Solo titoli USA (EU non depositano in SEC). Due fasi:
  fetch()    -> scarica e costruisce data/fundamentals_pit.csv (ticker, filed, netIncome,
                revenue, equity, assets, liabilities, epsDiluted)
  validate() -> fattori quality/value PIT vs forward return sul ciclo completo (mib_data_long.csv)

NB ambiente: data.sec.gov deve essere nell'allowlist di egress (come query1.finance.yahoo.com).
Se non raggiungibile, fetch() lo segnala chiaramente e NON fabbrica dati.
"""
import time
import json
import urllib.request
import numpy as np
import pandas as pd

UA = {"User-Agent": "mib-data research newspaper.gram@gmail.com"}
OUT = "data/fundamentals_pit.csv"
# concetti us-gaap (con alias: i nomi variano tra societa')
CONCEPTS = {
    "netIncome":  ["NetIncomeLoss"],
    "revenue":    ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"],
    "equity":     ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "assets":     ["Assets"],
    "liabilities":["Liabilities"],
    "epsDiluted": ["EarningsPerShareDiluted"],
}


def _get(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.read()
        except Exception as e:
            if i == tries-1:
                raise
            time.sleep(0.4)


def _us_tickers():
    from fetch_data import TICKERS, _EU_SUFFIXES
    return [t for t in TICKERS if not t.endswith(_EU_SUFFIXES) and not t.startswith("^")
            and t not in ("SPY",) and "." not in t]


def _annual_points(facts, names):
    """Estrae i punti ANNUALI (form 10-K) per il primo concetto/alias disponibile:
    lista di (filed, end, val). Usa unita' USD (o /shares per EPS)."""
    g = facts.get("facts", {}).get("us-gaap", {})
    for nm in names:
        if nm in g:
            for unit, arr in g[nm]["units"].items():
                pts = [(p["filed"], p["end"], p["val"]) for p in arr
                       if p.get("form") in ("10-K", "10-K/A") and p.get("fp") == "FY" and p.get("val") is not None]
                if pts:
                    return pts
    return []


def fetch():
    try:
        tmap = json.loads(_get("https://www.sec.gov/files/company_tickers.json"))
    except Exception as e:
        print(f"[SEC] NON raggiungibile ({repr(e)[:90]}).")
        print("    -> aggiungere www.sec.gov e data.sec.gov all'allowlist di egress dell'ambiente,")
        print("       poi rilanciare. Nessun dato fabbricato.")
        return None
    t2c = {v["ticker"]: str(v["cik_str"]).zfill(10) for v in tmap.values()}
    rows = []
    for tk in _us_tickers():
        cik = t2c.get(tk)
        if not cik:
            print(f"[SEC] {tk}: CIK assente"); continue
        try:
            cf = json.loads(_get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"))
        except Exception as e:
            print(f"[SEC] {tk}: errore companyfacts {repr(e)[:60]}"); continue
        series = {k: dict((end, (filed, val)) for filed, end, val in _annual_points(cf, names))
                  for k, names in CONCEPTS.items()}
        # unisci per 'end' (anno fiscale); filed = max tra i concetti (disponibilita' prudente)
        ends = set().union(*[set(s.keys()) for s in series.values()]) if series else set()
        for end in sorted(ends):
            rec = {"ticker": tk, "end": end}
            fileds = []
            for k in CONCEPTS:
                fv = series[k].get(end)
                if fv:
                    fileds.append(fv[0]); rec[k] = fv[1]
                else:
                    rec[k] = np.nan
            if fileds and not np.isnan(rec.get("netIncome", np.nan)):
                rec["filed"] = max(fileds)
                rows.append(rec)
        time.sleep(0.12)  # rispetta limite SEC ~10 req/s
    if not rows:
        print("[SEC] nessun dato estratto."); return None
    df = pd.DataFrame(rows)
    df["roe"] = df["netIncome"] / df["equity"]
    df["net_margin"] = df["netIncome"] / df["revenue"]
    df["leverage"] = df["liabilities"] / df["assets"]
    df.to_csv(OUT, index=False)
    print(f"[SEC] scritti {len(df)} bilanci annuali ({df['ticker'].nunique()} ticker) in {OUT}")
    return df


def validate(px_path="data/mib_data_long.csv"):
    import backtest_v3 as bt
    try:
        fnd = pd.read_csv(OUT, parse_dates=["filed", "end"])
    except FileNotFoundError:
        print(f"[validate] manca {OUT}: esegui prima fetch() (richiede SEC in allowlist)."); return
    px = pd.read_csv(px_path, parse_dates=["date"]).dropna(subset=["close"])
    sig = bt.build_signals(px, bt.score_new, horizons=(5, 10, 20))
    # lookup PIT: per ogni (ticker, data segnale) prendi l'ULTIMO 10-K con filed < data
    fnd = fnd.sort_values("filed")
    out = []
    for tk, grp in sig.groupby("ticker"):
        f = fnd[fnd["ticker"] == tk]
        if f.empty:
            continue
        for r in grp.itertuples():
            prior = f[f["filed"] < r.date]
            if prior.empty:
                continue
            last = prior.iloc[-1]
            price = float(px[(px.ticker == tk)].sort_values("date").set_index("date")["close"].asof(r.date))
            ey = (last["epsDiluted"] / price) if price and price > 0 and pd.notna(last["epsDiluted"]) else np.nan
            out.append({"ticker": tk, "fwd_10_net": getattr(r, "fwd_10_net", np.nan),
                        "fwd_20_net": getattr(r, "fwd_20_net", np.nan), "score": r.score,
                        "roe": last["roe"], "net_margin": last["net_margin"],
                        "leverage": last["leverage"], "earnings_yield": ey})
    d = pd.DataFrame(out).replace([np.inf, -np.inf], np.nan)
    print(f"Segnali USA con fondamentali PIT: {len(d)}")
    print("\n=== Spearman fattore PIT vs forward return netto (full-cycle) ===")
    print(f"{'fattore':16s}{'10gg':>10s}{'20gg':>10s}")
    for f in ["roe", "net_margin", "earnings_yield", "leverage", "score"]:
        row = f"{f:16s}"
        for hz in (10, 20):
            col = f"fwd_{hz}_net"; dd = d.dropna(subset=[f, col])
            row += f"{dd[[f, col]].corr('spearman').iloc[0, 1]:>10.4f}" if len(dd) > 30 else f"{'n/a':>10s}"
        print(row)
    print("\n=== Forward 10gg per quintile (fattori value/quality) ===")
    for f in ["earnings_yield", "roe"]:
        dd = d.dropna(subset=[f, "fwd_10_net"]).copy()
        if len(dd) < 50:
            continue
        dd["q"] = pd.qcut(dd[f], 5, labels=[1, 2, 3, 4, 5], duplicates="drop")
        g = dd.groupby("q", observed=True)["fwd_10_net"].mean()
        print(f"  {f:16s}: " + " | ".join(f"Q{q}={v:+.2f}%" for q, v in g.items()))


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "validate":
        validate()
    else:
        if fetch() is not None:
            validate()
