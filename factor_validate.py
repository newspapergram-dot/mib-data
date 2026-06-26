"""factor_validate.py — Validazione FULL-CYCLE di fattori cross-sectional da prezzo.

Fattori testati (point-in-time, niente lookahead), tra i piu' robusti in letteratura:
  - mom12_1 : momentum 12-1 (rendimento da 12 mesi fa a 1 mese fa)  [Jegadeesh-Titman]
  - invvol  : 1 / volatilita' a 60g (anomalia low-volatility)
  - mom6    : momentum 6 mesi (controllo)

Per ogni segnale storico (build_signals su mib_data_long.csv) si calcola il fattore con i
SOLI dati fino all'ingresso, poi si misura:
  1) Spearman(fattore, forward return netto) a 10/20gg sul ciclo completo;
  2) forward return medio per QUINTILE del fattore (monotonia = fattore solido);
  3) se il fattore aggiunge valore DENTRO il top-quintile dello score (interazione).
"""
import numpy as np
import pandas as pd
import backtest_v3 as bt


def factors_for(g, t):
    """Fattori point-in-time all'indice di ingresso t (close incluso)."""
    c = g["close"]
    if t < 252:
        return None
    mom12_1 = c.iloc[t-21] / c.iloc[t-252] - 1.0
    mom6 = c.iloc[t] / c.iloc[t-126] - 1.0
    rets = c.iloc[t-60:t+1].pct_change().dropna()
    vol60 = rets.std()
    invvol = 1.0/vol60 if vol60 and vol60 > 0 else np.nan
    return mom12_1, mom6, invvol


if __name__ == "__main__":
    px = pd.read_csv("data/mib_data_long.csv", parse_dates=["date"]).dropna(subset=["close"])
    sig = bt.build_signals(px, bt.score_new, horizons=(5, 10, 20))
    frames = {tk: px[px.ticker == tk].sort_values("date").dropna(subset=["close"]).reset_index(drop=True)
              for tk in sig["ticker"].unique()}
    M, M6, IV = [], [], []
    for r in sig.itertuples():
        f = factors_for(frames[r.ticker], r.t)
        if f is None:
            M.append(np.nan); M6.append(np.nan); IV.append(np.nan)
        else:
            M.append(f[0]); M6.append(f[1]); IV.append(f[2])
    sig = sig.copy(); sig["mom12_1"] = M; sig["mom6"] = M6; sig["invvol"] = IV
    sig = sig.dropna(subset=["mom12_1", "invvol"])
    print(f"Ciclo {px['date'].min().date()}->{px['date'].max().date()} | segnali con fattori: {len(sig)}")

    print("\n=== 1) Spearman fattore vs forward return netto (full-cycle) ===")
    print(f"{'fattore':12s}{'10gg':>10s}{'20gg':>10s}")
    for f in ["score", "mom12_1", "mom6", "invvol"]:
        row = f"{f:12s}"
        for hz in (10, 20):
            col = f"fwd_{hz}_net"; d = sig.dropna(subset=[col])
            row += f"{d[[f,col]].corr('spearman').iloc[0,1]:>10.4f}"
        print(row)

    print("\n=== 2) Forward return medio (10gg) per QUINTILE del fattore ===")
    for f in ["mom12_1", "invvol"]:
        col = "fwd_10_net"; d = sig.dropna(subset=[col]).copy()
        d["q"] = pd.qcut(d[f], 5, labels=[1, 2, 3, 4, 5], duplicates="drop")
        g = d.groupby("q", observed=True)[col].mean()
        print(f"  {f:10s}: " + " | ".join(f"Q{q}={v:+.2f}%" for q, v in g.items()) +
              f"  (Q5-Q1 = {g.iloc[-1]-g.iloc[0]:+.2f}%)")

    print("\n=== 3) Il fattore aggiunge valore DENTRO il top-quintile dello score? (fwd_10) ===")
    col = "fwd_10_net"; d = sig.dropna(subset=[col])
    top = d[d["score"] >= d["score"].quantile(0.80)]
    for f in ["mom12_1", "invvol"]:
        hi = top[top[f] >= top[f].median()][col]; lo = top[top[f] < top[f].median()][col]
        print(f"  {f:10s}: top-score & fattore ALTO ret {hi.mean():+.2f}% (n={len(hi)}) vs "
              f"BASSO {lo.mean():+.2f}% (n={len(lo)})  -> spread {hi.mean()-lo.mean():+.2f}%")
