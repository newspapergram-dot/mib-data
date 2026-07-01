"""Verifica l'isolamento reale tra agenti del Comitato (`orchestrator.py`).

Nessun test qui tocca la rete o l'API Anthropic: `FakeClient` (tests/fakes.py)
sostituisce il client e registra ogni chiamata per ispezione. Le proprieta'
verificate sono esattamente quelle richieste dal goal: comunicazione stateless,
scoping informativo per-stadio, short-circuit sui rigetti, backstop deterministici
che l'LLM non puo' aggirare.
"""
import json
from types import SimpleNamespace

from orchestrator import NativeOrchestrator, STOP_LOSS_FLOOR, invoke_isolated_agent
from tests.fakes import FakeClient

CANDIDATE = {
    "ticker": "STMMI.MI",
    "market": "EU",
    "asof": "2026-07-01",
    "regime_gate": "TREND_UP",
    "momentum_score": 0.82,
    "entry_price": 30.0,
    "fundamentals": {
        "debt_to_equity": 0.8,
        "ebitda_margin": 0.28,
        "eps_growth_q_on_q": 0.05,
        "free_cash_flow": 1_200_000_000,
    },
}

RESEARCHER_OK = {"ticker": "STMMI.MI", "news_sentiment": "positive", "sentiment_score": 0.4,
                 "key_events": ["guidance alzata"], "earnings_call_flag": False}
ANALYST_PASS = {"ticker": "STMMI.MI", "verdict": "pass", "reasons": ["debito basso"],
                "debt_flag": False}
ANALYST_REJECT = {"ticker": "STMMI.MI", "verdict": "reject", "reasons": ["debt_to_equity 3.1 senza FCF positivo"],
                   "debt_flag": True}
FINANCE_FAVORABLE = {"macro_regime": "easing", "sector_rotation_favorable": True,
                      "notes": "nessun FOMC/BCE entro 10gg"}
FINANCE_UNFAVORABLE = {"macro_regime": "tightening", "sector_rotation_favorable": False,
                        "notes": "FOMC tra 3 giorni: kill switch attivo"}
AUDITOR_APPROVE_WIDE_SL = {"approved": True, "stop_loss_pct": 0.30, "risk_notes": ["ok ma SL largo"]}
AUDITOR_REJECT = {"approved": False, "stop_loss_pct": 0.15, "risk_notes": ["volatilita' eccessiva"]}
CEO_BUY_WIDE_SL = {"ticker": "STMMI.MI", "action": "BUY", "rationale": "Setup solido, procedi.",
                    "final_stop_loss_pct": 0.30}


def _payload(call):
    return json.loads(call["messages"][0]["content"])


def test_validate_candidate_rejects_missing_fundamentals():
    client = FakeClient([])
    orch = NativeOrchestrator(client=client)
    bad = {k: v for k, v in CANDIDATE.items() if k != "fundamentals"}
    result = orch.run_committee(bad)
    assert result["final"]["action"] == "SKIP"
    assert "schema_validation" in result["final"]["rationale"]
    assert len(client.calls) == 0  # nessuna chiamata LLM sprecata su input invalido


def test_isolated_calls_are_stateless_single_turn():
    client = FakeClient([RESEARCHER_OK, ANALYST_PASS, FINANCE_FAVORABLE,
                         AUDITOR_APPROVE_WIDE_SL, CEO_BUY_WIDE_SL])
    orch = NativeOrchestrator(client=client)
    orch.run_committee(CANDIDATE)
    assert len(client.calls) == 5
    for call in client.calls:
        # Ogni chiamata e' un turno singolo: nessuna cronologia accumulata tra agenti.
        assert len(call["messages"]) == 1
        assert call["messages"][0]["role"] == "user"


def test_finance_guy_does_not_see_researcher_or_analyst_output():
    client = FakeClient([RESEARCHER_OK, ANALYST_PASS, FINANCE_FAVORABLE,
                         AUDITOR_APPROVE_WIDE_SL, CEO_BUY_WIDE_SL])
    orch = NativeOrchestrator(client=client)
    orch.run_committee(CANDIDATE)
    finance_call_payload = _payload(client.calls[2])
    assert "researcher" not in finance_call_payload
    assert "company_analyst" not in finance_call_payload
    assert "macro_guidelines" in finance_call_payload


def test_ceo_sees_all_structured_verdicts():
    client = FakeClient([RESEARCHER_OK, ANALYST_PASS, FINANCE_FAVORABLE,
                         AUDITOR_APPROVE_WIDE_SL, CEO_BUY_WIDE_SL])
    orch = NativeOrchestrator(client=client)
    orch.run_committee(CANDIDATE)
    ceo_payload = _payload(client.calls[4])
    assert set(["researcher", "company_analyst", "finance_guy", "auditor"]).issubset(ceo_payload)


