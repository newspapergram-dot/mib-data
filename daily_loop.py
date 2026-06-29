#!/usr/bin/env python3
"""daily_loop.py — Orchestratore del loop operativo giornaliero (profit-seeker).

Implementa lo scheletro DETERMINISTICO del loop richiesto:

  Giorno N+1, PRIMA di qualunque richiesta:
    Verifica raccomandazioni precedenti -> Confronta coi prezzi reali ->
    [AUDIT: ricerca dura degli errori] -> [trova le cause] -> [correggi] ->
    Genera i nuovi top-5 strong-buy -> Congela nel diario per domani.

Il loop e' SPLIT in due fasi separate da un handoff all'agente, perche' i passi
"ricerca errori / cause / fix" richiedono RAGIONAMENTO (idealmente un sub-agent
indipendente da chi genera i pick) e non vanno automatizzati ciecamente:

  FASE 1  `python3 daily_loop.py verify`
     fetch_data -> regime_filter -> verify_picks
     Produce data/VERIFICATION.txt + data/verification.json.
     >>> HANDOFF: l'agente lancia il sub-agent "auditor" su questi file
         (ricerca dura errori -> cause -> fix mirati). Vedi LOOP.md.

  FASE 2  `python3 daily_loop.py generate`
     score_generator -> portfolio_builder -> self_improve -> charts -> journal snapshot
     Genera i nuovi pick (con eventuali fix gia' applicati) e li CONGELA nel diario.

  `python3 daily_loop.py all`  esegue tutto di seguito (solo se l'audit non chiede fix).

Ogni passo e' un sottoprocesso: stesso comportamento di quando li lanci a mano,
nessun effetto collaterale di import, e un fallimento non corrompe gli altri artefatti.
"""
import subprocess
import sys
import datetime

PY = sys.executable


def _run(label, args):
    print(f"\n{'='*70}\n[loop] {label}\n{'='*70}", flush=True)
    r = subprocess.run([PY, *args])
    if r.returncode != 0:
        print(f"[loop] !! '{label}' uscito con codice {r.returncode}", file=sys.stderr)
    return r.returncode == 0


def phase_verify():
    ok = True
    ok &= _run("FETCH dati freschi", ["fetch_data.py"])
    ok &= _run("REGIME di mercato", ["regime_filter.py"])
    ok &= _run("VERIFICA raccomandazioni precedenti", ["verify_picks.py"])
    print("\n" + "#" * 70)
    print("# HANDOFF AGENTE — leggi data/VERIFICATION.txt e data/verification.json.")
    print("# Lancia il sub-agent 'auditor' (ricerca dura errori -> cause -> fix).")
    print("# Applica i fix, aggiorna FINANCIAL_SKILLS.md + STATE.md, poi: daily_loop.py generate")
    print("#" * 70)
    return ok


def phase_generate():
    ok = True
    ok &= _run("SCORE (tecnico + flow, allineato al backtest)", ["score_generator.py"])
    ok &= _run("PORTAFOGLIO (top strong-buy + schede operative)", ["portfolio_builder.py"])
    ok &= _run("AUTO-AUDIT della raccomandazione", ["self_improve.py"])
    ok &= _run("GRAFICI dei titoli selezionati", ["-c", "from charts import charts_for_portfolio; charts_for_portfolio()"])
    ok &= _run("DIARIO — congela i pick di oggi", ["journal.py", "snapshot"])
    print("\n" + "#" * 70)
    print("# PICK CONGELATI nel diario. Domani 'daily_loop.py verify' li verifichera'.")
    print("#" * 70)
    return ok


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    print(f"[loop] avvio fase '{cmd}' — {datetime.datetime.utcnow().isoformat()}Z")
    if cmd == "verify":
        ok = phase_verify()
    elif cmd == "generate":
        ok = phase_generate()
    elif cmd == "all":
        ok = phase_verify()
        ok &= phase_generate()
    else:
        print(__doc__)
        return
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
