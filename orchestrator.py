"""orchestrator.py — Comitato multi-agente nativo (Anthropic Messages API).

Ogni agente e' invocato con una chiamata `messages.create()` ISOLATA e stateless:
niente cronologia condivisa, niente prompt-chaining implicito. `invoke_isolated_agent`
costruisce SEMPRE `messages=[<un solo turno utente>]` — un agente non vede mai i turni
di conversazione di un altro agente.

La comunicazione tra agenti passa SOLO attraverso payload JSON strutturati e validati
contro uno schema (`agents/output_schemas.py`), mai testo libero/persuasivo. Questo e'
il meccanismo concreto che garantisce comunicazione "unilaterale" (a valle riceve la
CONCLUSIONE di monte, non il suo ragionamento) senza contaminazione di bias tra agenti:
- il Finance Guy non vede sentiment/fondamentali del titolo (giudizio macro indipendente);
- il Company Analyst non vede il giudizio macro ne' quello di rischio;
- se uno stadio boccia, gli stadi successivi non vengono nemmeno invocati (short-circuit):
  un agente a valle non puo' mai "convincere" a ribaltare un rigetto di monte.

Pipeline: Researcher -> Company Analyst -> Finance Guy -> Auditor -> CEO.

Regole immutabili: l'Auditor riceve il codice REALE di `portfolio_backtester.py` letto da
disco (non riassunto, non trascritto a memoria). Due regole non negoziabili (Run #40 /
LOOP.md) sono inoltre applicate in CODICE, non affidate al giudizio del modello:
  1) lo stop-loss finale non supera mai STOP_LOSS_FLOOR, qualunque cosa proponga l'LLM;
  2) regime_gate == "TREND_DOWN" forza sempre approved=False.

Uso (fallback CLI, non e' lo slash-command primario — vedi AGENTS.md):
    export ANTHROPIC_API_KEY=...
    python3 orchestrator.py data/committee_input.json
"""
import os
import sys
import json
import datetime
from pathlib import Path

from jsonschema import validate, ValidationError

from agents.output_schemas import (
    RESEARCHER_SCHEMA, COMPANY_ANALYST_SCHEMA, FINANCE_GUY_SCHEMA,
    AUDITOR_SCHEMA, CEO_SCHEMA,
)

REPO_ROOT = Path(__file__).resolve().parent
STOP_LOSS_FLOOR = 0.15  # Run #40: qualunque proposta piu' larga viene clampata qui
MODEL = os.environ.get("ORCHESTRATOR_MODEL", "claude-sonnet-5")


def _client():
    from anthropic import Anthropic
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY assente: impostala nell'ambiente prima di lanciare il Comitato.")
    return Anthropic(api_key=key)


def _read(relpath):
    path = REPO_ROOT / relpath
    if not path.exists():
        raise FileNotFoundError(f"File immutabile non trovato nel repo: {relpath}")
    return path.read_text()


def _prompt(name):
    return _read(f"agents/prompts/{name}.md")


def load_input_schema():
    return json.loads(_read("data_schema.json"))


def validate_candidate(candidate, schema=None):
    schema = schema or load_input_schema()
    try:
        validate(instance=candidate, schema=schema)
        return True, None
    except ValidationError as e:
        return False, e.message


def invoke_isolated_agent(client, system_prompt, payload, output_schema,
                           max_tokens=1500, model=None):
    """Chiamata STATELESS a un singolo agente.

    `messages` ha SEMPRE un solo turno utente costruito dal `payload` esplicito:
    nessuna cronologia accumulata, nessun contesto ereditato da altre chiamate.
    L'output DEVE essere un JSON che rispetta `output_schema` — se il modello
    risponde con testo libero o campi extra, la chiamata fallisce esplicitamente
    invece di lasciar passare un ragionamento non strutturato allo stadio successivo.
    """
    resp = client.messages.create(
        model=model or MODEL,
        max_tokens=max_tokens,
        system=system_prompt + "\n\nRispondi SOLO con un oggetto JSON valido, senza testo fuori dal JSON.",
        messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
    )
    raw = resp.content[0].text
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Risposta agente non e' JSON valido: {raw[:200]!r}") from e
    validate(instance=data, schema=output_schema)
    return data


