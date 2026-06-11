import json, time, re, io, zipfile, datetime as dt
import urllib.request
import xml.etree.ElementTree as ET
import pandas as pd

# ====== PERSONALIZZA: la SEC richiede un User-Agent con email reale ======
UA = {"User-Agent": "MIB Pipeline newspaper.gram@gmail.com"}
# =========================================================================

US_TICKERS = ["AAPL","MSFT","NVDA","GOOGL","AMZN","META","AVGO","TSLA","LLY","JPM",
              "V","UNH","XOM","COST","HD","PG","JNJ","ORCL","BAC","NFLX",
              "AMD","CRM","KO","CVX","MRK","WMT","PLTR","GE","CAT","GS"]

# Gestori attivi concentrati (CIK). Il log stampa il nome restituito da EDGAR:
# se non corrisponde, correggere il CIK.
GURUS = {
    "Berkshire Hathaway": "0001067983",
    "Pershing Square":    "0001336528",
    "Scion Asset Mgmt":   "0001649339",
    "Appaloosa":          "0001656456",
    "Baupost Group":      "0001061768",
}

LOG = []
def log(m): print(m); LOG.append(m)

def get(url, binary=False, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=40) as r:
                d = r.read()
            time.sleep(0.15)  # rispetto del limite SEC 10 req/s
            return d if binary else d.decode("utf-8", "ignore")
        except Exception as e:
            if i == tries-1: raise
            time.sleep(1.5)

# ---------- 1) FORM 4 INSIDER (ultimi 30 giorni, codice P/S) ----------
def insider():
    tickmap = json.loads(get("https://www.sec.gov/files/company_tickers.json"))
    t2c = {v["ticker"]: str(v["cik_str"]).zfill(10) for v in tickmap.values()}
    cutoff = (dt.date.today() - dt.timedelta(days=30)).isoformat()
    rows = []
    for tk in US_TICKERS:
        cik = t2c.get(tk)
        if not cik: log(f"[INS] {tk}: CIK non trovato"); continue
        try:
            sub = json.loads(get(f"https://data.sec.gov/submissions/CIK{cik}.json"))
            rec = sub["filings"]["recent"]
            buys, sells = set(), set()
            bval = sval = 0.0; officer_buy = False
            for form, date, acc, doc in zip(rec["form"], rec["filingDate"],
                                            rec["accessionNumber"], rec["primaryDocument"]):
                if form != "4" or date < cutoff: continue
                accn = acc.replace("-", ""); fn = doc.split("/")[-1]
                try:
                    x = get(f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accn}/{fn}")
                    root = ET.fromstring(x)
                except Exception: continue
                owner = (root.findtext(".//rptOwnerName") or f"owner_{accn[:8]}")
                is_off = (root.findtext(".//isOfficer") or "0").strip() in ("1","true")
                for tr in root.iter("nonDerivativeTransaction"):
                    code = tr.findtext(".//transactionCode") or ""
                    ad   = tr.findtext(".//transactionAcquiredDisposedCode/value") or ""
                    sh   = float(tr.findtext(".//transactionShares/value") or 0)
                    px   = float(tr.findtext(".//transactionPricePerShare/value") or 0)
                    if code == "P" and ad == "A":
                        buys.add(owner); bval += sh*px
                        if is_off: officer_buy = True
                    elif code == "S":
                        sells.add(owner); sval += sh*px
            rows.append(dict(ticker=tk, buy_insiders=len(buys), sell_insiders=len(sells),
                             buy_value=round(bval), sell_value=round(sval),
                             officer_buy=officer_buy, cluster=len(buys) >= 2))
        except Exception as e:
            log(f"[INS] {tk}: ERR {e}")
    pd.DataFrame(rows).to_csv("data/insider_us.csv", index=False)
    log(f"[INS] ok: {len(rows)} ticker")

