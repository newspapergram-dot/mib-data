# post_mortem_registry.md — Diario delle lezioni da trade falliti

Consumato da: Agente Post-Mortem (append-only, mai overwrite) e Company Analyst (letto come
contesto storico prima di valutare candidati con caratteristiche simili a fallimenti passati).

Formato riga: `- [YYYY-MM-DD] TICKER: <guideline azionabile> (causa: <causa radice>)`

Ogni riga nasce da UNA chiamata isolata dell'Agente Post-Mortem su UN trade fallito reale
(`post_mortem.py::run_for_trade`) — mai da una generalizzazione a tavolino.

## Storico

(vuoto — la prima voce viene aggiunta dal primo stop-loss/trade chiuso in perdita processato
da `post_mortem.py`)
