"""orchestrator.py — Comitato multi-agente nativo (Anthropic Messages API).

Ogni agente e' invocato con una chiamata `messages.create()` ISOLATA e stateless:
niente cronologia condivisa, niente prompt-chaining implicito. `invoke_isolated_agent`
costruisce SEMPRE `messages=[<un solo turno utente>]` — un agente non vede mai i turni
di conversazione di un altro agente.

La comunicazione tra agenti passa SOLO attraverso payload JSON strutturati e validati
contro uno schema (`agents/output_schemas.py`), mai testo libero/persuasivo. Questo e'
il meccanismo concreto che garantisce comunicazione "unilaterale" (a valle riceve la
CONCLUSIONE di monte, non il suo ragionamento) senza contaminazione di bias tra agenti:
- il Finance Guy non vede sentiment/fondamentali del titolo (giudizio macro indipendente);
- il Company Analyst non vede il giudizio macro ne' quello di rischio;
- se uno stadio boccia, gli stadi successivi non vengono nemmeno invocati (short-circuit):
  un agente a valle non puo' mai "convincere" a ribaltare un rigetto di monte.

Pipeline: Researcher -> Technical Analyst -> Company Analyst -> Finance Guy -> Auditor -> CEO.

Regole immutabili: l'Auditor riceve il codice REALE di `portfolio_backtester.py` letto da
disco (non riassunto, non trascritto a memoria). Due regole non negoziabili (Run #40 /
LOOP.md) sono inoltre applicate in CODICE, non affidate al giudizio del modello:
  1) lo stop-loss finale non supera mai STOP_LOSS_FLOOR, qualunque cosa proponga l'LLM;
  2) regime_gate == "TREND_DOWN" forza sempre approved=False.

Il TRADE PLAN operativo (prezzo di ingresso, stop-loss e take-profit T1/T2/T3) NON viene mai
chiesto all'LLM: e' calcolato in CODICE da `modules/trade_proposal.py` (motore gia'
validato/backtestato su ATR + risk/reward), stesso principio dei due backstop sopra — i
livelli di prezzo sono un fatto quantitativo, non un giudizio da delegare al modello.

Uso (fallback CLI, non e' lo slash-command primario — vedi AGENTS.md):
    export ANTHROPIC_API_KEY=...
    python3 orchestrator.py data/committee_input.json
"""
import os
import re
import sys
import json
import datetime
from pathlib import Path

from jsonschema import validate, ValidationError

from agents.output_schemas import (
    RESEARCHER_SCHEMA, TECHNICAL_ANALYST_SCHEMA, COMPANY_ANALYST_SCHEMA,
    FINANCE_GUY_SCHEMA, AUDITOR_SCHEMA, CEO_SCHEMA,
)
from modules.trade_proposal import propose as propose_trade_plan

REPO_ROOT = Path(__file__).resolve().parent
STOP_LOSS_FLOOR = 0.15  # Run #40: qualunque proposta piu' larga viene clampata qui
MODEL = os.environ.get("ORCHESTRATOR_MODEL", "claude-sonnet-5")
# Capitale nozionale per il trade plan (entry/stop/T1-T2-T3): stesso default di
# portfolio_builder.py::build(). Non e' il capitale reale dell'utente, serve solo a
# derivare i LIVELLI DI PREZZO (indipendenti dal capitale) e un sizing di riferimento.
COMMITTEE_CAPITAL = float(os.environ.get("COMMITTEE_CAPITAL", "50000"))


def _client():
    from anthropic import Anthropic
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY assente: impostala nell'ambiente prima di lanciare il Comitato.")
    return Anthropic(api_key=key)


def _read(relpath):
    path = REPO_ROOT / relpath
    if not path.exists():
        raise FileNotFoundError(f"File immutabile non trovato nel repo: {relpath}")
    return path.read_text()


def _prompt(name):
    return _read(f"agents/prompts/{name}.md")


def load_input_schema():
    return json.loads(_read("data_schema.json"))


def validate_candidate(candidate, schema=None):
    schema = schema or load_input_schema()
    try:
        validate(instance=candidate, schema=schema)
        return True, None
    except ValidationError as e:
        return False, e.message


