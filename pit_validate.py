"""pit_validate.py — Il filtro QUALITA' FONDAMENTALE PIT regge su un ciclo completo?

Il backtest sez.9 ha validato il filtro PIT su 14 mesi (prevalentemente bull): PIT>=0.60
migliorava il top-quintile (ret +3.30%, Sharpe 1.50). Ma e' un effetto bull-concentrato
(come lo score, Lezione #11) o tiene anche in BEAR? Qui si valida su 2018-2026 (con crash
2020 e bear 2022), segmentando per regime.

Metodo (point-in-time, no lookahead):
  - segnali score NUOVO sul dataset LUNGO (data/mib_data_long.csv, prezzi aggiustati);
  - per ogni segnale, fondamentali SEC EDGAR con filed <= data segnale (bt.pit_lookup);
  - pit_quality_score (definizione canonica in modules.fundamentals);
  - regime bull/bear via ^GSPC vs SMA200 (stesso criterio di bt.regime_analysis);
  - confronto top-quintile base vs +PIT>=0.60 vs net_margin>=10%, DENTRO ciascun regime.

Domanda a cui risponde: il filtro fondamentale e' una leva di affidabilita' robusta al
bear, o va usato (come lo score) solo dentro il gate di regime TREND_UP?
"""
import numpy as np
import pandas as pd
import backtest_v3 as bt
from modules.fundamentals import pit_quality_score


def _add_regime(sig, px, sma_window=200):
    """Aggiunge la colonna 'regime' (bull/bear/unknown) ai segnali, via ^GSPC/SMA200.
    Un solo benchmark, deduplicato per data (stessa logica di bt.regime_analysis)."""
    bench = pd.DataFrame()
    for cand in ["^GSPC", "SPY"]:
        cand_df = px[px["ticker"] == cand]
        if not cand_df.empty:
            bench = cand_df.copy()
            break
    if bench.empty:
        sig["regime"] = "unknown"
        return sig
    bench = (bench.sort_values("date").dropna(subset=["close"]).drop_duplicates("date"))
    bench["sma"] = bench["close"].rolling(sma_window).mean()
    bench["regime"] = np.where(bench["close"] > bench["sma"], "bull", "bear")
    bench = bench[["date", "regime"]].set_index("date")
    sig = sig.join(bench["regime"], on="date", how="left")
    sig["regime"] = sig["regime"].fillna("unknown")
    return sig


def _metrics(a, hz):
    """Metriche per-trade su array di rendimenti (frazione). None se troppo pochi."""
    a = np.asarray(a, float)
    a = a[~np.isnan(a)]
    if len(a) < 5:
        return None
    sd = a.std(ddof=1) or 1e-9
    pf = a[a > 0].sum() / (-a[a < 0].sum()) if (a < 0).any() else np.inf
    return dict(n=len(a), mean=a.mean() * 100, med=np.median(a) * 100,
                win=(a > 0).mean() * 100, sharpe=a.mean() / sd * np.sqrt(252 / hz), pf=pf)


def _row(name, m):
    if m is None:
        return f"  {name:26s}      (campione insufficiente)"
    pf = "inf" if np.isinf(m["pf"]) else f"{m['pf']:.2f}"
    return (f"  {name:26s}{m['n']:5d}{m['mean']:8.2f}{m['med']:8.2f}"
            f"{m['win']:7.1f}{m['sharpe']:8.2f}{pf:>7s}")


