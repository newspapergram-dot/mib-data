"""unicorn_validate.py — Gli "unicorni" growth sono tradeable nel modello? Backtest del profilo.

Run #15 ha prodotto uno screener fondamentale di SCOPERTA (unicorn_screener.py), avvertendo che
NON era un segnale validato. Qui si fa la validazione vera, con la disciplina del repo:

  1. PREZZI: scarica lo storico 2018-2026 (aggiustato) dei top candidati unicorno (Yahoo v8).
  2. SEGNALI: applica lo score momentum gia' validato (score_new) -> il modello "vede" gli unicorni.
  3. CRESCITA PIT: per ogni segnale calcola la crescita ricavi YoY POINT-IN-TIME da SEC EDGAR
     (solo filing con filed <= data segnale: nessun lookahead).
  4. REGIME: segmenta bull/bear (^GSPC/SMA200), come pit_validate.

Domande:
  A) Il momentum del modello funziona sugli unicorni quanto/piu' che sui mega-cap?
  B) Dentro il top-quintile, l'IPER-CRESCITA PIT (rev YoY alta) predice i ritorni? In che regime?
  C) Correlazione continua crescita↔ritorno.

Onesta' attesa (coerente con L#14): gli unicorni sono HIGH-BETA -> ci si aspetta ritorni medi
piu' alti ma drawdown/varianza maggiori, e un effetto crescita concentrato per regime. Il verdetto
guida se aggiungerli al TICKERS operativo o tenerli come watchlist ad alto rischio.
"""
import os
import csv
import datetime
import json

import numpy as np
import pandas as pd

import backtest_v3 as bt
import fundamentals_pit as fp
from pit_validate import _add_regime, _metrics, _row
from unicorn_screener import REVENUE_CONCEPTS

PRICES_CACHE = "data/mib_data_unicorns.csv"
LONG_PATH = "data/mib_data_long.csv"


def top_unicorns(min_score=50.0, exclude=None, path="data/unicorn_candidates.csv"):
    exclude = set(exclude or [])
    with open(path) as f:
        rows = [r for r in csv.DictReader(f)
                if float(r["unicorn_score"]) >= min_score and r["ticker"] not in exclude]
    rows.sort(key=lambda r: float(r["unicorn_score"]), reverse=True)
    return [r["ticker"] for r in rows]


def fetch_prices(tickers, force=False):
    """Storico aggiustato 2018-2026 dei ticker (Yahoo v8, via fetch_long.fetch). Cache su CSV."""
    if os.path.exists(PRICES_CACHE) and not force:
        df = pd.read_csv(PRICES_CACHE, parse_dates=["date"])
        if set(tickers).issubset(set(df["ticker"].unique())):
            return df
    from fetch_long import fetch
    frames, failed = [], []
    for t in tickers:
        d = fetch(t)
        if d is None or d.empty:
            failed.append(t); continue
        frames.append(d)
    if not frames:
        return None
    out = pd.concat(frames, ignore_index=True)
    for c in ["open", "high", "low", "close", "volume"]:
        out[c] = pd.to_numeric(out[c], errors="coerce")
    out = out.dropna(subset=["close"]).drop_duplicates(["ticker", "date"])
    out.to_csv(PRICES_CACHE, index=False)
    if failed:
        print(f"[uni-val] prezzi falliti: {failed}")
    return pd.read_csv(PRICES_CACHE, parse_dates=["date"])