class NativeOrchestrator:
    """Orchestratore del Comitato. `client` e' iniettabile (test con un client finto
    senza mai toccare la rete o consumare crediti API)."""

    def __init__(self, client=None):
        self._client = client
        self.schema = load_input_schema()

    def _get_client(self):
        if self._client is None:
            self._client = _client()
        return self._client

    def run_committee(self, candidate):
        ok, err = validate_candidate(candidate, self.schema)
        if not ok:
            return {
                "ticker": candidate.get("ticker", "?"),
                "stages": {},
                "final": {"ticker": candidate.get("ticker", "?"), "action": "SKIP",
                          "rationale": f"[schema_validation] dato in ingresso non valido: {err}",
                          "final_stop_loss_pct": None},
            }

        client = self._get_client()
        ticker = candidate["ticker"]
        trail = {"ticker": ticker, "stages": {}}

        # 1) RESEARCHER — vede solo il candidato immutabile. Primo della catena.
        researcher_out = invoke_isolated_agent(
            client, _prompt("researcher"), {"candidate": candidate}, RESEARCHER_SCHEMA)
        trail["stages"]["researcher"] = researcher_out

        # 2) COMPANY ANALYST — vede candidato + SOLO l'output strutturato del Researcher.
        analyst_out = invoke_isolated_agent(
            client, _prompt("company_analyst"),
            {"candidate": candidate, "researcher": researcher_out},
            COMPANY_ANALYST_SCHEMA)
        trail["stages"]["company_analyst"] = analyst_out
        if analyst_out["verdict"] == "reject":
            return self._reject(ticker, "company_analyst", analyst_out["reasons"], trail)

        # 3) FINANCE GUY — vede SOLO ticker/mercato/regime + le linee guida macro. Non
        #    vede researcher/company_analyst: il giudizio macro resta indipendente dalla
        #    narrativa sul singolo titolo (isolamento deliberato).
        finance_out = invoke_isolated_agent(
            client, _prompt("finance_guy"),
            {"candidate": {"ticker": ticker, "market": candidate.get("market"),
                           "regime_gate": candidate["regime_gate"]},
             "macro_guidelines": _read("macro_guidelines.md")},
            FINANCE_GUY_SCHEMA)
        trail["stages"]["finance_guy"] = finance_out
        if not finance_out["sector_rotation_favorable"]:
            return self._reject(ticker, "finance_guy", [finance_out["notes"]], trail)

        # 4) AUDITOR — vede candidato + i verdetti strutturati + il codice REALE delle
        #    regole (letto da disco, non a memoria).
        auditor_out = invoke_isolated_agent(
            client,
            _prompt("auditor") + f"\n\n--- portfolio_backtester.py (codice reale) ---\n{_read('portfolio_backtester.py')}",
            {"candidate": candidate, "researcher": researcher_out,
             "company_analyst": analyst_out, "finance_guy": finance_out},
            AUDITOR_SCHEMA)
        # BACKSTOP DETERMINISTICO #1: lo SL non scende mai sotto il floor di Run #40,
        # qualunque cosa proponga il modello.
        auditor_out["stop_loss_pct"] = min(auditor_out["stop_loss_pct"], STOP_LOSS_FLOOR)
        # BACKSTOP DETERMINISTICO #2: regime TREND_DOWN veta sempre, a prescindere
        # dal giudizio del modello (LOOP.md: il gate di regime e' la fonte dell'edge).
        if candidate["regime_gate"] == "TREND_DOWN" and auditor_out["approved"]:
            auditor_out["approved"] = False
            auditor_out["risk_notes"].append(
                "[BACKSTOP] regime_gate=TREND_DOWN -> veto automatico (LOOP.md)")
        trail["stages"]["auditor"] = auditor_out
        if not auditor_out["approved"]:
            return self._reject(ticker, "auditor", auditor_out["risk_notes"], trail)

        # 5) CEO — vede SOLO i verdetti strutturati finali, mai il ragionamento grezzo
        #    (che non esiste: ogni stadio a monte ha gia' risposto solo in JSON vincolato).
        ceo_out = invoke_isolated_agent(
            client, _prompt("ceo"),
            {"candidate": candidate, "researcher": researcher_out,
             "company_analyst": analyst_out, "finance_guy": finance_out, "auditor": auditor_out},
            CEO_SCHEMA)
        if ceo_out.get("final_stop_loss_pct") is not None:
            # Il CEO puo' solo restringere lo stop, mai allargarlo oltre l'Auditor.
            ceo_out["final_stop_loss_pct"] = min(ceo_out["final_stop_loss_pct"],
                                                  auditor_out["stop_loss_pct"])
        trail["stages"]["ceo"] = ceo_out
        trail["final"] = ceo_out
        return trail

    @staticmethod
    def _reject(ticker, stage, reasons, trail):
        trail["final"] = {
            "ticker": ticker, "action": "SKIP",
            "rationale": f"[{stage}] " + "; ".join(reasons),
            "final_stop_loss_pct": None,
        }
        return trail


def render_report(results, asof=None):
    asof = asof or datetime.date.today().isoformat()
    lines = [f"COMITATO MULTI-AGENTE — Report operativo {asof}", "=" * 70]
    for r in results:
        final = r["final"]
        lines.append(f"\n{r['ticker']}: {final['action']}")
        lines.append(f"  Motivazione: {final['rationale']}")
        if final["action"] == "BUY" and final.get("final_stop_loss_pct") is not None:
            lines.append(f"  Stop-Loss: -{final['final_stop_loss_pct']*100:.1f}%")
    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        print("uso: python3 orchestrator.py <candidates.json>")
        sys.exit(1)
    candidates = json.loads(Path(sys.argv[1]).read_text())
    orch = NativeOrchestrator()
    results = [orch.run_committee(c) for c in candidates]
    asof = datetime.date.today().isoformat()
    report = render_report(results, asof)
    data_dir = REPO_ROOT / "data"
    data_dir.mkdir(exist_ok=True)
    (data_dir / f"COMMITTEE_REPORT_{asof}.txt").write_text(report)
    (data_dir / f"committee_output_{asof}.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False))
    print(report)


if __name__ == "__main__":
    main()
