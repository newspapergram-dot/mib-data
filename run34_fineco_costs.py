#!/usr/bin/env python3
"""run34_fineco_costs.py — Run #34: Integrazione Commissioni Reali Fineco + Slippage.

Struttura costi:
  EU (.MI/.PA/.AS): 0.19% controvalore, min 2.95€, max 19.00€ per gamba (ingresso + uscita).
  US (altri):       9.95€ flat per gamba (USD ≈ EUR, approssimazione < 5%).
  Slippage:         0.02% su ogni eseguito (acquisto al rialzo, vendita al ribasso).

4 run: EU senza costi / EU con costi / US senza costi / US con costi.
Schema fisso: GATE TREND_UP + RISK-PARITY (il best arm validato in Run #30/#33).
Report: data/FINECO_COSTS_REPORT.txt
"""
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, ".")
from portfolio_backtester import prepare, backtest, SLIP, FINECO_EU_PCT, FINECO_EU_MIN, FINECO_EU_MAX, FINECO_US_FLAT

EU_PATH  = "data/mib_data_long.csv"
US_PATH  = "data/sp500_data_long.csv"
REPORT   = "data/FINECO_COSTS_REPORT.txt"


def run_arm(label, px_path, costs, pre, equity_out):
    print(f"  {label}...", end="", flush=True)
    eq, res = backtest(px_path=px_path, regime_mode="gate", sizing="riskparity",
                       costs=costs, equity_out=equity_out, _pre=pre)
    print(f"  CAGR {res['CAGR_pct']:+.2f}% | MaxDD {res['MaxDD_pct']:.2f}% | "
          f"Sharpe {res['Sharpe_daily']:.2f} | Costi {res['total_costs_paid']:.0f}€")
    return eq, res


