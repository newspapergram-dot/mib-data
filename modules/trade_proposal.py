"""
trade_proposal.py — Motore di proposta operativa per copilota investitore.
Trasforma un candidato dello score in una scheda operativa completa con:
  - potenziale guadagno NETTO (costi realistici per fascia di liquidità)
  - position sizing quarter-Kelly (conservativo, calibrato su campione bull-only)
  - stop/target basati su statistica della strategia + ATR
  - tesi pro/contro esplicite e livello di confidenza onesto
Parametri di edge dal backtest validato (NUOVO score, orizzonte 5gg).
NB: calibrato su 18 settimane di solo bull market -> trattare come PRUDENZIALE.

AGGIORNAMENTO: aggiunto regime_mult, il freno del regime di mercato
(regime_filter.py). Modula sia il rischio per trade sia il cap di valore
della posizione: x1.0 trend favorevole, x0.5 laterale, x0.0 regime ostile
(nessuna posizione apribile).
"""
import numpy as np

# --- Parametri di edge dal backtest (NUOVO score, 5gg, costi reali) ---
EDGE = {
    "win_rate": 0.744,
    "avg_win_pct": 4.11,
    "avg_loss_pct": 5.10,
    "payoff": 0.81,
    "kelly_full": 0.428,
    "sharpe_point": 3.79,
    "sharpe_ci95": (1.14, 9.65),   # intervallo bootstrap: onestà sulla precisione
    "n_weeks": 18,
    "regime": "BULL ONLY (gen-mag 2026) - nessun bear testato",
}

MEGA = {'ENEL.MI','ENI.MI','ISP.MI','UCG.MI','STMMI.MI','UNI.MI','TIT.MI','G.MI','AI.PA','AIR.PA','MT.AS','XLC'}
ILLIQUID = {'A2A.MI','BPSO.MI','IVG.MI','LTMC.MI','BMED.MI','AZM.MI','HER.MI','BZU.MI','PIRC.MI',
            'PST.MI','IP.MI','CPR.MI','BMPS.MI','BAMI.MI','FBK.MI','SRG.MI','TRN.MI'}

def cost_rt_bps(ticker):
    """Costo round-trip in % (spread+slippage stimati per fascia di liquidità)."""
    per_side = 0.10 if ticker in MEGA else (0.35 if ticker in ILLIQUID else 0.20)
    return per_side * 2

def confidence_level(score, ticker):
    """Confidenza onesta: alta richiede score forte E titolo liquido."""
    if ticker in ILLIQUID:
        return "BASSA"  # costi alti + raramente selezionato nel backtest
    if score >= 0.45:
        return "ALTA"
    if score >= 0.20:
        return "MEDIA"
    return "BASSA"

