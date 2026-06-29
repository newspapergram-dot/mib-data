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

---

## Run #4 — 2026-06-25 (EU SBLOCCATO — refresh completo live)

**Sblocco riuscito.** L'utente ha aggiunto i domini all'allowlist di egress
(`query1.finance.yahoo.com` ecc.). Verificato raggiungibile → il **Piano C** già scritto
(`get_eod_eu_robust`, API JSON Yahoo v8) ha sbloccato l'intero universo, EU compreso, con
la barra di **oggi 25-giu**.

### Cosa ho fatto
1. **Refresh COMPLETO** dell'universo via Piano C (Yahoo v8), 2 anni di storia, fonte unica e
   coerente: **127/128 ticker** freschi al 2026-06-25 (`data/mib_data.csv`, 64.241 righe).
   - Unico fallito: `BPSO.MI` (404 Yahoo, cambio simbolo/delisting) → **omesso, non inventato**.
   - NB: `yfinance` resta KO anche con l'allowlist (usa anche `fc.yahoo.com` per cookie/crumb,
     non in allowlist). L'endpoint diretto **v8 JSON** è più robusto della libreria → usato quello.
2. **Ranking rigenerato** (`score_generator.py`) su dati freschi: GOOGL 0.343 · STMPA/STMMI.PA 0.231
   · EDEN.PA 0.202 · ENGI.PA 0.190 · VIE.PA 0.189 · MRK 0.188 · PRY.MI 0.187 (EU ora pesa molto).
3. **`regime_filter.csv` rigenerato**: IT/FR/US tutti TREND_UP (x1.0). **Nota fragilità**: S&P 500
   a −0.09% dalla SMA50 → regime US sul filo, un calo modesto lo ribalta in RISK_OFF.
4. **REPORT_RUN4** (`data/REPORT_RUN4.txt`): tabella operativa + overlay Smart Money + scan
   accumulazione/distribuzione, ora **tutto su dati freschi 25-giu** (niente più EU-stale).

### Insight dal Foreground (ora EU fresco)
- **Accumulazione**: utility/banche IT (SRG.MI, BAMI.MI, BMPS.MI, G.MI, TRN.MI) e FR (CS.PA,
  VIE.PA). **VIE.PA** (sm +0.68) ed **ENGI.PA** (sm +0.53) = score long *confermato* dal volume.
- **Distribuzione (veto)**: **AAPL** (sm −1.00, ADL −94%), **AMZN** (−0.78), Stellantis
  (STLAM/STLAP), **MC.PA**, **LDO.MI**. EDEN.PA è in top score ma in distribuzione → cautela.

### Addendum Run #4b — Piano C reso sorgente PRIMARIA in `fetch_data.py`
- `fetch_data.py` riscritto: ordine sorgenti ora **1) Piano C (Yahoo v8 JSON) → 2) yfinance →
  3) FMP/catena EU → 4) Borsa Italiana**. Logica isolata in `fetch_one()`; esecuzione sotto
  `if __name__ == "__main__"` (importare il modulo non scarica più nulla — bug latente risolto).
- `modules/fmp_source.get_eod_eu_robust`: ora se è indicata una finestra date usa
  `period1`/`period2` (epoch) invece di `range`, così una richiesta su molti mesi non viene
  troncata. Verificato: finestra 14m → 299 barre (prima ~60). Piano C primario su US/EU/indici OK.

---

## Run #5 — 2026-06-25 (collaudo end-to-end + piano d'azione + audit del processo)

**Test del processo completo** con la nuova sorgente primaria:
`fetch_data.py` (Piano C, 127/128 ticker in 82s) → `score_generator.py` → `regime_filter.py`
→ filtro multi-requisito (`data/ACTION_PLAN.txt`).

### Piano d'azione — requisiti applicati (idoneo solo se li rispetta TUTTI)
R1 gate (px>SMA200 & SMA50>SMA200) · R2 regime mercato TREND_UP · R3 score top quintile
(≥0.169) · R4 Smart Money non in distribuzione (sm≥0) · R5 confidenza ≥MEDIA · R6 volume
affidabile · **+ dedup doppie quotazioni stesso emittente**.

**Esito: 1 titolo idoneo → STMMI.MI** (STMicroelectronics, Milano; tenuta vs Parigi perché
costo round-trip inferiore 0.20% vs 0.40%). Entry 65.05 · Stop 61.80 · T1 67.72 · T2 70.40 ·
sizing 76 az ≈ 4.944€ (9.9%, x1.0) · rischio max 247€. Foreground neutro (sm +0.14), volume ok.
Quasi-idonei bocciati quasi tutti su R5 (confidenza BASSA) o R4 (distribuzione: EDEN.PA, UCG.MI).

