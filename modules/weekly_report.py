"""
weekly_report.py — Ultimo anello della pipeline mib-data.
Lega score_output.csv ai due moduli (debate.py, trade_proposal.py) e produce
UN report settimanale completo: per ogni candidato, dibattito BULL/BEAR + scheda
operativa (entry/stop/target/sizing/guadagno atteso netto).

Esecuzione: python modules/weekly_report.py
Output:     data/weekly_report.html  +  data/weekly_report.txt

NB: NON tocca lo score validato. Legge solo i CSV gia' prodotti dalla pipeline.
Tutti i parametri operativi (capitale, n. posizioni) sono in cima, modificabili.
"""
import csv, os, datetime

# ---- CONFIG OPERATIVA (modifica qui) ----
CAPITALE = 2000         # capitale di portafoglio in EUR
N_POSIZIONI = 5           # max posizioni aperte a settimana
TOP_N_CANDIDATI = 10       # quanti candidati analizzare (per score decrescente)
DATA_DIR = os.environ.get("MIB_DATA_DIR", "data")

# ---- import moduli locali (stessa cartella modules/) ----
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from debate import build_debate, render_debate
from trade_proposal import propose, render

def _load(fn):
    path = os.path.join(DATA_DIR, fn)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))

def _index(rows, key="ticker"):
    return {r.get(key): r for r in rows if r.get(key)}