JSON_ONLY_INSTRUCTION = "Rispondi SOLO con un oggetto JSON valido, senza testo fuori dal JSON."


def _strip_markdown_fence(raw):
    """Rimuove un eventuale fence markdown (```json ... ``` oppure ``` ... ```)
    attorno alla risposta. Run reale del 1/7/2026: il Company Analyst ha risposto
    con '```json\\n{...}\\n```' nonostante l'istruzione di rispondere solo JSON."""
    stripped = raw.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z]*\n?", "", stripped)
        stripped = re.sub(r"\n?```$", "", stripped)
    return stripped.strip()


def invoke_isolated_agent(client, system_prompt, payload, output_schema,
                           max_tokens=1500, model=None):
    """Chiamata STATELESS a un singolo agente.

    `messages` ha SEMPRE un solo turno utente costruito dal `payload` esplicito:
    nessuna cronologia accumulata, nessun contesto ereditato da altre chiamate.
    L'output DEVE essere un JSON che rispetta `output_schema` — se il modello
    risponde con testo libero o campi extra, la chiamata fallisce esplicitamente
    invece di lasciar passare un ragionamento non strutturato allo stadio successivo.

    `system_prompt` puo' essere una stringa (caso comune) oppure una lista di blocchi
    di contenuto gia' pronti per l'API (usata dall'Auditor per marcare con
    `cache_control` il codice immutabile di `portfolio_backtester.py`, cosi' che le
    chiamate ripetute nella stessa nottata lo paghino una sola volta).
    """
    if isinstance(system_prompt, list):
        system = system_prompt + [{"type": "text", "text": JSON_ONLY_INSTRUCTION}]
    else:
        system = system_prompt + "\n\n" + JSON_ONLY_INSTRUCTION
    resp = client.messages.create(
        model=model or MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
    )
    # Alcune risposte includono blocchi di thinking prima del testo: si cerca il
    # primo blocco testuale invece di assumere che sia content[0] (Run reale del
    # 1/7/2026: 'ThinkingBlock' object has no attribute 'text').
    text_blocks = [b.text for b in resp.content if getattr(b, "type", "text") == "text"]
    if not text_blocks:
        raise ValueError(f"Risposta agente priva di blocchi testuali: {resp.content!r}")
    raw = _strip_markdown_fence(text_blocks[0])
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Risposta agente non e' JSON valido: {raw[:200]!r}") from e
    validate(instance=data, schema=output_schema)
    return data


