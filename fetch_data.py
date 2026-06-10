import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import os

# === MODIFICA QUI LA TUA WATCHLIST ===
TICKERS = [
    # --- FTSE MIB (Borsa Italiana, .MI) ---
    "A2A.MI", "AMP.MI", "AZM.MI", "BMED.MI", "BMPS.MI",
    "BAMI.MI", "BPE.MI", "BC.MI", "BZU.MI", "CPR.MI",
    "DIA.MI", "ENEL.MI", "ENI.MI", "RACE.MI", "FBK.MI",
    "G.MI", "HER.MI", "IP.MI", "ISP.MI", "INW.MI",
    "IVG.MI", "LDO.MI", "MB.MI", "MONC.MI", "NEXI.MI",
    "PIRC.MI", "PST.MI", "PRY.MI", "REC.MI", "SPM.MI",
    "SRG.MI", "STLAM.MI", "STMMI.MI", "TIT.MI", "TEN.MI",
    "TRN.MI", "UCG.MI", "UNI.MI", "BPSO.MI", "LTMC.MI",

    # --- CAC 40 (Euronext Paris, .PA) ---
    "AC.PA", "AI.PA", "AIR.PA", "MT.PA", "CS.PA",
    "BNP.PA", "EN.PA", "CAP.PA", "CA.PA", "ACA.PA",
    "BN.PA", "DSY.PA", "EDEN.PA", "ENGI.PA", "EL.PA",
    "ERF.PA", "RMS.PA", "KER.PA", "LR.PA", "OR.PA",
    "MC.PA", "ML.PA", "ORA.PA", "RI.PA", "PUB.PA",
    "RNO.PA", "SAF.PA", "SGO.PA", "SAN.PA", "SU.PA",
    "GLE.PA", "STLAP.PA", "STMPA.PA", "TEP.PA", "HO.PA",
    "TTE.PA", "VIE.PA", "DG.PA", "VIV.PA", "WLN.PA",
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
            print(f"[WARN] Nessun dato per {t}")
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
    os.makedirs("data", exist_ok=True)
    out.to_csv("data/mib_data.csv", index=False)
    with open("data/last_update.txt", "w") as f:
        f.write(datetime.utcnow().isoformat() + "Z")
    print(f"Scritte {len(out)} righe totali in data/mib_data.csv")
else:
    print("Nessun dato scaricato; file non aggiornato.")
