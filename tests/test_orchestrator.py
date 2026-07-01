"""Verifica l'isolamento reale tra agenti del Comitato (`orchestrator.py`).

Nessun test qui tocca la rete o l'API Anthropic: `FakeClient` (tests/fakes.py)
sostituisce il client e registra ogni chiamata per ispezione. Le proprieta'
verificate sono esattamente quelle richieste dal goal: comunicazione stateless,
scoping informativo per-stadio, short-circuit sui rigetti, backstop deterministici
che l'LLM non puo' aggirare.
"""
import json
import math
from types import SimpleNamespace

import pandas as pd

from orchestrator import (NativeOrchestrator, STOP_LOSS_FLOOR, invoke_isolated_agent,
                           render_report, export_frontend_json, export_chart_data,
                           _operational_plan_json, compare_with_previous, _load_previous_results)
from tests.fakes import FakeClient


def _synthetic_price_history(ticker, n=260, start=100.0):
    """Storico prezzi sintetico con trend + oscillazione (evita degenerazioni
    matematiche in una serie perfettamente piatta o monotona)."""
    rows = []
    price = start
    for i in range(n):
        price += 0.15 + 0.8 * math.sin(i / 7.0)
        rows.append({"ticker": ticker, "date": f"2025-{(i % 12) + 1:02d}-{(i % 28) + 1:02d}",
                     "open": price - 0.1, "high": price + 0.6, "low": price - 0.6,
                     "close": price, "volume": 1_000_000 + i * 137})
    return pd.DataFrame(rows)

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
    "technical": {
        "rsi": 58.0, "adx": 27.0, "atr_pct": 2.5, "mom6m": 0.18,
        "sma20": 29.0, "sma50": 27.5, "sma200": 24.0,
    },
    "candlestick": {
        "trend": "up", "trend_strength": "forte", "structure": "higher-highs",
        "continuation": None, "breakout": "sopra 31.20", "pullback": False,
        "rsi_divergence": None, "bollinger": "upper-band", "notes": "",
    },
}

RESEARCHER_OK = {"ticker": "STMMI.MI", "news_sentiment": "positive", "sentiment_score": 0.4,
                 "key_events": ["guidance alzata"], "earnings_call_flag": False}
TECHNICAL_FAVORABLE = {"ticker": "STMMI.MI", "verdict": "favorable",
                        "reasons": ["RSI neutro, non ipercomprato", "trend rialzista confermato"],
                        "setup_read": "RSI 58 neutro, ADX 27 trend in atto",
                        "candlestick_read": "breakout sopra resistenza confermato"}
TECHNICAL_UNFAVORABLE = {"ticker": "STMMI.MI", "verdict": "unfavorable",
                          "reasons": ["RSI 84 ipercomprato estremo senza breakout confermato"],
                          "setup_read": "ipercomprato estremo",
                          "candlestick_read": "nessun pattern di conferma"}
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

FULL_APPROVAL_SCRIPT = [RESEARCHER_OK, TECHNICAL_FAVORABLE, ANALYST_PASS, FINANCE_FAVORABLE,
                         AUDITOR_APPROVE_WIDE_SL, CEO_BUY_WIDE_SL]


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
    client = FakeClient(FULL_APPROVAL_SCRIPT)
    orch = NativeOrchestrator(client=client)
    orch.run_committee(CANDIDATE)
    assert len(client.calls) == 6
    for call in client.calls:
        # Ogni chiamata e' un turno singolo: nessuna cronologia accumulata tra agenti.
        assert len(call["messages"]) == 1
        assert call["messages"][0]["role"] == "user"


def test_technical_analyst_does_not_see_fundamentals_researcher_or_other_verdicts():
    client = FakeClient(FULL_APPROVAL_SCRIPT)
    orch = NativeOrchestrator(client=client)
    orch.run_committee(CANDIDATE)
    technical_payload = _payload(client.calls[1])
    assert "fundamentals" not in technical_payload["candidate"]
    assert "researcher" not in technical_payload
    assert "company_analyst" not in technical_payload
    assert technical_payload["technical"] == CANDIDATE["technical"]
    assert technical_payload["candlestick"] == CANDIDATE["candlestick"]


