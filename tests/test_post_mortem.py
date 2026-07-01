"""Verifica il ciclo di auto-miglioramento: proposta isolata + applicazione append-only."""
import post_mortem
from tests.fakes import FakeClient

PROPOSAL = {
    "ticker": "BPSO.MI",
    "root_cause": "earnings entro 2gg non filtrati dal gate pre-trade",
    "new_guideline": "Escludere candidati con earnings entro 3 giorni di calendario",
    "target_file": "post_mortem_registry.md",
}


def test_apply_guideline_appends_without_overwriting(tmp_path, monkeypatch):
    registry = tmp_path / "post_mortem_registry.md"
    registry.write_text("# post_mortem_registry.md\n\n## Storico\n\n(vuoto)\n")
    monkeypatch.setattr(post_mortem, "REPO_ROOT", tmp_path)
    original = registry.read_text()

    path = post_mortem.apply_guideline(PROPOSAL)
    updated = path.read_text()

    assert updated.startswith(original)  # append, mai overwrite
    assert "BPSO.MI" in updated
    assert PROPOSAL["root_cause"] in updated


def test_analyze_failed_trade_is_isolated_single_turn():
    client = FakeClient([PROPOSAL])
    trade = {"ticker": "BPSO.MI", "exit_reason": "stop_loss", "pnl_pct": -15.2}

    result = post_mortem.analyze_failed_trade(trade, client=client)

    assert result == PROPOSAL
    assert len(client.calls) == 1
    assert len(client.calls[0]["messages"]) == 1  # stateless: nessuna cronologia del Comitato


def test_run_for_trade_end_to_end(tmp_path, monkeypatch):
    registry = tmp_path / "post_mortem_registry.md"
    registry.write_text("(vuoto)")
    monkeypatch.setattr(post_mortem, "REPO_ROOT", tmp_path)
    client = FakeClient([PROPOSAL])
    trade = {"ticker": "BPSO.MI", "exit_reason": "stop_loss", "pnl_pct": -15.2}

    proposal, path = post_mortem.run_for_trade(trade, client=client)

    assert proposal == PROPOSAL
    assert "BPSO.MI" in path.read_text()
