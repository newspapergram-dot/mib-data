#!/usr/bin/env python3
"""journal.py — Diario datato delle raccomandazioni operative (memory spine del loop).

PORTFOLIO.txt viene SOVRASCRITTO a ogni run: senza un archivio datato non e' possibile
verificare le raccomandazioni del giorno prima (lo abbiamo dovuto ricostruire a mano).
Questo modulo congela ogni piano operativo in data/journal/YYYY-MM-DD.json, cosi' il passo
"verifica raccomandazioni precedenti" del loop diventa automatico e onesto.

Cattura per ogni pick: ticker, nome, score, confidenza, ruolo, mercato, regime del mercato,
entry/stop/T1/T2/T3 ASSOLUTI (gli stessi numeri della scheda operativa che vede l'utente).

Uso:
  python3 journal.py snapshot              # congela data/PORTFOLIO.txt -> data/journal/<asof>.json
  python3 journal.py list                  # elenca gli snapshot esistenti
  python3 journal.py show <YYYY-MM-DD>      # stampa uno snapshot
"""
import os
import re
import json
import sys
import glob
import datetime

JOURNAL_DIR = "data/journal"


def _parse_portfolio(txt):
    """Estrae asof, regime, capitale e i pick (con livelli assoluti) da PORTFOLIO.txt."""
    asof = None
    m = re.search(r"PORTAFOGLIO DIVERSIFICATO\s*[—-]\s*(\d{4}-\d{2}-\d{2})", txt)
    if m:
        asof = m.group(1)
    capital = None
    m = re.search(r"capitale\s+(\d+)\s*EUR", txt)
    if m:
        capital = float(m.group(1))
    regime = {}
    m = re.search(r"Regime:\s*(.+)", txt)
    if m:
        for tok in re.findall(r"(IT|FR|US)=([A-Z_]+)", m.group(1)):
            regime[tok[0]] = tok[1]

    picks = []
    # Le SCHEDE OPERATIVE contengono i livelli assoluti; il blocco unicorni e' separato.
    body = txt.split("SCHEDE OPERATIVE", 1)
    cards_txt = body[1] if len(body) > 1 else txt
    lines = cards_txt.splitlines()
    cur = None
    for i, line in enumerate(lines):
        hm = re.match(r"^\s*([A-Z0-9.]+)\s*\|\s*Score:\s*([-\d.]+)\s*\|\s*CONFIDENZA:\s*(\w+)", line)
        if hm:
            if cur:
                picks.append(cur)
            cur = {"ticker": hm.group(1), "score": float(hm.group(2)),
                   "confidence": hm.group(3), "name": None, "role": None,
                   "market": None, "entry": None, "stop": None,
                   "t1": None, "t2": None, "t3": None}
            continue
        if cur is None:
            continue
        em = re.search(r"Entry:\s*([\d.]+)\s+Stop:\s*([\d.]+)", line)
        if em:
            cur["entry"] = float(em.group(1))
            cur["stop"] = float(em.group(2))
        for idx, key in enumerate(["t1", "t2", "t3"], 1):
            tm = re.match(rf"^\s*Target {idx}:\s*([\d.]+)", line)
            if tm:
                cur[key] = float(tm.group(1))
        fm = re.search(r"FOREGROUND:.*\|\s*(CORE|SAT)\s*\|.*\|\s*(IT|FR|US)\s*$", line)
        if fm:
            cur["role"] = fm.group(1)
            cur["market"] = fm.group(2)
            # il nome azienda e' la riga subito prima di FOREGROUND
            if i > 0:
                nm = lines[i - 1].strip()
                if nm and not nm.startswith("=") and "FOREGROUND" not in nm:
                    cur["name"] = nm
    if cur:
        picks.append(cur)
    # tieni solo i pick con livelli completi (le schede operative vere)
    picks = [p for p in picks if p["entry"] is not None and p["stop"] is not None]
    return {"asof": asof, "capital": capital, "regime": regime, "picks": picks}


def snapshot(portfolio_path="data/PORTFOLIO.txt", out_dir=JOURNAL_DIR):
    if not os.path.exists(portfolio_path):
        print(f"[journal] {portfolio_path} assente — niente da congelare", file=sys.stderr)
        return None
    txt = open(portfolio_path).read()
    snap = _parse_portfolio(txt)
    asof = snap["asof"] or datetime.date.today().isoformat()
    snap["asof"] = asof
    # data_asof = data della barra di prezzo da cui parte il piano (di norma == asof). La verifica
    # deriva da qui le barre dell'holding e il fill realistico, restando robusta a uno snapshot
    # marcato con una data ma prezzato su una barra precedente (vedi Lezione #20).
    snap["data_asof"] = asof
    snap["captured_at"] = datetime.datetime.utcnow().isoformat() + "Z"
    os.makedirs(out_dir, exist_ok=True)
    # Identita' dello snapshot = DATA DI PREZZO (data_asof), non il timbro nominale: un piano
    # prezzato su una barra precedente non deve collidere con un build sulla barra corrente.
    out = os.path.join(out_dir, f"{snap['data_asof']}.json")
    with open(out, "w") as f:
        json.dump(snap, f, indent=2, ensure_ascii=False)
    print(f"[journal] congelati {len(snap['picks'])} pick (asof {asof}) -> {out}")
    return out


def list_snapshots(out_dir=JOURNAL_DIR):
    return sorted(glob.glob(os.path.join(out_dir, "*.json")))


def load(path):
    with open(path) as f:
        return json.load(f)


def latest_before(asof, out_dir=JOURNAL_DIR):
    """Snapshot piu' recente con data STRETTAMENTE precedente ad asof (per la verifica)."""
    snaps = list_snapshots(out_dir)
    prior = [s for s in snaps if os.path.basename(s)[:10] < asof]
    return prior[-1] if prior else None


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "snapshot"
    if cmd == "snapshot":
        snapshot()
    elif cmd == "list":
        for s in list_snapshots():
            d = load(s)
            print(f"{os.path.basename(s)[:10]}  {len(d['picks'])} pick  "
                  f"regime {d.get('regime')}")
    elif cmd == "show":
        day = sys.argv[2]
        path = os.path.join(JOURNAL_DIR, f"{day}.json")
        print(json.dumps(load(path), indent=2, ensure_ascii=False))
    else:
        print(__doc__)