# ── Crescita ricavi POINT-IN-TIME da SEC ────────────────────────────────────
def _rev_points(facts):
    """Punti di ricavo annuale (filed, end_year, val), durata ~365gg, per il calcolo PIT.
    A differenza dello snapshot, tiene TUTTI i filing (serve sapere cosa era noto quando)."""
    pools = [facts.get("facts", {}).get("us-gaap", {})]
    points = []
    seen = set()
    for concept in REVENUE_CONCEPTS:
        for pool in pools:
            if concept not in pool:
                continue
            for entries in pool[concept].get("units", {}).values():
                for e in entries:
                    if e.get("form") not in ("10-K", "10-Q"):
                        continue
                    s, en, filed = e.get("start"), e.get("end"), e.get("filed")
                    if not (s and en and filed):
                        continue
                    try:
                        dur = (datetime.date.fromisoformat(en) - datetime.date.fromisoformat(s)).days
                    except ValueError:
                        continue
                    if not (350 <= dur <= 380):
                        continue
                    val = fp._num(e.get("val"))
                    if val is None:
                        continue
                    key = (filed, en, round(val, 2))
                    if key in seen:
                        continue
                    seen.add(key)
                    points.append((filed, int(en[:4]), val))
    return points


def _pit_rev_yoy(points, as_of):
    """Crescita ricavi YoY come nota alla data `as_of` (solo filing filed <= as_of)."""
    avail = [(f, y, v) for (f, y, v) in points if f <= as_of]
    if not avail:
        return None
    # per ogni end_year, valore dal filing piu' recente disponibile
    by_year = {}
    for f, y, v in sorted(avail, key=lambda x: x[0]):
        by_year[y] = v
    years = sorted(by_year)
    if len(years) < 2:
        return None
    last, prev = by_year[years[-1]], by_year[years[-2]]
    if prev is None or prev <= 0:
        return None
    return last / prev - 1.0


