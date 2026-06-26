# mib-data — Swing Copilot EU + USA

Sistema di supporto alle decisioni per swing trading su azioni **FTSE MIB, CAC 40 e USA
large-cap**. **Genera proposte operative** (entry / stop / target / sizing), non esegue ordini
e non ha posizioni reali. Orizzonte tipico: ~10 sedute.

> ⚠️ **Non è consulenza finanziaria.** È uno strumento di analisi. L'edge è modesto e
> bull-favored (vedi *Limiti onesti*): l'affidabilità del processo viene dalla **gestione del
> rischio**, non da un rendimento elevato garantito.

---

## TL;DR (onesto)

- Il modello **funziona bene in mercato rialzista** e **perde in bear**: l'edge di prezzo è reale
  ma **bull-concentrato**. Sul ciclo completo 2018–2026 la strategia *grezza* (senza filtri)
  crollerebbe (Sharpe 0.18, **MaxDD −95.7%**).
- I **controlli di rischio** (gate di trend, regime + trigger rapido, stop, go-flat, accumulazione,
  sizing per convinzione) sono il vero pilastro: portano il **MaxDD da −96% a ~−33/−37%** sul ciclo
  completo. Questi elementi sono validati full-cycle.
- L'**edge di rendimento ha un tetto strutturale** (≈0.27%/trade, PF 1.18 full-cycle): non si
  sblocca spremendo altri segnali di prezzo (momentum/low-vol testati e **non integrati**, vedi
  `factor_validate.py`). Per alzarlo serve **informazione nuova** (fondamentali point-in-time / alt-data).

---

## Il modello operativo (strati condizionali)

Ogni strato restringe al sottoinsieme dove l'edge è misurato; si **moltiplicano**:

1. **Gate di trend** (per titolo): si considerano solo azioni con `prezzo > SMA200` e `SMA50 > SMA200`
   (in `score_generator.py` / `score_new`).
2. **Regime di mercato** (`regime_filter.py`): per ciascun mercato (IT=FTSEMIB, FR=^FCHI, US=^GSPC)
   si classifica TREND_UP / **PULLBACK** / LATERALE / TREND_DOWN e si assegna un **moltiplicatore di
   rischio** (1.0 / 0.5 / 0.5 / 0.0). Include il **trigger rapido `px>SMA20`** (fattore bear): se il
   prezzo perde la SMA20 pur in trend lungo → PULLBACK (mezza size), risk-off precoce.
3. **Ranking** (`score_generator.py`): score tecnico (breakout + ADX + momentum) + flow (13F/insider/short);
   si seleziona il **top-quintile**.
4. **Smart Money / Foreground** (`volume_tools.py`): ADL + CMF + anomalie di volume → stato
   accumulazione/neutro/distribuzione. **Filtro di affidabilità validato**: dentro il top-quintile,
   l'accumulazione batte la distribuzione (win 60% vs 40%). In portafoglio: accumulazione = **CORE**
   (piena size), neutro = **SAT** (size ridotta), distribuzione = **esclusa**.
5. **Uscita** (`modules/trade_proposal.py`): **stop** = `max(entry·0.95, entry−2·ATR)`; **target
   laddered** T1/T2/T3 = `max(k·ATR, k·rischio)` con k=(2,6,10) — tarati sul backtest (T1 "hittable",
   T2/T3 catturano la coda). Lo stop è il secondo fattore bear decisivo.
6. **Sizing & portafoglio** (`portfolio_builder.py`): size per convinzione (tier score × tier smart
   money × liquidità) modulata dal `regime_mult`; **dedup per emittente** (no doppie quotazioni
   Milano/Parigi); cap esposizione.
7. **Overlay di rischio** (opzionale): default **go-flat** nei mercati non TREND_UP; modalità
   `include_pullback=True` resta a metà size con **hedge dell'indice** suggerito (assicurazione, non alpha).

---

## Come si esegue (pipeline)

```bash
pip install -r requirements.txt          # pandas, numpy, scipy, requests, ...

python3 fetch_data.py            # 1) prezzi EOD (Piano C = Yahoo v8 JSON; fallback FMP/stooq)
python3 score_generator.py       # 2) ranking -> data/score_output.csv
python3 regime_filter.py         # 3) regime di mercato -> data/regime_filter.csv
python3 portfolio_builder.py     # 4) portafoglio operativo -> data/PORTFOLIO.txt
```

