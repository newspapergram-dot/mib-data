#!/usr/bin/env python3
"""verify_picks.py — Verifica path-based delle raccomandazioni del giorno precedente.

Passo 1-2 del loop operativo: prende lo snapshot piu' recente PRECEDENTE alla data dei
prezzi correnti (data/journal/<asof>.json) e confronta ogni pick con i prezzi REALI
successivi. Usa i massimi/minimi GIORNALIERI (non solo la chiusura) per rilevare se lo
stop o i target sono stati toccati intraday, e in che ordine cronologico.

Per ogni pick calcola:
  - esito path-based: STOP HIT | T1/T2/T3 RAGGIUNTO | IN CORSO (con primo evento cronologico)
  - drift % dall'entry alla chiusura corrente, MAE (max adverse) e MFE (max favorable)
  - cambio di regime del mercato del titolo tra snapshot e oggi
  - P&L per-share se uscito allo stop / alla chiusura / al target toccato

Output: data/VERIFICATION.txt (leggibile) + data/verification.json (per l'audit sub-agent).
Onesto per costruzione: nessun esito inventato, solo cio' che i prezzi hanno fatto.
"""
import os
import sys
import json
import datetime
import pandas as pd

import journal


def _current_regime():
    """Regime corrente per mercato dal CSV fresco (gia' rigenerato nel loop)."""
    path = "data/regime_filter.csv"
    if not os.path.exists(path):
        return {}
    rf = pd.read_csv(path)
    return {r.market: r.regime for r in rf.itertuples()}


def _bars_after(px, ticker, asof):
    g = px[(px.ticker == ticker) & (px.date > pd.Timestamp(asof))].sort_values("date")
    return g


