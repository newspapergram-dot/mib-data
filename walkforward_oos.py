"""walkforward_oos.py — Validazione OUT-OF-SAMPLE (anchored walk-forward) del MODELLO
OPERATIVO: top-quintile dello score + filtro accumulazione Smart Money, uscita
laddered a target/stop (target tarati in trade_proposal).

Metodo (no lookahead):
  - i segnali sono ordinati per data; un warmup iniziale fa da primo IS;
  - il resto e' diviso in K finestre OOS sequenziali;
  - per ogni finestra OOS: la SOGLIA del top-quintile e' calcolata SOLO sui dati IS
    precedenti (anchored), poi il modello viene applicato ai segnali OOS mai visti;
  - si misura la performance OOS e la si confronta con l'IS. WFE = OOS/IS.

Limite: dati ~14 mesi prevalentemente bull -> testa la STABILITA' temporale, non un
ciclo completo con bear vero. Nessuna garanzia fuori da questo regime.
"""
import numpy as np
import pandas as pd
import backtest_v3 as bt
from indicators import atr_wilder
from volume_tools import smart_money_signal
from modules.trade_proposal import propose

COST = (5.0 + 2.0) / 1e4 * 2 * 100
FRAC = (0.5, 0.25, 0.25)
KATR = (2.0, 6.0, 10.0)      # target tarati (= default trade_proposal)
KRR = (1.2, 3.0, 5.0)
SM_ACC = 0.33                # soglia accumulazione (filtro di affidabilita')


def _ladder_ret(entry, atr, H, L, C):
    stop = max(entry*0.95, entry - 2*atr); risk = entry - stop
    Ts = [entry + max(KATR[k]*atr, KRR[k]*risk) for k in range(3)]
    rem = 1.0; acc = 0.0; ti = 0
    for i in range(len(C)):
        if L[i] <= stop:
            acc += rem*(stop/entry-1)*100; rem = 0.0; break
        while ti < 3 and H[i] >= Ts[ti]:
            acc += FRAC[ti]*(Ts[ti]/entry-1)*100; rem -= FRAC[ti]; ti += 1
    if rem > 0:
        acc += rem*(C[-1]/entry-1)*100
    return acc - COST


def _metrics(rets, hz):
    a = np.array(rets)
    if len(a) < 5:
        return None
    sd = a.std(ddof=1) or 1e-9
    pf = a[a > 0].sum()/(-a[a < 0].sum()) if (a < 0).any() else np.inf
    return dict(n=len(a), mean=a.mean(), med=np.median(a), win=(a > 0).mean()*100,
                sharpe=a.mean()/sd*np.sqrt(252/hz), pf=pf)


def run(px_path="data/mib_data.csv", N=10, folds=4, warmup_frac=0.40):
    px = pd.read_csv(px_path, parse_dates=["date"]).dropna(subset=["close"])
    sig = bt.build_signals(px, bt.score_new, horizons=(5, 10, 20))
    frames = {tk: px[px.ticker == tk].sort_values("date").dropna(subset=["close"]).reset_index(drop=True)
              for tk in sig["ticker"].unique()}
    sig = sig.copy()
    sig["sm"] = [(lambda s: s["score"] if s["score"] is not None else np.nan)(
        smart_money_signal(frames[r.ticker].iloc[:r.t+1])) for r in sig.itertuples()]
    sig = sig.dropna(subset=["sm"]).sort_values("date").reset_index(drop=True)

    def trade(r):
        g = frames[r.ticker]; idx = r.t
        if idx+1 >= len(g) or idx < 15:
            return None
        entry = float(g["close"].iloc[idx])
        atr = float(atr_wilder(g["high"].iloc[:idx+1], g["low"].iloc[:idx+1], g["close"].iloc[:idx+1], 14).iloc[-1])
        if not np.isfinite(atr) or atr <= 0:
            return None
        H = g["high"].iloc[idx+1:idx+1+N].values; L = g["low"].iloc[idx+1:idx+1+N].values; C = g["close"].iloc[idx+1:idx+1+N].values
        if len(C) == 0:
            return None
        return _ladder_ret(entry, atr, H, L, C)

    n = len(sig); w = int(n*warmup_frac)
    bounds = np.linspace(w, n, folds+1).astype(int)
    print(f"Segnali {n} | warmup IS iniziale {w} | {folds} finestre OOS | hold {N}gg")
    print(f"Modello: top-quintile(soglia da IS) + accumulazione (sm>={SM_ACC}) + target {KATR}")
    print(f"\n{'fold OOS (date)':28s}{'n':>4}{'win%':>7}{'mean%':>7}{'med%':>7}{'Sharpe':>8}{'PF':>6}")
    oos_all = []
    for f in range(folds):
        lo, hi = bounds[f], bounds[f+1]
        is_part = sig.iloc[:lo]                    # anchored: tutto cio' che precede
        oos_part = sig.iloc[lo:hi]
        thr = is_part["score"].quantile(0.80)      # soglia stimata SOLO su IS
        sel = oos_part[(oos_part["score"] >= thr) & (oos_part["sm"] >= SM_ACC)]
        rets = [x for x in (trade(r) for r in sel.itertuples()) if x is not None]
        m = _metrics(rets, N)
        d0, d1 = oos_part["date"].min().date(), oos_part["date"].max().date()
        if m:
            oos_all += rets
            print(f"{str(d0)+'->'+str(d1):28s}{m['n']:4d}{m['win']:7.1f}{m['mean']:7.2f}{m['med']:7.2f}{m['sharpe']:8.2f}{m['pf']:6.2f}")
        else:
            print(f"{str(d0)+'->'+str(d1):28s}  (troppi pochi trade)")

    # IS aggregato (intero campione, stesso modello con soglia globale) per il confronto/WFE
    thr_g = sig["score"].quantile(0.80)
    is_sel = sig[(sig["score"] >= thr_g) & (sig["sm"] >= SM_ACC)]
    is_rets = [x for x in (trade(r) for r in is_sel.itertuples()) if x is not None]
    mi = _metrics(is_rets, N); mo = _metrics(oos_all, N)
    print("\n--- AGGREGATO ---")
    if mi: print(f"IS  (in-sample):  n={mi['n']:4d} win {mi['win']:.1f}% mean {mi['mean']:+.2f}% Sharpe {mi['sharpe']:+.2f} PF {mi['pf']:.2f}")
    if mo: print(f"OOS (walk-fwd):   n={mo['n']:4d} win {mo['win']:.1f}% mean {mo['mean']:+.2f}% Sharpe {mo['sharpe']:+.2f} PF {mo['pf']:.2f}")
    if mi and mo and mi['mean'] != 0:
        print(f"WFE (OOS/IS mean): {mo['mean']/mi['mean']:+.2f}  (>~0.5 = edge regge OOS)")
    print("\nNB: periodo unico prevalentemente bull -> stabilita' temporale, NON ciclo completo.")


if __name__ == "__main__":
    run()
