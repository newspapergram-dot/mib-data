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

## Run #3 — 2026-06-25 (Smart Money / Foreground + sblocco EU in codice)

**Obiettivo:** (Fase 1) ispezione struttura repo; (Fase 2) sbloccare i dati EU con
fallback pulito e aggiungere una logica 'Smart Money' (ADL / volume-ponderato / anomalie
volume) per intercettare i grandi fondi; (Fase 3) report `data/REPORT_RUN3.txt`, lezione #3,
update STATE.

### Fase 1 — Ispezione (cosa già esiste, per non duplicare)
- `score_generator.py`: ranking = gate (px>SMA200 & SMA50>SMA200) → score tecnico
  (RSI/ADX/MOM/MACD) + score flow (13F guru, insider, short FR) con decay/ensemble.
  **Nessun segnale volume-based**: lo Smart Money è quindi un'aggiunta complementare.
- `volume_tools.py`: già presenti `validate_volume`, `obv`, `cmf`, `vwap`, `cmf_mfi`,
  **e già una `fetch_stooq_fallback`** (mappa .MI→.IT, .PA→.FR). Da riusare, non riscrivere.
- `modules/fmp_source.py` (Run #2): client FMP con `get_eod`/`get_fundamentals`.

### Fase 2 — Esecuzione
1. **Sblocco EU (in codice, senza duplicazione).** Aggiunta catena pulita
   `modules/fmp_source.get_eod_eu()`: ① FMP nativo → ② **stooq riusando
   `volume_tools.fetch_stooq_fallback`**. Wired in `fetch_data.py` (i ticker EU usano la
   catena se yfinance fallisce).
   - **Stato live**: EU NON sbloccabile in questa sandbox — *tutte* le fonti EU sono bloccate:
     yfinance→proxy 403, stooq→proxy 403, FMP→piano "US-domestic only" (anche gli ADR STM/E
     gated). Verificato che gli US-domestic (AAPL/GOOGL/…) passano, i foreign issuer no.
     → il codice è pronto; lo sblocco effettivo richiede copertura FMP-EU, egress verso
     stooq/yahoo, o run esterno. Nessun dato EU fabbricato.
2. **Smart Money / Foreground.** Aggiunte a `volume_tools.py` (riusando `cmf`):
   - `ad_line()` — Accumulation/Distribution Line (Williams), cumulata complementare al CMF.
   - `volume_anomaly()` — flag volume ultimo > 1.5× media20 + direzione (accum/distrib).
   - `smart_money_signal()` — score [-1,+1] = pendenza ADL + CMF20 + spike di volume direzionale.

### Fase 3 — Output
- **Ranking aggiornato** (`score_generator.py` rieseguito su dati US@24-giu):
  GOOGL 0.301 · GS 0.252 · AMZN 0.207 · SPM.MI 0.169 · GE 0.166 · STMMI.MI 0.148.
- **Report**: `data/REPORT_RUN3.txt` (tabella operativa + colonna Smart$, scan universo
  accumulazione/distribuzione, schede con verdetto Foreground, stato sblocco EU).
- **Insight chiave dal Foreground**:
  - **AMZN**: score long +0.21 ma **DISTRIBUZIONE** (sm −0.74, ADL −89%, CMF −0.26) →
    il flusso reale dei fondi contraddice il long. Veto/cautela.
  - **GE**: **ACCUMULAZIONE** (sm +0.39, ADL +21%) → conferma il long nonostante score modesto.
  - Universo: top accumulazione BAMI.MI/SRG.MI/ISP.MI (banche/utility IT); top distribuzione
    Stellantis (STLAM/STLAP), CRM (vol 3.46×!), XLRE. (EU su dati 18-giu.)
- Macro live 25-giu: S&P 7358 (>SMA50>SMA200), VIX 18.0, 10y 4.41% → regime risk-on confermato.
- Nota dati: barra 25-giu non ancora pubblicata → ultimo EOD consistente 24-giu.

### Addendum Run #3b — Piano C sblocco EU (API Yahoo JSON + header browser)
- Aggiunta `modules/fmp_source.get_eod_eu_robust()`: interroga l'API pubblica JSON di Yahoo
  (`query1.finance.yahoo.com/v8/finance/chart/<TICKER>`) con User-Agent da browser reale, su
  formato ticker Yahoo (es. `ISP.MI`). Scelto l'endpoint JSON ufficiale (non lo scraping HTML
  di Investing/MarketScreener, fragile e spesso vietato dai ToS).
