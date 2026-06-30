#!/usr/bin/env python3
"""run36_p85_test.py — Run #36: Ottimizzazione selettività EU (p80 vs p85) + Holding Ibrido.

Configurazione testata:
  EU: soglia score p80 vs p85 | holding 10gg | Fineco+slip | GATE TREND_UP | Risk-Parity
  US: soglia score p80 (invariata) | holding 20gg (best arm R35) | Fineco+slip | GATE | RP

Ipotesi: p85 riduce il turnover EU del ~20-25% rispetto a p80 (seleziona solo il top 15%
dei segnali invece del top 20%), abbassando il drag commissionale senza deteriorare il
profilo di rischio — il 20° percentile aggiuntivo (p80→p85) atteso avere lower IC.

Report: data/EUROPE_P85_REPORT.txt
"""
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, ".")
from portfolio_backtester import (prepare, backtest,
                                  SLIP, FINECO_EU_PCT, FINECO_EU_MIN,
                                  FINECO_EU_MAX, FINECO_US_FLAT)

EU_PATH = "data/mib_data_long.csv"
US_PATH = "data/sp500_data_long.csv"
REPORT  = "data/EUROPE_P85_REPORT.txt"


def run_arm(label, px_path, hold, pre, equity_out):
    print(f"  {label}...", end="", flush=True)
    eq, res = backtest(px_path=px_path, regime_mode="gate", sizing="riskparity",
                       costs=True, hold=hold, equity_out=equity_out, _pre=pre)
    print(f"  CAGR {res['CAGR_pct']:+.2f}% | MaxDD {res['MaxDD_pct']:.2f}% | "
          f"Sharpe {res['Sharpe_daily']:.2f} | Calmar {res['Calmar']:.2f} | "
          f"Trade {res['trades']} | Costi {res['total_costs_paid']:.0f}€")
    return eq, res


