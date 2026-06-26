"""self_improve.py — Ciclo di AUTOMIGLIORAMENTO post-raccomandazione (goal profit-seeker).

Dopo ogni consiglio operativo (PORTFOLIO.txt / EXECUTION_PLAN.txt) esegue un auto-audit:
  1) controlli OGGETTIVI sulla raccomandazione (freschezza dati, disciplina rischio,
     coerenza regime, concentrazione, qualita' dei nomi, assunzioni non blindate);
  2) per OGNI criticita' propone l'azione di miglioramento e LA SKILL che aiuta a eseguirla;
  3) sceglie la PROSSIMA mossa di miglioramento a piu' alto impatto.

Scrive data/IMPROVEMENT_LOG.txt (storico append) + ritorna le criticita'. Idea: ogni sessione
non solo genera profitto atteso, ma RENDE IL MODELLO MIGLIORE della sessione precedente.

NB: i controlli sono reali e azionabili, non decorativi. Una criticita' a impatto alto va
chiusa prima della sessione successiva (entra in STATE.md watch-list).
"""
import os
import re
import csv
import datetime

# Mappa criticita' -> skill Claude Code che aiuta a risolverla (nota #3 dell'utente).
SKILL_FOR = {
    "code":     "/code-review  (bug di correttezza nel modulo coinvolto)",
    "simplify": "/simplify     (codice duplicato/complesso da ripulire)",
    "verify":   "/verify       (eseguire e osservare che il comportamento sia reale)",
    "security": "/security-review (chiavi/segreti/credenziali esposte)",
    "stats":    "metodo statistico (walk-forward/DSR/bootstrap: vedi backtest_v3)",
    "data":     "controllo fonte dati (freschezza/provenienza: vedi Lezione #2)",
}


def _read(path):
    return open(path).read() if os.path.exists(path) else ""


