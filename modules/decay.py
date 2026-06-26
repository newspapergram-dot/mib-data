import numpy as np
from datetime import datetime, timedelta

HALF_LIVES = {
    "insider_form4": 25,
    "f13": 30,
    "cot": 10,
    "short_interest": 14,
    "etf_flow": 7,
    "technical": 10,
}
DECAY_FLOOR = 0.10

def decay_weight(signal_type: str, age_days: float) -> float:
    """Peso residuo esponenziale."""
    hl = HALF_LIVES.get(signal_type, 14)
    lam = np.log(2) / hl
    w = float(np.exp(-lam * max(age_days, 0)))
    return 0.0 if w < DECAY_FLOOR else w

def apply_decay(components: dict, ages: dict) -> dict:
    """Applica decay a ciascun componente. Fail-safe. None passati inalterati."""
    out = {}
    for k, v in components.items():
        if v is None:
            out[k] = None
            continue
        try:
            out[k] = v * decay_weight(k, ages.get(k, 0))
        except Exception:
            out[k] = v
    return out

def compute_ages(data_dates: dict, reference_date=None):
    """Calcola eta' in giorni da reference_date (default oggi)."""
    if reference_date is None:
        reference_date = datetime.today()
    ages = {}
    for signal_type, date_obj in data_dates.items():
        if date_obj is None:
            ages[signal_type] = 999  # ignora
        else:
            try:
                age = (reference_date - date_obj).days
                ages[signal_type] = max(age, 0)
            except Exception:
                ages[signal_type] = 999
    return ages