class NativeOrchestrator:
    """Orchestratore del Comitato. `client` e' iniettabile (test con un client finto
    senza mai toccare la rete o consumare crediti API)."""

    def __init__(self, client=None):
        self._client = client
        self.schema = load_input_schema()

    def _get_client(self):
        if self._client is None:
            self._client = _client()
        return self._client

    def run_committee(self, candidate):
        ok, err = validate_candidate(candidate, self.schema)
        if not ok:
            return {
                "ticker": candidate.get("ticker", "?"),
                "candidate": candidate,
                "stages": {},
                "final": {"ticker": candidate.get("ticker", "?"), "action": "SKIP",
                          "rationale": f"[schema_validation] dato in ingresso non valido: {err}",
                          "final_stop_loss_pct": None},
            }

        client = self._get_client()
        ticker = candidate["ticker"]
        # Il candidato completo viene conservato nel trail SOLO per il rendering del
        # report (fondamentali/tecnici/candlestick oggettivi) — non e' mai ripassato
        # a un agente oltre a quanto gia' esplicitamente previsto stadio per stadio.
        trail = {"ticker": ticker, "candidate": candidate, "stages": {}}

        # 1) RESEARCHER — vede solo il candidato immutabile. Primo della catena.
        researcher_out = invoke_isolated_agent(
            client, _prompt("researcher"), {"candidate": candidate}, RESEARCHER_SCHEMA)
        trail["stages"]["researcher"] = researcher_out

        # 2) TECHNICAL ANALYST — vede SOLO ticker/mercato + i dati tecnici/candlestick
        #    deterministici (RSI/ADX/ATR/SMA/pattern). Non vede fondamentali, sentiment
        #    o altri verdetti: il giudizio tecnico resta indipendente dalla narrativa
        #    societaria (isolamento deliberato, stesso principio del Finance Guy).
        technical_out = invoke_isolated_agent(
            client, _prompt("technical_analyst"),
            {"candidate": {"ticker": ticker, "market": candidate.get("market")},
             "technical": candidate.get("technical", {}),
             "candlestick": candidate.get("candlestick", {})},
            TECHNICAL_ANALYST_SCHEMA)
        trail["stages"]["technical_analyst"] = technical_out
        if technical_out["verdict"] == "unfavorable":
            return self._reject(ticker, "technical_analyst", technical_out["reasons"], trail)

        # 3) COMPANY ANALYST — vede candidato + SOLO l'output strutturato del Researcher.
        analyst_out = invoke_isolated_agent(
            client, _prompt("company_analyst"),
            {"candidate": candidate, "researcher": researcher_out},
            COMPANY_ANALYST_SCHEMA)
        trail["stages"]["company_analyst"] = analyst_out
        if analyst_out["verdict"] == "reject":
            return self._reject(ticker, "company_analyst", analyst_out["reasons"], trail)

        # 4) FINANCE GUY — vede SOLO ticker/mercato/regime + le linee guida macro. Non
        #    vede researcher/company_analyst: il giudizio macro resta indipendente dalla
        #    narrativa sul singolo titolo (isolamento deliberato).
        finance_out = invoke_isolated_agent(
            client, _prompt("finance_guy"),
            {"candidate": {"ticker": ticker, "market": candidate.get("market"),
                           "regime_gate": candidate["regime_gate"]},
             "macro_guidelines": _read("macro_guidelines.md")},
            FINANCE_GUY_SCHEMA)
        trail["stages"]["finance_guy"] = finance_out
        if not finance_out["sector_rotation_favorable"]:
            return self._reject(ticker, "finance_guy", [finance_out["notes"]], trail)

        # 5) AUDITOR — vede candidato + i verdetti strutturati + il codice REALE delle
        #    regole (letto da disco, non a memoria). Il codice e' identico per ogni
        #    candidato della nottata: e' marcato cache_control cosi' che solo la prima
        #    chiamata Auditor della run lo paghi per intero (le successive leggono dalla
        #    cache a frazione del prezzo, finche' resta entro la finestra TTL).
        auditor_system = [
            {"type": "text", "text": _prompt("auditor")},
            {"type": "text",
             "text": f"--- portfolio_backtester.py (codice reale) ---\n{_read('portfolio_backtester.py')}",
             "cache_control": {"type": "ephemeral"}},
        ]
        auditor_out = invoke_isolated_agent(
            client, auditor_system,
            {"candidate": candidate, "researcher": researcher_out,
             "company_analyst": analyst_out, "finance_guy": finance_out},
            AUDITOR_SCHEMA)
        # BACKSTOP DETERMINISTICO #1: lo SL non scende mai sotto il floor di Run #40,
        # qualunque cosa proponga il modello.
        auditor_out["stop_loss_pct"] = min(auditor_out["stop_loss_pct"], STOP_LOSS_FLOOR)
        # BACKSTOP DETERMINISTICO #2: regime TREND_DOWN veta sempre, a prescindere
        # dal giudizio del modello (LOOP.md: il gate di regime e' la fonte dell'edge).
        if candidate["regime_gate"] == "TREND_DOWN" and auditor_out["approved"]:
            auditor_out["approved"] = False
            auditor_out["risk_notes"].append(
                "[BACKSTOP] regime_gate=TREND_DOWN -> veto automatico (LOOP.md)")
        trail["stages"]["auditor"] = auditor_out
        if not auditor_out["approved"]:
            return self._reject(ticker, "auditor", auditor_out["risk_notes"], trail)

        # 6) CEO — vede SOLO i verdetti strutturati finali, mai il ragionamento grezzo
        #    (che non esiste: ogni stadio a monte ha gia' risposto solo in JSON vincolato).
        ceo_out = invoke_isolated_agent(
            client, _prompt("ceo"),
            {"candidate": candidate, "researcher": researcher_out,
             "technical_analyst": technical_out, "company_analyst": analyst_out,
             "finance_guy": finance_out, "auditor": auditor_out},
            CEO_SCHEMA)
        if ceo_out.get("final_stop_loss_pct") is not None:
            # Il CEO puo' solo restringere lo stop, mai allargarlo oltre l'Auditor.
            ceo_out["final_stop_loss_pct"] = min(ceo_out["final_stop_loss_pct"],
                                                  auditor_out["stop_loss_pct"])
        trail["stages"]["ceo"] = ceo_out
        trail["final"] = ceo_out

        # TRADE PLAN — entry/stop/T1-T2-T3 SOLO in codice (modules/trade_proposal.py),
        # mai chiesto all'LLM: sono livelli quantitativi, non un giudizio (vedi docstring
        # di modulo). Calcolato solo per un BUY finale, sui dati tecnici reali del
        # candidato (mai fabbricati: se mancano, il Data Parser ha gia' escluso il ticker).
        if ceo_out["action"] == "BUY":
            trail["trade_plan"] = self._trade_plan(candidate)
        return trail

    @staticmethod
    def _trade_plan(candidate):
        atr_pct = candidate.get("technical", {}).get("atr_pct")
        entry = candidate["entry_price"]
        if atr_pct is None:
            return None
        atr_abs = entry * atr_pct / 100.0
        plan = propose_trade_plan(candidate["ticker"], entry=entry, atr14=atr_abs,
                                   score=candidate["momentum_score"], capital=COMMITTEE_CAPITAL)
        # BACKSTOP DETERMINISTICO #3: lo stop del trade plan non supera mai STOP_LOSS_FLOOR,
        # stesso tetto imposto all'Auditor (Run #40) — qui applicato al PREZZO, non al %.
        floor_price = entry * (1 - STOP_LOSS_FLOOR)
        plan["stop"] = round(max(plan["stop"], floor_price), 4)
        plan["stop_pct"] = round((entry - plan["stop"]) / entry, 4)
        return plan

    @staticmethod
    def _reject(ticker, stage, reasons, trail):
        trail["final"] = {
            "ticker": ticker, "action": "SKIP",
            "rationale": f"[{stage}] " + "; ".join(reasons),
            "final_stop_loss_pct": None,
        }
        return trail


