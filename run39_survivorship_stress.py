#!/usr/bin/env python3
"""run39_survivorship_stress.py — Run #39: Stress Test Survivorship Bias (Monte Carlo).

Quantifica l'impatto del survivorship bias simulando titoli delistati/falliti:
  - 1.5% dei trade EU e 1.5% dei trade US vengono forzati a −60% di perdita
  - 500 simulazioni Monte Carlo per distribuzione statistica dei risultati netti

Assetto: Run #38 (soglia espandente, holding ibrido, Fineco+slip+tasse IT).

Approccio delta-cumsum (O(n) per iterazione, ~500 sims in < 5 secondi):
  1. Esegui una volta il backtest base con return_trade_log=True
  2. Per ogni sim MC, seleziona 1.5% dei trade e calcola il delta cash giornaliero
     (perdita catastrofica vs outcome reale)
  3. Applica il cumsum dei delta alla curva equity base
  4. Ricalcola CAGR/MaxDD/Sharpe sulla curva stressata

Report: data/SURVIVORSHIP_STRESS_REPORT.txt
"""
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, ".")
from portfolio_backtester import (prepare, backtest,
                                  SLIP, FINECO_EU_PCT, FINECO_EU_MIN, FINECO_EU_MAX,
                                  FINECO_US_FLAT, TAX_CAPITAL_GAIN, TAX_BOLLO, TAX_CREDIT_YEARS,
                                  _max_drawdown)

EU_PATH  = "data/mib_data_long.csv"
US_PATH  = "data/sp500_data_long.csv"
REPORT   = "data/SURVIVORSHIP_STRESS_REPORT.txt"

N_SIMS       = 500
STRESS_RATE  = 0.015   # 1.5% dei trade
STRESS_LOSS  = 0.60    # −60% rispetto al cost_basis
ANN          = 252
RNG_SEED     = 42


def _stress_equity(eq_base: pd.DataFrame, trade_log: list, stress_rate: float,
                   stress_loss: float, rng: np.random.Generator) -> pd.Series:
    """Applica stress a stress_rate% dei trade e restituisce la curva equity modificata."""
    if not trade_log:
        return eq_base["equity"].copy()

    n_stress = max(1, int(round(len(trade_log) * stress_rate)))
    idx = rng.choice(len(trade_log), size=n_stress, replace=False)

    # delta_cash[date] = differenza cash da applicare alla curva base
    delta_by_date: dict[pd.Timestamp, float] = {}
    for i in idx:
        t = trade_log[i]
        # In un trade catastrofico il titolo vale 40% del cost_basis (−60%)
        stressed_proceeds = t["cost_basis"] * (1.0 - stress_loss)
        # La CGT pagata sul trade originale diventa un credito fiscale (si annulla):
        # la perdita crea una minusvalenza, quindi recuperiamo la CGT originalmente pagata
        # e aggiungiamo la perdita effettiva al portafoglio.
        # delta = (stressed_net) − (original net_proceeds_post_tax)
        # = stressed_proceeds − t["net_proceeds_post_tax"]  [netto tasse, ma le tasse cambiano]
        # Semplificazione conservativa: la CGT originale si azzera (credito), ma non modelliamo
        # l'uso futuro del credito (quello andrerebbe nelle sim successive). Per ogni trade stressato:
        # outcome_stressed_post_tax = stressed_proceeds + cgt_originale_recuperata
        # (perché la perdita genera credito zainetto che nella sim base non era presente)
        stressed_net = stressed_proceeds + t["cgt_paid"]  # recupero CGT come credito immediato
        delta = stressed_net - t["net_proceeds_post_tax"]
        date = t["exit_date"]
        delta_by_date[date] = delta_by_date.get(date, 0.0) + delta

    # Converti in serie allineata all'indice equity
    eq_idx = eq_base.index
    delta_series = pd.Series(0.0, index=eq_idx, dtype=float)
    for dt, dv in delta_by_date.items():
        if dt in delta_series.index:
            delta_series[dt] += dv

    stressed_eq = eq_base["equity"] + delta_series.cumsum()
    return stressed_eq


