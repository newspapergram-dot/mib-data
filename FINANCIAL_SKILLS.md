# FINANCIAL_SKILLS.md — Regole apprese dal Loop di Analisi

Conoscenza operativa accumulata, run dopo run. Ogni regola nasce da un'evidenza
concreta nei dati del repository o nel mercato. Le regole nuove vanno in fondo.

---

## Lezione #1 — 2026-06-25 — Il regime di mercato viene prima della selezione titoli

**Evidenza.**
- Il backtest v3 mostra che l'edge dello score NUOVO è **validato solo in regime BULL**
  (`backtest_summary.txt`, sez. 7 e note del `weekly_report`); fuori dal trend l'edge
  non è dimostrato.
- Al 2026-06-25 i tre mercati sono concordi **TREND_UP** (IT/FR/US in `regime_filter.csv`,
  confermato live: S&P 500 7358 > SMA50 7349 > SMA200 6916; VIX 18 sotto media; curva
  Treasury positiva 2s10s +0.30%). È quindi il contesto giusto per essere LONG.
- Lo score, da solo, ha correlazione debole con i rendimenti (Spearman 10g ≈ +0.055):
  non basta a generare guadagno se applicato controtrend.

**Regola.**
1. **Decidi prima il regime, poi i titoli.** Controlla `regime_filter.csv` (e i dati live):
   opera LONG e a piena size (risk_mult 1.0) solo quando il mercato di riferimento è TREND_UP.
2. **Se il regime gira (px < SMA200 o slope negativa), riduci o azzera l'esposizione**
   anche se lo score resta alto: l'edge non è validato fuori dal BULL.
3. **In TREND_UP, seleziona il top quintile dello score NUOVO**, holding ~10 giorni
   (massimo Sharpe nella griglia di sensitivity), size ≤10% per posizione.
4. **Lo stop non si tocca.** Il payoff medio è <1: il vantaggio statistico (win rate ~65%)
   esiste solo se le perdite restano tagliate. Disciplina sullo stop = fonte dell'edge.
5. **Pesa la robustezza, non solo il rendimento.** Il DSR (0.849) non supera la soglia 0.95
   e il MaxDD in block-bootstrap arriva a −86% nella coda: tieni size moderata e non
   estrapolare l'equity finale del backtest (+141.7%) come aspettativa realistica.

**Da verificare nei prossimi run.**
- Lo split bull/bear del backtest produce righe identiche → probabile bug di partizionamento
  del regime in `backtest_v3.py` (sez. 7). Finché non è risolto, la conclusione "edge solo in
  BULL" va presa come ipotesi prudente, non come fatto misurato.

---
*Le attività di ogni run sono registrate in `STATE.md`.*
