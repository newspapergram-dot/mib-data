#!/usr/bin/env python3
"""
backtest_v3.py — Backtest istituzionale completo.
Integra tutti i parametri di affidabilità e scalabilità:
  - Fill realistico (open barra successiva) + costi/slippage
  - Metriche complete: Sharpe, Sortino, Calmar, Profit Factor, Expectancy,
    CVaR, Win Rate, Max Consecutive Losses, Time Underwater, Recovery Factor
  - Deflated Sharpe Ratio (DSR) — correzione per multiple testing
  - Purged K-Fold CV con embargo — elimina leakage da label sovrapposte
  - Block Bootstrap — intervalli di confidenza su Sharpe e MaxDD
  - Probability of Backtest Overfitting (CSCV/PBO)
  - Walk-Forward Analysis (anchored) con Walk-Forward Efficiency
  - Performance per regime di mercato (bull/bear/laterale, vol)
  - Parameter sensitivity heatmap (Sharpe su griglia holding × soglia)
  - Score VECCHIO vs Score NUOVO (breakout + ADX reale)
Produce: data/backtest_report.csv + data/backtest_summary.txt
"""

import os, sys, json
import numpy as np
import pandas as pd
from itertools import combinations
from scipy.stats import norm, skew, kurtosis as sp_kurtosis

sys.path.insert(0, ".")          # trova indicators.py nella root del repo

try:
    from indicators import adx, rsi_wilder, macd, atr_wilder
except ImportError:
    print("[backtest] ERRORE: indicators.py non trovato nella root del repo.")
    sys.exit(1)

# Definizione canonica del quality score PIT (condivisa con portfolio_builder).
from modules.fundamentals import pit_quality_score

EMC = 0.5772156649015329          # costante di Eulero-Mascheroni

# ─────────────────────────────────────────────────────────────────────────────
# FONDAMENTALI POINT-IN-TIME (SEC EDGAR)
# ─────────────────────────────────────────────────────────────────────────────

def load_pit(path="data/fundamentals_pit_history.csv",
             eu_path="data/fundamentals_eu_history.csv"):
    """Carica la storia fondamentale e costruisce un lookup point-in-time per ticker.

    Unisce due fonti con schema identico:
      - USA: SEC EDGAR, PIT VERO (filed = data di deposito reale).
      - EU:  Yahoo timeseries, PIT APPROSSIMATO (filed = fine periodo + lag regolatorio;
             dati restated). Disponibile solo ~ultimi 4 anni. Vedi fundamentals_eu.py.
    Ritorna {ticker: DataFrame ordinato per filed} o {} se nessun file presente."""
    frames = []
    for p in (path, eu_path):
        if os.path.exists(p):
            d = pd.read_csv(p)
            if not d.empty:
                frames.append(d)
    if not frames:
        return {}
    df = pd.concat(frames, ignore_index=True, sort=False)
    df["filed"] = pd.to_datetime(df["filed"], errors="coerce")
    df = df.dropna(subset=["filed"])
    out = {}
    for tk, g in df.groupby("ticker"):
        out[tk] = g.sort_values("filed").reset_index(drop=True)
    return out


def pit_lookup(pit_data, ticker, as_of_date):
    """Dato un ticker e una data, ritorna la riga PIT piu' recente con filed <= as_of_date.
    Ritorna un dict con le metriche o None se non disponibile."""
    if ticker not in pit_data:
        return None
    df = pit_data[ticker]
    mask = df["filed"] <= pd.Timestamp(as_of_date)
    if not mask.any():
        return None
    return df[mask].iloc[-1].to_dict()

# ─────────────────────────────────────────────────────────────────────────────
# SEZIONE 1 — SCORE FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

def score_old(c, h, l, t):
    """Score VECCHIO (proxy ADX errato) — mantenuto per confronto."""
    if t < 200:
        return None
    cc, hh, ll = c.iloc[:t+1], h.iloc[:t+1], l.iloc[:t+1]
    sma20  = cc.rolling(20).mean().iloc[-1]
    sma50  = cc.rolling(50).mean().iloc[-1]
    sma200 = cc.rolling(200).mean().iloc[-1]
    cur = cc.iloc[-1]
    if not (cur > sma200 and sma50 > sma200):
        return None
    rsi = rsi_wilder(cc).iloc[-1]
    adx_val = adx(hh, ll, cc)["adx"].iloc[-1]
    m   = macd(cc)["hist"].iloc[-1]
    mom = (cur / cc.iloc[max(0, len(cc)-127)] - 1)*100 if len(cc) > 127 else 0
    s = 0.3*np.tanh(mom/50) + 0.2*np.tanh(adx_val/50)
    if rsi > 70:           s -= 0.15
    elif rsi < 30:         s += 0.10
    elif 50 <= rsi <= 70:  s += 0.10
    if m > 0:              s += 0.10
    elif m < -0.001:       s -= 0.05
    return float(np.clip(s, -1, 1))


