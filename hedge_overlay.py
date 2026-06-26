"""hedge_overlay.py — Overlay di rischio sul modello operativo, ciclo completo 2018-2026.
Confronta MaxDD/Sharpe di:
  BASE  : modello (fast-regime + accumulazione + stop/target), nessun overlay
  A     : GO-FLAT  -> in cash nei giorni di regime TREND_DOWN (indice ^GSPC)
  B1/B2 : HEDGE    -> short indice (h=1.0 / 0.5) nei giorni NON TREND_UP
  C     : combinato (flat in DOWN + hedge in PULLBACK)
Simulazione giornaliera (mark-to-market) cosi' gli overlay agiscono giorno per giorno.
Obiettivo: ridurre il rischio di rovina avvicinandosi al profilo bull-only.
"""
import numpy as np
import pandas as pd
import backtest_v3 as bt
from indicators import atr_wilder
from volume_tools import smart_money_signal

BENCH = "^GSPC"
N = 10


def _us_regime_and_ret(px):
    g = px[px.ticker == BENCH].sort_values("date").reset_index(drop=True)
    c = g["close"]
    s20, s50, s200 = (c.rolling(w).mean() for w in (20, 50, 200))
    slope = s50 / s50.shift(20) - 1
    reg = np.where((c > s20) & (c > s50) & (c > s200) & (slope > 0.01), "UP",
          np.where((c < s200) & (slope < -0.01), "DOWN", "MID"))
    idx = pd.to_datetime(g["date"])
    return (pd.Series(reg, index=idx), pd.Series(c.pct_change().values, index=idx))


def _daily_trade(g, i0):
    """Rendimenti giornalieri di un trade (entry close[i0]) con stop + target T1, max N gg."""
    if i0 + 1 >= len(g) or i0 < 15:
        return None
    entry = float(g["close"].iloc[i0])
    atr = float(atr_wilder(g["high"].iloc[:i0+1], g["low"].iloc[:i0+1], g["close"].iloc[:i0+1], 14).iloc[-1])
    if not np.isfinite(atr) or atr <= 0:
        return None
    stop = max(entry*0.95, entry - 2*atr); risk = entry - stop
    T1 = entry + max(2.0*atr, 1.2*risk)
    out = []; prev = entry
    for i in range(1, N+1):
        j = i0 + i
        if j >= len(g):
            break
        hi, lo, cl, dt = float(g["high"].iloc[j]), float(g["low"].iloc[j]), float(g["close"].iloc[j]), g["date"].iloc[j]
        if lo <= stop:
            out.append((dt, stop/prev - 1)); break
        if hi >= T1:
            out.append((dt, T1/prev - 1)); break
        out.append((dt, cl/prev - 1)); prev = cl
    return out


def _equity(daily):
    s = daily.sort_index()
    eq = (1 + s).cumprod()
    dd = (eq/eq.cummax() - 1).min()*100
    a = s.values; sharpe = a.mean()/(a.std(ddof=1) or 1e-9)*np.sqrt(252)
    return dict(dd=dd, sharpe=sharpe, cagr=(eq.iloc[-1]**(252/len(eq))-1)*100 if len(eq) else 0,
                fin=eq.iloc[-1] if len(eq) else 1)


if __name__ == "__main__":
    COST = (5.0 + 2.0)/1e4
    px = pd.read_csv("data/mib_data_long.csv", parse_dates=["date"]).dropna(subset=["close"])
    reg, iret = _us_regime_and_ret(px)
    sig = bt.build_signals(px, bt.score_new, horizons=(5, 10, 20))
    frames = {tk: px[px.ticker == tk].sort_values("date").dropna(subset=["close"]).reset_index(drop=True)
              for tk in sig["ticker"].unique()}

    # modello operativo: fast-regime UP del mercato del titolo + accumulazione + top-quintile
    sig = sig.copy()
    sig["reg_up"] = [reg.asof(d) == "UP" for d in pd.to_datetime(sig["date"])]
    up = sig[sig["reg_up"]]
    thr = up["score"].quantile(0.80)
    up = up[up["score"] >= thr]
    up = up.copy()
    up["sm"] = [(lambda s: s["score"] if s["score"] is not None else np.nan)(
        smart_money_signal(frames[r.ticker].iloc[:r.t+1])) for r in up.itertuples()]
    trades = up.dropna(subset=["sm"])
    trades = trades[trades["sm"] >= 0.33]
    print(f"Trade del modello (ciclo completo): {len(trades)}")

    # P&L giornaliero aggregato (media equal-weight dei trade attivi ogni giorno)
    bucket = {}
    for r in trades.itertuples():
        dl = _daily_trade(frames[r.ticker], r.t)
        if not dl:
            continue
        first = True
        for dt, ret in dl:
            ret = ret - (COST if first else 0.0); first = False
            bucket.setdefault(pd.Timestamp(dt), []).append(ret)
    base = pd.Series({d: np.mean(v) for d, v in bucket.items()}).sort_index()

    # allinea regime e rendimento indice ai giorni operativi
    rday = reg.reindex(base.index, method="ffill")
    iday = iret.reindex(base.index, method="ffill").fillna(0.0)

    flat = base.where(rday != "DOWN", 0.0)                        # A: cash nei DOWN
    hedge1 = base - 1.0*iday.where(rday != "UP", 0.0)             # B1: short indice (h=1) se non UP
    hedge2 = base - 0.5*iday.where(rday != "UP", 0.0)             # B2: short indice (h=0.5)
    comb = base.where(rday != "DOWN", 0.0) - 0.5*iday.where(rday == "MID", 0.0)  # C

    print(f"\n{'overlay':34s}{'MaxDD':>9s}{'Sharpe':>8s}{'CAGR%':>8s}{'equity x':>10s}")
    for name, s in [("BASE (nessun overlay)", base), ("A) GO-FLAT in DOWN", flat),
                    ("B1) HEDGE indice h=1.0", hedge1), ("B2) HEDGE indice h=0.5", hedge2),
                    ("C) flat in DOWN + hedge .5 in MID", comb)]:
        m = _equity(s)
        print(f"{name:34s}{m['dd']:8.1f}%{m['sharpe']:8.2f}{m['cagr']:8.1f}{m['fin']:10.2f}")
    print("\nNB: giorni operativi distinti:", len(base), "| periodo",
          base.index.min().date(), "->", base.index.max().date())