def test_finance_guy_does_not_see_researcher_or_analyst_output():
    client = FakeClient(FULL_APPROVAL_SCRIPT)
    orch = NativeOrchestrator(client=client)
    orch.run_committee(CANDIDATE)
    finance_call_payload = _payload(client.calls[3])
    assert "researcher" not in finance_call_payload
    assert "company_analyst" not in finance_call_payload
    assert "technical_analyst" not in finance_call_payload
    assert "macro_guidelines" in finance_call_payload


def test_ceo_sees_all_structured_verdicts():
    client = FakeClient(FULL_APPROVAL_SCRIPT)
    orch = NativeOrchestrator(client=client)
    orch.run_committee(CANDIDATE)
    ceo_payload = _payload(client.calls[5])
    assert set(["researcher", "technical_analyst", "company_analyst",
                "finance_guy", "auditor"]).issubset(ceo_payload)


def test_stop_loss_backstop_clamps_llm_overreach():
    client = FakeClient(FULL_APPROVAL_SCRIPT)
    orch = NativeOrchestrator(client=client)
    result = orch.run_committee(CANDIDATE)
    assert result["stages"]["auditor"]["stop_loss_pct"] == STOP_LOSS_FLOOR
    assert result["final"]["final_stop_loss_pct"] == STOP_LOSS_FLOOR


def test_regime_down_forces_veto_regardless_of_llm():
    candidate = dict(CANDIDATE, regime_gate="TREND_DOWN")
    client = FakeClient([RESEARCHER_OK, TECHNICAL_FAVORABLE, ANALYST_PASS, FINANCE_FAVORABLE,
                         {"approved": True, "stop_loss_pct": 0.10, "risk_notes": ["il modello sbaglia"]}])
    orch = NativeOrchestrator(client=client)
    result = orch.run_committee(candidate)
    assert len(client.calls) == 5  # CEO non viene invocato
    assert result["final"]["action"] == "SKIP"
    assert result["stages"]["auditor"]["approved"] is False
    assert any("BACKSTOP" in note for note in result["stages"]["auditor"]["risk_notes"])


def test_short_circuit_on_technical_analyst_unfavorable():
    client = FakeClient([RESEARCHER_OK, TECHNICAL_UNFAVORABLE])
    orch = NativeOrchestrator(client=client)
    result = orch.run_committee(CANDIDATE)
    assert len(client.calls) == 2
    assert result["final"]["action"] == "SKIP"
    assert result["final"]["rationale"].startswith("[technical_analyst]")


def test_short_circuit_on_company_analyst_reject():
    client = FakeClient([RESEARCHER_OK, TECHNICAL_FAVORABLE, ANALYST_REJECT])
    orch = NativeOrchestrator(client=client)
    result = orch.run_committee(CANDIDATE)
    assert len(client.calls) == 3
    assert result["final"]["action"] == "SKIP"
    assert result["final"]["rationale"].startswith("[company_analyst]")


def test_short_circuit_on_finance_guy_unfavorable():
    client = FakeClient([RESEARCHER_OK, TECHNICAL_FAVORABLE, ANALYST_PASS, FINANCE_UNFAVORABLE])
    orch = NativeOrchestrator(client=client)
    result = orch.run_committee(CANDIDATE)
    assert len(client.calls) == 4
    assert result["final"]["action"] == "SKIP"
    assert result["final"]["rationale"].startswith("[finance_guy]")


def test_report_shows_upstream_favorable_verdicts_even_when_finance_guy_vetoes():
    """Il veto macro non deve far sparire dal report cio' che tecnica e fondamentali
    avevano gia' concluso: l'operatore deve poter vedere che il rigetto e' arrivato
    dal macro nonostante un quadro tecnico/fondamentale favorevole, non un buco nero."""
    client = FakeClient([RESEARCHER_OK, TECHNICAL_FAVORABLE, ANALYST_PASS, FINANCE_UNFAVORABLE])
    orch = NativeOrchestrator(client=client)
    result = orch.run_committee(CANDIDATE)
    report = render_report([result], asof="2026-07-01")

    assert "Verdetto Company Analyst: pass" in report
    assert "Verdetto Technical Analyst: favorable" in report
    assert "Analisi macro: regime tightening, rotazione settoriale sfavorevole" in report
    assert "FOMC tra 3 giorni: kill switch attivo" in report