- `fetch_data.py`: cascata di fallback per gli EU ora Piano A (FMP) → B (stooq) → **C (Yahoo
  JSON robust)**; se tutti falliscono, **WARN chiaro e riga OMESSA (mai inventata)**.
- **Verifica live**: anche il Piano C è bloccato in sandbox — `query1.finance.yahoo.com:443
  → 403 al CONNECT (policy denial)`. Importante: **lo User-Agent NON aggira un blocco di
  egress per allowlist di host** (il rifiuto avviene al tunnel CONNECT, prima di ogni header).
  Il codice è corretto e funzionerà dove l'host è raggiungibile; qui resta None gestito,
  nessun dato EU fabbricato. Non si tenta di forzare la policy del proxy (vedi README proxy).

### Addendum Run #3c — Piano D sblocco EU (scheda pubblica Borsa Italiana)
- Aggiunta `modules/fmp_source.get_eod_eu_borsait()`: parsing della scheda pubblica
  `borsaitaliana.it/borsa/azioni/scheda/<ISIN>.html` (mappa ticker→ISIN per i nomi principali).
  Estrae la chiusura/prezzo di riferimento + O/H/L/volume se presenti. UA reale + ritardo di
  **cortesia/rate-limit** (non per simulare un umano né per eludere protezioni).
- `fetch_data.py`: cascata EU ora A (FMP) → B (stooq) → C (Yahoo JSON) → **D (Borsa Italiana,
  solo `.MI`)**; se tutto fallisce, WARN chiaro e riga OMESSA.
- **Diagnosi endpoint-vs-policy (richiesta esplicita)**: è **POLICY**. Verifica live:
  `www.borsaitaliana.it:443 → 403 al CONNECT (policy denial)`. Non è arrivato alcun 403 *dal*
  web server di Borsa Italiana: il rifiuto è del gateway di egress *prima* della richiesta HTTP
  (ProxyError sul CONNECT). Un blocco anti-bot del sito darebbe invece un vero HTTP 403, che il
  codice distingue e logga come "403 Borsa Italiana". → cambiare host/header/sleep non aiuta:
  il vincolo è l'allowlist di egress, non l'endpoint.

### Decisione Run #3d — leva scelta: ALLOWLIST DOMINI EGRESS
- Esito test esaustivo: lo sblocco EU è impossibile in-sandbox per **policy di egress + piano
  FMP**, non per il codice. Bloccati al CONNECT (403): yfinance, stooq, query1.finance.yahoo.com,
  borsaitaliana.it; FMP MCP gated su EU (anche senza filtro date; screener gated).
- Leva scelta dall'utente: **allowlist domini egress**. Dominio minimo e più funzionale da
  aggiungere: **`query1.finance.yahoo.com`** (copre tutti i .MI/.PA con OHLCV completo via Piano C).
  Backup opzionali: `query2.finance.yahoo.com`, `stooq.com` (Piano B).
- NB: la network policy si imposta alla **creazione dell'environment** → ha effetto in una
  **nuova sessione**, non a caldo (testato: dopo la scelta i domini risultano ancora 403).
- **Azione una volta attivo l'allowlist (nessun nuovo codice):**
  `python3 fetch_data.py` (il Piano C scarica EU live) → `python3 score_generator.py` → report RUN4.

### Watch list per il prossimo run
- [ ] **Quando `query1.finance.yahoo.com` è raggiungibile**: rifare il refresh EU (2 comandi sopra)
      e generare REPORT_RUN4 con scan Foreground EU finalmente fresco.
- [ ] Integrare lo `smart_money_signal` come 4° componente in `score_generator` (oggi è overlay).
      Validarlo nel backtest prima di pesarlo nello score.
- [ ] Ri-girare `backtest_v3.py` col regime corretto (da Run #2) e misurare l'edge dello Smart Money.

---
*Aggiornato dal loop di analisi finanziaria. Le regole apprese vivono in `FINANCIAL_SKILLS.md`.*
