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
from indicators import adx, rsi_wilder, atr_wilder
from regime_filter import market_of, INDEX_BY_MARKET

CAPITAL0 = 100_000.0
MAX_POS = 10
POS_CAP = 0.10           # 10% del capitale totale per posizione
HOLD = 10                # giorni operativi
TOP_Q = 0.80
ANN = 252
FAVORABLE = {"TREND_UP"}     # regimi in cui si aprono NUOVE posizioni (go-flat validato: solo trend)


def regime_series(g, slope_window=20, flat_slope=1.0):
    """classify_regime VETTORIZZATO per l'indice di un mercato (serie giornaliera di regime).
    Stessa logica causale di regime_filter.classify_regime (condizioni mutuamente esclusive)."""
    c = g["close"]
    sma20 = c.rolling(20).mean()
    sma50 = c.rolling(50).mean()
    sma200 = c.rolling(200).mean()
    slope50 = (sma50 / sma50.shift(slope_window) - 1) * 100
    above20, above50, above200 = c > sma20, c > sma50, c > sma200
    rising, falling = slope50 > flat_slope, slope50 < -flat_slope
    reg = pd.Series("LATERALE", index=c.index)
    reg = reg.mask(above200 & ~above20, "PULLBACK")
    reg = reg.mask((~above200) & falling, "TREND_DOWN")
    reg = reg.mask(above50 & above200 & rising & above20, "TREND_UP")
    reg.iloc[:200] = "INSUFF"
    return reg


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


def prepare(px_path="data/mib_data_long.csv", top_q=TOP_Q):
    """Precompute (costoso) condiviso tra i due rami dell'A/B: prezzi, score, regime per mercato."""
    px = pd.read_csv(px_path, parse_dates=["date"]).dropna(subset=["close"]).sort_values(["ticker", "date"])
    close_raw = px.pivot(index="date", columns="ticker", values="close").sort_index()
    close_mtm = close_raw.ffill()
    scores, atrp = {}, {}
    for tk in px["ticker"].unique():
        g = px[px.ticker == tk].set_index("date").sort_index()
        scores[tk] = score_series(g[["close", "high", "low"]])
        atrp[tk] = atr_wilder(g["high"], g["low"], g["close"], 14) / g["close"]   # ATR in frazione di prezzo
    score_panel = pd.DataFrame(scores).reindex(close_raw.index)
    atr_panel = pd.DataFrame(atrp).reindex(close_raw.index)
    thr = np.nanquantile(score_panel.values, top_q)
    med_atr = float(np.nanmedian(atr_panel.values))   # ATR% mediano (riferimento risk parity)
    # regime giornaliero per mercato (dall'indice di riferimento), ffilled sul calendario globale
    regime_by_mkt = {}
    for mkt, idx in INDEX_BY_MARKET.items():
        sub = px[px.ticker == idx].set_index("date").sort_index()
        if sub.empty:
            continue
        regime_by_mkt[mkt] = regime_series(sub[["close"]]).reindex(close_raw.index).ffill()
    cal = list(close_raw.index)
    return close_raw, close_mtm, score_panel, regime_by_mkt, thr, cal, atr_panel, med_atr


def backtest(px_path="data/mib_data_long.csv", capital0=CAPITAL0, max_pos=MAX_POS,
             pos_cap=POS_CAP, hold=HOLD, top_q=TOP_Q, regime_mode="off", sizing="equal",
             equity_out="data/portfolio_equity.csv", _pre=None):
    """regime_mode: off (always-in) | gate (TREND_UP only) | tiered (TREND_UP pieno + PULLBACK 1/2 size).
       sizing: equal (10% flat) | riskparity (10% scalato da min(medATR/ATR_i, 1): vol alta pesa meno)."""
    if _pre is None:
        _pre = prepare(px_path, top_q)
    close_raw, close_mtm, score_panel, regime_by_mkt, thr, cal, atr_panel, med_atr = _pre
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

            def _regime_mult(tk):
                # moltiplicatore di size dal regime del mercato al giorno-segnale (prev, no lookahead)
                if regime_mode == "off":
                    return 1.0
                rs = regime_by_mkt.get(market_of(tk))
                r = rs.get(prev) if rs is not None else None
                if regime_mode == "gate":
                    return 1.0 if r == "TREND_UP" else 0.0
                if regime_mode == "tiered":
                    return 1.0 if r == "TREND_UP" else (0.5 if r == "PULLBACK" else 0.0)
                return 1.0

            def _vol_mult(tk):
                # risk parity: rischio paritario col cap del 10% -> vol alta pesa MENO, mai piu' del 10%
                if sizing != "riskparity":
                    return 1.0
                a = atr_panel.at[prev, tk] if (prev in atr_panel.index and tk in atr_panel.columns) else np.nan
                if not np.isfinite(a) or a <= 0:
                    return 1.0
                return float(min(med_atr / a, 1.0))

            elig = elig[[tk for tk in elig.index
                         if tk not in positions and pd.notna(close_raw.at[day, tk]) and _regime_mult(tk) > 0]]
            elig = elig.sort_values(ascending=False)
            for tk in elig.index:
                if len(positions) >= max_pos:
                    break
                price = float(close_raw.at[day, tk])
                mult = _regime_mult(tk) * _vol_mult(tk)      # size = 10% x regime x vol (mai > 10%)
                budget = min(pos_cap * mult * total_value, cash)
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
           "avg_n_pos": avg_npos, "trades": trades, "score_thr": float(thr),
           "regime_mode": regime_mode, "sizing": sizing}
    return eq, res