def main():
    scores = _load("score_output.csv")
    if not scores:
        print("ERRORE: score_output.csv vuoto o assente. Lancia prima la pipeline.")
        return

    patterns  = _index(_load("patterns.csv"))
    volume    = _index(_load("volume_quality.csv"))
    earnings  = _index(_load("earnings_calendar.csv"))
    insider   = _index(_load("insider_us.csv"))
    cot       = _load("cot.csv")
    macro     = _load("macro_calendar.csv")
    killswitch = any(r.get("killswitch_next_2w","") in ("True","1","true") for r in macro)
    ks_events = [r.get("event") for r in macro if r.get("killswitch_next_2w","") in ("True","1","true")]

    # candidati ordinati per score
    try:
        cands = sorted(scores, key=lambda r: float(r.get("score",0)), reverse=True)[:TOP_N_CANDIDATI]
    except ValueError:
        cands = scores[:TOP_N_CANDIDATI]

    oggi = datetime.date.today().isoformat()
    txt_blocks = []
    html_cards = []
    summary = []  # per la tabella riassuntiva in cima

    header = f"REPORT SETTIMANALE mib-data — {oggi}"
    txt_blocks.append("="*64 + f"\n {header}\n" + "="*64)
    if killswitch:
        txt_blocks.append(f" !! KILL SWITCH MACRO ATTIVO: {', '.join(ks_events)}")
        txt_blocks.append(f"    La regola operativa sospende nuovi swing fino a finestra chiusa.\n")

    for row in cands:
        t = row["ticker"]
        # --- dibattito ---
        d = build_debate(row,
                         patterns=patterns.get(t), volume=volume.get(t),
                         earnings=earnings.get(t), insider=insider.get(t),
                         macro_killswitch=killswitch, cot_rows=cot)
        # --- scheda operativa (solo se NON sotto veto) ---
        veto = d["confidence"] == "N/A (veto)"
        prop = None
        if not veto:
            try:
                price = float(row.get("price",0))
                atr_pct = float(row.get("atr_pct",0))
                atr14 = price * atr_pct/100 if atr_pct>0 else price*0.02
                prop = propose(t, entry=price, atr14=atr14,
                               score=float(row.get("score",0)),
                               capital=CAPITALE, n_positions=N_POSIZIONI)
            except (ValueError, TypeError):
                prop = None

        # --- blocco testo ---
        block = [render_debate(d)]
        if veto:
            block.append("  [scheda operativa OMESSA: candidato sotto veto]")
        elif prop:
            block.append(render(prop))
        txt_blocks.append("\n".join(block))

        # --- riga riassuntiva ---
        summary.append({
            "ticker": t, "score": row.get("score"),
            "verdict": d["verdict"].split(" - ")[0].split(" (")[0],
            "conf": d["confidence"],
            "nbull": len(d["bull"]), "nbear": len(d["bear"]),
            "guadagno": (f"{prop['net_exp_pct']:+.2f}%" if prop else "—"),
        })

        # --- card HTML ---
        bull_li = "".join(f"<li>{b}</li>" for b in d["bull"]) or "<li><em>nessuno</em></li>"
        bear_li = "".join(f"<li>{b}</li>" for b in d["bear"]) or "<li><em>nessuno</em></li>"
        op_html = ""
        if veto:
            op_html = "<p class='veto'>Scheda operativa omessa: candidato sotto veto macro/earnings.</p>"
        elif prop:
            op_html = (f"<div class='op'><b>Entry</b> {prop['entry']:.4f} &nbsp; "
                       f"<b>Stop</b> {prop['stop']:.4f} &nbsp; "
                       f"<b>T1</b> {prop['t1']:.4f} (R/R {prop['rr1']}) &nbsp; "
                       f"<b>T2</b> {prop['t2']:.4f} (R/R {prop['rr2']})<br>"
                       f"<b>Sizing</b> {prop['shares']} az = {prop['pos_value']:.0f}€ "
                       f"({prop['pos_pct']}%){prop['binding']} &nbsp; "
                       f"<b>Rischio</b> {prop['risk_eur']:.0f}€<br>"
                       f"<b>Guadagno atteso netto</b> {prop['net_exp_pct']:+.2f}% = {prop['eur_exp']:+.0f}€</div>")
        html_cards.append(
            f"<div class='card'><h3>{t} <span class='score'>score {row.get('score')}</span> "
            f"<span class='verdict {d['confidence'].split()[0].lower()}'>{d['verdict'].split(' - ')[0]}</span></h3>"
            f"<div class='cols'><div class='bull'><h4>BULL</h4><ul>{bull_li}</ul></div>"
            f"<div class='bear'><h4>BEAR</h4><ul>{bear_li}</ul></div></div>{op_html}</div>"
        )

    # --- scrittura TXT ---
    txt = "\n\n".join(txt_blocks)
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(os.path.join(DATA_DIR,"weekly_report.txt"),"w",encoding="utf-8") as f:
        f.write(txt)

    # --- tabella riassuntiva HTML ---
    rows_html = "".join(
        f"<tr><td>{s['ticker']}</td><td>{s['score']}</td><td>{s['verdict']}</td>"
        f"<td>{s['conf']}</td><td>{s['nbull']}</td><td>{s['nbear']}</td><td>{s['guadagno']}</td></tr>"
        for s in summary)
    ks_banner = (f"<div class='ks'>KILL SWITCH MACRO ATTIVO: {', '.join(ks_events)} — "
                 f"nuovi swing sospesi.</div>" if killswitch else "")
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>{header}</title><style>
body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:960px;margin:24px auto;padding:0 16px;color:#1a1a1a}}
h1{{font-size:22px}} h3{{margin:4px 0;font-size:17px}} h4{{margin:6px 0;font-size:13px;letter-spacing:.5px}}
.ks{{background:#fff3cd;border:1px solid #e0c060;padding:10px 14px;border-radius:8px;margin:12px 0;font-weight:600}}
table{{border-collapse:collapse;width:100%;margin:16px 0;font-size:14px}}
th,td{{border:1px solid #ddd;padding:7px 9px;text-align:left}} th{{background:#f5f5f5}}
.card{{border:1px solid #e2e2e2;border-radius:10px;padding:14px 16px;margin:14px 0;box-shadow:0 1px 3px rgba(0,0,0,.05)}}
.score{{font-size:13px;color:#666;font-weight:400}}
.verdict{{float:right;font-size:12px;padding:3px 10px;border-radius:12px;font-weight:600}}
.verdict.alta{{background:#d4edda;color:#155724}} .verdict.media{{background:#fff3cd;color:#856404}}
.verdict.bassa,.verdict.n{{background:#f8d7da;color:#721c24}}
.cols{{display:flex;gap:16px;margin-top:8px}} .cols>div{{flex:1}}
.bull ul{{color:#155724}} .bear ul{{color:#721c24}} ul{{margin:4px 0;padding-left:18px;font-size:13px}}
.op{{background:#f0f7ff;border:1px solid #cfe2ff;border-radius:8px;padding:10px 12px;margin-top:10px;font-size:13px;line-height:1.7}}
.veto{{color:#721c24;font-style:italic;margin-top:8px}}
</style></head><body>
<h1>{header}</h1>{ks_banner}
<table><tr><th>Ticker</th><th>Score</th><th>Verdetto</th><th>Conf.</th><th>#Bull</th><th>#Bear</th><th>Guad. atteso</th></tr>{rows_html}</table>
{''.join(html_cards)}
<p style="font-size:12px;color:#888;margin-top:24px">Generato da weekly_report.py — edge calibrato su regime bull (gen-mag 2026). Sizing prudenziale. Non e' consulenza finanziaria.</p>
</body></html>"""
    with open(os.path.join(DATA_DIR,"weekly_report.html"),"w",encoding="utf-8") as f:
        f.write(html)
    print(f"Report generato: {DATA_DIR}/weekly_report.html e weekly_report.txt ({len(cands)} candidati)")

if __name__ == "__main__":
    main()
