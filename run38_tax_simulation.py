#!/usr/bin/env python3
"""run38_tax_simulation.py — Run #38: Simulazione Fiscale (Regime Amministrato IT).

Aggiunge la tassazione italiana reale al loop di backtest:
  1) CGT 26%: applicata su ogni plusvalenza al momento della chiusura del trade.
  2) Zainetto fiscale: le minusvalenze azzerano le plusvalenze future (FIFO, scadenza 4 anni).
  3) Imposta di Bollo 0.20%/anno: applicata il primo giorno dell'anno sul valore di
     chiusura dell'ultimo giorno dell'anno precedente (cash + valore posizioni).

Assetto OOS definitivo (Run #37):
  EU: p85 | hold 10gg | soglia espandente | GATE+RP | Fineco+Slip
  US: p80 | hold 20gg | soglia espandente | GATE+RP | Fineco+Slip

Confronto: lordo (costi+slip, senza tasse) vs netto (costi+slip+tasse).
Report: data/TAX_SIMULATION_REPORT.txt
"""
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, ".")
from portfolio_backtester import (prepare, backtest,
                                  SLIP, FINECO_EU_PCT, FINECO_EU_MIN, FINECO_EU_MAX,
                                  FINECO_US_FLAT, TAX_CAPITAL_GAIN, TAX_BOLLO, TAX_CREDIT_YEARS)

EU_PATH = "data/mib_data_long.csv"
US_PATH = "data/sp500_data_long.csv"
REPORT  = "data/TAX_SIMULATION_REPORT.txt"


def run_arm(label, px_path, hold, top_q, pre, taxes, equity_out):
    tax_lbl = "tasse" if taxes else "lordo"
    print(f"  {label} [{tax_lbl}]...", end="", flush=True)
    eq, res = backtest(px_path=px_path, regime_mode="gate", sizing="riskparity",
                       costs=True, hold=hold, top_q=top_q,
                       expanding_threshold=True, taxes=taxes,
                       equity_out=equity_out, _pre=pre)
    cgt_lbl = f" | CGT {res['total_taxes_paid']:.0f}€ | Zainetto {res['zainetto_remaining']:.0f}€" if taxes else ""
    print(f"  CAGR {res['CAGR_pct']:+.2f}% | MaxDD {res['MaxDD_pct']:.2f}% | "
          f"Sharpe {res['Sharpe_daily']:.2f} | Calmar {res['Calmar']:.2f}{cgt_lbl}")
    return eq, res


