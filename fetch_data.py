import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import os

# Fallback FMP: usato quando yfinance non restituisce dati (es. proxy che
# blocca Yahoo con HTTP 403). Richiede FMP_API_KEY; se assente resta no-op.
try:
    from modules.fmp_source import (get_eod as _fmp_eod,
                                     get_eod_eu as _fmp_eod_eu,
                                     get_eod_eu_robust as _eu_robust,
                                     get_eod_eu_borsait as _eu_borsait)
except Exception:
    _fmp_eod = None
    _fmp_eod_eu = None
    _eu_robust = None
    _eu_borsait = None

_EU_SUFFIXES = (".MI", ".PA", ".AS", ".L", ".DE")

# === MODIFICA QUI LA TUA WATCHLIST ===
TICKERS = [
    # --- FTSE MIB (.MI) ---
    "A2A.MI", "AMP.MI", "AZM.MI", "BMED.MI", "BMPS.MI",
    "BAMI.MI", "BPE.MI", "BC.MI", "BZU.MI", "CPR.MI",
    "DIA.MI", "ENEL.MI", "ENI.MI", "RACE.MI", "FBK.MI",
    "G.MI", "HER.MI", "IP.MI", "ISP.MI", "INW.MI",
    "IVG.MI", "LDO.MI", "MB.MI", "MONC.MI", "NEXI.MI",
    "PIRC.MI", "PST.MI", "PRY.MI", "REC.MI", "SPM.MI",
    "SRG.MI", "STLAM.MI", "STMMI.MI", "TIT.MI", "TEN.MI",
    "TRN.MI", "UCG.MI", "UNI.MI", "BPSO.MI", "LTMC.MI",

    # --- CAC 40 (.PA) ---
    "AC.PA", "AI.PA", "AIR.PA", "MT.AS", "CS.PA",
    "BNP.PA", "EN.PA", "CAP.PA", "CA.PA", "ACA.PA",
    "BN.PA", "DSY.PA", "EDEN.PA", "ENGI.PA", "EL.PA",
    "ERF.PA", "RMS.PA", "KER.PA", "LR.PA", "OR.PA",
    "MC.PA", "ML.PA", "ORA.PA", "RI.PA", "PUB.PA",
    "RNO.PA", "SAF.PA", "SGO.PA", "SAN.PA", "SU.PA",
    "GLE.PA", "STLAP.PA", "STMPA.PA", "TEP.PA", "HO.PA",
    "TTE.PA", "VIE.PA", "DG.PA", "VIV.PA", "WLN.PA",

    # --- USA mega/large cap liquide ---
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN",
    "META", "AVGO", "TSLA", "LLY", "JPM",
    "V", "UNH", "XOM", "COST", "HD",
    "PG", "JNJ", "ORCL", "BAC", "NFLX",
    "AMD", "CRM", "KO", "CVX", "MRK",
    "WMT", "PLTR", "GE", "CAT", "GS",

    # --- Indici e regime (gratis via Yahoo) ---
    "^GSPC", "^NDX", "^VIX", "FTSEMIB.MI", "^FCHI", "^STOXX50E",
    
    # --- ETF settoriali USA (proxy rotazione istituzionale) ---
    "SPY", "XLF", "XLE", "XLK", "XLV", "XLY",
    "XLP", "XLU", "XLI", "XLB", "XLRE", "XLC",
]
# ======================================
MONTHS_BACK = 14
end = datetime.today()
start = end - timedelta(days=MONTHS_BACK * 31)

frames = []
for t in TICKERS:
    try:
        df = yf.download(
            t,
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            interval="1d",
            auto_adjust=False,
            progress=False,
        )
        if df is None or df.empty:
            # Cascata di fallback quando Yahoo (yfinance) non risponde (es. proxy 403).
            _s, _e = start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
            _is_eu = t.endswith(_EU_SUFFIXES)
            # Piano A (FMP nativo) + Piano B (stooq) per gli EU; FMP per il resto.
            _fb_fn = _fmp_eod_eu if _is_eu else _fmp_eod
            fb = _fb_fn(t, _s, _e) if _fb_fn is not None else None
            if (fb is None or fb.empty) and _is_eu and _eu_robust is not None:
                # Piano C: API pubblica JSON di Yahoo con header da browser reale.
                fb = _eu_robust(t, _s, _e)
                if fb is not None and not fb.empty:
                    print(f"[OK-PIANO-C] {t}: {len(fb)} righe (Yahoo JSON robust)")
            if (fb is None or fb.empty) and _is_eu and _eu_borsait is not None and t.endswith(".MI"):
                # Piano D: scheda pubblica Borsa Italiana (solo titoli .MI, indicizzata per ISIN).
                fb = _eu_borsait(t)
                if fb is not None and not fb.empty:
                    print(f"[OK-PIANO-D] {t}: {len(fb)} righe (Borsa Italiana)")
            if fb is not None and not fb.empty:
                frames.append(fb)
                print(f"[OK-FALLBACK] {t}: {len(fb)} righe")
                continue
            # Nessun piano ha funzionato: avviso CHIARO, nessun dato fabbricato.
            print(f"[WARN] {t}: nessun dato (yfinance/FMP/stooq/Yahoo-robust tutti falliti) "
                  f"-> riga OMESSA, non inventata")
            continue
        df = df.reset_index()
        # yfinance a volte restituisce colonne MultiIndex: normalizziamole
        df.columns = [c if isinstance(c, str) else c[0] for c in df.columns]
        df = df.rename(columns={
            "Date": "date", "Open": "open", "High": "high",
            "Low": "low", "Close": "close", "Volume": "volume",
        })
        df["ticker"] = t
        frames.append(df[["ticker", "date", "open", "high", "low", "close", "volume"]])
        print(f"[OK] {t}: {len(df)} righe")
    except Exception as e:
        print(f"[ERR] {t}: {e}")

if frames:
    out = pd.concat(frames, ignore_index=True)
    out = out.dropna(subset=["close"]) 
    os.makedirs("data", exist_ok=True)
    out.to_csv("data/mib_data.csv", index=False)
    with open("data/last_update.txt", "w") as f:
        f.write(datetime.utcnow().isoformat() + "Z")
    print(f"Scritte {len(out)} righe totali in data/mib_data.csv")
else:
    print("Nessun dato scaricato; file non aggiornato.")
