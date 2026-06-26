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
from modules.fundamentals import _load_pit_csv, pit_quality_score

DUAL = {"STM": {"STMMI.MI", "STMPA.PA"}, "STLA": {"STLAM.MI", "STLAP.PA"}}


def _load_fundamentals():
    """Merge fondamentali per il fq tier: USA (SEC PIT) + EU (Yahoo best-effort).
    Le righe EU hanno gli stessi campi-metrica (net_margin, current_ratio, ocf_margin, roe)
    che pit_quality_score usa. USA ha precedenza se un ticker comparisse in entrambi."""
    rows = {}
    if os.path.exists("data/fundamentals_eu.csv"):
        import csv as _csv
        with open("data/fundamentals_eu.csv", newline="") as f:
            for r in _csv.DictReader(f):
                rows[r["ticker"]] = r
    rows.update(_load_pit_csv())   # USA sovrascrive eventuali collisioni
    return rows


def _fundamental_tier(tk, pit_rows, defensive=False):
    """Leva di size da QUALITA' FONDAMENTALE PIT (SEC EDGAR), validata su ciclo completo
    2018-2026 in `pit_validate.py`.

    SCOPERTA della validazione: la qualita' fondamentale e' una leva DIFENSIVA, non un
    miglioramento universale. Segmentando per regime (top-quintile USA):
      - in BULL il filtro PIT>=0.60 PEGGIORA (ret -0.28%/-0.50%, Sharpe -0.16/-0.11 a 10/20gg):
        nel momentum rialzista anche i nomi a qualita' piu' bassa corrono -> penalizzarli costa.
      - in BEAR il filtro AIUTA (ret +0.63%/+0.82%, win +3.7%/+3.5%, Sharpe +0.48/+0.34):
        flight-to-quality, i fondamentali solidi proteggono. Spearman bear +0.16/+0.19 vs ~0 in bull.
    (Il +3.30% del backtest sez.9 era un artefatto del solo sotto-periodo bull a 14 mesi.)

    Quindi la leva si applica SOLO in regime difensivo (`defensive=True`, mercato non in
    TREND_UP). In TREND_UP resta NEUTRA (label informativo, size piena): non penalizzare la
    qualita' bassa quando il momentum la premia.

    Restituisce (fq_mult, fq_label). Copre USA (SEC PIT vero) ed EU (Yahoo best-effort, restated,
    NON PIT vero — vedi fundamentals_eu.py); chi non ha dati resta `n/d` neutro (N/A != veto).
    Coerente con Lezione #6 (scala la size, non escludere) e #9 (leva condizionale, non blend).
    """
    row = pit_rows.get(tk)
    fq = pit_quality_score(row) if row else None
    if fq is None:
        return 1.0, "n/d"
    label = "Q+" if fq >= 0.60 else ("Q" if fq >= 0.40 else "Q-")
    if not defensive:
        return 1.0, label                 # in TREND_UP la qualita' non aiuta: lever neutro
    mult = 1.0 if fq >= 0.60 else (0.85 if fq >= 0.40 else 0.70)
    return mult, label


