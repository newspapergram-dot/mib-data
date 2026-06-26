"""unicorn_screener.py — Scoperta di "unicorni" growth USA via fondamentali SEC EDGAR.

Estende l'universo oltre i 45 mega/large-cap della watchlist: la SEC copre TUTTI i
filer USA (company_tickers.json, ~10k), quindi i fondamentali costano solo rate-limit.
Cerca il profilo "unicorno": crescita ricavi alta e sostenuta, margini scalabili e in
miglioramento (leva operativa), dimensione ancora contenuta (spazio per crescere),
bilancio capace di finanziare la crescita.

ONESTA' SULLO SCOPO (cruciale): questo e' uno screener FONDAMENTALE DI SCOPERTA, non un
segnale di alpha validato. Diversamente dallo score (backtestato) e dal filtro PIT
(validato per regime in pit_validate), qui NON c'e' prova statistica che il profilo
predica i ritorni. La validazione di Run #14 anzi avverte: i nomi high-growth/non
profittevoli sono ESPLOSIVI ma HIGH-BETA (crollano per primi in bear). Un candidato
"unicorno" va quindi sempre passato dal gate momentum + regime + stop del modello, mai
comprato sui soli fondamentali. Output = lista da indagare, non da eseguire.

Output: data/unicorn_candidates.csv (ranked) + log a stdout.
"""
import json
import datetime
import os
import csv

import fundamentals_pit as fp

# Concetti XBRL per i totali annuali (in ordine di PRIORITA': i totali "puliti" prima,
# le varianti con segmenti/assessed-tax come ripiego). Gestisce il tagging non uniforme
# tra emittenti (es. CRWD espone solo IncludingAssessedTax).
REVENUE_CONCEPTS = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
    "SalesRevenueServicesNet",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
]
GROSS_CONCEPTS = ["GrossProfit"]
NET_INCOME_CONCEPTS = ["NetIncomeLoss",
                       "NetIncomeLossAvailableToCommonStockholdersBasic"]


def _annual_totals(facts, concepts):
    """Totali ANNUALI per anno-fiscale da companyfacts, robusti al tagging non uniforme.

    Regole:
      - solo 10-K/10-Q con start+end e durata ~annuale (350-380gg) -> esclude trimestrali;
      - chiave = anno della data `end` (NON il campo `fy`, che e' l'anno del FILING);
      - dedup per anno: vince il filing piu' recente (restatement), poi il valore max
        (il totale consolidato >= un singolo segmento);
      - priorita' tra concetti: un anno gia' coperto da un concetto piu' affidabile NON
        viene sovrascritto da uno di ripiego (evita che un segmento rimpiazzi un totale).
    Ritorna {anno_end: valore} ordinabile per anno.
    """
    pools = [facts.get("facts", {}).get("us-gaap", {}),
             facts.get("facts", {}).get("dei", {})]
    result = {}            # year -> (filed, val)
    for concept in concepts:
        this_concept = {}  # year -> (filed, val) per QUESTO concetto
        for pool in pools:
            if concept not in pool:
                continue
            for entries in pool[concept].get("units", {}).values():
                for e in entries:
                    if e.get("form") not in ("10-K", "10-Q"):
                        continue
                    s, en = e.get("start"), e.get("end")
                    if not s or not en:
                        continue
                    try:
                        dur = (datetime.date.fromisoformat(en) -
                               datetime.date.fromisoformat(s)).days
                    except ValueError:
                        continue
                    if not (350 <= dur <= 380):
                        continue
                    val = fp._num(e.get("val"))
                    if val is None:
                        continue
                    y = int(en[:4])
                    filed = e.get("filed", "")
                    keep = this_concept.get(y)
                    if keep is None or filed > keep[0] or (filed == keep[0] and val > keep[1]):
                        this_concept[y] = (filed, val)
        # riempi solo gli anni non gia' coperti da un concetto a priorita' superiore
        for y, fv in this_concept.items():
            if y not in result:
                result[y] = fv
    return {y: v for y, (f, v) in result.items()}