def score_new(c, h, l, t):
    """Score NUOVO — breakout + ADX reale >= 40 (validato dal backtest v1)."""
    if t < 200:
        return None
    cc, hh, ll = c.iloc[:t+1], h.iloc[:t+1], l.iloc[:t+1]
    sma50  = cc.rolling(50).mean().iloc[-1]
    sma200 = cc.rolling(200).mean().iloc[-1]
    cur = cc.iloc[-1]
    if not (cur > sma200 and sma50 > sma200):
        return None
    adf      = adx(hh, ll, cc)
    adx_v    = adf["adx"].iloc[-1]
    trend_up = adf["plus_di"].iloc[-1] > adf["minus_di"].iloc[-1]
    rsi      = rsi_wilder(cc).iloc[-1]
    rh20     = hh.iloc[-21:-1].max()
    breakout = cur > rh20
    s = 0.0
    if breakout and trend_up:       s += 0.55
    if adx_v >= 40 and trend_up:    s += 0.35
    elif adx_v >= 25 and trend_up:  s += 0.15
    mom3m = (cur / cc.iloc[max(0, len(cc)-63)] - 1)*100 if len(cc) > 63 else 0
    s += 0.15*np.tanh(mom3m/30)
    if rsi > 75 and not breakout:   s -= 0.20
    return float(np.clip(s, -1, 1))


# ─────────────────────────────────────────────────────────────────────────────
# SEZIONE 2 — METRICHE COMPLETE
# ─────────────────────────────────────────────────────────────────────────────

def perf_metrics(r, ann=252, rf=0.0, mar=0.0, label=""):
    """Calcola tutte le metriche di performance su serie di rendimenti r."""
    r = pd.Series(r).dropna()
    if len(r) < 5:
        return {}
    mu, sd = r.mean(), r.std(ddof=1)
    if sd == 0:
        return {}
    dd_dev    = np.sqrt((np.minimum(r - mar, 0)**2).mean())
    eq        = (1 + r).cumprod()
    peak      = eq.cummax()
    dd        = (eq / peak - 1)
    maxdd     = float(dd.min())
    years     = len(r) / ann
    cagr      = float(eq.iloc[-1]**(1/years) - 1) if years > 0 else np.nan
    wins      = r[r > 0]; losses = r[r < 0]
    pf        = float(wins.sum() / abs(losses.sum())) if losses.sum() != 0 else np.inf
    wr        = float((r > 0).mean())
    avg_w     = float(wins.mean())  if len(wins)   else 0.0
    avg_l     = float(abs(losses.mean())) if len(losses) else 0.0
    exp_val   = wr*avg_w - (1-wr)*avg_l
    # max consecutive losses
    sign = (r < 0).astype(int).reset_index(drop=True)
    run  = sign.groupby((sign != sign.shift()).cumsum()).cumsum()
    mcl  = int(run.max())
    # time underwater (bar)
    uw   = (dd < 0).astype(int)
    tuw  = int(uw.groupby((uw != uw.shift()).cumsum()).cumsum().max())
    # tail risk
    var95 = float(np.percentile(r, 5))
    cvar  = float(r[r <= var95].mean()) if (r <= var95).any() else var95
    tr    = (abs(np.percentile(r,95))/abs(np.percentile(r,5))
             if np.percentile(r,5) != 0 else np.nan)
    rf_factor = float((eq.iloc[-1]-1)/abs(maxdd)) if maxdd < 0 else np.nan
    m = {
        "label": label, "n": len(r),
        "Sharpe_ann": float(mu/sd*np.sqrt(ann)),
        "Sortino_ann": float((mu-mar)/dd_dev*np.sqrt(ann)) if dd_dev > 0 else np.nan,
        "Calmar": float(cagr/abs(maxdd)) if maxdd < 0 else np.nan,
        "CAGR_pct": float(cagr*100), "Vol_ann_pct": float(sd*np.sqrt(ann)*100),
        "MaxDD_pct": float(maxdd*100),
        "ProfitFactor": pf, "Expectancy_pct": float(exp_val*100),
        "WinRate_pct": float(wr*100), "PayoffRatio": float(avg_w/avg_l) if avg_l>0 else np.inf,
        "AvgWin_pct": float(avg_w*100), "AvgLoss_pct": float(avg_l*100),
        "MaxConsecLoss": mcl, "TimeUnderwater_bars": tuw,
        "RecoveryFactor": rf_factor, "TailRatio": float(tr) if not np.isnan(tr) else np.nan,
        "VaR95_pct": float(var95*100), "CVaR95_pct": float(cvar*100),
    }
    return m