def test_report_shows_macro_section_on_approved_buy_too():
    """Il giudizio macro non deve essere visibile SOLO sui rigetti: oggi spariva anche
    sui BUY approvati, l'unica traccia era annegata nel testo libero del CEO."""
    client = FakeClient(FULL_APPROVAL_SCRIPT)
    orch = NativeOrchestrator(client=client)
    result = orch.run_committee(CANDIDATE)
    report = render_report([result], asof="2026-07-01")
    assert "Analisi macro: regime easing, rotazione settoriale favorevole" in report
    assert "nessun FOMC/BCE entro 10gg" in report


def test_short_circuit_on_auditor_reject():
    client = FakeClient([RESEARCHER_OK, TECHNICAL_FAVORABLE, ANALYST_PASS, FINANCE_FAVORABLE, AUDITOR_REJECT])
    orch = NativeOrchestrator(client=client)
    result = orch.run_committee(CANDIDATE)
    assert len(client.calls) == 5  # CEO mai invocato dopo un rigetto a monte
    assert result["final"]["action"] == "SKIP"
    assert result["final"]["rationale"].startswith("[auditor]")


def test_full_approval_yields_buy_with_clamped_stop_loss():
    client = FakeClient(FULL_APPROVAL_SCRIPT)
    orch = NativeOrchestrator(client=client)
    result = orch.run_committee(CANDIDATE)
    assert result["final"]["action"] == "BUY"
    assert result["final"]["final_stop_loss_pct"] == STOP_LOSS_FLOOR


def test_trade_plan_computed_deterministically_on_buy():
    """Entry/stop/take-profit non vengono MAI chiesti all'LLM: sono calcolati da
    modules/trade_proposal.py sui dati tecnici reali del candidato."""
    client = FakeClient(FULL_APPROVAL_SCRIPT)
    orch = NativeOrchestrator(client=client)
    result = orch.run_committee(CANDIDATE)
    plan = result["trade_plan"]
    assert plan is not None
    assert plan["ticker"] == "STMMI.MI"
    assert plan["entry"] == CANDIDATE["entry_price"]
    assert plan["stop"] < plan["entry"]
    assert plan["stop_pct"] <= STOP_LOSS_FLOOR + 1e-9  # BACKSTOP #3: mai oltre il floor
    assert plan["entry"] < plan["t1"] < plan["t2"] < plan["t3"]
    assert plan["rr1"] > 0


def test_trade_plan_is_none_when_technical_data_missing():
    """Mai fabbricare un piano operativo senza ATR reale: se manca il dato tecnico
    il trade_plan resta None invece di inventare un livello di rischio."""
    candidate = {k: v for k, v in CANDIDATE.items() if k != "technical"}
    client = FakeClient(FULL_APPROVAL_SCRIPT)
    orch = NativeOrchestrator(client=client)
    result = orch.run_committee(candidate)
    assert result["final"]["action"] == "BUY"
    assert result.get("trade_plan") is None


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


def test_render_report_includes_entry_stop_take_profit_and_analysis_sections():
    client = FakeClient(FULL_APPROVAL_SCRIPT)
    orch = NativeOrchestrator(client=client)
    result = orch.run_committee(CANDIDATE)
    report = render_report([result], asof="2026-07-01")
    assert "Trigger d'ingresso: 30.00" in report
    assert "Stop-Loss:" in report
    assert "Take Profit: T1" in report
    assert "Analisi fondamentale:" in report
    assert "Analisi tecnica:" in report
    assert "Analisi candlestick:" in report
    assert "Universo unicorni" in report


def test_render_report_labels_unicorn_universe_and_uses_funnel_counts():
    candidate = dict(CANDIDATE, universe="unicorn")
    client = FakeClient(FULL_APPROVAL_SCRIPT)
    orch = NativeOrchestrator(client=client)
    result = orch.run_committee(candidate)
    report = render_report([result], asof="2026-07-01",
                            unicorn_funnel={"screened": 64, "gate_passed": 3})
    assert "[UNICORNO]" in report
    assert "64 candidati analizzati" in report
    assert "3 hanno superato il gate" in report


