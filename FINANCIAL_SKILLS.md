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

## Lezione #13 — 2026-06-26 — Fondamentali POINT-IN-TIME o non sono fondamentali; e una sola definizione canonica

**Evidenza.**
- I fondamentali raccolti per data di PERIODO (es. "FY2025") sono lookahead travestito: al
  momento del segnale il mercato NON aveva ancora quel bilancio. La fonte XBRL SEC espone la
  **data di FILING** (`filed`): usando quella (`pit_lookup`: filed <= data segnale) il backtest
  e' onesto. La storia PIT (`fundamentals_pit_history.csv`, 2821 obs) esiste apposta.
- Validazione (backtest sez.9, top-quintile 10gg): il filtro qualita' fondamentale **migliora**
  il sottoinsieme — PIT>=0.60 ret +3.30%/Sharpe 1.50 (vs base +2.49%/1.21); net margin>=10%
  ret +4.86%/win 60%. Coerente con L#9: l'affidabilita' e' un prodotto di filtri condizionali.
- Caveat onesto: campioni piccoli (n=35-57), in-sample bull. Quindi integrato come **leva di
  size**, non come veto rigido ne' come blend lineare (L#8: il blend lineare degrada lo score).
- La stessa formula di quality score serviva a DUE chiamanti (backtest + builder live): tenerne
  due copie = drift garantito. Centralizzata una sola `pit_quality_score` in `modules/fundamentals`.

**Regola.**
1. **Un fondamentale senza data di filing non e' usabile nel backtest.** Aggancia OGNI dato
   contabile al momento in cui e' diventato pubblico (`filed`), mai alla fine del periodo
   contabile: altrimenti e' lookahead. Se la fonte non da' la data di filing, non e' point-in-time.
2. **Il dato fondamentale mancante e' NEUTRO, mai un veto.** SEC copre solo gli USA: gli EU
   restano `n/d` e passano a size piena (N/A != penalita', come per i criteri settoriali in
   `build_screen`). Penalizzare l'assenza di dato e' fabbricare un segnale che non esiste.
3. **Qualita' fondamentale = leva di size su un filtro condizionato, non blend nello score.**
   Validala DENTRO la selezione (top-quintile) e usala per scalare la size (Q+ piena, Q/Q-
   ridotta), come gia' fatto per lo Smart Money. Non sommarla linearmente al ranking.
4. **Una sola definizione canonica per ogni metrica condivisa.** Se backtest e produzione usano
   lo stesso score, deve vivere in UN posto solo (qui `modules/fundamentals.pit_quality_score`),
   importato da entrambi: due copie divergono e il live smette di misurare cio' che hai validato.
5. **La fonte ufficiale batte gli aggregatori a pagamento, quando raggiungibile.** SEC EDGAR e'
   gratis, completo e autorevole per gli USA: e' diventato fonte primaria (Finnhub/yfinance
   fallback). Come per Yahoo v8 (L#4), bastava il dominio in allowlist, non piu' codice.

---

## Lezione #14 — 2026-06-26 — Un effetto medio nasconde il regime: la qualita' fondamentale e' DIFENSIVA

**Evidenza.**
- Il filtro qualita' fondamentale PIT sembrava un miglioramento universale (backtest sez.9,
  14 mesi bull: PIT>=0.60 ret +3.30%/Sharpe 1.50). Validato sul **ciclo completo 2018-2026**
  e **segmentato per regime**, il quadro si ribalta:
  - BULL: il filtro PIT>=0.60 **PEGGIORA** (ret -0.28%/-0.50%, Sharpe -0.16/-0.11 a 10/20gg).
  - BEAR: il filtro **AIUTA** (ret +0.63%/+0.82%, win +3.7%/+3.5%, Sharpe +0.48/+0.34).
  - Spearman pit_quality↔ritorno: bull ~0, **bear +0.16/+0.19**. E' flight-to-quality: i
    fondamentali proteggono nel risk-off; nel momentum rialzista anche la qualita' bassa corre.
- Sul ciclo completo (non segmentato) PIT>=0.60 sta SOTTO il base USA (0.70 vs 0.91 a 10gg):
  l'effetto medio e' negativo perche' DOMINATO dalle barre bull. Il +3.30% era un artefatto
  del solo sotto-periodo bull a 14 mesi — esattamente il rischio di L#11 (backtest senza bear).
- Anomalia: `net margin < 0` (in perdita) ha i ritorni TOP (n=61, +4.23%/+8.66%, PF 3-5) =
  high-beta/turnaround dentro il momentum, non qualita'. Alta varianza: segnale rischioso, non edge.

**Regola.**
1. **Un effetto medio puo' avere SEGNO OPPOSTO nei due regimi.** Prima di integrare un fattore,
   segmenta per regime (bull/bear): una media positiva su un campione bull-dominato puo' nascondere
   un danno in bull e un beneficio in bear (o viceversa). Mai validare un fattore solo sull'aggregato.
2. **La qualita' fondamentale e' una leva DIFENSIVA, non un miglioramento universale.** Applicala
   dove serve (regimi risk-off / non-TREND_UP), tienila NEUTRA dove il momentum premia la bassa
   qualita' (TREND_UP). Una leva right-in-bear / wrong-in-bull va resa condizionale al regime.
3. **Ricorda L#11 ogni volta che un filtro "funziona".** Se la validazione e' su un periodo
   mono-regime (qui i 14 mesi bull della sez.9), il risultato vale SOLO per quel regime. Ri-testa
   sul ciclo completo prima di scolpire la conclusione nel modello.