def _fmt(v, nd=2):
    return "n/d" if v is None else f"{v:.{nd}f}"


def render_report(results, asof=None, unicorn_funnel=None):
    asof = asof or datetime.date.today().isoformat()
    lines = [f"COMITATO MULTI-AGENTE — Report operativo {asof}", "=" * 70]

    for r in results:
        candidate = r.get("candidate", {}) or {}
        stages = r.get("stages", {}) or {}
        final = r["final"]
        is_unicorn = candidate.get("universe") == "unicorn"
        tag = " [UNICORNO]" if is_unicorn else ""
        lines.append(f"\n{r['ticker']}{tag}: {final['action']}")

        entry = candidate.get("entry_price")
        if entry is not None:
            lines.append(f"  Trigger d'ingresso: {entry:.2f} {candidate.get('market', '')} "
                          f"(regime {candidate.get('regime_gate', 'n/d')})")

        fundamentals = candidate.get("fundamentals")
        analyst = stages.get("company_analyst")
        if fundamentals or analyst:
            lines.append("  Analisi fondamentale:")
            if fundamentals:
                lines.append(
                    f"    D/E {_fmt(fundamentals.get('debt_to_equity'))} | "
                    f"EBITDA margin {_fmt(fundamentals.get('ebitda_margin'), 3)} | "
                    f"EPS growth QoQ {_fmt(fundamentals.get('eps_growth_q_on_q'), 3)} | "
                    f"FCF {_fmt(fundamentals.get('free_cash_flow'), 0)}")
            if analyst:
                lines.append(f"    Verdetto Company Analyst: {analyst['verdict']} — "
                              + "; ".join(analyst["reasons"]))

        technical = candidate.get("technical")
        tech_agent = stages.get("technical_analyst")
        if technical or tech_agent:
            lines.append("  Analisi tecnica:")
            if technical:
                lines.append(
                    f"    RSI {_fmt(technical.get('rsi'), 1)} | ADX {_fmt(technical.get('adx'), 1)} | "
                    f"ATR% {_fmt(technical.get('atr_pct'), 2)} | mom6m {_fmt(technical.get('mom6m'), 3)} | "
                    f"SMA20/50/200 {_fmt(technical.get('sma20'))}/{_fmt(technical.get('sma50'))}/"
                    f"{_fmt(technical.get('sma200'))}")
            if tech_agent:
                lines.append(f"    Verdetto Technical Analyst: {tech_agent['verdict']} — "
                              f"{tech_agent['setup_read']}")

        candlestick = candidate.get("candlestick")
        if candlestick or tech_agent:
            lines.append("  Analisi candlestick:")
            if candlestick:
                lines.append(
                    f"    trend={candlestick.get('trend')} struttura={candlestick.get('structure')} "
                    f"breakout={candlestick.get('breakout')} divergenza={candlestick.get('rsi_divergence')} "
                    f"bollinger={candlestick.get('bollinger')}")
            if tech_agent:
                lines.append(f"    {tech_agent['candlestick_read']}")

        lines.append(f"  Motivazione CEO: {final['rationale']}")

        trade_plan = r.get("trade_plan")
        if final["action"] == "BUY" and trade_plan:
            lines.append(f"  Stop-Loss: {trade_plan['stop']:.2f} (-{trade_plan['stop_pct']*100:.1f}%)")
            lines.append(
                f"  Take Profit: T1 {trade_plan['t1']:.2f} (R/R {trade_plan['rr1']}:1) | "
                f"T2 {trade_plan['t2']:.2f} (R/R {trade_plan['rr2']}:1) | "
                f"T3 {trade_plan['t3']:.2f} (R/R {trade_plan['rr3']}:1, runner)")
            binding = f" {trade_plan['binding']}" if trade_plan.get("binding") else ""
            lines.append(
                f"  Strategia operativa: confidenza {trade_plan['confidence']} | "
                f"regime x{trade_plan['regime_mult']}, convinzione x{trade_plan['size_mult']}")
            lines.append(
                f"    Sizing (su capitale nozionale {COMMITTEE_CAPITAL:,.0f}, NON il tuo capitale reale — "
                f"usa la % di portafoglio su qualunque capitale): {trade_plan['shares']} azioni = "
                f"{trade_plan['pos_value']:,.0f} ({trade_plan['pos_pct']}% portafoglio){binding}")
            lines.append(f"    Rischio massimo posizione: {trade_plan['risk_eur']:,.0f} "
                          f"| Costo round-trip stimato: {trade_plan['cost_pct']:.2f}%"
                          + ("" if trade_plan["cost_efficient"] else " [!] poco efficiente per conti piccoli"))
            lines.append(
                f"    Guadagno atteso (riferimento storico, ai vecchi target validati): "
                f"{trade_plan['net_exp_pct']:+.2f}% = {trade_plan['eur_exp']:+,.0f}")
        elif final["action"] == "BUY" and final.get("final_stop_loss_pct") is not None:
            lines.append(f"  Stop-Loss: -{final['final_stop_loss_pct']*100:.1f}% "
                          f"(trade plan non calcolabile: dati ATR mancanti per questo ticker)")

    lines.append("\n" + "=" * 70)
    mega = [r for r in results if r.get("candidate", {}).get("universe", "mega_cap") == "mega_cap"]
    uni = [r for r in results if r.get("candidate", {}).get("universe") == "unicorn"]
    lines.append(f"Universo mega-cap: {len(mega)} valutati dal Comitato, "
                 f"{sum(1 for r in mega if r['final']['action'] == 'BUY')} BUY")
    if unicorn_funnel is not None:
        lines.append(
            f"Universo unicorni: {unicorn_funnel.get('screened', 0)} candidati analizzati da "
            f"unicorn_screener.py, {unicorn_funnel.get('gate_passed', 0)} hanno superato il gate "
            f"momentum+crescita (unicorn_validate.py), {len(uni)} passati al Comitato "
            f"({sum(1 for r in uni if r['final']['action'] == 'BUY')} BUY, "
            f"{sum(1 for r in uni if r['final']['action'] == 'SKIP')} SKIP)")
    else:
        lines.append(f"Universo unicorni: {len(uni)} passati al Comitato "
                     f"({sum(1 for r in uni if r['final']['action'] == 'BUY')} BUY, "
                     f"{sum(1 for r in uni if r['final']['action'] == 'SKIP')} SKIP) — "
                     f"conteggio pre-gate non disponibile in questo run")
    return "\n".join(lines)


