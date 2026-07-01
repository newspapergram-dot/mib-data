"""build_committee_input.py — Data Parser (Livello 1 del flusso live).

Assembla `data/committee_input.json` — l'input di `orchestrator.py` — a partire
dagli output GIA' DETERMINISTICI della pipeline esistente:
  - `data/score_output.csv`        (score_generator.py: momentum/tecnico, universo mega-cap)
  - `data/regime_filter.csv`       (regime_filter.py: gate di regime per mercato)
  - `data/fundamentals_pit.csv`    (fundamentals_pit.py: fondamentali USA, SEC EDGAR PIT)
  - `data/fundamentals_eu.csv`     (fundamentals_eu.py: fondamentali EU)
  - `data/patterns.csv`            (patterns.py: pattern candlestick/struttura, universo mega-cap)
  - `data/unicorn_sleeve.csv`      (unicorn_validate.py: unicorni che hanno superato il gate
                                     momentum + rev YoY — satellite high-beta, universo separato)
  - `data/mib_data_unicorns.csv`   (unicorn_validate.py: storico prezzi degli unicorni, usato
                                     per calcolare RSI/ADX/ATR/pattern con le stesse funzioni
                                     deterministiche del resto della pipeline)

Filosofia (LOOP.md): mai fabbricare dati. Se i campi richiesti da `data_schema.json`
non sono disponibili per un ticker con un dato REALE, il ticker viene ESCLUSO dal
Comitato con un motivo esplicito — non riceve un valore inventato. Questo vale ora
anche per gli indicatori tecnici (RSI/ADX/ATR%) e per il pattern candlestick: se
mancano, il ticker e' escluso con un motivo esplicito, non riceve un "n/d" travestito
da segnale.

NOTA ONESTA (gap noto, in watch-list STATE.md): `fundamentals_eu.csv` oggi non
contiene `debt_to_equity` ne' una crescita EPS trimestrale, quindi l'universo EU
viene sistematicamente escluso dal Comitato finche' `fundamentals_eu.py` non viene
esteso con quei campi. Non e' un bug di questo script: e' un limite del dato a monte.

Il `regime_gate` dello schema del Comitato e' un gate BINARIO (TREND_UP/TREND_DOWN),
piu' severo del freno a 3 stati di `regime_filter.py` (TREND_UP/LATERALE/PULLBACK/
TREND_DOWN): qualunque stato diverso da TREND_UP viene mappato a TREND_DOWN, cioe'
"non operabile" per il Comitato — errare per prudenza, mai per permissivita'
(stesso principio del gate deterministico, vedi LOOP.md).

UNICORNI: sono un universo SEPARATO dal mega-cap (satellite high-beta, vedi
`unicorn_validate.py`). Vengono aggiunti ai candidati del Comitato SOLO se hanno gia'
superato il gate validato (momentum top-quintile + crescita ricavi YoY>=25%) in
`unicorn_sleeve.csv` — non competono per gli stessi TOP_N slot del mega-cap, sono
sempre etichettati `universe="unicorn"` cosi' che il report li distingua chiaramente,
e sono soggetti alle STESSE regole di schema/regime/fondamentali/tecnici degli altri
candidati (nessuna scorciatoia solo perche' sono "growth").
"""
import json
import datetime
from pathlib import Path

import pandas as pd

from regime_filter import market_of

REPO_ROOT = Path(__file__).resolve().parent
TOP_N = 10


def _regime_gate(market_code, regimes):
    r = regimes.get(market_code, {}).get("regime")
    return "TREND_UP" if r == "TREND_UP" else "TREND_DOWN"


def load_regimes(path="data/regime_filter.csv"):
    df = pd.read_csv(path)
    return {row["market"]: {"regime": row["regime"]} for _, row in df.iterrows()}


def _us_fundamentals(ticker, fund_us):
    """Fondamentali USA da fundamentals_pit.csv. Ritorna (dict, None) o (None, motivo)."""
    if ticker not in fund_us.index:
        return None, "fundamentals_pit.csv incompleto per questo ticker"
    f = fund_us.loc[ticker]
    revenue = float(f.get("revenue", 0) or 0)
    if pd.isna(f.get("debt_to_equity")) or pd.isna(f.get("eps_growth_yoy")) \
            or pd.isna(f.get("ocf")) or revenue <= 0:
        return None, "fundamentals_pit.csv incompleto per questo ticker"
    return {
        "debt_to_equity": float(f["debt_to_equity"]),
        # proxy: operating_income/revenue (nessun D&A separato nel dataset PIT -> non e' EBITDA vera)
        "ebitda_margin": float(f["operating_income"]) / revenue,
        # proxy: crescita EPS YoY, non trimestrale (il dataset PIT non ha granularita' Q su Q)
        "eps_growth_q_on_q": float(f["eps_growth_yoy"]),
        # proxy: OCF, non FCF puro (il dataset PIT non isola il capex)
        "free_cash_flow": float(f["ocf"]),
    }, None