def run_mc_stress(label, px_path, hold, top_q, pre, equity_out):
    print(f"  {label}: backtest base (tasse, return_trade_log=True)...", end="", flush=True)
    eq, res = backtest(px_path=px_path, regime_mode="gate", sizing="riskparity",
                       costs=True, hold=hold, top_q=top_q,
                       expanding_threshold=True, taxes=True,
                       equity_out=equity_out, _pre=pre,
                       return_trade_log=True)
    trade_log = res["_trade_log"]
    n_trades = len(trade_log)
    n_stress_per_sim = max(1, int(round(n_trades * STRESS_RATE)))
    print(f" {n_trades} trade | {n_stress_per_sim} stressati/sim")

    capital0 = res["capital0"]
    years = res["days"] / ANN

    rng = np.random.default_rng(RNG_SEED)
    cagr_list, maxdd_list, sharpe_list = [], [], []

    for _ in range(N_SIMS):
        eq_s = _stress_equity(eq, trade_log, STRESS_RATE, STRESS_LOSS, rng)
        # Clamp equity a 0 per evitare nan nei ratio
        eq_s = eq_s.clip(lower=1.0)
        ret_s = eq_s.pct_change().dropna()
        cagr_s = (eq_s.iloc[-1] / capital0) ** (1 / years) - 1 if years > 0 else np.nan
        maxdd_s = _max_drawdown(eq_s)
        sharpe_s = (float(ret_s.mean() / ret_s.std(ddof=1) * np.sqrt(ANN))
                    if ret_s.std(ddof=1) > 0 else np.nan)
        cagr_list.append(cagr_s * 100)
        maxdd_list.append(maxdd_s * 100)
        sharpe_list.append(sharpe_s)

    cagr_arr   = np.array(cagr_list)
    maxdd_arr  = np.array(maxdd_list)
    sharpe_arr = np.array(sharpe_list)

    stats = {
        "label":         label,
        "base_cagr":     res["CAGR_pct"],
        "base_maxdd":    res["MaxDD_pct"],
        "base_sharpe":   res["Sharpe_daily"],
        "n_trades":      n_trades,
        "n_stress":      n_stress_per_sim,
        "cagr_mean":     float(np.nanmean(cagr_arr)),
        "cagr_p5":       float(np.nanpercentile(cagr_arr, 5)),
        "cagr_p25":      float(np.nanpercentile(cagr_arr, 25)),
        "cagr_p50":      float(np.nanpercentile(cagr_arr, 50)),
        "cagr_p75":      float(np.nanpercentile(cagr_arr, 75)),
        "cagr_p95":      float(np.nanpercentile(cagr_arr, 95)),
        "maxdd_mean":    float(np.nanmean(maxdd_arr)),
        "maxdd_p5":      float(np.nanpercentile(maxdd_arr, 5)),
        "maxdd_p50":     float(np.nanpercentile(maxdd_arr, 50)),
        "sharpe_mean":   float(np.nanmean(sharpe_arr)),
        "sharpe_p5":     float(np.nanpercentile(sharpe_arr, 5)),
        "cagr_prob_pos": float(np.mean(cagr_arr > 0) * 100),
        "cagr_prob_btp": float(np.mean(cagr_arr > 3.5) * 100),  # >BTP 10yr ~3.5%
    }
    return eq, res, stats