def test_export_frontend_json_writes_run_manifest_and_latest(tmp_path):
    client = FakeClient(FULL_APPROVAL_SCRIPT)
    orch = NativeOrchestrator(client=client)
    result = orch.run_committee(CANDIDATE)
    payload = export_frontend_json([result], asof="2026-07-01",
                                    unicorn_funnel={"screened": 10, "gate_passed": 2},
                                    frontend_dir=tmp_path)

    data_dir = tmp_path / "public" / "data"
    run_file = json.loads((data_dir / "runs" / "2026-07-01.json").read_text())
    latest = json.loads((data_dir / "latest.json").read_text())
    manifest = json.loads((data_dir / "manifest.json").read_text())

    assert run_file == payload == latest
    assert payload["signals"][0]["ticker"] == "STMMI.MI"
    assert payload["signals"][0]["action"] == "BUY"
    assert payload["signals"][0]["stop"] == payload["signals"][0]["entry"] - \
        (payload["signals"][0]["entry"] * payload["signals"][0]["stop_pct"])
    assert payload["unicorns"]["screened"] == 10
    assert manifest == [{"date": "2026-07-01", "buy": 1, "skip": 0, "total": 1}]


def test_export_frontend_json_is_idempotent_per_date(tmp_path):
    client = FakeClient(FULL_APPROVAL_SCRIPT * 2)
    orch = NativeOrchestrator(client=client)
    result = orch.run_committee(CANDIDATE)
    export_frontend_json([result], asof="2026-07-01", frontend_dir=tmp_path)
    export_frontend_json([result], asof="2026-07-01", frontend_dir=tmp_path)

    manifest = json.loads((tmp_path / "public" / "data" / "manifest.json").read_text())
    assert len(manifest) == 1  # non duplica l'entry della stessa notte


def test_export_frontend_json_manifest_accumulates_multiple_nights(tmp_path):
    client = FakeClient(FULL_APPROVAL_SCRIPT * 2)
    orch = NativeOrchestrator(client=client)
    result = orch.run_committee(CANDIDATE)
    export_frontend_json([result], asof="2026-06-30", frontend_dir=tmp_path)
    export_frontend_json([result], asof="2026-07-01", frontend_dir=tmp_path)

    manifest = json.loads((tmp_path / "public" / "data" / "manifest.json").read_text())
    assert [m["date"] for m in manifest] == ["2026-07-01", "2026-06-30"]  # piu' recenti prima


def test_export_frontend_json_sanitizes_nan_for_strict_json_parsers(tmp_path):
    """Run reale: ebitda_margin puo' essere NaN (operating_income/revenue con revenue
    non valida per un ticker come JPM). json.dumps scrive il bareword NaN, che NON e'
    JSON valido in senso stretto e manda in crash il parser di Vite/Astro in build."""
    candidate = dict(CANDIDATE, fundamentals=dict(CANDIDATE["fundamentals"],
                                                   ebitda_margin=float("nan")))
    client = FakeClient(FULL_APPROVAL_SCRIPT)
    orch = NativeOrchestrator(client=client)
    result = orch.run_committee(candidate)
    export_frontend_json([result], asof="2026-07-01", frontend_dir=tmp_path)

    raw = (tmp_path / "public" / "data" / "latest.json").read_text()
    assert "NaN" not in raw
    payload = json.loads(raw)
    assert payload["signals"][0]["fundamentals"]["ebitda_margin"] is None


def test_report_and_json_include_full_operational_strategy_not_just_price_levels():
    """La sola tripletta entry/stop/take-profit non e' la strategia operativa: mancano
    sizing, rischio in valuta, confidenza e guadagno atteso gia' calcolati da
    modules/trade_proposal.py. Devono comparire sia nel report testuale sia nel JSON."""
    client = FakeClient(FULL_APPROVAL_SCRIPT)
    orch = NativeOrchestrator(client=client)
    result = orch.run_committee(CANDIDATE)

    report = render_report([result], asof="2026-07-01")
    assert "Strategia operativa" in report
    assert "Sizing" in report
    assert "Rischio massimo posizione" in report
    assert "Guadagno atteso" in report

    plan = result["trade_plan"]
    op = _operational_plan_json(plan)
    assert op["confidence"] in ("ALTA", "MEDIA", "BASSA")
    assert op["shares"] > 0
    assert op["position_pct"] > 0
    assert op["max_risk"] > 0
    assert op["notional_capital"] > 0