def _technical_fields(row):
    """RSI/ADX/ATR%/SMA/momentum da una riga di score_output.csv. Ritorna (dict, None)
    o (None, motivo). RSI/ADX/ATR% sono essenziali (servono anche al trade plan deterministico
    di modules/trade_proposal.py): se mancano, il ticker va escluso."""
    rsi, adx_v, atr_pct = row.get("rsi"), row.get("adx"), row.get("atr_pct")
    if pd.isna(rsi) or pd.isna(adx_v) or pd.isna(atr_pct):
        return None, "score_output.csv privo di RSI/ADX/ATR%: dato tecnico reale non disponibile"
    return {
        "rsi": float(rsi), "adx": float(adx_v), "atr_pct": float(atr_pct),
        "mom6m": None if pd.isna(row.get("mom6m")) else float(row["mom6m"]),
        "sma20": None if pd.isna(row.get("sma20")) else float(row["sma20"]),
        "sma50": None if pd.isna(row.get("sma50")) else float(row["sma50"]),
        "sma200": None if pd.isna(row.get("sma200")) else float(row["sma200"]),
    }, None


def load_patterns(path="data/patterns.csv"):
    if not Path(path).exists():
        return pd.DataFrame()
    return pd.read_csv(path).drop_duplicates("ticker").set_index("ticker")


def _candlestick_from_patterns_csv(ticker, patterns_df):
    """Pattern grafico da patterns.csv. Se il ticker non ha una riga (script non girato
    o storia insufficiente), si dichiara esplicitamente l'assenza — mai un pattern inventato."""
    if patterns_df.empty or ticker not in patterns_df.index:
        return {"trend": None, "trend_strength": None, "structure": None,
                "continuation": None, "breakout": None, "pullback": None,
                "rsi_divergence": None, "bollinger": None,
                "notes": "dati candlestick non disponibili per questo ticker"}
    r = patterns_df.loc[ticker]
    return _candlestick_from_pattern_dict(r.to_dict())


def _candlestick_from_pattern_dict(pattern):
    def _v(key):
        val = pattern.get(key)
        return None if val is None or (isinstance(val, float) and pd.isna(val)) else val
    return {
        "trend": _v("trend"), "trend_strength": _v("trend_strength"),
        "structure": _v("structure"), "continuation": _v("continuation"),
        "breakout": _v("breakout"), "pullback": _v("pullback"),
        "rsi_divergence": _v("rsi_divergence"), "bollinger": _v("bollinger"),
        "notes": _v("notes") or "",
    }


def build(score_path="data/score_output.csv",
          fund_us_path="data/fundamentals_pit.csv",
          fund_eu_path="data/fundamentals_eu.csv",
          regime_path="data/regime_filter.csv",
          patterns_path="data/patterns.csv",
          unicorn_sleeve_path="data/unicorn_sleeve.csv",
          unicorn_prices_path="data/mib_data_unicorns.csv",
          top_n=TOP_N):
    score = pd.read_csv(score_path).sort_values("score", ascending=False)
    regimes = load_regimes(regime_path)
    fund_us = (pd.read_csv(fund_us_path).drop_duplicates("ticker").set_index("ticker")
               if Path(fund_us_path).exists() else pd.DataFrame())
    fund_eu = (pd.read_csv(fund_eu_path).drop_duplicates("ticker").set_index("ticker")
               if Path(fund_eu_path).exists() else pd.DataFrame())
    patterns_df = load_patterns(patterns_path)

    candidates, skipped = [], []
    for _, row in score.iterrows():
        if len(candidates) >= top_n:
            break
        ticker = str(row["ticker"])
        market_code = market_of(ticker)
        market = "EU" if market_code in ("IT", "FR") else "US"

        if market == "US":
            fundamentals, reason = _us_fundamentals(ticker, fund_us)
            if fundamentals is None:
                skipped.append((ticker, reason))
                continue
        elif market == "EU":
            skipped.append((ticker, "fundamentals_eu.csv privo di debt_to_equity/eps_growth: "
                                     "dato reale non disponibile, nessun valore inventato"))
            continue
        else:
            skipped.append((ticker, "nessun dato fondamentale trovato per questo ticker"))
            continue

        technical, tech_reason = _technical_fields(row)
        if technical is None:
            skipped.append((ticker, tech_reason))
            continue

        candidates.append({
            "ticker": ticker,
            "market": market,
            "universe": "mega_cap",
            "asof": datetime.date.today().isoformat(),
            "regime_gate": _regime_gate(market_code, regimes),
            "momentum_score": max(0.0, min(1.0, float(row["score"]))),
            "entry_price": float(row["price"]),
            "fundamentals": fundamentals,
            "technical": technical,
            "candlestick": _candlestick_from_patterns_csv(ticker, patterns_df),
        })

    uni_candidates, uni_skipped = _unicorn_candidates(
        regimes, fund_us, sleeve_path=unicorn_sleeve_path, prices_path=unicorn_prices_path)
    candidates.extend(uni_candidates)
    skipped.extend(uni_skipped)
    return candidates, skipped


