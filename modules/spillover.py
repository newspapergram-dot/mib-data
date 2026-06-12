import numpy as np
import pandas as pd

def rolling_cross_correlations(prices: pd.DataFrame, window: int = 20):
    """Correlazione rolling tra asset class."""
    try:
        rets = np.log(prices / prices.shift(1)).dropna()
        pairs = {}
        cols = rets.columns
        for i, a in enumerate(cols):
            for b in cols[i+1:]:
                pairs[f"{a}_{b}"] = rets[a].rolling(window).corr(rets[b])
        return pd.DataFrame(pairs)
    except Exception:
        return None

def sector_beta(stock_returns: pd.Series, factor_returns: pd.Series,
                window: int = 60) -> float:
    """Beta OLS. stock_returns e factor_returns sono log-rendimenti."""
    try:
        df = pd.concat([stock_returns, factor_returns], axis=1,
                       join="inner").dropna().tail(window)
        if len(df) < 20:
            return np.nan
        cov = np.cov(df.iloc[:, 0], df.iloc[:, 1])
        return cov[0, 1] / cov[1, 1] if cov[1, 1] != 0 else np.nan
    except Exception:
        return np.nan

def spillover_confidence_adjust(base_signal: float, sector_beta_treasury: float,
                                treasury_move_bp: float,
                                fx_drift_pct: float = 0.0) -> dict:
    """Aggiusta confidence per spillover di tasso e FX."""
    try:
        rate_impact = -sector_beta_treasury * (treasury_move_bp / 100.0)
        fx_impact = fx_drift_pct / 100.0
        adjusted = base_signal * (1.0 + rate_impact) + fx_impact * np.sign(base_signal)
        adjusted = float(np.clip(adjusted, -1.0, 1.0))
        return {"adjusted_signal": adjusted, "rate_impact": rate_impact,
                "fx_impact": fx_impact, "ok": True}
    except Exception as e:
        return {"adjusted_signal": base_signal, "ok": False, "error": str(e)}
