"""
debate.py — Dibattito strutturato BULL vs BEAR per un candidato.
Ogni argomento e' ancorato a un dato reale della pipeline. Nessun
argomento senza dato a sostegno.

Incorpora regole proprietarie:
  - KILL SWITCH MACRO: earnings/FOMC/BCE entro finestra -> argomento BEAR forte
  - COT SHORT ESTREMO (z<=-1 soft): RSI alto NON e' bear (squeeze regime)
  - CMF(20) / MFI(14): pressione di acquisto/vendita e conferma di volume
"""

def _cot_squeeze_active(cot_rows):
    """True se almeno un mercato indice ha hedge fund z<=-1 (soft squeeze)."""
    for r in cot_rows:
        try:
            if r.get("trader","").lower().startswith("hedge") and float(r.get("zscore",0)) <= -1.0:
                return True, float(r.get("zscore"))
        except (ValueError, TypeError):
            continue
    return False, None

def build_debate(row, patterns=None, volume=None, earnings=None,
                 insider=None, macro_killswitch=False, cot_rows=None):
    """
    row: dict con campi di score_output (ticker, score, rsi, adx, mom6m,
         price, sma50, sma200, segnale_flow...)
    Gli altri sono dict/lookup specifici per quel ticker (o None se assente).
    """
    bull, bear = [], []
    t = row["ticker"]
    rsi = float(row.get("rsi", 50))
    adx = float(row.get("adx", 0))
    mom = float(row.get("mom6m", 0))
    price = float(row.get("price", 0))
    sma50 = float(row.get("sma50", 0))
    sma200 = float(row.get("sma200", 0))
    squeeze, cot_z = _cot_squeeze_active(cot_rows or [])

    # ---- ARGOMENTI BULL ----
    if adx >= 40:
        bull.append(f"Trend FORTE confermato: ADX reale {adx:.0f} (>=40, soglia validata nel backtest)")
    elif adx >= 25:
        bull.append(f"Trend in atto: ADX {adx:.0f} (>25)")
    if price > sma50 > sma200 and sma200 > 0:
        bull.append(f"Struttura rialzista pulita: prezzo>SMA50>SMA200 ({price:.2f}>{sma50:.2f}>{sma200:.2f})")
    if mom > 15:
        bull.append(f"Momentum 6m forte: +{mom:.1f}%")
    if patterns:
        if str(patterns.get("breakout","")).strip() not in ("","False","nan"):
            bull.append(f"Breakout segnalato dai pattern: {patterns.get('breakout')}")
        cont = str(patterns.get("continuation","")).strip()
        if cont and cont not in ("nan","False"):
            parts = [c.strip() for c in cont.split("|") if c.strip()]
            if parts:
                bull.append(f"Pattern di continuazione: {parts[0]}")
    if insider and str(insider.get("signal","")) == "1":
        bull.append("Insider buying / cluster buy rilevato (Form 4)")
    try:
        if float(row.get("segnale_flow", 0)) >= 0.4:
            bull.append(f"Flow istituzionale a favore: segnale_flow {row.get('segnale_flow')}")
    except (ValueError, TypeError):
        pass
    if rsi >= 65 and squeeze:
        bull.append(f"RSI {rsi:.0f} alto MA COT short estremo (z={cot_z:.1f}): in squeeze e' pro-trend, non overbought")
    # --- NUOVO: CMF e MFI lato bull ---
    if volume:
        try:
            cmf = float(volume.get("cmf20",""))
            if cmf >= 0.10:
                bull.append(f"CMF(20) a {cmf:+.2f}: pressione di acquisto netta nell'ultimo mese")
        except (ValueError, TypeError):
            pass
        try:
            mfi = float(volume.get("mfi14",""))
            if mfi >= rsi + 10:
                bull.append(f"MFI {mfi:.0f} sopra RSI {rsi:.0f}: il volume confema la forza del prezzo")
        except (ValueError, TypeError):
            pass

    # ---- ARGOMENTI BEAR ----
    if macro_killswitch:
        bear.append("KILL SWITCH MACRO ATTIVO (FOMC/BCE entro 2 settimane): la tua regola dice NO nuovi swing")
    if earnings and str(earnings.get("earnings_within_N","")) in ("True","1","true"):
        bear.append(f"Earnings imminenti ({earnings.get('next_earnings_date')}): rischio gap, evita swing")
    if volume and str(volume.get("volume_reliable","")) not in ("True","true","1"):
        bear.append(f"Volume NON affidabile ({volume.get('reason')}): breakout non confermabile")
    if adx < 20:
        bear.append(f"Trend assente/debole: ADX {adx:.0f} (<20) - rischio falso segnale, fai whipsaw")
    if price < sma50 and sma50 > 0:
        bear.append(f"Prezzo sotto SMA50 ({price:.2f}<{sma50:.2f}): momentum di breve negativo")
    if rsi >= 70 and not squeeze:
        bear.append(f"RSI {rsi:.0f} in ipercomprato (no regime squeeze a compensare)")
    if rsi <= 30:
        bear.append(f"RSI {rsi:.0f} molto basso: possibile debolezza, non solo 'sconto'")
    if patterns:
        div = str(patterns.get("rsi_divergence","")).lower()
        if "bearish" in div:
            bear.append(f"Divergenza RSI ribassista: {patterns.get('rsi_divergence')}")
    if insider and str(insider.get("signal","")) == "-1":
        bear.append(f"Insider SELLING (Form 4): {insider.get('sell_insiders')} venditori, valore {insider.get('sell_value')}")
    # --- NUOVO: CMF e MFI lato bear ---
    if volume:
        try:
            cmf = float(volume.get("cmf20",""))
            if cmf <= -0.10:
                bear.append(f"CMF(20) a {cmf:+.2f}: pressione di vendita netta nell'ultimo mese")
        except (ValueError, TypeError):
            pass
        try:
            mfi = float(volume.get("mfi14",""))
            if mfi <= rsi - 10:
                bear.append(f"MFI {mfi:.0f} sotto RSI {rsi:.0f}: il rialzo di prezzo non e' confermato dal volume")
        except (ValueError, TypeError):
            pass

    # ---- VERDETTO ----
    veto = macro_killswitch or (earnings and str(earnings.get("earnings_within_N","")) in ("True","1","true"))
    nb, nr = len(bull), len(bear)
    if veto:
        verdict = "ASTIENI (veto: evento macro/earnings) - rivedi a finestra chiusa"
        conf = "N/A (veto)"
    elif nb >= nr + 2:
        verdict = "FAVOREVOLE - i pro dominano e sono ancorati a dati"
        conf = "ALTA" if (adx>=40 and nb>=4) else "MEDIA"
    elif nr >= nb + 1:
        verdict = "SFAVOREVOLE - i contro pesano piu' dei pro"
        conf = "BASSA"
    else:
        verdict = "INCERTO - pro e contro bilanciati, serve discrezione"
        conf = "MEDIA"

    return {"ticker": t, "score": row.get("score"), "bull": bull, "bear": bear,
            "verdict": verdict, "confidence": conf, "squeeze_regime": squeeze}

def render_debate(d):
    out = []
    out.append("="*60)
    out.append(f" DIBATTITO: {d['ticker']}  (score {d['score']})")
    if d["squeeze_regime"]:
        out.append(" [regime COT short estremo attivo -> filtro RSI ammorbidito]")
    out.append("="*60)
    out.append(" TESI RIALZISTA (BULL):")
    if d["bull"]:
        for b in d["bull"]: out.append(f"   + {b}")
    else:
        out.append("   (nessun argomento rialzista ancorato a dati)")
    out.append("")
    out.append(" TESI RIBASSISTA (BEAR):")
    if d["bear"]:
        for b in d["bear"]: out.append(f"   - {b}")
    else:
        out.append("   (nessun argomento ribassista ancorato a dati)")
    out.append("")
    out.append(f" VERDETTO: {d['verdict']}")
    out.append(f" CONFIDENZA: {d['confidence']}")
    out.append("="*60)
    return "\n".join(out)
