#!/usr/bin/env python3
"""
Score Generator Completo — Tecnico + Flow + 4 Moduli (Decay, Spillover, Ensemble, Learning).
"""
from indicators import adx, rsi_wilder, macd, atr_wilder
from patterns import detect_patterns
import os, sys, csv
from datetime import datetime, timedelta
import numpy as np
import pandas as pd

# Importa moduli locali
from modules.decay import apply_decay, compute_ages
from modules.spillover import spillover_confidence_adjust
from modules.ensemble import combine_signals, equal_weight
from modules.learning import SignalClassStats

NON_EQUITY = {
    "FTSEMIB.MI", "^FCHI", "^STOXX50E", "^GSPC", "^NDX", "^VIX",
    "SPY", "XLF", "XLE", "XLK", "XLV", "XLY",
    "XLP", "XLU", "XLI", "XLB", "XLRE", "XLC",
}

# ============================================================================
# PARTE 1: CALCOLO INDICATORI TECNICI
# ============================================================================

def calculate_technical_indicators(g_df):
    """Calcola RSI, ADX, SMA, ATR, MACD."""
    try:
        g_df = g_df.dropna(subset=["close"])
        c = g_df["close"].reset_index(drop=True)
        h = g_df["high"].reset_index(drop=True)
        l = g_df["low"].reset_index(drop=True)
        if len(c) < 200:
            return {}
        
        # RSI 14
        d = c.diff()
        up = d.clip(lower=0).rolling(14).mean()
        dn = (-d.clip(upper=0)).rolling(14).mean()
        rsi = (100 - 100 / (1 + up / dn)).iloc[-1]
        
        # SMA 20, 50, 200
        sma20 = c.rolling(20).mean().iloc[-1]
        sma50 = c.rolling(50).mean().iloc[-1]
        sma200 = c.rolling(200).mean().iloc[-1]
        
        # ATR 14
        tr = c.diff().abs().rolling(14).mean()
        atr = tr.iloc[-1]
        atr_pct = (atr / c.iloc[-1] * 100) if c.iloc[-1] != 0 else 0
        
        # MACD
        macd = c.ewm(span=12).mean() - c.ewm(span=26).mean()
        signal_line = macd.ewm(span=9).mean()
        macd_hist = (macd - signal_line).iloc[-1]
        
        # ADX reale (Wilder)
        adx_df = adx(h, l, c)
        adx_val = adx_df["adx"].iloc[-1]
        trend_up = adx_df["plus_di"].iloc[-1] > adx_df["minus_di"].iloc[-1]

        # Breakout: prezzo > max(high) degli ultimi 20 giorni (escluso oggi)
        rh20 = h.iloc[-21:-1].max() if len(h) >= 21 else h.iloc[:-1].max()
        breakout = bool(c.iloc[-1] > rh20) if len(h) > 1 else False

        # Momentum 3 mesi (allineato a score_new del backtest)
        mom3m = (c.iloc[-1] / c.iloc[max(0, len(c)-63)] - 1) * 100 if len(c) > 63 else 0
        # Momentum 6 mesi (legacy, per CSV)
        mom6m = (c.iloc[-1] / c.iloc[max(0, len(c)-127)] - 1) * 100 if len(c) > 127 else 0

        # Gate
        gate = (c.iloc[-1] > sma200) and (sma50 > sma200)

        return {
            "rsi": round(float(rsi), 1) if not np.isnan(rsi) else None,
            "sma20": round(float(sma20), 2) if not np.isnan(sma20) else None,
            "sma50": round(float(sma50), 2) if not np.isnan(sma50) else None,
            "sma200": round(float(sma200), 2) if not np.isnan(sma200) else None,
            "atr": round(float(atr), 3) if not np.isnan(atr) else None,
            "atr_pct": round(float(atr_pct), 2) if not np.isnan(atr_pct) else None,
            "macd_hist": round(float(macd_hist), 4) if not np.isnan(macd_hist) else None,
            "adx": round(float(adx_val), 1),
            "trend_up": bool(trend_up),
            "breakout": breakout,
            "mom3m": round(float(mom3m), 1),
            "mom6m": round(float(mom6m), 1),
            "gate": bool(gate),
            "last_price": round(float(c.iloc[-1]), 3),
        }
    except Exception as e:
        print(f"[tech_indicators] errore: {e}", file=sys.stderr)
        return {}