# ---------------------------------------------------------------------------
# UNIVERSO CANDIDATI — growth USA mid/large-cap fuori dai 45 mega-cap gia' coperti.
# Lista di PARTENZA curata su temi secolari (cloud/AI/cyber/fintech/consumer/biotech/
# semis/industrial-tech). Tutti filer SEC (10-K): i foreign issuer (20-F, es. SE/MELI/
# ASML) ritornano vuoti e vengono saltati senza errore. Estendibile liberamente.
# ---------------------------------------------------------------------------
CANDIDATES = [
    # Cloud / software infrastruttura
    "SNOW", "NET", "DDOG", "MDB", "CFLT", "GTLB", "S", "ZS", "OKTA", "PANW",
    "CRWD", "FTNT", "TEAM", "HUBS", "BILL", "TWLO", "DOCU", "ESTC", "PD", "FROG",
    # AI / data / dev tools
    "PATH", "AI", "PLTR", "SMCI", "ARM", "ANET",
    # Fintech / pagamenti
    "SOFI", "AFRM", "COIN", "HOOD", "XYZ", "TOST", "NU", "UPST",
    # Consumer / piattaforme
    "ABNB", "DASH", "UBER", "RBLX", "U", "DKNG", "TTD", "ROKU", "CELH", "ELF",
    # Healthcare / biotech growth
    "RXRX", "VEEV", "DXCM", "PODD", "NVCR", "EXAS",
    # Industrial / clean / mobility tech
    "ENPH", "FSLR", "RIVN", "LCID", "CART", "GEV",
]


def _cagr(series, years):
    """CAGR su `years` anni dall'ultima coppia disponibile. None se non calcolabile."""
    if len(series) < years + 1:
        return None
    first, last = series[-(years + 1)], series[-1]
    if first is None or last is None or first <= 0 or last <= 0:
        return None
    return (last / first) ** (1.0 / years) - 1.0


def _yoy(series):
    if len(series) < 2 or series[-2] in (None, 0) or series[-2] <= 0:
        return None
    return series[-1] / series[-2] - 1.0


def analyze(ticker, facts):
    """Profilo unicorno da companyfacts SEC. Ritorna dict o None se dati insufficienti."""
    rev_by_y = _annual_totals(facts, REVENUE_CONCEPTS)
    gp_by_y = _annual_totals(facts, GROSS_CONCEPTS)
    ni_by_y = _annual_totals(facts, NET_INCOME_CONCEPTS)

    years = sorted(rev_by_y)
    if len(years) < 2:
        return None
    rev_series = [rev_by_y[y] for y in years]

    rev_latest = rev_series[-1]
    last_y = years[-1]
    rev_cagr_3y = _cagr(rev_series, 3)
    rev_cagr_5y = _cagr(rev_series, 5)
    rev_yoy = _yoy(rev_series)

    # gross/net margin allineati per ANNO (stesso end-year di revenue) -> niente 184% spurii
    def _margin(by_y, y):
        r = rev_by_y.get(y)
        v = by_y.get(y)
        if r and r > 0 and v is not None:
            m = v / r
            return m if -5.0 < m <= 1.5 else None   # sanity: scarta rapporti implausibili
        return None

    gm_now = _margin(gp_by_y, last_y)
    gm_then = _margin(gp_by_y, last_y - 3)
    gm_trend = (gm_now - gm_then) if (gm_now is not None and gm_then is not None) else None
    nm_now = _margin(ni_by_y, last_y)

    # bilancio: cash / LT-debt (capacita' di finanziare la crescita) — ultimo instant
    data = fp._extract_facts(facts)
    def _last_instant(field):
        e = data.get(field, [])
        return fp._num(e[-1].get("val")) if e else None
    cash = _last_instant("cash")
    ltd = _last_instant("long_term_debt")
    cash_to_ltd = (cash / ltd) if (cash is not None and ltd and ltd != 0) else None

    score, reasons = _unicorn_score(rev_cagr_3y, rev_yoy, gm_now, gm_trend, rev_latest, nm_now)

    return {
        "ticker": ticker,
        "entity": facts.get("entityName", ticker),
        "unicorn_score": score,
        "rev_latest": rev_latest,
        "rev_cagr_3y": _r(rev_cagr_3y, 4),
        "rev_cagr_5y": _r(rev_cagr_5y, 4),
        "rev_yoy": _r(rev_yoy, 4),
        "gross_margin": _r(gm_now, 4),
        "gm_trend_3y": _r(gm_trend, 4),
        "net_margin": _r(nm_now, 4),
        "cash_to_lt_debt": _r(cash_to_ltd, 2),
        "profile": "; ".join(reasons),
        "n_years": len(rev_series),
    }


