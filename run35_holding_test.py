#!/usr/bin/env python3
"""run35_holding_test.py — Run #35: Ottimizzazione Holding Period (10 vs 20 giorni).

Confronta holding period di 10 e 20 giorni operativi su entrambi gli universi (EU + S&P 500),
mantenendo attivi: costi Fineco reali, slippage 0.02%, Regime Gate TREND_UP, Risk-Parity.

Ipotesi: raddoppiare l'holding period (~halves i trade) riduce il drag commissionale EU di
~2 pt CAGR, mentre il decadimento dell'alpha è atteso inferiore grazie al gate (position
tenute solo in regime favorevole).

Report: data/HOLDING_20D_REPORT.txt
"""
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, ".")
from portfolio_backtester import prepare, backtest, SLIP, FINECO_EU_PCT, FINECO_EU_MIN, FINECO_EU_MAX, FINECO_US_FLAT

EU_PATH  = "data/mib_data_long.csv"
US_PATH  = "data/sp500_data_long.csv"
REPORT   = "data/HOLDING_20D_REPORT.txt"
HOLDS    = [10, 20]


def run_arm(label, px_path, hold, pre, equity_out):
    print(f"  {label}...", end="", flush=True)
    eq, res = backtest(px_path=px_path, regime_mode="gate", sizing="riskparity",
                       costs=True, hold=hold, equity_out=equity_out, _pre=pre)
    print(f"  CAGR {res['CAGR_pct']:+.2f}% | MaxDD {res['MaxDD_pct']:.2f}% | "
          f"Sharpe {res['Sharpe_daily']:.2f} | Trade {res['trades']} | Costi {res['total_costs_paid']:.0f}€")
    return eq, res