def score_technical(indicators):
    """Score tecnico — allineato a score_new del backtest (validato sul ciclo 2018-2026).

    Componenti identiche a backtest_v3.score_new:
      breakout (+0.55) | ADX threshold (+0.35/+0.15) | momentum 3m | RSI penalty
    """
    try:
        if not indicators.get("gate"):
            return -0.3

        adx_v = indicators.get("adx", 20)
        trend_up = indicators.get("trend_up", False)
        breakout = indicators.get("breakout", False)
        rsi = indicators.get("rsi", 50)
        mom3m = indicators.get("mom3m", 0)

        s = 0.0
        if breakout and trend_up:
            s += 0.55
        if adx_v >= 40 and trend_up:
            s += 0.35
        elif adx_v >= 25 and trend_up:
            s += 0.15
        s += 0.15 * np.tanh(mom3m / 30)
        if rsi > 75 and not breakout:
            s -= 0.20

        return float(np.clip(s, -1.0, 1.0))
    except Exception:
        return 0.0

# ============================================================================
# PARTE 2: CALCOLO SEGNALI DI FLOW
# ============================================================================

def score_flow_13f(ticker, f13_df):
    """Segnale 13F: conta quanti guru hanno il titolo. None = no data."""
    try:
        ticker_to_issuer = {
            "AAPL": "APPLE INC", "MSFT": "MICROSOFT CORP", "NVDA": "NVIDIA CORPORATION",
            "GOOGL": "ALPHABET INC", "AMZN": "AMAZON COM INC", "META": "META PLATFORMS INC",
            "JPM": "JPMORGAN", "BAC": "BANK AMERICA CORP", "KO": "COCA COLA CO",
            "CVX": "CHEVRON CORPORATION", "PFE": "PFIZER INC",
            "STM": "STMICROELECTRONICS", "STMMI.MI": "STMICROELECTRONICS",
        }
        issuer = ticker_to_issuer.get(ticker, ticker.upper())

        if f13_df.empty:
            return None

        matches = f13_df[f13_df["issuer"].str.contains(issuer, case=False, na=False)]
        if matches.empty:
            return None

        guru_count = matches["guru"].nunique()
        return float(np.clip(guru_count / 3.0, 0, 1))
    except Exception:
        return None

def score_flow_insider(ticker, ins_df):
    """Segnale insider: +1 cluster, -0.5 vendite discrezionali. None = no data."""
    try:
        if ins_df.empty:
            return None

        match = ins_df[ins_df["ticker"] == ticker]
        if match.empty:
            return None

        sig = float(match.iloc[0].get("signal", 0))
        if sig == 0:
            return None
        return sig
    except Exception:
        return None

def score_flow_short(ticker, short_fr_df):
    """Segnale short: contrarian. None = no data / low interest."""
    try:
        if not short_fr_df.empty:
            matches = short_fr_df[short_fr_df["Emetteur / issuer"].str.contains(
                ticker, case=False, na=False)]
            if not matches.empty:
                try:
                    max_ratio = matches["Ratio"].astype(float, errors="coerce").max()
                    if max_ratio > 0.5:
                        return -0.5
                except Exception:
                    pass
        return None
    except Exception:
        return None

def score_flow(ticker, f13_df, ins_df, short_fr_df):
    """Combina segnali di flow. None se nessuna fonte ha dati per il ticker."""
    try:
        s_13f = score_flow_13f(ticker, f13_df)
        s_ins = score_flow_insider(ticker, ins_df)
        s_short = score_flow_short(ticker, short_fr_df)
        parts = [(v, w) for v, w in [(s_13f, 0.5), (s_ins, 0.4), (s_short, 0.1)]
                 if v is not None]
        if not parts:
            return None
        wsum = sum(w for _, w in parts)
        combined = sum(v * w for v, w in parts) / wsum
        return float(np.clip(combined, -1.0, 1.0))
    except Exception:
        return None

# ============================================================================
# PARTE 3: ORCHESTRATORE PRINCIPALE
# ============================================================================

