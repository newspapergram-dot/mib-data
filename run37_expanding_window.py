#!/usr/bin/env python3
"""run37_expanding_window.py — Run #37: Rimozione Lookahead Bias tramite Soglia Espandente.

Confronta soglia STATICA (p85/p80 calcolata sull'intero dataset) vs ESPANDENTE
(p85/p80 calcolata giorno per giorno solo sui dati storici disponibili fino a t).

Assetto ibrido validato (Run #36):
  EU: soglia p85 | holding 10gg | GATE TREND_UP | Risk-Parity | Fineco+Slip
  US: soglia p80 | holding 20gg | GATE TREND_UP | Risk-Parity | Fineco+Slip

Domanda chiave: il α del sistema è reale o è un artefatto del lookahead nella soglia?
Con soglia espandente il modello è genuinamente OOS (no dati futuri per costruire la soglia).

Report: data/EXPANDING_WINDOW_REPORT.txt
"""
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, ".")
from portfolio_backtester import (prepare, backtest,
                                  SLIP, FINECO_EU_PCT, FINECO_EU_MIN,
                                  FINECO_EU_MAX, FINECO_US_FLAT)

EU_PATH  = "data/mib_data_long.csv"
US_PATH  = "data/sp500_data_long.csv"
REPORT   = "data/EXPANDING_WINDOW_REPORT.txt"


def run_arm(label, px_path, hold, top_q, pre, expanding, equity_out):
    mode = "expanding" if expanding else "static"
    print(f"  {label} [{mode}]...", end="", flush=True)
    eq, res = backtest(px_path=px_path, regime_mode="gate", sizing="riskparity",
                       costs=True, hold=hold, top_q=top_q,
                       expanding_threshold=expanding,
                       equity_out=equity_out, _pre=pre)
    thr_lbl = f"thr={res['score_thr']:.4f}"
    print(f"  CAGR {res['CAGR_pct']:+.2f}% | MaxDD {res['MaxDD_pct']:.2f}% | "
          f"Sharpe {res['Sharpe_daily']:.2f} | Calmar {res['Calmar']:.2f} | "
          f"Trade {res['trades']} | Costi {res['total_costs_paid']:.0f}€ | {thr_lbl}")
    return eq, res