# ─────────────────────────────────────────────────────────────────────────────
# SEZIONE 3 — DSR / PSR (correzione per multiple testing)
# ─────────────────────────────────────────────────────────────────────────────

def psr(returns, sr_bench=0.0):
    r = np.asarray(returns, float)
    r = r[~np.isnan(r)]
    if len(r) < 5: return np.nan
    T = len(r)
    sr = r.mean() / r.std(ddof=1)
    g3, g4 = float(skew(r)), float(sp_kurtosis(r, fisher=False))
    num = (sr - sr_bench) * np.sqrt(T - 1)
    den = np.sqrt(max(1 - g3*sr + (g4-1)/4*sr**2, 1e-9))
    return float(norm.cdf(num/den))


def deflated_sharpe(returns, all_sharpes):
    """DSR: PSR valutato contro lo Sharpe massimo atteso per multiple testing."""
    r = np.asarray(returns, float)
    r = r[~np.isnan(r)]
    if len(r) < 5 or len(all_sharpes) < 2: return np.nan, np.nan
    T   = len(r)
    sr  = r.mean() / r.std(ddof=1)
    g3, g4 = float(skew(r)), float(sp_kurtosis(r, fisher=False))
    N   = len(all_sharpes)
    sr0 = np.std(all_sharpes, ddof=1) * (
          (1-EMC)*norm.ppf(1-1/N) + EMC*norm.ppf(1-1/(N*np.e)))
    num = (sr - sr0) * np.sqrt(T-1)
    den = np.sqrt(max(1 - g3*sr + (g4-1)/4*sr**2, 1e-9))
    return float(norm.cdf(num/den)), float(sr0)


def min_track_record_length(returns, sr_bench=0.0, prob=0.95):
    r = np.asarray(returns, float); r = r[~np.isnan(r)]
    if len(r) < 5: return np.nan
    sr = r.mean()/r.std(ddof=1)
    g3, g4 = float(skew(r)), float(sp_kurtosis(r, fisher=False))
    if sr == sr_bench: return np.inf
    z = norm.ppf(prob)
    return 1 + (1 - g3*sr + (g4-1)/4*sr**2) * (z/(sr-sr_bench))**2


# ─────────────────────────────────────────────────────────────────────────────
# SEZIONE 4 — PBO (Probability of Backtest Overfitting via CSCV)
# ─────────────────────────────────────────────────────────────────────────────

