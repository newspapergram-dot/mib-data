#!/usr/bin/env python3
"""fix4_validate.py — FIX 4: dimensionare la size con conferma-volume / smart money alza lo Sharpe?

Test A/B sul ciclo completo (build_signals di backtest_v3, score NUOVO validato, holding 10gg).
Tutti gli schemi selezionano lo STESSO top-quintile dello score; cambia solo il PESO di size:

  A) EQUAL            peso 1 (baseline attuale del portfolio_sim)
  B) SMART-MONEY      tier come portfolio_builder: sm>=.33 -> 1.0 ; sm in [-.15,.33) -> 0.55 ;
                      sm < -.15 (distribuzione) -> ESCLUSO
  C) VOLUME-CONFIRM   conferma-volume sul breakout (FIX 4 dell'auditor): volR>=1.2 -> 1.0 ;
                      volR in [0.8,1.2) -> 0.7 ; volR < 0.8 (breakout su volume debole) -> 0.45
  D) COMBINED         B x C (entrambe le leve)

Il rendimento di portafoglio per data e' la media PESATA dei rendimenti netti dei nomi
selezionati quel giorno: sum(w_i r_i)/sum(w_i). Sharpe/MaxDD/Sortino via perf_metrics.

Rigore (coerente col DSR<0.95 del repo): bootstrap a blocchi PAIRED sulle date — ogni
ricampionamento valuta tutti gli schemi sulle STESSE date, cosi' la differenza di Sharpe
(variante - baseline) e' misurata appaiata, con IC 95%. Si testano 3 varianti: un vincitore
deve superare una soglia piu' alta (multiple testing), quindi si chiede che l'IC della
differenza escluda lo 0.

Tutto point-in-time: sm e vol_ratio calcolati con i soli dati fino alla data del segnale.
"""
import numpy as np
import pandas as pd
import backtest_v3 as bt
from volume_tools import smart_money_signal, volume_anomaly

HZ = 10
TOP_Q = 0.80
ANN = 252


def _pit_sm_vol(g, idx):
    """smart money score e vol_ratio del giorno-segnale, solo dati fino a idx (no lookahead)."""
    sl = g.iloc[:idx + 1]
    sm = smart_money_signal(sl)
    va = volume_anomaly(sl)
    return (sm["score"] if sm["score"] is not None else np.nan,
            va["vol_ratio"] if va["vol_ratio"] is not None else np.nan)


def _sm_tier(sm):
    if sm < -0.15:
        return 0.0          # distribuzione: esclusa
    return 1.0 if sm >= 0.33 else 0.55


def _vol_tier(volr):
    if np.isnan(volr):
        return 0.7          # volume non valutabile: peso neutro
    if volr >= 1.2:
        return 1.0
    return 0.7 if volr >= 0.8 else 0.45


def _weighted_daily(sel, wcol):
    """Serie di rendimenti netti di portafoglio per data = media pesata wcol su fwd_HZ_net."""
    col = f"fwd_{HZ}_net"
    d = sel.dropna(subset=[col]).copy()
    d = d[d[wcol] > 0]
    if d.empty:
        return pd.Series(dtype=float)

    def agg(grp):
        w = grp[wcol].values
        r = grp[col].values / 100.0
        return float((w * r).sum() / w.sum())
    return d.groupby("date").apply(agg).sort_index()


def _sharpe(r):
    r = pd.Series(r).dropna()
    if len(r) < 5 or r.std(ddof=1) == 0:
        return np.nan
    return float(r.mean() / r.std(ddof=1) * np.sqrt(ANN))


def _maxdd(r):
    eq = (1 + pd.Series(r).dropna()).cumprod()
    return float((eq / eq.cummax() - 1).min())