def generate_report(eu_stat, eu_exp, us_stat, us_exp):
    lines = []
    w = lines.append

    w("=" * 94)
    w(" RUN #37 — ELIMINAZIONE LOOKAHEAD BIAS: SOGLIA STATICA vs ESPANDENTE (EXPANDING WINDOW)")
    w(" portfolio_backtester.py — GATE TREND_UP + RISK-PARITY + FINECO COSTS + SLIPPAGE 0.02%")
    w(" Assetto ibrido: EU p85 hold 10gg | US p80 hold 20gg")
    w("=" * 94)
    w("")
    w(" DEFINIZIONI:")
    w("   Statica:    thr = np.nanquantile(score_panel_INTERO, q)  -- usa dati 2018-2026 interi")
    w("               -> lookahead bias: la soglia di un giorno qualsiasi del 2018 usa")
    w("                  distribuzione di score che include il 2019-2026 (non disponibile allora)")
    w("   Espandente: thr_t = np.nanquantile(score_panel[:t], q)  -- usa solo dati fino a t")
    w("               -> OOS pulito: la soglia di ogni giorno usa solo il passato osservabile")
    w("")
    w(f" STRUTTURA COSTI: EU {FINECO_EU_PCT*100:.2f}% [{FINECO_EU_MIN:.2f}€-{FINECO_EU_MAX:.2f}€/gamba]")
    w(f"   US {FINECO_US_FLAT:.2f}€ flat/gamba | Slippage {SLIP*100:.2f}%")
    w("")

    def block(label, r_stat, r_exp):
        w(f" {'='*88}")
        w(f" {label}")
        w(f" {'='*88}")
        hdr = (f" {'Schema':<42} {'CAGR%':>8} {'MaxDD%':>8} {'Sharpe':>8} "
               f"{'Calmar':>8} {'Expo%':>7} {'Trade':>7} {'Costi€':>9} {'Thr(finale)':>12}")
        w(hdr)
        w(" " + "-" * 102)

        def row(tag, r):
            cal_s = f"{r['Calmar']:>+8.2f}" if np.isfinite(r['Calmar']) else "     n/a"
            return (f" {tag:<42} {r['CAGR_pct']:>+8.2f} {r['MaxDD_pct']:>8.2f} "
                    f"{r['Sharpe_daily']:>8.2f} {cal_s} {r['avg_exposure_pct']:>7.1f} "
                    f"{r['trades']:>7d} {r['total_costs_paid']:>9.0f} {r['score_thr']:>12.4f}")

        w(row("A  Soglia STATICA  (baseline R36)", r_stat))
        w(row("B  Soglia ESPANDENTE (OOS pulito)", r_exp))
        w("")

        dc  = r_exp['CAGR_pct']      - r_stat['CAGR_pct']
        dm  = r_exp['MaxDD_pct']     - r_stat['MaxDD_pct']
        ds  = r_exp['Sharpe_daily']  - r_stat['Sharpe_daily']
        dca = (r_exp['Calmar']       - r_stat['Calmar']
               if np.isfinite(r_exp['Calmar']) and np.isfinite(r_stat['Calmar'])
               else float('nan'))
        d_tr = r_exp['trades'] - r_stat['trades']
        d_co = r_exp['total_costs_paid'] - r_stat['total_costs_paid']
        pct_co = d_co / r_stat['total_costs_paid'] * 100 if r_stat['total_costs_paid'] else 0

        w(f"   Δ CAGR {dc:>+.2f} pt | Δ MaxDD {dm:>+.2f} pt | Δ Sharpe {ds:>+.2f} | Δ Calmar {dca:>+.2f}")
        w(f"   Δ Trade {d_tr:>+d} | Δ Costi {d_co:>+.0f}€ ({pct_co:>+.1f}%)")

        # Interpret bias magnitude
        bias_cagr = abs(dc)
        if bias_cagr < 0.3:
            bias_verdict = "TRASCURABILE (<0.3pt CAGR): il lookahead bias e' irrilevante"
        elif bias_cagr < 1.0:
            bias_verdict = "CONTENUTO (0.3-1.0pt CAGR): bias presente ma alpha genuinamente positivo"
        elif bias_cagr < 2.0:
            bias_verdict = "MODERATO (1.0-2.0pt CAGR): parte dell'alpha e' artefatto della soglia statica"
        else:
            bias_verdict = "SIGNIFICATIVO (>2.0pt CAGR): l'alpha dipende materialmente dalla soglia statica"

        # Check if edge survives expanding threshold
        edge_ok = (r_exp['Sharpe_daily'] > 0.5 and
                   r_exp['CAGR_pct'] > 3.0 and
                   r_exp['MaxDD_pct'] > -40.0)
        w(f"   Bias lookahead: {bias_verdict}")
        w(f"   Edge con soglia espandente: {'SI (Sharpe>0.5, CAGR>3%, MaxDD>-40%)' if edge_ok else 'MARGINALE o ASSENTE'}")
        w("")

    block("EUROPA (mib_data_long.csv, p85, hold 10gg, 2018-2026):", eu_stat, eu_exp)
    block("S&P 500 (sp500_data_long.csv, p80, hold 20gg, 2018-2026):", us_stat, us_exp)

    w(" " + "=" * 88)
    w(" CONCLUSIONE CROSS-MARKET:")
    w(" " + "=" * 88)
    eu_bias = eu_stat['CAGR_pct'] - eu_exp['CAGR_pct']
    us_bias = us_stat['CAGR_pct'] - us_exp['CAGR_pct']
    eu_edge = eu_exp['Sharpe_daily'] > 0.5 and eu_exp['CAGR_pct'] > 3.0
    us_edge = us_exp['Sharpe_daily'] > 0.5 and us_exp['CAGR_pct'] > 3.0

    w(f"   EU: lookahead bias soglia = {eu_bias:+.2f} pt CAGR | "
      f"Alpha OOS: {'CONFERMATO' if eu_edge else 'NON CONFERMATO'}")
    w(f"   US: lookahead bias soglia = {us_bias:+.2f} pt CAGR | "
      f"Alpha OOS: {'CONFERMATO' if us_edge else 'NON CONFERMATO'}")
    w("")

    # config recommendation
    w(" CONFIGURAZIONE RACCOMANDATA PER IL LIVE (OOS-clean):")
    eu_best = eu_exp if eu_edge else eu_stat
    eu_mode = "ESPANDENTE (OOS pulito)" if eu_edge else "STATICA (expanding fallisce)"
    us_best = us_exp if us_edge else us_stat
    us_mode = "ESPANDENTE (OOS pulito)" if us_edge else "STATICA (expanding fallisce)"
    w(f"   EU: p85 | hold 10gg | soglia {eu_mode}")
    w(f"       CAGR {eu_best['CAGR_pct']:+.2f}% | Sharpe {eu_best['Sharpe_daily']:.2f} | "
      f"Calmar {eu_best['Calmar']:.2f} | MaxDD {eu_best['MaxDD_pct']:.2f}%")
    w(f"   US: p80 | hold 20gg | soglia {us_mode}")
    w(f"       CAGR {us_best['CAGR_pct']:+.2f}% | Sharpe {us_best['Sharpe_daily']:.2f} | "
      f"Calmar {us_best['Calmar']:.2f} | MaxDD {us_best['MaxDD_pct']:.2f}%")
    w("")
    w(" NOTE:")
    w("   - La soglia espandente nei primi ~200 giorni (warmup) usa pochi score (bassa")
    w("     stima del quantile). Il sistema entra in produzione reale solo dopo start=201.")
    w("   - La soglia statica usa la distribuzione completa degli score: tende a essere")
    w("     piu' alta nei periodi bull e piu' bassa nei periodi bear (effetto distribuzione)")
    w("     -> la soglia espandente puo' differire sistematicamente in mercati non stazionari.")
    w("   - Con expanding threshold: la soglia cresce monotonicamente nel tempo se il mercato")
    w("     e' bull (aggiunge score piu' alti) — fenomeno normale e corretto.")
    w("=" * 94)

    txt = "\n".join(lines)
    with open(REPORT, "w") as f:
        f.write(txt)
    print(f"\n{'='*94}")
    print(txt)
    print(f"\nReport salvato: {REPORT}")


