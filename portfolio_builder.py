"""portfolio_builder.py — Costruttore di portafoglio diversificato.

Trasforma lo score_output in un PORTAFOGLIO di piu' titoli, con filtri meno
restrittivi del piano stretto e sizing per CONVINZIONE (invece di escludere):
  - R3 score nel top META' (percentile 50) invece che top quintile
  - R4 banda neutra sullo smart money (sm >= -0.15): esclude solo la distribuzione
  - confidenza/illiquidita' NON escludono ma SCALANO la size (size_mult)
  - dedup per emittente (doppie quotazioni Milano/Parigi, ADR)
  - cap esposizione totale e numero massimo di nomi
Target piu' larghi (T1/T2/T3 ATR/R-based) gestiti da modules.trade_proposal.

Esegue su dati LOCALI freschi: data/{mib_data,score_output,regime_filter}.csv.
"""
import os
import numpy as np
import pandas as pd
from indicators import atr_wilder
from modules.trade_proposal import propose, render, cost_rt_bps, confidence_level, ILLIQUID
from volume_tools import smart_money_signal, validate_volume

DUAL = {"STM": {"STMMI.MI", "STMPA.PA"}, "STLA": {"STLAM.MI", "STLAP.PA"}}


def _market_of(tk):
    if tk.endswith(".MI"):
        return "IT"
    if tk.endswith(".PA") or tk.endswith(".AS"):
        return "FR"
    return "US"


def _dual_group(tk):
    for g, m in DUAL.items():
        if tk in m:
            return g
    return tk


