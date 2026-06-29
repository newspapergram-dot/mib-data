import pandas as pd
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import os

# === SORGENTE PRIMARIA: Piano C — API JSON pubblica di Yahoo v8 (get_eod_eu_robust) ===
# Scelta come primaria perche' funziona in modo uniforme per US/EU/indici usando UN
# solo host (query1.finance.yahoo.com) e l'endpoint JSON ufficiale. yfinance resta come
# fallback ma richiede host aggiuntivi (es. fc.yahoo.com per cookie/crumb) e fallisce se
# non sono raggiungibili. Ulteriori ripieghi: FMP (US) / catena EU / Borsa Italiana.
try:
    from modules.fmp_source import (get_eod_eu_robust as _eu_robust,
                                     get_eod as _fmp_eod,
                                     get_eod_eu as _fmp_eod_eu,
                                     get_eod_eu_borsait as _eu_borsait)
except Exception:
    _eu_robust = _fmp_eod = _fmp_eod_eu = _eu_borsait = None

try:
    import yfinance as yf
except Exception:
    yf = None

_EU_SUFFIXES = (".MI", ".PA", ".AS", ".L", ".DE")

# ============================================================================
# SESSION GATE — non registrare MAI una barra giornaliera di una sessione ancora
# aperta. Le sorgenti EOD (Yahoo v8 incluso) possono restituire una barra marcata
# con la data di OGGI ma con prezzi intraday/precedenti finche' la borsa non chiude:
# entra cosi' un prezzo "fantasma" (vedi Lezione #20: l'entry stantio del 25/06
# marcato 26/06 nasceva proprio da qui). Il gate scarta l'ultima barra se la
# sessione del SUO mercato non e' ancora chiusa+settled nel fuso locale.
# ============================================================================
_MKT_CLOSE = {            # ora di chiusura ufficiale (ora locale del mercato)
    "Europe/Rome": (17, 30),       # Borsa Italiana / Euronext (.MI/.PA/.AS, CAC, Stoxx)
    "America/New_York": (16, 0),   # NYSE/Nasdaq (azioni USA, ETF, ^GSPC/^NDX/^VIX)
}
_SETTLE_MIN = 20          # margine post-chiusura prima che l'EOD sia considerato definitivo
_EU_INDICES = {"^FCHI", "^STOXX50E"}   # indici EU senza suffisso .MI/.PA


def _market_tz(ticker):
    """Fuso del mercato di quotazione. FTSEMIB.MI cade su .MI (Europe/Rome);
    ^FCHI/^STOXX50E mappati esplicitamente; tutto il resto = USA."""
    if ticker.endswith((".MI", ".PA", ".AS")) or ticker in _EU_INDICES:
        return "Europe/Rome"
    return "America/New_York"


def drop_incomplete_last_bar(df, ticker, now_utc=None):
    """Rimuove l'ultima barra se appartiene a una sessione NON ancora chiusa+settled
    nel fuso del mercato del ticker. Ritorna (df, dropped_date|None).

    Regole:
      - ultima barra di un giorno PASSATO  -> sessione chiusa, si tiene;
      - ultima barra = OGGI (ora locale del mercato) e ora locale < chiusura+settle
        -> barra intraday/incompleta (fantasma): si SCARTA;
      - oltre la chiusura+settle -> EOD definitivo, si tiene.
    Weekend/festivi: non esiste una barra 'oggi', quindi nessuno scarto."""
    if df is None or df.empty:
        return df, None
    tzname = _market_tz(ticker)
    tz = ZoneInfo(tzname)
    now_local = (now_utc or datetime.now(timezone.utc)).astimezone(tz)
    last_date = pd.to_datetime(df["date"].iloc[-1]).date()
    today_local = now_local.date()
    if last_date != today_local:
        return df, None                      # passato (ok) o futuro (non e' il caso d'uso)
    ch, cm = _MKT_CLOSE[tzname]
    settle = now_local.replace(hour=ch, minute=cm, second=0, microsecond=0) \
        + timedelta(minutes=_SETTLE_MIN)
    if now_local < settle:
        return df.iloc[:-1].copy(), last_date   # sessione aperta/non settled -> scarta il fantasma
    return df, None

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
    # ampliamento universo USA (large cap liquide, regime=US)
    "ADBE", "QCOM", "TXN", "ABBV", "PEP",
    "MCD", "ACN", "INTC", "CSCO", "NOW",
    "AMAT", "DIS", "TMO", "ABT", "LIN",

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

