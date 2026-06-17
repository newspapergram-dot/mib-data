"""
backtest_lookup.py — Validazione track record per candidati settimanali.
Dato un candidato (ticker + caratteristiche del setup), cerca nel
backtest_report.csv tutti i trade storici con setup simile e restituisce:
  - hit rate storico
  - rendimento medio
  - rendimento mediano
  - max drawdown medio
  - numero di occorrenze
  - confidenza (ALTA / MEDIA / BASSA / INSUFFICIENTE)
"""

import numpy as np
import pandas as pd

DEFAULT_HZ = 10

CONF_THRESHOLDS = {
    "min_occurrences": 8,
    "high_hit_rate":   0.65,
    "min_hit_rate":    0.50,
    "high_ret":        1.5,
    "min_ret":         0.0,
}


def lookup_track_record(
    ticker: str,
    score: float,
    patterns: dict,
    bt_df: pd.DataFrame,
    hz: int = DEFAULT_HZ,
    score_tolerance: float = 0.15,
) -> dict:
    col = f"fwd_{hz}_net"

    empty = {
        "hit_rate": None, "ret_mean": None, "ret_median": None,
        "ret_std": None, "n_total": 0, "n_same_ticker": 0,
        "n_similar_setup": 0, "confidenza": "NON DISPONIBILE",
        "label": "Track record non disponibile",
        "same_ticker_stats": {}
    }

    if bt_df is None or bt_df.empty or col not in bt_df.columns:
        return empty

    bt = bt_df[bt_df["score_version"] == "NUOVO"].copy() if "score_version" in bt_df.columns else bt_df.copy()
    bt = bt.dropna(subset=[col])
    if bt.empty:
        return {**empty, "label": "Nessun trade NUOVO nel backtest"}

    same_tk = bt[bt["ticker"] == ticker][col]
    same_ticker_stats = {}
    if len(same_tk) >= 3:
        same_ticker_stats = {
            "n": int(len(same_tk)),
            "hit_rate": float((same_tk > 0).mean()),
            "ret_mean": float(same_tk.mean()),
            "ret_median": float(same_tk.median()),
        }

    mask = (bt["score"] >= score - score_tolerance) & \
           (bt["score"] <= score + score_tolerance)

    breakout     = patterns.get("breakout", False)
    strong_trend = patterns.get("strong_trend", False)

    if breakout and "breakout" in bt.columns:
        mask = mask & (bt["breakout"] == True)
    if strong_trend and "strong_trend" in bt.columns:
        mask = mask & (bt["strong_trend"] == True)

    similar = bt[mask][col]
    n_sim = len(similar)
    note = ""

    if n_sim < CONF_THRESHOLDS["min_occurrences"]:
        similar_loose = bt[
            (bt["score"] >= score - score_tolerance) &
            (bt["score"] <= score + score_tolerance)
        ][col]
        if len(similar_loose) >= CONF_THRESHOLDS["min_occurrences"]:
            similar = similar_loose
            n_sim = len(similar)
            note = " (filtro pattern rilassato)"
        else:
            similar_wide = bt[
                (bt["score"] >= score - 0.25) &
                (bt["score"] <= score + 0.25)
            ][col]
            if len(similar_wide) >= CONF_THRESHOLDS["min_occurrences"]:
                similar = similar_wide
                n_sim = len(similar)
                note = " (range score allargato)"
            else:
                return {
                    **empty,
                    "n_total": len(bt),
                    "n_same_ticker": len(same_tk),
                    "n_similar_setup": n_sim,
                    "same_ticker_stats": same_ticker_stats,
                    "confidenza": "INSUFFICIENTE",
                    "label": f"Solo {n_sim} occorrenze simili (min {CONF_THRESHOLDS['min_occurrences']})",
                }

    hit_rate  = float((similar > 0).mean())
    ret_mean  = float(similar.mean())
    ret_med   = float(similar.median())
    ret_std   = float(similar.std(ddof=1))
    maxdd_mean = float(similar[similar < 0].mean()) if (similar < 0).any() else 0.0

    thr = CONF_THRESHOLDS
    if hit_rate >= thr["high_hit_rate"] and ret_mean >= thr["high_ret"]:
        confidenza = "ALTA"; icon = "✅"
    elif hit_rate < thr["min_hit_rate"] or ret_mean < thr["min_ret"]:
        confidenza = "BASSA"; icon = "⚠️"
    else:
        confidenza = "MEDIA"; icon = "🟡"

    label = (
        f"{icon} {confidenza} — "
        f"{n_sim} occorrenze{note} | "
        f"hit {hit_rate*100:.0f}% | "
        f"ret medio {ret_mean:+.1f}% | "
        f"mediana {ret_med:+.1f}%"
    )

    return {
        "hit_rate": hit_rate, "ret_mean": ret_mean, "ret_median": ret_med,
        "ret_std": ret_std, "maxdd_mean": maxdd_mean, "n_total": len(bt),
        "n_same_ticker": len(same_tk), "n_similar_setup": n_sim,
        "confidenza": confidenza, "label": label,
        "same_ticker_stats": same_ticker_stats,
    }


