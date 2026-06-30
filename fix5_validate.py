#!/usr/bin/env python3
"""fix5_validate.py — FIX 5: il sizing a RISCHIO PARITARIO (inverse-ATR) abbatte il MaxDD?

Test A/B sul ciclo completo (build_signals di backtest_v3, score NUOVO validato, holding 10gg).
Tutti gli schemi selezionano lo STESSO top-quintile dello score; cambia solo il PESO di size:

  A) EQUAL            peso 1 (baseline attuale del portfolio_sim)
  B) RISK-PARITY      rischio paritario: peso ∝ 1/ATR%14 (inverse-vol) -> ogni nome contribuisce
                      ~lo stesso rischio; i nomi piu' volatili pesano meno
  C) RP-CAPPED        come B ma con cap del rapporto di peso (un nome a bassa vol non puo' pesare
                      piu' di CAP volte la media): risk parity robusta agli outlier di bassa vol

Rendimento di portafoglio per data = media PESATA dei rendimenti netti: sum(w_i r_i)/sum(w_i).

DECISIONE (richiesta dall'utente): integrare in portfolio_builder SOLO se il MaxDD si abbatte
in modo SISTEMATICO, cioe' Δ MaxDD (variante - baseline) ha IC95% che NON attraversa lo 0 ed e'
POSITIVO (MaxDD e' negativo: variante meno negativa = drawdown ridotto). Si monitora anche lo
Sharpe (non deve peggiorare in modo significativo).

Rigore: bootstrap a blocchi PAIRED sulle date — ogni ricampionamento valuta tutti gli schemi
sulle STESSE date, quindi Δ Sharpe e Δ MaxDD sono misurati appaiati con IC 95%. Multiple testing
(2 varianti): un fix passa solo se l'IC della differenza esclude lo 0.

Point-in-time: ATR%14 calcolato dai soli dati fino alla barra di INGRESSO (nessun lookahead).
"""
import numpy as np
import pandas as pd
import backtest_v3 as bt
from indicators import atr_wilder

HZ = 10
TOP_Q = 0.80
ANN = 252
RP_CAP = 3.0          # cap del rapporto peso/media per lo schema RP-CAPPED


def _sharpe(r):
    r = pd.Series(r).dropna()
    if len(r) < 5 or r.std(ddof=1) == 0:
        return np.nan
    return float(r.mean() / r.std(ddof=1) * np.sqrt(ANN))


def _maxdd(r):
    r = pd.Series(r).dropna()
    if len(r) < 2:
        return np.nan
    eq = (1 + r).cumprod()
    return float((eq / eq.cummax() - 1).min())


def _weighted_daily(sel, wcol):
    col = f"fwd_{HZ}_net"
    d = sel.dropna(subset=[col, wcol]).copy()
    d = d[d[wcol] > 0]
    if d.empty:
        return pd.Series(dtype=float)

    def agg(grp):
        w = grp[wcol].values
        r = grp[col].values / 100.0
        return float((w * r).sum() / w.sum())
    return d.groupby("date").apply(agg).sort_index()


