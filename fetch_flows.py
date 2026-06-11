import json, time, re, io, datetime as dt
import urllib.request
import xml.etree.ElementTree as ET
import pandas as pd

# ====== PERSONALIZZA: la SEC richiede User-Agent con email reale ======
UA = {"User-Agent": "MIB Pipeline newspaper.gram@gmail.com"}
# ======================================================================

# Mega-cap (segnale insider strutturalmente raro, ma le vendite contano)
US_TICKERS = ["AAPL","MSFT","NVDA","GOOGL","AMZN","META","AVGO","TSLA","LLY","JPM",
              "V","UNH","XOM","COST","HD","PG","JNJ","ORCL","BAC","NFLX",
              "AMD","CRM","KO","CVX","MRK","WMT","PLTR","GE","CAT","GS"]

# ====== PERSONALIZZA: mid/small-cap dove l'insider buying ha vero valore ======
# Inserisci qui i titoli su cui hai una tesi: è dove il segnale insider conta.
INSIDER_FOCUS = ["RIG","AAL","PARA","WBD","HBI","CHK","RIOT"]
# ==============================================================================

GURUS = {
    "Berkshire Hathaway": "0001067983",
    "Pershing Square":    "0001336528",
    "Scion Asset Mgmt":   "0001649339",
    "Appaloosa":          "0001656456",
    "Baupost Group":      "0001061768",
}

LOG=[]
def log(m): print(m); LOG.append(m)

def get(url, tries=3):
    for i in range(tries):
        try:
            req=urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=45) as r:
                d=r.read().decode("utf-8","ignore")
            time.sleep(0.16)  # rispetta limite SEC 10 req/s
            return d
        except Exception as e:
            if i==tries-1: raise
            time.sleep(1.6)

# ---------- 1) INSIDER FORM 4 (codici corretti + 10b5-1) ----------
def insider():
    tickmap=json.loads(get("https://www.sec.gov/files/company_tickers.json"))
    t2c={v["ticker"]:str(v["cik_str"]).zfill(10) for v in tickmap.values()}
    cutoff=(dt.date.today()-dt.timedelta(days=45)).isoformat()
    rows=[]
    universe=[(t,"mega") for t in US_TICKERS]+[(t,"focus") for t in INSIDER_FOCUS]
    for tk,grp in universe:
        cik=t2c.get(tk)
        if not cik: log(f"[INS] {tk}: CIK assente"); continue
        try:
            sub=json.loads(get(f"https://data.sec.gov/submissions/CIK{cik}.json"))
            rec=sub["filings"]["recent"]
            buyers=set(); sellers=set(); disc_sellers=set()
            bval=sval=0.0; officer_buy=False
            for form,date,acc,doc in zip(rec["form"],rec["filingDate"],
                                         rec["accessionNumber"],rec["primaryDocument"]):
                if form!="4" or date<cutoff: continue
                accn=acc.replace("-",""); fn=doc.split("/")[-1]
                try:
                    x=get(f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accn}/{fn}")
                    root=ET.fromstring(x)
                except Exception: continue
                owner=root.findtext(".//rptOwnerName") or f"o_{accn[:8]}"
                is_off=(root.findtext(".//isOfficer") or "0").strip() in ("1","true")
                # 10b5-1: piano pre-impostato => vendita "routine", non opportunistica
                planned=(root.findtext(".//aff10b5One") or "0").strip() in ("1","true")
                for tr in root.iter("nonDerivativeTransaction"):
                    code=tr.findtext(".//transactionCode") or ""
                    ad=tr.findtext(".//transactionAcquiredDisposedCode/value") or ""
                    sh=float(tr.findtext(".//transactionShares/value") or 0)
                    px=float(tr.findtext(".//transactionPricePerShare/value") or 0)
                    if code=="P" and ad=="A":            # acquisto open-market
                        buyers.add(owner); bval+=sh*px
                        if is_off: officer_buy=True
                    elif code=="S" and ad=="D":          # vendita open-market
                        sellers.add(owner); sval+=sh*px
                        if not planned: disc_sellers.add(owner)
                    # M (esercizio opzioni), A (grant), F (tax), G (dono) -> esclusi
            # segnale: +1 cluster buy / -1 vendite discrezionali / 0 neutro
            sig=0
            if len(buyers)>=2: sig=1
            elif len(buyers)==1 and officer_buy: sig=1
            elif len(disc_sellers)>=2: sig=-1
            rows.append(dict(ticker=tk, group=grp,
                buy_insiders=len(buyers), sell_insiders=len(sellers),
                discretionary_sellers=len(disc_sellers),
                buy_value=round(bval), sell_value=round(sval),
                officer_buy=officer_buy, cluster_buy=len(buyers)>=2, signal=sig))
        except Exception as e:
            log(f"[INS] {tk}: ERR {e}")
    pd.DataFrame(rows).to_csv("data/insider_us.csv", index=False)
    nb=sum(1 for r in rows if r["signal"]==1)
    log(f"[INS] ok: {len(rows)} ticker, {nb} con segnale buy")