def _unicorn_candidates(regimes, fund_us, sleeve_path="data/unicorn_sleeve.csv",
                         prices_path="data/mib_data_unicorns.csv"):
    """Ingest degli unicorni che hanno GIA' superato il gate validato (PASS=True in
    unicorn_sleeve.csv, scritto da unicorn_validate.live_sleeve()). Non e' un universo
    parallelo con regole piu' morbide: stessi controlli di fondamentali/tecnici/schema
    dei mega-cap, mai fabbricati."""
    candidates, skipped = [], []
    if not Path(sleeve_path).exists():
        return candidates, skipped
    sleeve = pd.read_csv(sleeve_path)
    if "PASS" not in sleeve.columns:
        return candidates, skipped
    passed = sleeve[sleeve["PASS"].astype(str) == "True"]
    if passed.empty:
        return candidates, skipped

    prices = pd.read_csv(prices_path) if Path(prices_path).exists() else None
    from score_generator import calculate_technical_indicators
    from patterns import detect_patterns

    for _, row in passed.iterrows():
        ticker = str(row["ticker"])
        fundamentals, reason = _us_fundamentals(ticker, fund_us)
        if fundamentals is None:
            skipped.append((ticker, f"[unicorno] {reason}"))
            continue
        if prices is None:
            skipped.append((ticker, "[unicorno] mib_data_unicorns.csv assente: "
                                     "nessuno storico prezzi per calcolare gli indicatori tecnici"))
            continue
        g = prices[prices["ticker"] == ticker].sort_values("date")
        tech = calculate_technical_indicators(g) if not g.empty else {}
        if not tech or tech.get("rsi") is None or tech.get("adx") is None \
                or tech.get("atr_pct") is None:
            skipped.append((ticker, "[unicorno] storico prezzi insufficiente per RSI/ADX/ATR%"))
            continue
        pattern = detect_patterns(g) if not g.empty else {}

        candidates.append({
            "ticker": ticker,
            "market": "US",
            "universe": "unicorn",
            "asof": datetime.date.today().isoformat(),
            "regime_gate": _regime_gate("US", regimes),
            "momentum_score": max(0.0, min(1.0, float(row["mom_score"]))),
            "entry_price": float(row["price"]),
            "fundamentals": fundamentals,
            "technical": {
                "rsi": tech["rsi"], "adx": tech["adx"], "atr_pct": tech["atr_pct"],
                "mom6m": tech.get("mom6m"), "sma20": tech.get("sma20"),
                "sma50": tech.get("sma50"), "sma200": tech.get("sma200"),
            },
            "candlestick": _candlestick_from_pattern_dict(pattern),
        })
    return candidates, skipped


def main():
    candidates, skipped = build()
    data_dir = REPO_ROOT / "data"
    data_dir.mkdir(exist_ok=True)
    out_path = data_dir / "committee_input.json"
    out_path.write_text(json.dumps(candidates, indent=2, ensure_ascii=False))
    print(f"[data-parser] {len(candidates)} candidati scritti in {out_path}")
    for tk, reason in skipped:
        print(f"[data-parser] SKIP {tk}: {reason}")


if __name__ == "__main__":
    main()