def verify(px_path="data/mib_data.csv", out_txt="data/VERIFICATION.txt",
           out_json="data/verification.json"):
    px = pd.read_csv(px_path, parse_dates=["date"]).sort_values(["ticker", "date"])
    data_asof = px["date"].max().strftime("%Y-%m-%d")

    prior_path = journal.latest_before(data_asof)
    if not prior_path:
        msg = f"[verify] nessuno snapshot precedente a {data_asof} — niente da verificare."
        print(msg)
        open(out_txt, "w").write(msg + "\n")
        json.dump({"status": "no_prior", "data_asof": data_asof}, open(out_json, "w"))
        return None

    prior = journal.load(prior_path)
    snap_asof = prior["asof"]
    cur_regime = _current_regime()

    results = []
    for p in prior["picks"]:
        tk = p["ticker"]
        entry, stop = p["entry"], p["stop"]
        t1, t2, t3 = p["t1"], p["t2"], p["t3"]
        bars = _bars_after(px, tk, snap_asof)
        if bars.empty:
            results.append({**p, "outcome": "NO_DATA", "n_days": 0})
            continue

        # Cammina le barre in ordine. Convenzione prudente: se in un giorno il minimo tocca lo
        # stop, la posizione e' chiusa quel giorno (lo stop vince anche se il massimo tocca un
        # target lo stesso giorno). Le barre dopo lo stop non contano (posizione gia' chiusa).
        first_event = None       # primo evento cronologico: ("STOP"|"T1", data)
        stopped = False
        max_high = float("-inf")
        for b in bars.itertuples():
            if b.low <= stop:
                stopped = True
                first_event = first_event or ("STOP", b.date.strftime("%Y-%m-%d"))
                max_high = max(max_high, b.high)   # includi la barra dello stop nell'MFE
                break
            max_high = max(max_high, b.high)
            if first_event is None and t1 is not None and b.high >= t1:
                first_event = ("T1", b.date.strftime("%Y-%m-%d"))
        # target piu' alto toccato PRIMA dello stop (t1<t2<t3): derivato dal max high pre-stop
        if t3 is not None and max_high >= t3:
            max_target = "T3"
        elif t2 is not None and max_high >= t2:
            max_target = "T2"
        elif t1 is not None and max_high >= t1:
            max_target = "T1"
        else:
            max_target = None

        cur_close = float(bars["close"].iloc[-1])
        mae = (float(bars["low"].min()) / entry - 1) * 100
        mfe = (float(bars["high"].max()) / entry - 1) * 100
        drift = (cur_close / entry - 1) * 100

        if stopped and max_target and first_event and first_event[0] == "T1":
            # ha toccato un target e POI e' stato stoppato: parziale bancato + resto stoppato
            outcome = f"{max_target}→STOP"
            pnl_per_share = stop - entry          # conservativo sull'unita' residua
        elif stopped:
            outcome = "STOP HIT"
            pnl_per_share = stop - entry
        elif max_target:
            outcome = f"{max_target} RAGGIUNTO"    # target toccato, posizione ancora aperta
            pnl_per_share = cur_close - entry
        else:
            outcome = "IN CORSO"
            pnl_per_share = cur_close - entry

        reg_then = p.get("market") and prior.get("regime", {}).get(p["market"])
        reg_now = cur_regime.get(p.get("market")) if p.get("market") else None
        regime_changed = bool(reg_then and reg_now and reg_then != reg_now)

        results.append({
            "ticker": tk, "name": p.get("name"), "market": p.get("market"),
            "role": p.get("role"), "score_then": p.get("score"),
            "entry": entry, "stop": stop, "t1": t1, "t2": t2, "t3": t3,
            "cur_close": round(cur_close, 4), "drift_pct": round(drift, 2),
            "mae_pct": round(mae, 2), "mfe_pct": round(mfe, 2),
            "outcome": outcome, "first_event": first_event,
            "pnl_per_share": round(pnl_per_share, 4),
            "regime_then": reg_then, "regime_now": reg_now,
            "regime_changed": regime_changed,
            "n_days": int(len(bars)),
        })

    # aggregati
    n = len(results)
    stops = sum(1 for r in results if r.get("outcome") == "STOP HIT")
    t1plus = sum(1 for r in results if "RAGGIUNTO" in r.get("outcome", ""))
    inprog = sum(1 for r in results if r.get("outcome") == "IN CORSO")
    avg_drift = round(sum(r.get("drift_pct", 0) for r in results) / n, 2) if n else 0
    regime_flips = [r for r in results if r.get("regime_changed")]

    report = {
        "status": "ok", "snapshot_asof": snap_asof, "data_asof": data_asof,
        "n_picks": n, "stops": stops, "targets": t1plus, "in_progress": inprog,
        "avg_drift_pct": avg_drift, "regime_flips": len(regime_flips),
        "current_regime": cur_regime, "results": results,
    }
    json.dump(report, open(out_json, "w"), indent=2, ensure_ascii=False)

    # report leggibile
    L = []
    w = L.append
    w("=" * 92)
    w(f" VERIFICA RACCOMANDAZIONI — snapshot {snap_asof} → prezzi {data_asof}")
    w("=" * 92)
    w(f" Pick verificati: {n} | STOP: {stops} | target raggiunti: {t1plus} | "
      f"in corso: {inprog} | drift medio: {avg_drift:+.2f}%")
    if regime_flips:
        w(f" CAMBIO REGIME su {len(regime_flips)} mercati dei pick: "
          + ", ".join(f"{r['ticker']}({r['market']} {r['regime_then']}→{r['regime_now']})"
                      for r in regime_flips))
    w("-" * 92)
    w(f" {'TICK':9s}{'MKT':4s}{'ENTRY':>9s}{'NOW':>9s}{'DRIFT':>8s}{'MAE':>8s}{'MFE':>8s}  {'ESITO':<14s}{'REGIME':>14s}")
    for r in results:
        if r.get("outcome") == "NO_DATA":
            w(f" {r['ticker']:9s}{'?':4s}{'—':>9s}{'—':>9s}  NO_DATA")
            continue
        rc = f"{r['regime_then']}→{r['regime_now']}" if r["regime_changed"] else (r["regime_now"] or "")
        w(f" {r['ticker']:9s}{r['market'] or '?':4s}{r['entry']:9.3f}{r['cur_close']:9.3f}"
          f"{r['drift_pct']:+8.2f}{r['mae_pct']:+8.2f}{r['mfe_pct']:+8.2f}  {r['outcome']:<14s}{rc:>14s}")
    w("-" * 92)
    w(" LEGENDA: DRIFT=entry→chiusura ora | MAE=peggior escursione | MFE=migliore escursione")
    w(" ESITO path-based: usa max/min GIORNALIERI; stop+target stesso giorno = conta lo STOP (prudente).")
    w(" NB: entry = prezzo pianificato nella scheda (fill reale ~ apertura giorno dopo): assunzione esplicitata.")
    w("=" * 92)
    txt = "\n".join(L) + "\n"
    open(out_txt, "w").write(txt)
    print(txt)
    return report


if __name__ == "__main__":
    verify()