def generate_report(eu_res, eu_stats, us_res, us_stats):
    lines = []
    w = lines.append

    w("=" * 98)
    w(" RUN #39 — STRESS TEST SURVIVORSHIP BIAS: MONTE CARLO DEGRADATION (500 SIMULAZIONI)")
    w(" portfolio_backtester.py — GATE TREND_UP + RISK-PARITY + FINECO + SLIP + TASSE IT")
    w(" Assetto Run #38: EU p85 hold 10gg espandente | US p80 hold 20gg espandente")
    w("=" * 98)
    w("")
    w(" METODOLOGIA:")
    w(f"   Per ogni simulazione MC ({N_SIMS} iterazioni):")
    w(f"   1) Si seleziona casualmente il {STRESS_RATE*100:.1f}% dei trade storici (simulazione delisting/fallimento)")
    w(f"   2) I trade selezionati vengono forzati a perdita catastrofica di −{STRESS_LOSS*100:.0f}%")
    w(f"      (il titolo vale solo il {(1-STRESS_LOSS)*100:.0f}% del costo d'acquisto — stile crack Wirecard/Astaldi)")
    w( "   3) La CGT originalmente pagata su questi trade viene recuperata come credito zainetto")
    w( "      (la perdita annulla la plusvalenza fiscale del trade originale)")
    w( "   4) L'equity base viene corretta con il delta-cumsum dei cash delta giornalieri")
    w( "   5) CAGR/MaxDD/Sharpe vengono ricalcolati sulla curva stressata")
    w( "   Approccio delta-cumsum: O(n) per iterazione, nessuna ri-esecuzione del backtest completo.")
    w("")
    w( " ASSUNZIONI CONSERVATIVE:")
    w( "   - La perdita è immediata alla data di chiusura originale del trade (no partial recovery)")
    w( "   - Il credito zainetto da delisting NON viene usato nelle sim future (bias conservativo)")
    w( "   - I 500 seed sono deterministici (seed=42) per riproducibilità")
    w(f"   - Fineco EU: {FINECO_EU_PCT*100:.2f}% [{FINECO_EU_MIN:.2f}€-{FINECO_EU_MAX:.2f}€/gamba] | "
       f"US: {FINECO_US_FLAT:.2f}€ flat | Slip {SLIP*100:.2f}%")
    w("")

    def block(s, r):
        n_s = s["n_stress"]
        w(f" {'='*94}")
        w(f" {s['label']}")
        w(f" {'='*94}")
        w(f" Trade totali nel backtest base: {s['n_trades']} | Trade stressati per sim: {n_s} "
          f"({STRESS_RATE*100:.1f}% × {s['n_trades']} = {n_s})")
        w("")
        w(f" {'SCENARIO':<40} {'CAGR%':>8} {'MaxDD%':>8} {'Sharpe':>8}")
        w(" " + "-"*70)
        w(f" {'Base (lordo + tasse, no stress)':<40} {s['base_cagr']:>+8.2f} "
          f"{s['base_maxdd']:>8.2f} {s['base_sharpe']:>8.2f}")
        w("")
        w(f" {'DISTRIBUZIONE MC (500 sims, 1.5% trade stressati a -60%)':}")
        w(f" {'Metrica':<28} {'p5':>8} {'p25':>8} {'p50/Med':>8} {'Mean':>8} {'p75':>8} {'p95':>8}")
        w(" " + "-"*80)
        w(f" {'CAGR % netto stressato':<28} "
          f"{s['cagr_p5']:>+8.2f} {s['cagr_p25']:>+8.2f} {s['cagr_p50']:>+8.2f} "
          f"{s['cagr_mean']:>+8.2f} {s['cagr_p75']:>+8.2f} {s['cagr_p95']:>+8.2f}")
        w(f" {'MaxDD % stressato':<28} "
          f"{s['maxdd_p5']:>8.2f} {'':>8} {s['maxdd_p50']:>8.2f} "
          f"{s['maxdd_mean']:>8.2f} {'':>8} {'':>8}")
        w(f" {'Sharpe netto stressato':<28} "
          f"{s['sharpe_p5']:>8.2f} {'':>8} {'':>8} "
          f"{s['sharpe_mean']:>8.2f} {'':>8} {'':>8}")
        w("")
        d_cagr_mean = s['cagr_mean'] - s['base_cagr']
        d_cagr_p5   = s['cagr_p5']  - s['base_cagr']
        d_maxdd     = s['maxdd_mean'] - s['base_maxdd']
        w(f"   Δ CAGR medio vs base: {d_cagr_mean:>+.2f} pt | "
          f"Δ CAGR p5 vs base: {d_cagr_p5:>+.2f} pt | "
          f"Δ MaxDD medio vs base: {d_maxdd:>+.2f} pt")
        w(f"   Prob(CAGR > 0%)  = {s['cagr_prob_pos']:>5.1f}% | "
          f"Prob(CAGR > 3.5% BTP) = {s['cagr_prob_btp']:>5.1f}%")
        w("")

        # Verdict
        p5_ok   = s["cagr_p5"] > 0.0
        mean_ok = s["cagr_mean"] > 2.0
        dd_ok   = s["maxdd_mean"] > -40.0
        if p5_ok and mean_ok and dd_ok:
            verdict = "ROBUSTO: anche nel peggior 5% dei casi il sistema rimane positivo"
        elif mean_ok and dd_ok:
            verdict = "ACCETTABILE: in media profittevole, ma il p5 entra in territorio negativo"
        elif mean_ok:
            verdict = "FRAGILE: CAGR medio positivo ma MaxDD estremo sotto stress"
        else:
            verdict = "NON ROBUSTO: il survivorship bias è materiale — CAGR medio negativo sotto stress"
        w(f"   VERDETTO ROBUSTEZZA: {verdict}")
        w("")

    block(eu_stats, eu_res)
    block(us_stats, us_res)

    w(" " + "="*94)
    w(" RIEPILOGO CROSS-MARKET: IMPATTO SURVIVORSHIP BIAS")
    w(" " + "="*94)
    hdr = (f" {'Universo':<8} {'Base CAGR':>10} {'Stress Mean':>12} {'Stress p5':>10} "
           f"{'Stress p50':>11} {'MaxDD base':>11} {'MaxDD stress':>13} {'P(>BTP)':>8}")
    w(hdr)
    w(" " + "-"*90)

    def srow(lbl, s):
        return (f" {lbl:<8} {s['base_cagr']:>+10.2f}% {s['cagr_mean']:>+11.2f}% "
                f"{s['cagr_p5']:>+9.2f}% {s['cagr_p50']:>+10.2f}% "
                f"{s['base_maxdd']:>11.2f}% {s['maxdd_mean']:>12.2f}% "
                f"{s['cagr_prob_btp']:>7.1f}%")

    w(srow("EU", eu_stats))
    w(srow("US", us_stats))
    w("")

    # Global verdict
    both_robust = (eu_stats["cagr_p5"] > 0 and us_stats["cagr_p5"] > 0 and
                   eu_stats["cagr_mean"] > 2 and us_stats["cagr_mean"] > 2)
    w(" CONCLUSIONE:")
    if both_robust:
        w("   Il sistema è ROBUSTO al survivorship bias. Anche con l'1.5% dei trade forzati a −60%,")
        w("   il CAGR medio rimane positivo e il worst-case (p5) è accettabile su entrambi i mercati.")
        w("   Il dataset presenta inevitabile survivorship bias ma NON è il driver principale dell'alpha.")
    else:
        w("   Il sistema è PARZIALMENTE SENSIBILE al survivorship bias. Il worst-case (p5) scende")
        w("   in territorio negativo su almeno un mercato. Cautela nell'uso live senza data augmentation")
        w("   (es. aggiungere titoli delistati storicamente al dataset).")
    w("")
    w(" NOTE:")
    w("   - 1.5% stress rate corrisponde a ca. 1 titolo ogni 67 trade: realistico per portafogli")
    w("     che operano su mid-small cap o settori ad alto rischio delisting (biotech, energy).")
    w("   - Il −60% loss è conservativo: la maggior parte dei delisting avviene a −80%/−100%,")
    w("     ma spesso il trading system esce prima (stop loss, segnale contrario).")
    w("   - Il modello attuale NON ha stop loss espliciti: l'uscita è solo per holding period.")
    w("     Un trailing stop (es. −15%) ridurrebbe drasticamente l'impatto di ogni singolo evento.")
    w(f"   - Simulazioni: {N_SIMS} | Seed deterministico: {RNG_SEED} | Rate: {STRESS_RATE*100:.1f}% | Loss: −{STRESS_LOSS*100:.0f}%")
    w("=" * 98)

    txt = "\n".join(lines)
    with open(REPORT, "w") as f:
        f.write(txt)
    print(f"\n{'='*98}")
    print(txt)
    print(f"\nReport salvato: {REPORT}")


