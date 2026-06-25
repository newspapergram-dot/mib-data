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

## Run #2 — 2026-06-25 (report operativo + correzioni codice)

**Obiettivo:** (1) report operativo con prezzi esatti di ingresso/uscita per i 6 nomi
suggeriti; (2) aggiornare i dati vecchi di 6 giorni, risolvere il bug bull/bear (sez. 7
del backtest) e recuperare i fondamentali mancanti dei big USA.

### 1. Report operativo (capitale ipotizzato €50.000, regime TREND_UP → mult x1.0)
Formula del repo (`modules/trade_proposal.py`): `stop = max(entry·0.95, entry−2·ATR)`,
`T1 = entry·1.0411`, `T2 = entry·1.0822`. Report completo in `data/REPORT_RUN2.txt`.

| Titolo | Score | Entry | Stop (SL) | Take Profit 1 | Take Profit 2 | Fonte prezzo |
|--------|------:|------:|----------:|--------------:|--------------:|--------------|
| GOOGL    | 0.306 | 345.29  | 328.03  | 359.48  | 373.67  | EOD 24-giu (FMP) |
| GE       | 0.281 | 365.88  | 347.59  | 380.92  | 395.96  | EOD 24-giu (FMP) |
| SPM.MI   | 0.257 | 4.383   | 4.164   | 4.563   | 4.743   | EOD 18-giu (EU stale) |
| GS       | 0.239 | 1076.91 | 1023.06 | 1121.17 | 1165.43 | EOD 24-giu (FMP) |
| AMZN     | 0.224 | 234.27  | 222.56  | 243.90  | 253.53  | EOD 24-giu (FMP) |
| STMMI.MI | 0.224 | 67.91   | 64.51   | 70.70   | 73.49   | EOD 18-giu (EU stale) |

- R/R uniforme (T1 0.82:1, T2 1.64:1): per tutti il cap statistico −5% è più stretto del
  2·ATR → lo stop è a −5% dall'entry. È una proprietà voluta della strategia (stop stretto).
- **GOOGL è sceso da 363.79 (19-giu) a 345.29 (24-giu), −5.1%**: avrebbe colpito lo stop di
  Run #1. Lezione concreta sul perché lo stop non è negoziabile.

### 2. Correzioni al codice
- **Bug regime bull/bear risolto** (`backtest_v3.py`, `regime_analysis`). Causa reale: in
  `px` erano presenti **sia `SPY` sia `^GSPC`** → indice-data duplicato → il join espandeva
  ogni segnale in 2 righe (una per benchmark) e, con regimi discordi, bull e bear diventavano
  copie quasi identiche dell'intero set (n_bull = n_bear = n_totale). Inoltre `rolling(200)`
  girava su due serie con scale diverse interlacciate → SMA priva di senso. Fix: **un solo
  benchmark** (preferito `^GSPC`, fallback `SPY`) + `drop_duplicates("date")`.
  Verificato su dati reali: prima blow-up 298→587 righe; dopo split sano bull=84 / bear=205.
- **Fallback dati FMP aggiunto** (`modules/fmp_source.py` + hook in `fetch_data.py`).
  Motivo: in sandbox **yfinance è bloccato dal proxy (HTTP 403 sul CONNECT verso Yahoo)** e
  finnhub restituiva P/E/EPS vuoti per i big USA. Il fallback usa FMP (richiede `FMP_API_KEY`).
- **Fondamentali big USA recuperati** (`data/fundamentals.csv`, fonte FMP TTM):
  GOOGL P/E 26.1 / EPS 13.24 / mktcap 4.18T · GE P/E 44.9 / EPS 8.35 / 382B ·
  GS P/E 19.4 / EPS 59.47 / 318B · AMZN P/E 27.6 / EPS 8.45 / 2.52T. Risolto il
  precedente "nessun P/E né EPS disponibile".

### 3. Aggiornamento dati — parziale (limite ambiente)
- Aggiunte le barre EOD reali 22–24 giugno per i nomi del report US + indici `^GSPC`/`^VIX`
  in `data/mib_data.csv` (via FMP).
- **Non completato per EU**: i ticker `.MI`/`.PA` sono gated sul piano FMP attuale e yfinance
  è bloccato → restano fermi al 18–19 giugno. Un refresh completo richiede `FMP_API_KEY` con
  piano adeguato **oppure** l'esecuzione di `fetch_data.py` fuori dalla sandbox (rete Yahoo).
  `data/last_update.txt` annota la natura parziale.
- Macro live (24-giu): S&P 500 7358 (>SMA50>SMA200), VIX rientrato a 18.6, 10y UST 4.41% → regime
  TREND_UP confermato.

### Watch list per il prossimo run
- [ ] Completare il refresh EU (piano FMP o run esterno) — priorità alta per coerenza cross-section.
- [ ] Rigirare `backtest_v3.py` end-to-end ora che il regime è corretto: rileggere la sez. 7
      (l'edge "solo BULL" va ri-misurato, non più copia dell'aggregato).
- [ ] Aggiungere forward P/E e consenso analisti FMP ai fondamentali US (ora vuoti).

---
*Aggiornato dal loop di analisi finanziaria. Le regole apprese vivono in `FINANCIAL_SKILLS.md`.*