_COLS = ["ticker", "date", "open", "high", "low", "close", "volume"]


def _via_yfinance(t, s, e):
    """Fallback yfinance, normalizzato allo schema del repo."""
    if yf is None:
        return None
    try:
        df = yf.download(t, start=s, end=e, interval="1d",
                         auto_adjust=False, progress=False)
    except Exception as ex:
        print(f"[yf] {t}: {repr(ex)[:90]}")
        return None
    if df is None or df.empty:
        return None
    df = df.reset_index()
    df.columns = [c if isinstance(c, str) else c[0] for c in df.columns]  # de-MultiIndex
    df = df.rename(columns={"Date": "date", "Open": "open", "High": "high",
                            "Low": "low", "Close": "close", "Volume": "volume"})
    df["ticker"] = t
    return df[[c for c in _COLS if c in df.columns]]


def fetch_one(t, s, e):
    """Cascata di sorgenti, in ordine di priorita':
       1) Piano C — Yahoo v8 JSON (PRIMARIA)
       2) yfinance
       3) FMP (US) / catena FMP+stooq (EU)
       4) Borsa Italiana (.MI)
    Ritorna un DataFrame normalizzato o None (mai dati fabbricati)."""
    # 1) PRIMARIA
    if _eu_robust is not None:
        df = _eu_robust(t, s, e)
        if df is not None and not df.empty:
            print(f"[OK-PIANO-C] {t}: {len(df)} righe (Yahoo v8 JSON)")
            return df
    # 2) yfinance
    df = _via_yfinance(t, s, e)
    if df is not None and not df.empty:
        print(f"[OK-yfinance] {t}: {len(df)} righe")
        return df
    # 3) FMP / catena EU
    is_eu = t.endswith(_EU_SUFFIXES)
    fn = _fmp_eod_eu if is_eu else _fmp_eod
    df = fn(t, s, e) if fn is not None else None
    if df is not None and not df.empty:
        print(f"[OK-FMP] {t}: {len(df)} righe")
        return df
    # 4) Borsa Italiana (.MI)
    if is_eu and t.endswith(".MI") and _eu_borsait is not None:
        df = _eu_borsait(t)
        if df is not None and not df.empty:
            print(f"[OK-BorsaIT] {t}: {len(df)} righe")
            return df
    return None


if __name__ == "__main__":
    _s, _e = start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
    frames, failed, trimmed = [], [], []
    for t in TICKERS:
        df = fetch_one(t, _s, _e)
        if df is None or df.empty:
            failed.append(t)
            print(f"[WARN] {t}: nessuna sorgente disponibile -> riga OMESSA, non inventata")
            continue
        # SESSION GATE: scarta una eventuale ultima barra di sessione non ancora chiusa
        df, dropped = drop_incomplete_last_bar(df, t)
        if dropped is not None:
            trimmed.append(t)
            print(f"[GATE] {t}: scartata barra intraday {dropped} ({_market_tz(t)} ancora aperto)")
        if df is None or df.empty:
            failed.append(t)
            continue
        frames.append(df)

    if frames:
        out = pd.concat(frames, ignore_index=True)
        for c in ["open", "high", "low", "close", "volume"]:
            out[c] = pd.to_numeric(out[c], errors="coerce")
        out = (out.dropna(subset=["close"])
                  .drop_duplicates(["ticker", "date"])
                  .sort_values(["ticker", "date"]))
        os.makedirs("data", exist_ok=True)
        out.to_csv("data/mib_data.csv", index=False)
        with open("data/last_update.txt", "w") as f:
            f.write(datetime.utcnow().isoformat() + "Z  # fonte primaria: Piano C (Yahoo v8 JSON)")
        print(f"\nScritte {len(out)} righe ({out['ticker'].nunique()} ticker) in data/mib_data.csv")
        if trimmed:
            print(f"Session gate — barre intraday scartate (sessione aperta): {trimmed}")
        if failed:
            print(f"Falliti (omessi): {failed}")
    else:
        print("Nessun dato scaricato; file non aggiornato.")