def run(hz=10, min_score=50.0):
    uni = top_unicorns(min_score=min_score, exclude=set(__import__("fetch_data").TICKERS))
    print(f"[uni-val] {len(uni)} unicorni candidati (score>={min_score:.0f}): {', '.join(uni)}")

    px = fetch_prices(uni)
    if px is None:
        print("[uni-val] nessun prezzo scaricato."); return
    # benchmark ^GSPC dal dataset lungo (per il regime)
    if os.path.exists(LONG_PATH):
        long = pd.read_csv(LONG_PATH, parse_dates=["date"])
        bench = long[long["ticker"] == "^GSPC"]
        px = pd.concat([px, bench], ignore_index=True)
    px = px.dropna(subset=["close"])
    n_uni = px[px["ticker"].isin(uni)]["ticker"].nunique()
    print(f"[uni-val] prezzi: {n_uni} unicorni con storico, "
          f"{px['date'].min().date()} -> {px['date'].max().date()}")

    # segnali momentum (modello validato) sugli unicorni
    sig = bt.build_signals(px[px["ticker"].isin(uni)], bt.score_new, horizons=(5, 10, 20))
    sig = _add_regime(sig, px)
    col = f"fwd_{hz}_net"
    sig = sig.dropna(subset=[col])
    print(f"[uni-val] segnali momentum sugli unicorni: {len(sig)}")

    # crescita ricavi PIT per ogni segnale
    print("[uni-val] scarico fondamentali SEC per la crescita PIT...")
    t2c = fp.ticker_to_cik()
    rev_points = {}
    for tk in sig["ticker"].unique():
        cik = t2c.get(tk)
        if not cik:
            continue
        try:
            facts = json.loads(fp.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"))
            rev_points[tk] = _rev_points(facts)
        except Exception as e:
            print(f"  {tk}: SEC ERR {repr(e)[:50]}")
    sig["pit_rev_yoy"] = [
        _pit_rev_yoy(rev_points.get(r.ticker, []), r.date.strftime("%Y-%m-%d"))
        for r in sig.itertuples()]
    n_growth = sig["pit_rev_yoy"].notna().sum()
    print(f"[uni-val] segnali con crescita PIT: {n_growth} ({n_growth*100//max(len(sig),1)}%)")

    header = f"  {'selezione':28s}{'n':>5}{'mean%':>8}{'med%':>8}{'win%':>7}{'Sharpe':>8}{'PF':>7}"
    p80 = sig["score"].quantile(0.80)
    top = sig[sig["score"] >= p80].copy()

    # ── A) Il momentum funziona sugli unicorni? (confronto col mega-cap base) ──
    print("\n" + "=" * 74)
    print(f"A) MOMENTUM SUGLI UNICORNI vs MEGA-CAP — top-quintile, hold {hz}gg (netto)")
    print("=" * 74)
    print(header)
    print(_row("unicorni (tutti)", _metrics(sig[col] / 100, hz)))
    print(_row("unicorni top-quintile", _metrics(top[col] / 100, hz)))
    # confronto mega-cap: stesso modello sul dataset lungo (45 USA originari)
    mega = _megacap_topq(hz, col)
    if mega is not None:
        print(_row("mega-cap top-quintile", mega))

    # ── B) Iper-crescita PIT dentro il top-quintile, per regime ───────────────
    print("\n" + "=" * 74)
    print(f"B) IPER-CRESCITA PIT dentro il top-quintile, per regime (hold {hz}gg)")
    print("=" * 74)
    tg = top[top["pit_rev_yoy"].notna()].copy()
    for reg in ["bull", "bear"]:
        sub = tg[tg["regime"] == reg]
        print(f"\n  --- regime {reg.upper()} (n={len(sub)}) ---")
        print(header)
        hi = sub[sub["pit_rev_yoy"] >= 0.25]
        lo = sub[sub["pit_rev_yoy"] < 0.25]
        print(_row("tutti", _metrics(sub[col] / 100, hz)))
        print(_row("iper-crescita (YoY>=25%)", _metrics(hi[col] / 100, hz)))
        print(_row("crescita bassa (<25%)", _metrics(lo[col] / 100, hz)))

    # ── C) Correlazione continua crescita↔ritorno ────────────────────────────
    print("\n" + "=" * 74)
    print("C) SPEARMAN crescita PIT ↔ forward return (top-quintile unicorni)")
    print("=" * 74)
    for reg in ["bull", "bear"]:
        sub = tg[tg["regime"] == reg].dropna(subset=["pit_rev_yoy", col])
        if len(sub) > 10:
            c = sub[["pit_rev_yoy", col]].corr("spearman").iloc[0, 1]
            print(f"  {reg:5s}: Spearman {c:+.4f} (n={len(sub)})")
        else:
            print(f"  {reg:5s}: campione insufficiente (n={len(sub)})")

    print("\n[uni-val] NB: high-beta. Leggere mean E drawdown/varianza insieme; effetto crescita")
    print("  spesso concentrato per regime. Decidere se aggiungere a TICKERS o tenere in watchlist.")
    return sig


def live_sleeve(min_score=50.0, growth_gate=0.25, out_path="data/unicorn_sleeve.csv"):
    """Sleeve high-beta OPERATIVO: unicorni che OGGI passano il gate validato in run().

    Regola validata (unicorn_validate.run): un segnale momentum su un unicorno vale solo se il
    nome e' ANCORA in iper-crescita (rev YoY >= 25% PIT). I nomi a crescita decelerata sono
    trappole momentum (ritorno bull negativo). Qui si applica la regola ai dati correnti.

    Output: data/unicorn_sleeve.csv con score momentum corrente, crescita PIT, e flag PASS.
    NB: high-beta -> usare come SATELLITE a size ridotta dentro il gate di regime del modello.
    """
    uni = top_unicorns(min_score=min_score, exclude=set(__import__("fetch_data").TICKERS))
    px = fetch_prices(uni)
    if px is None:
        print("[sleeve] nessun prezzo."); return None
    t2c = fp.ticker_to_cik()
    today = datetime.date.today().strftime("%Y-%m-%d")

    rows = []
    for tk in uni:
        d = px[px["ticker"] == tk].sort_values("date").dropna(subset=["close"]).reset_index(drop=True)
        if len(d) < 230:
            continue
        score = bt.score_new(d["close"], d["high"], d["low"], len(d) - 1)
        if score is None:
            continue
        yoy = None
        cik = t2c.get(tk)
        if cik:
            try:
                facts = json.loads(fp.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"))
                yoy = _pit_rev_yoy(_rev_points(facts), today)
            except Exception:
                pass
        rows.append(dict(ticker=tk, mom_score=round(float(score), 3),
                         rev_yoy=round(yoy, 4) if yoy is not None else None,
                         price=round(float(d["close"].iloc[-1]), 2)))

    if not rows:
        print("[sleeve] nessun candidato con storico sufficiente."); return None
    df = pd.DataFrame(rows)
    thr = df["mom_score"].quantile(0.80)
    df["topq"] = df["mom_score"] >= thr
    df["hypergrowth"] = df["rev_yoy"].apply(lambda x: x is not None and x >= growth_gate)
    df["PASS"] = df["topq"] & df["hypergrowth"]
    df = df.sort_values(["PASS", "mom_score"], ascending=[False, False])

    if out_path:
        df.to_csv(out_path, index=False)
    print("\n" + "=" * 60)
    print(f" SLEEVE UNICORNI OPERATIVO — {today} (gate: top-quintile mom + rev YoY>={growth_gate:.0%})")
    print("=" * 60)
    print(f" {'TICK':7s}{'MOM':>7s}{'REV_YoY':>9s}{'TOPQ':>6s}{'HYPER':>7s}{'PASS':>6s}")
    for r in df.itertuples():
        yoy = "N/A" if r.rev_yoy is None else f"{r.rev_yoy*100:.0f}%"
        print(f" {r.ticker:7s}{r.mom_score:7.3f}{yoy:>9s}{str(r.topq):>6s}{str(r.hypergrowth):>7s}"
              f"{('SI' if r.PASS else '-'):>6s}")
    n_pass = int(df["PASS"].sum())
    print(f"\n [sleeve] {n_pass} unicorni passano il gate -> {out_path}")
    print(" [sleeve] high-beta: usare come SATELLITE a size ridotta, dentro il gate di regime.")
    return df


_MEGA_SIG = None   # cache dei segnali mega-cap (build_signals e' caro: non rifarlo per ogni hz)

def _megacap_topq(hz, col):
    """Stesso modello sui 45 mega-cap USA originari (dal dataset lungo), per confronto equo.
    I segnali (indipendenti dall'orizzonte) sono cachati: run(10) e run(20) non li ricostruiscono."""
    global _MEGA_SIG
    if not os.path.exists(LONG_PATH):
        return None
    if _MEGA_SIG is None:
        mega_tickers = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "AVGO", "TSLA", "LLY", "JPM",
                        "V", "UNH", "XOM", "COST", "HD", "PG", "JNJ", "ORCL", "BAC", "NFLX",
                        "AMD", "CRM", "KO", "CVX", "MRK", "WMT", "PLTR", "GE", "CAT", "GS",
                        "ADBE", "QCOM", "TXN", "ABBV", "PEP", "MCD", "ACN", "INTC", "CSCO", "NOW",
                        "AMAT", "DIS", "TMO", "ABT", "LIN"]
        long = pd.read_csv(LONG_PATH, parse_dates=["date"]).dropna(subset=["close"])
        long = long[long["ticker"].isin(mega_tickers)]
        _MEGA_SIG = bt.build_signals(long, bt.score_new, horizons=(5, 10, 20))
    sig = _MEGA_SIG
    if sig.empty or col not in sig.columns:
        return None
    sig = sig.dropna(subset=[col])
    top = sig[sig["score"] >= sig["score"].quantile(0.80)]
    return _metrics(top[col] / 100, hz)


if __name__ == "__main__":
    run(hz=10)
    print("\n\n########## ORIZZONTE 20gg ##########")
    run(hz=20)
    print("\n\n########## SLEEVE OPERATIVO (dati correnti) ##########")
    live_sleeve()