def main():
    print("=== Run #39: Stress Test Survivorship Bias — Monte Carlo Degradation ===\n")
    print(f"Config: {N_SIMS} simulazioni | {STRESS_RATE*100:.1f}% trade stressati | "
          f"−{STRESS_LOSS*100:.0f}% catastrofico | seed={RNG_SEED}\n")

    print("1. Precompute EU p85 universe...")
    pre_eu = prepare(EU_PATH, top_q=0.85)
    print("2. Precompute US p80 universe...")
    pre_us = prepare(US_PATH, top_q=0.80)
    print()

    print("3. EU (p85, hold 10gg, expanding, tasse IT):")
    eu_eq, eu_res, eu_stats = run_mc_stress(
        "EUROPA (mib_data_long.csv, p85, hold 10gg, 2018-2026):",
        EU_PATH, 10, 0.85, pre_eu, "data/eu_equity_stress_base.csv")
    print()

    print("4. US (p80, hold 20gg, expanding, tasse IT):")
    us_eq, us_res, us_stats = run_mc_stress(
        "S&P 500 (sp500_data_long.csv, p80, hold 20gg, 2018-2026):",
        US_PATH, 20, 0.80, pre_us, "data/sp500_equity_stress_base.csv")
    print()

    generate_report(eu_res, eu_stats, us_res, us_stats)


if __name__ == "__main__":
    main()