def generate_report(eu_p80, eu_p85, us_p80_20d):
    lines = []
    w = lines.append

    w("=" * 92)
    w(" RUN #36 — OTTIMIZZAZIONE SELETTIVITÀ EU: p80 vs p85 + HOLDING IBRIDO (EU 10gg / US 20gg)")
    w(" portfolio_backtester.py — GATE TREND_UP + RISK-PARITY + FINECO COSTS + SLIPPAGE 0.02%")
    w("=" * 92)
    w("")
    w(" CONFIGURAZIONE:")
    w("   EU: soglia score p80 (baseline R34) vs p85 (nuovo) | holding 10gg | Fineco+slip")
    w("   US: soglia score p80 | holding 20gg (best arm R35) | Fineco+slip")
    w(f"   EU costi: {FINECO_EU_PCT*100:.2f}% controvalore | min {FINECO_EU_MIN:.2f}€ | max {FINECO_EU_MAX:.2f}€ / gamba")
    w(f"   US costi: {FINECO_US_FLAT:.2f}€ flat / gamba | Slippage: {SLIP*100:.2f}% su ogni eseguito")
    w("")
    w(" IPOTESI: innalzare la soglia da p80 a p85 riduce il numero di trade EU del ~20-25%,")
    w("   abbassando il drag commissionale proporzionalmente. Il segnale nel range p80-p85")
    w("   ha atteso IC inferiore, quindi l'effetto netto sul CAGR e' ambiguo: da testare.")
    w("")

    # --- EU COMPARISON BLOCK ---
    w(" " + "=" * 88)
    w(" CONFRONTO EUROPA: Configurazione Precedente (p80) vs Nuova Configurazione (p85)")
    w(" " + "=" * 88)
    hdr = (f" {'Schema':<40} {'CAGR%':>8} {'MaxDD%':>8} {'Sharpe':>8} "
           f"{'Calmar':>8} {'Expo%':>7} {'Trade':>7} {'Costi€':>9} {'€/RT':>7}")
    w(hdr)
    w(" " + "-" * 98)

    def row(tag, r):
        cal_s = f"{r['Calmar']:>+8.2f}" if np.isfinite(r['Calmar']) else "     n/a"
        rt_cost = r['total_costs_paid'] / r['trades'] if r['trades'] > 0 else 0.0
        return (f" {tag:<40} {r['CAGR_pct']:>+8.2f} {r['MaxDD_pct']:>8.2f} "
                f"{r['Sharpe_daily']:>8.2f} {cal_s} {r['avg_exposure_pct']:>7.1f} "
                f"{r['trades']:>7d} {r['total_costs_paid']:>9.0f} {rt_cost:>7.1f}")

    w(row("A  EU p80, Hold 10gg (baseline R34)", eu_p80))
    w(row("B  EU p85, Hold 10gg (nuovo)", eu_p85))
    w("")

    # delta EU
    dc   = eu_p85['CAGR_pct']  - eu_p80['CAGR_pct']
    dm   = eu_p85['MaxDD_pct'] - eu_p80['MaxDD_pct']
    ds   = eu_p85['Sharpe_daily'] - eu_p80['Sharpe_daily']
    dca  = (eu_p85['Calmar'] - eu_p80['Calmar']) if (np.isfinite(eu_p85['Calmar']) and
            np.isfinite(eu_p80['Calmar'])) else float('nan')
    d_tr = eu_p85['trades'] - eu_p80['trades']
    d_co = eu_p85['total_costs_paid'] - eu_p80['total_costs_paid']
    pct_tr = d_tr / eu_p80['trades'] * 100 if eu_p80['trades'] > 0 else 0.0
    pct_co = d_co / eu_p80['total_costs_paid'] * 100 if eu_p80['total_costs_paid'] > 0 else 0.0

    ann80 = eu_p80['trades'] / (eu_p80['days'] / 252)
    ann85 = eu_p85['trades'] / (eu_p85['days'] / 252)
    drag80 = eu_p80['total_costs_paid'] / eu_p80['capital0'] / (eu_p80['days'] / 252) * 100
    drag85 = eu_p85['total_costs_paid'] / eu_p85['capital0'] / (eu_p85['days'] / 252) * 100

    w(f"   Δ CAGR      {dc:>+.2f} pt | Δ MaxDD {dm:>+.2f} pt | Δ Sharpe {ds:>+.2f} | Δ Calmar {dca:>+.2f}")
    w(f"   Δ Trade     {d_tr:>+d} ({ann80:.0f}/anno → {ann85:.0f}/anno) = {pct_tr:>+.1f}%")
    w(f"   Δ Costi     {d_co:>+.0f}€ ({pct_co:>+.1f}%) | Drag annuo: {drag80:.2f}% → {drag85:.2f}%")
    w(f"   Score thr   p80={eu_p80['score_thr']:.4f} → p85={eu_p85['score_thr']:.4f}")
    w("")

    # verdict EU
    cost_win  = d_co < 0
    alpha_ok  = dc >= -0.5   # accettiamo max 0.5pt CAGR di decadimento
    mdd_ok    = dm >= -2.0   # non vogliamo peggiorare il MaxDD di più di 2pt
    sharpe_ok = ds >= -0.05

    if cost_win and alpha_ok and mdd_ok:
        verdict = "OTTIMALE: risparmio commissionale senza deterioramento significativo dell'alpha"
    elif cost_win and alpha_ok and not mdd_ok:
        verdict = "ACCETTABILE: risparmio costi ma MaxDD peggiora — monitorare"
    elif cost_win and not alpha_ok:
        verdict = "PARZIALE: risparmio costi ma alpha decade oltre la soglia (-0.5pt)"
    elif not cost_win:
        verdict = "NON CONVENIENTE: p85 non riduce i trade/costi in modo significativo"
    else:
        verdict = "NEUTRO"
    w(f"   Verdetto EU (p85 vs p80): {verdict}")
    w("")

    # --- US REFERENCE BLOCK ---
    w(" " + "=" * 88)
    w(" UNIVERSO USA: Configurazione Ibrida Validata (p80 / Hold 20gg)")
    w(" " + "=" * 88)
    w(row("C  US p80, Hold 20gg (best arm R35)", us_p80_20d))
    ann_us = us_p80_20d['trades'] / (us_p80_20d['days'] / 252)
    drag_us = us_p80_20d['total_costs_paid'] / us_p80_20d['capital0'] / (us_p80_20d['days'] / 252) * 100
    rt_us = us_p80_20d['total_costs_paid'] / us_p80_20d['trades'] if us_p80_20d['trades'] > 0 else 0
    w("")
    w(f"   Trade/anno: {ann_us:.0f} | Drag annuo: {drag_us:.2f}% | €/RT: {rt_us:.1f}€")
    w(f"   Score thr p80={us_p80_20d['score_thr']:.4f} | Calmar {us_p80_20d['Calmar']:.2f}")
    w("")

    # --- PORTFOLIO IBRIDO SUMMARY ---
    w(" " + "=" * 88)
    w(" SCHEMA IBRIDO RACCOMANDATO (EU p85 10gg + US p80 20gg):")
    w(" " + "=" * 88)
    eu_best = eu_p85 if (cost_win and alpha_ok) else eu_p80
    eu_tag  = "p85" if (cost_win and alpha_ok) else "p80 (invariato)"
    w(f"   EU: {eu_tag} | Hold 10gg | CAGR {eu_best['CAGR_pct']:+.2f}% | Sharpe {eu_best['Sharpe_daily']:.2f} | "
      f"Calmar {eu_best['Calmar']:.2f} | Costi {eu_best['total_costs_paid']:.0f}€/8anni")
    w(f"   US: p80 | Hold 20gg | CAGR {us_p80_20d['CAGR_pct']:+.2f}% | Sharpe {us_p80_20d['Sharpe_daily']:.2f} | "
      f"Calmar {us_p80_20d['Calmar']:.2f} | Costi {us_p80_20d['total_costs_paid']:.0f}€/8anni")
    w("")
    w(" NOTE:")
    w("   - La soglia p85 e' calcolata sull'intera distribuzione storica (lieve in-sample bias).")
    w("     Una soglia espandente (expanding-window p85) darebbe un test OOS piu' pulito.")
    w("   - Il pool di ticker EU e' fisso (mib_data_long.csv); su un universo piu' ampio")
    w("     p85 avrebbe piu' segnali disponibili e un turnover piu' elevato.")
    w("   - Il confronto p80 vs p85 usa _pre separato per ciascuna soglia (thr diverso):")
    w("     i due backtest sono identici tranne per la soglia di ingresso.")
    w("=" * 92)

    txt = "\n".join(lines)
    with open(REPORT, "w") as f:
        f.write(txt)
    print(f"\n{'='*92}")
    print(txt)
    print(f"\nReport salvato: {REPORT}")