def audit(portfolio="data/PORTFOLIO.txt", regime="data/regime_filter.csv",
          last_update="data/last_update.txt", capital=50000.0):
    today = datetime.date.today()
    findings = []   # (severita', area, criticita', azione, skill_key)

    # 1) FRESCHEZZA DATI ----------------------------------------------------
    lu = _read(last_update).strip()
    m = re.search(r"(\d{4}-\d{2}-\d{2})", lu)
    if m:
        age = (today - datetime.date.fromisoformat(m.group(1))).days
        if age >= 2:
            findings.append(("ALTA", "dati", f"dataset vecchio di {age}g ({m.group(1)})",
                             "rieseguire fetch_data prima di operare", "data"))
    else:
        findings.append(("MEDIA", "dati", "data ultimo aggiornamento non leggibile",
                         "verificare data/last_update.txt", "data"))

    txt = _read(portfolio)
    if not txt:
        findings.append(("ALTA", "output", "PORTFOLIO.txt assente",
                         "eseguire portfolio_builder", "verify"))
        return _emit(findings, today)

    # 2) DISCIPLINA RISCHIO -------------------------------------------------
    risks = [int(x) for x in re.findall(r"Rischio massimo posizione:\s*(\d+)EUR", txt)]
    tot_risk = sum(risks)
    if tot_risk:
        rpct = tot_risk / capital * 100
        if rpct > 6:
            findings.append(("ALTA", "rischio", f"rischio totale a stop {rpct:.1f}% > 6%",
                             "ridurre size o numero posizioni", "code"))
    # singola posizione > 10% capitale?
    vals = [int(v) for v in re.findall(r"SIZING:\s*\d+ azioni = (\d+)EUR", txt)]
    if vals and max(vals) / capital > 0.105:
        findings.append(("MEDIA", "rischio", f"posizione max {max(vals)/capital*100:.0f}% > cap 10%",
                         "verificare pos_cap in trade_proposal", "code"))

    # 3) CONCENTRAZIONE MERCATO E CONTINENTE -------------------------------
    mkts = re.findall(r"FOREGROUND:.*\|\s*(IT|FR|US)\s*$", txt, re.M)
    if mkts:
        from collections import Counter
        c = Counter(mkts)
        top_mkt, n = c.most_common(1)[0]
        if n / len(mkts) > 0.8:
            findings.append(("MEDIA", "diversif.", f"concentrazione {top_mkt} {n}/{len(mkts)} (>80%)",
                             "il regime di un solo mercato domina: monitorare correlazione", "stats"))
        # concentrazione di CONTINENTE: IT+FR sono entrambi EU -> un book 100% EU resta
        # una scommessa correlata su un'unica regione anche se IT e FR sono "due mercati".
        cont = Counter("EU" if m in ("IT", "FR") else "US" for m in mkts)
        top_c, nc = cont.most_common(1)[0]
        if nc / len(mkts) > 0.85 and len(set(mkts)) > 1:
            # se il piano DICHIARA gia' la concentrazione (con hedge di area opzionale) e' un
            # rischio gestito -> NOTA; altrimenti e' una criticita' operativa -> MEDIA.
            acknowledged = "CONCENTRAZIONE DI AREA" in txt
            sev = "NOTA" if acknowledged else "MEDIA"
            tail = " (dichiarata nel piano, hedge di area disponibile)" if acknowledged else ""
            findings.append((sev, "diversif.", f"book {nc}/{len(mkts)} concentrato su {top_c}{tail}",
                             "regione correlata: e' per regime (es. US in PULLBACK); monitorare il "
                             "rischio macro comune; hedge di area come assicurazione opzionale", "stats"))

    # 3b) CONCENTRAZIONE SETTORIALE -----------------------------------------
    picks_list = re.findall(r"^\s*([A-Z0-9]+\.?[A-Z]{0,3})\s*\|\s*Score:", txt, re.M)
    if len(picks_list) >= 6:
        _SECTOR = {
            "SRG.MI": "Utility", "TRN.MI": "Utility", "ENEL.MI": "Utility",
            "ENGI.PA": "Utility", "VIE.PA": "Utility", "A2A.MI": "Utility",
            "ISP.MI": "Banca", "BMPS.MI": "Banca", "BAMI.MI": "Banca",
            "UCG.MI": "Banca", "FBK.MI": "Banca", "GLE.PA": "Banca",
            "BNP.PA": "Banca", "AZM.MI": "Finanza",
            "TEN.MI": "Oil&Gas", "SPM.MI": "Oil&Gas", "ENI.MI": "Oil&Gas",
            "STMMI.MI": "Tech", "STMPA.PA": "Tech",
            "CA.PA": "Retail", "PST.MI": "Servizi", "REC.MI": "Pharma",
            "EDEN.PA": "Servizi", "AI.PA": "Industriale", "LDO.MI": "Difesa",
        }
        from collections import Counter
        sec_c = Counter(_SECTOR.get(tk, "Altro") for tk in picks_list)
        top_sec, ns = sec_c.most_common(1)[0]
        if ns / len(picks_list) > 0.35:
            findings.append(("MEDIA", "diversif.",
                             f"concentrazione settoriale: {top_sec} {ns}/{len(picks_list)} (>{35}%)",
                             "ridurre esposizione al settore o monitorare correlazione intra-settore",
                             "stats"))

    # 4) QUALITA' DEI NOMI (confidenza/distribuzione) ----------------------
    n_bassa = len(re.findall(r"conf BASSA", txt))
    n_tot = len(re.findall(r"FOREGROUND:", txt))
    if n_tot and n_bassa / n_tot > 0.4:
        from modules.trade_proposal import ILLIQUID
        cards = re.findall(r"^\s*([A-Z0-9]+\.?[A-Z]{0,3})\s*\|.*CONFIDENZA:\s*BASSA", txt, re.M)
        n_illiq = sum(1 for tk in cards if tk in ILLIQUID)
        n_score_bassa = n_bassa - n_illiq
        if n_score_bassa > 0:
            findings.append(("MEDIA", "selezione",
                             f"{n_bassa}/{n_tot} nomi conf BASSA ({n_illiq} illiquidi, {n_score_bassa} per score)",
                             "rivedere normalizzazione score_technical o soglie confidenza", "code"))
        else:
            findings.append(("NOTA", "selezione",
                             f"{n_bassa}/{n_tot} nomi conf BASSA (tutti illiquidi: costi alti -> riduzione size gia' attiva)",
                             "strutturale: la selezione premia l'accumulazione su titoli meno liquidi", "data"))
    if re.search(r"DISTRIBUZIONE", txt):
        findings.append(("BASSA", "selezione", "almeno un nome in distribuzione tra i selezionati",
                         "verificare la soglia smart-money (sm>=-0.15)", "code"))

    # 5) ASSUNZIONI NON BLINDATE (onesta' statistica) ----------------------
    # Consolidato su ciclo completo (robustness_consolidate, Run #20): modello operativo
    # Sharpe 1.0 / MaxDD -13.8% / PSR 0.98 (edge REALE) ma DSR 0.86-0.92 (<0.95, non blindato).
    findings.append(("NOTA", "robustezza", "edge reale (PSR 0.98) ma DSR<0.95 sul ciclo completo",
                     "size moderata: l'edge vive nel gate di regime+stop, non nel Sharpe; mai leverage",
                     "stats"))

    # 6) COPERTURA GRAFICI -------------------------------------------------
    picks = set(re.findall(r"^\s*([A-Z0-9]+\.?[A-Z]{0,3})\s*\|\s*Score:", txt, re.M))
    if picks:
        missing = [t for t in picks if not os.path.exists(f"charts/{t.replace('.', '_')}.png")]
        if missing:
            findings.append(("BASSA", "analisi", f"grafici mancanti per {len(missing)} nomi",
                             "eseguire charts.charts_for_portfolio()", "verify"))

    return _emit(findings, today)


def _emit(findings, today):
    order = {"ALTA": 0, "MEDIA": 1, "BASSA": 2, "NOTA": 3}
    findings.sort(key=lambda f: order.get(f[0], 9))

    L = ["=" * 84, f" AUTO-AUDIT MODELLO — {today.isoformat()} (ciclo di automiglioramento)", "=" * 84]
    if not findings:
        L.append(" Nessuna criticita': raccomandazione robusta su tutti i controlli.")
    for sev, area, crit, action, skill in findings:
        L.append(f" [{sev:5s}] {area:10s} {crit}")
        L.append(f"          -> azione: {action}")
        L.append(f"          -> skill : {SKILL_FOR.get(skill, skill)}")

    # PROSSIMA MOSSA a piu' alto impatto = prima criticita' non-NOTA
    actionable = [f for f in findings if f[0] != "NOTA"]
    L.append("-" * 84)
    if actionable:
        nxt = actionable[0]
        L.append(f" PROSSIMA MOSSA (impatto piu' alto): [{nxt[0]}] {nxt[2]} -> {nxt[3]}")
        L.append(f"   skill consigliata: {SKILL_FOR.get(nxt[4], nxt[4])}")
    else:
        L.append(" PROSSIMA MOSSA: consolidare robustezza (DSR>0.95) — nessuna criticita' operativa.")
    L.append("=" * 84)
    report = "\n".join(L)
    print(report)

    # append storico
    with open("data/IMPROVEMENT_LOG.txt", "a") as f:
        f.write(report + "\n\n")
    return findings


if __name__ == "__main__":
    audit()