def generate_report(eu_nc, eu_c, us_nc, us_c):
    lines = []
    w = lines.append

    w("=" * 86)
    w(" RUN #34 — COMMISSIONI REALI FINECO + SLIPPAGE")
    w(" portfolio_backtester.py — schema GATE TREND_UP + RISK-PARITY (best arm Run #30/#33)")
    w("=" * 86)
    w("")
    w(" STRUTTURA COSTI FINECO (singola gamba = ingresso O uscita):")
    w(f"   EU  (.MI/.PA/.AS): {FINECO_EU_PCT*100:.2f}% controvalore | min {FINECO_EU_MIN:.2f}€ | max {FINECO_EU_MAX:.2f}€")
    w(f"   US  (altri):       {FINECO_US_FLAT:.2f}€ flat (USD≈EUR, err<5% al cambio corrente)")
    w(f"   Slippage:          {SLIP*100:.2f}% su ogni prezzo eseguito (acquisto +slip, vendita -slip)")
    w(f"   Ogni trade = 2 gambe (ingresso + uscita) -> costo round-trip = 2x il costo singola gamba")
    w("")

    def block(label, nc, cc, w):
        w(f" {label}")
        w(f" {'Schema':<34} {'CAGR%':>8} {'MaxDD%':>8} {'Sharpe':>8} {'Calmar':>8} "
          f"{'Expo%':>8} {'Trade':>7} {'Costi€':>9}")
        w(" " + "-" * 90)

        def row(tag, r):
            cal = r['Calmar']
            cal_s = f"{cal:>+8.2f}" if np.isfinite(cal) else "     n/a"
            costs_s = f"{r['total_costs_paid']:>9.0f}" if r['costs'] else "        -"
            return (f" {tag:<34} {r['CAGR_pct']:>+8.2f} {r['MaxDD_pct']:>8.2f} "
                    f"{r['Sharpe_daily']:>8.2f} {cal_s} {r['avg_exposure_pct']:>8.1f} "
                    f"{r['trades']:>7d} {costs_s}")

        w(row("A  Gate+RP, zero costi",  nc))
        w(row("B  Gate+RP, Fineco+slip", cc))
        w("")

        # delta
        dc = cc['CAGR_pct'] - nc['CAGR_pct']
        dm = cc['MaxDD_pct'] - nc['MaxDD_pct']
        ds = cc['Sharpe_daily'] - nc['Sharpe_daily']
        dca = (cc['Calmar'] - nc['Calmar']) if np.isfinite(cc['Calmar']) and np.isfinite(nc['Calmar']) else float('nan')
        ann_drag = cc['total_costs_paid'] / nc['capital0'] / (nc['days'] / 252) * 100 if nc['days'] > 0 else float('nan')
        rt_cost = cc['total_costs_paid'] / cc['trades'] if cc['trades'] > 0 else 0
        w(f"   Δ CAGR      {dc:>+.2f} pt | Δ MaxDD    {dm:>+.2f} pt | Δ Sharpe {ds:>+.2f}")
        w(f"   Δ Calmar    {dca:>+.2f}    | Drag annuo {ann_drag:>.2f}% | Costo medio/trade {rt_cost:.1f}€ (RT = 2 gambe)")
        edge_survives = cc['Sharpe_daily'] > 0.5 and cc['CAGR_pct'] > 3.0 and cc['MaxDD_pct'] > -40.0
        w(f"   Edge con costi: {'SI (Sharpe>0.5, CAGR>3%, MaxDD>-40%)' if edge_survives else 'DEGRADATO (soglie non rispettate)'}")
        w("")

    block("UNIVERSO EU (mib_data_long.csv, 2018-2026):", eu_nc, eu_c, w)
    block("UNIVERSO S&P 500 (sp500_data_long.csv, 2018-2026):", us_nc, us_c, w)

    w(" CONCLUSIONE CROSS-MARKET:")
    eu_ok = eu_c['Sharpe_daily'] > 0.5 and eu_c['CAGR_pct'] > 3.0
    us_ok = us_c['Sharpe_daily'] > 0.5 and us_c['CAGR_pct'] > 3.0
    eu_drag = (eu_nc['CAGR_pct'] - eu_c['CAGR_pct'])
    us_drag = (us_nc['CAGR_pct'] - us_c['CAGR_pct'])
    w(f"   EU: {'ROBUSTO' if eu_ok else 'MARGINALE'} dopo costi — drag {eu_drag:.2f} pt CAGR | "
      f"Sharpe {eu_c['Sharpe_daily']:.2f} | Calmar {eu_c['Calmar']:.2f}")
    w(f"   US: {'ROBUSTO' if us_ok else 'MARGINALE'} dopo costi — drag {us_drag:.2f} pt CAGR | "
      f"Sharpe {us_c['Sharpe_daily']:.2f} | Calmar {us_c['Calmar']:.2f}")
    w("")
    w(" IMPLICAZIONI OPERATIVE:")

    # turnover analysis
    eu_ann_trades = eu_c['trades'] / (eu_nc['days'] / 252)
    us_ann_trades = us_c['trades'] / (us_nc['days'] / 252)
    w(f"   EU: {eu_c['trades']} trade ({eu_ann_trades:.0f}/anno) -> ridurre il turnover abbassa il drag proporzionalmente.")
    w(f"   US: {us_c['trades']} trade ({us_ann_trades:.0f}/anno) -> 9.95€/gamba flat = drag piu' pesante sui titoli a bassa capitalizzazione.")
    w(f"   Fineco Max EU 19€ = la gamba EU e' economica per posizioni >10k€ (19€ = 0.19% su 10k€ -> il cap morde a 10k€).")
    w(f"   Soglia minima EU 2.95€ = conviene evitare posizioni < 1.550€ ({FINECO_EU_MIN/FINECO_EU_PCT:.0f}€) per non pagare la min fee al 100%.")
    w("")
    w(" LIMITI:")
    w("   - Slippage 0.02% e' una stima conservativa (mercati liquidi in condizioni normali).")
    w("     In gap di apertura o bassa liquidita' puo' arrivare a 0.05-0.10%: testare con SLIP=0.0005.")
    w("   - USD/EUR approssimato (US flat in EUR): errore < 5% al cambio corrente.")
    w("   - Non include tasse su plusvalenze (imposta 26% in Italia: impatta il CAGR effettivo,")
    w("     non il gross CAGR — aggiungere in una simulazione fiscale separata).")
    w("   - Non include bollo titoli (0.2%/anno sul valore medio del portafoglio — stimato ~0.1% sul")
    w("     capitale totale al 50% di esposizione media: un ulteriore drag fisso da considerare).")
    w("=" * 86)

    txt = "\n".join(lines)
    with open(REPORT, "w") as f:
        f.write(txt)
    print(f"\n{'='*86}")
    print(txt)
    print(f"\nReport salvato: {REPORT}")


def main():
    print("=== Run #34: Commissioni Fineco + Slippage ===\n")

    print("1. Precompute EU universe...")
    pre_eu = prepare(EU_PATH)
    print("2. Precompute US universe...")
    pre_us = prepare(US_PATH)
    print()

    print("3. Backtest EU:")
    _, eu_nc = run_arm("EU  zero costi (baseline)",   EU_PATH, False, pre_eu, "data/eu_equity_nocost.csv")
    _, eu_c  = run_arm("EU  Fineco+slip",              EU_PATH, True,  pre_eu, "data/eu_equity_fineco.csv")
    print()

    print("4. Backtest US:")
    _, us_nc = run_arm("US  zero costi (baseline)",   US_PATH, False, pre_us, "data/sp500_equity_nocost.csv")
    _, us_c  = run_arm("US  Fineco+slip",              US_PATH, True,  pre_us, "data/sp500_equity_fineco.csv")
    print()

    generate_report(eu_nc, eu_c, us_nc, us_c)


if __name__ == "__main__":
    main()