def main():
    print("=== Run #36: EU p80 vs p85 + Holding Ibrido (EU 10gg / US 20gg) ===\n")

    print("1. Precompute EU p80 universe...")
    pre_eu_p80 = prepare(EU_PATH, top_q=0.80)
    print("2. Precompute EU p85 universe...")
    pre_eu_p85 = prepare(EU_PATH, top_q=0.85)
    print("3. Precompute US p80 universe...")
    pre_us_p80 = prepare(US_PATH, top_q=0.80)
    print()

    print("4. Backtest EU:")
    _, eu_p80 = run_arm("EU  p80 hold 10gg (baseline R34)", EU_PATH, 10,
                        pre_eu_p80, "data/eu_equity_p80_h10.csv")
    _, eu_p85 = run_arm("EU  p85 hold 10gg (nuovo)",        EU_PATH, 10,
                        pre_eu_p85, "data/eu_equity_p85_h10.csv")
    print()

    print("5. Backtest US (best arm R35: p80 hold 20gg):")
    _, us_20d = run_arm("US  p80 hold 20gg (best arm R35)", US_PATH, 20,
                        pre_us_p80, "data/sp500_equity_p80_h20.csv")
    print()

    generate_report(eu_p80, eu_p85, us_20d)


if __name__ == "__main__":
    main()
