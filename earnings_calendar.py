"""earnings_calendar.py — Date earnings/dividendi per evitare swing su earnings."""
import os
import time
import pandas as pd
from datetime import datetime, timedelta


def earnings_from_yfinance(ticker: str):
    import yfinance as yf
    next_earn, next_div = None, None
    try:
        t = yf.Ticker(ticker)
        cal = t.calendar
        if isinstance(cal, dict):
            ed = cal.get("Earnings Date")
            if ed:
                next_earn = ed[0] if isinstance(ed, list) else ed
            dd = cal.get("Dividend Date")
            if dd:
                next_div = dd[0] if isinstance(dd, list) else dd
    except Exception:
        pass
    return {"ticker": ticker, "next_earnings_date": next_earn,
            "next_dividend_date": next_div, "source": "yfinance"}


def earnings_from_finnhub(ticker: str, api_key: str):
    import requests
    to = (datetime.utcnow() + timedelta(days=90)).strftime("%Y-%m-%d")
    frm = datetime.utcnow().strftime("%Y-%m-%d")
    try:
        r = requests.get("https://finnhub.io/api/v1/calendar/earnings",
                         params={"from": frm, "to": to, "symbol": ticker, "token": api_key},
                         timeout=20)
        if r.status_code == 429:
            time.sleep(2); return None
        data = r.json().get("earningsCalendar", [])
        if data:
            return {"ticker": ticker, "next_earnings_date": data[0]["date"],
                    "next_dividend_date": None, "source": "finnhub"}
    except Exception:
        pass
    return None


def build_calendar(tickers, out_path="data/earnings_calendar.csv",
                   finnhub_key=None, within_days=14):
    rows = []
    for tk in tickers:
        rec = earnings_from_yfinance(tk)
        if rec["next_earnings_date"] is None and finnhub_key and not tk.endswith((".MI", ".PA", ".L", ".AS", ".DE")):
            fh = earnings_from_finnhub(tk, finnhub_key)
            if fh:
                rec = fh
        rows.append(rec)
        time.sleep(0.3)
    df = pd.DataFrame(rows)
    today = pd.Timestamp(datetime.utcnow().date())
    def flag(d):
        try:
            days = (pd.to_datetime(d).tz_localize(None) - today).days
            return 0 <= days <= within_days
        except Exception:
            return False
    df["earnings_within_N"] = df["next_earnings_date"].apply(flag)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    df.to_csv(out_path, index=False)
    print(f"[earnings] {df['earnings_within_N'].sum()} ticker con earnings entro {within_days}gg -> {out_path}")
    return df


if __name__ == "__main__":
    import urllib.request, io
    base = "https://raw.githubusercontent.com/newspapergram-dot/mib-data/refs/heads/main/data/"
    px = pd.read_csv(io.StringIO(urllib.request.urlopen(base+"mib_data.csv", timeout=60).read().decode("utf-8","replace")))
    build_calendar(list(px["ticker"].unique()), finnhub_key=os.getenv("FINNHUB_API_KEY"))
