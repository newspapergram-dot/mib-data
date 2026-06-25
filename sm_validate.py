"""sm_validate.py — Lo Smart Money e' un predittore? Validazione point-in-time.

Per ogni segnale storico calcola smart_money_signal usando SOLO i dati fino alla
data del segnale, poi misura:
  1) correlazione di Spearman (sm vs forward return netto) a 5/10/20gg, e se un
     blend lineare score+sm migliora o peggiora la correlazione dello score;
  2) forward return medio per stato (accumulazione/neutro/distribuzione);
  3) se, CONDIZIONATO al top-quintile dello score, l'accumulazione batte la distribuzione.

Esito (run 2026-06-25): il blend lineare PEGGIORA la correlazione a 10gg
(0.059 vs 0.086 dello score) -> NON integrare lo Smart Money come componente
lineare dello score. Pero' DENTRO il top-quintile l'accumulazione rende +3.14%
(win 60%) vs +1.63% (win 40%) della distribuzione -> usarlo come FILTRO di
conferma/veto (come fa portfolio_builder), non come peso nello score.
"""
import numpy as np
import pandas as pd
import backtest_v3 as bt
from volume_tools import smart_money_signal


def run(px_path="data/mib_data.csv"):
    px = pd.read_csv(px_path, parse_dates=["date"]).dropna(subset=["close"])
    sig = bt.build_signals(px, bt.score_new, horizons=(5, 10, 20))
    frames = {tk: px[px.ticker == tk].sort_values("date").dropna(subset=["close"]).reset_index(drop=True)
              for tk in sig["ticker"].unique()}
    sig = sig.copy()
    sig["sm"] = [(_sm(frames[r.ticker], r.t)) for r in sig.itertuples()]
    sig = sig.dropna(subset=["sm"])
    print(f"Segnali con smart money: {len(sig)}")

    print("\n=== 1) Spearman vs forward return netto ===")
    print(f"{'orizzonte':12s}{'score':>10s}{'smart$':>10s}{'blend 0.7/0.3':>14s}")
    for hz in (5, 10, 20):
        col = f"fwd_{hz}_net"; d = sig.dropna(subset=[col])
        cs = d[["score", col]].corr("spearman").iloc[0, 1]
        cm = d[["sm", col]].corr("spearman").iloc[0, 1]
        blend = 0.7*d["score"] + 0.3*d["sm"]
        cb = pd.concat([blend, d[col]], axis=1).corr("spearman").iloc[0, 1]
        print(f"{hz:>2d}gg netto {cs:>10.4f}{cm:>10.4f}{cb:>14.4f}")

    print("\n=== 2) Forward return medio per stato (fwd_10_net) ===")
    col = "fwd_10_net"; d = sig.dropna(subset=[col])
    def bucket(s):
        return "accumulazione" if s >= 0.33 else ("distribuzione" if s <= -0.15 else "neutro")
    d = d.assign(stato=d["sm"].apply(bucket))
    g = d.groupby("stato")[col].agg(["count", "mean", "median", lambda x: (x > 0).mean()*100])
    g.columns = ["n", "ret_medio%", "mediana%", "win%"]
    print(g.round(3).to_string())

    print("\n=== 3) Valore aggiunto DENTRO il top-quintile ===")
    tq = sig["score"].quantile(0.80); top = d[d["score"] >= tq]
    hi = top[top["sm"] >= 0.33][col]; lo = top[top["sm"] <= -0.15][col]
    print(f"  accumulazione: n={len(hi)} ret {hi.mean():+.3f}% win {(hi>0).mean()*100:.0f}%")
    print(f"  distribuzione: n={len(lo)} ret {lo.mean():+.3f}% win {(lo>0).mean()*100:.0f}%")
    print(f"  spread accumulazione-distribuzione: {hi.mean()-lo.mean():+.3f}%")


def reliability(px_path="data/mib_data.csv"):
    """Test di AFFIDABILITA': il filtro Smart Money migliora il portafoglio selezionato?
    Metriche (win/median/Sharpe/PF) per top-quintile +/- filtro SM a 10 e 20gg.
    Esito: l'accumulazione (sm>=.33) alza ogni metrica -> e' la leva di affidabilita'."""
    px = pd.read_csv(px_path, parse_dates=["date"]).dropna(subset=["close"])
    sig = bt.build_signals(px, bt.score_new, horizons=(5, 10, 20))
    frames = {tk: px[px.ticker == tk].sort_values("date").dropna(subset=["close"]).reset_index(drop=True)
              for tk in sig["ticker"].unique()}
    sig = sig.copy()
    sig["sm"] = [_sm(frames[r.ticker], r.t) for r in sig.itertuples()]
    sig = sig.dropna(subset=["sm"])
    p80 = sig["score"].quantile(0.80)
    defs = {
        "base top-quintile":         lambda d: d[d.score >= p80],
        "+ non distrib (sm>=-.15)":  lambda d: d[(d.score >= p80) & (d.sm >= -0.15)],
        "+ accumulazione (sm>=.33)": lambda d: d[(d.score >= p80) & (d.sm >= 0.33)],
    }
    for hz in (10, 20):
        col = f"fwd_{hz}_net"
        print(f"\n=== AFFIDABILITA' orizzonte {hz}gg (netto) ===")
        print(f"{'selezione':28s}{'n':>5}{'mean%':>7}{'med%':>7}{'win%':>7}{'Sharpe':>8}{'PF':>6}")
        for name, fn in defs.items():
            a = fn(sig)[col].dropna().values/100
            if len(a) < 10:
                continue
            sd = a.std(ddof=1) or 1e-9
            pf = a[a > 0].sum()/(-a[a < 0].sum()) if (a < 0).any() else np.inf
            print(f"{name:28s}{len(a):5d}{a.mean()*100:7.2f}{np.median(a)*100:7.2f}"
                  f"{(a>0).mean()*100:7.1f}{a.mean()/sd*np.sqrt(252/hz):8.2f}{pf:6.2f}")


def _sm(g, idx):
    s = smart_money_signal(g.iloc[:idx+1])
    return s["score"] if s["score"] is not None else np.nan


if __name__ == "__main__":
    run()
    reliability()
