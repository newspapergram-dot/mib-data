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

## Lezione #2 — 2026-06-25 — Valida la fonte dati e le metriche di partizione prima di fidarti dei numeri

**Evidenza.**
- Un risultato del backtest "troppo pulito" era in realtà un **bug**: la sez. 7 mostrava
  bull e bear identici (n=1100 entrambi, stesse metriche). Causa: nel dataset c'erano due
  benchmark (`SPY` e `^GSPC`) → indice-data duplicato → il join cartesiano duplicava ogni
  segnale in una copia "bull" e una "bear". Non era un edge: era doppio conteggio. Fix in
  `backtest_v3.py` (un solo benchmark + dedup); verificato bull=84 / bear=205 su dati reali.
- La fonte prezzi del repo (**yfinance**) è risultata **bloccata dal proxy (HTTP 403)** e
  finnhub dava fondamentali vuoti per i big USA. Senza un controllo, la pipeline avrebbe
  prodotto silenziosamente dati stantii/mancanti. FMP ha colmato il gap (US), ma l'**EU resta
  gated**: il dataset è aggiornabile solo in parte → ogni numero EU va marcato come "stale".
- Conferma operativa del rischio: **GOOGL −5.1% in 3 sedute** (363.79→345.29), proprio
  l'entità dello stop statistico −5%. Lo stop stretto del modello non è teoria.

**Regola.**
1. **Diffida dei risultati "perfetti o impossibili".** Metriche identiche tra gruppi che
   dovrebbero differire (bull≡bear) = sospetto bug di join/partizione, non un edge. Controlla
   chiavi duplicate e blow-up cartesiani (n_righe dopo join > n_righe prima).
2. **Un solo benchmark per il regime**, deduplicato per data. Mai mescolare serie con scale
   diverse in una `rolling()`.
3. **Verifica la freschezza e la provenienza di OGNI dato prima di usarlo.** Etichetta i
   prezzi con data e fonte (es. "EOD 24-giu FMP" vs "EU stale 18-giu"); non spacciare per
   aggiornato ciò che non lo è. Se una fonte è bloccata, dichiaralo e usa un fallback esplicito.
4. **Tieni un fallback dati indipendente** (qui FMP via `modules/fmp_source.py`): una sola
   fonte è un single point of failure. Il fallback deve degradare in modo grazioso (None, non
   crash) quando manca la chiave o il piano non copre il mercato.
5. **Conseguenza sulla Lezione #1:** finché il backtest non viene ri-eseguito col regime
   corretto, l'affermazione "edge solo in BULL" resta un'ipotesi prudenziale — la vecchia
   misura era inquinata dal bug. Ri-misurare prima di trattarla come fatto.

**Da verificare nei prossimi run.**
- Refresh EU completo (piano FMP o `fetch_data.py` fuori sandbox) per coerenza cross-section.
- Ri-eseguire il backtest e rileggere la performance per regime ora corretta.

---
*Le attività di ogni run sono registrate in `STATE.md`.*
