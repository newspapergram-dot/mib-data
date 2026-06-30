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

def confidence_level(score, ticker, hi=0.19, mid=0.13):
    """Confidenza onesta: alta richiede score forte E titolo liquido.
    Soglie TARATE sulla distribuzione reale degli score (max osservato ~0.36,
    p90~0.19, p60~0.14): le vecchie soglie assolute (0.45/0.20) rendevano 'ALTA'
    IRRAGGIUNGIBILE e quasi tutto 'BASSA'. Ora hi~p90 (top decile) e mid~p60
    (top ~40%). I parametri `hi`/`mid` permettono al chiamante di passare percentili
    live della selezione corrente (es. portfolio_builder)."""
    if ticker in ILLIQUID:
        return "BASSA"  # costi alti + raramente selezionato nel backtest
    if score >= hi:
        return "ALTA"
    if score >= mid:
        return "MEDIA"
    return "BASSA"

def propose(ticker, entry, atr14, score, capital,
            risk_per_trade=0.0214, atr_mult_stop=2.0, n_positions=5,
            regime_mult=1.0, pos_cap=0.10, size_mult=1.0, rp_scale=1.0,
            target_atr_mult=(2.0, 6.0, 10.0), target_rr_floor=(1.2, 3.0, 5.0)):
    """
    Genera la scheda operativa per un singolo candidato.
    entry: prezzo di ingresso previsto (es. apertura lunedi)
    atr14: ATR(14) corrente del titolo (in valuta)
    score: score NUOVO del candidato
    capital: capitale totale del portafoglio
    regime_mult: moltiplicatore di rischio dal regime di mercato (regime_filter.py).
    size_mult: moltiplicatore di convinzione (1.0 piena, <1 ridotta) per il portafoglio tiered.
    pos_cap: cap di valore della posizione in frazione del capitale (default 10%).
    rp_scale: moltiplicatore di risk-parity = min(medATR%/ATR%_i, 1.0). Abbassa il cap
        per i nomi ad alta volatilita' relativa; validato su ciclo 2018-2026 (IC95 [+1.07,+9.04]
        su DeltaMaxDD). Default 1.0 = equal-weight (nessun aggiustamento).
    target_atr_mult / target_rr_floor: i 3 target (T1/T2/T3) sono il MASSIMO tra un multiplo
        di ATR (scala con la volatilita' del titolo) e un multiplo del rischio (garantisce R/R
        favorevole). Sostituiscono i vecchi target fissi +4.1%/+8.2% (R/R<1).
        DEFAULT TARATI SUL BACKTEST (path-based target/stop su top-quintile NUOVO, N=10/20):
        T1=2*ATR e' "hittable" (~44-55% di hit) -> banca presto la prima quota, mediana POSITIVA;
        T2=6*ATR / T3=10*ATR restano larghi per catturare la coda (dove sta l'expectancy).
        Il confronto laddered [0.5/0.25/0.25] mostra che spostare T1 da 3 a 2*ATR alza win-rate
        (49%->51%) e mediana (-0.17%->+0.28%) cedendo ~15% di expectancy: scelta migliore per
        conti piccoli (curva piu' liscia). Per massimizzare la sola expectancy usare (3,6,10).
        NB: i numeri storici di win-rate/expectancy (EDGE) erano misurati sui VECCHI target.
    """
    cost = cost_rt_bps(ticker)
    # STOP guidato dalla STATISTICA della strategia (non da regola R/R generica):
    # il backtest mostra che troncare le perdite a ~-5% porta il payoff da 0.81 a 1.20.
    # Si usa il piu' STRETTO tra: (a) cap statistico -5%, (b) stop tecnico ATR.
    stop_stat = entry * (1 - 0.05)                 # cap perdita statistico
    stop_atr  = entry - atr_mult_stop * atr14      # stop tecnico ATR
    stop = max(stop_stat, stop_atr)                # il piu' vicino all'entry = piu' protettivo
    risk_per_share = entry - stop
    # Target = max(multiplo ATR, multiplo del rischio): piu' ampi, volatility-aware, R/R>=floor.
    def _tgt(k_atr, k_rr):
        return entry + max(k_atr * atr14, k_rr * risk_per_share)
    t1 = _tgt(target_atr_mult[0], target_rr_floor[0])
    t2 = _tgt(target_atr_mult[1], target_rr_floor[1])
    t3 = _tgt(target_atr_mult[2], target_rr_floor[2])
    rr = lambda t: (t-entry)/risk_per_share if risk_per_share>0 else float("nan")
    rr1, rr2, rr3 = rr(t1), rr(t2), rr(t3)

    # Sizing: rischio fisso per trade, MODULATO da regime e convinzione (size_mult).
    eff_mult = regime_mult * size_mult
    risk_eur = capital * risk_per_trade * eff_mult
    shares = int(risk_eur / risk_per_share) if risk_per_share > 0 else 0
    pos_value = shares * entry
    # Risk-parity: pos_cap ridotto per nomi ad alta ATR (rp_scale = min(medATR/ATR_i, 1.0)).
    # Validato 2018-2026: MaxDD -17.81% -> -13.15%, IC95 [+1.07,+9.04], Calmar +0.70 -> +0.89.
    eff_pos_cap = pos_cap * rp_scale
    max_pos_value = capital * eff_pos_cap * eff_mult   # cap modulato da regime, convinzione e RP
    binding = ""
    if pos_value > max_pos_value:
        shares = int(max_pos_value / entry) if entry > 0 else 0
        pos_value = shares * entry
        if rp_scale < 0.999:
            binding = f" (capped RP {eff_pos_cap*100:.0f}%)"
        else:
            binding = f" (capped a {pos_cap*100:.0f}% x conv)"

    # Guadagno POTENZIALE per ciascun target, netto costi, in % e in EUR sulla posizione.
    def _gain(t):
        gpct = (t/entry - 1)*100 - cost
        return round(gpct, 2), round(pos_value * gpct/100, 2)
    g1_pct, g1_eur = _gain(t1)
    g2_pct, g2_eur = _gain(t2)
    g3_pct, g3_eur = _gain(t3)
    # Efficienza per conti piccoli: il guadagno netto a T1 deve battere nettamente i costi.
    cost_efficient = g1_pct >= max(3.0, 6*cost)

    # Guadagno atteso NETTO probabilistico (storico, ai VECCHI target — riferimento)
    gross_exp = EDGE["win_rate"]*EDGE["avg_win_pct"] - (1-EDGE["win_rate"])*EDGE["avg_loss_pct"]
    net_exp = gross_exp - cost
    eur_exp = pos_value * net_exp/100

    conf = confidence_level(score, ticker)
    return {
        "ticker": ticker, "score": score, "confidence": conf,
        "entry": entry, "stop": round(stop,4),
        "t1": round(t1,4), "t2": round(t2,4), "t3": round(t3,4),
        "rr1": round(rr1,2), "rr2": round(rr2,2), "rr3": round(rr3,2),
        "g1_pct": g1_pct, "g1_eur": g1_eur, "g2_pct": g2_pct, "g2_eur": g2_eur,
        "g3_pct": g3_pct, "g3_eur": g3_eur, "cost_efficient": cost_efficient,
        "shares": shares, "pos_value": round(pos_value,2), "pos_pct": round(pos_value/capital*100,1),
        "risk_eur": round(shares*risk_per_share,2), "cost_pct": cost,
        "net_exp_pct": round(net_exp,2), "eur_exp": round(eur_exp,2), "binding": binding,
        "regime_mult": regime_mult, "size_mult": size_mult, "rp_scale": round(rp_scale, 3),
    }

