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

## Lezione #3 — 2026-06-25 — Il Foreground (smart money sui volumi) è un filtro, non un dettaglio

**Evidenza.**
- Lo score del repo è prezzo-centrico (trend + flow 13F/insider). Aggiungendo un overlay
  **volume-ponderato** (ADL + CMF + anomalie volume >1.5× media20) emergono contraddizioni
  che il solo prezzo nasconde:
  - **AMZN**: score long positivo (+0.21) ma **distribuzione** netta (sm −0.74, ADL −89%,
    CMF −0.26, volume 1.48×). I grandi fondi stavano *uscendo* mentre il trend appariva ok.
  - **GE**: score modesto ma **accumulazione** (sm +0.39, ADL +21%) → il volume *conferma* il long.
  - Scan universo: distribuzione forte su Stellantis e CRM (volume 3.46× su giornata negativa =
    impronta di vendita istituzionale); accumulazione su banche/utility IT.
- Conferma che l'analisi del Foreground (chi compra/vende davvero) aggiunge informazione
  ortogonale al segnale di prezzo, soprattutto come **veto** sui long "belli ma vuoti".

**Regola.**
1. **Usa lo Smart Money come filtro di conferma/veto sopra lo score**, non come abbellimento:
   - score long + accumulazione → conferma (size piena nel regime favorevole);
   - score long + **distribuzione** → declassa o salta: il flusso reale contraddice il prezzo.
2. **Pesa l'anomalia di volume con la direzione**: spike >1.5× su giornata *positiva* =
   accumulazione; su giornata *negativa* = distribuzione. Il volume senza direzione è rumore.
3. **ADL e CMF sono complementari**: ADL (cumulata) coglie il trend strutturale di
   accumulo/distribuzione; CMF(20) la pressione del mese. Concordi = segnale robusto.
4. **Prima di pesare un nuovo segnale nello score, validalo nel backtest.** Per ora lo Smart
   Money è overlay nel report: va misurato (correlazione col forward return) prima di entrare
   nel ranking come 4° componente.

**Regola operativa sui dati (rafforza Lezione #2).**
5. **Quando una fonte è bloccata a ogni livello (egress + piano API), implementa comunque il
   fallback in codice ma NON fabbricare dati.** EU qui è irraggiungibile da yfinance (403),
   stooq (403) e FMP (piano US-only): la catena `get_eod_eu()` è pronta e riusa il tool stooq
   esistente, ma i prezzi EU restano marcati "18-giu stale". Codice resiliente ≠ dati inventati.

**Da verificare nei prossimi run.**
- Backtest dello Smart Money come predittore; se regge, integrarlo in `score_generator`.
- Sblocco EU effettivo (piano FMP-EU o egress) per scan Foreground fresco su IT/FR.

---

## Lezione #4 — 2026-06-25 — Diagnostica il livello giusto del problema, e fidati della fonte canonica

**Evidenza.**
- Per 3 run ho aggiunto fallback su fallback (FMP→stooq→Yahoo JSON→Borsa Italiana) contro un
  403 che NON era del dato ma della **policy di egress** (allowlist di host). La svolta non è
  arrivata da più codice ma dall'**aggiunta di un dominio all'allowlist** (`query1.finance.yahoo.com`):
  subito dopo, il Piano C già scritto ha sbloccato **tutto l'universo EU live**. Il codice era
  pronto da prima; mancava il permesso di rete.
- `yfinance`, pur con l'allowlist, è rimasto KO: usa host aggiuntivi (`fc.yahoo.com` per
  cookie/crumb) non in allowlist. L'**endpoint JSON ufficiale v8** (un solo host) ha funzionato:
  meno dipendenze di rete = più robusto della libreria.
- Ricalcolando il regime "a mano" ottenevo US=RISK_OFF (S&P 7350 < SMA50 7357), mentre il modulo
  canonico del repo (`regime_filter.py`) dava US=TREND_UP (slope +4.99%). Differenza nata su un
  confine sub-0,1%: la mia stima ad-hoc era fragile e **incoerente con la fonte di verità**.

**Regola.**
1. **Prima di accumulare workaround, isola il livello del fallimento.** Un 403 al CONNECT
   (ProxyError, prima di qualunque header) = policy di rete, non endpoint/anti-bot. Più scraper
   non risolvono un blocco di allowlist: la leva è la configurazione di egress, non il codice.
2. **Costruisci il fallback resiliente, ma riconosci quando il blocco è esterno** e portalo a chi
   ha la leva (qui: allowlist dell'environment). Codice pronto + leva giusta = sblocco immediato.
3. **Preferisci l'endpoint con meno dipendenze di rete.** Una libreria che tocca più host fallisce
   appena uno non è raggiungibile; un singolo endpoint JSON ufficiale è più robusto.
4. **Per le decisioni operative usa la fonte canonica del repo, non ricalcoli ad-hoc.** Sul confine
   di una SMA un ricalcolo semplificato può dare il segno opposto. Usa `regime_filter.py` (e segnala
   la fragilità: "S&P a −0,09% dalla SMA50 → regime sul filo"), non una stima parallela.
5. **Una fonte unica e coerente batte il mix.** Rifare TUTTO l'universo da Yahoo (vs US-FMP +
   EU-Yahoo) elimina discrepanze cross-source nei confronti cross-section dello score.