def run(px_path="data/mib_data.csv", n_boot=2000, block=10, seed=42):
    px = pd.read_csv(px_path, parse_dates=["date"]).dropna(subset=["close"])
    print(f"[fix4] build_signals (score NUOVO, holding {HZ}gg)...", flush=True)
    sig = bt.build_signals(px, bt.score_new, horizons=(5, 10, 20))
    frames = {tk: px[px.ticker == tk].sort_values("date").dropna(subset=["close"]).reset_index(drop=True)
              for tk in sig["ticker"].unique()}
    smv, volr = [], []
    for r in sig.itertuples():
        s, v = _pit_sm_vol(frames[r.ticker], r.t)
        smv.append(s); volr.append(v)
    sig["sm"] = smv
    sig["volr"] = volr

    p80 = sig["score"].quantile(TOP_Q)
    sel = sig[sig["score"] >= p80].copy().dropna(subset=[f"fwd_{HZ}_net"])
    sel["w_equal"] = 1.0
    sel["w_sm"] = sel["sm"].apply(lambda x: _sm_tier(x) if not np.isnan(x) else 0.55)
    sel["w_vol"] = sel["volr"].apply(_vol_tier)
    sel["w_comb"] = sel["w_sm"] * sel["w_vol"]

    schemes = {"A EQUAL": "w_equal", "B SMART-MONEY": "w_sm",
               "C VOLUME-CONFIRM": "w_vol", "D COMBINED": "w_comb"}

    # serie giornaliere per schema (paired sulle stesse date)
    daily = {name: _weighted_daily(sel, wcol) for name, wcol in schemes.items()}
    # allinea le date (union); le date senza nomi pesati restano NaN -> escluse pairwise
    D = pd.DataFrame(daily).sort_index()

    print(f"\n[fix4] segnali top-quintile: {len(sel)} | date operative: {len(D)} | "
          f"campione 2018-2026\n")
    print(f" {'SCHEMA':18s}{'n_date':>7s}{'Sharpe':>8s}{'MaxDD%':>8s}{'CAGR%':>8s}{'mean%/op':>9s}")
    base = D["A EQUAL"]
    rows = {}
    for name in schemes:
        r = D[name].dropna()
        m = bt.perf_metrics(r, ann=ANN, label=name)
        rows[name] = r
        print(f" {name:18s}{len(r):7d}{m.get('Sharpe_ann', np.nan):8.2f}"
              f"{m.get('MaxDD_pct', np.nan):8.1f}{m.get('CAGR_pct', np.nan):8.1f}"
              f"{r.mean()*100:9.3f}")

    # ---- paired block bootstrap sulle differenze di Sharpe vs baseline ----
    print(f"\n[fix4] bootstrap a blocchi PAIRED (block={block}, n_boot={n_boot}) — "
          f"Δ Sharpe vs A EQUAL:")
    idx = D.index.to_numpy()
    n = len(idx)
    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(n / block))
    deltas = {name: [] for name in schemes if name != "A EQUAL"}
    base_sh = []
    for _ in range(n_boot):
        starts = rng.integers(0, n, size=n_blocks)
        sel_idx = np.concatenate([np.arange(s, min(s + block, n)) for s in starts])[:n]
        sub = D.iloc[sel_idx]
        b = _sharpe(sub["A EQUAL"])
        base_sh.append(b)
        for name in deltas:
            deltas[name].append(_sharpe(sub[name]) - b)
    print(f"   baseline Sharpe IC95%: [{np.nanpercentile(base_sh, 2.5):+.2f}, "
          f"{np.nanpercentile(base_sh, 97.5):+.2f}]")
    print(f" {'VARIANTE':18s}{'ΔSharpe':>9s}{'IC95% Δ':>20s}{'p(Δ>0)':>9s}  verdetto")
    for name, ds in deltas.items():
        ds = np.array(ds)
        lo, hi = np.nanpercentile(ds, 2.5), np.nanpercentile(ds, 97.5)
        med = np.nanmedian(ds)
        p_pos = float(np.nanmean(ds > 0))
        verdict = "REALE (IC esclude 0)" if lo > 0 else (
                  "PEGGIORA (IC<0)" if hi < 0 else "RUMORE (IC attraversa 0)")
        print(f" {name:18s}{med:+9.2f}{f'[{lo:+.2f}, {hi:+.2f}]':>20s}{p_pos:9.2f}  {verdict}")

    print("\n[fix4] NB: 3 varianti testate -> multiple testing: accettare un fix solo se l'IC95%")
    print("      della differenza esclude lo 0 (non basta p(Δ>0) alto). Coerente con DSR<0.95.")
    return D


if __name__ == "__main__":
    run()
