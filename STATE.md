# STATE.md — Diario del Loop di Analisi Finanziaria

Repository: `mib-data` (Swing Copilot EU + USA)
Loop avviato: 2026-06-25

---

## Run #1 — 2026-06-25 (inizializzazione)

**Obiettivo:** prima analisi dettagliata di indici USA/EU e azioni nel repository per
individuare potenziali guadagni e quadro macro; definire la strategia operativa.

### Cosa ho fatto
1. **Esplorato il repository** `mib-data`: pipeline di scoring swing (EU+USA) con
   `score_generator.py`, `regime_filter.py`, `backtest_v3.py`, moduli `debate`/`fundamentals`/
   `trade_proposal` e output in `data/`.
2. **Letto lo stato dei dati**: ultimo aggiornamento dataset `2026-06-19T12:52Z`
   (`data/last_update.txt`); 128 ticker coperti, 79 righe in `score_output.csv`.
3. **Quadro macro / regime** (snapshot repo `data/regime_filter.csv`):
   - IT `FTSEMIB.MI` → TREND_UP (px>SMA50, px>SMA200, slope50 +5.24%), risk_mult 1.0
   - FR `^FCHI` → TREND_UP (slope50 +1.76%), risk_mult 1.0
   - US `^GSPC` → TREND_UP (slope50 +5.13%), risk_mult 1.0
4. **Dati live integrati** (FMP, 2026-06-25):
   - S&P 500 `^GSPC` 7358.22 (>SMA50 7349, >SMA200 6916; ~3.5% sotto max anno 7620) → uptrend confermato live
   - VIX 18.05 (−3.1%, sotto media 200g 18.6) → volatilità contenuta, contesto risk-on
   - Treasury: 10y 4.41% (in calo da 4.51% nella settimana), 2y 4.11%, spread 2s10s +0.30% → curva positiva, nessuna inversione
5. **Letto il backtest istituzionale v3** (`data/backtest_summary.txt`): score NUOVO domina
   il VECCHIO (Sharpe 1.88 vs 1.40, Profit Factor 2.75, win rate 65%, +141.7% equity),
   con caveat di robustezza (DSR 0.849 < 0.95, MaxDD bootstrap fino a −86% in coda).
6. **Individuato il ranking corrente** (`data/score_output.csv`, top per score):
   GOOGL 0.306 · GE 0.281 · SPM.MI 0.257 · GS 0.239 · AMZN 0.224 · STMMI.MI/STMPA.PA 0.224.
7. **Creato** `STATE.md` (questo diario) e `FINANCIAL_SKILLS.md` (regole apprese).
8. **Definita e scritta in output la strategia operativa** (vedi sezione sotto e chat).

### Strategia operativa decisa (sintesi)
- **Regime:** tutti e tre i mercati TREND_UP → bias LONG, moltiplicatore rischio x1.0.
- **Selezione:** long-only sul top quintile dello score NUOVO; orizzonte holding 10 giorni
  (sweet spot di Sharpe nella griglia di sensitivity).
- **Rischio:** size per posizione capped al 10% del portafoglio; stop NON negoziabile
  (payoff medio <1 → la disciplina sugli stop è la fonte dell'edge).
- **Edge:** validato solo in regime BULL → ridurre/azzerare esposizione se il regime gira.
- **Cautela:** DSR non supera la soglia → tenere size moderata e considerare il rischio di coda.

### Watch list per il prossimo run
- [ ] Dataset da rinfrescare: ha 6 giorni (`last_update.txt` = 2026-06-19).
- [ ] Bug regime nel backtest: le righe bull/bear sono identiche (n=1100, ret +0.338%) →
      lo split di regime non sta partizionando i trade; verificare `backtest_v3.py`.
- [ ] Fondamentali mancanti per i big USA (GOOGL/GE: niente P/E né EPS) → migliorare la fonte.
- [ ] Confermare i prezzi live dei top pick (tool quote azioni gated sul piano FMP attuale).

---
*Aggiornato dal loop di analisi finanziaria. Le regole apprese vivono in `FINANCIAL_SKILLS.md`.*