_METRIC_ROWS = [
    ("Equity finale", "{:,.0f}", "equity_final"),
    ("CAGR %", "{:+.2f}", "CAGR_pct"),
    ("MaxDD % (path)", "{:+.2f}", "MaxDD_pct"),
    ("Sharpe (daily)", "{:+.2f}", "Sharpe_daily"),
    ("Vol annua %", "{:.2f}", "Vol_ann_pct"),
    ("Calmar", "{:+.2f}", "Calmar"),
    ("Market Exposure % media", "{:.1f}", "avg_exposure_pct"),
    ("Posizioni medie", "{:.1f}", "avg_n_pos"),
    ("Trade totali", "{:d}", "trades"),
]


def _table(results, names, w):
    """Stampa una tabella affiancata di N scenari (results: lista di dict res; names: intestazioni)."""
    head = " " + f"{'METRICA':26s}" + "".join(f"{nm:>16s}" for nm in names)
    w(head)
    w(" " + "-" * (26 + 16 * len(names)))
    for label, fmt, key in _METRIC_ROWS:
        w(" " + f"{label:26s}" + "".join(f"{fmt.format(r[key]):>16s}" for r in results))


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


def ab_pullback(px_path="data/mib_data_long.csv", report_out="data/REGIME_PULLBACK_TEST.txt", pre=None):
    """Run #29 — 3 vie: OFF (always-in) vs GATE (TREND_UP only) vs TIERED (TREND_UP pieno + PULLBACK 1/2)."""
    if pre is None:
        pre = prepare(px_path)
    _, off = backtest(_pre=pre, regime_mode="off", equity_out="data/portfolio_equity.csv")
    _, gate = backtest(_pre=pre, regime_mode="gate", equity_out="data/portfolio_equity_regime.csv")
    _, tier = backtest(_pre=pre, regime_mode="tiered", equity_out="data/portfolio_equity_tiered.csv")
    L = []; w = L.append
    w("=" * 90)
    w(" REGIME SIZING — 3 vie (Run #29): OFF vs GATE (TREND_UP) vs TIERED (TREND_UP + PULLBACK 1/2)")
    w(" Il TIERED apre a META' size anche in PULLBACK (px sotto SMA20 ma sopra SMA200): recupera")
    w(" esposizione mantenendo il go-flat nei regimi davvero ostili (LATERALE/TREND_DOWN).")
    w("=" * 90)
    w(f" Periodo {off['start']} -> {off['end']} | capitale {off['capital0']:.0f}\n")
    _table([off, gate, tier], ["A OFF", "B GATE", "C TIERED"], w)
    w("")
    w(" LETTURA (focus: il TIERED recupera CAGR/esposizione senza riportare su il MaxDD?):")
    w(f"  - MaxDD:  OFF {off['MaxDD_pct']:+.2f} | GATE {gate['MaxDD_pct']:+.2f} | TIERED {tier['MaxDD_pct']:+.2f}")
    w(f"  - Calmar: OFF {off['Calmar']:+.2f} | GATE {gate['Calmar']:+.2f} | TIERED {tier['Calmar']:+.2f}")
    w(f"  - Expo%:  OFF {off['avg_exposure_pct']:.1f} | GATE {gate['avg_exposure_pct']:.1f} | TIERED {tier['avg_exposure_pct']:.1f}")
    best = max([gate, tier], key=lambda r: r["Calmar"])
    w(f"  - Miglior Calmar tra GATE/TIERED: {'TIERED' if best is tier else 'GATE'} "
      f"({best['Calmar']:+.2f}). {'Il PULLBACK a mezza size aggiunge valore.' if best is tier else 'Il PULLBACK a mezza size NON migliora: tenere il gate binario.'}")
    w("")
    w(" NB: stesso universo e soglia (p80 globale); cambia SOLO la regola di regime/size. Costi non modellati.")
    w("=" * 90)
    txt = "\n".join(L) + "\n"; open(report_out, "w").write(txt); print(txt)
    return off, gate, tier


def _mdd_from_ret(r):
    eq = (1 + r).cumprod()
    return float((eq / eq.cummax() - 1).min())