def test_export_chart_data_writes_ohlcv_and_moving_averages(tmp_path):
    prices = _synthetic_price_history("STMMI.MI", n=260)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    prices.to_csv(data_dir / "mib_data.csv", index=False)

    client = FakeClient(FULL_APPROVAL_SCRIPT)
    orch = NativeOrchestrator(client=client)
    result = orch.run_committee(CANDIDATE)

    frontend_dir = tmp_path / "frontend"
    export_chart_data([result], frontend_dir=frontend_dir, data_dir=data_dir)

    chart_path = frontend_dir / "public" / "data" / "charts" / "STMMI.MI.json"
    assert chart_path.exists()
    chart = json.loads(chart_path.read_text())
    assert chart["ticker"] == "STMMI.MI"
    assert len(chart["candles"]) == 260
    assert len(chart["volume"]) == 260
    assert all(c["high"] >= c["low"] for c in chart["candles"])
    assert all(v["color"] in ("#10b98180", "#f4384580") for v in chart["volume"])
    # SMA200 valida solo dopo le prime 199 barre (rolling su tutta la serie)
    assert 0 < len(chart["sma200"]) <= 61
    assert len(chart["sma20"]) == 241  # 260 - 19 (prime barre insufficienti per SMA20)
    assert "NaN" not in chart_path.read_text()


def test_export_chart_data_uses_unicorn_price_file_for_unicorn_universe(tmp_path):
    prices = _synthetic_price_history("SNOW", n=260)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    prices.to_csv(data_dir / "mib_data_unicorns.csv", index=False)

    candidate = dict(CANDIDATE, ticker="SNOW", universe="unicorn")
    client = FakeClient(FULL_APPROVAL_SCRIPT)
    orch = NativeOrchestrator(client=client)
    result = orch.run_committee(candidate)

    frontend_dir = tmp_path / "frontend"
    export_chart_data([result], frontend_dir=frontend_dir, data_dir=data_dir)

    chart_path = frontend_dir / "public" / "data" / "charts" / "SNOW.json"
    assert chart_path.exists()


def test_auditor_receives_trade_plan_preview_before_deciding():
    """Il trade plan (sizing/rischio/efficienza costi) e' calcolato PRIMA dell'Auditor
    e gli viene passato in anteprima — non e' piu' un fatto scoperto dopo il BUY del CEO."""
    client = FakeClient(FULL_APPROVAL_SCRIPT)
    orch = NativeOrchestrator(client=client)
    orch.run_committee(CANDIDATE)
    auditor_payload = _payload(client.calls[4])
    preview = auditor_payload["trade_plan_preview"]
    assert preview["available"] is True
    assert preview["shares"] > 0
    assert "cost_efficient" in preview


def test_backstop_vetoes_trade_that_sizes_to_zero_shares_regardless_of_llm():
    """Un piano che sizerebbe a 0 azioni sul capitale nozionale e' ineseguibile: deve
    essere bocciato in codice anche se l'Auditor (LLM) lo approva per errore."""
    unexecutable = dict(CANDIDATE, entry_price=25000.0,
                         technical=dict(CANDIDATE["technical"], atr_pct=5.0))
    client = FakeClient(FULL_APPROVAL_SCRIPT)
    orch = NativeOrchestrator(client=client)
    result = orch.run_committee(unexecutable)

    assert result["trade_plan"]["shares"] == 0
    assert result["final"]["action"] == "SKIP"
    assert result["final"]["rationale"].startswith("[auditor]")
    assert any("0 azioni" in note for note in result["stages"]["auditor"]["risk_notes"])


def test_skip_result_does_not_expose_hypothetical_trade_plan_in_json():
    """Un ticker scartato non deve mostrare uno stop/target 'ipotetico' in report/JSON,
    anche se il trade plan e' ora calcolato internamente per ogni candidato valido."""
    client = FakeClient([RESEARCHER_OK, TECHNICAL_FAVORABLE, ANALYST_REJECT])
    orch = NativeOrchestrator(client=client)
    result = orch.run_committee(CANDIDATE)
    assert result["trade_plan"] is not None  # calcolato comunque, per l'Auditor
    assert result["final"]["action"] == "SKIP"

    from orchestrator import _signal_json
    signal = _signal_json(result)
    assert signal["stop"] is None
    assert signal["t1"] is None
    assert signal["operational_plan"] is None

    report = render_report([result], asof="2026-07-01")
    assert "Stop-Loss:" not in report
    assert "Take Profit:" not in report


