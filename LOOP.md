# LOOP.md — Loop Operativo Giornaliero (Profit-Seeker)

Loop di analisi finanziaria del repo `mib-data`. Istanzia il pattern **daily-triage**
della reference `loopengineering` (`patterns/daily-triage.md`) applicato al trading swing
EU+USA: stessa spina dorsale (scheduler → stato → verifica → azione → handoff umano),
specializzata sulla generazione e verifica di raccomandazioni operative.

> **Goal** (invariante del loop):
> *"Dammi i top-5 strong-buy di <data>. Trade profittevole, nessun errore di analisi o
> output confuso. Il task finisce solo quando sei fortemente sicuro che non ci sono altri
> ticker da aggiungere."*

## Memory spine

| File | Ruolo |
|------|-------|
| `data/journal/<asof>.json` | **Diario datato dei pick** — congela ogni piano (entry/stop/T1-T3, regime). Senza, la verifica del giorno dopo e' impossibile. |
| `STATE.md` | Diario narrativo run-by-run + watch-list delle criticita' aperte. |
| `FINANCIAL_SKILLS.md` | Lezioni accumulate (ogni fix nasce qui come regola). |
| `data/VERIFICATION.txt` / `verification.json` | Esito path-based dei pick precedenti vs prezzi reali. |
| `data/IMPROVEMENT_LOG.txt` | Auto-audit post-raccomandazione (`self_improve.py`). |

## Il ciclo giornaliero

Ogni mattina (o `/loop 1d`), PRIMA che l'utente chieda qualcosa:

### Fase 1 — Verifica (deterministica)
```bash
python3 daily_loop.py verify     # fetch_data -> regime_filter -> verify_picks
```
Produce `data/VERIFICATION.txt`. Confronto **path-based** (max/min giornalieri): rileva stop
toccati intraday, target raggiunti, drift, MAE/MFE, e **cambi di regime** sui mercati dei pick.

### Fase 2 — Audit: ricerca dura degli errori (RAGIONAMENTO → sub-agent)
Questo passo NON va automatizzato ciecamente. Lancia un **sub-agent "auditor"** (`Agent`,
`subagent_type: general-purpose`) indipendente da chi genera i pick — l'indipendenza e' il
punto: un agente separato non razionalizza i propri errori.

Input al sub-agent: `data/VERIFICATION.txt`, `data/verification.json`, lo snapshot del giorno
prima, `FINANCIAL_SKILLS.md`. Compiti:
1. **Ricerca dura degli errori.** Per ogni pick: il segnale prometteva X, il prezzo ha fatto Y
   — era segnale sbagliato o solo anticipato? Il pattern (`patterns.py`) diceva breakout ma il
   volume era debole → falso segnale? Il regime e' girato durante l'holding → il gate e' stato
   abbastanza rapido?
2. **Confronto con cio' che si e' MOSSO davvero.** Quali ticker NON selezionati hanno corso?
   Cosa li distingueva dai nostri (regime, score, flow)? Abbiamo mancato un edge sistematico?
3. **Cause radice, non sintomi.** Ogni errore → una causa nominabile (bug di codice, soglia
   sbagliata, dato vecchio, assunzione non validata).
4. **Fix mirati proposti** con la skill che li esegue (`/code-review`, `/verify`, controllo dato).

Il sub-agent RIPORTA; non scrive codice di produzione. L'agente principale decide e applica.

### Fase 3 — Fix (agente principale)
Applica i fix proposti (tocca piu' file → resta nel contesto principale). Ogni fix:
- diventa una **Lezione** in `FINANCIAL_SKILLS.md` (regola + evidenza concreta);
- aggiorna la **watch-list** in `STATE.md`;
- se cambia codice di scoring/regime, va passato a `/code-review` e `/verify`.

### Fase 4 — Genera i nuovi top-5 (deterministica, coi fix applicati)
```bash
python3 daily_loop.py generate   # score -> portfolio -> self_improve -> charts -> journal snapshot
```
L'ultimo passo **congela** i nuovi pick in `data/journal/<asof>.json`: domani la Fase 1 li
verifichera'. Il loop si chiude su se stesso.

> Se l'audit non richiede fix: `python3 daily_loop.py all` esegue tutto di seguito.

## Quando il task "finisce" (criterio del goal)

I top-5 sono pronti solo quando TUTTE sono vere, altrimenti si itera:
- [ ] dati freschi (`last_update.txt` = oggi; `self_improve` non segnala freschezza ALTA);
- [ ] ogni pick e' in un mercato **operabile** dal gate di regime (no nomi gated dentro);
- [ ] nessuna criticita' ALTA aperta in `IMPROVEMENT_LOG.txt`;
- [ ] livelli coerenti (entry/stop/T1-T3, R/R ≥ floor) e output non ambiguo;
- [ ] la verifica del giorno prima e' stata fatta e le sue lezioni applicate.

Se i nomi operabili sono **meno di 5** (es. regime in PULLBACK), il risultato onesto e'
"meno di 5" con la motivazione — **non** si forzano nomi gated per arrivare a quota (Lezione:
il gate di regime e' la fonte dell'edge, non un ostacolo da aggirare).

## Sub-agent: sì, ma solo dove serve indipendenza/scope

| Passo | Sub-agent? | Perche' |
|-------|-----------|---------|
| Verifica (Fase 1) | No | Confronto deterministico: e' codice (`verify_picks.py`). |
| Audit errori/cause (Fase 2) | **Sì** | Serve un giudizio INDIPENDENTE da chi ha generato i pick. |
| Fix (Fase 3) | No | Tocca piu' file, serve il contesto pieno del repo. |
| Genera top-5 (Fase 4) | No | Dipende dai fix, dev'essere sequenziale. |

## Sicurezza & gate (questo repo)

- Stop **non negoziabile**: l'edge vive nella disciplina sugli stop (payoff < 1).
- Size moderata, **mai leverage** (DSR < 0.95: edge reale ma non blindato).
- Nessun pick fuori dal regime operabile, anche con score alto (es. TIT.MI score 1.00 ma IT
  in PULLBACK → escluso).
- Mai inventare un esito: la verifica riporta solo cio' che i prezzi hanno fatto.
- Mai committare chiavi/cookie/segreti (vedi `AGENTS.md` / `CLAUDE.md`).

---
*Cadence: 1d feriali. Tier: medio. Parent pattern: `loopengineering/patterns/daily-triage.md`.*
