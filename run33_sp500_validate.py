#!/usr/bin/env python3
"""run33_sp500_validate.py — Run #33: S&P 500 Out-of-Universe Validation.

Esegue il portfolio_backtester (GATE + RISK-PARITY) sull'universo S&P 500 (sp500_data_long.csv)
e confronta le metriche con il ciclo EU (mib_data_long.csv, Run #28-30).
Genera data/SP500_VALIDATION_REPORT.txt.

Nota metodologica:
  - Il modello (score_new + regime gate + risk-parity) NON e' stato addestrato su dati USA.
    L'universo EU serviva sia per la scoperta che per la validazione del segnale (bias in-sample).
    L'universo S&P 500 e' genuinamente OOS.
  - Soglia score = p80 GLOBALE del dataset USA (bias in-sample leggero).
  - Costi di transazione NON nel motore (invariato vs Run EU — confronto coerente).
"""
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, ".")
from portfolio_backtester import prepare, backtest, _paired_boot

SP500_PATH = "data/sp500_data_long.csv"
REPORT     = "data/SP500_VALIDATION_REPORT.txt"

# Metriche EU ciclo completo (Run #30, held-portfolio, regime GATE + RISK-PARITY)
EU_BEST = {
    "CAGR_pct":           11.73,
    "MaxDD_pct":         -13.15,
    "Sharpe_daily":        1.04,
    "Vol_ann_pct":        11.97,
    "Calmar":              0.89,
    "avg_exposure_pct":   54.4,
    "trades":             1208,
}
EU_GATE_EQW = {   # Run #28 gate+equal-weight (baseline EU senza RP)
    "CAGR_pct":           12.44,
    "MaxDD_pct":         -17.81,
    "Sharpe_daily":        0.93,
    "Calmar":              0.70,
    "avg_exposure_pct":   59.9,
    "trades":             1208,
}


def run_sp500():
    print("=== Run #33: S&P 500 Out-of-Universe Validation ===\n")
    print("1. Caricamento dati SP500...")
    try:
        pre = prepare(SP500_PATH)
    except Exception as e:
        print(f"ERRORE caricamento {SP500_PATH}: {e}")
        sys.exit(1)
    close_raw, close_mtm, score_panel, regime_by_mkt, thr, cal, atr_panel, med_atr = pre
    n_tickers = close_raw.shape[1] - (1 if "^GSPC" in close_raw.columns else 0)
    print(f"   {close_raw.shape[1]} ticker (incl. ^GSPC), {len(cal)} date, thr score p80={thr:.3f}")

    if "US" not in regime_by_mkt:
        print("ERRORE: ^GSPC non trovato nel dataset — regime gate non funziona")
        sys.exit(1)
    us_reg = regime_by_mkt["US"]
    trend_days = int((us_reg == "TREND_UP").sum())
    print(f"   ^GSPC regime: TREND_UP {trend_days}/{len(us_reg)} giorni ({trend_days/len(us_reg)*100:.0f}%)")

    # A) ALWAYS-IN — baseline puro segnale
    print("\n2. Backtest A — ALWAYS-IN (no gate, equal-weight)...")
    eq_A, rA = backtest(px_path=SP500_PATH, regime_mode="off", sizing="equal",
                        equity_out="data/sp500_equity_A.csv", _pre=pre)
    print(f"   CAGR {rA['CAGR_pct']:+.2f}% | MaxDD {rA['MaxDD_pct']:.2f}% | "
          f"Sharpe {rA['Sharpe_daily']:.2f} | Exposure {rA['avg_exposure_pct']:.1f}%")

    # B) GATE TREND_UP + equal-weight
    print("\n3. Backtest B — GATE TREND_UP + equal-weight...")
    eq_B, rB = backtest(px_path=SP500_PATH, regime_mode="gate", sizing="equal",
                        equity_out="data/sp500_equity_B.csv", _pre=pre)
    print(f"   CAGR {rB['CAGR_pct']:+.2f}% | MaxDD {rB['MaxDD_pct']:.2f}% | "
          f"Sharpe {rB['Sharpe_daily']:.2f} | Exposure {rB['avg_exposure_pct']:.1f}%")

    # C) GATE + RISK-PARITY — schema principale
    print("\n4. Backtest C — GATE TREND_UP + Risk-Parity sizing...")
    eq_C, rC = backtest(px_path=SP500_PATH, regime_mode="gate", sizing="riskparity",
                        equity_out="data/sp500_equity_C.csv", _pre=pre)
    print(f"   CAGR {rC['CAGR_pct']:+.2f}% | MaxDD {rC['MaxDD_pct']:.2f}% | "
          f"Sharpe {rC['Sharpe_daily']:.2f} | Exposure {rC['avg_exposure_pct']:.1f}%")

    # Bootstrap paired C vs B
    print("\n5. Bootstrap paired C vs B (ΔMaxDD, ΔSharpe, n=2000)...")
    ret_B = eq_B["equity"].pct_change().dropna()
    ret_C = eq_C["equity"].pct_change().dropna()
    (mdd_lo, mdd_md, mdd_hi), (sh_lo, sh_md, sh_hi) = _paired_boot(ret_B, ret_C)
    rp_us = mdd_lo > 0
    print(f"   ΔSharpe  {sh_md:+.2f} IC95 [{sh_lo:+.2f},{sh_hi:+.2f}]")
    print(f"   ΔMaxDD   {mdd_md:+.2f} IC95 [{mdd_lo:+.2f},{mdd_hi:+.2f}]")
    print(f"   Risk-parity US: {'VALIDATO (IC95 ΔMaxDD esclude 0)' if rp_us else 'non significativo'}")

    generate_report(rA, rB, rC, mdd_lo, mdd_md, mdd_hi, sh_lo, sh_md, sh_hi, rp_us,
                    close_raw.shape[1], thr, med_atr, cal, trend_days, len(us_reg))