def run(px_path="data/mib_data_long.csv", hz=10):
    px = pd.read_csv(px_path, parse_dates=["date"]).dropna(subset=["close"])
    print(f"[pit_validate] dataset {px['date'].min().date()} -> {px['date'].max().date()} "
          f"| {px['ticker'].nunique()} ticker")

    pit_data = bt.load_pit()
    print(f"[pit_validate] PIT fondamentali: {len(pit_data)} ticker (filed range storico)")

    sig = bt.build_signals(px, bt.score_new, horizons=(5, 10, 20), pit_data=pit_data or None)
    sig = _add_regime(sig, px)
    col = f"fwd_{hz}_net"
    sig = sig.dropna(subset=[col])
    has_pit = sig["pit_quality"].notna()
    print(f"[pit_validate] segnali: {len(sig)} | con PIT (USA): {has_pit.sum()} "
          f"({has_pit.mean()*100:.0f}%)")

    p80 = sig["score"].quantile(0.80)
    top = sig[sig["score"] >= p80].copy()
    top_pit = top[top["pit_quality"].notna()].copy()

    header = f"  {'selezione':26s}{'n':>5}{'mean%':>8}{'med%':>8}{'win%':>7}{'Sharpe':>8}{'PF':>7}"

    # ── A) Ciclo completo ────────────────────────────────────────────────────
    print("\n" + "=" * 72)
    print(f"A) CICLO COMPLETO 2018-2026 — top-quintile, hold {hz}gg (netto)")
    print("=" * 72)
    print(header)
    print(_row("base (tutti)", _metrics(top[col] / 100, hz)))
    print(_row("solo USA (ha PIT)", _metrics(top_pit[col] / 100, hz)))
    print(_row("+ PIT >= 0.60", _metrics(top_pit[top_pit["pit_quality"] >= 0.60][col] / 100, hz)))
    print(_row("+ PIT >= 0.80", _metrics(top_pit[top_pit["pit_quality"] >= 0.80][col] / 100, hz)))
    nm = top_pit[top_pit["pit_net_margin"].notna()].copy()
    nm["pit_net_margin"] = nm["pit_net_margin"].astype(float)
    print(_row("+ net margin >= 10%", _metrics(nm[nm["pit_net_margin"] >= 0.10][col] / 100, hz)))
    print(_row("net margin < 0 (perdita)", _metrics(nm[nm["pit_net_margin"] < 0][col] / 100, hz)))

    # ── B) Segmentato per regime (la domanda chiave) ─────────────────────────
    print("\n" + "=" * 72)
    print(f"B) PER REGIME — il filtro PIT aiuta anche in BEAR? (top-quintile USA, {hz}gg)")
    print("=" * 72)
    for reg in ["bull", "bear"]:
        sub = top_pit[top_pit["regime"] == reg]
        print(f"\n  --- regime {reg.upper()} (n={len(sub)} segnali USA top-quintile) ---")
        print(header)
        base_m = _metrics(sub[col] / 100, hz)
        pit_m = _metrics(sub[sub["pit_quality"] >= 0.60][col] / 100, hz)
        print(_row("base USA", base_m))
        print(_row("+ PIT >= 0.60", pit_m))
        if base_m and pit_m:
            d_ret = pit_m["mean"] - base_m["mean"]
            d_win = pit_m["win"] - base_m["win"]
            d_shp = pit_m["sharpe"] - base_m["sharpe"]
            verdict = "AIUTA" if (d_ret > 0 and d_shp > 0) else ("NEUTRO" if abs(d_ret) < 0.2 else "PEGGIORA")
            print(f"  -> delta filtro PIT: ret {d_ret:+.2f}% | win {d_win:+.1f}% | "
                  f"Sharpe {d_shp:+.2f}  => {verdict}")

    # ── C) Correlazione pit_quality vs forward return per regime ─────────────
    print("\n" + "=" * 72)
    print("C) SPEARMAN pit_quality vs forward return (top-quintile USA)")
    print("=" * 72)
    for reg in ["bull", "bear"]:
        sub = top_pit[top_pit["regime"] == reg].dropna(subset=["pit_quality", col])
        if len(sub) > 10:
            corr = sub[["pit_quality", col]].corr("spearman").iloc[0, 1]
            print(f"  {reg:5s}: Spearman {corr:+.4f} (n={len(sub)})")
        else:
            print(f"  {reg:5s}: campione insufficiente (n={len(sub)})")

    print("\n[pit_validate] NB: campioni bear piccoli, metriche in-sample. Il filtro PIT")
    print("  va letto come leva di affidabilita' dentro il gate di regime, non come veto autonomo.")


if __name__ == "__main__":
    run(hz=10)
    run(hz=20)
