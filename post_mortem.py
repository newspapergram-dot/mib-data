"""post_mortem.py — Agente iterativo di auto-miglioramento (Livello 4 del flusso).

Si attiva dopo uno stop-loss o a fine mese: analizza UN trade fallito alla volta, in una
chiamata ISOLATA (stesso principio del Comitato in `orchestrator.py` — nessuna cronologia
condivisa con la discussione che ha originato quel trade), e propone UNA riga di linea
guida strutturata (`agents.output_schemas.POST_MORTEM_SCHEMA`).

La proposta e' validata contro lo schema e applicata in APPEND (mai overwrite) al file
target da codice deterministico: l'LLM propone, il codice scrive. Nessuna riscrittura
libera di file da parte del modello.
"""
import json
import datetime

from jsonschema import validate

from orchestrator import _client, _prompt, _read, REPO_ROOT, MODEL
from agents.output_schemas import POST_MORTEM_SCHEMA


def analyze_failed_trade(trade, client=None):
    """`trade`: dict con almeno ticker, exit_reason, pnl_pct, e contesto minimo
    (es. entry_date, exit_date, market). Chiamata isolata: un solo turno utente,
    nessuna cronologia del Comitato che ha generato il trade."""
    client = client or _client()
    registry = _read("post_mortem_registry.md")
    resp = client.messages.create(
        model=MODEL,
        max_tokens=800,
        system=_prompt("post_mortem") + "\n\nRispondi SOLO con un oggetto JSON valido.",
        messages=[{"role": "user",
                   "content": json.dumps({"trade": trade, "registro_attuale": registry},
                                          ensure_ascii=False)}],
    )
    data = json.loads(resp.content[0].text)
    validate(instance=data, schema=POST_MORTEM_SCHEMA)
    return data


def apply_guideline(proposal):
    """Applica in APPEND la proposta al file target. Ritorna il Path modificato.
    Mai overwrite: la storia delle lezioni e' un log, non uno stato mutabile."""
    target = REPO_ROOT / proposal["target_file"]
    ts = datetime.date.today().isoformat()
    entry = f"\n- [{ts}] {proposal['ticker']}: {proposal['new_guideline']} (causa: {proposal['root_cause']})\n"
    with open(target, "a") as f:
        f.write(entry)
    return target


def run_for_trade(trade, client=None):
    proposal = analyze_failed_trade(trade, client=client)
    path = apply_guideline(proposal)
    return proposal, path


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("uso: python3 post_mortem.py <trade.json>")
        sys.exit(1)
    trade_data = json.loads(open(sys.argv[1]).read())
    proposal, path = run_for_trade(trade_data)
    print(f"Proposta applicata a {path}:\n{json.dumps(proposal, indent=2, ensure_ascii=False)}")
