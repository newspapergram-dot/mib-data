"""target_backtest.py — Valida e tara i moltiplicatori dei target su simulazione
PATH-BASED (uscita a target/stop/timeout), riusando i segnali di backtest_v3.

Due viste:
  - sweep_single(): un target singolo a m*ATR -> hit%, stop%, expectancy, exp/sd.
  - compare_ladder(): exit laddered [0.5/0.25/0.25] su terne (T1,T2,T3) -> expectancy,
    mediana, win%, exp/sd. Serve a scegliere i moltiplicatori di trade_proposal.

Stop replicato da trade_proposal: max(entry*0.95, entry-2*ATR). Stop controllato
PRIMA dei target nella stessa barra (conservativo). Costi round-trip come build_signals.
"""
import numpy as np
import pandas as pd
import backtest_v3 as bt
from indicators import atr_wilder

COST = (5.0 + 2.0) / 1e4 * 2 * 100          # round-trip %  (= 0.14%)
FRAC = (0.5, 0.25, 0.25)


def _signals(px, top_q=0.80):
    sig = bt.build_signals(px, bt.score_new, horizons=(5, 10, 20))
    sig = sig[sig["score"] >= sig["score"].quantile(top_q)].copy()
    frames = {tk: px[px.ticker == tk].sort_values("date").dropna(subset=["close"]).reset_index(drop=True)
              for tk in sig["ticker"].unique()}
    return sig, frames


def _entry_atr_path(g, idx, N):
    if idx + 1 >= len(g) or idx < 15:
        return None
    entry = float(g["close"].iloc[idx])
    atr = float(atr_wilder(g["high"].iloc[:idx+1], g["low"].iloc[:idx+1], g["close"].iloc[:idx+1], 14).iloc[-1])
    if not np.isfinite(atr) or atr <= 0:
        return None
    H = g["high"].iloc[idx+1:idx+1+N].values
    L = g["low"].iloc[idx+1:idx+1+N].values
    C = g["close"].iloc[idx+1:idx+1+N].values
    if len(C) == 0:
        return None
    return entry, atr, H, L, C


def sweep_single(px, N=10, grid=(1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10)):
    sig, frames = _signals(px)
    print(f"\n=== SWEEP target singolo, N={N} (top-quintile, netto {COST:.2f}%) ===")
    print(f"{'m·ATR':>6}{'n':>5}{'hit%':>7}{'stop%':>7}{'time%':>7}{'exp%':>8}{'med%':>7}{'exp/sd':>8}")
    for m in grid:
        rets = []; hits = stops = 0
        for r in sig.itertuples():
            ea = _entry_atr_path(frames[r.ticker], r.t, N)
            if ea is None:
                continue
            entry, atr, H, L, C = ea
            stop = max(entry*0.95, entry - 2*atr); T = entry + m*atr
            n = len(C); esito = "time"; rg = (C[-1]/entry-1)*100
            for i in range(n):
                if L[i] <= stop:
                    esito, rg = "stop", (stop/entry-1)*100; break
                if H[i] >= T:
                    esito, rg = "target", (T/entry-1)*100; break
            rets.append(rg - COST); hits += esito == "target"; stops += esito == "stop"
        a = np.array(rets); n = len(a)
        if not n:
            continue
        print(f"{m:6.1f}{n:5d}{hits/n*100:7.1f}{stops/n*100:7.1f}{(n-hits-stops)/n*100:7.1f}"
              f"{a.mean():8.2f}{np.median(a):7.2f}{a.mean()/(a.std(ddof=1) or 1e-9):8.3f}")


def compare_ladder(px, configs, N=10):
    sig, frames = _signals(px)
    print(f"\n=== LADDERED {FRAC}, N={N} (netto {COST:.2f}%) ===")
    print(f"{'config':20s}{'n':>5}{'exp%':>8}{'med%':>7}{'win%':>7}{'exp/sd':>8}")
    for name, (katr, krr) in configs.items():
        rets = []
        for r in sig.itertuples():
            ea = _entry_atr_path(frames[r.ticker], r.t, N)
            if ea is None:
                continue
            entry, atr, H, L, C = ea
            stop = max(entry*0.95, entry - 2*atr); risk = entry - stop
            Ts = [entry + max(katr[k]*atr, krr[k]*risk) for k in range(3)]
            rem = 1.0; acc = 0.0; ti = 0
            for i in range(len(C)):
                if L[i] <= stop:
                    acc += rem*(stop/entry-1)*100; rem = 0.0; break
                while ti < 3 and H[i] >= Ts[ti]:
                    acc += FRAC[ti]*(Ts[ti]/entry-1)*100; rem -= FRAC[ti]; ti += 1
            if rem > 0:
                acc += rem*(C[-1]/entry-1)*100
            rets.append(acc - COST)
        a = np.array(rets)
        print(f"{name:20s}{len(a):5d}{a.mean():8.2f}{np.median(a):7.2f}{(a>0).mean()*100:7.1f}"
              f"{a.mean()/(a.std(ddof=1) or 1e-9):8.3f}")


if __name__ == "__main__":
    px = pd.read_csv("data/mib_data.csv", parse_dates=["date"]).dropna(subset=["close"])
    CONFIGS = {                       # (k_ATR T1/T2/T3, R-floor T1/T2/T3)
        "(3,6,10) exp-max":  ((3.0, 6.0, 10.0), (1.5, 3.0, 5.0)),
        "(2,6,10) DEFAULT":  ((2.0, 6.0, 10.0), (1.2, 3.0, 5.0)),
        "(2,4,6) tight":     ((2.0, 4.0, 6.0),  (1.2, 2.5, 4.0)),
    }
    for N in (10, 20):
        sweep_single(px, N=N)
        compare_ladder(px, CONFIGS, N=N)