# ---------- 2) 13F (aggregato per emittente) ----------
def thirteenf():
    rows=[]
    for name,cik in GURUS.items():
        try:
            sub=json.loads(get(f"https://data.sec.gov/submissions/CIK{cik}.json"))
            log(f"[13F] {name} -> {sub.get('name','?')}")
            rec=sub["filings"]["recent"]
            acc=next((a for f,a in zip(rec["form"],rec["accessionNumber"])
                      if f.startswith("13F-HR")),None)
            if not acc: log(f"[13F] {name}: nessun 13F-HR"); continue
            accn=acc.replace("-","")
            idx=json.loads(get(f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accn}/index.json"))
            names=[i["name"] for i in idx["directory"]["item"] if i["name"].lower().endswith(".xml")]
            xmls=[n for n in names if "infotable" in n.lower()] or \
                 [n for n in names if "primary_doc" not in n.lower()]
            x=get(f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accn}/{xmls[0]}")
            x=re.sub(r'xmlns="[^"]+"',"",x,count=1)
            root=ET.fromstring(x)
            agg={}
            for it in root.iter("infoTable"):
                iss=(it.findtext("nameOfIssuer") or "?").strip().upper()
                val=float(it.findtext("value") or 0)
                agg[iss]=agg.get(iss,0)+val
            for iss,val in sorted(agg.items(),key=lambda z:-z[1])[:15]:
                rows.append(dict(guru=name, issuer=iss, value_kusd=int(val)))
        except Exception as e:
            log(f"[13F] {name}: ERR {e}")
    pd.DataFrame(rows).to_csv("data/13f_holdings.csv", index=False)
    log(f"[13F] ok: {len(rows)} posizioni aggregate")

# ---------- 3) COT (solo S&P500 + Nasdaq100 Consolidated, z 3 anni) ----------
def cot():
    try:
        from cot_reports import cot_year
        yr=dt.date.today().year
        frames=[]
        for y in (yr-2,yr-1,yr):
            try: frames.append(cot_year(y, cot_report_type="traders_in_financial_futures_fut"))
            except Exception as e: log(f"[COT] anno {y}: {e}")
        df=pd.concat(frames)
        keep=df["Market_and_Exchange_Names"].str.contains(
            "S&P 500 Consolidated|NASDAQ-100 Consolidated", case=False, na=False)
        df=df[keep].copy()
        df["date"]=pd.to_datetime(df["Report_Date_as_YYYY-MM-DD"])
        df["lev_net"]=df["Lev_Money_Positions_Long_All"]-df["Lev_Money_Positions_Short_All"]
        df["am_net"]=df["Asset_Mgr_Positions_Long_All"]-df["Asset_Mgr_Positions_Short_All"]
        def band(z):
            return ("estremo long" if z>=2 else "long" if z>=1 else
                    "estremo short" if z<=-2 else "short" if z<=-1 else "neutro")
        out=[]
        for mkt,g in df.groupby("Market_and_Exchange_Names"):
            g=g.sort_values("date")
            for col in ("lev_net","am_net"):
                z=(g[col].iloc[-1]-g[col].mean())/(g[col].std() or 1)
                out.append(dict(market=mkt.split(" - ")[0][:38],
                    trader=("Hedge fund" if col=="lev_net" else "Asset manager"),
                    latest=int(g[col].iloc[-1]), zscore=round(z,2),
                    posizionamento=band(z), date=str(g["date"].iloc[-1].date())))
        pd.DataFrame(out).to_csv("data/cot.csv", index=False)
        log(f"[COT] ok: {len(out)} righe pulite")
    except Exception as e:
        log(f"[COT] ERR {e}")

# ---------- 4) SHORT FRANCIA (slug data.gouv diretto) ----------
def short_fr():
    slug="historique-des-positions-courtes-nettes-sur-actions-rendues-publiques-depuis-le-1er-novembre-2012"
    try:
        meta=json.loads(get(f"https://www.data.gouv.fr/api/1/datasets/{slug}/"))
        csvs=[r for r in meta.get("resources",[])
              if (r.get("format","") or "").lower()=="csv" or (r.get("url","") or "").lower().endswith(".csv")]
        log(f"[SHF] risorse CSV trovate: {len(csvs)}")
        url=csvs[0]["url"]
        raw=get(url)
        try: df=pd.read_csv(io.StringIO(raw), sep=";", engine="python")
        except Exception: df=pd.read_csv(io.StringIO(raw), sep=None, engine="python")
        df.tail(1000).to_csv("data/short_fr.csv", index=False)
        log(f"[SHF] ok: {min(len(df),1000)} righe ({list(df.columns)[:4]})")
    except Exception as e:
        log(f"[SHF] ERR {e}")

# ---------- 5) SHORT ITALIA (best-effort) ----------
def short_it():
    try:
        h=dict(UA); h["User-Agent"]="Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        req=urllib.request.Request("https://www.consob.it/web/area-pubblica/pnc", headers=h)
        html=urllib.request.urlopen(req,timeout=30).read().decode("utf-8","ignore")
        m=re.search(r'href="([^"]+\.(?:xlsx|xls|csv))"', html, re.I)
        if not m: log("[SHI] link file non trovato (anti-bot) -> consultare via web"); return
        log(f"[SHI] candidato file: {m.group(1)[:70]} (download da validare a mano)")
    except Exception as e:
        log(f"[SHI] ERR {e} -> consultare Consob via web in analisi")

import os
os.makedirs("data", exist_ok=True)
for fn in (insider, thirteenf, cot, short_fr, short_it):
    try: fn()
    except Exception as e: log(f"[FATAL] {fn.__name__}: {e}")
open("data/flows_log.txt","w").write(dt.datetime.utcnow().isoformat()+"Z\n"+"\n".join(LOG))
print("fetch_flows v2 completato")