def generate_scores(mib_data_path="data/mib_data.csv",
                    insider_path="data/insider_us.csv",
                    f13_path="data/13f_holdings.csv",
                    cot_path="data/cot.csv",
                    short_fr_path="data/short_fr.csv",
                    output_path="data/score_output.csv",
                    treasury_move_bp=0.0,
                    fx_drift_pct=0.0):
    """Main orchestrator."""
    
    print("[score_generator] INIZIO", flush=True)
    
    try:
        px = pd.read_csv(mib_data_path)
        px["date"] = pd.to_datetime(px["date"])
        px = px.sort_values(["ticker", "date"])
        
        ins = pd.read_csv(insider_path) if os.path.exists(insider_path) else pd.DataFrame()
        f13 = pd.read_csv(f13_path) if os.path.exists(f13_path) else pd.DataFrame()
        cot = pd.read_csv(cot_path) if os.path.exists(cot_path) else pd.DataFrame()
        shf = pd.read_csv(short_fr_path) if os.path.exists(short_fr_path) else pd.DataFrame()
        
        print(f"[score_generator] dati: {len(px)} prezzi, {len(ins)} insider, {len(f13)} holdings", flush=True)
        
        results = []
        ref_date = datetime.today()
        
        for tk in sorted(px.ticker.unique()):
            if tk in NON_EQUITY:
                continue
            try:
                g = px[px.ticker == tk].sort_values("date")
                if len(g) < 50:
                    continue
                
                tech_ind = calculate_technical_indicators(g)
                if not tech_ind or not tech_ind.get("gate"):
                    continue
                
                sig_tech = score_technical(tech_ind)
                sig_flow = score_flow(tk, f13, ins, shf)
                
                last_price_date = g["date"].iloc[-1]
                ages = {
                    "technical": max((ref_date - last_price_date).days, 0),
                    "f13": 40,
                    "insider_form4": 2,
                    "cot": 8,
                    "etf_flow": 1,
                }
                
                components = {"technical": sig_tech, "flow": sig_flow}
                decayed = apply_decay(components, ages)
                
                if treasury_move_bp != 0:
                    try:
                        if "tech" in tk.lower() or tk in ["NVDA", "MSFT", "AAPL", "GOOGL"]:
                            beta_t = 1.2
                        elif "bank" in tk.lower() or tk in ["JPM", "BAC", "GS"]:
                            beta_t = -0.3
                        else:
                            beta_t = 0.5
                        
                        spillover_adj = spillover_confidence_adjust(
                            decayed["technical"], beta_t, treasury_move_bp, fx_drift_pct)
                        decayed["technical"] = spillover_adj["adjusted_signal"]
                    except Exception:
                        pass
                
                final_score = combine_signals(decayed)
                
                results.append({
                    "ticker": tk,
                    "score": round(final_score, 3),
                    "segnale_tecnico": round(sig_tech, 3),
                    "segnale_flow": round(sig_flow, 3) if sig_flow is not None else 0.0,
                    "segnale_decayed": round(decayed["technical"], 3),
                    "price": tech_ind.get("last_price"),
                    "rsi": tech_ind.get("rsi"),
                    "adx": tech_ind.get("adx"),
                    "atr_pct": tech_ind.get("atr_pct"),
                    "mom6m": tech_ind.get("mom6m"),
                    "sma20": tech_ind.get("sma20"),
                    "sma50": tech_ind.get("sma50"),
                    "sma200": tech_ind.get("sma200"),
                    "date": ref_date.isoformat(),
                })
                
            except Exception as e:
                print(f"[score] {tk}: {e}", file=sys.stderr)
        
        if not results:
            print("[score_generator] nessun candidato", file=sys.stderr)
            return
        
        out_df = pd.DataFrame(results).sort_values("score", ascending=False)
        out_df.to_csv(output_path, index=False)
        
        print(f"\n[score_generator] OK: {len(out_df)} candidati in {output_path}", flush=True)
        print("\n=== TOP 10 ===", flush=True)
        print(out_df[["ticker", "score", "segnale_tecnico", "segnale_flow", 
                      "price", "rsi", "adx"]].head(10).to_string(index=False), flush=True)
        print("\n", flush=True)
        
    except Exception as e:
        print(f"\n[score_generator] ERRORE: {e}\n", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    generate_scores()
