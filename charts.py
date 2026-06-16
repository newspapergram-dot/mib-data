"""charts.py — Grafici candlestick multi-pannello via mplfinance."""
import os
import matplotlib
matplotlib.use("Agg")
import mplfinance as mpf
import pandas as pd
from indicators import rsi_wilder, macd
from volume_tools import obv, validate_volume


def make_chart(df: pd.DataFrame, ticker: str, out_dir="charts"):
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
             panel_ratios=(6, 2, 3), figscale=1.4, title=f"\n{ticker}",
             savefig=dict(fname=out_png, dpi=150, bbox_inches="tight"))
    print(f"[charts] salvato {out_png}")
    return out_png


def chart_from_repo(ticker: str, lookback=180):
    import urllib.request, io
    base = "https://raw.githubusercontent.com/newspapergram-dot/mib-data/refs/heads/main/data/"
    px = pd.read_csv(io.StringIO(urllib.request.urlopen(base+"mib_data.csv", timeout=60).read().decode("utf-8","replace")))
    px["date"] = pd.to_datetime(px["date"])
    g = px[px["ticker"] == ticker].sort_values("date").tail(lookback)
    g = g.set_index("date")[["open", "high", "low", "close", "volume"]]
    return make_chart(g, ticker)


if __name__ == "__main__":
    import urllib.request, io
    base = "https://raw.githubusercontent.com/newspapergram-dot/mib-data/refs/heads/main/data/"
    px = pd.read_csv(io.StringIO(urllib.request.urlopen(base+"mib_data.csv", timeout=60).read().decode("utf-8","replace")))
    px["date"] = pd.to_datetime(px["date"])
    s = px.sort_values(["ticker", "date"]).groupby("ticker").tail(1)
    top = s.head(8)["ticker"].tolist()
    for tk in top:
        try: chart_from_repo(tk)
        except Exception as e: print(f"[charts] {tk}: {e}")
