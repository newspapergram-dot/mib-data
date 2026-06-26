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
*Aggiornato dal loop di analisi finanziaria. Le regole apprese vivono in `FINANCIAL_SKILLS.md`.*