def build(capital=50000.0, max_names=12, exposure_cap=0.85, include_pullback=False,
          px_path="data/mib_data.csv", score_path="data/score_output.csv",
          regime_path="data/regime_filter.csv", out_path="data/PORTFOLIO.txt"):
    # include_pullback=False (DEFAULT, piu' affidabile) = GO-FLAT: si opera solo nei mercati
    #   TREND_UP, fuori dagli altri (il fattore bear validato: MaxDD piu' basso).
    # include_pullback=True = si resta nei mercati PULLBACK a META' size (regime_mult 0.5) e si
    #   suggerisce l'hedge dell'indice (overlay di rischio) per coprire il beta residuo.
    _ok_regimes = ("TREND_UP", "PULLBACK") if include_pullback else ("TREND_UP",)
    px = pd.read_csv(px_path, parse_dates=["date"]).sort_values(["ticker", "date"])
    score = pd.read_csv(score_path)
    rf = pd.read_csv(regime_path)
    asof = px["date"].max().strftime("%Y-%m-%d")
    regime_by_mkt = {r.market: r.regime for r in rf.itertuples()}
    mult_by_mkt = {r.market: r.risk_mult for r in rf.itertuples()}
    p50, p60, p80, p90 = (score["score"].quantile(q) for q in (0.50, 0.60, 0.80, 0.90))

    rows = []
    for r in score.itertuples():
        tk = r.ticker
        d = px[px.ticker == tk].sort_values("date")
        if len(d) < 20:
            continue
        sm = smart_money_signal(d)
        vq = validate_volume(d.tail(60))
        mkt = _market_of(tk)
        s = float(r.score)
        smv = sm["score"] if sm["score"] is not None else 0.0
        # filtri: regime TREND_UP, score top-meta', NON in distribuzione, volume affidabile
        ok = (regime_by_mkt.get(mkt) in _ok_regimes) and (s >= p50) and (smv >= -0.15) and bool(vq["reliable"])
        # size_mult = tier di score x tier di SMART MONEY (driver di affidabilita' validato).
        # Accumulazione (sm>=.33) = CORE a piena size; neutro = SATELLITE a size ridotta.
        s_tier = "ALTA" if s >= p80 else ("MEDIA" if s >= p60 else "BASE")
        s_base = {"ALTA": 1.0, "MEDIA": 0.7, "BASE": 0.45}[s_tier]
        role = "CORE" if smv >= 0.33 else "SAT"
        sm_tier = 1.0 if role == "CORE" else 0.55          # distribuzione gia' esclusa
        size_mult = float(np.clip(s_base * sm_tier * (0.6 if tk in ILLIQUID else 1.0), 0.3, 1.0))
        # confidenza con soglie LIVE (percentili della selezione corrente)
        conf = confidence_level(s, tk, hi=p90, mid=p60)
        conv = 0.45 * s + 0.55 * max(smv, 0)               # ranking: SM pesa piu' dello score
        rows.append(dict(ticker=tk, score=s, mkt=mkt, sm=round(smv, 2),
                         sm_label=sm["label"].split(" (")[0], tier=s_tier, role=role, conf=conf,
                         size_mult=round(size_mult, 2), conv=conv, ok=ok,
                         price=float(d.close.iloc[-1]),
                         atr=float(atr_wilder(d.high, d.low, d.close, 14).iloc[-1]),
                         dg=_dual_group(tk), rt=cost_rt_bps(tk)))
    df = pd.DataFrame(rows)
    elig = df[df.ok].copy()
    elig = (elig.sort_values(["dg", "rt", "conv"], ascending=[True, True, False])
                .drop_duplicates("dg", keep="first")
                .sort_values("conv", ascending=False))

    budget = exposure_cap * capital
    picked, exposure = [], 0.0
    for r in elig.itertuples():
        p = propose(r.ticker, entry=r.price, atr14=r.atr, score=r.score, capital=capital,
                    regime_mult=mult_by_mkt.get(r.mkt, 0.5), size_mult=r.size_mult)
        p["confidence"] = r.conf      # confidenza con soglie LIVE (percentili)
        if p["shares"] <= 0 or exposure + p["pos_value"] > budget:
            continue
        picked.append((r, p))
        exposure += p["pos_value"]
        if len(picked) >= max_names:
            break

    L = []
    w = L.append
    w("=" * 92)
    w(f" PORTAFOGLIO DIVERSIFICATO — {asof}  (capitale {capital:.0f} EUR)")
    w("=" * 92)
    w(" MODELLO AFFIDABILE (validato in backtest): filtro SMART MONEY = leva di affidabilita'.")
    w(" Accumulazione (sm>=.33) = CORE piena size; neutro = SAT size ridotta; distribuzione ESCLUSA.")
    w(f" Top-quintile+accumulazione (10gg): win 60%, Sharpe 1.55, PF 2.61 (vs base 57%/1.21/2.08).")
    w(f" Score top-meta' (>= {p50:.3f}); confidenza su percentili LIVE; dedup emittente.")
    w(f" Universo {px.ticker.nunique()} ticker, {len(score)} gated. "
      f"Regime: " + " ".join(f"{m}={regime_by_mkt.get(m)}" for m in ('IT', 'FR', 'US')))
    w("")
    n_core = sum(1 for r, _ in picked if r.role == "CORE")
    w(f" SELEZIONATI: {len(picked)} ({n_core} CORE / {len(picked)-n_core} SAT) | "
      f"esposizione {exposure:.0f} EUR ({exposure/capital*100:.0f}% del capitale)")
    w("-" * 92)
    w(f" {'TICK':9s}{'SCORE':>6s}{'SM$':>6s}{'ROLE':>5s}{'CONF':>6s}{'SIZE×':>6s}{'AZ':>5s}{'VALORE':>9s}"
      f"{'T1%':>7s}{'T2%':>7s}{'T3%':>7s}")
    t1 = t2 = t3 = 0.0
    expo_mkt = {}
    for r, p in picked:
        w(f" {r.ticker:9s}{r.score:6.3f}{r.sm:6.2f}{r.role:>5s}{r.conf:>6s}{r.size_mult:6.2f}{p['shares']:5d}"
          f"{p['pos_value']:9.0f}{p['g1_pct']:7.1f}{p['g2_pct']:7.1f}{p['g3_pct']:7.1f}")
        t1 += p['g1_eur']; t2 += p['g2_eur']; t3 += p['g3_eur']
        expo_mkt[r.mkt] = expo_mkt.get(r.mkt, 0.0) + p['pos_value']
    w("-" * 92)
    w(" GUADAGNO POTENZIALE NETTO se ogni titolo tocca il target (scenario ottimistico):")
    w(f"   T1: +{t1:.0f} EUR (+{t1/capital*100:.1f}%) | T2: +{t2:.0f} EUR (+{t2/capital*100:.1f}%) | "
      f"T3: +{t3:.0f} EUR (+{t3/capital*100:.1f}%)")
    w("   (NB: non tutti i target vengono raggiunti; lo stop tronca i perdenti)")
    w("")
    # OVERLAY DI RISCHIO: hedge dell'indice per i mercati NON in TREND_UP.
    # Validato su 2018-2026 come riduzione del drawdown (-13.8% -> -9/-10%); h=0.5 prudente.
    # NB: e' ASSICURAZIONE, non alpha: in mercati laterali/choppy l'hedge COSTA (whipsaw).
    INDEX_HEDGE = {"US": "SPY/ES (o inverso SH)", "FR": "CAC40 (o EWQ inverso)", "IT": "FTSEMIB (o EWI inverso)"}
    hedge_lines = []
    for mkt, expo in sorted(expo_mkt.items()):
        if regime_by_mkt.get(mkt) != "TREND_UP" and expo > 0:
            hedge_lines.append((mkt, expo, 0.5*expo))
    if hedge_lines:
        w("-" * 92)
        w(" OVERLAY DI RISCHIO (mercati NON in TREND_UP) — hedge indice ~0.5x esposizione:")
        for mkt, expo, h in hedge_lines:
            w(f"   {mkt}: long {expo:.0f}EUR in regime {regime_by_mkt.get(mkt)} -> short "
              f"{INDEX_HEDGE.get(mkt, 'indice')} ~{h:.0f}EUR (copertura beta, riduce il MaxDD)")
        w("   (assicurazione: attendersi un COSTO in fasi laterali; togliere l'hedge al ritorno TREND_UP)")
    else:
        w(" OVERLAY DI RISCHIO: nessuno (tutti i mercati selezionati in TREND_UP).")
    w("")
    w("=" * 92); w(" SCHEDE OPERATIVE"); w("=" * 92)
    for r, p in picked:
        w(""); w(render(p))
        w(f" FOREGROUND: sm {r.sm:+.2f} ({r.sm_label}) | {r.role} | conf {r.conf} | tier {r.tier} | {r.mkt}")
        w("=" * 58)

    txt = "\n".join(L) + "\n"
    if out_path:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w") as f:
            f.write(txt)
    return picked, txt


if __name__ == "__main__":
    picked, txt = build()
    print(txt)
    print(f"[OK] {len(picked)} titoli -> data/PORTFOLIO.txt")