def _unicorn_funnel():
    """Conta candidati screenati/passati-gate anche per i ticker MAI arrivati al
    Comitato (es. nessuno ha passato il gate quella notte): risponde onestamente
    a "sono stati analizzati gli unicorni e sono stati scartati tutti?" invece di
    mostrare silenzio quando `results` non ne contiene nessuno."""
    import csv
    data_dir = REPO_ROOT / "data"
    screened = gate_passed = 0
    cand_path = data_dir / "unicorn_candidates.csv"
    sleeve_path = data_dir / "unicorn_sleeve.csv"
    if cand_path.exists():
        with open(cand_path) as f:
            screened = sum(1 for _ in csv.DictReader(f))
    if sleeve_path.exists():
        with open(sleeve_path) as f:
            gate_passed = sum(1 for row in csv.DictReader(f) if row.get("PASS") == "True")
    return {"screened": screened, "gate_passed": gate_passed}


def _operational_plan_json(plan):
    """Strategia operativa completa (sizing, rischio, costi, guadagno atteso), non
    solo i livelli di prezzo — calcolata in codice da modules/trade_proposal.py,
    mai chiesta all'LLM (stesso principio del trade plan). Il capitale
    (COMMITTEE_CAPITAL) e' NOZIONALE: shares/EUR sono illustrativi su quel
    capitale di riferimento, la % di portafoglio (position_pct) e' la cifra
    portabile su qualunque capitale reale dell'utente."""
    return {
        "confidence": plan["confidence"],
        "notional_capital": COMMITTEE_CAPITAL,
        "shares": plan["shares"],
        "position_value": plan["pos_value"],
        "position_pct": plan["pos_pct"],
        "max_risk": plan["risk_eur"],
        "cost_pct_round_trip": plan["cost_pct"],
        "cost_efficient": plan["cost_efficient"],
        "sizing_note": plan["binding"] or None,
        "regime_mult": plan["regime_mult"],
        "size_mult": plan["size_mult"],
        "expected_net_pct_legacy_targets": plan["net_exp_pct"],
        "expected_eur_legacy_targets": plan["eur_exp"],
        "targets_gain": {
            "t1": {"pct": plan["g1_pct"], "eur": plan["g1_eur"]},
            "t2": {"pct": plan["g2_pct"], "eur": plan["g2_eur"]},
            "t3": {"pct": plan["g3_pct"], "eur": plan["g3_eur"]},
        },
    }


