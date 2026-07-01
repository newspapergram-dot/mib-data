"""Verifica il Data Parser: mai fabbricare fondamentali/tecnici/candlestick mancanti,
mai propagare NaN/valori incompleti nel JSON dato in pasto al Comitato. Copre anche
l'ingest dell'universo unicorni (satellite separato, stesse regole dei mega-cap)."""
import math

import pandas as pd

import build_committee_input as bci

TECH_OK = {"rsi": 55.0, "adx": 22.0, "atr_pct": 1.5, "mom6m": 12.0,
           "sma20": 205.0, "sma50": 200.0, "sma200": 190.0}


def _write(tmp_path, name, df):
    path = tmp_path / name
    df.to_csv(path, index=False)
    return str(path)


def _synthetic_price_history(ticker, n=260, start=100.0):
    """Storico prezzi sintetico con trend + oscillazione (evita degenerazioni
    matematiche in RSI/ADX/ATR su una serie perfettamente piatta o monotona)."""
    rows = []
    price = start
    for i in range(n):
        price += 0.15 + 0.8 * math.sin(i / 7.0)
        high = price + 0.6
        low = price - 0.6
        rows.append({"ticker": ticker, "date": f"2025-{(i % 12) + 1:02d}-{(i % 28) + 1:02d}",
                     "open": price, "high": high, "low": low, "close": price,
                     "volume": 1_000_000})
    return pd.DataFrame(rows)


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
    score = pd.DataFrame([dict({"ticker": "AAPL", "score": 0.42, "price": 210.0}, **TECH_OK)])
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
                                     fund_eu_path=fund_eu_p, regime_path=regime_p,
                                     patterns_path=str(tmp_path / "nope_patterns.csv"))

    assert len(candidates) == 1
    assert skipped == []
    c = candidates[0]
    assert c["ticker"] == "AAPL"
    assert c["market"] == "US"
    assert c["universe"] == "mega_cap"
    assert c["regime_gate"] == "TREND_UP"
    assert c["fundamentals"]["debt_to_equity"] == 2.48
    assert c["technical"]["rsi"] == 55.0
    # patterns.csv assente -> placeholder onesto, mai un pattern inventato
    assert c["candlestick"]["trend"] is None
    assert "non disponibili" in c["candlestick"]["notes"]

    from orchestrator import validate_candidate
    ok, err = validate_candidate(c)
    assert ok, err


def test_candlestick_populated_from_patterns_csv(tmp_path):
    score = pd.DataFrame([dict({"ticker": "AAPL", "score": 0.42, "price": 210.0}, **TECH_OK)])
    regime = pd.DataFrame([{"market": "US", "regime": "TREND_UP"}])
    fund_us = pd.DataFrame([{
        "ticker": "AAPL", "debt_to_equity": 2.48, "operating_income": 1.47e11,
        "revenue": 4.5e11, "eps_growth_yoy": 0.227, "ocf": 1.4e11,
    }])
    patterns = pd.DataFrame([{
        "ticker": "AAPL", "trend": "up", "trend_strength": "forte", "structure": "higher-highs",
        "continuation": None, "breakout": "sopra 215.0", "pullback": False,
        "rsi_divergence": None, "bollinger": "upper-band", "notes": "",
    }])

    score_p = _write(tmp_path, "score.csv", score)
    regime_p = _write(tmp_path, "regime.csv", regime)
    fund_us_p = _write(tmp_path, "fund_us.csv", fund_us)
    patterns_p = _write(tmp_path, "patterns.csv", patterns)

    candidates, _ = bci.build(score_path=score_p, fund_us_path=fund_us_p,
                               fund_eu_path=str(tmp_path / "nope.csv"), regime_path=regime_p,
                               patterns_path=patterns_p)

    assert candidates[0]["candlestick"]["trend"] == "up"
    assert candidates[0]["candlestick"]["breakout"] == "sopra 215.0"


def test_us_ticker_with_incomplete_fundamentals_is_skipped_not_fabricated(tmp_path):
    score = pd.DataFrame([dict({"ticker": "XYZ", "score": 0.3, "price": 50.0}, **TECH_OK)])
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


def test_us_ticker_missing_technical_indicators_is_skipped_not_fabricated(tmp_path):
    """Fondamentali completi ma RSI/ADX/ATR% assenti da score_output.csv: il ticker
    va escluso, non ricevere un piano di rischio (ATR) fabbricato a valle."""
    score = pd.DataFrame([{"ticker": "AAPL", "score": 0.42, "price": 210.0}])  # niente rsi/adx/atr_pct
    regime = pd.DataFrame([{"market": "US", "regime": "TREND_UP"}])
    fund_us = pd.DataFrame([{
        "ticker": "AAPL", "debt_to_equity": 2.48, "operating_income": 1.47e11,
        "revenue": 4.5e11, "eps_growth_yoy": 0.227, "ocf": 1.4e11,
    }])

    score_p = _write(tmp_path, "score.csv", score)
    regime_p = _write(tmp_path, "regime.csv", regime)
    fund_us_p = _write(tmp_path, "fund_us.csv", fund_us)

    candidates, skipped = bci.build(score_path=score_p, fund_us_path=fund_us_p,
                                     fund_eu_path=str(tmp_path / "nope.csv"), regime_path=regime_p)

    assert candidates == []
    assert any("AAPL" in tk and "RSI/ADX/ATR" in reason for tk, reason in skipped)