def generate_report(rA, rB, rC, mdd_lo, mdd_md, mdd_hi, sh_lo, sh_md, sh_hi, rp_us,
                    n_all_tickers, thr, med_atr, cal, trend_days, total_days):
    period = f"{cal[201]} -> {cal[-1]}"
    lines = []
    w = lines.append

    w("=" * 82)
    w(" RUN #33 — S&P 500 OUT-OF-UNIVERSE VALIDATION")
    w(" portfolio_backtester.py su data/sp500_data_long.csv (ciclo 2018-2026)")
    w("=" * 82)
    w("")
    w(f" UNIVERSO: {n_all_tickers-1} ticker S&P 500 (multi-settore, liquidi) + ^GSPC (regime)")
    w(f" PERIODO : {period}  |  soglia score top-quintile p80 = {thr:.3f}")
    w(f" REGIME ^GSPC: TREND_UP {trend_days}/{total_days} giorni ({trend_days/total_days*100:.0f}%) "
      f"| medATR% = {med_atr*100:.2f}%")
    w("")
    w(" ARCHITETTURA: identica a Run #27-31 EU (zero modifiche al motore).")
    w("   Ingresso close t+1 (segnale t, no lookahead), holding 10 gg operativi,")
    w("   max 10 posizioni x 10% capitale, equity MTM giornaliera reale.")
    w("")
    w(" METRICHE CICLO COMPLETO 2018-2026 — S&P 500:")
    w(f" {'Schema':<30} {'CAGR%':>8} {'MaxDD%':>8} {'Sharpe':>8} {'Calmar':>8} {'Expo%':>8} {'Trade':>7}")
    w(" " + "-"*79)

    def row(label, m):
        cal_ = m['Calmar']
        cal_s = f"{cal_:>+8.2f}" if np.isfinite(cal_) else "     n/a"
        return (f" {label:<30} {m['CAGR_pct']:>+8.2f} {m['MaxDD_pct']:>8.2f} "
                f"{m['Sharpe_daily']:>8.2f} {cal_s} {m['avg_exposure_pct']:>8.1f} {m['trades']:>7d}")

    w(row("A  ALWAYS-IN (no gate, equal)",  rA))
    w(row("B  GATE TREND_UP (equal)",        rB))
    w(row("C  GATE + RISK-PARITY",           rC))
    w("")
    w(f" Bootstrap PAIRED C vs B (block=10, n=2000):")
    w(f"   ΔMaxDD  {mdd_md:+.2f} pt  IC95 [{mdd_lo:+.2f}, {mdd_hi:+.2f}]")
    w(f"   ΔSharpe {sh_md:+.2f}      IC95 [{sh_lo:+.2f}, {sh_hi:+.2f}]")
    w(f"   -> Risk-parity USA: {'VALIDATO (IC95 ΔMaxDD esclude 0)' if rp_us else 'non significativo (IC95 attraversa 0)'}")
    w("")
    w(" CONFRONTO EU (Run #30) vs S&P 500 (Run #33) — schema GATE + RISK-PARITY:")
    w(f" {'Metrica':<22} {'EU (mib_data_long)':>22} {'S&P 500 (sp500_data)':>22}")
    w(" " + "-"*66)
    compare = [
        ("CAGR %",        EU_BEST["CAGR_pct"],        rC["CAGR_pct"]),
        ("MaxDD %",       EU_BEST["MaxDD_pct"],        rC["MaxDD_pct"]),
        ("Sharpe",        EU_BEST["Sharpe_daily"],     rC["Sharpe_daily"]),
        ("Vol % ann",     EU_BEST["Vol_ann_pct"],      rC["Vol_ann_pct"]),
        ("Calmar",        EU_BEST["Calmar"],            rC["Calmar"]),
        ("Exposure %",    EU_BEST["avg_exposure_pct"], rC["avg_exposure_pct"]),
        ("Trade totali",  EU_BEST["trades"],            rC["trades"]),
    ]
    for name, ev, uv in compare:
        if isinstance(ev, int):
            w(f" {name:<22} {int(ev):>22d} {int(uv):>22d}")
        else:
            w(f" {name:<22} {ev:>22.2f} {uv:>22.2f}")
    w("")

    # Criteri di robustezza cross-market
    edge_ok   = rC["Sharpe_daily"] > 0.5 and rC["CAGR_pct"] > 3.0 and rC["MaxDD_pct"] > -40.0
    calmar_ok = np.isfinite(rC["Calmar"]) and rC["Calmar"] > 0.3
    sharpe_d  = abs(rC["Sharpe_daily"] - EU_BEST["Sharpe_daily"])
    comparable = sharpe_d < 0.5

    w(" VALUTAZIONE CROSS-MARKET (criteri: Sharpe>0.5, CAGR>3%, MaxDD>-40%, Calmar>0.3):")
    w(f"   Edge positivo (S&P 500): {'SI' if edge_ok else 'NO'}")
    w(f"   Calmar accettabile:       {'SI' if calmar_ok else 'NO'}")
    w(f"   Sharpe comparabile EU (Δ < 0.5): {'SI' if comparable else f'NO (Δ={sharpe_d:.2f})'}")
    w("")
    if edge_ok and comparable:
        w("   CONCLUSIONE: il segnale score_new + regime gate e' ROBUSTO cross-market.")
        w("   L'edge non e' specifico all'universo EU: si replica su S&P 500 (genuinamente OOS).")
        w("   Implicazione operativa: il modello e' candidato a coprire anche azioni USA in TREND_UP.")
    elif edge_ok:
        w("   CONCLUSIONE PARZIALE: l'edge esiste su S&P 500 ma con profilo diverso dall'EU.")
        w("   Differenze plausibili (diversa vol USA vs EU, % TREND_UP diverso, campione diverso).")
        w("   L'edge cross-market non e' rigettato ma non e' identico: usare con cautela su US.")
    else:
        w("   CONCLUSIONE: l'edge NON si replica in modo affidabile su S&P 500.")
        w("   Il segnale sembra specifico al contesto EU — non usare per US senza ri-calibrazione.")
    w("")
    w(" LIMITI:")
    w("   - Soglia p80 globale (bias in-sample leggero); universo conservativo (76 ticker).")
    w("   - Costi di transazione non nel motore (identico a run EU — confronto coerente).")
    w("   - EU: bias scoperta+validazione; S&P 500: genuinamente OOS (piu' robusto da interpretare).")
    w("   - Equity giornaliere: data/sp500_equity_A/B/C.csv")
    w("=" * 82)

    report = "\n".join(lines)
    with open(REPORT, "w") as f:
        f.write(report)
    print(f"\n{'='*82}")
    print(report)
    print(f"\nReport salvato: {REPORT}")


if __name__ == "__main__":
    run_sp500()
