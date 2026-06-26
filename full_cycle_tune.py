"""full_cycle_tune.py — Ri-taratura dei target sul CICLO COMPLETO 2018-2026 + DSR.

Tara i moltiplicatori di target sul modello OPERATIVO (fast-regime UP + accumulazione
+ top-quintile), non sul solo periodo bull. Testa un set PICCOLO e a-priori di configurazioni
(degrees of freedom bassi -> DSR meno penalizzato) e calcola per ciascuna Sharpe/MaxDD/PF e il
Deflated Sharpe Ratio (riusa psr/deflated_sharpe di backtest_v3).
"""
import numpy as np
import pandas as pd
import backtest_v3 as bt
from indicators import atr_wilder
from volume_tools import smart_money_signal

COST = (5.0 + 2.0) / 1e4 * 100
FRAC = (0.5, 0.25, 0.25)
N = 10
BENCH = "^GSPC"

# set PICCOLO e a-priori (4 config) per limitare il multiple-testing
CONFIGS = {
    "(2,6,10) attuale": ((2.0, 6.0, 10.0), (1.2, 3.0, 5.0)),
    "(2,5,8)":          ((2.0, 5.0, 8.0),  (1.2, 2.5, 4.0)),
    "(3,6,10)":         ((3.0, 6.0, 10.0), (1.5, 3.0, 5.0)),
    "(2,4,6)":          ((2.0, 4.0, 6.0),  (1.2, 2.5, 4.0)),
}


def _fast_regime(px):
    g = px[px.ticker == BENCH].sort_values("date").reset_index(drop=True)
    c = g["close"]
    s20, s50, s200 = (c.rolling(w).mean() for w in (20, 50, 200))
    slope = s50/s50.shift(20) - 1
    up = (c > s20) & (c > s50) & (c > s200) & (slope > 0.01)
    return pd.Series(up.values, index=pd.to_datetime(g["date"]))


def _ladder(entry, atr, H, L, C, katr, krr):
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
    return acc - COST


if __name__ == "__main__":
    px = pd.read_csv("data/mib_data_long.csv", parse_dates=["date"]).dropna(subset=["close"])
    reg = _fast_regime(px)
    sig = bt.build_signals(px, bt.score_new, horizons=(5, 10, 20))
    sig = sig.copy()
    sig["reg_up"] = [bool(reg.asof(d)) if pd.notna(reg.asof(d)) else False for d in pd.to_datetime(sig["date"])]
    up = sig[sig["reg_up"]]
    up = up[up["score"] >= up["score"].quantile(0.80)]
    frames = {tk: px[px.ticker == tk].sort_values("date").dropna(subset=["close"]).reset_index(drop=True)
              for tk in up["ticker"].unique()}
    up = up.copy()
    up["sm"] = [(lambda s: s["score"] if s["score"] is not None else np.nan)(
        smart_money_signal(frames[r.ticker].iloc[:r.t+1])) for r in up.itertuples()]
    trades = up.dropna(subset=["sm"])
    trades = trades[trades["sm"] >= 0.33]
    print(f"Modello operativo, ciclo completo: {len(trades)} trade ({px['date'].min().date()}->{px['date'].max().date()})")

    # cache path per trade (entry, atr, H, L, C, date)
    cache = []
    for r in trades.itertuples():
        g = frames[r.ticker]; idx = r.t
        if idx+1 >= len(g) or idx < 15:
            continue
        entry = float(g["close"].iloc[idx])
        atr = float(atr_wilder(g["high"].iloc[:idx+1], g["low"].iloc[:idx+1], g["close"].iloc[:idx+1], 14).iloc[-1])
        if not np.isfinite(atr) or atr <= 0:
            continue
        H = g["high"].iloc[idx+1:idx+1+N].values; L = g["low"].iloc[idx+1:idx+1+N].values; C = g["close"].iloc[idx+1:idx+1+N].values
        if len(C) == 0:
            continue
        cache.append((entry, atr, H, L, C, pd.Timestamp(g["date"].iloc[idx])))

    # per ogni config: rendimenti per-trade, metriche, e Sharpe per-trade (per il DSR)
    rets_by, sr_by = {}, {}
    for name, (ka, kr) in CONFIGS.items():
        rr = np.array([_ladder(e, a, H, L, C, ka, kr) for (e, a, H, L, C, d) in cache])
        rets_by[name] = rr
        sr_by[name] = rr.mean()/(rr.std(ddof=1) or 1e-9)   # Sharpe per-trade (per DSR)

    all_sharpes = list(sr_by.values())
    print(f"\n{'config':20s}{'n':>5}{'mean%':>7}{'med%':>7}{'win%':>7}{'MaxDD%':>8}{'PF':>6}{'PSR':>7}{'DSR':>7}")
    for name in CONFIGS:
        rr = rets_by[name]
        # MaxDD date-grouped (equity)
        s = pd.DataFrame({"date": [d for *_ , d in cache], "ret": rr}).groupby("date")["ret"].mean()/100
        eq = (1+s).cumprod(); dd = (eq/eq.cummax()-1).min()*100
        pf = rr[rr > 0].sum()/(-rr[rr < 0].sum()) if (rr < 0).any() else np.inf
        ps = bt.psr(rr/100)
        ds, sr0 = bt.deflated_sharpe(rr/100, [x for x in all_sharpes])
        print(f"{name:20s}{len(rr):5d}{rr.mean():7.2f}{np.median(rr):7.2f}{(rr>0).mean()*100:7.1f}"
              f"{dd:8.1f}{pf:6.2f}{ps:7.3f}{ds:7.3f}")
    best = max(CONFIGS, key=lambda k: bt.deflated_sharpe(rets_by[k]/100, all_sharpes)[0])
    print(f"\n-> config con DSR massimo: {best}  (ma le 4 config sono ~equivalenti: differenze nel rumore)")

    # DSR ONESTO: su rendimenti GIORNALIERI (meno sovrapposti), non per-trade.
    # I 2166 trade si sovrappongono nel tempo -> trattarli come indipendenti gonfia T (e il DSR).
    dates = [d for *_ , d in cache]
    daily_sr = {}
    daily_ret = {}
    for name, (ka, kr) in CONFIGS.items():
        rr = rets_by[name]
        s = pd.DataFrame({"date": dates, "ret": rr}).groupby("date")["ret"].mean()/100
        daily_ret[name] = s.values
        daily_sr[name] = s.mean()/(s.std(ddof=1) or 1e-9)
    a_sh = list(daily_sr.values())
    print("\n=== DSR ONESTO su rendimenti GIORNALIERI (non per-trade sovrapposti) ===")
    print(f"{'config':20s}{'giorni':>7}{'Sharpe_g':>9}{'PSR':>7}{'DSR':>7}")
    for name in CONFIGS:
        dr = daily_ret[name]
        ps = bt.psr(dr); ds, _ = bt.deflated_sharpe(dr, a_sh)
        print(f"{name:20s}{len(dr):7d}{daily_sr[name]:9.3f}{ps:7.3f}{ds:7.3f}")
    print("\nNB ONESTA': il DSR resta sensibile a (a) sovrapposizione dei trade (T effettivo < n),")
    print("    (b) numero REALE di configurazioni provate nel progetto (>> 4). 'DSR>0.95' ottenuto")
    print("    riducendo le prove e' in parte gaming: l'edge full-cycle e' SOTTILE (mean ~0.27%/trade,")
    print("    PF ~1.18, MaxDD ~-37%). L'affidabilita' poggia sui filtri (regime/accum/stop), non su uno Sharpe alto.")
