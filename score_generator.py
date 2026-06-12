import pandas as pd
import numpy as np
from datetime import datetime
import sys

# Import moduli locali
from modules.decay import apply_decay, compute_ages, HALF_LIVES
from modules.spillover import spillover_confidence_adjust, sector_beta
from modules.ensemble import combine_signals, inverse_vol_weight, equal_weight
from modules.learning import SignalClassStats

def generate_scores(mib_data_path: str, insider_path: str, f13_path: str,
                    cot_path: str, output_path: str, treasury_move_bp: float = 0,
                    fx_drift_pct: float = 0):
    """Orchestratore principale. Genera score finale per ogni ticker."""
    
    try:
        # 1. Carica dati
        px = pd.read_csv(mib_data_path); px["date"] = pd.to_datetime(px["date"])
        ins = pd.read_csv(insider_path) if os.path.exists(insider_path) else pd.DataFrame()
        f13 = pd.read_csv(f13_path) if os.path.exists(f13_path) else pd.DataFrame()
        cot = pd.read_csv(cot_path) if os.path.exists(cot_path) else pd.DataFrame()
        
        print("[score_generator] dati caricati")
        
        # 2. Per ogni ticker, compila componenti segnale
        results = []
        for tk in px.ticker.unique():
            g = px[px.ticker == tk].sort_values("date")
            if len(g) < 50:
                continue
            
            # segnali base (tecnico, flow) — li calcoli tu o li importi da fetch_flows
            # PER SEMPLICITA': placeholder
            sig_tech = 0.5  # da mettere il calcolo reale RSI/ADX/SMA
            sig_flow = 0.2  # da mettere il calcolo reale 13F/insider
            
            # 3. DECAY
            ages = {
                "technical": 1,  # ieri (EOD oggi)
                "f13": 40,       # plausibile
                "insider_form4": 2,
                "cot": 8,        # settimanale, ieri era marted
            }
            components = {"technical": sig_tech, "flow": sig_flow}
            decayed = apply_decay(components, ages)
            
            # 4. SPILLOVER (semplificato: skippa se mancano dati Treasury)
            try:
                # Se hai TLT nella pipeline, calcolalo; altrimenti skippa
                spillover_adj = spillover_confidence_adjust(
                    decayed["technical"], sector_beta_treasury=0.8,
                    treasury_move_bp=treasury_move_bp, fx_drift_pct=fx_drift_pct)
                decayed["technical"] = spillover_adj["adjusted_signal"]
            except Exception as e:
                print(f"[spillover] fallito per {tk}: {e}")
            
            # 5. ENSEMBLE
            score = combine_signals(decayed)
            
            # 6. LEARNING (placeholder: skippa finche' non hai trade log)
            # score *= 1.0  # no moltiplicatore
            
            results.append({
                "ticker": tk, "score": round(score, 3),
                "segnale_tecnico": round(sig_tech, 3),
                "segnale_flow": round(sig_flow, 3),
                "segnale_decay": round(decayed.get("technical", 0), 3),
                "componenti_decayed": str(decayed),
                "date": datetime.today().isoformat()
            })
        
        # Output
        out_df = pd.DataFrame(results).sort_values("score", ascending=False)
        out_df.to_csv(output_path, index=False)
        print(f"[score_generator] score salvati in {output_path}")
        print(out_df.head(10).to_string())
        
    except Exception as e:
        print(f"[score_generator] ERRORE: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    import os
    generate_scores(
        "data/mib_data.csv",
        "data/insider_us.csv",
        "data/13f_holdings.csv",
        "data/cot.csv",
        "data/score_output.csv",
        treasury_move_bp=0,
        fx_drift_pct=0
    )
