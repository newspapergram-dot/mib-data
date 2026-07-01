"""build_committee_input.py — Data Parser (Livello 1 del flusso live).

Assembla `data/committee_input.json` — l'input di `orchestrator.py` — a partire
dagli output GIA' DETERMINISTICI della pipeline esistente:
  - `data/score_output.csv`      (score_generator.py: momentum/tecnico)
  - `data/regime_filter.csv`     (regime_filter.py: gate di regime per mercato)
  - `data/fundamentals_pit.csv`  (fundamentals_pit.py: fondamentali USA, SEC EDGAR PIT)
  - `data/fundamentals_eu.csv`   (fundamentals_eu.py: fondamentali EU)

Filosofia (LOOP.md): mai fabbricare dati. Se i campi richiesti da `data_schema.json`
non sono disponibili per un ticker con un dato REALE, il ticker viene ESCLUSO dal
Comitato con un motivo esplicito — non riceve un valore inventato.

NOTA ONESTA (gap noto, in watch-list STATE.md): `fundamentals_eu.csv` oggi non
contiene `debt_to_equity` ne' una crescita EPS trimestrale, quindi l'universo EU
viene sistematicamente escluso dal Comitato finche' `fundamentals_eu.py` non viene
esteso con quei campi. Non e' un bug di questo script: e' un limite del dato a monte.

Il `regime_gate` dello schema del Comitato e' un gate BINARIO (TREND_UP/TREND_DOWN),
piu' severo del freno a 3 stati di `regime_filter.py` (TREND_UP/LATERALE/PULLBACK/
TREND_DOWN): qualunque stato diverso da TREND_UP viene mappato a TREND_DOWN, cioe'
"non operabile" per il Comitato — errare per prudenza, mai per permissivita'
(stesso principio del gate deterministico, vedi LOOP.md).
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


def build(score_path="data/score_output.csv",
          fund_us_path="data/fundamentals_pit.csv",
          fund_eu_path="data/fundamentals_eu.csv",
          regime_path="data/regime_filter.csv",
          top_n=TOP_N):
    score = pd.read_csv(score_path).sort_values("score", ascending=False)
    regimes = load_regimes(regime_path)
    fund_us = (pd.read_csv(fund_us_path).drop_duplicates("ticker").set_index("ticker")
               if Path(fund_us_path).exists() else pd.DataFrame())
    fund_eu = (pd.read_csv(fund_eu_path).drop_duplicates("ticker").set_index("ticker")
               if Path(fund_eu_path).exists() else pd.DataFrame())

    candidates, skipped = [], []
    for _, row in score.iterrows():
        if len(candidates) >= top_n:
            break
        ticker = str(row["ticker"])
        market_code = market_of(ticker)
        market = "EU" if market_code in ("IT", "FR") else "US"

        if market == "US" and ticker in fund_us.index:
            f = fund_us.loc[ticker]
            revenue = float(f.get("revenue", 0) or 0)
            if pd.isna(f.get("debt_to_equity")) or pd.isna(f.get("eps_growth_yoy")) \
                    or pd.isna(f.get("ocf")) or revenue <= 0:
                skipped.append((ticker, "fundamentals_pit.csv incompleto per questo ticker"))
                continue
            fundamentals = {
                "debt_to_equity": float(f["debt_to_equity"]),
                # proxy: operating_income/revenue (nessun D&A separato nel dataset PIT -> non e' EBITDA vera)
                "ebitda_margin": float(f["operating_income"]) / revenue,
                # proxy: crescita EPS YoY, non trimestrale (il dataset PIT non ha granularita' Q su Q)
                "eps_growth_q_on_q": float(f["eps_growth_yoy"]),
                # proxy: OCF, non FCF puro (il dataset PIT non isola il capex)
                "free_cash_flow": float(f["ocf"]),
            }
        elif market == "EU":
            skipped.append((ticker, "fundamentals_eu.csv privo di debt_to_equity/eps_growth: "
                                     "dato reale non disponibile, nessun valore inventato"))
            continue
        else:
            skipped.append((ticker, "nessun dato fondamentale trovato per questo ticker"))
            continue

        candidates.append({
            "ticker": ticker,
            "market": market,
            "asof": datetime.date.today().isoformat(),
            "regime_gate": _regime_gate(market_code, regimes),
            "momentum_score": max(0.0, min(1.0, float(row["score"]))),
            "entry_price": float(row["price"]),
            "fundamentals": fundamentals,
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