def test_non_trend_up_regime_maps_to_trend_down_gate(tmp_path):
    score = pd.DataFrame([dict({"ticker": "AAPL", "score": 0.42, "price": 210.0}, **TECH_OK)])
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


def test_unicorn_sleeve_pass_ticker_is_included_with_universe_tag(tmp_path):
    score = pd.DataFrame([dict({"ticker": "AAPL", "score": 0.42, "price": 210.0}, **TECH_OK)])
    regime = pd.DataFrame([{"market": "US", "regime": "TREND_UP"}])
    fund_us = pd.DataFrame([
        {"ticker": "AAPL", "debt_to_equity": 2.48, "operating_income": 1.47e11,
         "revenue": 4.5e11, "eps_growth_yoy": 0.227, "ocf": 1.4e11},
        {"ticker": "SNOW", "debt_to_equity": 0.9, "operating_income": 2e8,
         "revenue": 3e9, "eps_growth_yoy": 0.35, "ocf": 4e8},
    ])
    sleeve = pd.DataFrame([{"ticker": "SNOW", "mom_score": 0.61, "rev_yoy": 0.30,
                            "price": 180.0, "topq": True, "hypergrowth": True, "PASS": True},
                           {"ticker": "DDOG", "mom_score": 0.40, "rev_yoy": 0.10,
                            "price": 90.0, "topq": False, "hypergrowth": False, "PASS": False}])
    unicorn_prices = _synthetic_price_history("SNOW")

    score_p = _write(tmp_path, "score.csv", score)
    regime_p = _write(tmp_path, "regime.csv", regime)
    fund_us_p = _write(tmp_path, "fund_us.csv", fund_us)
    sleeve_p = _write(tmp_path, "unicorn_sleeve.csv", sleeve)
    prices_p = _write(tmp_path, "mib_data_unicorns.csv", unicorn_prices)

    candidates, skipped = bci.build(score_path=score_p, fund_us_path=fund_us_p,
                                     fund_eu_path=str(tmp_path / "nope.csv"), regime_path=regime_p,
                                     unicorn_sleeve_path=sleeve_p, unicorn_prices_path=prices_p)

    tickers = {c["ticker"] for c in candidates}
    assert "SNOW" in tickers and "DDOG" not in tickers  # DDOG non ha superato il gate
    snow = next(c for c in candidates if c["ticker"] == "SNOW")
    assert snow["universe"] == "unicorn"
    assert snow["technical"]["rsi"] is not None
    assert snow["fundamentals"]["debt_to_equity"] == 0.9

    from orchestrator import validate_candidate
    ok, err = validate_candidate(snow)
    assert ok, err


def test_unicorn_missing_fundamentals_is_skipped_not_fabricated(tmp_path):
    score = pd.DataFrame([dict({"ticker": "AAPL", "score": 0.42, "price": 210.0}, **TECH_OK)])
    regime = pd.DataFrame([{"market": "US", "regime": "TREND_UP"}])
    fund_us = pd.DataFrame([{"ticker": "AAPL", "debt_to_equity": 2.48, "operating_income": 1.47e11,
                             "revenue": 4.5e11, "eps_growth_yoy": 0.227, "ocf": 1.4e11}])
    sleeve = pd.DataFrame([{"ticker": "SNOW", "mom_score": 0.61, "rev_yoy": 0.30,
                            "price": 180.0, "topq": True, "hypergrowth": True, "PASS": True}])

    score_p = _write(tmp_path, "score.csv", score)
    regime_p = _write(tmp_path, "regime.csv", regime)
    fund_us_p = _write(tmp_path, "fund_us.csv", fund_us)  # niente SNOW
    sleeve_p = _write(tmp_path, "unicorn_sleeve.csv", sleeve)

    candidates, skipped = bci.build(score_path=score_p, fund_us_path=fund_us_p,
                                     fund_eu_path=str(tmp_path / "nope.csv"), regime_path=regime_p,
                                     unicorn_sleeve_path=sleeve_p,
                                     unicorn_prices_path=str(tmp_path / "nope_uni_px.csv"))

    assert all(c["ticker"] != "SNOW" for c in candidates)
    assert any("SNOW" in tk and "[unicorno]" in reason for tk, reason in skipped)
