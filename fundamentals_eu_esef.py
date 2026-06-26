"""fundamentals_eu_esef.py — Hook PRONTO (gated da allowlist) per il PIT-EU vero via ESEF.

STATO (2026-06-26): l'host `filings.xbrl.org` (repository ufficiale ESEF di XBRL International)
e' BLOCCATO dall'allowlist di egress (ProxyError al CONNECT, stesso pattern di Lezioni #3/#4).
Questo modulo e' scritto PRONTO secondo il pattern del repo ("codice pronto, leva = allowlist"):
si attiva automaticamente appena `filings.xbrl.org` viene aggiunto all'allowlist.

COSA AGGIUNGEREBBE (valore quando sbloccato):
  - `fundamentals_eu.py` oggi approssima la disponibilita' del dato EU come fine-periodo + 120gg
    (lag regolatorio). L'ESEF index espone la DATA DI DEPOSITO REALE (`date_added`) -> si
    sostituirebbe l'approssimazione con il filed-date vero, rendendo il PIT-EU 2020+ esatto.
  - I VALORI restano da Yahoo (l'ESEF index non e' una companyfacts pulita come la SEC; estrarre
    i fatti richiede il download del report package iXBRL, fuori da questo hook minimale).

LIMITE STRUTTURALE (non aggirabile da nessuna fonte): il mandato ESEF parte da FY2020 -> la
storia EU pre-2020 NON esiste in XBRL standardizzato. Quindi il massimo ottenibile e' 2020+.

ONESTA': il parsing sotto e' DIFENSIVO ma NON testato in produzione (host bloccato). Degrada a
None con messaggio chiaro; va verificato sul campo quando l'allowlist sara' aperto. Non fabbrica
dati: se non raggiunge l'host o non riconosce lo schema, ritorna None.
"""
import datetime

try:
    import requests
except Exception:
    requests = None

from modules.fmp_source import _BROWSER_HEADERS

BASE = "https://filings.xbrl.org/api"


def reachable():
    """True se filings.xbrl.org risponde (host in allowlist). Non solleva eccezioni."""
    if requests is None:
        return False
    try:
        r = requests.get(f"{BASE}/filings", params={"page[size]": 1},
                         headers=_BROWSER_HEADERS, timeout=15)
        return r.status_code == 200
    except Exception:
        return False


def esef_filing_dates(lei, since="2020-01-01"):
    """Date di deposito REALI (period_end -> filing_date) per un'entita' EU, via LEI.

    L'ESEF index e' chiavato per LEI (Legal Entity Identifier), non per ticker: serve una
    mappa ticker->LEI a monte (TODO: GLEIF API o tabella statica). Ritorna lista di tuple
    (period_end:str, filing_date:str) ordinata, oppure None se host bloccato / schema ignoto.

    NB: parsing difensivo su JSON:API (campi possibili: attributes.period_end / period,
    attributes.date_added / added). NON testato in produzione (host bloccato). Verificare
    sul campo quando l'allowlist e' aperto.
    """
    if not reachable():
        print("[ESEF] filings.xbrl.org non raggiungibile (host non in allowlist) -> None")
        return None
    try:
        r = requests.get(f"{BASE}/filings",
                         params={"filter[entity.identifier]": lei, "page[size]": 100},
                         headers=_BROWSER_HEADERS, timeout=25)
        if r.status_code != 200:
            print(f"[ESEF] HTTP {r.status_code} per LEI {lei}")
            return None
        data = r.json().get("data", [])
    except Exception as e:
        print(f"[ESEF] errore query LEI {lei}: {repr(e)[:90]}")
        return None

    out = []
    for item in data:
        a = item.get("attributes", {}) or {}
        period = a.get("period_end") or a.get("period") or a.get("fiscal_period")
        filed = a.get("date_added") or a.get("added") or a.get("processed")
        if not period or not filed:
            continue
        period, filed = str(period)[:10], str(filed)[:10]
        if period >= since:
            out.append((period, filed))
    if not out:
        print(f"[ESEF] nessun filing riconosciuto per LEI {lei} (schema da verificare)")
        return None
    return sorted(set(out))


def probe():
    """Diagnostica: stampa stato raggiungibilita' + un campione di schema (se aperto)."""
    if not reachable():
        print("[ESEF] BLOCCATO: aggiungere 'filings.xbrl.org' all'allowlist per attivare il PIT-EU vero 2020+.")
        return False
    print("[ESEF] RAGGIUNGIBILE. Campione schema /api/filings:")
    try:
        r = requests.get(f"{BASE}/filings", params={"page[size]": 2},
                         headers=_BROWSER_HEADERS, timeout=20)
        items = r.json().get("data", [])
        for it in items:
            print("  attributes keys:", list((it.get("attributes", {}) or {}).keys()))
    except Exception as e:
        print(f"  errore lettura schema: {repr(e)[:90]}")
    return True


if __name__ == "__main__":
    probe()