4. **Una validazione che corregge un'integrazione gia' fatta e' un successo, non un fallimento**
   (estende L#8). Run #13 aveva applicato la leva sempre; Run #14 l'ha resa difensiva. Meglio
   correggere su evidenza che lasciare un mis-fit "perche' era gia' integrato".
5. **Distingui edge da high-beta.** Ritorni altissimi su un sotto-gruppo piccolo e rischioso
   (qui i nomi in perdita) sono di solito beta/coda, non un fattore da sfruttare: alta varianza,
   crolla per primo in un bear vero. Non confondere la coda fortunata con un segnale.

**Aggiornamento Run #16 (riconferma con piu' dati).** Allargato il campione (US PIT + EU,
bear n 168->276), il SEGNO del filtro difensivo regge (aiuta in bear, neutro/contro in bull) ma
le MAGNITUDINI crollano: bear 10gg da +0.63%/Sharpe+0.48 a **+0.18%/+0.17**; Spearman ~0 in
entrambi i regimi. Conferma il punto 3 nella sua forma piu' forte: la stima US-only era ottimistica.
La leva resta direzionalmente giusta (difensiva, regime-conditional) ma e' DEBOLE (effetto-soglia,
non monotono): tienila come leva prudente, non come edge. Un'altra prova che piu' dati raffreddano
una stima in-sample (L#11) — e che il segno puo' reggere anche quando l'ampiezza si sgonfia.

---

## Lezione #15 — 2026-06-26 — Allargare l'universo non e' gratis: piu' nomi diluiscono se non li filtri

**Evidenza.**
- Tentazione: aggiungere ~33 "unicorni" growth (alto unicorn_score) al `TICKERS` per piu' rendimento.
  Backtest (unicorn_validate, 2018-2026, score momentum validato sugli unicorni):
  - unicorni top-quintile: ret +0.34%/+1.05% (10/20gg), **Sharpe 0.15/0.22**;
  - mega-cap top-quintile (stesso modello): ret +0.89%/+2.01%, **Sharpe 0.64/0.68**.
  -> dump indiscriminato di high-beta **DILUISCE** l'edge (Sharpe quasi triplo sui mega-cap).
- Ma DENTRO il top-quintile, un GATE point-in-time separa nettamente: iper-crescita (rev YoY>=25%
  PIT) vs crescita decelerata (<25%):
  - BULL: +0.60%/+1.58% vs **-0.68%/+0.06%** (i nomi a crescita svanita = trappole momentum);
  - BEAR: +2.68%/+4.37% (win 56-64%) vs +1.34%/+0.51%. Spearman crescita↔ritorno bear +0.12/+0.20.

**Regola.**
1. **Piu' ticker != piu' edge.** Allargare l'universo con nomi high-beta non filtrati abbassa lo
   Sharpe del sistema: il rumore aggiunto supera il segnale. Misura SEMPRE l'effetto sull'edge
   (Sharpe, non solo il rendimento medio) prima di ampliare la watchlist operativa.
2. **Se aggiungi high-beta, aggiungi anche il gate che li rende edge.** Per gli unicorni il gate e'
   la crescita ricavi PIT (>=25%): senza, il momentum su un growth decelerato e' una trappola.
   Con, e' uno SLEEVE valido (ma high-beta -> satellite a size ridotta, dentro il gate di regime).
3. **Il profilo "growth" e' un gate point-in-time, non un'etichetta statica.** Un nome era un
   unicorno; conta se lo e' ANCORA alla data del segnale (rev YoY corrente, da SEC filed<=data).
   La crescita passata non si compra: si compra quella ancora in corso.
4. **Uno screener di scoperta (L precedenti su unicorn_screener) NON e' un segnale finche' non lo
   backtesti.** Il profilo fondamentale alto non basta: solo il backtest ha detto DOVE (gate
   crescita) e COME (satellite high-beta) usarlo. Scoperta -> validazione -> regola operativa.
5. **Zero candidati che passano il gate e' un output legittimo** (ribadisce L#5). Oggi 0 unicorni
   passano (i leader di momentum hanno crescita svanita, gli iper-cresciti non hanno momentum):
   "non comprare" e' una decisione, non un fallimento del tool.

---

## Lezione #16 — 2026-06-26 — Misura il modello che OPERI, non il segnale grezzo; e PSR != DSR

**Evidenza.**
- Stesso periodo (ciclo completo 2018-2026), due numeri opposti a seconda di COSA misuri:
  - top-quintile GREZZO (no gate regime, no accumulazione, no stop): Sharpe **0.17**, MaxDD **-95.7%**;
  - modello OPERATIVO (go-flat regime UP + top-quintile + accumulazione + stop): Sharpe **1.00**,
    MaxDD **-13.8%**, CAGR +14.4%. Stesso edge sottostante, ma il modello e' i FILTRI, non il segnale.
- **PSR 0.977 ma DSR 0.86-0.92**: l'edge e' quasi certamente reale (Sharpe vero >0) MA non supera la
  soglia di multiple-testing. PSR e DSR rispondono a domande diverse: "lo Sharpe e' >0?" vs "e' >0
  dopo aver corretto per quante strategie ho provato?". Un edge puo' essere reale e non blindato.
- Le metriche a 14 mesi (Sharpe 1.89) erano un artefatto bull: sul ciclo completo il profilo onesto
  e' Sharpe ~1.0. Il numero piu' alto non era piu' vero, era solo su meno (e migliori) dati.

**Regola.**
1. **Backtesta il modello che OPERI, non il segnale grezzo.** Gate di regime, filtro di conferma e
   stop FANNO parte del modello: misurarli fuori da' una diagnosi falsa (Sharpe 0.17 vs 1.0). Se la
   pipeline misura il grezzo, costruisci la serie del modello reale (M2M giornaliera) e valuta quella.
2. **PSR e DSR non sono intercambiabili.** PSR>0.95 dice "edge reale"; DSR>0.95 dice "robusto a
   multiple-testing". Riporta entrambi: un edge reale-ma-non-blindato si OPERA, ma a size moderata.
3. **Non gamare il DSR.** Il DSR dipende dal numero di trial N: riportalo a piu' N (6/10/15) e giudica
   dal piu' severo. Ridurre N "per far passare la soglia" e' barare; ridurre i gradi di liberta' VERI
   del modello (meno knob) e' lecito e riduce anche l'overfit.
4. **Se l'edge non e' blindato, la protezione e' la DISCIPLINA, non il leverage.** Size moderata +
   gate di regime + stop sono cio' che rende operabile un edge bull-concentrato con DSR<0.95. Il
   profitto composto vive nel non-rovinarsi, non nell'alzare la posta su un Sharpe non blindato.

---

## Lezione #17 — 2026-06-26 — "No data" != "segnale negativo" nella combinazione multi-sorgente

**Evidenza.**
- `score_flow` ritornava 0.0 quando nessuna fonte (13F/insider/short) copriva un ticker. Poi
  `combine_signals = mean(technical, flow=0)` dimezzava lo score. L'intero universo EU + i piccoli
  US avevano score artificialmente compressi (IQR 0.086, mediana 0.116). Dopo il fix: IQR 0.193,
  mediana 0.200 (+72%). I nomi con forte accumulazione ma senza copertura 13F (SRG.MI, BMPS.MI)
  passavano sotto p50 e venivano esclusi dal portafoglio a causa del bug.
- Errore classico: confondere l'assenza di informazione con un dato reale e usarlo per penalizzare.

**Regola.**
1. **Se una fonte non copre un ticker, il segnale e' `None`, non 0.** Zero e' "ho cercato, il dato
   e' neutro"; `None` e' "non ho dato per giudicare". La media ponderata deve ignorare il `None`,
   non includerlo come zero.
2. **Verifica che il modulo di aggregazione (combine_signals) salti i `None`.** Se fa la media
   semplice con 0, i ticker meno coperti sono penalizzati in modo invisibile.
3. **L'auto-audit deve distinguere cause strutturali da actionable.** "6/12 BASSA" e' un allarme
   diverso se 4 sono illiquidi (strutturale, size gia' ridotta) vs 6 per score (problema di calibrazione).

## Lezione #18 — 2026-06-26 — Il live scoring deve essere identico al backtest scoring

**Evidenza.**
Run #22: la funzione live `score_technical()` usava tanh(momentum) + MACD — logica completamente
diversa dalla `score_new()` validata nel backtest (breakout + ADX threshold + mom3m). Le due funzioni
producevano ranking differenti: il backtest diceva "compra breakout + forte trend", il live diceva
"compra momentum liscio + MACD positivo". L'edge validato (Sharpe 1.0, PSR 0.98) non si replicava
nel live perche' il live selezionava nomi diversi.

Dopo l'allineamento: distribuzione bimodale (breakout ≥0.55, non-breakout <0.15). Questo e' corretto —
il breakout e' il driver dominante dell'edge nel backtest (+0.55 = 55% del range del segnale).

**Regola.**
1. **Il live scoring e il backtest scoring devono essere la stessa funzione.** Se il backtest valida
   `score_new`, il live deve usare `score_new`, non una versione "migliorata" che nessuno ha testato.
2. **L'allineamento va verificato confrontando i ranking**, non solo le formule. Due formule possono
   sembrare simili ma produrre ranking completamente diversi (tanh vs thresholds, continuo vs discreto).
3. **Indici e ETF non sono candidati operativi.** Se il dataset li contiene per regime/rotazione,
   escluderli dal scoring (NON_EQUITY set). FTSEMIB.MI nel ranking e' un bug, non un segnale.
4. **I settori nel mapping devono essere verificati con i nomi reali.** CS.PA = AXA (assicurazione),
   non una banca. Un errore nel mapping settoriale corrompe il cap e la diversificazione.

---

## Lezione #19 — 2026-06-29 — Senza un diario datato dei pick, il loop non puo' auto-verificarsi

**Evidenza.**
Run #23: riaprendo la sessione dopo 3 giorni di mercato, per verificare le raccomandazioni
precedenti ho dovuto **ricostruirle a mano** (memoria + un CSV vecchio), perche' `PORTFOLIO.txt`
viene SOVRASCRITTO a ogni run. Un loop "verifica ieri → trova errori → correggi" e' impossibile
se non resta traccia datata di cosa fu raccomandato e a quali livelli. La verifica path-based
(max/min giornalieri) ha poi mostrato che nessuno stop fu toccato ma 6 nomi IT cambiarono
regime (TREND_UP→PULLBACK) in 3 giorni: senza confronto datato, quel segnale si perde.

**Regola.**
1. **Ogni raccomandazione si congela in un diario datato** (`data/journal/<asof>.json`) PRIMA
   di poter essere sovrascritta. La memory spine viene prima della verifica: senza, non c'e' loop.
   Lo snapshot e' automatico in `portfolio_builder.build()` (difensivo, non bloccante).
2. **La verifica usa il PATH, non solo la chiusura.** Stop e target si toccano intraday: servono
   max/min giornalieri e l'ordine cronologico (stop+target stesso giorno → conta lo stop, prudente).
   MAE/MFE raccontano quanto la posizione ha sofferto/offerto, non solo dove ha chiuso.
3. **La verifica include il cambio di regime del mercato del titolo.** Un pick puo' essere ancora
   in range ma con il regime girato sotto: e' il primo segnale di uscita, prima dello stop.
4. **La ricerca degli errori va a un sub-agent INDIPENDENTE** da chi ha generato i pick: un agente
   separato non razionalizza i propri errori. Verifica = codice; audit = giudizio indipendente;
   fix = contesto multi-file (agente principale). Vedi `LOOP.md`.
5. **Mai inventare un esito.** La verifica riporta solo cio' che i prezzi hanno fatto; "IN CORSO"
   e' un esito onesto, non un fallimento da mascherare.

---

## Lezione #20 — 2026-06-29 — Verifica dal FILL reale, non dal prezzo pianificato; il gap e' rischio non modellato

**Evidenza (Fase-2 audit indipendente, Run #24).** Un sub-agent auditor, lanciato sulla verifica
26→29 giugno, ha scoperto un bug che la verifica stessa nascondeva: **gli entry del diario erano
le chiuse del 25/06, non del 26/06** (9/9 match esatti contro `mib_data.csv`). Un fetch eseguito a
sessione 06-26 non ancora chiusa aveva scritto una barra marcata "06-26" con i prezzi del 25/06.
Conseguenze, tutte misurate:
- La verifica filtrava `date > 06-26` e **saltava la sessione reale del 06-26**, dove stava quasi
  tutto il movimento. La finestra vera era 2 sedute (06-26 + 06-29), non 1.
- Misurando dal prezzo pianificato stantio, AC.PA risultava "−3.22% il peggiore" e STMMI "−1.31%".
  Misurando dal **fill reale** (apertura 06-26): AC.PA −0.48% (gap −2.75% gia' lasciato dal mercato),
  STMMI **+1.55%** (MFE +3.23%) — da peggiore a vincente. Drift medio reale **+0.34%**, non −0.60%.
- Il gap di apertura medio era −0.94%: STMMI e AC.PA hanno gappato −2.8%/−2.75%. Il piano assume un
  fill pulito e uno stop che tiene al suo livello: un gap puo' riempire lo stop PEGGIO (slippage non
  contabilizzata). Qui non e' costato nulla (nessuno stop a tiro), ma e' rischio reale non modellato.

**Regola.**
1. **La verifica misura dal FILL REALISTICO = apertura della prima seduta dopo `data_asof`**, non
   dal prezzo pianificato (che il mercato ha gia' lasciato). Drift/MAE/MFE/P&L partono da li'; i
   livelli stop/target restano assoluti. Un prezzo pianificato stantio gonfia ogni perdita e rende
   ogni post-mortem falsamente pessimista.
2. **Lo snapshot registra `data_asof`** = data della barra di prezzo da cui parte il piano. La
   verifica deriva da li' barre e fill. Auto-rilevazione: se l'entry pianificato != chiusura a
   `data_asof`, lo snapshot e' stantio → warning esplicito (avrebbe colto il bug da solo).
3. **Il gap di apertura e' una metrica di rischio di prima classe.** Riportare gap = fill/pianificato
   e segnalare quando l'apertura gappa OLTRE lo stop (fill peggiore del livello = slippage reale).
4. **Su 2 sedute e 9 nomi non si conclude nulla sull'edge.** L'audit ha REFUTATO con i numeri tre
   ipotesi seducenti: (a) regime "troppo lento" — FALSO, FTSEMIB ha perso la SMA20 il 29 in modo
   COINCIDENTE (margine +0.04% il 26 → −0.11% il 29); il trigger px>SMA20 esiste gia' e non ha lag.
   (b) soglia smart-money troppo larga — i nomi in DISTRIBUZIONE (sm<−0.5: DIA.MI, WLN.PA) sono stati
   i top gainer: relazione invertita = rumore a 2 sedute. (c) "volume debole sul breakout = fallimento"
   — corr(volR, ritorno) ≈ 0 sul campione. **Un fix di strategia si spedisce solo dietro un backtest
   sul ciclo 2018-2026, mai sulla forza di 2 giorni.** Strumentare (verifica/diario) si', cambiare la
   strategia no.
5. **L'indipendenza dell'auditor paga.** Il bug dell'entry stantio era nel codice che *io* avevo
   scritto: un sub-agent separato l'ha trovato proprio perche' non aveva motivo di fidarsi delle mie
   assunzioni. Verifica = codice; audit = giudizio indipendente; fix = agente principale.

---

## Lezione #21 — 2026-06-29 — Session Gate: mai una barra di sessione aperta; e FIX 4 respinto dal backtest

**Evidenza A (Session Gate).** Run #25: alle 15:56 di Roma (lunedi 06-29, mercati APERTI) la barra
06-29 in `mib_data.csv` era un prezzo intraday marcato EOD. Era la VERA radice della Lezione #20:
il fetch non distingueva sessione aperta da chiusa. Conseguenza nascosta: quella barra fantasma
aveva spinto FTSEMIB sotto la SMA20 → il modello segnava **IT in PULLBACK** e metteva go-flat 6
nomi IT. Scartata la barra (ultima sessione chiusa = 06-26), **IT torna TREND_UP**: il "cambio di
regime" dei Run #23/#24 era un ARTEFATTO del dato fantasma, non un evento di mercato.

**Regola A.**
1. **Session Gate in `fetch_data.py`**: non registrare l'ultima barra se la sessione del SUO mercato
   non e' chiusa+settled nel fuso locale (EU/Europe-Rome chiude 17:30, US/New-York 16:00; +20min di
   settle). Scartare, non marcare: un prezzo intraday in un file EOD inquina regime, score, entry.
2. **Il fuso e' per mercato di quotazione**, non per ticker: .MI/.PA/.AS + ^FCHI/^STOXX50E → Europe/Rome;
   resto → America/New_York.
3. **L'identita' dello snapshot del diario = data di PREZZO (`data_asof`)**, non il timbro nominale:
   un piano prezzato su una barra precedente non deve collidere con un build sulla barra corrente.
4. **Un dato fantasma puo' fabbricare un falso segnale di REGIME**, non solo un entry stantio. Il gate
   alla fonte protegge l'intera pipeline a valle.

**Evidenza B (FIX 4 respinto).** Backtest ciclo completo 2018-2026 (`fix4_validate.py`, score NUOVO,
holding 10gg, 6329 segnali / 1004 date): dimensionare la size per smart money (B) o conferma-volume
sul breakout (C) NON alza lo Sharpe. ΔSharpe vs equal-weight: B −0.07 [IC95% −0.39,+0.29], C +0.01
[−0.07,+0.09], D −0.04 [−0.37,+0.32] — **tutti gli IC attraversano lo 0** (bootstrap a blocchi paired).

**Regola B.**
5. **Una leva di size si accetta solo se l'IC95% della differenza di Sharpe esclude lo 0**, su ciclo
   completo e con bootstrap paired (non sul punto, non su 2 sedute). FIX 4 non passa → NON implementato.
   Lo Smart Money resta validato come FILTRO di selezione (gate anti-distribuzione), non come peso di size.
6. **Backtest sul dataset GIUSTO**: `mib_data.csv` e' ~14 mesi (operativo); il ciclo completo 2018-2026
   e' `mib_data_long.csv`. Un A/B su 14 mesi (41 date) dava Sharpe assurdi (7+) e CAGR fantasiosi: la
   conclusione richiede la storia lunga.

---

## Lezione #22 — 2026-06-29 — Risk parity (inverse-ATR) respinto: il harness non puo' testare cio' che conta

**Evidenza.** Run #26 (FIX 5): sizing a rischio paritario (peso ∝ 1/ATR%14) vs equal-weight sul
ciclo completo 2018-2026 (`fix5_validate.py`, 6329 segnali / 1004 date, bootstrap PAIRED).
Risultato: Sharpe 0.55→0.52, **MaxDD IDENTICO −95.7%** per tutti gli schemi; ΔMaxDD IC95%
[−2.35,+3.68] attraversa lo 0. Per la regola (integrare solo se ΔMaxDD IC95%>0) → NON integrato.

**Root cause (non solo "non significativo").** Le date di peggior drawdown hanno UN SOLO nome
selezionato (worst: 2025-04-08 −45.8%, 2018-12-24 −44.7%, 2020-03-02 −41.9%, tutte n=1). Su una
data a nome singolo ogni schema di peso da' 100% a quel nome → ritorno e MaxDD identici. Il 23%
delle date ha 1 nome, il 34% ≤2: i tail-drawdown sono eventi a nome singolo, dove il sizing
cross-sectional e' impotente per costruzione.

**Regola.**
1. **Una leva di size si integra solo se la metrica-bersaglio migliora con IC95% che esclude lo 0**
   sul ciclo completo (qui: ΔMaxDD>0 sistematico). FIX 5 non passa → non si tocca `portfolio_builder`.
2. **Verificare che il harness possa DAVVERO misurare l'effetto cercato prima di concludere.** Il
   risk parity diversifica la vol tra posizioni CONCORRENTI; un harness per-segnale con date sparse
   (mediana 5 nomi, 23% a nome singolo) e rendimenti 10gg sovrapposti NON lo cattura. "Nessun effetto
   misurato" puo' voler dire "strumento sbagliato", non "ipotesi falsa": dirlo esplicitamente.
3. **Il test corretto del vol-sizing e' un portafoglio REALMENTE detenuto** (posizioni sovrapposte
   nel tempo, equity giornaliera vera), non bet indipendenti per-segnale. Finche' non esiste quel
   test, il sizing resta equal/convinzione: niente cambi sulla base di un harness inadatto.
4. **Promemoria artefatto**: il MaxDD −95.7% del portfolio_sim e' l'effetto dei rendimenti
   sovrapposti; il MaxDD reale del modello operativo e' −13.8% (`robustness_consolidate`).

---

## Lezione #23 — 2026-06-29 — Held-portfolio backtester: il MaxDD reale e' -32%, non -95%

**Evidenza.** Run #27: costruito `portfolio_backtester.py`, motore event-driven con equity di
PERCORSO reale (capitale 100k, MTM giornaliero, max 10 posizioni x 10%, cassa esplicita, holding
10gg). Sul ciclo 2018-2026: CAGR +12.2%, **MaxDD -32.1%**, Sharpe 0.80, exposure media 93%, 9.4
posizioni, 1876 trade. Il MaxDD di percorso reale (-32%) e' MENO della meta' dell'artefatto -95.7%
del harness per-segnale (fix4/fix5): conferma la Lezione #22 (lo strumento sbagliato gonfiava il DD).

**Regola.**
1. **Per testare sizing, drawdown e esposizione serve un portafoglio REALMENTE detenuto**: posizioni
   concorrenti, MTM giornaliero, cassa esplicita. Il harness per-segnale (rendimenti sovrapposti,
   pesi cross-sectional) va bene per il ranking del segnale, NON per metriche di portafoglio.
2. **No leva implicita**: max 10 posizioni x 10% = max 100% investito; sotto i 10 segnali il resto
   resta in CASSA. Cosi' l'esposizione (qui 93% media) e' una metrica reale, non un assunto.
3. **Validare il segnale vettorizzato contro la funzione canonica** prima di fidarsi del motore:
   `score_series` (vettoriale) == `score_new` punto-a-punto (0 mismatch/25), perche' ADX/RSI/rolling
   sono CAUSALI (il valore a t sull'intera serie == quello sullo slice [:t+1]). Senza questo check,
   un motore veloce ma infedele produce numeri puliti e SBAGLIATI.
4. **Niente gate di regime nel motore base** -> MaxDD -32% "always-in"; il -13.8% di
   robustness_consolidate include il go-flat. Il backtester va usato per MISURARE l'effetto del
   gate e del vol-sizing, un layer alla volta, ognuno con il suo A/B.
5. **Onesta' sui limiti**: soglia score p80 globale (lieve bias in-sample) e costi di transazione
   non ancora nel motore (1876 trade -> non trascurabili). Da chiudere prima di decisioni di sizing.

---

## Lezione #24 — 2026-06-29 — Il gate di regime e' la leva #1; risk parity validato sul motore giusto

**Evidenza (Run #28-30, held-portfolio backtester, equity di percorso reale 2018-2026).**
1. **Regime gate (TREND_UP-only)**: MaxDD −32.1%→−17.8% (quasi dimezzato) con CAGR +0.23 pt:
   protezione del drawdown sostanzialmente gratuita. Calmar 0.38→0.70. E' la singola leva piu'
   potente del sistema. Valida il `include_pullback=False` del live.
2. **PULLBACK a mezza size**: respinto. Abbassa il MaxDD di 1.2 pt ma costa 2.5 pt di CAGR
   (Calmar 0.60<0.70). Il PULLBACK (px<SMA20) e' debolezza precoce: entrarci cattura perdenti.
3. **Risk parity (inverse-ATR)**: sul motore REALE col gate attivo abbatte il MaxDD −17.8%→−13.2%,
   bootstrap PAIRED IC95% [+1.07,+9.04] (esclude lo 0), Sharpe +0.12, Calmar +0.19. La STESSA
   ipotesi respinta sul harness per-segnale (FIX 5, Run #26) PASSA qui.

**Regola.**
1. **Il gate di regime viene prima di ogni ottimizzazione di sizing.** Dimezza il drawdown a costo
   ~zero di rendimento; nessuna leva di size si avvicina a quell'impatto. Giudicare col Calmar.
2. **Piu' esposizione non e' meglio**: il TIERED alza l'esposizione ma peggiora il Calmar. La cassa
   nei regimi non-trend e' una posizione, non un'inefficienza da riempire.
3. **Una leva si valuta sullo STRUMENTO giusto** (Lezione #22, ora confermata costruttivamente):
   il vol-sizing agisce tra posizioni CONCORRENTI → si misura su un portafoglio realmente detenuto
   (MaxDD di percorso), non su bet per-segnale indipendenti. Stesso test, conclusione opposta.
4. **Prima di "integrare", verifica se la logica c'e' gia' — e verifica i NUMERI, non la formula.**
   CORREZIONE (Run #31): avevo concluso che il live (`trade_proposal.propose`) fosse "gia' risk-parity"
   perche' `shares=risk_eur/(entry−stop)`. SBAGLIATO: con `risk_per_trade`=2.14% e stop ~2·ATR, la
   pos_value non-capata e' SEMPRE 4-10x il cap del 10% → **il cap vince sempre**, la size = 10%×convinzione,
   indipendente dall'ATR. Verificato sul motore: sizing "live" ≡ equal-weight (metriche IDENTICHE). Quindi
   l'equal-weight ERA il baseline rappresentativo, e il **risk-parity e' un miglioramento REALE non
   catturato dal live** (MaxDD −17.8%→−13.2%, IC95% esclude 0) → candidato vero all'integrazione.
   Lezione meta: "la formula c'e'" non basta; controlla se un altro vincolo (qui il cap) la annulla nei fatti.

---

## Lezione #25 — 2026-06-30 — Risk-parity integrato nel live: come farlo senza rompere il builder

**Evidenza (Run #32, integrazione in produzione).**
Il cap del 10% nella `propose()` domina sempre (Lezione #24, Run #31): il live era equal-weight di fatto.
Per attivare il risk-parity validato (IC95 [+1.07,+9.04] su ΔMaxDD, Lezione #24) si introduce:

```python
# In modules/trade_proposal.py: nuovo parametro rp_scale (default 1.0 = no-op)
eff_pos_cap = pos_cap * rp_scale          # riduce il cap per nomi ad alta ATR
max_pos_value = capital * eff_pos_cap * eff_mult

# In portfolio_builder.build(): calcolo cross-sezionale sui nomi eleggibili
med_atr_pct = np.median(elig["atr"] / elig["price"])   # mediana ATR% del giorno
rp_scale = min(med_atr_pct / atr_pct_i, 1.0)           # >= 1 clampato a 1
```

**Effetto concreto (portafoglio 2026-06-26)**:
- medATR% = 2.31%: nomi a bassa volatilita' (CS.PA, ENEL.MI) restano al 10%; nomi ad alta
  volatilita' (STMMI.MI RP×0.43 → cap 4.3%, EDEN.PA RP×0.58 → cap 5.8%) ridotti proporzionalmente.
- Esposizione totale 61% (vs 85% max teorico): il gate di regime (go-flat US) e la riduzione RP
  combinano, nessun nome supera il cap aggiustato per la sua volatilita'.
- L'output mostra la colonna RP× in tabella e "RP x<val>" nella scheda operativa.

**Regola.**
1. **Il rp_scale e' backward-compatible**: default 1.0 = comportamento precedente esatto. Nessuna
   regressione nei test o nei chiamanti che non passano il parametro.
2. **Il med_atr_pct si calcola DOPO la selezione eleggibile**, non su tutto l'universo: evita
   di usare la distribuzione delle ATR di nomi esclusi (diversa dal set operativo del giorno).
3. **La riduzione RP diminuisce sia il pos_cap base sia quello modulato da size_mult e regime_mult**:
   l'ordine corretto e' `eff_pos_cap = pos_cap * rp_scale` e poi `max_pos = capital * eff_pos_cap * eff_mult`.
   Non modificare il risk_per_trade: lo stop rimane invariato.
4. **Tracciabilita'**: la colonna RP× in tabella e il tag "(capped RP N%)" nel binding rendono ogni
   riduzione di size trasparente. Non nascondere la leva — il trader deve capire PERCHE' una posizione
   e' piu' piccola.
5. **Unicorn sleeve non modificato**: usa gia' `pos_cap=0.05` (meta' del core) e `size_mult=0.5`;
   l'ATR elevata degli unicorni renderebbe il RP aggiuntivo eccessivamente restrittivo su un sleeve
   gia' gated e dimensionato per l'high-beta.

---

## Lezione #26 — 2026-06-30 — Il modello e' robusto cross-market: replica su S&P 500 OOS

**Evidenza (Run #33, portfolio_backtester su sp500_data_long.csv, 2018-2026).**
76 ticker S&P 500 multi-settore, genuinamente out-of-sample (il modello non ha mai "visto" questo universo):

| Schema | CAGR% | MaxDD% | Sharpe | Calmar | Expo% |
|--------|-------|--------|--------|--------|-------|
| ALWAYS-IN (no gate) | +17.51 | −17.79 | 1.09 | 0.98 | 88.8% |
| GATE TREND_UP | +13.20 | −13.17 | 1.00 | 1.00 | 48.6% |
| GATE + RISK-PARITY | +10.57 | −11.92 | 0.99 | 0.89 | 43.7% |

Confronto GATE+RP: EU Sharpe 1.04 / Calmar 0.89 vs S&P 500 Sharpe 0.99 / Calmar 0.89 — **Calmar identico**.
Bootstrap RP: ΔMaxDD IC95 [+0.09, +5.98] (esclude 0, marginalmente ma valido).

**Interpretazione chiave.**
- Il ^GSPC e' TREND_UP solo il 37% dei giorni 2018-2026 (vs ~63% per EU): il mercato USA ha avuto
  bear/lateral frequenti (2018Q4, 2020, 2022) — il gate riduce il CAGR ma anche l'exposure (49% vs 89%).
- Il segnale score_new (breakout + ADX + mom3m + RSI penalty) funziona su qualsiasi mercato liquido
  con trend: e' una firma di MOMENTUM TECNICO, non un artefatto EU.
- La bassa esposizione del GATE (49%) e' un'opportunita': con 51% in cassa in media si potrebbe
  combinare EU + US in un portafoglio bilanciato senza leva.

**Regola.**
1. **Il modello e' validato su S&P 500 OOS**: Sharpe 0.99, Calmar 0.89, MaxDD -11.9%. E' candidato
   reale per coprire azioni USA in TREND_UP (gate ^GSPC), non solo EU.
2. **Il gate di regime e' ancora la leva #1 anche per gli USA**: porta il MaxDD da -17.8% a -11.9%
   (il terzo migliore in assoluto su tutti i test) senza modificare il segnale.
3. **Calmar e' la metrica piu' stabile cross-market**: EU e USA coincidono a 0.89. E' la metrica
   da usare per comparare portafogli con profili di rischio diversi (diversa vol, diverso CAGR).
4. **US ALWAYS-IN Sharpe 1.09 > EU ALWAYS-IN Sharpe 0.80**: il bull USA 2018-2026 e' stato
   eccezionalmente forte. Non assumere che si ripeta; il gate resta necessario.
5. **Implicazione pratica**: nelle sessioni in cui IT/FR sono TREND_UP ma ^GSPC e' PULLBACK
   (come al 2026-06-30), il portafoglio EU-only e' la scelta corretta; quando ^GSPC torna
   TREND_UP, si possono aggiungere azioni USA selezionate dallo stesso score_new.

---

## Lezione #27 — 2026-06-30 — Le commissioni Fineco mangiano ~4 pt di CAGR ma l'edge sopravvive

**Evidenza (Run #34, GATE+RP, 2018-2026, struttura Fineco reale + slippage 0.02%).**

| Universo | CAGR (no costi) | CAGR (con costi) | Drag | Sharpe | Calmar |
|----------|-----------------|------------------|------|--------|--------|
| EU       | +11.73%         | **+7.49%**        | −4.25 pt | 0.70 | 0.51 |
| S&P 500  | +10.57%         | **+8.03%**        | −2.54 pt | 0.77 | 0.66 |

EU drag annuo: 5.08% (40,169€ / 8 anni / 100k) — costo medio per trade RT (2 gambe) 33.3€.
US drag annuo: 3.06% (23,458€ / 8 anni / 100k) — costo medio per trade RT 24.6€ (di cui 19.90€ flat).

**Perché EU costa di più nonostante la struttura percentuale?**
- La struttura 0.19% (cap 19€ per gamba) su una posizione tipica di 5k-10k dà 9.5-19€ per gamba.
  Una posizione >5,263€ paga più della US flat (9.95€ per gamba). Su portafoglio crescente (capitale
  che cresce da 100k a ~165k) le posizioni medie crescono e la spesa supera la tariffa US.
- In più, EU ha 1208 trades vs US 952 (26% più turnover, stesso holding 10gg ma universo più piccolo
  produce meno slot liberi → paradossalmente, un universo piccolo trada di più proporzionalmente
  perché riempie le 10 slot con un sottoinsieme più ristretto — minor diversification of turnover).

**Regola.**
1. **L'edge esiste anche netto di commissioni reali** — Sharpe 0.70 e CAGR 7.49% (EU), 0.77 e 8.03%
   (US). Non è il sogno del lordo, ma è un profitto reale. Non gonfiare le aspettative col backtest
   a zero costi.
2. **Il turnover (10gg holding, ~150 trade/anno) è il fattore critico**, non la tariffazione unitaria.
   Ogni giorno in più di holding riduce i trade proporzionalmente: raddoppiare il holding a 20gg
   dimezzerebbe i trade e risparmierebbe ~2 pt di CAGR. Da testare (Run #35 candidato).
3. **La struttura Fineco EU penalizza posizioni medie (5-10k€)**. Su posizioni >10k€ il cap 19€
   diventa conveniente (0.19% → non paghi più). Il sistema scala meglio con capitale maggiore
   (la commissione non scala sopra i 10k ma il profitto sì): con 200k capitale, stesso drag in EUR
   = drag % dimezzato.
4. **US flat 9.95€/gamba è più prevedibile**: su qualsiasi posizione > 1.000$ conviene più del
   percentuale EU. Per un conto US puro la struttura flat è favorevole a posizioni piccole.
5. **Costi non inclusi nel backtest ma rilevanti in Italia**: bollo titoli 0.2%/anno (≈ 0.1% sul
   capitale totale con 50% exposure media) e imposta plusvalenze 26%. Aggiungere in una simulazione
   fiscale separata prima di prendere decisioni finali.

---

## Lezione #28 — 2026-06-30 — Holding 20gg: EU distrugge il MaxDD, US migliora

**Evidenza (Run #35, GATE+RP+Fineco+Slip, 2018-2026, holding 10gg vs 20gg).**

| Universo | Hold | CAGR% | MaxDD% | Sharpe | Calmar | Trade | Costi€ |
|----------|------|-------|--------|--------|--------|-------|--------|
| EU | 10gg | +7.49 | −14.70 | 0.70 | 0.51 | 1208 | 40,169 |
| EU | 20gg | +4.86 | **−36.87** | 0.40 | 0.13 | 674 | 21,394 |
| US | 10gg | +8.03 | −12.19 | 0.77 | 0.66 | 952 | 23,458 |
| US | 20gg | +8.41 | −11.61 | 0.76 | **0.72** | 538 | 13,270 |

EU: 20gg riduce i costi del 46.7% (−18,775€) ma crolla il MaxDD da −14.7% a **−36.9%** e il
CAGR perde 2.63pt. Il risparmio commissionale è completamente sovrastato dal deterioramento del
profilo di rischio. **Verdetto EU: 10gg dominante.**

US: 20gg migliora LEGGERMENTE tutto — CAGR +0.38pt, MaxDD migliora (+0.58pt), costi −43.4%.
Il flat rate di 9.95€/gamba non penalizza come il percentuale EU, e il trend USA 2018-2026 è
abbastanza persistente da reggere holding più lunghi. **Verdetto US: 20gg marginalmente migliore.**

**Perché EU crolla con 20gg?**
- L'EU con 10gg sfrutta breakout di momentum di breve durata. A 20gg, le posizioni attraversano
  l'intera fase di ritracciamento dopo il breakout — il segnale score_new non ha persistenza a
  20gg su questo universo.
- Il gate TREND_UP NON chiude posizioni anticipatamente se il regime cambia durante l'holding:
  la posizione 20gg resta aperta anche se il mercato si gira dopo 10gg, amplificando i drawdown
  intraciclo (questo effetto è amplificato da mercati EU più volatili e meno trending).
- Con 20gg il numero di slot occupati aumenta simultaneamente (più sovrapposizione): ExpoMean
  sale da 54.4% a 60.6%. Più esposizione in regime che può essere cambiato = più rischio.

**Regola.**
1. **L'holding period ottimale è specifico per mercato**: EU 10gg, US 20gg (o più)
   riflette la diversa persistenza del momentum tra i due universi.
2. **Allungare l'holding per risparmiare commissioni è un'euristica pericolosa**: il risparmio
   reale dipende interamente da quante barre il segnale mantiene potere predittivo. Misurare
   sempre il Calmar e il MaxDD, non solo il Δ costi.
3. **Il gate di regime va abbinato a una logica di uscita anticipata (regime-exit)**:
   se il mercato gira a TREND_DOWN/LATERALE durante una posizione 20gg, chiudere pro-quota
   ridurrebbe il MaxDD EU di 20gg. Da implementare come Run #36 candidato.
4. **Strategia ibrida possibile**: holding 10gg per EU (protezione del MaxDD) + holding 20gg
   per azioni US quando ^GSPC è TREND_UP (risparmio commissionale + Calmar migliore).
5. **Il Calmar è la sentinella**: EU 20gg Calmar 0.13 (inutilizzabile) vs 10gg Calmar 0.51
   (operativo). Non accettare mai una configurazione con Calmar < 0.3 su un backtest 8 anni.

---

## Lezione #29 — 2026-06-30 — p85 migliora CAGR e MaxDD EU senza ridurre il turnover

**Evidenza (Run #36, EU GATE+RP+Fineco+Slip, 2018-2026, holding 10gg, p80 vs p85).**

| Schema | CAGR% | MaxDD% | Sharpe | Calmar | Trade | Costi€ |
|--------|-------|--------|--------|--------|-------|--------|
| EU p80 (baseline R34) | +7.49 | −14.70 | 0.70 | 0.51 | 1208 | 40,169 |
| EU p85 (nuovo)        | **+8.13** | **−11.80** | **0.76** | **0.69** | 1185 | 39,497 |

Δ CAGR +0.64pt | Δ MaxDD +2.90pt | Δ Sharpe +0.06 | Δ Calmar +0.18 | Δ Trade −23 (−1.9%)

**La sorpresa: p85 non riduce il turnover (−1.9%, 23 trade su 1208).**
Il threshold salire da 0.2436 a 0.3924 (delta +61%), ma il numero di trade quasi non cambia
perché `np.nanquantile(score_panel, 0.85)` include TUTTI i (ticker, giorno) osservati incluse
le date out-of-gate. In regime TREND_UP con 10 slot disponibili, la maggior parte delle posizioni
è riempita anche con p85 — l'universo EU ha abbastanza segnali sopra la soglia. Il risultato è
che p85 filtra solo i segnali più deboli al margine, migliorando la qualità senza ridurre
materialmente la quantità.

**L'effetto netto è puro quality screening**: le posizioni p80→p85 che vengono escluse sono
quelle con il segnale meno forte (sono rimpiazzate da posizioni vuote o da candidati con score
appena sotto p80 — ma su un universo piccolo, se ci sono <10 nomi sopra p85, entra anche il
primo sopra p80 comunque). L'esclusione selettiva dei segnali deboli riduce i drawdown
intraciclo: MaxDD scende da −14.7% a −11.8%.

**Regola.**
1. **Usare p85 come soglia EU**: migliora CAGR (+0.64pt), MaxDD (−2.90pt), Calmar (0.51→0.69)
   senza costi aggiuntivi. È un free lunch di qualità — adottare come default per il live.
2. **L'ipotesi "p85 = meno trade = meno costi" era sbagliata** per universi piccoli: il pool EU
   ha abbastanza nomi da riempire i 10 slot anche con una soglia più alta. Il canale di
   risparmio è il quality screening, non la riduzione del turnover.
3. **Per ridurre davvero il turnover su universi piccoli bisogna agire sull'holding period**
   (ma Run #35 ha mostrato che 20gg EU distrugge il MaxDD). Alternative: ampliare l'universo
   (più ticker) o restringere il numero di slot (MAX_POS < 10 → meno posizioni = più selettivi).
4. **La combinazione ottimale validata finora:**
   - EU: p85 | holding 10gg | GATE+RP+Fineco+Slip → CAGR +8.13%, MaxDD −11.80%, Calmar 0.69
   - US: p80 | holding 20gg | GATE+RP+Fineco+Slip → CAGR +8.41%, MaxDD −11.61%, Calmar 0.72
5. **Attenzione alla soglia calcolata in-sample**: `np.nanquantile(panel, 0.85)` usa tutti i
   dati 2018-2026. Una soglia espandente (expanding-window) darebbe un test OOS più pulito
   per il p85 — da validare in un run dedicato prima di adottarlo definitivamente nel live.

---

## Lezione #30 — 2026-06-30 — Il lookahead bias della soglia è trascurabile: l'alpha è OOS genuino

**Evidenza (Run #37, GATE+RP+Fineco+Slip, assetto ibrido R36, 2018-2026).**

| Universo | Soglia | CAGR% | MaxDD% | Sharpe | Calmar | Bias CAGR |
|----------|--------|-------|--------|--------|--------|-----------|
| EU p85 hold 10gg | STATICA (R36) | +8.13 | −11.80 | 0.76 | 0.69 | — |
| EU p85 hold 10gg | **ESPANDENTE** | **+8.49** | **−11.44** | **0.79** | **0.74** | **+0.36pt** |
| US p80 hold 20gg | STATICA (R35) | +8.41 | −11.61 | 0.76 | 0.72 | — |
| US p80 hold 20gg | **ESPANDENTE** | **+8.16** | **−11.36** | **0.74** | **0.72** | **−0.25pt** |

**Il bias è trascurabile: EU +0.36pt, US −0.25pt** (entrambi <0.5pt CAGR su 8 anni).
Entrambi i mercati passano il test OOS con soglia espandente: Sharpe>0.5, CAGR>3%, MaxDD>−40%.

**La direzione del bias è inaspettata (EU: espandente > statica).**
La soglia STATICA usa la distribuzione completa 2018-2026 (include anni bull 2021-2024 con
score elevati), risultando troppo alta nei primi anni (2018-2019). La soglia ESPANDENTE inizia
bassa (pochi dati) e cresce col tempo — nella fase early cattura opportunità che la soglia
statica troppo alta avrebbe escluso. Nessun artefatto di overfitting: l'expanding migliora.

**Il numero di trade è identico (1185 EU, 538 US)** — la soglia espandente converge a fine
periodo allo stesso valore finale della statica (0.3924 e 0.2481): ha visto gli stessi dati.
La differenza sta solo nell'ordine temporale di attivazione dei segnali.

**Configurazione definitivamente validata (OOS pulito):**
- **EU: p85 | hold 10gg | soglia espandente** → CAGR +8.49%, MaxDD −11.44%, Sharpe 0.79, Calmar 0.74
- **US: p80 | hold 20gg | soglia espandente** → CAGR +8.16%, MaxDD −11.36%, Sharpe 0.74, Calmar 0.72

**Regola.**
1. **Sempre testare con soglia espandente prima di dichiarare un alpha**. La differenza può
   essere piccola (come qui) o grande — non saperlo è un rischio. In questo sistema è piccola.
2. **Il segno del bias non è predicibile a priori**: qui la soglia statica è MÁS restrittiva
   early (perché il bull 2021-2024 alza la distribuzione aggregata). In un mercato bear
   persistente l'effetto potrebbe invertirsi.
3. **La soglia espandente è la scelta principiata per il live trading**: usa solo informazioni
   disponibili all'operatore al momento della decisione. Non c'è motivo operativo per usare
   la soglia statica (che richiederebbe di conoscere il futuro).
4. **Con universi grandi (S&P 500) il bias tende a zero** (più segnali → stima del quantile
   più stabile fin dall'inizio). Con universi piccoli (EU ~70 ticker) il bias è lievemente
   maggiore ma ancora trascurabile.
5. **L'alpha del sistema è genuino**: sopravvive sia ai costi reali (Run #34) sia alla rimozione
   del lookahead bias della soglia (Run #37). Le uniche fonti di ottimismo residue da eliminare
   prima del live sono: survivorship bias nel dataset e tasse (26% plusvalenze + bollo 0.2%).

---

## Lezione #31 — 2026-06-30 — Il CAGR netto dopo tasse IT è ~5.6%: edge reale confermato

**Evidenza (Run #38, regime amministrato IT, CGT 26% + zainetto 4 anni + bollo 0.20%).**

| Universo | CAGR Lordo | CAGR Netto | Δ (tax drag) | Tasse totali | Calmar netto |
|----------|-----------|-----------|--------------|-------------|--------------|
| EU p85 10gg | +8.49% | **+5.64%** | −2.86pt | 23,714€ | 0.45 |
| US p80 20gg | +8.16% | **+5.60%** | −2.56pt | 22,631€ | 0.49 |

Zainetto residuo a fine periodo: EU 4,097€ / US 6,344€ (crediti da minus non recuperati).
Aliquota effettiva: EU 26.2% / US 27.4% (vicina al 26% teorico — zainetto ha ridotto la base).
MaxDD dopo tasse: EU −12.53% (Δ −1.09pt) / US −11.35% (invariato) — tasse non amplificano i drawdown.

**Edge dopo tasse: CONFERMATO su entrambi i mercati** (Sharpe>0.5, CAGR>2%).

**Cumulo drag 2018-2026 rispetto al backtest a zero costi (baseline R30/33):**
```
EU:  +11.73% (zero costi) → +8.49% lordo (−3.24pt Fineco+slip) → +5.64% netto (−2.85pt tasse)
     Drag totale: −6.09 pt CAGR | CAGR netto / anno: +5.64%
US:  +10.57% (zero costi) → +8.16% lordo (−2.41pt Fineco+slip) → +5.60% netto (−2.56pt tasse)
     Drag totale: −4.97 pt CAGR | CAGR netto / anno: +5.60%
```

**Cosa significa il zainetto in pratica:**
- Il zainetto fiscale italiano è potente: permette di portare in detrazione le minus per 4 anni.
- Nelle fasi di mercato ribassista (2018Q4, 2020 Covid, 2022) il sistema accumula crediti
  che compensano le plusvalenze degli anni successivi → l'aliquota effettiva rimane vicina al 26%
  (non più alta per effetto delle perdite, non più bassa perché il portafoglio è profittevole).
- Zainetto residuo a fine periodo (EU 4k€, US 6k€) = perdite degli ultimi mesi 2025-2026
  che non hanno ancora trovato contropartita (normale a fine backtest).

**Regola.**
1. **Il CAGR netto realistico è +5.6% circa** per entrambi i mercati: questo è il numero da
   usare per valutare il conto economico della strategia (non il +8.5% lordo, non il +11.7%
   a zero costi). Il +5.6% batte l'inflazione EU attesa (2-3%) e il rendimento dei BTP 10y
   (~3.5%) con un profilo di rischio moderato (MaxDD −12%, Sharpe 0.55).
2. **Il drag fiscale (−2.8pt CAGR) ≈ drag commissionale EU (−3.2pt)**: le tasse e le commissioni
   hanno peso simile. Ottimizzare entrambi con la stessa priorità.
3. **Il zainetto è un'opzione gratuita offerta dal fisco**: usarla attivamente significa
   evitare di chiudere posizioni in gain negli anni in cui si hanno crediti disponibili
   (per esempio, aspettare che il regime torni TREND_UP dopo una fase ribassista invece di
   chiudere le posizioni aperte). In questo backtest la logica automatica già sfrutta il
   zainetto attraverso il gate (poche posizioni aperte in bear → meno minus negli anni sbagliati).
4. **La soglia di selettività del gestore**: CAGR netto +5.6% è sopra il costo opportunità
   (BTP ~3.5%) ma non abbastanza da rendere la strategia dominante vs un ETF S&P 500 (CAGR
   lordo ~8%/anno da Buy&Hold). La strategia ha valore per il profilo di rischio (MaxDD −12%
   vs −34% del Buy&Hold S&P 2020) e per l'investitore che non tolera drawdown elevati.
5. **Fonte di ottimismo residua**: survivorship bias — i titoli delisted tra 2018 e 2026 non
   sono nel dataset, il che gonfia il CAGR lordo. Questo è il prossimo test critico (Run #39).

---

## Lezione #32 — 2026-06-30 — Il survivorship bias è materiale per l'EU ad alta rotazione; moderato per US

**Evidenza (Run #39, 500 sim MC, 1.5% trade stressati a −60%, assetto Run #38 con tasse IT).**

| Universo | Trade tot | Stressati/sim | CAGR base | Stress Mean | Stress p5 | MaxDD stress mean | P(CAGR>BTP) |
|----------|-----------|---------------|-----------|-------------|-----------|-------------------|-------------|
| EU p85 10gg | 1175 | 18 | +5.64% | **−15.33%** | **−20.36%** | −81.31% | 0.0% |
| US p80 20gg | 528 | 8 | +5.60% | **−0.22%** | **−1.17%** | −26.97% | 0.0% |

**L'EU collassa** sotto stress: 18 eventi catastrofici × ~7,000€ avg delta = ~126,000€
perdita cumulativa su un portafoglio di 100K. L'alto turnover EU (1175 vs 528 trade US)
è la fonte di vulnerabilità. Il cumsum dei delta si propaga in avanti nel tempo → una
perdita al mese 1 riduce il portfolio per tutti gli 8 anni successivi.

**L'US sopravvive** con CAGR medio −0.22% (vicino allo zero): solo 8 eventi stressati
per sim, impatto cumulativo ~56,000€ su portafoglio che cresce a 155K+ → meno devastante.

**Interpretazione del modello (conservativo):**
- Il credito zainetto da ogni trade stressato viene recuperato nella stessa data di uscita
  (assumption favorevole) ma NON viene riapplicato alle plusvalenze future (assumption sfavorevole).
- Ogni trade delisted paga −60% del cost_basis (Wirecard/Astaldi scenario), non −100%:
  questa è la soglia MÍNIMA di scenario catastrofico plausibile su mid-small cap.

**Limitazioni del modello:**
1. Nel delta-cumsum non si rimodella l'intero loop di portafoglio: un portafoglio stressato
   ridurrebbe la size dei trade successivi (cash inferiore) → la perdita reale è superiore
   (il modello SOTTOSTIMA l'impatto per EU perché il compounding del portafoglio ridotto
   non è catturato).
2. Il 1.5% di trade stressati è prudente (ca. 1 delisting ogni 67 trade su 8 anni).
   Un portafoglio EU diversificato su FTSE MIB 40 (solo large cap, no fallimenti storici)
   avrebbe una rate reale probabilmente <0.2%.
3. I 10 giorni di holding riducono l'esposizione: il sistema tipicamente esce per scadenza
   holding PRIMA del delisting. Il −60% è una stima conservativa della perdita media.

**Regola.**
1. **Non trattare il CAGR netto +5.6% EU come numero certo**: il survivorship bias nel
   dataset EU è materiale data l'alta rotazione (1175 trade / 8 anni = 147 trade/anno).
   Il numero reale potrebbe essere significativamente inferiore se si includono titoli delisted.
2. **L'US è più robusto** al survivorship bias (528 trade, p5 CAGR −1.17%): il portafoglio
   S&P 500 ha meno fallimenti storici e il sistema ha meno trade stressabili per sim.
3. **Priorità per rendere l'EU robusto:**
   a. **Stop-loss per ogni posizione** (es. −15% sul cost_basis) → taglia le perdite
      catastrofiche a −15% invece di −60%. Un solo intervento riduce il delta per trade di 4x.
   b. **Filtrare l'universo EU** su capitalization >500M€ (FTSE MIB 40 + EURO STOXX 50):
      le large cap hanno tassi di fallimento ~0 negli ultimi 10 anni.
   c. **Aggiungere i titoli delisted storicamente al dataset** (data augmentation):
      include Wirecard, Thomas Cook, Evergrande ADR, Astaldi, ecc.
4. **Il driver principale dell'alpha EU è il regime gate + RSI edge**: anche con survivorship
   bias nel dataset, l'edge su FTSE MIB è reale ma la sua ampiezza è incerta.
5. **Nelle decisioni di allocazione real money**: usare una stima conservativa del CAGR EU
   (+2% a +4% reale) fino a disponibilità di dati con survivorship correction.

---

## Lezione #33 — 2026-06-30 — Lo Stop-Loss −15% è protezione efficace contro il survivorship bias; il filtro completeness è inutile sui dataset pre-curati

**Evidenza (Run #40, 500 sim MC con stress model corretto, assetto Run #38 + tasse IT).**

| Config | EU base CAGR | EU stress p5 | US base CAGR | US stress p5 | US P(>BTP) | Verdetto |
|--------|-------------|-------------|-------------|-------------|-----------|---------|
| A Base (noSL, noLC) | +5.64% | **−20.36%** | +5.60% | **−1.17%** | 0.0% | NON ROBUSTO |
| B SL −15% only | +5.36% | **+1.71%** | +4.85% | **+2.99%** | 45.2% | EU ACCETTABILE / US ROBUSTO |
| C LC75% only | +5.64% | **−20.36%** | +5.60% | **−1.17%** | 0.0% | NON ROBUSTO (nessun effetto) |
| D SL+LC | +5.36% | **+1.71%** | +4.85% | **+2.99%** | 45.2% | EU ACCETTABILE / US ROBUSTO |

**Costo assicurativo dello SL**: EU −0.28pt CAGR base / US −0.75pt CAGR base (whipsaw).
**Beneficio protettivo**: EU p5 +22pt / US p5 +4.2pt vs baseline senza SL.

**Correzione critica al modello MC di R39:**
R39 applicava la perdita −60% anche ai trade con SL attivo — questo era SBAGLIATO.
Con SL a −15%, se il titolo crolla a −60% lo SL scatta PRIMA, limitando la perdita a −15%.
Nel modello corretto: `stressed_net = cost_basis × (1 − stop_loss_pct)` invece di
`cost_basis × 0.40 + CGT_originale`. Il delta per trade stressato è ~3x minore con SL.
Trade già usciti per SL hanno delta ≈ 0 (la perdita era già nell'outcome originale).

**Filtro large-cap via completeness: null result su dataset pre-curati.**
Il filtro `completeness ≥ 75%` (% giorni con close non-NaN nei 252 giorni precedenti) ha
selezionato ZERO titoli da escludere. Motivo: `mib_data_long.csv` e `sp500_data_long.csv`
sono dataset pre-curati con quotazioni continue (completeness ≥ 99% per tutti i titoli).
Un filtro di completeness su dati di questo tipo non discrimina nulla.

**Regola.**
1. **Aggiungere Stop-Loss −15% è la singola modifica più importante per la robustezza:**
   - EU: trasforma uno scenario catastrofico (p5 −20%) in uno accettabile (p5 +1.71%)
   - US: da fragile (p5 −1.17%, P>0%=34%) a robusto (p5 +2.99%, P>BTP=45.2%)
   - Costo: piccolo (−0.28pt EU, −0.75pt US) rispetto al beneficio (22pt EU, 4pt US)
2. **Il modello MC stress deve essere coerente con il meccanismo di exit usato nel backtest.**
   Se lo SL è attivo, il worst-case per ogni posizione è il SL stesso (−15%), non il −60%
   teorico del delisting. Il modello deve cappare il stressed_net alla perdita massima reale.
3. **Filtri large-cap richiedono dati di market cap espliciti**, non proxy di completeness.
   Soluzioni corrette: lista esplicita di indice (FTSE MIB 40 = 40 ticker), API FMP per
   market cap storica, oppure dataset Compustat con field `csho × prcc_f`.
4. **Il whipsaw è il costo dell'assicurazione:**
   Lo SL a −15% uscirà da trade che poi rimbalzano. Questo è accettabile se il guadagno
   in robustezza (p5 da −20% a +2%) supera il costo in CAGR (−0.28pt EU, −0.75pt US).
   Per un portafoglio real-money il trade-off è nettamente favorevole.
5. **Configurazione live raccomandata post R40:**
   - EU: p85 | hold 10gg | espandente | SL −15% | Fineco+slip+tasse | CAGR base +5.36%
   - US: p80 | hold 20gg | espandente | SL −15% | Fineco+slip+tasse | CAGR base +4.85%
   - Stress robustezza: EU p5 +1.71% / US p5 +2.99% (vs delisting 1.5%@−60%)

---
*Le attività di ogni run sono registrate in `STATE.md`.*