Output principale: **`data/PORTFOLIO.txt`** (tabella + schede entry/stop/T1-T2-T3 + overlay rischio).

Validazioni (riproducibili, ciclo completo dove indicato):
```bash
python3 fetch_long.py            # storico 2018-2026 AGGIUSTATO -> data/mib_data_long.csv (gitignored)
python3 backtest_v3.py           # backtest istituzionale (Sharpe/DSR/walk-forward/regime)
python3 target_backtest.py       # taratura target (sweep + laddered)
python3 sm_validate.py           # smart money: predittore? + test di affidabilita'
python3 walkforward_oos.py       # walk-forward OUT-OF-SAMPLE
python3 bear_analysis.py         # fattori bear sul ciclo completo (MaxDD)
python3 hedge_overlay.py         # overlay go-flat / hedge indice
python3 full_cycle_tune.py       # ri-taratura target full-cycle + DSR
python3 factor_validate.py       # fattori cross-sectional (momentum/low-vol) full-cycle
```

---

## Performance validata (numeri onesti)

| Contesto | Sharpe | MaxDD | Note |
|---|---|---|---|
| Backtest 14 mesi (solo bull) | 1.89 | ~−29% | **fuorviante**: edge bull-specifico |
| Walk-forward OOS (periodo bull) | — | — | WFE **+1.52** (no overfit *nel periodo*) |
| Ciclo completo 2018-2026, **grezzo** | 0.18 | **−95.7%** | senza filtri = rovina |
| Ciclo completo, + regime + accumulazione + **stop** | 0.75 | −45.7% | i filtri salvano |
| Ciclo completo, + **trigger rapido SMA20** | **0.83** | **−33.0%** | modello completo |

Edge per-trade full-cycle: ~**0.27%**, win ~52%, **PF 1.18** (sottile). DSR > 0.95 ottenibile ma
sensibile al numero di prove (vedi *Limiti*).

---

## Limiti onesti (leggere prima di usare)

1. **Bull-favored.** L'edge è concentrato nei rialzi; in bear il modello bleed-a (mitigato, non
   azzerato). Una strategia long-only **non diventa bear-proof** col solo risk-off.
2. **Edge sottile e con tetto.** ~0.27%/trade, PF 1.18 full-cycle. Mediana per-trade ~0: l'edge sta
   nella **coda** dei vincitori → serve disciplina su **molte** operazioni con **stop rispettato**.
3. **DSR fragile.** "DSR > 0.95" è in parte gaming (poche config simili + trade sovrapposti); il
   numero reale di prove nel progetto è alto → il DSR onesto è più basso.
4. **Niente fondamentali point-in-time.** P/E, ROE storici non disponibili (FMP EU gated) → i fattori
   quality/value non sono validabili full-cycle qui.
5. **Dati di prezzo.** `fetch_data.py` operativo a 14 mesi su prezzi grezzi; per il backtest lungo si
   usano prezzi **aggiustati** (`fetch_long.py`). Yahoo v8 è la fonte primaria (vedi sotto).
6. **In-sample ≠ futuro.** Tutte le metriche sono storiche; il walk-forward OOS copre solo un periodo
   prevalentemente bull. Nessuna garanzia forward.

---

## Dati e ambiente

- **Fonte prezzi primaria**: API pubblica JSON di **Yahoo v8** (`modules/fmp_source.get_eod_eu_robust`),
  uniforme per US/EU/indici. Fallback: FMP (US), stooq, Borsa Italiana. yfinance resta come ripiego ma
  richiede host extra (cookie/crumb) non sempre raggiungibili.
- **EU sbloccato** via allowlist di egress dell'ambiente (`query1.finance.yahoo.com`). FMP sul piano
  attuale copre solo US-domestic; gli MCP passano per i server Anthropic.
- **Diario e regole**: `STATE.md` (cronologia run) e `FINANCIAL_SKILLS.md` (lezioni operative apprese)
  documentano *perché* il modello è fatto così — leggerli prima di modificare.

---

## Roadmap

- [ ] Fondamentali **storici point-in-time** → testare quality/value senza lookahead (unico vero modo
      per alzare l'edge).
- [ ] Ripetere il walk-forward su un **ciclo completo con bear** quando arriveranno nuovi dati.
- [ ] Finché l'edge resta modesto: **priorità alla gestione del rischio** (già solida), non a nuovi segnali.

---
*Generato e mantenuto dal loop di analisi. Le scelte di design sono tracciate run-per-run in `STATE.md`.*