def test_stop_loss_backstop_clamps_llm_overreach():
    client = FakeClient([RESEARCHER_OK, ANALYST_PASS, FINANCE_FAVORABLE,
                         AUDITOR_APPROVE_WIDE_SL, CEO_BUY_WIDE_SL])
    orch = NativeOrchestrator(client=client)
    result = orch.run_committee(CANDIDATE)
    assert result["stages"]["auditor"]["stop_loss_pct"] == STOP_LOSS_FLOOR
    assert result["final"]["final_stop_loss_pct"] == STOP_LOSS_FLOOR


def test_regime_down_forces_veto_regardless_of_llm():
    candidate = dict(CANDIDATE, regime_gate="TREND_DOWN")
    client = FakeClient([RESEARCHER_OK, ANALYST_PASS, FINANCE_FAVORABLE,
                         {"approved": True, "stop_loss_pct": 0.10, "risk_notes": ["il modello sbaglia"]}])
    orch = NativeOrchestrator(client=client)
    result = orch.run_committee(candidate)
    assert len(client.calls) == 4  # CEO non viene invocato
    assert result["final"]["action"] == "SKIP"
    assert result["stages"]["auditor"]["approved"] is False
    assert any("BACKSTOP" in note for note in result["stages"]["auditor"]["risk_notes"])


def test_short_circuit_on_company_analyst_reject():
    client = FakeClient([RESEARCHER_OK, ANALYST_REJECT])
    orch = NativeOrchestrator(client=client)
    result = orch.run_committee(CANDIDATE)
    assert len(client.calls) == 2
    assert result["final"]["action"] == "SKIP"
    assert result["final"]["rationale"].startswith("[company_analyst]")


def test_short_circuit_on_finance_guy_unfavorable():
    client = FakeClient([RESEARCHER_OK, ANALYST_PASS, FINANCE_UNFAVORABLE])
    orch = NativeOrchestrator(client=client)
    result = orch.run_committee(CANDIDATE)
    assert len(client.calls) == 3
    assert result["final"]["action"] == "SKIP"
    assert result["final"]["rationale"].startswith("[finance_guy]")


def test_short_circuit_on_auditor_reject():
    client = FakeClient([RESEARCHER_OK, ANALYST_PASS, FINANCE_FAVORABLE, AUDITOR_REJECT])
    orch = NativeOrchestrator(client=client)
    result = orch.run_committee(CANDIDATE)
    assert len(client.calls) == 4  # CEO mai invocato dopo un rigetto a monte
    assert result["final"]["action"] == "SKIP"
    assert result["final"]["rationale"].startswith("[auditor]")


def test_full_approval_yields_buy_with_clamped_stop_loss():
    client = FakeClient([RESEARCHER_OK, ANALYST_PASS, FINANCE_FAVORABLE,
                         AUDITOR_APPROVE_WIDE_SL, CEO_BUY_WIDE_SL])
    orch = NativeOrchestrator(client=client)
    result = orch.run_committee(CANDIDATE)
    assert result["final"]["action"] == "BUY"
    assert result["final"]["final_stop_loss_pct"] == STOP_LOSS_FLOOR


class _ThinkingThenTextClient:
    """Simula una risposta reale con un ThinkingBlock (senza attributo .text) prima
    del blocco di testo — riproduce il crash osservato in produzione il 1/7/2026
    ('ThinkingBlock' object has no attribute 'text')."""

    def __init__(self, text):
        thinking_block = SimpleNamespace(type="thinking", thinking="ragionamento interno")
        text_block = SimpleNamespace(type="text", text=text)
        self.messages = SimpleNamespace(
            create=lambda **kw: SimpleNamespace(content=[thinking_block, text_block]))


def test_invoke_isolated_agent_skips_leading_thinking_block():
    client = _ThinkingThenTextClient(json.dumps(RESEARCHER_OK))
    from agents.output_schemas import RESEARCHER_SCHEMA
    result = invoke_isolated_agent(client, "system prompt", {"candidate": CANDIDATE},
                                    RESEARCHER_SCHEMA)
    assert result == RESEARCHER_OK


def test_invoke_isolated_agent_strips_markdown_json_fence():
    """Run reale del 1/7/2026: il Company Analyst ha risposto con un blocco
    ```json ... ``` nonostante l'istruzione di rispondere solo JSON puro."""
    fenced = "```json\n" + json.dumps(ANALYST_PASS) + "\n```"
    client = _ThinkingThenTextClient(fenced)
    from agents.output_schemas import COMPANY_ANALYST_SCHEMA
    result = invoke_isolated_agent(client, "system prompt", {"candidate": CANDIDATE},
                                    COMPANY_ANALYST_SCHEMA)
    assert result == ANALYST_PASS