def _signal_json(r):
    """Normalizza un risultato del Comitato nella forma consumata dalla dashboard
    Astro (frontend/). Un solo posto dove lo shape esportato e' definito, cosi'
    render_report() (testo) e la dashboard (JSON) leggono sempre dagli stessi dati
    grezzi senza poter divergere."""
    candidate = r.get("candidate", {}) or {}
    stages = r.get("stages", {}) or {}
    final = r["final"]
    plan = r.get("trade_plan")
    return {
        "ticker": r["ticker"],
        "universe": candidate.get("universe", "mega_cap"),
        "market": candidate.get("market"),
        "regime_gate": candidate.get("regime_gate"),
        "action": final["action"],
        "rationale": final["rationale"],
        "entry": candidate.get("entry_price"),
        "stop": plan["stop"] if plan else None,
        "stop_pct": plan["stop_pct"] if plan else final.get("final_stop_loss_pct"),
        "t1": plan["t1"] if plan else None,
        "t2": plan["t2"] if plan else None,
        "t3": plan["t3"] if plan else None,
        "rr1": plan["rr1"] if plan else None,
        "rr2": plan["rr2"] if plan else None,
        "rr3": plan["rr3"] if plan else None,
        "operational_plan": _operational_plan_json(plan) if plan else None,
        "fundamentals": candidate.get("fundamentals"),
        "technical": candidate.get("technical"),
        "candlestick": candidate.get("candlestick"),
        "technical_analyst": stages.get("technical_analyst"),
        "company_analyst": stages.get("company_analyst"),
        "finance_guy": stages.get("finance_guy"),
    }


