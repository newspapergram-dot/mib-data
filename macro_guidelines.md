# macro_guidelines.md — Regole macro per l'agente Finance Guy

Consumato da: agente Finance Guy (`orchestrator.py`), letto per intero a ogni invocazione.
Ogni riga qui è un VINCOLO RIGIDO, non un'opinione da pesare — il Finance Guy deve applicarle
come regole, non come suggerimenti.

## Regole attive

- **KILL SWITCH FOMC/BCE**: se una decisione tassi Fed o BCE cade entro 10 giorni di calendario
  dalla data odierna, `sector_rotation_favorable` deve essere `false` per QUALSIASI ticker del
  mercato interessato (US per Fed, EU per BCE), indipendentemente dal regime tecnico. Stesso
  principio già in uso nel motore deterministico (`modules/debate.py::build_debate`,
  `macro_killswitch`).
- **Il regime gate è la fonte dell'edge**: mai dichiarare `sector_rotation_favorable=true` per
  un mercato il cui `regime_gate` è `TREND_DOWN` — vedi `LOOP.md` §"Quando il task finisce".
- **Rotazione settoriale**: settori difensivi (utility, staples, farmaceutici) favoriti in fase
  di restringimento monetario (tassi in salita o "higher for longer"); ciclici (tech,
  discrezionale, industriali) favoriti in fase di easing o pausa prolungata.
- **Divergenza Fed/BCE**: se le due banche centrali sono in fasi diverse del ciclo (una taglia,
  l'altra tiene fermo/alza), segnalarlo esplicitamente in `notes` — impatta il cambio EUR/USD
  e quindi i titoli EU esportatori.

## Storico modifiche

(Le voci sotto sono aggiunte in APPEND dall'Agente Post-Mortem — non riordinare a mano, ogni
riga è datata e attribuita a un ticker/causa specifica. Vedi `post_mortem.py::apply_guideline`.)
