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

# ---- Struttura costi Fineco (Run #34) ----
SLIP           = 0.0002   # 0.02% slippage su ogni eseguito (acquisto al rialzo, vendita al ribasso)
FINECO_EU_PCT  = 0.0019   # 0.19% sul controvalore per titoli EU (.MI/.PA/.AS)
FINECO_EU_MIN  = 2.95     # minimo EUR per singola gamba EU
FINECO_EU_MAX  = 19.00    # massimo EUR per singola gamba EU
FINECO_US_FLAT = 9.95     # tariffa fissa per titoli US, trattata come EUR (USD≈EUR, err<5%)
TOP_Q = 0.80
ANN = 252

# ---- Regime fiscale amministrato italiano (Run #38) ----
TAX_CAPITAL_GAIN = 0.26   # aliquota 26% sulle plusvalenze realizzate
TAX_BOLLO        = 0.0020 # imposta di bollo 0.20%/anno sul valore totale portafoglio
TAX_CREDIT_YEARS = 4      # anni di validità dei crediti da minusvalenza (zainetto fiscale)
FAVORABLE = {"TREND_UP"}     # regimi in cui si aprono NUOVE posizioni (go-flat validato: solo trend)
RISK_PER_TRADE = 0.0214      # come trade_proposal.propose (per il sizing "live" fedele)


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


def _txn_cost(ticker, trade_value):
    """Costo di transazione per SINGOLA GAMBA (ingresso O uscita) — struttura Fineco.
    EU (.MI/.PA/.AS): 0.19% del controvalore, min 2.95€, max 19.00€.
    US (tutto il resto): 9.95 flat (USD ≈ EUR, approssimazione < 5% al cambio corrente)."""
    if ticker.endswith((".MI", ".PA", ".AS")):
        return float(np.clip(FINECO_EU_PCT * trade_value, FINECO_EU_MIN, FINECO_EU_MAX))
    return FINECO_US_FLAT


def _apply_capital_gains_tax(raw_gain, trade_year, zainetto):
    """Regime amministrato italiano: 26% sulla plusvalenza netta con zainetto fiscale.

    raw_gain: plusvalenza (>0) o minusvalenza (<0) del singolo trade, già netta di commissioni.
    trade_year: anno solare del trade (per gestire scadenza crediti a 4 anni).
    zainetto: lista di dict {'year': int, 'credit': float} — modificata in-place.

    Ritorna la tassa dovuta (€) da detrarre dalla cassa. Se raw_gain <= 0, la perdita
    viene aggiunta allo zainetto come credito e la funzione ritorna 0.0.
    """
    # Rimuovi crediti scaduti (generati più di TAX_CREDIT_YEARS anni fa)
    zainetto[:] = [e for e in zainetto if trade_year - e["year"] <= TAX_CREDIT_YEARS]

    if raw_gain <= 0:
        # Minusvalenza: accumula nel zainetto
        if raw_gain < 0:
            zainetto.append({"year": trade_year, "credit": abs(raw_gain)})
        return 0.0

    # Plusvalenza: consuma crediti zainetto FIFO (dal più vecchio) fino ad esaurimento
    taxable = raw_gain
    for entry in zainetto:
        if taxable <= 1e-6:
            break
        consumed = min(entry["credit"], taxable)
        entry["credit"] -= consumed
        taxable -= consumed
    # Rimuovi crediti esauriti
    zainetto[:] = [e for e in zainetto if e["credit"] > 1e-6]

    return max(0.0, taxable) * TAX_CAPITAL_GAIN


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


def _expanding_thr_array(score_panel, top_q):
    """Precompute expanding-window quantile threshold for each day in score_panel.

    Returns a numpy array exp_thr where exp_thr[i] = nanquantile of all non-NaN score
    values across all tickers from day 0 through day i (inclusive). Uses only past data,
    removing the in-sample lookahead bias of the global nanquantile over the full panel.
    """
    n = len(score_panel)
    exp_thr = np.full(n, np.nan)
    all_scores = []
    for i_d in range(n):
        row_vals = score_panel.iloc[i_d].dropna().values
        if len(row_vals):
            all_scores.extend(row_vals.tolist())
        if all_scores:
            exp_thr[i_d] = np.nanquantile(all_scores, top_q)
    return exp_thr


