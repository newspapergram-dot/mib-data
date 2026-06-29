#!/usr/bin/env python3
"""portfolio_backtester.py — Held-Portfolio Backtester: equity line REALE giornaliera.

A differenza del harness per-segnale (portfolio_sim di backtest_v3, usato in fix4/fix5), questo
motore simula un portafoglio REALMENTE detenuto: posizioni concorrenti, mark-to-market giornaliero,
cassa esplicita. E' il test corretto per il vol-sizing / risk parity (vedi Lezione #22): solo qui
il MaxDD e' un drawdown di PERCORSO vero, non l'artefatto dei rendimenti 10gg sovrapposti.

Regole (spec Run #27):
  1) Capitale iniziale 100k, mark-to-market giornaliero (equity = cassa + valore posizioni).
  2) Max 10 posizioni simultanee, max 10% del capitale TOTALE per posizione.
  3) Se i segnali validi in un giorno sono < 10, il capitale non allocato resta in CASSA
     (nessuna leva implicita: mai >100% investito, mai concentrare tutto su pochi nomi).
  4) Holding fisso 10 giorni operativi: ingresso al close di t+1 (no lookahead sul segnale di t),
     uscita al close del 10° giorno di borsa successivo.

Segnale: score NUOVO (score_new validato) calcolato vettorialmente (identico a score_new, che e'
causale). "Valido" = gate superato E score >= soglia top-quintile. Ranking per score decrescente.

Output: CAGR, MaxDD (di percorso, reale), Sharpe giornaliero, % media investita (Market Exposure),
numero di trade. Equity giornaliera in data/portfolio_equity.csv.
"""
import numpy as np
import pandas as pd
from indicators import adx, rsi_wilder

CAPITAL0 = 100_000.0
MAX_POS = 10
POS_CAP = 0.10           # 10% del capitale totale per posizione
HOLD = 10                # giorni operativi
TOP_Q = 0.80
ANN = 252


def score_series(g):
    """score_new vettorizzato su un ticker (colonne close/high/low ordinate per data).
    Identico a backtest_v3.score_new perche' ADX/RSI (Wilder) e rolling sono CAUSALI:
    il valore all'indice t calcolato sull'intera serie == quello sul solo slice [:t+1]."""
    c, h, l = g["close"], g["high"], g["low"]
    sma50 = c.rolling(50).mean()
    sma200 = c.rolling(200).mean()
    gate = (c > sma200) & (sma50 > sma200)
    adf = adx(h, l, c)
    adx_v = adf["adx"]
    trend_up = adf["plus_di"] > adf["minus_di"]
    rsi = rsi_wilder(c)
    rh20 = h.shift(1).rolling(20).max()        # max high t-20..t-1 (esclude oggi), come score_new
    breakout = c > rh20
    mom3m = (c / c.shift(62) - 1) * 100         # score_new: cc.iloc[len-63] => shift(62)
    s = np.zeros(len(c))
    s += np.where(breakout & trend_up, 0.55, 0.0)
    s += np.where((adx_v >= 40) & trend_up, 0.35,
                  np.where((adx_v >= 25) & trend_up, 0.15, 0.0))
    s += 0.15 * np.tanh(mom3m.fillna(0.0) / 30)
    s += np.where((rsi > 75) & (~breakout), -0.20, 0.0)
    s = pd.Series(np.clip(s, -1, 1), index=c.index)
    valid = gate & (np.arange(len(c)) >= 200)
    return s.where(valid, np.nan)


def _max_drawdown(equity):
    peak = equity.cummax()
    return float((equity / peak - 1).min())


