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

## Lezione #7 — 2026-06-25 — Tara i parametri sul backtest, non sull'intuizione; e scegli la metrica giusta

**Evidenza.**
- Avevo "indovinato" che i target larghi (3,6,10) fossero troppo lontani. Il backtest path-based
  ha mostrato il contrario sull'expectancy: target piu' larghi = expectancy PIU' alta, perche'
  l'edge della strategia vive nella **coda destra** (pochi grandi vincitori). L'intuizione era
  sbagliata; i dati l'hanno corretta.
- Ma "expectancy massima" non e' l'unica metrica: (3,6,10) ha **mediana per-trade negativa**
  (>50% dei trade perde, si vive di coda). Per un conto piccolo conta anche la *liscezza*: (2,6,10)
  porta la mediana a +0.28% e il win-rate a 51% cedendo solo ~15% di expectancy. La scelta del
  parametro dipende dall'OBIETTIVO (expectancy pura vs curva sostenibile), non da un singolo numero.

**Regola.**
1. **Prima di cambiare un parametro, simulalo.** Una taratura "a sensazione" e' un bias: costruisci
   il backtest del parametro stesso (qui: uscita path-based target/stop) e leggi i numeri.
2. **Simula il MECCANISMO reale, non un proxy.** I forward-return (hold-N) NON validano i target:
   serve simulare l'uscita a target/stop barra-per-barra, con lo stop controllato prima del target
   (conservativo) per non barare sull'intrabar.
3. **Scegli la metrica coerente con l'obiettivo.** Expectancy massima ≠ migliore per tutti:
   guarda anche mediana, win-rate ed exp/sd. Conti piccoli → preferire mediana positiva e win-rate
   piu' alti (curva sostenibile) anche a costo di un po' di expectancy.
4. **Edge nella coda = serve disciplina e numeri.** Se la mediana e' ~0 e l'expectancy viene dai
   pochi grandi vincitori, il sistema funziona solo su MOLTE operazioni con stop rispettato; un
   campione piccolo o l'abbandono anticipato distruggono l'edge.
5. **Lascia il parametro configurabile e documenta il trade-off**, cosi' la scelta resta reversibile
   (qui: default (2,6,10) "liscio", ma (3,6,10) per expectancy pura a un parametro di distanza).

**Da verificare nei prossimi run.**
- Validare lo Smart Money come predittore prima di pesarlo; calibrare `confidence_level` su percentili.

---

## Lezione #8 — 2026-06-25 — Una validazione che dice "NO" vale quanto una che dice "sì"

**Evidenza.**
- Da run integrare lo Smart Money nello score era in watch-list. La validazione point-in-time
  ha mostrato che **mescolarlo linearmente PEGGIORA** la correlazione col forward return a 10gg
  (blend 0.059 < score 0.086). Aggiungerlo "perche' sembra sensato" avrebbe danneggiato l'edge.
- Eppure lo stesso segnale, usato come **filtro condizionato** dentro il top-quintile, separa
  bene: accumulazione +3.14% (win 60%) vs distribuzione +1.63% (win 40%). E' un effetto di
  **interazione**, non un effetto principale: utile come filtro, dannoso come peso lineare.

**Regola.**
1. **Valida prima di integrare. Un risultato negativo e' un successo**: evita di degradare il
   sistema con un'aggiunta "intuitiva". Non aggiungere un fattore solo perche' e' plausibile.
2. **Distingui effetto principale da interazione.** Un segnale debole come predittore standalone
   (o in blend lineare) puo' essere forte come filtro CONDIZIONATO ad altro (qui: dentro il
   top-quintile). Testa entrambe le forme prima di decidere DOVE usarlo.
3. **Attento all'orizzonte**: lo Smart Money correla meglio a 20gg che a 10gg. Un fattore puo'
   essere giusto su un orizzonte e rumore su un altro — valida sull'orizzonte operativo reale.