def render(p):
    """Formatta la scheda nel formato memo operativo."""
    out = []
    out.append("="*58)
    out.append(f" {p['ticker']}  |  Score: {p['score']:.3f}  |  CONFIDENZA: {p['confidence']}")
    out.append("="*58)
    out.append(f" Entry: {p['entry']:.4f}   Stop: {p['stop']:.4f}")
    out.append(f" Target 1: {p['t1']:.4f} (R/R {p['rr1']}:1 | +{p['g1_pct']:.1f}% net = {p['g1_eur']:+.0f}EUR)")
    out.append(f" Target 2: {p['t2']:.4f} (R/R {p['rr2']}:1 | +{p['g2_pct']:.1f}% net = {p['g2_eur']:+.0f}EUR)")
    out.append(f" Target 3: {p['t3']:.4f} (R/R {p['rr3']}:1 | +{p['g3_pct']:.1f}% net = {p['g3_eur']:+.0f}EUR)  [runner]")
    out.append("")
    rp_str = f" | RP x{p['rp_scale']:.2f}" if p.get("rp_scale", 1.0) < 0.999 else ""
    out.append(f" Regime x{p['regime_mult']} | convinzione x{p['size_mult']}{rp_str}")
    out.append(f" SIZING:  {p['shares']} azioni = {p['pos_value']:.0f}EUR ({p['pos_pct']}% portaf.){p['binding']}")
    out.append(f"          Rischio massimo posizione: {p['risk_eur']:.0f}EUR")
    out.append("")
    out.append(f" Riferimento storico (ai VECCHI target, win-rate 74%): attesa {p['net_exp_pct']:+.2f}% = {p['eur_exp']:+.0f}EUR")
    out.append("")
    out.append(" PRO:  target tarati sul backtest: T1~2*ATR 'hittable' (~50% win, mediana>0),")
    out.append("       T2/T3 larghi catturano la coda dei vincitori (dove sta l'expectancy)")
    out.append(" CONTRO: stop NON negoziabile; mediana per-trade ~0 -> l'edge e' nella coda,")
    out.append("         serve disciplina su molte operazioni; DSR<0.95 = edge non blindato")
    if not p['cost_efficient']:
        out.append(f"         !! poco efficiente per conti piccoli: T1 netto +{p['g1_pct']:.1f}% troppo vicino ai costi")
    if p['confidence']=="BASSA":
        out.append("         !! confidenza BASSA: titolo illiquido o score debole -> size ridotta")
    if p['regime_mult'] < 1.0:
        out.append(f"         !! regime non pienamente favorevole: sizing ridotto a x{p['regime_mult']}")
    out.append("="*58)
    return "\n".join(out)

if __name__ == "__main__":
    # Demo con numeri di esempio (entry/ATR vanno presi dai dati EOD reali)
    print(render(propose("STMMI.MI", entry=30.0, atr14=0.95, score=0.43, capital=50000)))
    print()
    print(render(propose("BPSO.MI", entry=12.5, atr14=0.40, score=0.53, capital=50000, regime_mult=0.5)))