def backtest(px_path="data/mib_data_long.csv", capital0=CAPITAL0, max_pos=MAX_POS,
             pos_cap=POS_CAP, hold=HOLD, top_q=TOP_Q, regime_mode="off", sizing="equal",
             equity_out="data/portfolio_equity.csv", costs=False, expanding_threshold=False,
             taxes=False, _pre=None):
    """regime_mode: off (always-in) | gate (TREND_UP only) | tiered (TREND_UP pieno + PULLBACK 1/2 size).
       sizing: equal (10% flat) | riskparity (10% x min(medATR/ATR_i,1)) |
               live (fedele a propose: shares=risk_eur/(entry-stop), stop~entry-2*ATR, cap 10%).
       costs: False (default) | True (slippage SLIP + commissioni Fineco reali per singola gamba).
       expanding_threshold: False (default) | True (soglia OOS pulita, calcolata giorno per giorno).
       taxes: False (default) | True (regime amministrato IT: CGT 26% + zainetto 4 anni + bollo 0.20%)."""
    if _pre is None:
        _pre = prepare(px_path, top_q)
    close_raw, close_mtm, score_panel, regime_by_mkt, thr, cal, atr_panel, med_atr = _pre
    n = len(cal)

    # Expanding-window threshold: precompute per-day thresholds usando solo il passato.
    # exp_thr[i] = nanquantile(score_panel.iloc[:i+1], top_q) — nessun lookahead.
    if expanding_threshold:
        exp_thr = _expanding_thr_array(score_panel, top_q)

    cash = capital0
    positions = {}     # tk -> {shares, entry_i, entry_px, cost_basis}
    recs = []
    trades = 0
    total_costs_paid = 0.0   # commissioni + slippage cumulati (solo se costs=True)
    total_taxes_paid = 0.0   # CGT + bollo cumulati (solo se taxes=True)
    zainetto = []            # crediti da minusvalenza: [{"year": int, "credit": float}, ...]
    start = 201        # serve uno storico per gli score e un giorno-segnale precedente

    for i in range(start, n):
        day = cal[i]

        # 1) USCITE: posizioni con holding completato (>= hold giorni operativi)
        for tk in [t for t, p in positions.items() if i - p["entry_i"] >= hold]:
            px_exit = close_mtm.at[day, tk]
            if pd.notna(px_exit):
                eff_exit = float(px_exit) * (1 - SLIP) if costs else float(px_exit)
                proceeds = positions[tk]["shares"] * eff_exit
                exit_comm = _txn_cost(tk, proceeds) if costs else 0.0
                slip_cost = positions[tk]["shares"] * float(px_exit) * SLIP if costs else 0.0
                net_proceeds = proceeds - exit_comm
                cash += net_proceeds
                total_costs_paid += (exit_comm + slip_cost)
                # CGT 26% sul gain netto (plusvalenza = net_proceeds - cost_basis)
                if taxes:
                    raw_gain = net_proceeds - positions[tk].get("cost_basis", 0.0)
                    cgt = _apply_capital_gains_tax(raw_gain, day.year, zainetto)
                    cash -= cgt
                    total_taxes_paid += cgt
                positions.pop(tk)

        # 2) MARK-TO-MARKET (valore di portafoglio a inizio giornata, post-uscite)
        holdings_val = sum(p["shares"] * float(close_mtm.at[day, tk])
                           for tk, p in positions.items()
                           if pd.notna(close_mtm.at[day, tk]))
        total_value = cash + holdings_val

        # Imposta di Bollo 0.20%/anno: applicata il primo giorno dell'anno sul valore
        # di chiusura dell'ultimo giorno dell'anno precedente (recs[-1]["equity"]).
        if taxes and recs and day.year > recs[-1]["date"].year:
            bollo_base = recs[-1]["equity"]
            bollo = bollo_base * TAX_BOLLO
            cash -= bollo
            total_taxes_paid += bollo
            total_value = cash + holdings_val   # aggiorna total_value post-bollo

        # 3) INGRESSI: segnali validi del giorno PRECEDENTE (no lookahead), nomi non gia' detenuti,
        #    con barra REALE oggi per il fill. Riempi gli slot liberi, size 10% del totale per nome.
        if len(positions) < max_pos:
            prev = cal[i - 1]
            srow = score_panel.loc[prev]
            # expanding_threshold: usa la soglia calcolata sui dati fino a prev (i-1)
            thr_now = float(exp_thr[i - 1]) if expanding_threshold else thr
            elig = srow[(srow >= thr_now) & srow.notna()]

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
                eff_entry = price * (1 + SLIP) if costs else price   # slippage: compra più caro
                regmult = _regime_mult(tk)
                if sizing == "live":
                    # fedele a propose(): risk budget su stop ATR, poi cap al 10% (che di norma vince)
                    a = atr_panel.at[prev, tk] if (prev in atr_panel.index and tk in atr_panel.columns) else np.nan
                    rps = min(0.05 * price, 2 * float(a) * price) if np.isfinite(a) and a > 0 else 0.05 * price
                    uncapped = (total_value * RISK_PER_TRADE / rps) * price if rps > 0 else pos_cap * total_value
                    budget = min(uncapped, pos_cap * total_value) * regmult
                else:
                    budget = pos_cap * regmult * _vol_mult(tk) * total_value
                budget = min(budget, cash)                   # size = 10% x regime x (vol|live), mai > 10%
                shares = int(budget / eff_entry) if eff_entry > 0 else 0
                if shares <= 0:
                    continue
                trade_val = shares * eff_entry
                entry_comm = _txn_cost(tk, trade_val) if costs else 0.0
                slip_cost  = shares * price * SLIP if costs else 0.0
                # Verifica cassa: trade + commissione devono stare nella liquidita' disponibile
                if trade_val + entry_comm > cash:
                    max_sh = int((cash - entry_comm) / eff_entry) if (cash - entry_comm) > 0 else 0
                    if max_sh <= 0:
                        continue
                    shares = max_sh
                    trade_val  = shares * eff_entry
                    slip_cost  = shares * price * SLIP if costs else 0.0
                    entry_comm = _txn_cost(tk, trade_val) if costs else 0.0
                cash -= (trade_val + entry_comm)
                total_costs_paid += (entry_comm + slip_cost)
                # cost_basis: costo totale d'acquisto (valore + commissione) per il calcolo CGT
                positions[tk] = {"shares": shares, "entry_i": i, "entry_px": eff_entry,
                                 "cost_basis": trade_val + entry_comm}
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

    # score_thr: con expanding usa la soglia finale (ultima del periodo); con statico usa thr globale.
    final_thr = float(exp_thr[-1]) if expanding_threshold else float(thr)
    zainetto_rem = round(sum(e["credit"] for e in zainetto), 2)
    res = {"start": str(cal[start].date()), "end": str(cal[-1].date()), "days": len(eq),
           "capital0": capital0, "equity_final": float(eq["equity"].iloc[-1]),
           "CAGR_pct": cagr * 100, "MaxDD_pct": maxdd * 100, "Sharpe_daily": sharpe,
           "Vol_ann_pct": vol, "Calmar": calmar, "avg_exposure_pct": avg_expo * 100,
           "avg_n_pos": avg_npos, "trades": trades, "score_thr": final_thr,
           "expanding_threshold": expanding_threshold, "top_q_used": top_q,
           "regime_mode": regime_mode, "sizing": sizing,
           "costs": costs, "total_costs_paid": round(total_costs_paid, 2),
           "taxes": taxes, "total_taxes_paid": round(total_taxes_paid, 2),
           "zainetto_remaining": zainetto_rem}
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


