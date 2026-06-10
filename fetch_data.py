import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import os

# === MODIFICA QUI LA TUA WATCHLIST (ticker Borsa Italiana, suffisso .MI) ===
TICKERS = [
    "ENI.MI", "ISP.MI", "UCG.MI", "ENEL.MI", "G.MI",
    "STLAM.MI", "RACE.MI", "STMMI.MI", "PRY.MI", "LDO.MI",
]
# ==========================================================================

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