def generate_report(eu_g, eu_n, us_g, us_n):
    lines = []
    w = lines.append

    w("=" * 94)
    w(" RUN #38 — SIMULAZIONE FISCALE: REGIME AMMINISTRATO ITALIANO")
    w(" portfolio_backtester.py — GATE TREND_UP + RISK-PARITY + FINECO COSTS + SLIP + TASSE")
    w(" Assetto OOS definitivo (Run #37): EU p85 hold 10gg / US p80 hold 20gg | soglia espandente")
    w("=" * 94)
    w("")
    w(" REGIME FISCALE IMPLEMENTATO (regime amministrato):")
    w(f"   CGT {TAX_CAPITAL_GAIN*100:.0f}%: imposta sulle plusvalenze, applicata a ogni trade in profitto.")
    w(f"   Zainetto fiscale: le minusvalenze creano crediti (scadenza {TAX_CREDIT_YEARS} anni) che")
    w(f"     compensano le plusvalenze future — FIFO, dal credito piu' vecchio al piu' recente.")
    w(f"   Bollo {TAX_BOLLO*100:.2f}%/anno: sul valore totale portafoglio (cash + posizioni)")
    w(f"     applicato il primo giorno lavorativo dell'anno sull'equity di fine anno precedente.")
    w("")
    w(" STRUTTURA COSTI FINECO (invariata):")
    w(f"   EU: {FINECO_EU_PCT*100:.2f}% [{FINECO_EU_MIN:.2f}€-{FINECO_EU_MAX:.2f}€/gamba] | "
      f"US: {FINECO_US_FLAT:.2f}€ flat/gamba | Slip {SLIP*100:.2f}%")
    w("")

    def block(label, r_g, r_n, years=8):
        w(f" {'='*90}")
        w(f" {label}")
        w(f" {'='*90}")
        hdr = (f" {'Schema':<42} {'CAGR%':>8} {'MaxDD%':>8} {'Sharpe':>8} "
               f"{'Calmar':>8} {'Expo%':>7} {'Costi€':>9} {'Tasse€':>9} {'Netto€/a':>10}")
        w(hdr)
        w(" " + "-" * 106)

        def row(tag, r):
            cal_s = f"{r['Calmar']:>+8.2f}" if np.isfinite(r['Calmar']) else "     n/a"
            ann_tax = r['total_taxes_paid'] / years if r['taxes'] else 0.0
            return (f" {tag:<42} {r['CAGR_pct']:>+8.2f} {r['MaxDD_pct']:>8.2f} "
                    f"{r['Sharpe_daily']:>8.2f} {cal_s} {r['avg_exposure_pct']:>7.1f} "
                    f"{r['total_costs_paid']:>9.0f} {r['total_taxes_paid']:>9.0f} "
                    f"{ann_tax:>10.0f}")

        w(row("A  LORDO  (Fineco+Slip, no tasse)", r_g))
        w(row("B  NETTO  (Fineco+Slip + tasse IT)", r_n))
        w("")

        # deltas
        dc  = r_n['CAGR_pct']     - r_g['CAGR_pct']
        dm  = r_n['MaxDD_pct']    - r_g['MaxDD_pct']
        ds  = r_n['Sharpe_daily'] - r_g['Sharpe_daily']
        dca = (r_n['Calmar'] - r_g['Calmar']) if (np.isfinite(r_n['Calmar']) and
               np.isfinite(r_g['Calmar'])) else float('nan')

        cgt   = r_n['total_taxes_paid']
        bollo_est = r_n['capital0'] * TAX_BOLLO * years * r_n['avg_exposure_pct'] / 100 * 0.5 + \
                    r_n['capital0'] * TAX_BOLLO * years * (1 - r_n['avg_exposure_pct'] / 100)
        drag_pct  = cgt / r_n['capital0'] / years * 100
        eff_tax   = cgt / (r_g['equity_final'] - r_g['capital0']) * 100 if r_g['equity_final'] > r_g['capital0'] else float('nan')

        w(f"   Δ CAGR {dc:>+.2f} pt | Δ MaxDD {dm:>+.2f} pt | Δ Sharpe {ds:>+.2f} | Δ Calmar {dca:>+.2f}")
        w(f"   Tasse totali pagate: {cgt:,.0f}€ | Drag annuo: {drag_pct:.2f}% | "
          f"Aliquota effettiva sui guadagni lordi: {eff_tax:.1f}%")
        w(f"   Zainetto residuo a fine periodo: {r_n['zainetto_remaining']:,.0f}€ "
          f"(crediti non utilizzati — minus non compensate)")
        w("")

        # anno per anno (stima semplificata) — tax per year
        edge_net = r_n['Sharpe_daily'] > 0.5 and r_n['CAGR_pct'] > 2.0
        w(f"   Edge dopo tasse: {'SI (Sharpe>{:.1f}, CAGR>{:.0f}%)'.format(r_n['Sharpe_daily'], r_n['CAGR_pct']) if edge_net else 'MARGINALE o ASSENTE'}")
        w("")

    block("EUROPA (mib_data_long.csv, p85, hold 10gg, 2018-2026):", eu_g, eu_n)
    block("S&P 500 (sp500_data_long.csv, p80, hold 20gg, 2018-2026):", us_g, us_n)

    w(" " + "=" * 90)
    w(" RIEPILOGO CROSS-MARKET: LORDO vs NETTO")
    w(" " + "=" * 90)
    hdr2 = (f" {'Universo':<10} {'Lordo CAGR':>12} {'Netto CAGR':>12} {'Δ CAGR':>8} "
            f"{'Tasse€':>9} {'Bollo est.':>11} {'Calmar netto':>13}")
    w(hdr2)
    w(" " + "-" * 80)

    def sum_row(label, r_g, r_n):
        dc = r_n['CAGR_pct'] - r_g['CAGR_pct']
        return (f" {label:<10} {r_g['CAGR_pct']:>+12.2f}% {r_n['CAGR_pct']:>+11.2f}% "
                f"{dc:>+8.2f}pt {r_n['total_taxes_paid']:>9.0f} {'(incluso)':>11} "
                f"{r_n['Calmar']:>13.2f}")

    w(sum_row("EU", eu_g, eu_n))
    w(sum_row("US", us_g, us_n))
    w("")

    # Final config recommendation
    w(" CONFIGURAZIONE DEFINITIVA (OOS pulito + costi reali + tasse IT):")
    eu_cagr_n = eu_n['CAGR_pct']
    us_cagr_n = us_n['CAGR_pct']
    eu_cal_n  = eu_n['Calmar']
    us_cal_n  = us_n['Calmar']
    w(f"   EU: p85 | hold 10gg | expanding | Fineco+Slip+Tasse | CAGR NETTO {eu_cagr_n:+.2f}% | "
      f"Calmar {eu_cal_n:.2f}")
    w(f"   US: p80 | hold 20gg | expanding | Fineco+Slip+Tasse | CAGR NETTO {us_cagr_n:+.2f}% | "
      f"Calmar {us_cal_n:.2f}")
    w("")
    w(" NOTE E LIMITI:")
    w("   - Lo zainetto considera la scadenza di 4 anni per ogni credito da minusvalenza.")
    w("     In pratica le perdite 2018-2019 (es. Covid 2020) vengono usate nel 2020-2022.")
    w("   - Il bollo 0.20%/anno e' applicato sull'intera equity (cash + posizioni) a fine anno.")
    w("     Nella realta', alcuni broker applicano il bollo solo sui titoli (non sulla cassa).")
    w("   - L'aliquota effettiva <26% e' normale: lo zainetto riduce la base imponibile.")
    w("   - La simulazione NON include: plusvalenze ETF (aliquota diversa), dividendi 26%,")
    w("     tobin tax (0.1% su azioni IT >500M cap), costi di consulenza.")
    w("   - Fonte di ottimismo residua: survivorship bias nel dataset (titoli delisted esclusi).")
    w("=" * 94)

    txt = "\n".join(lines)
    with open(REPORT, "w") as f:
        f.write(txt)
    print(f"\n{'='*94}")
    print(txt)
    print(f"\nReport salvato: {REPORT}")


