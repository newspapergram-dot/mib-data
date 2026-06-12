import numpy as np
import pandas as pd

def equal_weight(signals: dict) -> float:
    """Peso uguale a tutti i segnali validi."""
    vals = [v for v in signals.values()
            if v is not None and not np.isnan(float(v) if v is not None else np.nan)]
    return float(np.mean(vals)) if vals else 0.0

def inverse_vol_weight(signal_df: pd.DataFrame, lookback: int = 60) -> dict:
    """Pesi inverse-vol. Ritorna dict {colonna: peso}."""
    try:
        vol = signal_df.tail(lookback).std()
        vol = vol.replace(0, np.nan)
        inv = 1.0 / vol
        w = inv / inv.sum()
        return w.fillna(0.0).to_dict()
    except Exception:
        return {col: 1.0/len(signal_df.columns) for col in signal_df.columns}

def combine_signals(signals: dict, weights: dict = None) -> float:
    """Combina segnali con pesi. Fail-safe a equal-weight."""
    try:
        keys = [k for k in signals if signals[k] is not None
                and not np.isnan(float(signals[k]))]
        if not keys:
            return 0.0
        if weights is None:
            return float(np.mean([signals[k] for k in keys]))
        wsum = sum(weights.get(k, 0) for k in keys)
        if wsum == 0:
            return float(np.mean([signals[k] for k in keys]))
        return float(sum(signals[k] * weights.get(k, 0) for k in keys) / wsum)
    except Exception:
        return equal_weight(signals)