# ---------- 2) 13F TOP HOLDINGS DEI GURU ----------
def thirteenf():
    rows = []
    for name, cik in GURUS.items():
        try:
            sub = json.loads(get(f"https://data.sec.gov/submissions/CIK{cik}.json"))
            log(f"[13F] {name} -> EDGAR: {sub.get('name','?')}")
            rec = sub["filings"]["recent"]
            acc = next((a for f,a in zip(rec["form"], rec["accessionNumber"])
                        if f.startswith("13F-HR")), None)
            if not acc: log(f"[13F] {name}: nessun 13F-HR"); continue
            accn = acc.replace("-", "")
            idx = json.loads(get(f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accn}/index.json"))
            xmls = [i["name"] for i in idx["directory"]["item"]
                    if i["name"].lower().endswith(".xml") and "infotable" in i["name"].lower()]
            if not xmls:
                xmls = [i["name"] for i in idx["directory"]["item"]
                        if i["name"].lower().endswith(".xml") and "primary" not in i["name"].lower()]
            x = get(f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accn}/{xmls[0]}")
            x = re.sub(r'xmlns="[^"]+"', "", x, count=1)
            root = ET.fromstring(x)
            hold = []
            for it in root.iter("infoTable"):
                hold.append((it.findtext("nameOfIssuer") or "?",
                             float(it.findtext("value") or 0)))
            hold.sort(key=lambda z: -z[1])
            for issuer, val in hold[:15]:
                rows.append(dict(guru=name, issuer=issuer, value_kusd=int(val)))
        except Exception as e:
            log(f"[13F] {name}: ERR {e}")
    pd.DataFrame(rows).to_csv("data/13f_holdings.csv", index=False)
    log(f"[13F] ok: {len(rows)} posizioni")

# ---------- 3) COT (TFF: S&P 500 e Nasdaq-100) ----------
def cot():
    try:
        from cot_reports import cot_year
        yr = dt.date.today().year
        df = pd.concat([cot_year(yr-1, cot_report_type="traders_in_financial_futures_fut"),
                        cot_year(yr,   cot_report_type="traders_in_financial_futures_fut")])
        m = df["Market_and_Exchange_Names"].str.contains("S&P 500|NASDAQ-100", case=False, na=False)
        df = df[m].copy()
        df["date"] = pd.to_datetime(df["Report_Date_as_YYYY-MM-DD"])
        df["lev_net"] = df["Lev_Money_Positions_Long_All"] - df["Lev_Money_Positions_Short_All"]
        df["am_net"]  = df["Asset_Mgr_Positions_Long_All"] - df["Asset_Mgr_Positions_Short_All"]
        out = []
        for mkt, g in df.groupby("Market_and_Exchange_Names"):
            g = g.sort_values("date")
            for col in ("lev_net","am_net"):
                z = (g[col].iloc[-1]-g[col].mean())/(g[col].std() or 1)
                out.append(dict(market=mkt[:40], metric=col,
                                latest=int(g[col].iloc[-1]), zscore=round(z,2),
                                date=str(g["date"].iloc[-1].date())))
        pd.DataFrame(out).to_csv("data/cot.csv", index=False)
        log(f"[COT] ok: {len(out)} righe")
    except Exception as e:
        log(f"[COT] ERR {e}")

# ---------- 4) SHORT FRANCIA (AMF via data.gouv.fr) ----------
def short_fr():
    try:
        api = ("https://www.data.gouv.fr/api/1/datasets/?q="
               "positions+courtes+nettes+AMF&page_size=5")
        ds = json.loads(get(api))["data"]
        url = None
        for d in ds:
            for r in d.get("resources", []):
                if r.get("format","").lower() == "csv":
                    url = r["url"]; break
            if url: break
        raw = get(url)
        df = pd.read_csv(io.StringIO(raw), sep=None, engine="python")
        df.tail(400).to_csv("data/short_fr.csv", index=False)
        log(f"[SHF] ok: {min(len(df),400)} righe da {url[:60]}")
    except Exception as e:
        log(f"[SHF] ERR {e} (consultare AMF via web in analisi)")

# ---------- MAIN ----------
import os
os.makedirs("data", exist_ok=True)
for fn in (insider, thirteenf, cot, short_fr):
    try: fn()
    except Exception as e: log(f"[FATAL] {fn.__name__}: {e}")
open("data/flows_log.txt","w").write(
    dt.datetime.utcnow().isoformat()+"Z\n"+"\n".join(LOG))
print("fetch_flows completato")