### ERRORI TROVATI E CORRETTI nel processo
1. **`regime_filter.py` __main__**: scaricava `mib_data.csv` da raw.githubusercontent/**main**
   → crash `IncompleteRead` (file da 3.5MB troncato) **e** dati STALE (classificava il regime
   sul branch main, non sul fresco locale). → FIX: legge `data/mib_data.csv` locale (remoto solo fallback).
2. **`volume_tools.py` __main__**: identico bug di download da main. → FIX: legge locale.
3. **Piano d'azione, doppia quotazione**: STMMI.MI e STMPA.PA sono lo STESSO emittente (ISIN
   NL0000226223) → comparivano entrambi = doppia esposizione nascosta. → FIX: dedup per emittente.

### MARGINI DI MIGLIORAMENTO (segnalati — scelte di design, non ancora applicate)
4. **Confidenza mal calibrata vs scala score**: soglie assolute 0.20/0.45, ma gli score reali
   sono compressi (max ~0.29) → quasi tutto "BASSA" e "ALTA" (≥0.45) non si raggiunge MAI →
   R5 over-filtra. Proposta: soglie percentile-based o ricalibrate alla distribuzione.
5. **R4 confine netto a 0**: GOOGL sm −0.07 (di fatto neutro) bocciato. Proposta: banda neutra
   (pass se sm≥−0.15) + tier "alta convinzione" se sm≥+0.33 (accumulazione).
6. **Score poco dispersivo** (tanh satura presto): il ranking discrimina poco; rivedere la
   normalizzazione di `score_technical`.
7. **Profondità storica** `MONTHS_BACK=14` (~298 barre): SMA200 ok ma con poco margine; valutare 18–24 mesi.
8. **Smart Money non ancora validato nel backtest**: filtra ma manca la prova statistica
   (correlazione col forward return) prima di pesarlo nello score.
9. **Conflitto score↔Foreground su GOOGL**: #1 per score (trainato dal flow 13F 0.5, dato a 40+gg)
   ma Smart Money neutro/negativo → valutare di pesare meno il 13F quando il volume contraddice.
10. **Watchlist**: `BPSO.MI` dà 404 su Yahoo (probabile cambio simbolo) → aggiornare la lista.

---

## Run #6 — 2026-06-25 (obiettivi: portafoglio piu' ampio + take profit piu' alti)

### Obiettivo 2 — TP piu' ampi e R/R favorevole (`modules/trade_proposal.py`)
- I vecchi target fissi (+4.11% / +8.22%) davano **R/R 0.82** (si rischiava il 5% per puntarne il 4):
  troppo bassi, e per conti piccoli i costi erodevano il margine.
- Nuovi target **T1/T2/T3 = max(k·ATR, k·rischio)** con k_ATR=(3,6,10) e floor R/R=(1.5,3,5).
  Gli ATR-multipli corrispondono a ~1σ/2σ/3σ sull'orizzonte di holding → laddering principiato.
  Aggiunto **T3 "runner"** e, per ogni target, il **guadagno netto in % e in EUR** sulla posizione.
  Flag di **efficienza per conti piccoli** (T1 netto deve battere nettamente i costi).
  Es. STM: prima T1 +1.35%/+77€ → ora **T1 +15.4%/+760€, T2 +30.9%/+1530€, T3 +51.7%/+2556€**.
- Aggiunti parametri `size_mult` (convinzione) e `pos_cap`. Backward-compatible (weekly_report OK).

### Obiettivo 1 — portafoglio piu' ampio
- **Universo ampliato**: +15 large cap USA liquide in `fetch_data.py` → **142 ticker** (80 gated).
- **`portfolio_builder.py` (NUOVO)**: filtri MENO restrittivi + sizing per convinzione:
  - R3 score top **meta'** (perc. 50) invece di top quintile; R4 **banda neutra** smart-money
    (sm≥−0.15: esclude solo la distribuzione); confidenza/illiquidita' **scalano la size**, non escludono.
  - tier su percentili dello score (calibrati ai dati) + bonus accumulazione − penalita' illiquidi.
  - dedup per emittente; cap esposizione 85%, max 12 nomi.
- **Risultato: da 1 → 12 titoli** (`data/PORTFOLIO.txt`), diversificati IT/FR/US, esposizione 85%.
  Top per convinzione: AMAT, VIE.PA, TRN.MI, ISP.MI, ENGI.PA (tutti in accumulazione).
  Potenziale netto (ottimistico): **+6.4% a T1, +13.2% a T2, +22.2% a T3** sul capitale.

### Caveat onesto
- TP piu' larghi = **hit-rate piu' basso** del 74% storico (misurato sui VECCHI target): il payoff
  sale ma la probabilita' di toccare il target scende. **Da ri-validare nel backtest** prima di
  fidarsi dei numeri di vincita storici con i nuovi target.

---

## Run #7 — 2026-06-25 (backtest + taratura moltiplicatori target sui risultati)

### Backtest base ri-validato su dati freschi (142 ticker, `backtest_v3.py`)
- Score NUOVO: Sharpe **1.89**, PF 3.03, win 68.3%, expectancy +3.09%, Spearman 10gg +0.086.
- **Fix regime confermato** (sez.7): bull n=1016 / bear n=189 / unknown distinti (niente piu' copie).
- Robustezza: PBO 0.000 (ok), WFE +2.34 (OOS>IS, ok), bootstrap Sharpe IC [0.61, 2.16];
  **DSR 0.794 < 0.95** → edge reale ma non blindato (cautela multiple-testing).

### Taratura target su simulazione PATH-BASED (`target_backtest.py`, NUOVO tool)
Simulazione uscita target/stop/timeout su top-quintile; stop = repo (max -5%/2ATR).
- **Sweep target singolo**: expectancy CRESCE col multiplo (coda fat-tail), hit% crolla
  (m=1→64% hit/exp 0.14%; m=3→31%/0.99%; m=10→1%/2.09%). exp/sd picco ~6×ATR (N=10).
- **Confronto laddered [0.5/0.25/0.25]** (exp% | med% | win% | exp/sd, N=10):
  - (3,6,10) **exp-max**: 1.50 | −0.17 | 49.4 | 0.216  → expectancy massima ma mediana NEGATIVA
  - **(2,6,10) SCELTO**: 1.27 | **+0.28** | **51.0** | 0.200
  - (2,4,6) tight: 1.10 | +0.28 | 51.0 | 0.185
- **Decisione**: default cambiati da (3,6,10) a **(2,6,10)** in `trade_proposal.py`. Si porta
  T1 a 2×ATR ("hittable" ~50%): mediana per-trade da −0.17% a **+0.28%**, win 49%→51%, cedendo
  ~15% di expectancy → curva piu' liscia, adatta a conti piccoli (obiettivo dell'utente).
  T2/T3 (6,10) restano larghi: la coda dei vincitori e' dove sta l'expectancy. Chi vuole la
  sola expectancy max usa (3,6,10) (un parametro).
- `portfolio_builder.py` e schede rigenerati con i nuovi target; testo PRO/CONTRO aggiornato
  (mediana ~0, edge nella coda, DSR<0.95).

---

## Run #8 — 2026-06-25 (validazione Smart Money + calibrazione confidenza)

### Smart Money e' un predittore? (`sm_validate.py`, NUOVO tool, point-in-time)
- **Spearman vs forward return netto**: score 10gg 0.086 | smart$ 10gg 0.037 (debole) ma 20gg
  **0.078** (piu' forte sul lungo). **Il blend lineare 0.7·score+0.3·sm PEGGIORA il 10gg
  (0.059 < 0.086)**: diluisce l'edge dello score.
- **Ret medio per stato (10gg)**: accumulazione +0.99% (win 51%), distribuzione +0.88% (win 52%),
  **neutro −0.245% (win 44%, il peggiore)** → lo stato grezzo non e' monotono col rendimento.
- **DENTRO il top-quintile** invece: accumulazione **+3.14% (win 60%)** vs distribuzione
  **+1.63% (win 40%)**, spread **+1.51%** → l'effetto e' un'INTERAZIONE col top-quintile.
- **DECISIONE**: NON integrare lo Smart Money come componente lineare in `score_generator`
  (peggiorerebbe il 10gg). Si tiene come **filtro di conferma/veto DENTRO la selezione**
  (gia' cosi' in `portfolio_builder`). Risposta definitiva a una watch-list ricorrente: **no blend**.

### Confidenza ricalibrata (`modules/trade_proposal.confidence_level`)
- Le soglie assolute 0.45/0.20 rendevano ALTA **irraggiungibile** (max score osservato ~0.36,
  p90~0.19) e quasi tutto BASSA. Nuove soglie hi=0.19 (~p90) / mid=0.13 (~p60), piu' parametri
  opzionali per passare percentili live. Ora: **ALTA 9 / MEDIA 26 / BASSA 45** (prima ~tutto BASSA).
- Portafoglio e schede rigenerati con la confidenza informativa.

---

## Run #9 — 2026-06-25 (modello operativo affidabile: 3 watch-list completate)

Obiettivo: modello operativo **altamente affidabile**. Eseguiti i 3 punti aperti.

### #3 — Backtest sez.7 segmentato sul PORTAFOGLIO selezionato (`backtest_v3.py`)
- Prima segmentava TUTTI i segnali → VECCHIO==NUOVO. Ora filtra al top-quintile selezionato.
- Diagnosi reale: **NUOVO bull** n=215 ret **+2.90%** hit 56.7% **Sharpe 4.58**; bear n=24 −1.24%
  (campione piccolo). VECCHIO bull solo +0.25% hit 43%. → l'edge NUOVO e' reale e **bull-concentrato**
  ⇒ il regime_filter (operare solo TREND_UP) e' la salvaguardia chiave, ora validata.

### #1 — Smart Money come LEVA DI AFFIDABILITA' (test in `sm_validate.reliability()`)
Filtro accumulazione (sm>=.33) sul top-quintile migliora OGNI metrica, monotono:
| selezione (10gg) | n | win% | med% | Sharpe | PF |
|---|---|---|---|---|---|
| base top-quintile | 245 | 56.7 | 1.29 | 1.21 | 2.08 |
| + accumulazione | 193 | **60.1** | **1.64** | **1.55** | **2.61** |
(20gg: accumulazione win 59.6%, med +3.50%, PF 3.30.) → l'accumulazione e' la leva.
- **`portfolio_builder` ora tiered**: accumulazione = **CORE** (piena size); neutro = **SAT**
  (size ridotta ×0.55); distribuzione **esclusa**. Portafoglio: 12 nomi (9 CORE / 3 SAT),
  esposizione 72% (piu' concentrata sul core affidabile). Ranking pesa SM > score.

### #2 — Confidenza su percentili LIVE
- `confidence_level(score, ticker, hi, mid)`: il builder passa hi=p90, mid=p60 della selezione
  corrente. La confidenza in scheda torna informativa (ALTA/MEDIA/BASSA reali, non ~tutto BASSA).

### Onesta' sull'affidabilita'
Il modello e' **piu' affidabile** (filtro accumulazione validato + gate trend + regime filter),
ma le metriche sono **in-sample** (un solo periodo 2025-04→2026-06, prevalentemente bull) e
**DSR 0.794 < 0.95**; l'edge e' bull-concentrato con mediana per-trade modesta. Affidabilita'
reale = trend gate + regime TREND_UP + accumulazione + stop disciplinato su MOLTE operazioni.
Manca un test out-of-sample su un ciclo completo (incl. bear vero).

### Watch list per il prossimo run
- [ ] Out-of-sample / walk-forward su un ciclo che includa un vero bear (oggi pochi dati bear).
- [ ] Tenere DSR>0.95 come obiettivo: ridurre i gradi di liberta' (meno configurazioni testate).
- [ ] Monitorare il regime US (S&P sul filo della SMA50): se rompe, mult → x0.5 (gia' automatico).
- [ ] Integrare `smart_money_signal` come 4° componente in `score_generator` (oggi overlay);
      validarlo prima nel backtest.
- [ ] Ri-girare `backtest_v3.py` col regime corretto (Run #2) e misurare l'edge dello Smart Money.

---

## Run #10 — 2026-06-25 (validazione walk-forward OUT-OF-SAMPLE del modello)

### `walkforward_oos.py` (NUOVO tool) — anchored walk-forward, no lookahead
Modello operativo testato OOS: top-quintile (soglia stimata SOLO sull'IS precedente) +
accumulazione (sm>=0.33) + uscita laddered a target (2,6,10). 4 finestre OOS sequenziali.

| | n | win% | mean% | Sharpe | PF |
|---|---|---|---|---|---|
| IS (in-sample) | 193 | 54.4 | +1.52 | 1.20 | 1.84 |
| **OOS (walk-fwd)** | 108 | **56.5** | **+2.31** | **1.55** | **2.25** |

- **WFE = +1.52** (OOS ≥ IS, ben oltre ~0.5) → l'edge NON e' un artefatto in-sample nel periodo:
  regge (anzi migliora) fuori campione. Per-fold: 3/4 positive (win 50/57/69%); 1 debole
  (win 45%, mediana −3.91%, media +0.49%).

### Limite onesto (ancora aperto)
Periodo unico ~14 mesi **prevalentemente bull**: l'OOS prova la **stabilita' temporale**, NON un
**ciclo completo con bear vero**. In bear l'edge NUOVO si indebolisce (sez.7) → il `regime_filter`
(full size solo in TREND_UP) resta la salvaguardia. DSR 0.794 < 0.95 invariato.

### Stato del modello operativo
Strati: trend gate → regime TREND_UP → top-quintile → accumulazione (CORE/SAT) → stop + target
laddered (2,6,10). In-sample E walk-forward OOS coerenti e positivi nel periodo disponibile.

### Watch list per il prossimo run
- [ ] Con dati bear disponibili: ripetere il walk-forward su un ciclo completo.
- [ ] Tenere DSR>0.95: ridurre i gradi di liberta' (meno configurazioni testate).
- [ ] Monitorare il regime US (S&P sul filo della SMA50): se rompe, mult → x0.5 (automatico).

---

## Run #11 — 2026-06-25 (FATTORI BEAR: test su ciclo completo 2018-2026)

### Dati: storico lungo con bear veri (`fetch_long.py`, NUOVO)
- Scaricato 2018→2026 via Yahoo v8 con prezzi **AGGIUSTATI** (split: NVDA/AMZN ecc.) →
  `data/mib_data_long.csv` (142 ticker, 301k righe; gitignored, riproducibile). Include
  **crash 2020 e bear 2022**.

### Scoperta cruciale: il backtest a 14 mesi era ottimista in modo pericoloso
- Sul ciclo completo la strategia GREZZA (top-quintile, no filtri) crolla:
  **Sharpe 0.18, MaxDD −95.7%**, Spearman negativa. L'edge a 14 mesi (Sharpe 1.89) era in larga
  parte un **artefatto bull**. Regime (sez.7 long): NUOVO bull Sharpe +1.37, **bear −0.48**.

### I fattori bear funzionano (ma non rendono il modello bear-proof) — `bear_analysis.py` (NUOVO)
Ciclo completo, MaxDD = metrica chiave:
| modello | Sharpe | MaxDD |
|---|---|---|
| A) grezzo (no filtro) | 0.18 | −95.7% |
| C) + regime + accumulazione | 0.57 | −66.7% |
| C+stop (modello reale) | 0.75 | −45.7% |
| **D) + trigger rapido SMA20** | **0.83** | **−33.0%** |
- Lo **stop** e il **trigger rapido** sono i fattori che il portfolio_sim grezzo non cattura.
  Insieme portano il MaxDD da −95.7% a −33.0% e lo Sharpe da 0.18 a 0.83.

### Integrato il fattore bear nel modello live (`regime_filter.py`)
- Aggiunto trigger **px>SMA20**: nuovo stato **PULLBACK (x0.5)** quando il prezzo perde la SMA20
  pur restando in trend lungo → risk-off precoce che il filtro lento SMA50/200 mancava.
- **Effetto live immediato**: **US → PULLBACK x0.5** (S&P sotto SMA20); IT/FR TREND_UP. Il
  portafoglio dimezza l'esposizione USA (esposizione totale 72%→62%) in automatico.

### Onesta'
Anche con TUTTI i fattori bear, sul ciclo completo: **MaxDD −33%, Sharpe 0.83** — il modello
resta **bull-favored**: i fattori bear **riducono il rischio di rovina, non lo eliminano**.
DSR ancora <0.95. Per un vero salto servirebbe una logica long/short o hedge, non solo risk-off.

### Watch list per il prossimo run
- [ ] Valutare un overlay di hedge (es. ridurre a 0 o coprire l'indice) in TREND_DOWN conclamato.
- [ ] Re-tarare i target/soglie sul ciclo COMPLETO (finora tarati su periodo bull).
- [ ] DSR>0.95: ridurre i gradi di liberta'.

---

## Run #12 — 2026-06-25 (overlay di rischio: go-flat + index hedge sul ciclo completo)

### `hedge_overlay.py` (NUOVO) — simulazione giornaliera (M2M) overlay, 2018-2026
| overlay | MaxDD | Sharpe | CAGR |
|---|---|---|---|
| BASE (modello, no overlay) | −13.8% | 0.99 | 14.3% |
| A) GO-FLAT in TREND_DOWN | −13.8% | 0.99 | 14.3% |
| B1) HEDGE indice h=1.0 | −9.1% | 2.55 | 41.3% |
| B2) HEDGE indice h=0.5 | −10.1% | 1.86 | 27.2% |

### Letture oneste (cruciali)
- **GO-FLAT e' REDUNDANTE**: A == BASE. Il filtro fast-regime tiene gia' il modello FUORI dai
  downtrend (non ci sono posizioni da chiudere) → e' per questo che il MaxDD e' contenuto.
  Il miglior overlay di rischio era gia' nel gate d'ingresso. (BASE DD −13.8% qui < −33% del
  Run #11 perche' qui il regime-switch e' globale ^GSPC, piu' protettivo.)
- **L'HEDGE riduce il drawdown** (−13.8%→−9/−10%) MA il boost di rendimento (Sharpe 2.55,
  CAGR 41%) e' **sample-specific** (short dell'indice durante i crash 2020/2022): in mercati
  laterali l'hedge fa **whipsaw e COSTA**. Va trattato come **ASSICURAZIONE, non alpha**.

### Operativizzazione in `portfolio_builder.py`
- **DEFAULT `include_pullback=False` = GO-FLAT** (piu' affidabile): si opera solo nei mercati
  TREND_UP. **Live: US in PULLBACK → escluso**; portafoglio IT/FR, esposizione 62%, hedge non
  necessario ("OVERLAY DI RISCHIO: nessuno").
- **`include_pullback=True`**: si resta nei mercati PULLBACK a META' size (regime_mult 0.5) e il
  report stampa la **raccomandazione di hedge** (es. US long 5196€ → short SPY ~2598€, h=0.5).

### Conclusione overlay
Per l'affidabilita' primaria, il DEFAULT e' **go-flat** (validato, DD piu' basso). L'hedge e'
disponibile come overlay opzionale per chi vuole mantenere diversificazione in PULLBACK, con
l'avvertenza che e' un costo-assicurazione, non un generatore di rendimento.

### Watch list per il prossimo run
- [ ] Re-tarare target/soglie sul ciclo COMPLETO (finora su periodo bull) e mirare DSR>0.95.
- [ ] Valutare hedge per-mercato (CAC/FTSEMIB) oltre a S&P, se si usa include_pullback.

---

## Run #13 — 2026-06-26 (fondamentali Point-In-Time da SEC EDGAR: raccolta, backtest, integrazione)

**Sblocco fonte.** L'utente ha aggiunto `www.sec.gov` e `data.sec.gov` all'allowlist di
egress. Verificato raggiungibile → costruita una pipeline di fondamentali **point-in-time**
(con data di FILING, non di periodo → zero lookahead) dai dati XBRL ufficiali SEC.

### #1 — Raccolta (`fundamentals_pit.py`, NUOVO)
- Fonte: `data.sec.gov/api/xbrl/companyfacts/CIK*.json` (gratuita, no API key, UA con email).
- 45/45 ticker USA della watchlist, da 10-K/10-Q: revenue, net income, EPS, gross/operating
  income, balance sheet completo, OCF; metriche derivate (net/gross/OCF margin, current ratio,
  cash/LT-debt, ROE, D/E, EPS growth YoY e CAGR 5Y).
- Output: `data/fundamentals_pit.csv` (snapshot) + `data/fundamentals_pit_history.csv`
  (2821 osservazioni storiche per backtest). Rispetta rate limit SEC (10 req/s).
- Robustezza: retry+backoff, JSON grandi (GOOGL/JNJ ~4MB), numeri complessi (INTC) gestiti.

### #2 — Backtest PIT (`backtest_v3.py`, sez.9 NUOVA)
- Ogni segnale associato ai fondamentali **as-of filed <= data segnale** (`pit_lookup`).
- `pit_quality_score`: 5 criteri soft (nm>0, nm>=10%, current>=1, ocf>0, roe>=10%), normalizzato.
- Risultato sul top-quintile (hold 10gg): **PIT>=0.60 → ret +3.30% / Sharpe 1.50** (vs base
  +2.49% / 1.21); **net margin>=10% → ret +4.86% / win 60%**. Il filtro fondamentale MIGLIORA.
  Caveat: campioni piccoli (n=35-57), in-sample; usare come leva, non come veto rigido.

### #3 — Integrazione live (`portfolio_builder.py` + `modules/fundamentals.py`)
- **`modules/fundamentals.py`**: SEC EDGAR diventa **fonte primaria USA** (Finnhub/yfinance
  fallback; analisti/earnings ancora da Finnhub). EU invariato (yfinance).
- **`portfolio_builder.py`**: leva di size `fq_mult` da `_fundamental_tier` (Q+ piena size,
  Q/Q- ridotta; USA only, EU=`n/d` neutro). Colonna FQ in tabella e scheda.
- `pit_quality_score` **centralizzato** in `modules/fundamentals.py`, importato da backtest e
  builder (una sola definizione, no drift). Coerente con Lezione #8/#9: filtro CONDIZIONATO /
  leva di size, NON blend lineare nello score; e Lezione #6: scala la size, non escludere.
- **Effetto live (oggi)**: US in PULLBACK → go-flat esclude i nomi USA → portafoglio tutto EU
  (`n/d`), leva inattiva su questa selezione. Verificato su `include_pullback=True`: la leva
  morde (AMAT/GE Q+ piena; **INTC fq=0.40 → Q → size ×0.85**, unico non profittevole tagliato).

### Watch list per il prossimo run
- [ ] Validare il filtro PIT su un ciclo COMPLETO con bear (oggi in-sample bull, n piccolo).
- [ ] Estendere i fondamentali PIT all'EU (SEC non copre: serve fonte ESEF/altra per .MI/.PA).
- [ ] Re-tarare target/soglie sul ciclo completo e mirare DSR>0.95.

---

## Run #14 — 2026-06-26 (validazione filtro PIT su ciclo completo: e' una leva DIFENSIVA)

**Obiettivo:** chiudere la watch-list di Run #13 — il filtro qualita' fondamentale regge su un
ciclo con bear, o e' (come lo score) bull-concentrato?

### Dati
- Rigenerato `data/mib_data_long.csv` (2018-2026, prezzi aggiustati, 301k righe, 142 ticker)
  via `fetch_long.py` (Yahoo v8 ancora in allowlist). PIT history copre 2009-2026 (45 ticker USA).

### `pit_validate.py` (NUOVO tool) — segmentazione per regime
- Segnali score NUOVO sul ciclo completo; fondamentali PIT con filed <= data segnale; regime
  bull/bear via ^GSPC/SMA200; confronto top-quintile USA base vs +PIT>=0.60, DENTRO ogni regime.

### SCOPERTA: la qualita' fondamentale e' una leva DIFENSIVA, non un miglioramento universale
| regime | filtro PIT>=0.60 vs base (10gg / 20gg) | verdetto |
|---|---|---|
| BULL | ret -0.28% / -0.50%, Sharpe -0.16 / -0.11 | **PEGGIORA** |
| BEAR | ret +0.63% / +0.82%, win +3.7% / +3.5%, Sharpe +0.48 / +0.34 | **AIUTA** |
- Spearman pit_quality↔ritorno: bull ~0 (-0.02), **bear +0.16/+0.19**. Flight-to-quality nel
  risk-off; nel momentum bull anche i nomi a qualita' bassa corrono -> penalizzarli costa.
- **Il +3.30% del backtest sez.9 era un artefatto del solo sotto-periodo bull a 14 mesi.** Sul
  ciclo completo PIT>=0.60 sta SOTTO il base USA (0.70 vs 0.91 a 10gg): senza segmentare, fuorviante.
- Anomalia onesta: `net margin < 0` (in perdita) ha i ritorni piu' alti (n=61, +4.23%/+8.66%,
  PF 3-5) = effetto high-beta/turnaround dentro il momentum, NON qualita'. Alta varianza, rischioso.

### Correzione dell'integrazione (Run #13 era mis-specificato)
- `portfolio_builder._fundamental_tier` ora **regime-conditional**: la leva morde SOLO nei mercati
  NON in TREND_UP (`defensive=True`); in TREND_UP resta NEUTRA (label informativo, size piena).
  Coerente con la validazione: non penalizzare la qualita' bassa quando il momentum la premia.
- Verificato: INTC (in perdita) TREND_UP -> x1.0 (neutro), PULLBACK -> x0.85 (difensivo morde);
  i Q+ sempre pieni. Nel default go-flat (solo TREND_UP) la leva e' di fatto neutra by design;
  si attiva con include_pullback=True (quando si sceglie di restare in mercati risk-off).

### Watch list per il prossimo run
- [ ] Campione bear ancora piccolo (n=168 top-quintile USA): riconfermare quando ci saranno piu' dati.
- [ ] Estendere i fondamentali PIT all'EU (SEC non copre: serve ESEF/altra fonte per .MI/.PA).
- [ ] Re-tarare target/soglie sul ciclo completo e mirare DSR>0.95.

---

## Run #15 — 2026-06-26 (estensione universo USA: screener "unicorni" da SEC EDGAR)

**Domanda dell'utente:** si possono estendere i ticker USA per individuare potenziali "unicorni"?
**Risposta:** si', quasi gratis — la SEC copre TUTTI i filer USA (company_tickers.json, ~10k),
quindi i fondamentali costano solo rate-limit, non un piano API.

### `unicorn_screener.py` (NUOVO tool)
- Universo candidati: ~52 growth USA mid/small-cap fuori dai 45 mega-cap (cloud/AI/cyber/fintech/
  consumer/biotech/semis), estendibile. Foreign issuer (20-F: ARM, NU) saltati senza errore.
- Profilo "unicorno" da SEC: crescita ricavi (CAGR 3Y + YoY), gross margin scalabile e in
  miglioramento (leva operativa), dimensione contenuta (spazio di crescita), bilancio. Score 0-100.
- **Estrazione annuale robusta** (lezione di data-hygiene): il campo `fy` di companyfacts e' l'anno
  del FILING, non del periodo -> si usano `start`/`end`, durata ~365gg, chiave su anno di `end`,
  dedup per filing recente, priorita' tra concetti. Fix: PODD GM da 184% (bug) a 72% (reale);
  recuperati CRWD/UBER/HOOD/XYZ che usavano concetti revenue non standard.

### Top candidati (profilo fondamentale, NON validato sui ritorni)
PLTR 88.8 · ELF 80.9 · CELH 79.1 · BILL 77.4 · S 75.3 · PODD 69.0 · GTLB 68.0 · DDOG 65.5 ·
UPST 65.0 · ZS 64.8. Sanity: PLTR in cima (iper-growth profittevole), giganti come UBER
declassati (rev $52B -> nessun bonus dimensione). Output: `data/unicorn_candidates.csv`.

### Onesta' (cruciale)
- E' uno screener di SCOPERTA, NON un segnale di alpha: nessuna prova statistica che il profilo
  predica i ritorni. La validazione Run #14 avverte: i nomi high-growth/non profittevoli (S, RIVN,
  LCID, SNOW) sono ESPLOSIVI ma HIGH-BETA (crollano per primi in bear). Ogni candidato va passato
  dal gate momentum + regime + stop del modello prima di operare. Lista da indagare, non da eseguire.
- Per integrarli davvero nel modello servirebbe: prezzi nel pipeline (gia' fattibile via Yahoo v8)
  + backtest del profilo come fattore. Non fatto: per ora resta tool di scoperta separato.

### Watch list per il prossimo run
- [ ] Se si vuole operare gli unicorni: aggiungere i top al `TICKERS` di fetch_data e backtestare.
- [ ] Estendere i fondamentali PIT all'EU (SEC non copre: serve ESEF/altra fonte per .MI/.PA).
- [ ] Re-tarare target/soglie sul ciclo completo e mirare DSR>0.95.

---

## Run #16 — 2026-06-26 (fondamentali EU best-effort + riconferma bear con piu' dati)

**Obiettivo:** chiudere le due watch-list aperte: (1) estendere i fondamentali all'EU; (2)
riconfermare il filtro PIT difensivo (Run #14) su un campione bear piu' ampio.

### #1 — `fundamentals_eu.py` (NUOVO): copertura EU best-effort
- Limite strutturale confermato: per l'EU NON esiste un equivalente gratuito di data.sec.gov
  (ESEF non ha API aggregata aperta). Unico ripiego praticabile: endpoint pubblico Yahoo
  fundamentals-timeseries (host query1, in allowlist) — verificato funzionante su .MI/.PA/.AS.
- **NON e' PIT vero** (da dichiarare sempre): `asOfDate` = fine periodo, valori RESTATED. Per il
  backtest si approssima la disponibilita' = fine periodo + **120gg** (lag regolatorio EU,
  Transparency Directive) per evitare lookahead. Fonte `yahoo_ts`, form `AR` (vs SEC PIT vero).
- Risultato: **79/80 ticker EU** (solo BPSO.MI ko), 317 osservazioni (~4 anni, limite Yahoo ->
  copre il bear 2022 ma non 2018/2020). Metriche sensate: RMS nm 28%/ROE 24%, RNO/STLA in perdita,
  banche current_ratio N/A. Output: `data/fundamentals_eu.csv` + `data/fundamentals_eu_history.csv`.
- Wiring: `backtest_v3.load_pit` fonde la storia EU (schema identico); `portfolio_builder` fonde
  lo snapshot EU -> i nomi EU ora hanno un fq tier reale (Q+/Q/Q-) invece di `n/d`. La leva resta
  DIFENSIVA: in TREND_UP neutra (label informativo), morde solo in PULLBACK (RNO->x0.85, STLA->x0.70).

### #2 — Riconferma del filtro difensivo con piu' dati (124 ticker con fondamentali, bear n 168->276)
| | Run #14 (US-only) | Run #16 (US+EU) |
|---|---|---|
| BEAR 10gg (PIT>=0.60 vs base) | +0.63% / Sharpe +0.48 | **+0.18% / +0.17** (aiuta) |
| BEAR 20gg | +0.82% / +0.34 | **+0.09% / +0.04** (aiuta) |
| BULL 10/20gg | peggiora | neutro / peggiora |
- **Il SEGNO regge** (qualita' = leva difensiva: aiuta in bear, neutra/contro in bull) -> l'integrazione
  regime-conditional e' confermata nella direzione. **Ma le magnitudini si ridimensionano molto**: la
  stima US-only era ottimistica (classico effetto L#11). Spearman ~0 in entrambi i regimi -> e' un
  debole effetto-SOGLIA, non un predittore monotono. Non sovrastimare; tenere come leva prudente.
- Caveat: i +108 segnali bear aggiunti sono in larga parte EU 2022 (restated/lag-approx, piu' rumorosi),
  un solo episodio bear. La riconferma rafforza il segno, non promuove il fattore a edge forte.

### Watch list per il prossimo run
- [ ] Bear ancora concentrato (2020 US + 2022): servono piu' episodi per stringere le stime.
- [ ] EU solo ~4 anni (limite Yahoo): per backtest PIT-EU piu' profondo serve fonte ESEF storica.
- [ ] Re-tarare target/soglie sul ciclo completo e mirare DSR>0.95.

---

## Run #17 — 2026-06-26 (EU PIT profondo: bloccato; integrazione unicorni: backtest del profilo)

Due punti in ordine.

### #1 — EU PIT piu' profondo: NON ottenibile ora (limite strutturale + allowlist)
- Fonte naturale per il PIT-EU vero: `filings.xbrl.org` (repository ESEF di XBRL International, con
  API JSON). **Bloccato dall'allowlist di egress** (ProxyError al CONNECT, stesso pattern L#3/#4).
- Limite STRUTTURALE oltre l'accesso: il mandato ESEF parte da **FY2020** -> la storia EU pre-2020
  NON esiste in forma XBRL standardizzata in nessuna fonte gratuita. Quindi anche sbloccando l'host
  si otterrebbe al massimo 2020+ (true PIT, meglio del lag-approx Yahoo, ma non piu' profondo).
- Decisione: non si fabbrica. Leva = aggiungere `filings.xbrl.org` all'allowlist (per true-PIT EU
  2020+); profondita' pre-2020 EU resta strutturalmente impossibile. Resta Yahoo (~4 anni) come base.

### #2 — `unicorn_validate.py` (NUOVO): gli unicorni sono tradeable nel modello?
Prezzi 2018-2026 (Yahoo v8, 33 candidati score>=50) + score momentum validato + crescita ricavi
**POINT-IN-TIME da SEC** (filed<=data segnale) + segmentazione per regime.

**Risultati (top-quintile, netto):**
| selezione (10gg / 20gg) | mean% | Sharpe |
|---|---|---|
| unicorni top-quintile | +0.34 / +1.05 | 0.15 / 0.22 |
| mega-cap top-quintile (confronto) | +0.89 / +2.01 | 0.64 / 0.68 |

- **Buttare gli unicorni nell'universo DILUISCE il modello** (Sharpe 0.15-0.22 vs 0.64-0.68): sono
  high-beta, piu' rumorosi. Un dump indiscriminato peggiora l'edge.
- **Il gate di CRESCITA PIT e' il separatore** (dentro il top-quintile):
  - BULL: iper-crescita (rev YoY>=25%) +0.60%/+1.58% vs crescita decelerata (<25%) **-0.68%/+0.06%**
    -> i nomi a crescita svanita sono **trappole momentum** (ritorno bull negativo).
  - BEAR: iper-crescita +2.68%/+4.37% (win 56-64%) vs bassa +1.34%/+0.51%. Crescita premiata di piu'
    nel risk-off (Spearman crescita↔ritorno bear +0.12/+0.20 vs bull +0.05).
- **Verdetto**: NON aggiungere gli unicorni al `TICKERS` operativo (diluirebbe il modello validato).
  Trattarli come **SLEEVE high-beta GATED**: un segnale momentum su un unicorno vale solo se il nome
  e' ANCORA in iper-crescita (rev YoY>=25% PIT); size ridotta, dentro il gate di regime.

### Artefatto operativo: `unicorn_validate.live_sleeve()` -> `data/unicorn_sleeve.csv`
- Applica il gate ai dati correnti. **Oggi: 0 nomi passano** — i leader di momentum (FTNT/PANW/CRWD)
  hanno crescita decelerata (<25%, la trappola), gli iper-cresciti (DDOG 28%/AFRM 39%/NET 30%) non
  sono in top-quintile di momentum ora. "Nessun unicorno da comprare oggi" e' un risultato onesto
  (L#5), non un bug: il gate rifiuta sia le trappole sia i growth senza momentum.
- Report completo: `data/unicorn_validate.txt`. Prezzi in `data/mib_data_unicorns.csv` (gitignored).

### Watch list per il prossimo run
- [ ] Sleeve unicorni: ricontrollare quando un iper-grower (rev YoY>=25%) entra in momentum top-quintile.
- [ ] Se si vuole operare lo sleeve: wiring opzionale in portfolio_builder come satellite a size ridotta.
- [ ] EU true-PIT 2020+: possibile solo con `filings.xbrl.org` in allowlist.
- [ ] Re-tarare target/soglie sul ciclo completo e mirare DSR>0.95.

---

## Run #18 — 2026-06-26 (GOAL profit-seeker: sleeve unicorni operativo + hook ESEF pronto)

Obiettivo impostato: rendere il modello operativo un cercatore di profitto. Due wiring richiesti.

### (a) Sleeve high-beta unicorni nel modello operativo (`portfolio_builder._unicorn_satellite`)
- Consuma `data/unicorn_sleeve.csv` (gate crescita PIT da unicorn_validate) + `data/mib_data_unicorns.csv`
  (prezzi) — nessuna chiamata SEC nel hot path. Gate: iper-crescita (rev YoY>=25%) AND momentum>=p50
  (soglia core) AND regime USA operabile AND non distribuzione AND volume affidabile.
- Satellite SEPARATO dal core (gli unicorni come gruppo diluiscono, Run #17): pos_cap 5% (meta'),
  size_mult 0.5 (high-beta), esposizione sleeve <=15% capitale, max 3 nomi. Default `include_unicorns=True`.
- Verificato: in go-flat (US PULLBACK) sleeve VUOTO (disciplina di regime); con include_pullback=True
  entra **DDOG (rev +28%) + AFRM (+39%)** a size ridotta (~2% esposizione). Sezione dedicata in PORTFOLIO.txt.

### (b) Hook ESEF pronto-ma-gated (`fundamentals_eu_esef.py`)
- `filings.xbrl.org` ancora BLOCCATO (allowlist). Scritto hook pronto (pattern "codice pronto, leva =
  allowlist"): `probe()` / `esef_filing_dates(lei)` per le DATE DI FILING REALI (rimpiazzerebbero il
  lag +120gg approssimato di fundamentals_eu, rendendo il PIT-EU 2020+ esatto). Degrada a None con
  messaggio chiaro; parsing difensivo NON testato (host bloccato). Limite strutturale: ESEF solo FY2020+.

### Watch list
- [ ] Quando US torna TREND_UP: lo sleeve unicorni entra a piena (mezza) size — monitorare DDOG/AFRM/ANET.
- [ ] Attivare `fundamentals_eu_esef` aggiungendo `filings.xbrl.org` all'allowlist (true-PIT EU 2020+).
- [ ] Re-tarare target/soglie sul ciclo completo e mirare DSR>0.95.

---

## Run #19 — 2026-06-26 (4 note operative: nomi, automiglioramento, skill, grafici)

Quattro richieste dell'utente, tutte chiuse + auto-review.

### #1 — Nomi azienda (`company_names.py`)
- Mappa ticker->nome: SEC entity (USA) + Yahoo longName (EU), cache `data/ticker_names.csv` (143
  ticker). Wired in `execution_sheet` (colonna AZIENDA): i ticker ora sono cercabili (Terna,
  Carrefour, Intesa Sanpaolo, Engie, Poste, Recordati, STMicroelectronics, Saipem, Air Liquide...).

### #4 — Analisi grafica reintegrata (`charts.py`)
- Trovato `charts.py` (candlestick + SMA/BB/RSI/MACD/OBV via mplfinance). **Bug Lezione #5**: leggeva
  da `raw.githubusercontent/main` -> corretto a LETTURA LOCALE. Nuova `charts_for_portfolio()` grafica
  i SOLI titoli selezionati col nome azienda nel titolo. 12 grafici/sessione in `charts/` (PNG gitignored).

### #2 — Ciclo di automiglioramento (`self_improve.py`)
- Auto-audit post-raccomandazione: freschezza dati, disciplina rischio, concentrazione (mercato E
  CONTINENTE), qualita' nomi, assunzioni non blindate, copertura grafici. Scrive `data/IMPROVEMENT_LOG.txt`
  + sceglie la "prossima mossa" a impatto piu' alto. Sessione oggi: book 100% EU flaggato (US PULLBACK),
  frontiera = DSR<0.95.

### #3 — Skill che migliorano le skill
- `self_improve` mappa OGNI criticita' -> skill che la risolve (/code-review, /simplify, /verify,
  /security-review, metodo statistico). E **eseguito davvero `/code-review`** sul codice nuovo: 5 fix
  applicati (il piu' importante: `execution_sheet` non perde piu' silenziosamente una posizione dal
  foglio rischio; parsing per-scheda con campi indipendenti + segnalazione schede incomplete).

### Loop operativo completo della sessione (profit-seeker)
`fetch_data -> score_generator -> regime_filter -> portfolio_builder -> execution_sheet -> charts -> self_improve`
Ogni sessione: genera il piano + foglio rischio + grafici + si auto-critica e indica il prossimo miglioramento.

### Watch list
- [ ] Prossima mossa dell'auto-audit: consolidare DSR>0.95 (ridurre gradi di liberta', walk-forward ciclo completo).
- [ ] Quando US torna TREND_UP: sleeve unicorni attivo (DDOG/AFRM/ANET).
- [ ] `filings.xbrl.org` in allowlist per true-PIT EU 2020+.

---

## Run #20 — 2026-06-26 (consolidamento robustezza: DSR del modello OPERATIVO sul ciclo completo)

Prossima mossa indicata dall'auto-audit: consolidare la robustezza (DSR>0.95). Eseguita con analisi
precisa, evitando di "gamare" il numero.

### Il problema misurato
- `backtest_v3` sez.2-3 calcola Sharpe/DSR sul top-quintile **GREZZO** (no gate regime, no
  accumulazione, no stop): sul ciclo 2018-2026 da' Sharpe **0.17 / MaxDD -95.7%** (conferma L#11).
  Ma NON e' cio' che si opera. Misurare il segnale grezzo invece del modello = diagnosi sbagliata.

### `robustness_consolidate.py` (NUOVO) — DSR del modello che si OPERA davvero
- Riusa la serie M2M giornaliera del modello operativo (go-flat regime UP + top-quintile +
  accumulazione, da hedge_overlay) sul ciclo completo: **1022 giorni op., 2164 trade, 2019-2026**.
- Pannello: **Sharpe 1.00 | MaxDD -13.8% | CAGR +14.4% | PSR 0.977 | MinTRL 2.8 anni**.
- DSR a conteggi-trial multipli (anti-gaming, si guarda il N piu' severo): **0.924 (N=6) ->
  0.855 (N=15)** -> NON supera 0.95.
- Output: `data/ROBUSTNESS_PANEL.txt`.

### Verdetto onesto (chiude la watch-list DSR)
- L'edge e' **REALE** (PSR 0.98 = Sharpe vero quasi certamente >0; Sharpe 1.0 / MaxDD -13.8% su un
  ciclo CON bear 2020/2022) ma **non blindato** a multiple-testing (DSR<0.95). Non si forza il numero.
- Implicazione operativa (gia' nel modello): **size MODERATA, mai leverage**; il profitto si protegge
  col **gate di regime + STOP**, non con un Sharpe alto. Aggiornati header di `portfolio_builder` e la
  nota di `self_improve` perche' citino queste metriche REALISTICHE di ciclo completo (non le
  bull-gonfiate 14-mesi: Sharpe 1.89 era artefatto di periodo).

### Watch list
- [ ] DSR>0.95 non raggiungibile onestamente con i dati attuali: rivedere solo se arriva piu' storia
      o si riducono i gradi di liberta' del modello senza intaccare l'edge. Per ora: chiuso, size moderata.
- [ ] Quando US torna TREND_UP: sleeve unicorni attivo (DDOG/AFRM/ANET).
- [ ] `filings.xbrl.org` in allowlist per true-PIT EU 2020+.

---

## Run #21 — 2026-06-26 (fix score compression: flow=0 bug + auto-audit migliorato)

Prossima mossa indicata dall'auto-audit Run #20: "6/12 nomi a confidenza BASSA → score compresso".

### Bug trovato e corretto: `score_flow` trattava "no data" come "segnale negativo"

**Causa radice**: `score_flow_13f`, `_insider`, `_short` ritornavano **0.0** sia per "nessun dato
disponibile" (EU, small cap senza copertura 13F/insider) sia per "dato trovato, valore neutro".
Poi `combine_signals = mean(technical, flow=0)` **dimezzava lo score** di ogni ticker senza
copertura flow — la maggior parte dell'universo EU + molti US.

**Fix**: le sotto-funzioni ora ritornano `None` quando non trovano dati. `score_flow` aggrega
solo le componenti con dato reale; `None` se nessuna fonte copre il ticker. `apply_decay` passa
`None` inalterato. `combine_signals` (gia' predisposto) ignora i `None` e usa solo il tecnico.

**Effetto sulla distribuzione**:
| metrica | PRIMA | DOPO |
|---|---|---|
| mediana score | 0.116 | **0.200** |
| IQR | 0.086 | **0.193** (+124%) |
| p90 | 0.190 | **0.356** |
| max | 0.356 | **0.599** |

### Effetto sul portafoglio
- **ENTRATI**: SRG.MI (Snam, sm +0.82 CORE) e BMPS.MI (Monte Paschi, sm +0.69 CORE) — avevano
  score dimezzato sotto p50, ora sopra → selezionati per la forte accumulazione.
- **USCITI**: REC.MI e FBK.MI — SAT con bassa convinzione, spinti fuori dal cap 12 dai nuovi CORE.
- **Composizione**: da 7 CORE / 5 SAT a **9 CORE / 3 SAT** (piu' concentrato sulla parte affidabile).
- **Rischio**: 2.61% a stop (OK <6%), R/R T2 3.42.

### Auto-audit migliorato
- `self_improve.py` ora distingue BASSA-per-illiquidita' (strutturale, size gia' ridotta) da
  BASSA-per-score (actionable). Risultato: 6/12 BASSA = **4 illiquidi** (SRG.MI, TRN.MI, BMPS.MI,
  AZM.MI: costi alti, ma selezionati per accumulation → BASSA e' un avviso corretto) + **2 per score**
  (CA.PA 0.242, TEN.MI 0.241 marginalmente sotto p60=0.253). La diagnosi "score compresso" ora punta
  al problema reale, non a un artefatto illiquidita'.

### Cap settoriale (Run #21b)
- **Analisi correlazione**: Snam-Terna 0.82, Intesa-Azimut 0.76, Tenaris-Saipem 0.62. Il book
  pre-cap aveva 5/12 utility = 42% → diversificazione illusoria su 3 cluster.
- **`portfolio_builder`**: aggiunto `SECTOR` map + `MAX_PER_SECTOR=3`. Risultato: 7 settori
  distinti, max 25% per settore. Da 5 utility → 3 (SRG.MI, VIE.PA, TRN.MI); ENGI.PA (4a utility)
  sacrificata per diversificazione, REC.MI e FBK.MI entrano come settori sotto-rappresentati.
- **`self_improve`**: nuovo check concentrazione settoriale (soglia >35%).
- **Trade-off**: ENGI.PA era CORE ad alta convinzione (score 0.355, sm 0.53) ma utility #4. La
  perdita di rendimento atteso e' compensata dal minor rischio di cluster. Mercato: 10/12 IT (FR ha
  molti nomi in distribuzione → bloccati dal filtro SM, strutturalmente corretto).
- Esposizione: 56%, rischio a stop 2.30%, R/R T2 3.48. Composizione: 8 CORE / 4 SAT.

### Watch list
- [ ] 10/12 IT: concentrazione mercato strutturale (FR in distribuzione). Monitorare.
- [ ] Quando US torna TREND_UP: sleeve unicorni attivo + nomi US entrano.
- [ ] `filings.xbrl.org` in allowlist per true-PIT EU 2020+.

## Run #22 — 2026-06-26 (score_technical ↔ score_new alignment)

**Obiettivo:** allineare la funzione di scoring live (`score_technical`) a quella validata
nel backtest (`score_new` di `backtest_v3.py`), eliminando la divergenza che faceva
generare ranking diversi tra live e backtest.

### Cosa ho fatto

1. **Riscritto `score_technical()`** — identica logica a `score_new`:
   - Breakout (+0.55 se price > max(high) ultimi 20gg + trend_up)
   - ADX threshold (+0.35 se >=40, +0.15 se >=25, entrambi con trend_up)
   - Momentum 3 mesi (0.15 * tanh(mom3m/30))
   - RSI penalty (-0.20 se >75 e no breakout)
   - Gate: price>SMA200 AND SMA50>SMA200 (altrimenti -0.3)

2. **Aggiunto breakout e mom3m a `calculate_technical_indicators()`**:
   - `rh20 = h.iloc[-21:-1].max()` — range high 20gg escluso oggi
   - `breakout = bool(c.iloc[-1] > rh20)` — breakout classico
   - `mom3m = (c[-1]/c[-63] - 1) * 100` — momentum 3 mesi (allineato backtest)

3. **Esclusi indici e ETF dal scoring** (`NON_EQUITY`):
   - Indici: FTSEMIB.MI, ^FCHI, ^STOXX50E, ^GSPC, ^NDX, ^VIX
   - ETF settoriali: SPY, XLF, XLE, XLK, XLV, XLY, XLP, XLU, XLI, XLB, XLRE, XLC
   - Questi servono per regime/rotazione, non sono candidati operativi.

4. **Corretto settore CS.PA**: era mappato "Banca" ma CS.PA = AXA SA (Assicuraz, non banca).
   Fix: CS.PA → "Assicuraz". Ha liberato un posto Banca, ISP.MI (sm +0.62 CORE) entra.

5. **Aggiunti settori mancanti**: MB.MI=Banca, TIT.MI=Telecom, AC.PA=Hospitality
   (sia in `portfolio_builder.py` che in `self_improve.py`).

### Risultato

**Score distribution** (66 equity-only candidati):
- min=-0.425  p25=0.009  **p50=0.075**  p75=0.273  max=0.713
- IQR=0.264 (distribuzione BIMODALE: breakout ≥0.55, non-breakout <0.15)

**Portfolio** (9 nomi, 7 settori distinti, 55% esposizione):

| Ticker   | Nome                 | Score | SM    | Ruolo | Settore     |
|----------|----------------------|-------|-------|-------|-------------|
| CS.PA    | AXA SA               | 0.713 | +0.73 | CORE  | Assicuraz   |
| BNP.PA   | BNP Paribas          | 0.611 | +0.59 | CORE  | Banca       |
| BMPS.MI  | Banca MPS            | 0.268 | +0.69 | CORE  | Banca       |
| ENEL.MI  | Enel                 | 0.555 | +0.30 | SAT   | Utility     |
| PST.MI   | Poste Italiane       | 0.451 | +0.38 | CORE  | Servizi     |
| ISP.MI   | Intesa Sanpaolo      | 0.078 | +0.62 | CORE  | Banca       |
| AC.PA    | Accor                | 0.612 | +0.13 | SAT   | Hospitality |
| TIT.MI   | Telecom Italia       | 0.439 | +0.05 | SAT   | Telecom     |
| STMMI.MI | STMicroelectronics   | 0.280 | +0.14 | SAT   | Tech        |

Guadagno atteso: T1 +2.6% / T2 +6.9% / T3 +11.7%. Rischio: 55% esposto, stop disciplinato.

### Differenze chiave vs pre-allineamento
- **Scoring bimodale**: breakout names (score ≥0.55) separati nettamente dai non-breakout.
  Questo e' corretto: nel backtest, il breakout (+0.55) e' il driver dominante dell'edge.
- **8→9 nomi** (dopo fix CS.PA settore): meno nomi del precedente 12 perche' la soglia
  breakout e' selettiva. Esposizione 55% vs 56% — il modello non forza il fully invested.
- **5 CORE / 4 SAT**: bilanciato. CS.PA e BNP.PA sono i CORE a piu' alta convinzione.
- **US esclusi** (PULLBACK go-flat): corretto. US names (UNH 0.423, LLY 0.414) sarebbero
  ben scorati ma il regime le blocca.

### Auto-audit
- Severita' massima: BASSA (grafici mancanti). Nessuna criticita' ALTA o MEDIA.
- Concentrazione area EU 100%: dichiarata nel piano (US in PULLBACK), hedge opzionale.
- Edge reale (PSR 0.98), DSR<0.95: size moderata confermata.

### Watch list
- [ ] Quando US torna TREND_UP: UNH (0.846 tecnico), LLY (0.827), GOOGL (0.097+flow) entrano.
- [ ] CS.PA RSI 93.2: breakout legittimo ma estremo. Monitorare per reversal post-breakout.
- [ ] BMPS.MI RSI 88.8: stessa nota. Lo stop protegge.
- [ ] `filings.xbrl.org` in allowlist per true-PIT EU 2020+.

---

## Run #23 — 2026-06-29 (loop operativo: diario datato + verifica path-based + sub-agent audit)

**Obiettivo:** trasformare l'analisi ad-hoc in un **loop giornaliero auto-verificante**.
Trigger: riaprendo la sessione dopo 3 giorni, i prezzi erano vecchi e per verificare le
raccomandazioni precedenti ho dovuto **ricostruirle a mano** (memoria + CSV vecchio). Manca
una memory spine: PORTFOLIO.txt viene sovrascritto a ogni run.

### Cosa ho fatto

1. **`journal.py`** — diario datato dei pick. Congela ogni piano operativo in
   `data/journal/<asof>.json` (ticker, nome, score, ruolo, mercato, regime, entry/stop/T1-T3
   assoluti). Backfillato `2026-06-26.json` (9 pick) da git per avere uno storico reale.

2. **`verify_picks.py`** — verifica **path-based** (max/min giornalieri, non solo chiusura):
   per ogni pick del giorno prima rileva stop toccati intraday, target raggiunti, ordine
   cronologico, drift, MAE/MFE, e **cambio di regime** del mercato del titolo. Output
   `data/VERIFICATION.txt` + `verification.json` (input per il sub-agent auditor).

3. **`daily_loop.py`** — orchestratore in 2 fasi separate da un handoff all'agente:
   - `verify`: fetch → regime → verify_picks (poi sub-agent auditor: errori → cause → fix)
   - `generate`: score → portfolio → self_improve → charts → journal snapshot

4. **`LOOP.md`** — spec del loop, istanzia il pattern `daily-triage` di `loopengineering`.
   Tabella esplicita di dove serve un sub-agent: **solo Fase 2 (audit)**, per indipendenza
   da chi genera i pick; verifica/fix/generazione restano nell'agente principale.

5. **Auto-snapshot in `portfolio_builder.build()`** — ogni raccomandazione e' SEMPRE
   journaled (anche via fallback CLI diretto), difensivo (try/except non bloccante).

### Verifica reale 2026-06-26 → 2026-06-29 (primo giro del loop)
- 9 pick, **0 stop / 0 target**, tutti IN CORSO, drift medio **-0.60%**.
- **Cambio regime su 6 nomi IT** (TREND_UP→PULLBACK): il gate li ha esclusi oggi.
- AC.PA il peggiore: MAE **-3.89%** (vicino ma non oltre lo stop -4.7%). Il gate di regime
  ha fatto il suo lavoro: book 9→3 nomi, esposizione 57%→18%, prima di danni maggiori.

### Risposta alla domanda "serve un sub-agent?"
Sì, ma **solo per l'audit (Fase 2)**: la ricerca dura degli errori dev'essere INDIPENDENTE
da chi ha generato i pick (un agente separato non razionalizza i propri errori). Verifica =
codice deterministico; fix = serve contesto multi-file; generazione = sequenziale. Vedi LOOP.md.

### Watch list
- [ ] Primo giro Fase 2: lanciare il sub-agent auditor su `data/VERIFICATION.txt` reale.
- [ ] IT in PULLBACK: quando rientra TREND_UP rientrano i 6 nomi IT esclusi.
- [ ] Concentrazione FR 3/3 (self_improve MEDIA): monitorare correlazione di mercato unico.

---

## Run #24 — 2026-06-29 (Fase-2 audit: il sub-agent indipendente trova il bug dell'entry stantio)

**Obiettivo:** primo giro reale della Fase 2 del loop — sub-agent auditor indipendente sulla
verifica 26→29 giugno, con mandato istituzionale (perche' i prezzi sono scesi? volume/smart
money? regime lento? gap?). Poi vagliare le proposte e applicare solo i fix supportati dai dati.

### Scoperta principale (l'auditor ha trovato un bug nel codice che AVEVO scritto io)
**Gli entry del diario erano le chiuse del 25/06, non del 26/06** (9/9 match esatti). Un fetch a
sessione 06-26 non chiusa aveva scritto una barra "06-26" coi prezzi del 25/06. La mia verifica
filtrava `date > 06-26` e **saltava la sessione reale del 06-26** (dove stava il movimento).

**Verifica CORRETTA (dal fill reale = apertura 06-26, finestra 2 sedute):**
- Drift medio **+0.34%** (non −0.60%). STMMI **+1.55%** (MFE +3.23%) — da "peggiore" a vincente.
- AC.PA −0.48% reale (il "−3.22%" era tutto entry stantio); gap apertura −2.75%.
- Gap medio −0.94%: STMMI/AC.PA hanno gappato −2.8% (rischio reale, ora strumentato).

### Fix applicati (solo quelli provati dai dati)
1. `verify_picks.py`: misura da **fill realistico** (apertura prima seduta dopo `data_asof`);
   colonne PIANO/FILL/GAP; auto-rilevazione snapshot stantio; flag gap-oltre-lo-stop.
2. `journal.py`: lo snapshot registra **`data_asof`** (barra di prezzo del piano). Ri-marcato il
   backfill 06-26 a `data_asof=2026-06-25` (data vera dei prezzi).

### Ipotesi REFUTATE dall'auditor coi numeri (NON cambiare la strategia)
- Regime "troppo lento": FALSO. FTSEMIB ha perso la SMA20 il 29 in modo **coincidente** (margine
  +0.04% il 26 → −0.11% il 29). Il trigger px>SMA20 esiste gia', nessun lag. NON accelerare la MA.
- Soglia smart-money troppo larga: i nomi in distribuzione (sm<−0.5) sono stati i top gainer →
  relazione invertita = rumore a 2 sedute. NON stringere il gate su questo campione.
- "Volume debole = fallimento": corr(volR, ritorno) ≈ 0. La conferma-volume si valuta SOLO su
  backtest 2018-2026, non su 2 giorni.

### Watch list
- [ ] **Backtest FIX 4** (conferma-volume sul breakout come leva di SIZE) sul ciclo 2018-2026
  prima di toccare lo scoring. Non spedire sulla forza di 2 sedute.
- [ ] **Hardening data-layer**: evitare che `fetch_data` scriva una barra marcata "oggi" con la
  chiusura di ieri quando gira a sessione aperta. Per ora la verifica e' robusta (rileva + misura
  dal fill), ma la fonte va irrobustita.
- [ ] IT in PULLBACK: rientro dei 6 nomi IT quando torna TREND_UP.

---

## Run #25 — 2026-06-29 (Session Gate alla fonte + FIX 4 respinto dal backtest completo)

**Obiettivo (scelta da analista critico):** irrobustire il data-layer — `fetch_data.py` non deve
MAI registrare una barra di sessione non chiusa (radice della Lezione #20) — poi backtestare FIX 4
(conferma-volume / smart money come leva di size) sul ciclo completo.

### Parte 1 — Session Gate (fetch_data.py)
- `drop_incomplete_last_bar(df, ticker)`: scarta l'ultima barra se la sessione del mercato non e'
  chiusa+settled nel fuso locale (EU 17:30 / US 16:00, +20min). Fuso per mercato di quotazione.
- Test unitari con orari iniettati: EU/US, aperto/chiuso/settle, indici EU, weekend, barra passata.
- **Dimostrazione su dati live**: lanciato alle 15:56 Roma / 09:56 NY (mercati APERTI), il gate ha
  scartato la barra 06-29 di TUTTI i 141 ticker → dataset all'ultima sessione CHIUSA (06-26).
- **Scoperta**: con i dati puliti **IT torna TREND_UP**. Il "cambio regime IT→PULLBACK" dei Run
  #23/#24 era un ARTEFATTO della barra fantasma intraday (tonfo sotto SMA20), non un evento reale.
  Il gate non corregge solo l'entry stantio: blocca un FALSO segnale di regime (go-flat su 6 IT).
- Diario: identita' su `data_asof` (data di prezzo). Backfill rinominato → `2026-06-25.json` (9 pick);
  snapshot fantasma `2026-06-29.json` (costruito su dati intraday) RIMOSSO.
- Portafoglio ricostruito su 06-26 pulito: **10 nomi** (6 CORE/4 SAT, 67%), IT rientrati.
- Verifica corretta (06-25 → 06-26, 1 sessione chiusa reale): drift medio **+0.05%**, gap medio
  −0.94% (STMMI/AC.PA gappano −2.8% in apertura ma recuperano intraday). Nessuno stop a tiro.

### Parte 2 — FIX 4 respinto (fix4_validate.py, ciclo 2018-2026)
- A/B di 4 schemi di size sullo stesso top-quintile (6329 segnali / 1004 date), bootstrap PAIRED:
  A equal 0.55 | B smart-money 0.53 | C volume-confirm 0.56 | D combined 0.56.
- **ΔSharpe vs equal: tutti gli IC95% attraversano lo 0** (B −0.07, C +0.01, D −0.04) → RUMORE.
- **Verdetto: FIX 4 NON si implementa.** Lo smart money resta FILTRO di selezione, non leva di size.
  Esito salvato in `data/FIX4_VALIDATE.txt`. (Conferma del prior dell'auditor: niente fix su 2 giorni.)
- Nota metodo: `mib_data.csv` = ~14 mesi; il ciclo completo richiede `mib_data_long.csv` (2018-2026).

### Watch list
- [ ] Size graduata per sm in `portfolio_builder` non danneggia ma non aggiunge Sharpe: candidata a
  /simplify futura (non urgente — l'uso come GATE di selezione resta validato).
- [ ] IT TREND_UP confermato su chiusura 06-26; rivalutare a fine sessione 06-29 reale.

---

## Run #26 — 2026-06-29 (FIX 5: risk parity inverse-ATR — respinto dal backtest, harness inadatto)

**Obiettivo:** testare il sizing a rischio paritario (peso ∝ 1/ATR%14) vs equal-weight sul ciclo
completo, con focus su MaxDD e Sharpe; integrare in `portfolio_builder` solo se il MaxDD si abbatte
in modo sistematico (ΔMaxDD IC95% che non attraversa lo 0).

### Test (fix5_validate.py, 2018-2026, 6329 segnali / 1004 date, bootstrap PAIRED)
| Schema | Sharpe | MaxDD% | Vol%ann |
|--------|--------|--------|---------|
| A EQUAL | 0.55 | −95.7 | 94.3 |
| B RISK-PARITY (1/ATR%) | 0.52 | −95.7 | 91.4 |
| C RP-CAPPED (3x) | 0.51 | −95.7 | 91.4 |

- ΔMaxDD vs equal: B +0.00pt [−2.35,+3.68], C +0.01pt [−2.11,+3.47] → **IC attraversa lo 0**.
- ΔSharpe: B/C −0.05 (rumore). **Soglia non soddisfatta → FIX 5 NON INTEGRATO.**

### Scoperta metodologica (più importante del risultato)
- MaxDD **identico −95.7%** tra schemi perche' le date di peggior drawdown hanno **1 solo nome**
  (worst: 2025-04-08 −45.8%, 2018-12-24 −44.7%, 2020-03-02 −41.9%, tutte n=1). 23% delle date ha
  1 nome, 34% ≤2 (mediana 5). Il sizing cross-sectional non puo' diversificare un tail a nome singolo.
- Il harness per-segnale (portfolio_sim, rendimenti 10gg sovrapposti) **non e' lo strumento giusto**
  per il vol-sizing, che agisce tra posizioni CONCORRENTI. "Nessun effetto" qui = strumento inadatto,
  non ipotesi falsa. Non si tocca `portfolio_builder` su questa base. Esito: `data/FIX5_VALIDATE.txt`.

### Watch list
- [ ] **Held-portfolio backtest**: simulare il portafoglio REALMENTE detenuto (~10 nomi concorrenti,
  posizioni sovrapposte, equity giornaliera vera) per testare correttamente risk parity / vol-sizing.
  Solo lì il FIX 5 puo' essere validato o respinto in modo equo.
- [ ] (da Run #25) size graduata per sm: candidata a /simplify; IT TREND_UP da rivalutare a fine 06-29.

---

## Run #27 — 2026-06-29 (Held-Portfolio Backtester: equity di percorso reale)

**Obiettivo:** costruire il motore mancante per testare correttamente sizing/drawdown — un
portafoglio REALMENTE detenuto con equity giornaliera, non bet per-segnale indipendenti (lo
strumento giusto chiesto a fine Run #26).

### Architettura (portfolio_backtester.py)
- Capitale 100k, mark-to-market giornaliero (equity = cassa + posizioni).
- Max 10 posizioni simultanee, max 10% del capitale totale per posizione.
- Segnali validi < 10 → resto in CASSA (mai >100% investito, nessuna leva implicita).
- Holding 10 giorni operativi: ingresso al close t+1 (segnale di t, no lookahead), uscita al
  close del 10° giorno successivo.
- Segnale: `score_series` = score_new VETTORIZZATO, validato identico a score_new (0 mismatch/25;
  ADX/RSI/rolling sono causali → valore a t su serie intera == su slice [:t+1]).

### Risultati (2018-10-11 → 2026-06-25, 1991 sedute)
| Metrica | Valore |
|---------|--------|
| CAGR | +12.21% |
| **MaxDD (path reale)** | **−32.11%** |
| Sharpe (daily) | +0.80 |
| Vol annua | 16.04% |
| Calmar | +0.38 |
| Market Exposure | 93.2% media, 9.4 posizioni |
| Trade | 1876 |

### Perche' conta
- **MaxDD reale −32% vs artefatto −95.7%** (harness per-segnale fix4/5): conferma Lezione #22.
  Questo motore sblocca il test CORRETTO di risk parity/vol-sizing (FIX 5) e size per smart money.
- Bug trovato e corretto in corsa: display vol annua (frazione stampata come %, 0.16%→16.04%);
  equity/Sharpe/MaxDD erano gia' corretti (verificato ricalcolando da portfolio_equity.csv).
- Report: `data/PORTFOLIO_BACKTEST.txt`; equity giornaliera: `data/portfolio_equity.csv`.

### Watch list
- [ ] **Aggiungere il gate di regime** al motore (go-flat fuori TREND_UP): atteso abbattimento del
  MaxDD verso il −13.8% di robustness_consolidate. Primo A/B sul nuovo motore.
- [ ] **Ri-testare FIX 5 (risk parity) e size-per-smart-money** su questo motore (dove le posizioni
  concorrenti rendono il vol-sizing osservabile).
- [ ] **Costi di transazione** nel motore (1876 trade, non trascurabili) + soglia score espandente
  per un OOS pulito (ora p80 globale, lieve bias in-sample).

## Run #28 — 2026-06-29 (A/B Regime Gate sul Held-Portfolio Backtester)

**Obiettivo:** primo A/B sul motore di Run #27 — misurare l'effetto del gate di regime
(ingressi solo in TREND_UP per mercato; posizioni a scadenza, capitale in cassa nei non-trend)
su MaxDD, Calmar ed esposizione. Logica validata `classify_regime` vettorizzata (0 mismatch/15).

### Risultato (2018-2026, stesso universo e soglia, cambia SOLO il gate)
| Metrica | A Baseline (always-in) | B Regime-Gate | Δ (B−A) |
|---------|------------------------|----------------|---------|
| CAGR % | +12.21 | **+12.44** | +0.23 |
| **MaxDD % (path)** | −32.11 | **−17.81** | **+14.30** |
| Sharpe (daily) | +0.80 | +0.93 | +0.13 |
| Calmar | +0.38 | **+0.70** | +0.32 |
| Market Exposure % | 93.2 | 59.9 | −33.3 |
| Posizioni medie | 9.4 | 6.0 | −3.4 |
| Trade | 1876 | 1208 | −668 |

### Lettura
- **Il gate quasi DIMEZZA il MaxDD (−32%→−18%) SENZA costare CAGR** (anzi +0.23 pt): protezione
  del drawdown sostanzialmente gratuita su questo ciclo. Calmar quasi raddoppia (0.38→0.70).
- L'esposizione media scende al 60% (40% del tempo in cassa nei regimi non-trend): è il meccanismo
  della protezione, non un effetto collaterale. Conferma il "go-flat" come fonte di robustezza.
- **Valida il design GIA' PRESENTE nel modello live**: `portfolio_builder` opera di default solo in
  TREND_UP (`include_pullback=False`). Questo A/B quantifica perche' quel gate e' corretto.
- Il MaxDD residuo −17.81% si avvicina al −13.8% di `robustness_consolidate`; il gap restante e'
  probabilmente la size dimezzata in PULLBACK + universo/periodo (prossimo affinamento).
- Report: `data/REGIME_PORTFOLIO_TEST.txt`; equity: `portfolio_equity.csv` (A) e
  `portfolio_equity_regime.csv` (B).

### Watch list
- [ ] Variante PULLBACK a mezza size (oggi il gate e' binario TREND_UP-only) per recuperare un po'
  di esposizione/CAGR mantenendo il DD basso.
- [ ] Costi di transazione nel motore (1208-1876 trade) + soglia score espandente (OOS pulito).
- [ ] Ri-testare FIX 5 risk-parity su questo motore CON il gate attivo (dove il vol-sizing conta).

## Run #29 — 2026-06-29 (PULLBACK a mezza size: respinto, si tiene il gate binario)

**Obiettivo:** verificare se aprire a META' size anche in PULLBACK (px<SMA20 ma >SMA200) recupera
esposizione/CAGR senza riportare su il MaxDD. A/B a 3 vie sul motore held-portfolio.

| Metrica | A OFF | B GATE (TREND_UP) | C TIERED (+PULLBACK 1/2) |
|---------|-------|-------------------|--------------------------|
| CAGR % | +12.21 | +12.44 | +9.95 |
| MaxDD % | −32.11 | −17.81 | −16.60 |
| Calmar | +0.38 | **+0.70** | +0.60 |
| Exposure % | 93.2 | 59.9 | 60.8 |

- Il TIERED abbassa il MaxDD di solo 1.2 pt ma **costa 2.5 pt di CAGR** → Calmar 0.60 < 0.70.
  **Respinto: si tiene il gate binario TREND_UP-only.** Conferma `include_pullback=False` del live.
- Motivo: il PULLBACK (px sotto SMA20) e' spesso debolezza precoce; entrarci, anche a mezza size,
  cattura piu' perdenti di quanto risparmi in drawdown. Report: `data/REGIME_PULLBACK_TEST.txt`.

## Run #30 — 2026-06-29 (Risk parity sul motore REALE: FIX 5 validato — e gia' nel live)

**Obiettivo:** ri-testare FIX 5 (risk parity inverse-ATR) sul motore held-portfolio col gate attivo,
dove il vol-sizing agisce tra posizioni CONCORRENTI (il test equo che il harness per-segnale di
Run #26 non permetteva, Lezione #22).

| Metrica | EQUAL-WEIGHT (10% flat) | RISK-PARITY (inverse-ATR, cap 10%) |
|---------|-------------------------|-------------------------------------|
| CAGR % | +12.44 | +11.73 |
| **MaxDD % (path)** | −17.81 | **−13.15** |
| Sharpe (daily) | +0.93 | **+1.04** |
| Calmar | +0.70 | **+0.89** |
| Exposure % | 59.9 | 54.4 |

- **ΔMaxDD +4.65 pt, bootstrap PAIRED IC95% [+1.07, +9.04] → ESCLUDE lo 0**: abbattimento
  SISTEMATICO confermato. ΔSharpe [−0.00, +0.24] (non peggiora). MaxDD −13.15% ≈ il −13.8% di
  robustness_consolidate.
- **Vindicazione di FIX 5 e della Lezione #22**: la STESSA ipotesi respinta sul harness artefatto
  (Run #26, MaxDD −95% non misurabile) PASSA sul motore reale. Lo strumento era sbagliato, non l'idea.
- **INTEGRAZIONE — gia' fatta nel live**: `trade_proposal.propose` dimensiona per rischio ATR
  (`shares = risk_eur/(entry−stop)`, stop ~ entry−2·ATR → pos_value ∝ 1/ATR%, cap 10%) = e' gia'
  risk-parity. Questo test VALIDA quel design; il baseline equal-weight 10% flat era il ramo NON
  rappresentativo del live. **Nessun nuovo codice di sizing**: duplicarlo sarebbe doppio conteggio.
  Report: `data/RISKPARITY_HELD_TEST.txt`.

### Watch list
- [ ] Costi di transazione nel motore + soglia score espandente (OOS pulito) — restano aperti.

## Run #31 — 2026-06-29 (Baseline alignment + CORREZIONE di Run #30)

**Obiettivo:** allineare il baseline del backtester al sizing del modello live e rimisurare il
risk-parity contro quel baseline (ultimo task di consolidamento).

**Scoperta (corregge Run #30):** il sizing "live" (replica di `propose`: risk budget su stop ATR,
cap 10%) sul motore da' metriche **IDENTICHE all'equal-weight** (equity 252.542, MaxDD −17.81,
Calmar 0.70). Motivo: con `risk_per_trade`=2.14% e stop ~2·ATR, la pos_value non-capata e' sempre
4-10x il cap del 10% → **il cap vince sempre**, la size = 10%×convinzione, NON dipende dall'ATR.

| Metrica | LIVE (propose) | EQUAL-WEIGHT | RISK-PARITY |
|---------|----------------|--------------|-------------|
| CAGR % | +12.44 | +12.44 | +11.73 |
| MaxDD % | −17.81 | −17.81 | **−13.15** |
| Calmar | +0.70 | +0.70 | **+0.89** |

- **Correzione**: in Run #30 avevo concluso "il live e' gia' risk-parity → niente da integrare".
  ERA SBAGLIATO. Il live ≡ equal-weight (cap dominante); il **risk-parity e' un miglioramento REALE
  non catturato** (ΔMaxDD +4.65 pt, IC95% [+1.07,+9.04] esclude 0) → vero candidato all'integrazione.
- Report: `data/BASELINE_ALIGN_TEST.txt`. Lezione #24 punto 4 corretta.

### Watch list (aggiornata)
- [ ] **INTEGRARE il risk-parity nel live** (Run #30+#31 lo validano): abbassare la size effettiva dei
  nomi ad alta ATR sotto il 10% (es. `pos_cap` scalato da `min(medATR/ATR,1)` in `propose`/builder).
  Cambio di produzione sul sizing → da fare con A/B sul builder, non a fine giornata.
- [ ] Costi di transazione nel motore + soglia score espandente (OOS pulito).

---
*Aggiornato dal loop di analisi finanziaria. Le regole apprese vivono in `FINANCIAL_SKILLS.md`.*