def propose(ticker, entry, atr14, score, capital,
            risk_per_trade=0.0214, atr_mult_stop=2.0, n_positions=5,
            regime_mult=1.0):
    """
    Genera la scheda operativa per un singolo candidato.
    entry: prezzo di ingresso previsto (es. apertura lunedi)
    atr14: ATR(14) corrente del titolo (in valuta)
    score: score NUOVO del candidato
    capital: capitale totale del portafoglio
    regime_mult: moltiplicatore di rischio dal regime di mercato (regime_filter.py).
                 1.0 = trend favorevole, 0.5 = laterale, 0.0 = regime ostile (stop).
    """
    cost = cost_rt_bps(ticker)
    # STOP guidato dalla STATISTICA della strategia (non da regola R/R generica):
    # il backtest mostra che troncare le perdite a ~-5% porta il payoff da 0.81 a 1.20.
    # Si usa il piu' STRETTO tra: (a) cap statistico -5%, (b) stop tecnico ATR.
    stop_stat = entry * (1 - 0.05)                 # cap perdita statistico
    stop_atr  = entry - atr_mult_stop * atr14      # stop tecnico ATR
    stop = max(stop_stat, stop_atr)                # il piu' vicino all'entry = piu' protettivo
    risk_per_share = entry - stop
    # Target coerenti con avg_win storico troncato (~4.1%) e estensione
    t1 = entry * (1 + EDGE["avg_win_pct"]/100)
    t2 = entry * (1 + 2*EDGE["avg_win_pct"]/100)
    rr1 = (t1-entry)/risk_per_share if risk_per_share>0 else float("nan")
    rr2 = (t2-entry)/risk_per_share if risk_per_share>0 else float("nan")

    # Sizing: rischio fisso per trade, MODULATO dal regime di mercato (freno).
    # regime_mult: 1.0 trend favorevole | 0.5 laterale | 0.0 regime ostile (stop).
    risk_eur = capital * risk_per_trade * regime_mult
    shares = int(risk_eur / risk_per_share) if risk_per_share > 0 else 0
    pos_value = shares * entry
    max_pos_value = capital * 0.10 * regime_mult   # cap 10% modulato dal regime
    binding = ""
    if pos_value > max_pos_value:
        shares = int(max_pos_value / entry) if entry > 0 else 0
        pos_value = shares * entry
        binding = " (capped a 10% portafoglio)"

    # Guadagno atteso NETTO probabilistico
    gross_exp = EDGE["win_rate"]*EDGE["avg_win_pct"] - (1-EDGE["win_rate"])*EDGE["avg_loss_pct"]
    net_exp = gross_exp - cost
    eur_exp = pos_value * net_exp/100

    conf = confidence_level(score, ticker)
    return {
        "ticker": ticker, "score": score, "confidence": conf,
        "entry": entry, "stop": round(stop,4), "t1": round(t1,4), "t2": round(t2,4),
        "rr1": round(rr1,2), "rr2": round(rr2,2),
        "shares": shares, "pos_value": round(pos_value,2), "pos_pct": round(pos_value/capital*100,1),
        "risk_eur": round(shares*risk_per_share,2), "cost_pct": cost,
        "net_exp_pct": round(net_exp,2), "eur_exp": round(eur_exp,2), "binding": binding,
        "regime_mult": regime_mult,
    }

def render(p):
    """Formatta la scheda nel formato memo operativo."""
    out = []
    out.append("="*58)
    out.append(f" {p['ticker']}  |  Score: {p['score']:.3f}  |  CONFIDENZA: {p['confidence']}")
    out.append("="*58)
    out.append(f" Entry: {p['entry']:.4f}   Stop: {p['stop']:.4f}")
    out.append(f" Target 1: {p['t1']:.4f} (R/R {p['rr1']}:1)   Target 2: {p['t2']:.4f} (R/R {p['rr2']}:1)")
    out.append("")
    out.append(f" Regime di mercato: moltiplicatore rischio x{p['regime_mult']}")
    out.append(f" SIZING:  {p['shares']} azioni = {p['pos_value']:.0f}EUR ({p['pos_pct']}% portaf.){p['binding']}")
    out.append(f"          Rischio massimo posizione: {p['risk_eur']:.0f}EUR")
    out.append("")
    out.append(f" GUADAGNO ATTESO (netto costi {p['cost_pct']:.2f}%): {p['net_exp_pct']:+.2f}% = {p['eur_exp']:+.0f}EUR")
    out.append("")
    out.append(" PRO:  edge misurato su orizzonte 5gg (il tuo); win rate storico 74%")
    out.append(" CONTRO: payoff <1 (perdite medie > vincite medie) -> stop NON negoziabile")
    out.append("         edge validato solo in regime BULL; Sharpe CI95 [1.1-9.6] = stima imprecisa")
    if p['confidence']=="BASSA":
        out.append("         !! confidenza BASSA: titolo illiquido o score debole -> valuta lo skip")
    if p['regime_mult'] < 1.0:
        out.append(f"         !! regime di mercato non pienamente favorevole: sizing ridotto a x{p['regime_mult']}")
    out.append("="*58)
    return "\n".join(out)

if __name__ == "__main__":
    # Demo con numeri di esempio (entry/ATR vanno presi dai dati EOD reali)
    print(render(propose("STMMI.MI", entry=30.0, atr14=0.95, score=0.43, capital=50000)))
    print()
    print(render(propose("BPSO.MI", entry=12.5, atr14=0.40, score=0.53, capital=50000, regime_mult=0.5)))