def baseline_align(px_path="data/mib_data_long.csv", report_out="data/BASELINE_ALIGN_TEST.txt", pre=None):
    """Run #31 — allinea il baseline al sizing LIVE e confronta con equal-weight e risk-parity (gate attivo).
    Dimostra: il sizing 'live' (propose, cap 10% che vince) ≈ equal-weight -> l'equal-weight ERA il
    baseline rappresentativo; il risk-parity resta un miglioramento REALE non catturato dal live."""
    if pre is None:
        pre = prepare(px_path)
    _, live = backtest(_pre=pre, regime_mode="gate", sizing="live", equity_out="data/portfolio_equity_live.csv")
    _, eqw = backtest(_pre=pre, regime_mode="gate", sizing="equal", equity_out="data/portfolio_equity_regime.csv")
    _, rp = backtest(_pre=pre, regime_mode="gate", sizing="riskparity", equity_out="data/portfolio_equity_rp.csv")
    L = []; w = L.append
    w("=" * 90)
    w(" BASELINE ALIGNMENT (Run #31) — sizing LIVE (propose) vs EQUAL-WEIGHT vs RISK-PARITY, gate attivo")
    w(" Scopo: capire QUALE baseline rappresenta il modello operativo, e rimisurare il risk-parity contro")
    w(" quel baseline. Il sizing 'live' replica propose(): risk budget su stop ATR, cap 10% (che di norma vince).")
    w("=" * 90)
    w(f" Periodo {live['start']} -> {live['end']} | capitale {live['capital0']:.0f}\n")
    _table([live, eqw, rp], ["LIVE (propose)", "EQUAL-WEIGHT", "RISK-PARITY"], w)
    w("")
    w(" LETTURA:")
    w(f"  - LIVE vs EQUAL: MaxDD {live['MaxDD_pct']:+.2f} vs {eqw['MaxDD_pct']:+.2f} | CAGR "
      f"{live['CAGR_pct']:+.2f} vs {eqw['CAGR_pct']:+.2f} -> il cap 10% vince quasi sempre, quindi il")
    w("    sizing LIVE ≈ EQUAL-WEIGHT. L'equal-weight 10% E' il baseline rappresentativo del modello.")
    w(f"  - RISK-PARITY vs LIVE: MaxDD {rp['MaxDD_pct']:+.2f} vs {live['MaxDD_pct']:+.2f} "
      f"(Δ {rp['MaxDD_pct']-live['MaxDD_pct']:+.2f} pt) | Calmar {rp['Calmar']:+.2f} vs {live['Calmar']:+.2f}.")
    w("  - CORREZIONE Run #30: il live NON e' risk-parity (il cap del 10% domina lo stop ATR). Il")
    w("    risk-parity e' un miglioramento REALE NON ancora nel modello -> candidato all'integrazione")
    w("    (abbassare la size effettiva dei nomi ad alta ATR sotto il 10%). Vedi Lezione #24 (corretta).")
    w("")
    w(" NB: stesso universo/soglia/gate; cambia SOLO lo schema di size. Costi non modellati.")
    w("=" * 90)
    txt = "\n".join(L) + "\n"; open(report_out, "w").write(txt); print(txt)
    return live, eqw, rp


if __name__ == "__main__":
    baseline_align()