4. **Le soglie delle etichette vanno calibrate sulla distribuzione** (ribadisce L#5/L#7): soglie
   assolute che non si raggiungono mai (ALTA>=0.45 con score max 0.36) non informano, confondono.

---

## Lezione #9 — 2026-06-25 — L'affidabilità si costruisce a strati condizionali, e si dichiara in-sample

**Evidenza.**
- Lo stesso segnale Smart Money, inutile come peso lineare (L#8), diventa la **leva di
  affidabilita'** come filtro condizionato: top-quintile + accumulazione porta win 57%→60%,
  Sharpe 1.21→1.55, PF 2.08→2.61 (monotono anche a 20gg). Gli strati (trend gate → regime
  TREND_UP → top-quintile → accumulazione → stop) si MOLTIPLICANO in condizioni dove l'edge
  esiste davvero.
- La sez.7 corretta mostra che l'edge e' **bull-concentrato** (NUOVO Sharpe bull +4.58, bear
  −1.54 su piccolo campione): l'affidabilita' dipende dall'operare nel regime giusto, non dal
  titolo in se'. Il regime filter non e' un orpello, e' la condizione abilitante.
- Tutte le metriche restano **in-sample** (un periodo, prevalentemente bull) con DSR<0.95.

**Regola.**
1. **L'affidabilita' e' un prodotto di filtri condizionali, non un singolo numero.** Concatena
   condizioni che restringono al sottoinsieme dove l'edge e' misurato (trend, regime, score,
   smart money); ogni strato deve MIGLIORARE le metriche del sottoinsieme, altrimenti toglilo.
2. **Concentra la size dove l'edge e' piu' forte** (CORE accumulazione piena size; SAT neutro
   ridotta): il sizing e' parte del modello di affidabilita', non un dettaglio.
3. **Dichiara sempre se le metriche sono in-sample.** "Win 60%, Sharpe 1.55" senza il contesto
   (un periodo, bull, DSR<0.95) e' fuorviante. Un modello e' "piu' affidabile", non "affidabile",
   finche' non regge out-of-sample su un ciclo completo.
4. **Un edge condizionato a un regime richiede il filtro di quel regime in produzione.** Se
   funziona solo in BULL, opera solo (o a piena size solo) in BULL: e' la salvaguardia, non un
   limite da aggirare.

**Da verificare nei prossimi run.**
- Walk-forward/OOS su un ciclo con bear vero; tenere DSR>0.95 riducendo i gradi di liberta'.

---

## Lezione #10 — 2026-06-25 — Out-of-sample: la prova del nove, ma solo nel regime che hai visto

**Evidenza.**
- Il walk-forward anchored (soglia top-quintile stimata solo sull'IS, modello applicato a
  finestre OOS mai viste) ha dato **WFE +1.52**: l'edge OOS (win 56.5%, Sharpe 1.55) e' pari o
  superiore all'IS → le scelte fatte (top-quintile + accumulazione + target) NON erano
  overfitting nel periodo. Una validazione che, stavolta, dice "si'".
- Ma tutte le finestre cadono in un periodo prevalentemente bull: l'OOS prova la stabilita'
  temporale, non la robustezza su un ciclo completo. Una finestra su 4 era gia' debole.

**Regola.**
1. **Stima i parametri SOLO sull'IS e misura sull'OOS mai visto.** La soglia (es. quantile del
   top-quintile) va calcolata sui dati precedenti, mai sull'intero campione: altrimenti e'
   lookahead travestito da validazione.
2. **WFE ~>0.5 = l'edge regge; WFE bassa = era overfit.** Un OOS >= IS e' ottimo, ma diffida
   se e' MOLTO sopra l'IS su pochi dati: puo' essere fortuna di periodo, non solo assenza di overfit.
3. **L'OOS vale quanto la varieta' dei dati che contiene.** Un walk-forward tutto in bull NON
   certifica il comportamento in bear. Dichiara sempre quali regimi l'OOS ha (e non ha) visto.
4. **Finche' manca un ciclo completo, l'affidabilita' poggia sul filtro di regime.** Se l'edge e'
   bull-concentrato, e' il regime_filter (operare solo in TREND_UP) a renderlo "operativo", non
   l'OOS da solo.

**Da verificare nei prossimi run.**
- Ripetere il walk-forward quando i dati includeranno un bear; tenere DSR>0.95.

---

## Lezione #11 — 2026-06-25 — Un backtest senza bear è una bugia gentile; il drawdown dice la verità

**Evidenza.**
- La stessa strategia: **Sharpe 1.89 su 14 mesi (bull)** → **Sharpe 0.18, MaxDD −95.7% sul
  ciclo completo 2018-2026**. Il periodo corto e mono-regime nascondeva un rischio di rovina
  totale. Walk-forward OOS positivo (L#10) NON bastava: era tutto dentro lo stesso regime bull.
- I "fattori bear" (filtro di regime + accumulazione + STOP + trigger rapido SMA20) hanno
  ridotto il MaxDD da −95.7% a −33% e alzato lo Sharpe a 0.83. Lo STOP e il trigger RAPIDO sono
  i pezzi decisivi; il filtro lento SMA50/200 da solo lasciava ancora −68%.

**Regola.**
1. **Non fidarti di un backtest che non contiene un bear.** Prima di operare, testa su un ciclo
   completo (incl. 2020/2022). Se non hai i dati, scaricali; se non puoi, dichiara che le metriche
   valgono solo per quel regime.
2. **Il Max Drawdown e' la metrica di verita' per i bear**, non lo Sharpe o l'expectancy: misura
   il rischio di rovina. Uno Sharpe alto con DD −95% e' inservibile.
3. **Usa prezzi AGGIUSTATI su orizzonti lunghi**: gli split (close grezzo) creano salti che
   falsano il backtest. adjclose o adjustment factor sull'OHLC.
4. **Contro i crash veloci serve un trigger RAPIDO**, non solo medie lente: SMA50>SMA200 entra
   tardi; px<SMA20 (o vol/momentum) coglie la prima gamba al ribasso. Lo STOP per-trade e' il
   secondo strato indispensabile.
5. **I filtri di risk-off riducono la rovina, non trasformano una strategia bull in bear-proof.**
   Onesta': una strategia long-only resta bull-favored; per il bear servono hedge/short o stare flat.

---

## Lezione #12 — 2026-06-25 — Diffida dell'hedge che sembra alpha; e non duplicare una difesa che hai già

**Evidenza.**
- "Stare flat nei TREND_DOWN" non ha cambiato nulla (A == BASE): il filtro di regime tiene gia'
  il modello fuori dai downtrend. La difesa bear migliore era gia' nel gate d'ingresso.
- L'index hedge ha ridotto il MaxDD (−13.8%→−9.1%) ma ha anche triplicato lo Sharpe (0.99→2.55)
  e il CAGR (14%→41%): troppo bello. Veniva dallo short dell'indice durante i crash 2020/2022 —
  eventi specifici del campione. In mercati laterali quello stesso hedge fa whipsaw e perde.

**Regola.**
1. **Giudica un hedge dalla RIDUZIONE del drawdown, non dal rendimento.** Se un overlay di
   copertura "aggiunge alpha" in backtest, sospetta overfitting agli eventi del campione: e'
   assicurazione, e l'assicurazione di norma COSTA. Dimensiona di conseguenza (h prudente).
2. **Non aggiungere una difesa che duplichi una salvaguardia esistente.** Go-flat era ridondante
   col filtro di regime. Prima di costruire un overlay, verifica cosa fa gia' il sistema.
3. **Testa gli overlay alla granularita' giusta (giornaliera/M2M).** Un overlay che agisce
   giorno per giorno non si valuta su rendimenti aggregati a N giorni.
4. **Default = la scelta piu' robusta; l'aggressiva resta opzionale e documentata.** Go-flat di
   default (DD piu' basso); hedge/stay-invested come flag esplicito con avvertenza sui costi.

---

## Lezione #13 — 2026-06-25 — Non si tara via il rumore, e il DSR si può ingannare

**Evidenza.**
- I 4 set di moltiplicatori di target danno risultati quasi identici sul ciclo completo
  (mean ~0.27%/trade, MaxDD −37/−40%, PF 1.18): cio' che sembrava una leva (i target) sul
  campione bull e' rumore sul ciclo completo. Cambiare avrebbe significato overfittare al rumore.
- Il DSR e' uscito ~0.99 ("supera 0.95"), ma e' in parte gonfiato: poche config quasi identiche
  → sr0 minuscolo; trade sovrapposti → T effettivo < n. Il numero reale di prove nel progetto e' >>4.
  L'edge full-cycle sottostante e' sottile (Sharpe giornaliero 0.12).

**Regola.**
1. **Se piu' valori di un parametro danno lo stesso risultato, NON tararlo: e' rumore.** Tieni il
   default piu' sensato e non inseguire la terza cifra decimale: e' overfitting travestito da tuning.
2. **Il DSR (e ogni metrica anti-overfit) si puo' ingannare**: testando poche alternative simili
   (sr0 basso) o usando osservazioni sovrapposte (T gonfiato). Per onesta': conta TUTTE le prove
   fatte, usa osservazioni il piu' indipendenti possibile, e diffida di un DSR alto con Sharpe basso.
3. **Quando l'edge e' sottile, l'affidabilita' viene dai controlli di rischio, non dallo Sharpe.**
   Filtri di regime, stop, go-flat, sizing per convinzione: limitano la rovina anche se l'edge e' modesto.
4. **Per un edge piu' forte serve un SEGNALE nuovo, non un'altra taratura.** Esaurita la spremitura
   dei parametri, il progresso arriva da informazione nuova (fattori/dati), validata full-cycle.

---

## Lezione #14 — 2026-06-25 — Un fattore "accademicamente solido" va comunque validato NEL TUO sistema

**Evidenza.**
- Il momentum 12-1 (fattore robusto in letteratura) era l'unico con correlazione full-cycle
  positiva (+0.027) e quintile top migliore (+1.11%). Sembrava il candidato giusto.
- Ma dentro il modello operativo reale (regime + stop + uscita laddered) NON ha aggiunto valore:
  rankare per momentum ha RADDOPPIATO il drawdown (−37%→−63%, i titoli ad alto momentum crashano
  di piu'), e combinare score+momentum ha peggiorato lo Sharpe (0.19). Il low-vol era addirittura
  negativo short-term. Decisione: non integrare nulla.

**Regola.**
1. **"Validato in letteratura" ≠ "valido nel tuo sistema".** Un fattore va testato CON la tua
   esecuzione reale (stop, target, costi, universo, orizzonte), non solo come correlazione grezza.
   Un edge che sparisce con lo stop non e' un edge per te.
2. **Guarda il drawdown, non solo il rendimento medio.** Il momentum aveva mean simile ma DD doppio:
   stesso ritorno, rischio di rovina molto peggiore. Il fattore "migliore" puo' essere il piu' pericoloso.
3. **Non aggiungere complessita' senza beneficio robusto dimostrato.** Tre fattori testati, zero
   integrati: e' il risultato corretto, non un fallimento. La disciplina del "NO" protegge il sistema.
4. **Conosci il tetto del tuo edge.** Quando spremere prezzo/volume non produce piu' nulla di
   robusto, il progresso richiede INFORMAZIONE NUOVA (fondamentali point-in-time, dati alternativi),
   non un'altra trasformazione degli stessi dati. E, nel frattempo, l'affidabilita' la dà il rischio.

---

## Lezione #15 — 2026-06-25 — Point-in-time vuol dire "data di deposito", non "data del periodo"

**Evidenza.**
- Procurare fondamentali "storici" non basta: per evitare il lookahead serve la **data in cui il
  dato e' diventato PUBBLICO** (filing). I bilanci si depositano 1-3 mesi dopo la fine del periodo;
  usare la data di fine periodo regalerebbe informazione futura.
- Le fonti differiscono molto: FMP-TTM da' solo lo snapshot CORRENTE (zero storia PIT); Yahoo
  fundamentals-timeseries da' la data di FINE periodo (no filing) e poca storia; **SEC EDGAR
  companyfacts** da' i valori con il campo `filed` → e' la fonte PIT corretta (e gratuita) per gli USA.

**Regola.**
1. **Per un fattore fondamentale, allinea sempre sulla data di DEPOSITO** (o, se manca, applica un
   lag prudente di ~75-90 giorni dopo la fine del periodo). Mai usare il dato il giorno in cui il
   periodo si chiude.
2. **Distingui snapshot corrente da serie storica PIT.** Un endpoint che da' "i fondamentali" di
   oggi non serve a backtestare: serve la serie con le date di disponibilita'.
3. **SEC EDGAR `companyfacts` e' il riferimento PIT gratuito USA** (campo `filed`); per EU servono
   fonti dedicate (spesso a pagamento). Conoscere la fonte giusta evita backtest inquinati.
4. **Se la fonte e' bloccata, prepara il codice e dichiara il lever** (qui: allowlist SEC), non
   ripiegare su un dato sbagliato (fine-periodo) pur di "avere qualcosa".

---
*Le attività di ogni run sono registrate in `STATE.md`.*