def main():
    print("=== Run #38: Simulazione Fiscale IT (CGT 26% + Zainetto + Bollo 0.20%) ===\n")

    print("1. Precompute EU p85 universe...")
    pre_eu = prepare(EU_PATH, top_q=0.85)
    print("2. Precompute US p80 universe...")
    pre_us = prepare(US_PATH, top_q=0.80)
    print()

    print("3. Backtest EU (p85, hold 10gg, expanding):")
    _, eu_g = run_arm("EU lordo (baseline R37)",  EU_PATH, 10, 0.85, pre_eu, False,
                      "data/eu_equity_gross.csv")
    _, eu_n = run_arm("EU netto (+ tasse IT)",    EU_PATH, 10, 0.85, pre_eu, True,
                      "data/eu_equity_netto.csv")
    print()

    print("4. Backtest US (p80, hold 20gg, expanding):")
    _, us_g = run_arm("US lordo (baseline R37)",  US_PATH, 20, 0.80, pre_us, False,
                      "data/sp500_equity_gross.csv")
    _, us_n = run_arm("US netto (+ tasse IT)",    US_PATH, 20, 0.80, pre_us, True,
                      "data/sp500_equity_netto.csv")
    print()

    generate_report(eu_g, eu_n, us_g, us_n)


if __name__ == "__main__":
    main()