def _paired_boot(rA, rB, n_boot=2000, block=10, seed=42):
    """Bootstrap a blocchi PAIRED su due serie di rendimenti giornalieri allineate.
    Ritorna IC95% di Δ MaxDD (pt%) e Δ Sharpe (B-A), misurati sulle STESSE date ricampionate."""
    df = pd.concat([rA, rB], axis=1).dropna()
    df.columns = ["A", "B"]
    n = len(df); rng = np.random.default_rng(seed); nb = int(np.ceil(n / block))
    dMDD, dSh = [], []
    for _ in range(n_boot):
        starts = rng.integers(0, n, size=nb)
        idx = np.concatenate([np.arange(s, min(s + block, n)) for s in starts])[:n]
        sub = df.iloc[idx]
        a, b = sub["A"], sub["B"]
        dMDD.append((_mdd_from_ret(b) - _mdd_from_ret(a)) * 100)
        sa = a.std(ddof=1); sb = b.std(ddof=1)
        if sa > 0 and sb > 0:
            dSh.append((b.mean() / sb - a.mean() / sa) * np.sqrt(ANN))
    f = lambda v: (float(np.percentile(v, 2.5)), float(np.median(v)), float(np.percentile(v, 97.5)))
    return f(dMDD), f(dSh)


def ab_riskparity(px_path="data/mib_data_long.csv", report_out="data/RISKPARITY_HELD_TEST.txt", pre=None):
    """Run #30 — FIX 5 ri-testato sul motore REALE col gate attivo: equal-weight vs risk-parity (inverse-ATR)."""
    if pre is None:
        pre = prepare(px_path)
    eq_eqw, eqw = backtest(_pre=pre, regime_mode="gate", sizing="equal",
                           equity_out="data/portfolio_equity_regime.csv")
    eq_rp, rp = backtest(_pre=pre, regime_mode="gate", sizing="riskparity",
                         equity_out="data/portfolio_equity_rp.csv")
    rA = eq_eqw["equity"].pct_change().dropna()
    rB = eq_rp["equity"].pct_change().dropna()
    (mdd_lo, mdd_md, mdd_hi), (sh_lo, sh_md, sh_hi) = _paired_boot(rA, rB)
    L = []; w = L.append
    w("=" * 86)
    w(" RISK PARITY su HELD-PORTFOLIO col gate di regime (Run #30) — il test CORRETTO di FIX 5")
    w(" Sizing 10% x min(medATR/ATR_i, 1): i nomi piu' volatili pesano MENO (mai oltre il 10%),")
    w(" il resto resta in cassa. Qui il vol-sizing agisce tra posizioni CONCORRENTI (vs Lezione #22).")
    w("=" * 86)
    w(f" Periodo {eqw['start']} -> {eqw['end']} | capitale {eqw['capital0']:.0f} | regime-gate attivo\n")
    _table([eqw, rp], ["EQUAL-WEIGHT", "RISK-PARITY"], w)
    w("")
    dd = rp["MaxDD_pct"] - eqw["MaxDD_pct"]
    w(" LETTURA (decisione = abbattimento SISTEMATICO del MaxDD: IC95% del ΔMaxDD che esclude lo 0):")
    w(f"  - ΔMaxDD punto: {dd:+.2f} pt | bootstrap PAIRED IC95% [{mdd_lo:+.2f}, {mdd_hi:+.2f}] (mediana {mdd_md:+.2f})")
    w(f"  - ΔSharpe punto: {rp['Sharpe_daily']-eqw['Sharpe_daily']:+.2f} | IC95% [{sh_lo:+.2f}, {sh_hi:+.2f}]")
    w(f"  - Calmar {eqw['Calmar']:+.2f} -> {rp['Calmar']:+.2f} | Exposure {eqw['avg_exposure_pct']:.1f}% -> "
      f"{rp['avg_exposure_pct']:.1f}% (scarica i nomi volatili, piu' cassa).")
    sig = mdd_lo > 0
    w(f"  - ESITO: ΔMaxDD IC95% {'ESCLUDE' if sig else 'ATTRAVERSA'} lo 0 -> "
      f"{'abbattimento SISTEMATICO confermato' if sig else 'non significativo'}.")
    w("  - NB INTEGRAZIONE: il modello LIVE (trade_proposal.propose) GIA' dimensiona per rischio ATR")
    w("    (shares = risk_eur / (entry-stop), stop ~ entry-2*ATR -> pos_value ∝ 1/ATR%, cap 10%):")
    w("    e' gia' risk-parity. Questo test VALIDA quel design; il baseline equal-weight 10% flat era")
    w("    il ramo NON rappresentativo del live. Nessun nuovo codice di sizing da aggiungere.")
    w("")
    w(" NB: vs FIX 5 (Run #26) sul harness per-segnale (MaxDD artefatto -95%, effetto non misurabile):")
    w("     qui il MaxDD e' di percorso reale e le posizioni sono concorrenti -> test equo (Lezione #22).")
    w(" NB: stesso universo/soglia/gate; cambia SOLO lo schema di size. Costi non modellati.")
    w("=" * 86)
    txt = "\n".join(L) + "\n"; open(report_out, "w").write(txt); print(txt)
    return eqw, rp


if __name__ == "__main__":
    _pre = prepare()
    ab_pullback(pre=_pre)
    print()
    ab_riskparity(pre=_pre)