def _unicorn_satellite(capital, p50, regime_by_mkt, mult_by_mkt, ok_regimes,
                       budget_left, sleeve_cap=0.15, max_uni=3,
                       sleeve_path="data/unicorn_sleeve.csv",
                       px_path="data/mib_data_unicorns.csv"):
    """Sleeve HIGH-BETA unicorni, validato in unicorn_validate (Run #17).

    Regola validata: un segnale momentum su un unicorno e' edge SOLO se il nome e' ANCORA in
    iper-crescita (rev YoY>=25% PIT); i growth decelerati sono trappole momentum (ret bull neg).
    Gli unicorni come gruppo DILUISCONO il modello (Sharpe 0.15 vs 0.64 mega-cap) -> qui NON
    entrano nell'universo core: sono un satellite separato, GATED e a size ridotta (high-beta).

    Gate: hypergrowth (da unicorn_sleeve.csv) AND momentum >= p50 (stessa soglia core) AND
    regime USA operabile AND non in distribuzione (sm>=-0.15) AND volume affidabile.
    Sizing: pos_cap 5% (meta' del core) + size_mult 0.5 (high-beta) + regime_mult del mercato US.
    Esposizione totale del sleeve limitata a `sleeve_cap` del capitale.

    Ritorna lista di (info_dict, proposal). Vuota se il file manca, il regime USA non e'
    operabile, o nessun nome passa il gate (output legittimo: niente da comprare, L#5).
    """
    if "US" not in [m for m in regime_by_mkt] or regime_by_mkt.get("US") not in ok_regimes:
        return []   # unicorni sono USA: se US non operabile (es. go-flat in PULLBACK), niente sleeve
    if not (os.path.exists(sleeve_path) and os.path.exists(px_path)):
        return []
    import csv as _csv
    with open(sleeve_path) as f:
        sleeve = {r["ticker"]: r for r in _csv.DictReader(f)}
    px = pd.read_csv(px_path, parse_dates=["date"]).sort_values(["ticker", "date"])

    cands = []
    for tk, srow in sleeve.items():
        hyper = str(srow.get("hypergrowth", "")).strip().lower() in ("true", "1")
        try:
            mom = float(srow.get("mom_score") or "nan")
        except ValueError:
            mom = float("nan")
        if not hyper or not (mom >= p50):
            continue                       # gate crescita + momentum (soglia core)
        d = px[px.ticker == tk].sort_values("date")
        if len(d) < 30:
            continue
        sm = smart_money_signal(d)
        smv = sm["score"] if sm["score"] is not None else 0.0
        vq = validate_volume(d.tail(60))
        if smv < -0.15 or not bool(vq["reliable"]):
            continue                       # non in distribuzione + volume affidabile
        rev_yoy = srow.get("rev_yoy", "")
        cands.append(dict(ticker=tk, score=mom, sm=round(smv, 2),
                          rev_yoy=(float(rev_yoy) if rev_yoy not in ("", "None") else None),
                          price=float(d.close.iloc[-1]),
                          atr=float(atr_wilder(d.high, d.low, d.close, 14).iloc[-1]),
                          sm_label=sm["label"].split(" (")[0]))
    cands.sort(key=lambda c: c["score"], reverse=True)

    sleeve_budget = min(budget_left, sleeve_cap * capital)
    picked, spent = [], 0.0
    for c in cands[:max_uni]:
        p = propose(c["ticker"], entry=c["price"], atr14=c["atr"], score=c["score"],
                    capital=capital, regime_mult=mult_by_mkt.get("US", 0.5),
                    size_mult=0.5, pos_cap=0.05)   # high-beta: meta' cap, meta' size
        if p["shares"] <= 0 or spent + p["pos_value"] > sleeve_budget:
            continue
        picked.append((c, p))
        spent += p["pos_value"]
    return picked


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
          include_unicorns=True,
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
    pit_rows = _load_fundamentals()   # fondamentali USA (SEC PIT) + EU (Yahoo, best-effort)

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
        # leva qualita' fondamentale PIT: DIFENSIVA (validata: aiuta in bear, non in bull).
        # Morde solo se il mercato del titolo NON e' in TREND_UP; in TREND_UP resta neutra.
        fq_defensive = regime_by_mkt.get(mkt) != "TREND_UP"
        fq_mult, fq_label = _fundamental_tier(tk, pit_rows, defensive=fq_defensive)
        size_mult = float(np.clip(s_base * sm_tier * fq_mult * (0.6 if tk in ILLIQUID else 1.0), 0.3, 1.0))
        # confidenza con soglie LIVE (percentili della selezione corrente)
        conf = confidence_level(s, tk, hi=p90, mid=p60)
        conv = 0.45 * s + 0.55 * max(smv, 0)               # ranking: SM pesa piu' dello score
        rows.append(dict(ticker=tk, score=s, mkt=mkt, sm=round(smv, 2),
                         sm_label=sm["label"].split(" (")[0], tier=s_tier, role=role, conf=conf,
                         fq=fq_label, size_mult=round(size_mult, 2), conv=conv, ok=ok,
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

    # SLEEVE high-beta unicorni (satellite separato, gated su iper-crescita PIT; vedi Run #17).
    uni_picked = []
    if include_unicorns:
        uni_picked = _unicorn_satellite(capital, p50, regime_by_mkt, mult_by_mkt,
                                        _ok_regimes, budget_left=budget - exposure)

    L = []
    w = L.append
    w("=" * 92)
    w(f" PORTAFOGLIO DIVERSIFICATO — {asof}  (capitale {capital:.0f} EUR)")
    w("=" * 92)
    w(" MODELLO AFFIDABILE (validato in backtest): filtro SMART MONEY = leva di affidabilita'.")
    w(" Accumulazione (sm>=.33) = CORE piena size; neutro = SAT size ridotta; distribuzione ESCLUSA.")
    w(" ROBUSTEZZA CICLO COMPLETO 2018-2026 (robustness_consolidate): Sharpe 1.0, MaxDD -13.8%,")
    w("   CAGR +14%, PSR 0.98 (edge REALE) ma DSR<0.95 (non blindato) -> SIZE MODERATA, mai leverage:")
    w("   il profitto si protegge col gate di regime + STOP, non con un Sharpe alto (bull-concentrato).")
    w(" QUALITA' FONDAMENTALE PIT (SEC EDGAR): leva DIFENSIVA (validata 2018-2026, pit_validate).")
    w("   Aiuta in BEAR (ret +0.63%/win +3.7%/Sharpe +0.48), non in bull -> morde solo nei mercati")
    w("   NON in TREND_UP (Q+ piena, Q/Q- ridotta); in TREND_UP neutra. USA only (EU=n/d).")
    w(f" Score top-meta' (>= {p50:.3f}); confidenza su percentili LIVE; dedup emittente.")
    w(f" Universo {px.ticker.nunique()} ticker, {len(score)} gated. "
      f"Regime: " + " ".join(f"{m}={regime_by_mkt.get(m)}" for m in ('IT', 'FR', 'US')))
    w("")
    n_core = sum(1 for r, _ in picked if r.role == "CORE")
    w(f" SELEZIONATI: {len(picked)} ({n_core} CORE / {len(picked)-n_core} SAT) | "
      f"esposizione {exposure:.0f} EUR ({exposure/capital*100:.0f}% del capitale)")
    w("-" * 92)
    w(f" {'TICK':9s}{'SCORE':>6s}{'SM$':>6s}{'ROLE':>5s}{'FQ':>4s}{'CONF':>6s}{'SIZE×':>6s}{'AZ':>5s}{'VALORE':>9s}"
      f"{'T1%':>7s}{'T2%':>7s}{'T3%':>7s}")
    t1 = t2 = t3 = 0.0
    expo_mkt = {}
    for r, p in picked:
        w(f" {r.ticker:9s}{r.score:6.3f}{r.sm:6.2f}{r.role:>5s}{r.fq:>4s}{r.conf:>6s}{r.size_mult:6.2f}{p['shares']:5d}"
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
    # SLEEVE HIGH-BETA UNICORNI (satellite separato dal core, gated su iper-crescita PIT).
    w("-" * 92)
    if uni_picked:
        uni_expo = sum(p["pos_value"] for _, p in uni_picked)
        ut1 = sum(p["g1_eur"] for _, p in uni_picked)
        w(f" SLEEVE HIGH-BETA UNICORNI: {len(uni_picked)} nomi | esposizione {uni_expo:.0f} EUR "
          f"({uni_expo/capital*100:.0f}%) — satellite, size ridotta (gate: momentum + rev YoY>=25% PIT)")
        w(f" {'TICK':9s}{'MOM':>6s}{'SM$':>6s}{'REVyoy':>8s}{'AZ':>5s}{'VALORE':>9s}{'T1%':>7s}{'T2%':>7s}{'T3%':>7s}")
        for c, p in uni_picked:
            ry = "N/A" if c["rev_yoy"] is None else f"{c['rev_yoy']*100:.0f}%"
            w(f" {c['ticker']:9s}{c['score']:6.3f}{c['sm']:6.2f}{ry:>8s}{p['shares']:5d}"
              f"{p['pos_value']:9.0f}{p['g1_pct']:7.1f}{p['g2_pct']:7.1f}{p['g3_pct']:7.1f}")
        w(" (HIGH-BETA: validato come edge SOLO se ancora in iper-crescita; size dimezzata, stop non negoziabile.)")
    else:
        _why = ("regime USA non operabile (go-flat)" if regime_by_mkt.get("US") not in _ok_regimes
                else "nessun unicorno passa il gate momentum+iper-crescita oggi")
        w(f" SLEEVE HIGH-BETA UNICORNI: nessun nome ({_why}).")
    w("")
    w("=" * 92); w(" SCHEDE OPERATIVE"); w("=" * 92)
    for r, p in picked:
        w(""); w(render(p))
        w(f" FOREGROUND: sm {r.sm:+.2f} ({r.sm_label}) | {r.role} | FQ {r.fq} | conf {r.conf} | tier {r.tier} | {r.mkt}")
        w("=" * 58)
    for c, p in uni_picked:
        w(""); w(render(p))
        w(f" UNICORNO HIGH-BETA: mom {c['score']:+.3f} | sm {c['sm']:+.2f} ({c['sm_label']}) | "
          f"rev YoY {'N/A' if c['rev_yoy'] is None else format(c['rev_yoy']*100, '.0f')+'%'} | satellite size ridotta")
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