def pbo_cscv(M, S=8):
    """M: array (T, N) di rendimenti per-bar. Restituisce PBO."""
    T, N = M.shape
    if N < 2 or T < S*2:
        return np.nan
    rows = np.array_split(np.arange(T), S)
    logits = []
    metric = lambda x: (x.mean()/(x.std(ddof=1)+1e-12)) if len(x)>1 else 0
    for comb in combinations(range(S), S//2):
        is_idx  = np.concatenate([rows[i] for i in comb])
        oos_idx = np.concatenate([rows[i] for i in range(S) if i not in comb])
        R_is  = np.array([metric(M[is_idx,  n]) for n in range(N)])
        R_oos = np.array([metric(M[oos_idx, n]) for n in range(N)])
        n_star = int(np.argmax(R_is))
        rank   = (R_oos.argsort().argsort()[n_star]+1)/(N+1)
        rank   = float(np.clip(rank, 1e-6, 1-1e-6))
        logits.append(np.log(rank/(1-rank)))
    logits = np.array(logits)
    return float((logits <= 0).mean())


# ─────────────────────────────────────────────────────────────────────────────
# SEZIONE 5 — PURGED K-FOLD con EMBARGO
# ─────────────────────────────────────────────────────────────────────────────

def purged_kfold_splits(n, holding, n_splits=5, embargo_frac=0.01):
    """
    Restituisce lista di (train_idx, test_idx) con purging e embargo.
    n        : numero totale di osservazioni (ordinate nel tempo)
    holding  : holding period in barre (usato per purging)
    """
    embargo = max(1, int(n * embargo_frac))
    folds   = np.array_split(np.arange(n), n_splits)
    splits  = []
    for f_idx, test in enumerate(folds):
        t0, t1 = int(test[0]), int(test[-1])
        train_mask = np.ones(n, bool)
        train_mask[test] = False
        # purge: rimuovi dal train le osservazioni la cui label tocca il test
        purge_start = max(0, t0 - holding)
        purge_end   = min(n-1, t1 + holding)
        train_mask[purge_start:purge_end+1] = False
        # embargo: buffer dopo il test fold
        emb_end = min(n-1, t1 + embargo)
        train_mask[t1+1:emb_end+1] = False
        train_idx = np.where(train_mask)[0]
        splits.append((train_idx, test))
    return splits


# ─────────────────────────────────────────────────────────────────────────────
# SEZIONE 6 — BLOCK BOOTSTRAP
# ─────────────────────────────────────────────────────────────────────────────

def block_bootstrap(r, fn, block=10, n_boot=2000, seed=42):
    """Bootstrap a blocchi per preservare autocorrelazione. Ritorna array di stime."""
    rng  = np.random.default_rng(seed)
    r    = np.asarray(r, float)
    T    = len(r)
    starts_all = np.arange(max(1, T-block+1))
    out  = np.empty(n_boot)
    n_bl = int(np.ceil(T/block))
    for b in range(n_boot):
        idx   = rng.choice(starts_all, n_bl, replace=True)
        samp  = np.concatenate([r[s:s+block] for s in idx])[:T]
        out[b] = fn(samp)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# SEZIONE 7 — COSTRUZIONE SEGNALI (no lookahead: ingresso all'open t+1)
# ─────────────────────────────────────────────────────────────────────────────

def build_signals(px, score_fn, horizons=(5, 10, 20),
                  step=5, comm_bps=5.0, slip_bps=2.0, pit_data=None):
    """
    Costruisce i segnali con fill realistico:
    - score calcolato al close di t (usa dati fino a t incluso)
    - ingresso simulato al close di t+1 (evita lookahead)
    - rendimento misurato da close(t+1) a close(t+1+hz)
    - costi: commissioni + slippage in bps (round-trip)
    - pit_data: se fornito, aggiunge pit_quality (fondamentali PIT point-in-time)
    """
    cost = (comm_bps + slip_bps) / 1e4 * 2     # round-trip
    recs = []
    for tk in px["ticker"].unique():
        g = (px[px["ticker"] == tk]
             .sort_values("date")
             .dropna(subset=["close"])
             .reset_index(drop=True))
        if len(g) < 230:
            continue
        c, h, l, o = g["close"], g["high"], g["low"], g["open"]
        dates = g["date"]
        for t in range(200, len(g) - max(horizons) - 1, step):
            s = score_fn(c, h, l, t)
            if s is None:
                continue
            entry = float(c.iloc[t+1])
            rec   = {"ticker": tk, "t": t+1, "date": dates.iloc[t+1], "score": s}
            for hz in horizons:
                if t+1+hz >= len(g):
                    continue
                exit_px = float(c.iloc[t+1+hz])
                ret_gross = (exit_px/entry - 1)
                ret_net   = ret_gross - cost
                rec[f"fwd_{hz}_gross"] = ret_gross * 100
                rec[f"fwd_{hz}_net"]   = ret_net   * 100
            if pit_data:
                pit_row = pit_lookup(pit_data, tk, dates.iloc[t+1])
                rec["pit_quality"] = pit_quality_score(pit_row)
                if pit_row is not None:
                    rec["pit_net_margin"] = pit_row.get("net_margin")
                    rec["pit_current_ratio"] = pit_row.get("current_ratio")
                    rec["pit_roe"] = pit_row.get("roe")
            recs.append(rec)
    return pd.DataFrame(recs)


# ─────────────────────────────────────────────────────────────────────────────
# SEZIONE 8 — SIMULAZIONE PORTAFOGLIO (equity line, drawdown)
# ─────────────────────────────────────────────────────────────────────────────

def portfolio_sim(signals, col, top_q=0.80, capital=100_000):
    if signals.empty or col not in signals.columns:
        return None
    sig = signals.copy().sort_values("date")
    thr = sig["score"].quantile(top_q)
    sel = sig[sig["score"] >= thr].copy()
    if sel.empty:
        return None
    rets = sel.groupby("date")[col].mean() / 100.0
    eq   = (1 + rets).cumprod() * capital
    peak = eq.cummax()
    dd   = (eq/peak - 1)
    return {"rets": rets, "equity": eq, "dd": dd,
            "n": len(sel), "thr": float(thr)}


# ─────────────────────────────────────────────────────────────────────────────
# SEZIONE 9 — PERFORMANCE PER REGIME
# ─────────────────────────────────────────────────────────────────────────────

def regime_analysis(signals, px, col, sma_window=200):
    """Segmenta i segnali per regime bull/bear dell'indice (proxy: ^GSPC, fallback SPY).

    NB: si usa UN SOLO benchmark e si deduplica per data. Usare più ticker
    (es. SPY + ^GSPC insieme) creava un indice-data duplicato: il join espandeva
    ogni segnale in più righe (una per benchmark) e, con regimi discordi, le
    partizioni bull e bear diventavano copie quasi identiche dell'intero set
    (n_bull == n_bear == n_totale). Inoltre rolling(200) su due serie con scale
    diverse interlacciate rendeva la SMA priva di senso.
    """
    bench = pd.DataFrame()
    for cand in ["^GSPC", "SPY"]:
        cand_df = px[px["ticker"] == cand]
        if not cand_df.empty:
            bench = cand_df.copy()
            break
    if bench.empty:
        return None
    bench = (bench.sort_values("date").dropna(subset=["close"])
                  .drop_duplicates("date"))
    bench["sma"] = bench["close"].rolling(sma_window).mean()
    bench["regime"] = np.where(bench["close"] > bench["sma"], "bull", "bear")
    bench = bench[["date","regime"]].set_index("date")
    sig   = signals.copy()
    sig   = sig.join(bench["regime"], on="date", how="left")
    sig["regime"] = sig["regime"].fillna("unknown")
    out = {}
    for reg in ["bull","bear","unknown"]:
        sub = sig[sig["regime"]==reg]
        if len(sub) < 5:
            continue
        r = sub[col].values / 100.0
        m = perf_metrics(r, label=reg)
        m["n_signals"] = len(sub)
        out[reg] = m
    return out


# ─────────────────────────────────────────────────────────────────────────────
# SEZIONE 10 — WALK-FORWARD ANALYSIS
# ─────────────────────────────────────────────────────────────────────────────

def walk_forward(signals, col, hz, n_windows=6, top_q=0.80):
    """Walk-forward anchored: IS fisso che cresce, OOS sequenziale."""
    if signals.empty or col not in signals.columns:
        return None
    sig   = signals.sort_values("date").dropna(subset=[col])
    dates = sig["date"].values
    T     = len(sig)
    size  = T // (n_windows + 1)
    if size < 10:
        return None
    is_rets, oos_rets = [], []
    for w in range(n_windows):
        is_end  = size*(w+1)
        oos_end = min(size*(w+2), T)
        is_sig  = sig.iloc[:is_end]
        oos_sig = sig.iloc[is_end:oos_end]
        thr     = is_sig["score"].quantile(top_q)
        is_r    = is_sig[is_sig["score"]>=thr][col].values/100
        oos_r   = oos_sig[oos_sig["score"]>=thr][col].values/100
        if len(is_r) > 0:
            is_rets.append(is_r.mean())
        if len(oos_r) > 0:
            oos_rets.append(oos_r.mean())
    if not is_rets or not oos_rets:
        return None
    wfe = np.mean(oos_rets) / np.mean(is_rets) if np.mean(is_rets) != 0 else np.nan
    return {"WFE": float(wfe),
            "mean_IS_ret": float(np.mean(is_rets)*100),
            "mean_OOS_ret": float(np.mean(oos_rets)*100),
            "n_windows": n_windows}


# ─────────────────────────────────────────────────────────────────────────────
# SEZIONE 11 — ORCHESTRATORE PRINCIPALE
# ─────────────────────────────────────────────────────────────────────────────

def run(px_path="data/mib_data.csv",
        out_csv="data/backtest_report.csv",
        out_txt="data/backtest_summary.txt",
        pit_path="data/fundamentals_pit_history.csv"):

    px = pd.read_csv(px_path)
    px["date"] = pd.to_datetime(px["date"])
    px = px.dropna(subset=["close"])
    print(f"[backtest] {len(px)} righe caricati, {px['ticker'].nunique()} ticker", flush=True)

    pit_data = load_pit(pit_path)
    print(f"[backtest] PIT fondamentali: {len(pit_data)} ticker caricati", flush=True)

    horizons = (5, 10, 20)
    lines    = []          # raccoglie il report testuale
    all_dfs  = {}

    def log(s=""):
        lines.append(s); print(s, flush=True)

    log("="*70)
    log("BACKTEST ISTITUZIONALE v3 — Swing Copilot EU+USA")
    log(f"Dati: {px['date'].min().date()} → {px['date'].max().date()}")
    log(f"Ticker: {px['ticker'].nunique()} | Orizzonti: {horizons}")
    if pit_data:
        log(f"Fondamentali PIT: {len(pit_data)} ticker SEC EDGAR (point-in-time)")
    log("="*70)

    for name, sfn in [("VECCHIO", score_old), ("NUOVO", score_new)]:
        log(f"\n>>> COSTRUZIONE SEGNALI — score {name} <<<")
        sig = build_signals(px, sfn, horizons=horizons, pit_data=pit_data or None)
        all_dfs[name] = sig
        log(f"    Segnali prodotti: {len(sig)}")
        if pit_data and "pit_quality" in sig.columns:
            n_pit = sig["pit_quality"].notna().sum()
            log(f"    Con fondamentali PIT: {n_pit} ({n_pit*100/len(sig):.0f}%)")

    # ── CONFRONTO POTERE PREDITTIVO ──────────────────────────────────────────
    log("\n" + "─"*70)
    log("1. CORRELAZIONE SPEARMAN score↔rendimento (netto)")
    log("─"*70)
    log(f"{'':12s} {'VECCHIO':>12s} {'NUOVO':>12s}")
    for hz in horizons:
        col = f"fwd_{hz}_net"
        co = all_dfs["VECCHIO"][["score",col]].dropna().corr(method="spearman").iloc[0,1]
        cn = all_dfs["NUOVO"][["score",col]].dropna().corr(method="spearman").iloc[0,1]
        log(f"  {hz:>2d}gg netto   {co:>+12.4f} {cn:>+12.4f}")

    # ── SIMULAZIONE PORTAFOGLIO (hold 10gg netto) ────────────────────────────
    log("\n" + "─"*70)
    log("2. SIMULAZIONE PORTAFOGLIO (hold 10gg, top 20%, netto)")
    log("─"*70)
    all_sharpes = {"VECCHIO": [], "NUOVO": []}
    for name in ["VECCHIO","NUOVO"]:
        sig = all_dfs[name]; col = "fwd_10_net"
        r   = portfolio_sim(sig, col)
        if r is None:
            log(f"  {name}: nessun dato"); continue
        m = perf_metrics(r["rets"].values, ann=252/10, label=name)
        all_sharpes[name].append(m.get("Sharpe_ann", np.nan))
        log(f"\n  SCORE {name}:")
        log(f"    Trade:          {r['n']}")
        log(f"    Profitto netto: {(r['equity'].iloc[-1]/100_000-1)*100:+.1f}%")
        log(f"    Equity finale:  €{r['equity'].iloc[-1]:,.0f}")
        log(f"    Max Drawdown:   {r['dd'].min()*100:.1f}%")
        log(f"    Sharpe ann:     {m.get('Sharpe_ann',np.nan):+.2f}")
        log(f"    Sortino ann:    {m.get('Sortino_ann',np.nan):+.2f}")
        log(f"    Calmar:         {m.get('Calmar',np.nan):+.2f}")
        log(f"    Profit Factor:  {m.get('ProfitFactor',np.nan):.2f}")
        log(f"    Expectancy:     {m.get('Expectancy_pct',np.nan):+.3f}%")
        log(f"    Win Rate:       {m.get('WinRate_pct',np.nan):.1f}%")
        log(f"    CVaR 95%:       {m.get('CVaR95_pct',np.nan):.2f}%")
        log(f"    Max Consec.Loss:{m.get('MaxConsecLoss',np.nan)}")
        log(f"    Time Underwater:{m.get('TimeUnderwater_bars',np.nan)} barre")
        log(f"    Recovery Factor:{m.get('RecoveryFactor',np.nan):.2f}")
        log(f"    Tail Ratio:     {m.get('TailRatio',np.nan):.2f}")

    # ── DEFLATED SHARPE RATIO ────────────────────────────────────────────────
    log("\n" + "─"*70)
    log("3. DEFLATED SHARPE RATIO (correzione multiple testing)")
    log("─"*70)
    holdlist  = [5, 10, 20]
    threshlist = [0.70, 0.75, 0.80, 0.85, 0.90]
    for name in ["VECCHIO","NUOVO"]:
        sig = all_dfs[name]
        sr_all = []
        for hz in holdlist:
            col = f"fwd_{hz}_net"
            if col not in sig.columns: continue
            for tq in threshlist:
                thr = sig["score"].quantile(tq)
                r   = sig[sig["score"]>=thr][col].dropna().values/100
                if len(r) < 10: continue
                sr_raw = r.mean()/(r.std(ddof=1)+1e-12)
                sr_all.append(sr_raw)
        col = "fwd_10_net"
        r_main = sig[sig["score"]>=sig["score"].quantile(0.80)][col].dropna().values/100
        if len(r_main) > 10 and len(sr_all) > 1:
            dsr, sr0 = deflated_sharpe(r_main, sr_all)
            psr_val  = psr(r_main)
            mtrl     = min_track_record_length(r_main)
            log(f"\n  {name}: N_configurazioni={len(sr_all)}, SR₀={sr0:+.3f}")
            log(f"    PSR(bench=0): {psr_val:.3f}  (soglia >0.95)")
            log(f"    DSR:          {dsr:.3f}  (soglia >0.95 → {'✓ PASSA' if dsr>0.95 else '✗ NON PASSA'})")
            log(f"    MinTRL:       {mtrl:.0f} barre ({mtrl/252:.1f} anni)")

    # ── WALK-FORWARD EFFICIENCY ──────────────────────────────────────────────
    log("\n" + "─"*70)
    log("4. WALK-FORWARD ANALYSIS (anchored, 6 finestre)")
    log("─"*70)
    for name in ["VECCHIO","NUOVO"]:
        wf = walk_forward(all_dfs[name], "fwd_10_net", hz=10)
        if wf:
            log(f"  {name}: WFE={wf['WFE']:+.2f} (soglia >0.50)")
            log(f"    Ret medio IS: {wf['mean_IS_ret']:+.3f}%")
            log(f"    Ret medio OOS: {wf['mean_OOS_ret']:+.3f}%")

    # ── PBO (CSCV) ────────────────────────────────────────────────────────────
    log("\n" + "─"*70)
    log("5. PROBABILITY OF BACKTEST OVERFITTING (CSCV, S=8)")
    log("─"*70)
    for name in ["VECCHIO","NUOVO"]:
        sig = all_dfs[name]
        cols_num = [f"fwd_{h}_net" for h in holdlist if f"fwd_{h}_net" in sig.columns]
        if len(cols_num) < 2: continue
        sig_clean = sig[cols_num].dropna()
        if len(sig_clean) < 16: continue
        M = sig_clean.values
        pbo = pbo_cscv(M, S=min(8, len(cols_num)*2))
        log(f"  {name}: PBO={pbo:.3f}  (soglia <0.50 → {'✓ OK' if pbo<0.5 else '✗ OVERFIT sospetto'})")

    # ── BLOCK BOOTSTRAP ────────────────────────────────────────────────────────
    log("\n" + "─"*70)
    log("6. BLOCK BOOTSTRAP (IC 95% su Sharpe e MaxDD, score NUOVO)")
    log("─"*70)
    sig  = all_dfs["NUOVO"]
    col  = "fwd_10_net"
    r_bt = sig[sig["score"]>=sig["score"].quantile(0.80)][col].dropna().values/100
    if len(r_bt) > 20:
        sr_fn  = lambda r: r.mean()/(r.std(ddof=1)+1e-12)*np.sqrt(252/10)
        dd_fn  = lambda r: ((1+pd.Series(r)).cumprod()/
                            (1+pd.Series(r)).cumprod().cummax()-1).min()*100
        sr_bs  = block_bootstrap(r_bt, sr_fn, block=10)
        dd_bs  = block_bootstrap(r_bt, dd_fn, block=10)
        log(f"  Sharpe ann: stima {sr_fn(r_bt):+.2f} | IC95% [{np.percentile(sr_bs,2.5):+.2f}, {np.percentile(sr_bs,97.5):+.2f}]")
        log(f"  MaxDD:      stima {dd_fn(r_bt):.1f}% | IC95% [{np.percentile(dd_bs,2.5):.1f}%, {np.percentile(dd_bs,97.5):.1f}%]")

    # ── PERFORMANCE PER REGIME ────────────────────────────────────────────────
    log("\n" + "─"*70)
    log("7. PERFORMANCE PER REGIME (bull / bear via SPY/SMA200) — sul PORTAFOGLIO selezionato")
    log("─"*70)
    for name in ["VECCHIO","NUOVO"]:
        # Si segmenta il portafoglio EFFETTIVAMENTE selezionato (top-quintile dello score),
        # non tutti i segnali: altrimenti VECCHIO e NUOVO risultano identici e la diagnosi
        # non riflette la strategia realmente operata.
        s_all = all_dfs[name]
        sel = s_all[s_all["score"] >= s_all["score"].quantile(0.80)]
        reg = regime_analysis(sel, px, "fwd_10_net")
        if reg:
            log(f"\n  {name}:")
            for r_name, m in reg.items():
                log(f"    {r_name:8s}: n={m.get('n_signals',0):4d} | ret {m.get('Expectancy_pct',0):+.3f}% | hit {m.get('WinRate_pct',0):.1f}% | Sharpe {m.get('Sharpe_ann',np.nan):+.2f}")

    # ── SENSITIVITY HEATMAP (testo) ───────────────────────────────────────────
    log("\n" + "─"*70)
    log("8. SENSITIVITY — Sharpe netto (griglia holding × soglia, score NUOVO)")
    log("─"*70)
    sig = all_dfs["NUOVO"]
    header = f"{'':10s}" + "".join(f"  tq={tq:.2f}" for tq in threshlist)
    log(header)
    for hz in holdlist:
        col = f"fwd_{hz}_net"
        if col not in sig.columns: continue
        row = f"  hold={hz:2d}gg "
        for tq in threshlist:
            thr = sig["score"].quantile(tq)
            r   = sig[sig["score"]>=thr][col].dropna().values/100
            if len(r) < 5:
                row += f"{'N/A':>10s}"
            else:
                sr = r.mean()/(r.std(ddof=1)+1e-12)*np.sqrt(252/hz)
                row += f"  {sr:>+7.2f} "
        log(row)

    # ── FONDAMENTALI POINT-IN-TIME (SEC EDGAR) ──────────────────────────────
    if pit_data and "pit_quality" in all_dfs.get("NUOVO", pd.DataFrame()).columns:
        log("\n" + "─"*70)
        log("9. FONDAMENTALI POINT-IN-TIME (SEC EDGAR) — filtro qualita' sul score NUOVO")
        log("─"*70)
        sig = all_dfs["NUOVO"].copy()
        col = "fwd_10_net"
        if col in sig.columns:
            has_pit = sig["pit_quality"].notna()
            log(f"  Segnali con PIT: {has_pit.sum()}/{len(sig)} ({has_pit.mean()*100:.0f}%)")
            thr = sig["score"].quantile(0.80)
            top = sig[sig["score"] >= thr].copy()

            # a) Correlazione pit_quality vs forward return
            pit_top = top[top["pit_quality"].notna()]
            if len(pit_top) > 10:
                corr = pit_top[["pit_quality", col]].corr(method="spearman").iloc[0, 1]
                log(f"\n  Spearman pit_quality ↔ fwd_10_net (top quintile): {corr:+.4f}")

            # b) Performance per terzile di qualita' PIT
            if len(pit_top) > 20:
                log(f"\n  Performance per terzile qualita' PIT (top quintile, hold 10gg):")
                log(f"  {'terzile':>10s} {'n':>6s} {'ret%':>8s} {'win%':>8s} {'Sharpe':>8s}")
                try:
                    pit_top["pit_tercile"] = pd.qcut(pit_top["pit_quality"], 3,
                                                      labels=["bassa", "media", "alta"],
                                                      duplicates="drop")
                    for terc in ["bassa", "media", "alta"]:
                        sub = pit_top[pit_top["pit_tercile"] == terc]
                        if len(sub) < 5:
                            continue
                        r = sub[col].values / 100.0
                        mu = r.mean() * 100
                        wr = (r > 0).mean() * 100
                        sr = (r.mean() / (r.std(ddof=1) + 1e-12)) * np.sqrt(252 / 10)
                        log(f"  {terc:>10s} {len(sub):>6d} {mu:>+8.3f} {wr:>8.1f} {sr:>+8.2f}")
                except Exception:
                    log("  (terzili non calcolabili: troppo pochi valori distinti)")

            # c) Confronto: top quintile CON vs SENZA filtro qualita' PIT
            if len(pit_top) > 20:
                log(f"\n  Confronto top quintile: tutti vs qualita' PIT >= 0.60:")
                for label, subset in [("tutti", top),
                                       ("PIT >= 0.60", top[top["pit_quality"] >= 0.60]),
                                       ("PIT >= 0.80", top[top["pit_quality"] >= 0.80])]:
                    if len(subset) < 5:
                        log(f"    {label:>15s}: N/A (n={len(subset)})")
                        continue
                    r = subset[col].values / 100.0
                    mu = r.mean() * 100
                    wr = (r > 0).mean() * 100
                    sr = (r.mean() / (r.std(ddof=1) + 1e-12)) * np.sqrt(252 / 10)
                    log(f"    {label:>15s}: n={len(subset):>4d} ret={mu:+.3f}% win={wr:.1f}% Sharpe={sr:+.2f}")

            # d) Net margin come filtro: profittevoli vs non profittevoli
            if "pit_net_margin" in top.columns:
                top_nm = top[top["pit_net_margin"].notna()].copy()
                if len(top_nm) > 20:
                    log(f"\n  Net margin come filtro (top quintile):")
                    for label, mask in [("nm > 0 (profittevole)", top_nm["pit_net_margin"].astype(float) > 0),
                                         ("nm >= 10%", top_nm["pit_net_margin"].astype(float) >= 0.10),
                                         ("nm < 0 (in perdita)", top_nm["pit_net_margin"].astype(float) < 0)]:
                        sub = top_nm[mask]
                        if len(sub) < 3:
                            continue
                        r = sub[col].values / 100.0
                        mu = r.mean() * 100
                        wr = (r > 0).mean() * 100
                        log(f"    {label:>25s}: n={len(sub):>4d} ret={mu:+.3f}% win={wr:.1f}%")

    # ── SALVATAGGIO ──────────────────────────────────────────────────────────
    os.makedirs(os.path.dirname(out_csv), exist_ok=True)
    combined = []
    for name, df in all_dfs.items():
        df = df.copy(); df["score_version"] = name
        combined.append(df)
    pd.concat(combined, ignore_index=True).to_csv(out_csv, index=False)
    with open(out_txt, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    log(f"\n[backtest] Salvato {out_csv}")
    log(f"[backtest] Salvato {out_txt}")
    log("="*70)


if __name__ == "__main__":
    run()