def run(px_path="data/mib_data_long.csv", n_boot=2000, block=10, seed=42):
    px = pd.read_csv(px_path, parse_dates=["date"]).dropna(subset=["close"])
    print(f"[fix5] build_signals (score NUOVO, holding {HZ}gg)...", flush=True)
    sig = bt.build_signals(px, bt.score_new, horizons=(5, 10, 20))

    # ATR%14 precalcolato per ticker (series allineata all'indice di frames), poi indicizzato a r.t
    frames, atrpct = {}, {}
    for tk in sig["ticker"].unique():
        g = px[px.ticker == tk].sort_values("date").dropna(subset=["close"]).reset_index(drop=True)
        frames[tk] = g
        a = atr_wilder(g["high"], g["low"], g["close"], 14)
        atrpct[tk] = (a / g["close"]).to_numpy()    # ATR in frazione di prezzo (cross-section safe)

    def _atr_at(tk, t):
        arr = atrpct[tk]
        if 0 <= t < len(arr):
            v = arr[t]
            return float(v) if np.isfinite(v) and v > 0 else np.nan
        return np.nan

    sig["atr_pct"] = [_atr_at(r.ticker, r.t) for r in sig.itertuples()]

    p80 = sig["score"].quantile(TOP_Q)
    sel = sig[sig["score"] >= p80].copy().dropna(subset=[f"fwd_{HZ}_net", "atr_pct"])
    sel["w_equal"] = 1.0
    sel["w_rp"] = 1.0 / sel["atr_pct"]                       # inverse-vol puro

    # RP-CAPPED: normalizza per la mediana del giorno e limita il rapporto a [1/CAP, CAP]
    med = sel.groupby("date")["w_rp"].transform("median")
    ratio = (sel["w_rp"] / med).clip(1.0 / RP_CAP, RP_CAP)
    sel["w_rpc"] = ratio

    schemes = {"A EQUAL": "w_equal", "B RISK-PARITY": "w_rp", "C RP-CAPPED": "w_rpc"}
    daily = {name: _weighted_daily(sel, wcol) for name, wcol in schemes.items()}
    D = pd.DataFrame(daily).sort_index()

    print(f"\n[fix5] segnali top-quintile: {len(sel)} | date operative: {len(D)} | campione 2018-2026\n")
    print(f" {'SCHEMA':16s}{'n_date':>7s}{'Sharpe':>8s}{'MaxDD%':>9s}{'CAGR%':>8s}{'Vol%ann':>9s}{'mean%/op':>9s}")
    for name in schemes:
        r = D[name].dropna()
        m = bt.perf_metrics(r, ann=ANN, label=name)
        print(f" {name:16s}{len(r):7d}{m.get('Sharpe_ann', np.nan):8.2f}{m.get('MaxDD_pct', np.nan):9.1f}"
              f"{m.get('CAGR_pct', np.nan):8.1f}{m.get('Vol_ann_pct', np.nan):9.1f}{r.mean()*100:9.3f}")

    # ---- paired block bootstrap su Δ Sharpe e Δ MaxDD vs baseline ----
    print(f"\n[fix5] bootstrap a blocchi PAIRED (block={block}, n_boot={n_boot}) — vs A EQUAL:")
    n = len(D)
    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(n / block))
    variants = [k for k in schemes if k != "A EQUAL"]
    dSh = {k: [] for k in variants}
    dDD = {k: [] for k in variants}
    for _ in range(n_boot):
        starts = rng.integers(0, n, size=n_blocks)
        sel_idx = np.concatenate([np.arange(s, min(s + block, n)) for s in starts])[:n]
        sub = D.iloc[sel_idx]
        b_sh, b_dd = _sharpe(sub["A EQUAL"]), _maxdd(sub["A EQUAL"])
        for k in variants:
            dSh[k].append(_sharpe(sub[k]) - b_sh)
            dDD[k].append(_maxdd(sub[k]) - b_dd)   # >0 = drawdown RIDOTTO (meno negativo)

    print(f" {'VARIANTE':16s}{'ΔSharpe':>9s}{'IC95% ΔSh':>18s}{'ΔMaxDD%':>9s}{'IC95% ΔMaxDD%':>22s}  verdetto MaxDD")
    decision = {}
    for k in variants:
        sh = np.array(dSh[k]); dd = np.array(dDD[k]) * 100  # ΔMaxDD in punti %
        sh_lo, sh_hi = np.nanpercentile(sh, 2.5), np.nanpercentile(sh, 97.5)
        dd_lo, dd_hi = np.nanpercentile(dd, 2.5), np.nanpercentile(dd, 97.5)
        dd_red = dd_lo > 0     # IC del ΔMaxDD interamente positivo = abbattimento sistematico
        decision[k] = dd_red
        verdict = "MaxDD ABBATTUTO (IC>0)" if dd_red else (
                  "MaxDD PEGGIORA (IC<0)" if dd_hi < 0 else "MaxDD invariato (IC attraversa 0)")
        print(f" {k:16s}{np.nanmedian(sh):+9.2f}{f'[{sh_lo:+.2f},{sh_hi:+.2f}]':>18s}"
              f"{np.nanmedian(dd):+9.2f}{f'[{dd_lo:+.2f},{dd_hi:+.2f}]':>22s}  {verdict}")

    print("\n[fix5] REGOLA DI INTEGRAZIONE: si integra in portfolio_builder solo se ΔMaxDD ha IC95%>0")
    print("       (abbattimento sistematico) senza che lo Sharpe peggiori in modo significativo.")
    winner = next((k for k in variants if decision[k]), None)
    print(f"[fix5] ESITO: {'integrare ' + winner if winner else 'NESSUNO schema abbatte il MaxDD in modo significativo -> NON integrare'}.")
    return D, decision


if __name__ == "__main__":
    run()