def backtest(px_path="data/mib_data_long.csv", capital0=CAPITAL0, max_pos=MAX_POS,
             pos_cap=POS_CAP, hold=HOLD, top_q=TOP_Q, equity_out="data/portfolio_equity.csv"):
    px = pd.read_csv(px_path, parse_dates=["date"]).dropna(subset=["close"]).sort_values(["ticker", "date"])
    tickers = px["ticker"].unique()

    # pannelli: close grezzo (esistenza barra), close ffilled (MTM), score (segnali)
    close_raw = px.pivot(index="date", columns="ticker", values="close").sort_index()
    close_mtm = close_raw.ffill()
    scores = {}
    for tk in tickers:
        g = px[px.ticker == tk].set_index("date").sort_index()
        scores[tk] = score_series(g[["close", "high", "low"]])
    score_panel = pd.DataFrame(scores).reindex(close_raw.index)

    thr = np.nanquantile(score_panel.values, top_q)   # soglia top-quintile (globale, vedi NB)
    cal = list(close_raw.index)
    n = len(cal)

    cash = capital0
    positions = {}     # tk -> {shares, entry_i, entry_px}
    recs = []
    trades = 0
    start = 201        # serve uno storico per gli score e un giorno-segnale precedente

    for i in range(start, n):
        day = cal[i]

        # 1) USCITE: posizioni con holding completato (>= hold giorni operativi)
        for tk in [t for t, p in positions.items() if i - p["entry_i"] >= hold]:
            px_exit = close_mtm.at[day, tk]
            if pd.notna(px_exit):
                cash += positions[tk]["shares"] * float(px_exit)
                positions.pop(tk)

        # 2) MARK-TO-MARKET (valore di portafoglio a inizio giornata, post-uscite)
        holdings_val = sum(p["shares"] * float(close_mtm.at[day, tk])
                           for tk, p in positions.items()
                           if pd.notna(close_mtm.at[day, tk]))
        total_value = cash + holdings_val

        # 3) INGRESSI: segnali validi del giorno PRECEDENTE (no lookahead), nomi non gia' detenuti,
        #    con barra REALE oggi per il fill. Riempi gli slot liberi, size 10% del totale per nome.
        if len(positions) < max_pos:
            prev = cal[i - 1]
            srow = score_panel.loc[prev]
            elig = srow[(srow >= thr) & srow.notna()]
            elig = elig[[tk for tk in elig.index
                         if tk not in positions and pd.notna(close_raw.at[day, tk])]]
            elig = elig.sort_values(ascending=False)
            for tk in elig.index:
                if len(positions) >= max_pos:
                    break
                price = float(close_raw.at[day, tk])
                budget = min(pos_cap * total_value, cash)    # 10% del totale, ma mai oltre la cassa
                shares = int(budget / price) if price > 0 else 0
                if shares <= 0:
                    continue
                cost = shares * price
                cash -= cost
                positions[tk] = {"shares": shares, "entry_i": i, "entry_px": price}
                trades += 1

        # 4) MTM di chiusura giornata (dopo gli ingressi) per l'equity
        holdings_val = sum(p["shares"] * float(close_mtm.at[day, tk])
                           for tk, p in positions.items()
                           if pd.notna(close_mtm.at[day, tk]))
        equity = cash + holdings_val
        recs.append({"date": day, "equity": equity, "cash": cash,
                     "invested": holdings_val, "n_pos": len(positions),
                     "exposure": holdings_val / equity if equity > 0 else 0.0})

    eq = pd.DataFrame(recs).set_index("date")
    eq.to_csv(equity_out)

    # ---- metriche su equity di PERCORSO reale ----
    ret = eq["equity"].pct_change().dropna()
    years = len(eq) / ANN
    cagr = (eq["equity"].iloc[-1] / capital0) ** (1 / years) - 1 if years > 0 else np.nan
    sharpe = float(ret.mean() / ret.std(ddof=1) * np.sqrt(ANN)) if ret.std(ddof=1) > 0 else np.nan
    maxdd = _max_drawdown(eq["equity"])
    vol = float(ret.std(ddof=1) * np.sqrt(ANN)) * 100
    avg_expo = float(eq["exposure"].mean())
    avg_npos = float(eq["n_pos"].mean())
    calmar = cagr / abs(maxdd) if maxdd < 0 else np.nan

    res = {"start": str(cal[start].date()), "end": str(cal[-1].date()), "days": len(eq),
           "capital0": capital0, "equity_final": float(eq["equity"].iloc[-1]),
           "CAGR_pct": cagr * 100, "MaxDD_pct": maxdd * 100, "Sharpe_daily": sharpe,
           "Vol_ann_pct": vol, "Calmar": calmar, "avg_exposure_pct": avg_expo * 100,
           "avg_n_pos": avg_npos, "trades": trades, "score_thr": float(thr)}
    return eq, res


def _print(res):
    print("=" * 78)
    print(" HELD-PORTFOLIO BACKTEST — equity di percorso reale (mib_data_long.csv)")
    print("=" * 78)
    print(f" Periodo: {res['start']} -> {res['end']} ({res['days']} sedute) | capitale {res['capital0']:.0f}")
    print(f" Equity finale:   {res['equity_final']:,.0f}  ({res['equity_final']/res['capital0']:.2f}x)")
    print(f" CAGR:            {res['CAGR_pct']:+.2f}%")
    print(f" MaxDD (path):    {res['MaxDD_pct']:+.2f}%   <- drawdown REALE (non artefatto)")
    print(f" Sharpe (daily):  {res['Sharpe_daily']:+.2f}")
    print(f" Vol annua:       {res['Vol_ann_pct']:.2f}%")
    print(f" Calmar:          {res['Calmar']:+.2f}")
    print(f" Market Exposure: {res['avg_exposure_pct']:.1f}% media investita | "
          f"{res['avg_n_pos']:.1f} posizioni medie")
    print(f" Trade totali:    {res['trades']} | soglia score (top-quintile): {res['score_thr']:.3f}")
    print("=" * 78)
    print(" NB: max 10 posizioni x 10% = max 100% investito; il resto resta in CASSA (niente leva).")
    print(" NB: soglia score = p80 GLOBALE (lieve bias in-sample, come fix4/5) — confronta architettura,")
    print("     non e' una stima out-of-sample; per OOS usare soglia espandente (watch-list).")


if __name__ == "__main__":
    eq, res = backtest()
    _print(res)