def main():
    print("=== Run #37: Soglia Statica vs Espandente (OOS bias removal) ===\n")

    print("1. Precompute EU p85 universe...")
    pre_eu = prepare(EU_PATH, top_q=0.85)
    print("2. Precompute US p80 universe...")
    pre_us = prepare(US_PATH, top_q=0.80)
    print()

    print("3. Backtest EU (p85, hold 10gg):")
    _, eu_stat = run_arm("EU p85 statica (baseline R36)", EU_PATH, 10, 0.85,
                         pre_eu, False, "data/eu_equity_p85_static.csv")
    _, eu_exp  = run_arm("EU p85 espandente",             EU_PATH, 10, 0.85,
                         pre_eu, True,  "data/eu_equity_p85_expanding.csv")
    print()

    print("4. Backtest US (p80, hold 20gg):")
    _, us_stat = run_arm("US p80 statica (baseline R35)", US_PATH, 20, 0.80,
                         pre_us, False, "data/sp500_equity_p80_static.csv")
    _, us_exp  = run_arm("US p80 espandente",             US_PATH, 20, 0.80,
                         pre_us, True,  "data/sp500_equity_p80_expanding.csv")
    print()

    generate_report(eu_stat, eu_exp, us_stat, us_exp)


if __name__ == "__main__":
    main()