def test_company_name_returns_ticker_when_unresolvable(tmp_path, monkeypatch):
    """Mai un nome inventato: se non risolvibile (nessuna cache, nessun dato SEC),
    _company_name ritorna il ticker cosi' com'e'."""
    monkeypatch.chdir(tmp_path)
    from orchestrator import _company_name
    assert _company_name("ZZZNONMAPPATO") == "ZZZNONMAPPATO"


def test_company_name_reads_local_cache_without_network(tmp_path, monkeypatch):
    """_company_name non deve MAI fare una chiamata di rete durante il rendering
    del report — usa solo la cache locale gia' scritta da company_names.py."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "ticker_names.csv").write_text("ticker,name\nAMAT,Applied Materials\n")
    from orchestrator import _company_name
    assert _company_name("AMAT") == "Applied Materials"


def test_render_report_shows_company_name_next_to_ticker(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "ticker_names.csv").write_text("ticker,name\nSTMMI.MI,STMicroelectronics N.V.\n")
    client = FakeClient(FULL_APPROVAL_SCRIPT)
    orch = NativeOrchestrator(client=client)
    result = orch.run_committee(CANDIDATE)
    report = render_report([result], asof="2026-07-01")
    assert "STMMI.MI (STMicroelectronics N.V.)" in report


def _result(ticker, action, stop=None, t1=None, t2=None, t3=None):
    plan = {"stop": stop, "t1": t1, "t2": t2, "t3": t3} if stop is not None else None
    return {"ticker": ticker, "final": {"action": action, "rationale": ""}, "trade_plan": plan}


def test_compare_with_previous_detects_new_and_dropped_buys():
    today = [_result("AAA", "BUY", 90, 100, 110, 120), _result("BBB", "SKIP")]
    previous = [_result("BBB", "BUY", 45, 50, 55, 60), _result("AAA", "SKIP")]
    cmp = compare_with_previous(today, previous)
    assert cmp["new_buys"] == ["AAA"]
    assert cmp["dropped_buys"] == ["BBB"]
    assert cmp["confirmed_buys"] == []


def test_compare_with_previous_flags_level_changes_for_confirmed_buys():
    today = [_result("AAA", "BUY", 91, 100, 110, 120)]
    previous = [_result("AAA", "BUY", 90, 100, 110, 120)]
    cmp = compare_with_previous(today, previous)
    assert cmp["confirmed_buys"] == ["AAA"]
    assert len(cmp["level_changes"]) == 1
    assert cmp["level_changes"][0]["ticker"] == "AAA"
    assert cmp["level_changes"][0]["changes"] == {"stop": {"was": 90, "now": 91}}


def test_compare_with_previous_reports_no_changes_when_levels_identical():
    today = [_result("AAA", "BUY", 90, 100, 110, 120)]
    previous = [_result("AAA", "BUY", 90, 100, 110, 120)]
    cmp = compare_with_previous(today, previous)
    assert cmp["confirmed_buys"] == ["AAA"]
    assert cmp["level_changes"] == []


def test_compare_with_previous_with_no_prior_run_data_is_empty_but_safe():
    today = [_result("AAA", "BUY", 90, 100, 110, 120)]
    cmp = compare_with_previous(today, [])
    assert cmp["new_buys"] == ["AAA"]
    assert cmp["dropped_buys"] == []
    assert cmp["confirmed_buys"] == []


def test_load_previous_results_finds_most_recent_prior_run(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "committee_output_2026-06-28.json").write_text(json.dumps([{"ticker": "OLD"}]))
    (data_dir / "committee_output_2026-06-30.json").write_text(json.dumps([{"ticker": "RECENT"}]))
    results, date = _load_previous_results("2026-07-01", data_dir=data_dir)
    assert date == "2026-06-30"
    assert results == [{"ticker": "RECENT"}]


def test_load_previous_results_returns_none_when_no_prior_run_exists(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    results, date = _load_previous_results("2026-07-01", data_dir=data_dir)
    assert results is None
    assert date is None


def test_render_report_includes_comparison_section_when_provided():
    result = _result("AAA", "SKIP")
    comparison = {"new_buys": ["AAA"], "dropped_buys": [], "confirmed_buys": [], "level_changes": []}
    report = render_report([result], asof="2026-07-01", comparison=comparison, previous_date="2026-06-30")
    assert "CONFRONTO CON IL RUN PRECEDENTE (2026-06-30)" in report
    assert "Nuovi BUY oggi: AAA" in report
