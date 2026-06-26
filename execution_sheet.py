"""execution_sheet.py — Foglio d'ESECUZIONE della sessione operativa, con contabilita' rischio.

Trasforma le schede di data/PORTFOLIO.txt in un piano eseguibile sintetico: per ogni posizione
entry/stop/stop% , azioni, valore, %portafoglio, rischio massimo a stop, e profitto netto ai 3
target. In coda: esposizione totale, RISCHIO TOTALE a stop (la metrica che protegge il capitale),
R/R aggregato e profitto potenziale. E' il deliverable concreto del goal "profitto da ogni sessione".

NB: i target sono lo scenario "se toccati" (ottimistico). L'edge reale e' nella CODA dei vincitori
con mediana per-trade ~0 (backtest): conta la disciplina su molte sessioni, lo STOP non e' negoziabile.
"""
import re
import datetime

CAP = 50000.0   # capitale di riferimento (coerente con portfolio_builder.build default)

# Header di scheda: 'TICK | Score: X | CONFIDENZA: Y'. Si parsa PER-SCHEDA (campi indipendenti)
# cosi' una posizione NON sparisce dal foglio se manca un campo opzionale (es. niente runner T3):
# meglio una riga con un target a 0 che una posizione invisibile -> rischio sotto-riportato.
_HDR = re.compile(r'([A-Z0-9]+\.?[A-Z]{0,3})\s*\|\s*Score:\s*([\d.]+)\s*\|\s*CONFIDENZA:\s*(\w+)')


def _target_eur(seg, n):
    m = re.search(rf'Target {n}:.*?=\s*\+?(-?\d+)EUR', seg)
    return int(m.group(1)) if m else 0


def build_sheet(portfolio_path="data/PORTFOLIO.txt", capital=CAP, out_path="data/EXECUTION_PLAN.txt"):
    txt = open(portfolio_path).read()
    asof = re.search(r'—\s*(\d{4}-\d{2}-\d{2})', txt)
    asof = asof.group(1) if asof else datetime.date.today().isoformat()

    # segmenta per scheda: ogni header delimita un blocco fino all'header successivo
    hdrs = list(_HDR.finditer(txt))
    rows, skipped = [], []
    for i, h in enumerate(hdrs):
        seg = txt[h.end():(hdrs[i + 1].start() if i + 1 < len(hdrs) else len(txt))]
        tk, conf = h.group(1), h.group(3)
        es = re.search(r'Entry:\s*([\d.]+)\s+Stop:\s*([\d.]+)', seg)
        sz = re.search(r'SIZING:\s*(\d+) azioni = (\d+)EUR\s*\(([\d.]+)%', seg)
        rk = re.search(r'Rischio massimo posizione:\s*(\d+)EUR', seg)
        if not (es and sz and rk):
            skipped.append(tk)       # scheda informativa o incompleta -> segnalata, non persa in silenzio
            continue
        rows.append(dict(tk=tk, conf=conf, entry=float(es.group(1)), stop=float(es.group(2)),
                         sh=int(sz.group(1)), val=int(sz.group(2)), pct=float(sz.group(3)),
                         risk=int(rk.group(1)),
                         t1e=_target_eur(seg, 1), t2e=_target_eur(seg, 2), t3e=_target_eur(seg, 3)))

    # nomi azienda per rendere i ticker cercabili
    try:
        from company_names import resolve
        names = resolve([r["tk"] for r in rows], refresh_missing=False)
    except Exception:
        names = {}

    L = []
    w = L.append
    w("=" * 114)
    w(f" FOGLIO D'ESECUZIONE — sessione {asof}  (capitale {capital:.0f} EUR)")
    w("=" * 114)
    if not rows:
        w(" Nessuna posizione operabile in questa sessione (regime risk-off o nessun nome idoneo).")
        w(" Decisione profit-seeker: restare flat e' una posizione. Capitale preservato per la prossima.")
        sheet = "\n".join(L) + "\n"
        if out_path:
            open(out_path, "w").write(sheet)
        print(sheet)
        return rows

    w(f" {'TICK':9s}{'AZIENDA':24s}{'CONF':>6s}{'ENTRY':>9s}{'STOP':>8s}{'STOP%':>7s}{'AZ':>5s}"
      f"{'VAL EUR':>8s}{'%pf':>6s}{'RISK':>6s}{'T1':>6s}{'T2':>6s}{'T3':>6s}")
    tv = tr = t1 = t2 = t3 = 0
    for r in rows:
        sp = (r["stop"] / r["entry"] - 1) * 100
        nm = names.get(r["tk"], "")[:23]
        w(f" {r['tk']:9s}{nm:24s}{r['conf']:>6s}{r['entry']:9.3f}{r['stop']:8.3f}{sp:6.1f}%{r['sh']:5d}"
          f"{r['val']:8d}{r['pct']:5.1f}%{r['risk']:6d}{r['t1e']:6d}{r['t2e']:6d}{r['t3e']:6d}")
        tv += r["val"]; tr += r["risk"]; t1 += r["t1e"]; t2 += r["t2e"]; t3 += r["t3e"]
    w("-" * 114)
    w(f" {'TOTALE':33s}{'':6s}{'':9s}{'':8s}{'':7s}{'':5s}{tv:8d}{tv/capital*100:5.1f}%{tr:6d}{t1:6d}{t2:6d}{t3:6d}")
    w("")
    w(f" Esposizione:        {tv:.0f} EUR ({tv/capital*100:.0f}% del capitale)")
    w(f" RISCHIO TOTALE a stop: {tr:.0f} EUR ({tr/capital*100:.2f}% del capitale) "
      f"<- max perdita se TUTTI gli stop scattano")
    w(f" Profitto potenziale: T1 +{t1} EUR (+{t1/capital*100:.1f}%) | "
      f"T2 +{t2} EUR (+{t2/capital*100:.1f}%) | T3 +{t3} EUR (+{t3/capital*100:.1f}%)")
    if tr:
        w(f" R/R aggregato:      T1 {t1/tr:.2f} | T2 {t2/tr:.2f} | T3 {t3/tr:.2f}")
    flag = "OK (<6%)" if tr / capital < 0.06 else "ALTO (>6%) -> ridurre size"
    w(f" Disciplina rischio: {tr/capital*100:.2f}% del capitale a rischio = {flag}")
    w("")
    w(" ESECUZIONE: ordini limite all'entry; stop OBBLIGATORIO subito dopo il fill (non negoziabile).")
    w(" Scala in uscita ai target (laddering); l'edge sta nella coda T2/T3, la mediana per-trade ~0.")
    if skipped:
        w("")
        w(f" ATTENZIONE: {len(skipped)} schede senza entry/sizing/rischio completi, NON quotate: "
          f"{', '.join(skipped)} (verificare PORTFOLIO.txt).")

    sheet = "\n".join(L) + "\n"
    if out_path:
        open(out_path, "w").write(sheet)
    print(sheet)
    return rows


if __name__ == "__main__":
    build_sheet()