def _json_safe(obj):
    """Sostituisce NaN/Infinity con None ovunque nell'albero. Python's json.dumps
    scrive il letterale bareword `NaN` (es. da ebitda_margin = operating_income/0
    per un ticker senza EBITDA valido), che NON e' JSON valido in senso stretto e
    manda in crash il parser JSON di Vite/Astro in fase di build."""
    if isinstance(obj, float) and (obj != obj or obj in (float("inf"), float("-inf"))):
        return None
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(v) for v in obj]
    return obj


def export_frontend_json(results, asof, unicorn_funnel=None, frontend_dir=None):
    """Scrive il payload JSON per la dashboard Astro (frontend/):
      - frontend/public/data/runs/<asof>.json  (snapshot immutabile della nottata)
      - frontend/public/data/manifest.json     (indice di TUTTE le notti, per l'archivio storico)
      - frontend/public/data/latest.json       (copia dell'ultima notte, per la home)
    Idempotente: se lanciato piu' volte per lo stesso `asof`, sovrascrive la stessa
    entry nel manifest invece di duplicarla.
    """
    frontend_dir = frontend_dir or (REPO_ROOT / "frontend")
    data_dir = frontend_dir / "public" / "data"
    runs_dir = data_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    signals = [_signal_json(r) for r in results]
    market_regime = {}
    for r in results:
        candidate = r.get("candidate", {}) or {}
        market = candidate.get("market")
        if market and market not in market_regime:
            market_regime[market] = candidate.get("regime_gate")

    payload = {
        "date": asof,
        "last_updated": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "market_regime": market_regime,
        "signals": signals,
        "unicorns": {
            "screened": (unicorn_funnel or {}).get("screened", 0),
            "gate_passed": (unicorn_funnel or {}).get("gate_passed", 0),
            "evaluated": sum(1 for s in signals if s["universe"] == "unicorn"),
            "buy": sum(1 for s in signals if s["universe"] == "unicorn" and s["action"] == "BUY"),
            "skip": sum(1 for s in signals if s["universe"] == "unicorn" and s["action"] == "SKIP"),
        },
    }
    payload = _json_safe(payload)

    run_path = runs_dir / f"{asof}.json"
    run_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    (data_dir / "latest.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False))

    manifest_path = data_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else []
    manifest = [m for m in manifest if m["date"] != asof]
    manifest.append({
        "date": asof,
        "buy": sum(1 for s in signals if s["action"] == "BUY"),
        "skip": sum(1 for s in signals if s["action"] == "SKIP"),
        "total": len(signals),
    })
    manifest.sort(key=lambda m: m["date"], reverse=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    return payload


def main():
    if len(sys.argv) < 2:
        print("uso: python3 orchestrator.py <candidates.json>")
        sys.exit(1)
    candidates = json.loads(Path(sys.argv[1]).read_text())
    orch = NativeOrchestrator()
    results = [orch.run_committee(c) for c in candidates]
    asof = datetime.date.today().isoformat()
    unicorn_funnel = _unicorn_funnel()
    report = render_report(results, asof, unicorn_funnel=unicorn_funnel)
    data_dir = REPO_ROOT / "data"
    data_dir.mkdir(exist_ok=True)
    (data_dir / f"COMMITTEE_REPORT_{asof}.txt").write_text(report)
    (data_dir / f"committee_output_{asof}.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False))
    export_frontend_json(results, asof, unicorn_funnel=unicorn_funnel)
    print(report)


if __name__ == "__main__":
    main()
