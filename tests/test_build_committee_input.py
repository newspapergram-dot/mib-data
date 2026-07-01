"""Verifica il Data Parser: mai fabbricare fondamentali mancanti, mai propagare
NaN/valori incompleti nel JSON dato in pasto al Comitato."""
import pandas as pd

import build_committee_input as bci


def _write(tmp_path, name, df):
    path = tmp_path / name
    df.to_csv(path, index=False)
    return str(path)


def test_eu_ticker_skipped_without_debt_to_equity(tmp_path):
    score = pd.DataFrame([{"ticker": "ENEL.MI", "score": 0.5, "price": 6.0}])
    regime = pd.DataFrame([{"market": "IT", "regime": "TREND_UP"}])
    fund_eu = pd.DataFrame([{"ticker": "ENEL.MI", "revenue": 1e9, "net_income": 1e8}])  # niente debt_to_equity

    score_p = _write(tmp_path, "score.csv", score)
    regime_p = _write(tmp_path, "regime.csv", regime)
    fund_eu_p = _write(tmp_path, "fund_eu.csv", fund_eu)
    fund_us_p = str(tmp_path / "nope.csv")  # assente apposta

    candidates, skipped = bci.build(score_path=score_p, fund_us_path=fund_us_p,
                                     fund_eu_path=fund_eu_p, regime_path=regime_p)

    assert candidates == []
    assert any("ENEL.MI" in tk and "privo di debt_to_equity" in reason for tk, reason in skipped)


def test_us_ticker_with_complete_fundamentals_is_included_and_schema_valid(tmp_path):
    score = pd.DataFrame([{"ticker": "AAPL", "score": 0.42, "price": 210.0}])
    regime = pd.DataFrame([{"market": "US", "regime": "TREND_UP"}])
    fund_us = pd.DataFrame([{
        "ticker": "AAPL", "debt_to_equity": 2.48, "operating_income": 1.47e11,
        "revenue": 4.5e11, "eps_growth_yoy": 0.227, "ocf": 1.4e11,
    }])

    score_p = _write(tmp_path, "score.csv", score)
    regime_p = _write(tmp_path, "regime.csv", regime)
    fund_us_p = _write(tmp_path, "fund_us.csv", fund_us)
    fund_eu_p = str(tmp_path / "nope.csv")

    candidates, skipped = bci.build(score_path=score_p, fund_us_path=fund_us_p,
                                     fund_eu_path=fund_eu_p, regime_path=regime_p)

    assert len(candidates) == 1
    assert skipped == []
    c = candidates[0]
    assert c["ticker"] == "AAPL"
    assert c["market"] == "US"
    assert c["regime_gate"] == "TREND_UP"
    assert c["fundamentals"]["debt_to_equity"] == 2.48

    from orchestrator import validate_candidate
    ok, err = validate_candidate(c)
    assert ok, err


def test_us_ticker_with_incomplete_fundamentals_is_skipped_not_fabricated(tmp_path):
    score = pd.DataFrame([{"ticker": "XYZ", "score": 0.3, "price": 50.0}])
    regime = pd.DataFrame([{"market": "US", "regime": "TREND_UP"}])
    fund_us = pd.DataFrame([{
        "ticker": "XYZ", "debt_to_equity": None, "operating_income": 1e8,
        "revenue": 1e9, "eps_growth_yoy": 0.1, "ocf": 5e7,
    }])

    score_p = _write(tmp_path, "score.csv", score)
    regime_p = _write(tmp_path, "regime.csv", regime)
    fund_us_p = _write(tmp_path, "fund_us.csv", fund_us)
    fund_eu_p = str(tmp_path / "nope.csv")

    candidates, skipped = bci.build(score_path=score_p, fund_us_path=fund_us_p,
                                     fund_eu_path=fund_eu_p, regime_path=regime_p)

    assert candidates == []
    assert any("XYZ" in tk for tk, _ in skipped)


def test_non_trend_up_regime_maps_to_trend_down_gate(tmp_path):
    score = pd.DataFrame([{"ticker": "AAPL", "score": 0.42, "price": 210.0}])
    regime = pd.DataFrame([{"market": "US", "regime": "PULLBACK"}])
    fund_us = pd.DataFrame([{
        "ticker": "AAPL", "debt_to_equity": 2.48, "operating_income": 1.47e11,
        "revenue": 4.5e11, "eps_growth_yoy": 0.227, "ocf": 1.4e11,
    }])
    score_p = _write(tmp_path, "score.csv", score)
    regime_p = _write(tmp_path, "regime.csv", regime)
    fund_us_p = _write(tmp_path, "fund_us.csv", fund_us)
    fund_eu_p = str(tmp_path / "nope.csv")

    candidates, _ = bci.build(score_path=score_p, fund_us_path=fund_us_p,
                               fund_eu_path=fund_eu_p, regime_path=regime_p)

    assert candidates[0]["regime_gate"] == "TREND_DOWN"  # solo TREND_UP e' operabile (LOOP.md)
