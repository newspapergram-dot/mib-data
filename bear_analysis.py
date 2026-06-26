"""bear_analysis.py — I 'fattori bear' funzionano? Test sul ciclo COMPLETO 2018-2026
(data/mib_data_long.csv, prezzi aggiustati). Confronta la strategia:
  A) GREZZA (top-quintile, nessun filtro di regime)  -> baseline catastrofica nei bear
  B) + FILTRO DI REGIME DI MERCATO (opera solo quando l'indice del titolo e' TREND_UP)
  C) + ACCUMULAZIONE smart money (il modello operativo completo)
Metrica chiave per i bear: Max Drawdown (oltre a Sharpe/expectancy/win).
"""
import numpy as np
import pandas as pd
import backtest_v3 as bt
from volume_tools import smart_money_signal
from indicators import atr_wilder

INDEX = {"IT": "FTSEMIB.MI", "FR": "^FCHI", "US": "^GSPC"}
COST = (5.0 + 2.0) / 1e4 * 2 * 100
KATR, KRR, FRAC = (2.0, 6.0, 10.0), (1.2, 3.0, 5.0), (0.5, 0.25, 0.25)


def _ladder_ret(g, idx, N=10):
    """Rendimento del trade con STOP + target laddered (modello operativo reale)."""
    if idx + 1 >= len(g) or idx < 15:
        return None, None
    entry = float(g["close"].iloc[idx])
    atr = float(atr_wilder(g["high"].iloc[:idx+1], g["low"].iloc[:idx+1], g["close"].iloc[:idx+1], 14).iloc[-1])
    if not np.isfinite(atr) or atr <= 0:
        return None, None
    H = g["high"].iloc[idx+1:idx+1+N].values; L = g["low"].iloc[idx+1:idx+1+N].values; C = g["close"].iloc[idx+1:idx+1+N].values
    if len(C) == 0:
        return None, None
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
    return acc - COST, g["date"].iloc[idx]


def _report_ladder(name, sig, frames, top_q=0.80):
    """Equity con STOP: per-segnale laddered return, media per data, compounding."""
    thr = sig["score"].quantile(top_q)
    sel = sig[sig["score"] >= thr]
    rows = []
    for r in sel.itertuples():
        ret, d = _ladder_ret(frames[r.ticker], r.t)
        if ret is not None:
            rows.append((d, ret))
    if not rows:
        print(f"{name:42s}  (nessun dato)"); return
    s = pd.DataFrame(rows, columns=["date", "ret"]).groupby("date")["ret"].mean()/100
    eq = (1+s).cumprod(); dd = (eq/eq.cummax()-1).min()*100
    a = s.values; sharpe = a.mean()/(a.std(ddof=1) or 1e-9)*np.sqrt(252/10)
    pf = a[a > 0].sum()/(-a[a < 0].sum()) if (a < 0).any() else np.inf
    print(f"{name:42s} n={len(rows):5d}  Sharpe {sharpe:+5.2f}  MaxDD {dd:6.1f}%  "
          f"exp {a.mean()*100:+5.2f}%  win {(a>0).mean()*100:4.1f}%  PF {pf:.2f}")


def _market(tk):
    if tk.endswith(".MI"):
        return "IT"
    if tk.endswith(".PA") or tk.endswith(".AS"):
        return "FR"
    return "US"


def _regime_series(px, idx, fast=False):
    g = px[px.ticker == idx].sort_values("date")
    c = g["close"]
    s50 = c.rolling(50).mean(); s200 = c.rolling(200).mean()
    up = (c > s50) & (s50 > s200)
    if fast:                                   # trigger rapido: indice anche sopra SMA20
        up = up & (c > c.rolling(20).mean())
    return pd.Series(up.values, index=pd.to_datetime(g["date"].values)).sort_index()


def _report(name, sig, col="fwd_10_net"):
    r = bt.portfolio_sim(sig, col)
    if r is None:
        print(f"{name:42s}  (nessun dato)"); return
    m = bt.perf_metrics(r["rets"].values, ann=252/10, label=name)
    print(f"{name:42s} n={r['n']:5d}  Sharpe {m.get('Sharpe_ann',np.nan):+5.2f}  "
          f"MaxDD {r['dd'].min()*100:6.1f}%  exp {m.get('Expectancy_pct',np.nan):+5.2f}%  "
          f"win {m.get('WinRate_pct',np.nan):4.1f}%  PF {m.get('ProfitFactor',np.nan):.2f}")


if __name__ == "__main__":
    px = pd.read_csv("data/mib_data_long.csv", parse_dates=["date"]).dropna(subset=["close"])
    sig = bt.build_signals(px, bt.score_new, horizons=(5, 10, 20))
    print(f"Periodo {px['date'].min().date()} -> {px['date'].max().date()} | segnali {len(sig)}")

    # regime di mercato point-in-time per ogni segnale
    reg = {m: _regime_series(px, idx) for m, idx in INDEX.items()}
    def is_up(r):
        s = reg[_market(r.ticker)]
        try:
            v = s.asof(r.date)
            return bool(v) if pd.notna(v) else False
        except Exception:
            return False
    sig = sig.copy()
    sig["reg_up"] = [is_up(r) for r in sig.itertuples()]

    print("\n=== STRATEGIA SUL CICLO COMPLETO (incl. crash 2020 e bear 2022) ===")
    _report("A) GREZZA (nessun filtro regime)", sig)
    up = sig[sig["reg_up"]]
    _report("B) + filtro regime di mercato (bull)", up)

    # C) + accumulazione: SM point-in-time solo sul sottoinsieme regime-up (piu' piccolo)
    frames = {tk: px[px.ticker == tk].sort_values("date").dropna(subset=["close"]).reset_index(drop=True)
              for tk in up["ticker"].unique()}
    sm = []
    for r in up.itertuples():
        g = frames[r.ticker]
        s = smart_money_signal(g.iloc[:r.t+1])
        sm.append(s["score"] if s["score"] is not None else np.nan)
    up = up.copy(); up["sm"] = sm
    acc = up.dropna(subset=["sm"])
    acc = acc[acc["sm"] >= 0.33]
    _report("C) + accumulazione (modello completo)", acc)

    print("\n=== STESSI FILTRI MA CON LO STOP (uscita laddered reale, non fwd return grezzo) ===")
    _report_ladder("B+stop) regime filter + stop", up, frames)
    _report_ladder("C+stop) modello completo + stop", acc, frames)

    # D) trigger di regime RAPIDO (indice anche sopra SMA20) + accumulazione + stop
    reg_fast = {m: _regime_series(px, idx, fast=True) for m, idx in INDEX.items()}
    def is_up_fast(r):
        s = reg_fast[_market(r.ticker)]
        try:
            v = s.asof(r.date); return bool(v) if pd.notna(v) else False
        except Exception:
            return False
    accf = acc[[is_up_fast(r) for r in acc.itertuples()]]
    print("\n=== FATTORE BEAR AGGIUNTIVO: trigger regime RAPIDO (indice > SMA20) ===")
    _report_ladder("D+stop) regime rapido + accum + stop", accf, frames)

    print("\nNB: Max Drawdown = metrica bear chiave. Lo STOP e il trigger rapido sono i")
    print("    fattori bear che il portfolio_sim grezzo NON cattura: confronta A -> D.")