def load_backtest(url: str = None, path: str = "data/backtest_report.csv") -> pd.DataFrame:
    import os
    if url:
        try:
            import urllib.request, io
            raw = urllib.request.urlopen(url, timeout=20).read().decode("utf-8", "replace")
            df = pd.read_csv(io.StringIO(raw))
            print(f"[lookup] backtest caricato da URL: {len(df)} righe")
            return df
        except Exception as e:
            print(f"[lookup] URL non disponibile: {e}")
    if os.path.exists(path):
        try:
            df = pd.read_csv(path)
            print(f"[lookup] backtest caricato da disco: {len(df)} righe")
            return df
        except Exception as e:
            print(f"[lookup] disco non disponibile: {e}")
    print("[lookup] backtest_report.csv non trovato — track record non disponibile")
    return None


def track_record_html(tr: dict, ticker: str, hz: int = DEFAULT_HZ) -> str:
    if tr["confidenza"] == "NON DISPONIBILE":
        return """
        <div class="tr-block tr-na">
          <div class="tr-title">📊 Track Record (backtest storico)</div>
          <div class="tr-na-msg">File backtest non ancora disponibile —
          eseguire backtest_v3.py e aggiornare il repo.</div>
        </div>"""

    if tr["confidenza"] == "INSUFFICIENTE":
        return f"""
        <div class="tr-block tr-low">
          <div class="tr-title">📊 Track Record (backtest storico, hold {hz}gg)</div>
          <div class="tr-na-msg">⚠️ {tr['label']}</div>
        </div>"""

    color_map = {"ALTA": "#0d5c4a", "MEDIA": "#a16207", "BASSA": "#9a3412"}
    color = color_map.get(tr["confidenza"], "#6b7280")

    tk_html = ""
    stk = tr.get("same_ticker_stats", {})
    if stk:
        tk_html = f"""
        <div class="tr-ticker-note">
          Storico specifico {ticker}: {stk['n']} trade |
          hit {stk['hit_rate']*100:.0f}% |
          ret medio {stk['ret_mean']:+.1f}%
        </div>"""

    return f"""
    <div class="tr-block">
      <div class="tr-head">
        <span class="tr-title">📊 Track Record (backtest storico, hold {hz}gg)</span>
        <span class="tr-badge" style="background:{color}">{tr['confidenza']}</span>
      </div>
      <div class="tr-grid">
        <div class="tr-kpi"><div class="tr-kv">{tr['hit_rate']*100:.0f}%</div><div class="tr-kl">Hit Rate</div></div>
        <div class="tr-kpi"><div class="tr-kv">{tr['ret_mean']:+.1f}%</div><div class="tr-kl">Ret. Medio</div></div>
        <div class="tr-kpi"><div class="tr-kv">{tr['ret_median']:+.1f}%</div><div class="tr-kl">Mediana</div></div>
        <div class="tr-kpi"><div class="tr-kv">{tr['ret_std']:.1f}%</div><div class="tr-kl">Volatilità</div></div>
        <div class="tr-kpi"><div class="tr-kv">{tr['n_similar_setup']}</div><div class="tr-kl">Occorrenze</div></div>
        <div class="tr-kpi"><div class="tr-kv">{tr['maxdd_mean']:+.1f}%</div><div class="tr-kl">Loss Medio</div></div>
      </div>
      {tk_html}
    </div>"""


TRACK_RECORD_CSS = """
  .tr-block { border:1px solid var(--line); border-radius:5px; padding:16px 18px;
    margin:16px 0 20px; background:var(--paper); }
  .tr-block.tr-na { border-color:#d1d5db; }
  .tr-block.tr-low { border-color:#e9b949; background:var(--warn-bg); }
  .tr-head { display:flex; align-items:center; justify-content:space-between;
    margin-bottom:14px; }
  .tr-title { font-family:'Archivo',sans-serif; font-weight:700; font-size:13px;
    color:var(--ink); }
  .tr-badge { font-family:'Archivo',sans-serif; font-weight:700; font-size:11px;
    color:#fff; padding:4px 12px; border-radius:20px; letter-spacing:0.05em; }
  .tr-grid { display:grid; grid-template-columns:repeat(6,1fr); gap:1px;
    background:var(--line); border:1px solid var(--line); border-radius:4px;
    overflow:hidden; margin-bottom:10px; }
  .tr-kpi { background:var(--card); padding:10px 6px; text-align:center; }
  .tr-kv { font-family:'JetBrains Mono',monospace; font-weight:700; font-size:14px;
    color:var(--ink); }
  .tr-kl { font-family:'Archivo',sans-serif; font-size:9px; letter-spacing:0.08em;
    text-transform:uppercase; color:var(--mut); margin-top:3px; }
  .tr-na-msg { font-size:13.5px; color:var(--mut); font-family:'Archivo',sans-serif; }
  .tr-ticker-note { font-family:'JetBrains Mono',monospace; font-size:11.5px;
    color:var(--mut); padding:6px 10px; background:var(--paper);
    border-radius:4px; margin-top:8px; }
  @media(max-width:640px){ .tr-grid{grid-template-columns:repeat(3,1fr);} }
"""


if __name__ == "__main__":
    bt = load_backtest(
        url="https://raw.githubusercontent.com/newspapergram-dot/mib-data/refs/heads/main/data/backtest_report.csv"
    )
    test_candidates = [
        {"ticker": "STMMI.MI", "score": 0.55, "patterns": {"breakout": True,  "strong_trend": True}},
        {"ticker": "GOOGL",    "score": 0.33, "patterns": {"breakout": False, "strong_trend": False}},
    ]
    for c in test_candidates:
        tr = lookup_track_record(c["ticker"], c["score"], c["patterns"], bt)
        print(f"\n{c['ticker']} (score {c['score']}): {tr['label']}")
