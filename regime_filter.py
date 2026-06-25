"""
regime_filter.py — Rilevatore di regime di mercato (FRENO, non selettore).

Classifica ogni mercato di riferimento (Milano, Parigi, USA) in uno di tre
regimi e restituisce un MOLTIPLICATORE DI RISCHIO che modula l'aggressivita'
della strategia breakout, SENZA cambiarla.

Filosofia: la strategia breakout+ADX e' validata solo in trend rialzista.
Quando il regime NON e' favorevole, il sistema NON inventa una strategia
diversa (non validata) — semplicemente si fa piu' piccolo o si ferma.

  Regime          Moltiplicatore   Significato operativo
  -----------     -------------    ---------------------------------------
  TREND_UP        1.00             pieno: la strategia opera normalmente
  LATERALE        0.50             dimezza il sizing: breakout meno affidabili
  TREND_DOWN      0.00             stop: non aprire long, regime ostile

Classificazione basata su 3 condizioni dell'indice (nessun parametro magico,
tutte derivate da medie mobili standard gia' usate nel resto del sistema):
  - prezzo vs SMA50 e SMA200
  - pendenza della SMA50 sulle ultime 20 sedute

Mappa mercato -> indice di riferimento (ticker presenti in mib_data.csv):
  Italia  -> FTSEMIB.MI
  Francia -> ^FCHI
  USA     -> ^GSPC (S&P 500)
"""
import pandas as pd
import numpy as np

INDEX_BY_MARKET = {
    "IT": "FTSEMIB.MI",
    "FR": "^FCHI",
    "US": "^GSPC",
}

# Suffisso/forma del ticker -> mercato di appartenenza
def market_of(ticker):
    if ticker.endswith(".MI"):
        return "IT"
    if ticker.endswith(".PA") or ticker.endswith(".AS"):
        return "FR"   # CAC/Euronext continentale: usiamo il CAC come proxy
    return "US"       # default: azioni USA e ETF settoriali


def classify_regime(df_index, slope_window=20, flat_slope=1.0):
    """
    df_index: DataFrame OHLCV dell'INDICE (colonne: date, close), ordinabile.
    flat_slope: soglia in % sotto la quale la pendenza SMA50 e' considerata piatta.

    Ritorna dict: {regime, risk_mult, detail}
    """
    d = df_index.sort_values("date").copy()
    if len(d) < 200:
        # storia insufficiente: prudenza, mezzo rischio
        return {"regime": "INSUFF_DATA", "risk_mult": 0.5,
                "detail": f"solo {len(d)} sedute (<200)"}

    d["sma50"] = d["close"].rolling(50).mean()
    d["sma200"] = d["close"].rolling(200).mean()
    px = d["close"].iloc[-1]
    s50 = d["sma50"].iloc[-1]
    s200 = d["sma200"].iloc[-1]
    slope50 = (d["sma50"].iloc[-1] / d["sma50"].iloc[-(slope_window + 1)] - 1) * 100

    above50 = px > s50
    above200 = px > s200
    rising = slope50 > flat_slope
    falling = slope50 < -flat_slope

    if above50 and above200 and rising:
        regime, mult = "TREND_UP", 1.00
    elif (not above200) and falling:
        regime, mult = "TREND_DOWN", 0.00
    else:
        regime, mult = "LATERALE", 0.50

    return {"regime": regime, "risk_mult": mult,
            "detail": f"px{'>' if above50 else '<'}SMA50, "
                      f"px{'>' if above200 else '<'}SMA200, "
                      f"slope50_{slope_window}g={slope50:+.2f}%"}


def regime_table(px_all, out_path="data/regime_filter.csv"):
    """
    px_all: DataFrame con tutti i ticker (colonne ticker, date, close...).
    Classifica i 3 mercati e scrive un CSV con regime e moltiplicatore.
    Ritorna un dict {mercato: classify_regime(...)} riutilizzabile in altri moduli.
    """
    import os
    result = {}
    rows = []
    for mkt, idx in INDEX_BY_MARKET.items():
        sub = px_all[px_all["ticker"] == idx]
        if sub.empty:
            result[mkt] = {"regime": "NO_INDEX", "risk_mult": 0.5,
                           "detail": f"indice {idx} assente"}
        else:
            result[mkt] = classify_regime(sub)
        r = result[mkt]
        rows.append({"market": mkt, "index": idx, "regime": r["regime"],
                     "risk_mult": r["risk_mult"], "detail": r["detail"]})
    if out_path:
        out = pd.DataFrame(rows)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        out.to_csv(out_path, index=False)
        print("[regime] " + " | ".join(f"{r['market']}:{r['regime']}(x{r['risk_mult']})" for r in rows)
              + f" -> {out_path}")
    return result


def risk_mult_for_ticker(ticker, regime_result):
    """
    Comodo helper: dato un ticker e il dict prodotto da regime_table(),
    ritorna il moltiplicatore di rischio del SUO mercato.
    Da usare in trade_proposal.propose() per modulare il sizing:
        risk_per_trade_effettivo = risk_per_trade * risk_mult_for_ticker(...)
    """
    mkt = market_of(ticker)
    return regime_result.get(mkt, {}).get("risk_mult", 0.5)


if __name__ == "__main__":
    import os
    # Sorgente: il file LOCALE appena rigenerato da fetch_data.py. Usare il file
    # locale (invece di scaricarlo da raw.githubusercontent/main) e' (1) robusto
    # — niente download da 3.5MB che si tronca (IncompleteRead) — e (2) corretto:
    # classifica il regime sui dati FRESCHI della pipeline, non sulla copia stale
    # del branch main. Il download remoto resta solo come fallback estremo.
    local = "data/mib_data.csv"
    if os.path.exists(local):
        px = pd.read_csv(local)
        print(f"[regime] sorgente: {local} (locale, fresco)")
    else:
        import urllib.request, io
        base = "https://raw.githubusercontent.com/newspapergram-dot/mib-data/refs/heads/main/data/"
        print("[regime] file locale assente -> fallback download da main")
        px = pd.read_csv(io.StringIO(
            urllib.request.urlopen(base + "mib_data.csv", timeout=60).read().decode("utf-8", "replace")))
    res = regime_table(px)
    print()
    for mkt, r in res.items():
        print(f"  {mkt}: {r['regime']}  (rischio x{r['risk_mult']})  — {r['detail']}")