def _unicorn_score(cagr3, yoy, gm, gm_trend, rev, nm):
    """Score [0,100] del profilo unicorno + note. Euristico, NON validato sui ritorni.

    Pesi: crescita 45 | margine scalabile 25 | leva operativa (margine in salita) 10 |
    dimensione (spazio di crescita) 15 | bonus 'profittevole mentre cresce' 5.
    """
    pts = 0.0
    reasons = []

    # 1) Crescita ricavi (45): usa il max tra CAGR 3Y e YoY (cattura sia trend sia accelerazione)
    g = max([x for x in (cagr3, yoy) if x is not None], default=None)
    if g is not None:
        # 0% -> 0 pt, 50%+ -> 45 pt (lineare con cap)
        pts += min(max(g, 0) / 0.50, 1.0) * 45
        if g >= 0.40:
            reasons.append(f"crescita ricavi {g*100:.0f}% (iper-growth)")
        elif g >= 0.20:
            reasons.append(f"crescita ricavi {g*100:.0f}%")
        else:
            reasons.append(f"crescita ricavi modesta {g*100:.0f}%")

    # 2) Margine lordo scalabile (25): 30% -> 0, 80%+ -> 25
    if gm is not None:
        pts += min(max(gm - 0.30, 0) / 0.50, 1.0) * 25
        if gm >= 0.70:
            reasons.append(f"gross margin {gm*100:.0f}% (software-like)")
        elif gm >= 0.50:
            reasons.append(f"gross margin {gm*100:.0f}%")

    # 3) Leva operativa: gross margin in miglioramento (10)
    if gm_trend is not None and gm_trend > 0:
        pts += min(gm_trend / 0.10, 1.0) * 10
        reasons.append(f"margine in salita (+{gm_trend*100:.1f}pp/3Y)")

    # 4) Dimensione: piu' piccolo = piu' spazio (15). <2B rev -> 15, >30B -> 0
    if rev is not None:
        if rev < 2e9:
            pts += 15; reasons.append("small-cap (ampio spazio)")
        elif rev < 10e9:
            pts += 10; reasons.append("mid-cap")
        elif rev < 30e9:
            pts += 4
        # >30B: nessun bonus (gia' grande)

    # 5) Profittevole MENTRE cresce (5): rara combinazione di qualita'
    if nm is not None and nm > 0 and g is not None and g >= 0.20:
        pts += 5
        reasons.append("profittevole in crescita")
    elif nm is not None and nm < 0:
        reasons.append(f"non profittevole (nm {nm*100:.0f}%, high-beta)")

    return round(pts, 1), reasons


def _r(v, n):
    return round(v, n) if v is not None else None


def run(candidates=None, out_path="data/unicorn_candidates.csv", top_n=20):
    candidates = candidates or CANDIDATES
    t2c = fp.ticker_to_cik()
    rows, skipped = [], []

    for tk in candidates:
        cik = t2c.get(tk)
        if not cik:
            skipped.append((tk, "no CIK")); continue
        try:
            facts = json.loads(fp.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"))
            prof = analyze(tk, facts)
            if prof is None:
                skipped.append((tk, "dati insufficienti / foreign filer")); continue
            rows.append(prof)
            print(f"[uni] {tk:6s} score={prof['unicorn_score']:5.1f} "
                  f"rev={fp._fmt_big(prof['rev_latest'])} cagr3={_pct(prof['rev_cagr_3y'])} "
                  f"gm={_pct(prof['gross_margin'])} | {prof['profile']}")
        except Exception as e:
            skipped.append((tk, f"ERR {repr(e)[:50]}"))

    rows.sort(key=lambda r: r["unicorn_score"], reverse=True)

    if rows and out_path:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=rows[0].keys())
            w.writeheader()
            w.writerows(rows)
        print(f"\n[uni] scritto {out_path} ({len(rows)} candidati)")

    print("\n" + "=" * 78)
    print(f" TOP {min(top_n, len(rows))} CANDIDATI UNICORNO (profilo fondamentale, NON validato sui ritorni)")
    print("=" * 78)
    print(f" {'#':>2} {'TICK':6s}{'SCORE':>7s}{'REV':>8s}{'CAGR3Y':>8s}{'GM%':>7s}{'NM%':>7s}  PROFILO")
    for i, r in enumerate(rows[:top_n], 1):
        print(f" {i:>2} {r['ticker']:6s}{r['unicorn_score']:7.1f}{fp._fmt_big(r['rev_latest']):>8s}"
              f"{_pct(r['rev_cagr_3y']):>8s}{_pct(r['gross_margin']):>7s}{_pct(r['net_margin']):>7s}  {r['profile']}")

    if skipped:
        print(f"\n[uni] saltati ({len(skipped)}): " +
              ", ".join(f"{t}({why})" for t, why in skipped))
    print("\n[uni] NB: screener di SCOPERTA, non segnale validato. Passare i candidati dal gate")
    print("  momentum + regime + stop del modello prima di operare (sono high-beta: vedi Lezione #14).")
    return rows


def _pct(v):
    return "N/A" if v is None else f"{float(v)*100:.0f}%"


if __name__ == "__main__":
    run()
