"""charts.py — Grafici candlestick multi-pannello via mplfinance."""
import os
import matplotlib
matplotlib.use("Agg")
import mplfinance as mpf
import pandas as pd
from indicators import rsi_wilder, macd
from volume_tools import obv, validate_volume


def make_chart(df: pd.DataFrame, ticker: str, out_dir="charts", title=None):
    os.makedirs(out_dir, exist_ok=True)
    df = df.copy()
    df.columns = [c.capitalize() for c in df.columns]
    df["SMA20"] = df["Close"].rolling(20).mean()
    df["SMA50"] = df["Close"].rolling(50).mean()
    std = df["Close"].rolling(20).std()
    df["BB_up"] = df["SMA20"] + 2 * std
    df["BB_dn"] = df["SMA20"] - 2 * std
    df["RSI"] = rsi_wilder(df["Close"])
    m = macd(df["Close"])
    vol_ok = validate_volume(df.rename(columns={"Volume": "volume"}))["reliable"]
    aps = [
        mpf.make_addplot(df["SMA20"], color="blue", width=0.8),
        mpf.make_addplot(df["SMA50"], color="orange", width=0.8),
        mpf.make_addplot(df["BB_up"], color="grey", linestyle="--", width=0.6),
        mpf.make_addplot(df["BB_dn"], color="grey", linestyle="--", width=0.6),
        mpf.make_addplot(df["RSI"], panel=2, color="green", ylabel="RSI"),
        mpf.make_addplot(m["macd"], panel=2, color="blue", secondary_y=True),
        mpf.make_addplot(m["signal"], panel=2, color="red", secondary_y=True),
    ]
    if vol_ok:
        df["OBV"] = obv(df["Close"], df["Volume"])
        aps.append(mpf.make_addplot(df["OBV"], panel=1, color="purple", ylabel="OBV"))
    out_png = os.path.join(out_dir, f"{ticker.replace('.', '_')}.png")
    mpf.plot(df, type="candle", style="yahoo", addplot=aps, volume=False,
             panel_ratios=(6, 2, 3), figscale=1.4, title=f"\n{title or ticker}",
             savefig=dict(fname=out_png, dpi=150, bbox_inches="tight"))
    print(f"[charts] salvato {out_png}")
    return out_png


def _load_local(px_path="data/mib_data.csv"):
    """Legge i prezzi LOCALI freschi (mai da raw.githubusercontent/main: vedi Lezione #5)."""
    px = pd.read_csv(px_path)
    px["date"] = pd.to_datetime(px["date"])
    return px


def chart_ticker(ticker, lookback=180, px=None, px_path="data/mib_data.csv", title=None):
    """Grafico di un ticker dai dati LOCALI. Titolo con nome azienda se disponibile."""
    if px is None:
        px = _load_local(px_path)
    g = px[px["ticker"] == ticker].sort_values("date").tail(lookback)
    if g.empty:
        print(f"[charts] {ticker}: nessun dato locale")
        return None
    g = g.set_index("date")[["open", "high", "low", "close", "volume"]]
    if title is None:
        try:
            from company_names import name as _name
            nm = _name(ticker)
            title = f"{ticker} — {nm}" if nm and nm != ticker else ticker
        except Exception:
            title = ticker
    return make_chart(g, ticker, title=title)


def charts_for_portfolio(portfolio_path="data/PORTFOLIO.txt", lookback=180):
    """Grafica i SOLI titoli selezionati nel piano operativo (PORTFOLIO.txt), dai dati locali."""
    import re
    txt = open(portfolio_path).read()
    # ticker dalle schede operative: 'TICK | Score: ... | CONFIDENZA: ...'
    picks = re.findall(r'^\s*([A-Z0-9]+\.?[A-Z]{0,3})\s*\|\s*Score:', txt, re.M)
    seen, ordered = set(), []
    for t in picks:
        if t not in seen:
            seen.add(t); ordered.append(t)
    if not ordered:
        print("[charts] nessun titolo selezionato in", portfolio_path)
        return []
    px = _load_local()
    out = []
    for tk in ordered:
        try:
            p = chart_ticker(tk, lookback=lookback, px=px)
            if p:
                out.append(p)
        except Exception as e:
            print(f"[charts] {tk}: {repr(e)[:80]}")
    print(f"[charts] {len(out)} grafici dei titoli selezionati -> charts/")
    return out


if __name__ == "__main__":
    charts_for_portfolio()