def generate_report(eu10, eu20, us10, us20):
    lines = []
    w = lines.append

    w("=" * 90)
    w(" RUN #35 — OTTIMIZZAZIONE HOLDING PERIOD: 10 vs 20 GIORNI OPERATIVI")
    w(" portfolio_backtester.py — schema GATE TREND_UP + RISK-PARITY + FINECO COSTS + SLIP")
    w("=" * 90)
    w("")
    w(" IPOTESI: raddoppiare l'holding period (~dimezza i trade) riduce il drag commissionale")
    w(" EU proporzionalmente; il decadimento dell'alpha e' atteso contenuto se il gate")
    w(" mantiene le posizioni in regime TREND_UP per l'intera durata estesa.")
    w("")
    w(f" STRUTTURA COSTI FINECO (identica per entrambi i test):")
    w(f"   EU  (.MI/.PA/.AS): {FINECO_EU_PCT*100:.2f}% controvalore | min {FINECO_EU_MIN:.2f}€ | max {FINECO_EU_MAX:.2f}€ / gamba")
    w(f"   US  (altri):       {FINECO_US_FLAT:.2f}€ flat / gamba")
    w(f"   Slippage:          {SLIP*100:.2f}% su ogni prezzo eseguito")
    w(f"   Round-trip = 2 gambe (ingresso + uscita)")
    w("")

    def block(label, r10, r20):
        w(f" {label}")
        hdr = (f" {'Schema':<35} {'CAGR%':>8} {'MaxDD%':>8} {'Sharpe':>8} "
               f"{'Calmar':>8} {'Expo%':>8} {'Trade':>7} {'Costi€':>10} {'€/trade(RT)':>12}")
        w(hdr)
        w(" " + "-" * 98)

        def row(tag, r):
            cal_s = f"{r['Calmar']:>+8.2f}" if np.isfinite(r['Calmar']) else "     n/a"
            rt_cost = r['total_costs_paid'] / r['trades'] if r['trades'] > 0 else 0
            ann_trades = r['trades'] / (r['days'] / 252)
            return (f" {tag:<35} {r['CAGR_pct']:>+8.2f} {r['MaxDD_pct']:>8.2f} "
                    f"{r['Sharpe_daily']:>8.2f} {cal_s} {r['avg_exposure_pct']:>8.1f} "
                    f"{r['trades']:>7d} {r['total_costs_paid']:>10.0f} {rt_cost:>12.1f}")

        w(row("A  Hold 10gg, Fineco+slip", r10))
        w(row("B  Hold 20gg, Fineco+slip", r20))
        w("")

        # deltas
        dc = r20['CAGR_pct'] - r10['CAGR_pct']
        dm = r20['MaxDD_pct'] - r10['MaxDD_pct']
        ds = r20['Sharpe_daily'] - r10['Sharpe_daily']
        dca = (r20['Calmar'] - r10['Calmar']) if np.isfinite(r20['Calmar']) and np.isfinite(r10['Calmar']) else float('nan')
        d_trades = r20['trades'] - r10['trades']
        d_costs = r20['total_costs_paid'] - r10['total_costs_paid']

        # annual trade/cost metrics
        ann10 = r10['trades'] / (r10['days'] / 252)
        ann20 = r20['trades'] / (r20['days'] / 252)
        drag10 = r10['total_costs_paid'] / r10['capital0'] / (r10['days'] / 252) * 100
        drag20 = r20['total_costs_paid'] / r10['capital0'] / (r10['days'] / 252) * 100

        w(f"   Δ CAGR      {dc:>+.2f} pt | Δ MaxDD    {dm:>+.2f} pt | Δ Sharpe {ds:>+.2f}")
        w(f"   Δ Calmar    {dca:>+.2f}    | Δ Trade    {d_trades:>+d} ({ann10:.0f}/anno → {ann20:.0f}/anno)")
        w(f"   Drag annuo: {drag10:.2f}% (10gg) → {drag20:.2f}% (20gg) | Δ Costi {d_costs:>+.0f}€ ({d_costs/r10['total_costs_paid']*100:>+.1f}%)")

        # verdict
        alpha_ok = dc >= -1.0    # accettiamo fino a 1pt CAGR di decadimento alpha
        cost_win = d_costs < 0
        net_ok   = dc > 0 or (cost_win and dc >= -1.0)
        if cost_win and alpha_ok:
            verdict = "CONVENIENTE: risparmio commissionale supera/compensa il decadimento alpha"
        elif cost_win and not alpha_ok:
            verdict = "PARZIALE: risparmio commissioni ma alpha decade troppo (>1pt CAGR)"
        elif not cost_win:
            verdict = "NON CONVENIENTE: 20gg non riduce i trade a sufficienza"
        else:
            verdict = "NEUTRO"
        w(f"   Verdetto: {verdict}")
        w("")

    block("UNIVERSO EU (mib_data_long.csv, 2018-2026):", eu10, eu20)
    block("UNIVERSO S&P 500 (sp500_data_long.csv, 2018-2026):", us10, us20)

    w(" CONCLUSIONE CROSS-MARKET:")
    eu_dc = eu20['CAGR_pct'] - eu10['CAGR_pct']
    us_dc = us20['CAGR_pct'] - us10['CAGR_pct']
    eu_dd = eu20['total_costs_paid'] - eu10['total_costs_paid']
    us_dd = us20['total_costs_paid'] - us10['total_costs_paid']
    w(f"   EU: Δ CAGR {eu_dc:>+.2f} pt | Δ Costi {eu_dd:>+.0f}€ | "
      f"Sharpe 20gg {eu20['Sharpe_daily']:.2f} vs 10gg {eu10['Sharpe_daily']:.2f}")
    w(f"   US: Δ CAGR {us_dc:>+.2f} pt | Δ Costi {us_dd:>+.0f}€ | "
      f"Sharpe 20gg {us20['Sharpe_daily']:.2f} vs 10gg {us10['Sharpe_daily']:.2f}")
    w("")

    # best config per market
    eu_best = "20gg" if (eu_dc + (eu_dd / eu10['capital0'] / (eu10['days'] / 252) * 100)) > 0 else "10gg"
    us_best = "20gg" if (us_dc + (us_dd / us10['capital0'] / (us10['days'] / 252) * 100)) > 0 else "10gg"
    w(f"   Config raccomandata EU: {eu_best}")
    w(f"   Config raccomandata US: {us_best}")
    w("")
    w(" NOTE METODOLOGICHE:")
    w("   - Il gate TREND_UP puo' interrompere una posizione 20gg se il regime gira durante l'holding;")
    w("     il motore NON chiude anticipatamente per cambio regime (solo per holding completato).")
    w("     -> In mercati laterali/ribassisti la posizione 20gg subisce piu' drawdown intraciclo.")
    w("   - Slippage 0.02% e' stima conservativa; con 20gg piu' tempo per la liquidazione programmata.")
    w("   - Confronto equo: stessa finestra 2018-2026, stessi parametri di gate e risk-parity.")
    w("   - Per ridurre ulteriormente il turnover: considerare filtro score minimo piu' alto (p85 vs p80)")
    w("     oppure momentum confirmation richiedendo N barre consecutive sopra la soglia.")
    w("=" * 90)

    txt = "\n".join(lines)
    with open(REPORT, "w") as f:
        f.write(txt)
    print(f"\n{'='*90}")
    print(txt)
    print(f"\nReport salvato: {REPORT}")


def main():
    print("=== Run #35: Holding Period 10 vs 20 giorni (Fineco+Slip, Gate+RP) ===\n")

    print("1. Precompute EU universe...")
    pre_eu = prepare(EU_PATH)
    print("2. Precompute US universe...")
    pre_us = prepare(US_PATH)
    print()

    print("3. Backtest EU:")
    _, eu10 = run_arm("EU  Hold 10gg (baseline R34)", EU_PATH, 10, pre_eu, "data/eu_equity_hold10.csv")
    _, eu20 = run_arm("EU  Hold 20gg",                EU_PATH, 20, pre_eu, "data/eu_equity_hold20.csv")
    print()

    print("4. Backtest US:")
    _, us10 = run_arm("US  Hold 10gg (baseline R34)", US_PATH, 10, pre_us, "data/sp500_equity_hold10.csv")
    _, us20 = run_arm("US  Hold 20gg",                US_PATH, 20, pre_us, "data/sp500_equity_hold20.csv")
    print()

    generate_report(eu10, eu20, us10, us20)


if __name__ == "__main__":
    main()