**Da verificare nei prossimi run.**
- Rendere il Piano C (Yahoo v8) la sorgente primaria in `fetch_data.py`.
- Monitorare il regime US (S&P sul filo della SMA50).

---

## Lezione #5 — 2026-06-25 — Collaudare l'INTERO processo svela errori che i singoli moduli nascondono

**Evidenza.**
- Eseguendo la pipeline end-to-end sono emersi bug invisibili nei test isolati:
  due script (`regime_filter.py`, `volume_tools.py`) leggevano i dati da
  raw.githubusercontent/**main** invece che dal file locale → crash `IncompleteRead`
  e, peggio, classificavano su dati **stale** del branch, non su quelli appena prodotti.
  Per giorni il regime poteva essere stato calcolato sui dati sbagliati senza errori visibili.
- Il piano d'azione consigliava STMMI.MI **e** STMPA.PA: stesso emittente (ISIN
  NL0000226223) su due borse → doppia esposizione nascosta su un solo nome.
- Con i requisiti stringenti applicati a dati freschi, **un solo titolo** (STM) li
  rispetta tutti: le soglie di confidenza (0.20/0.45) sono tarate troppo in alto rispetto
  alla scala reale degli score (max ~0.29), quindi quasi tutto finisce "BASSA".

**Regola.**
1. **Testa la catena completa, non i pezzi.** I bug stanno nelle giunzioni (sorgente dati,
   passaggio tra moduli), non dentro le funzioni pure. Un collaudo end-to-end periodico è
   parte del processo, non un extra.
2. **Una pipeline legge i dati che ha appena prodotto, in locale.** Mai far dipendere uno step
   da una copia remota/branch: è fragile (download che si troncano) e silenziosamente stale.
3. **Deduplica per EMITTENTE (ISIN), non per ticker.** Doppie quotazioni (Milano/Parigi),
   ADR e classi multiple sono lo stesso rischio: contarle due volte raddoppia l'esposizione.
4. **Tara le soglie sulla distribuzione reale dei dati.** Una soglia assoluta ("ALTA ≥0.45")
   che non viene MAI raggiunta non è un filtro, è un bug logico: usa percentili o ricalibra.
5. **Pochi titoli idonei è un risultato onesto, non un fallimento.** Con filtri stringenti in
   un mercato a bassa dispersione è normale che passi 1 nome: meglio 1 segnale pulito che 10
   forzati. Mostra sempre i "quasi-idonei" e il requisito fallito, per trasparenza e tuning.

**Da verificare nei prossimi run.**
- Calibrazione confidenza (percentile) e banda neutra su R4 → cambiano i titoli idonei.
- Validazione statistica dello Smart Money prima di pesarlo nello score.

---

## Lezione #6 — 2026-06-25 — Target legati a volatilità+rischio; diversificare scalando la size, non escludendo

**Evidenza.**
- I target fissi (+4.1%/+8.2%) davano **R/R 0.82** (rischio 5% per puntare 4%): strutturalmente
  sfavorevole e, per conti piccoli, mangiato dai costi. Legando i target ad **ATR** (volatilita')
  e al **rischio** (R-multipli) il R/R diventa ≥1.5 e i margini diventano significativi
  (es. STM da +1.35% a +15.4% a T1) — con T1/T2/T3 ≈ 1σ/2σ/3σ sull'orizzonte.
- Il piano stretto dava 1 solo titolo perche' la confidenza assoluta escludeva quasi tutto.
  Sostituendo l'esclusione con un **size_mult per convinzione** (e filtri su percentili, non
  soglie assolute) il portafoglio passa a 12 nomi diversificati, senza buttare il controllo del rischio.

**Regola.**
1. **Il take profit si ancora a volatilita' e rischio, non a una % fissa.** `T = entry + max(k·ATR,
   k·R)`: scala col titolo, garantisce R/R favorevole, e i k·ATR mappano su multipli di sigma
   (1σ/2σ/3σ) = laddering con probabilita' di touch interpretabili.
2. **Allargare il TP NON e' gratis: scambia hit-rate con payoff.** I numeri di win-rate storici
   valgono SOLO ai target con cui sono stati misurati. Cambi i target → ri-misuri. Mai riusare
   il vecchio win-rate con target nuovi.
3. **Per diversificare, scala la size per convinzione invece di escludere.** Un titolo meno
   liquido o meno forte non va buttato: entra con size ridotta. Cosi' il portafoglio si amplia
   mantenendo il rischio proporzionato alla convinzione.
4. **Mostra il guadagno in EUR per ogni target, non solo in %.** Per conti piccoli il punto e'
   se, NETTO costi, il trade vale la pena: il valore assoluto rende la decisione concreta.
5. **Soglie su percentili della distribuzione, non assolute** (vedi Lezione #5): una soglia che
   non si raggiunge mai non filtra, esclude e basta.

**Da verificare nei prossimi run.**
- Backtest dei nuovi target ATR/R (hit-rate, expectancy, Sharpe) e taratura di k_ATR.
- Calibrazione percentile anche di `confidence_level`.

---
*Le attività di ogni run sono registrate in `STATE.md`.*
