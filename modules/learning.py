import csv, os
import numpy as np
from dataclasses import dataclass, asdict

TRADE_LOG_COLUMNS = ["date","ticker","segnale_tecnico","segnale_flow",
                     "segnale_spillover","segnale_decay","entry","exit","pnl",
                     "realized_weights_usate","signal_class","won"]

@dataclass
class SignalClassStats:
    alpha: float = 7.0
    beta: float = 7.0
    wins: int = 0
    trades: int = 0

    def update(self, won: bool):
        self.trades += 1
        if won:
            self.wins += 1

    @property
    def posterior_winrate(self) -> float:
        return (self.alpha + self.wins) / (self.alpha + self.beta + self.trades)

    def weight_multiplier(self, min_trades: int = 20) -> float:
        """Ritorna 1.0 se trades < min_trades, altrimenti mappa win-rate a moltiplicatore."""
        if self.trades < min_trades:
            return 1.0
        wr = self.posterior_winrate
        return float(np.clip(0.6 + (wr - 0.4) * (0.8 / 0.3), 0.5, 1.5))

def log_trade(path: str, row: dict):
    """Append fail-safe di un trade al CSV."""
    exists = os.path.exists(path)
    try:
        with open(path, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=TRADE_LOG_COLUMNS)
            if not exists:
                w.writeheader()
            w.writerow({k: row.get(k, "") for k in TRADE_LOG_COLUMNS})
    except Exception as e:
        print(f"[learning] log fallito (non bloccante): {e}")

def load_signal_stats(path: str) -> dict:
    """Carica gli stats precedenti (placeholder per ora)."""
    return {}
