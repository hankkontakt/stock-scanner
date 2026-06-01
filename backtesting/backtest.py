"""
backtest.py
===========
Testar hur scoringmodellen hade presterat historiskt.

Princip:
  För varje månad bakåt i tid (t.ex. 2020-2024):
  1. Hämta historisk prisdata
  2. Beräkna scoring-faktorer baserat på DATA SOM FANNS DÅ
  3. Välj topp-N aktier
  4. Mät faktisk avkastning nästa period
  5. Jämför mot index (S&P 500 = SPY, OMX = ^OMX)

Varning: Vi kan bara backtesta tekniska/prisfaktorer korrekt
(momentum, MA, RSI) eftersom fundamental data (P/E, ROE etc.)
inte är tillgänglig historiskt via yfinance gratisnivån.
En "momentum-only" backtest är ändå värdefull.

Kör med:
  python backtest.py
  python backtest.py --years 3 --top 20
"""

import argparse
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

from core import config


# ═══════════════════════════════════════════════════════════════
# KONFIGURATION
# ═══════════════════════════════════════════════════════════════

BACKTEST_TICKERS   = config.UNIVERSE[:20]    # Begränsa för hastighet & reliability
REBALANCE_FREQ     = "ME"                    # Månatlig rebalansering
HOLDING_PERIOD_DAYS = 21                     # ~1 månad
BENCHMARK          = "SPY"                   # S&P 500 ETF som jämförelse
TOP_N              = 20                      # Antal aktier i "portföljen"
LOOKBACK_YEARS     = 3                       # År att backtesta


# ═══════════════════════════════════════════════════════════════
# DATAHÄMTNING
# ═══════════════════════════════════════════════════════════════

def fetch_all_prices(tickers: list, years: int = 4) -> pd.DataFrame:
    """
    Hämtar prishistorik EN AKTIE I TAGET (mer robust mot timeouts).
    Returnerar DataFrame med adjusted close prices.
    """
    import time as _time
    print(f"  Laddar ned prisdata för {len(tickers)} aktier ({years} år)...")
    period = f"{years+1}y"
    
    all_data = {}
    failed = 0
    for i, ticker in enumerate(tickers):
        try:
            data = yf.download(ticker, period=period, auto_adjust=True, progress=False)
            if data is not None and not data.empty:
                close = data["Close"] if "Close" in data.columns else data.iloc[:, 0]
                if isinstance(close, pd.DataFrame):
                    close = close.iloc[:, 0]
                all_data[ticker] = close
            else:
                failed += 1
        except Exception:
            failed += 1
        # Visa progress var 10:e ticker
        if (i + 1) % 10 == 0:
            print(f"    {i+1}/{len(tickers)} ({failed} misslyckades)...")
        _time.sleep(0.15)  # Rate limiting
    
    if not all_data:
        print(f"  ⚠ Alla {len(tickers)} aktier misslyckades!")
        return pd.DataFrame()
    
    prices = pd.DataFrame(all_data)
    # Ta bort aktier med för lite data
    min_rows = 252 * years * 0.7
    prices = prices.dropna(axis=1, thresh=int(min_rows))
    
    print(f"  ✓ Prisdata hämtad: {len(prices.columns)}/{len(tickers)} aktier x {len(prices)} dagar ({failed} misslyckades)")
    return prices


# ═══════════════════════════════════════════════════════════════
# TEKNISK SCORING (historisk)
# ═══════════════════════════════════════════════════════════════

def score_at_date(prices: pd.DataFrame, date: pd.Timestamp) -> pd.Series:
    """
    Beräknar teknisk momentum-score för alla aktier vid ett givet datum.
    Använder bara data som var tillgänglig vid det datumet (ingen look-ahead).

    Score bygger på:
    - 12m momentum (40%)
    - 6m momentum  (30%)
    - 3m momentum  (20%)
    - Avstånd från 52v-high (10%)
    """
    # Historisk data fram till (men INTE inkl.) det aktuella datumet - undviker look-ahead bias
    hist = prices[prices.index < date].copy()

    if len(hist) < 63:  # Minst 3 månader data
        return pd.Series(dtype=float)

    current = hist.iloc[-1]
    scores  = {}

    for ticker in hist.columns:
        try:
            close = hist[ticker].dropna()
            if len(close) < 63:
                continue

            price_now = close.iloc[-1]

            # Returns
            r12 = (price_now / close.iloc[-252]) - 1 if len(close) >= 252 else None
            r6  = (price_now / close.iloc[-126]) - 1 if len(close) >= 126 else None
            r3  = (price_now / close.iloc[-63])  - 1 if len(close) >= 63  else None

            # Avstånd från 52v-high
            high_52w    = close.tail(252).max()
            pct_fr_high = (price_now / high_52w) - 1 if high_52w > 0 else None

            scores[ticker] = {
                "r12":         r12,
                "r6":          r6,
                "r3":          r3,
                "pct_fr_high": pct_fr_high,
            }
        except Exception:
            continue

    if not scores:
        return pd.Series(dtype=float)

    score_df = pd.DataFrame(scores).T

    # Percentil-rank varje komponent
    composite = pd.Series(50.0, index=score_df.index)
    weights   = {"r12": 0.4, "r6": 0.3, "r3": 0.2, "pct_fr_high": 0.1}

    total_weight = 0
    for col, w in weights.items():
        if col in score_df.columns and score_df[col].notna().sum() > 3:
            ranked       = score_df[col].rank(pct=True) * 100
            composite   += w * ranked
            total_weight += w

    if total_weight > 0:
        composite /= total_weight

    return composite.sort_values(ascending=False)


# ═══════════════════════════════════════════════════════════════
# BACKTEST-LOOP
# ═══════════════════════════════════════════════════════════════

def run_backtest(
    tickers:    list  = BACKTEST_TICKERS,
    years:      int   = BACKTEST_YEARS if 'BACKTEST_YEARS' in dir() else BACKTEST_TICKERS and 3,
    top_n:      int   = TOP_N,
    benchmark:  str   = BENCHMARK,
    verbose:    bool  = True,
) -> dict:
    """
    Kör komplett backtest och returnerar resultat.
    """
    years = years or LOOKBACK_YEARS

    # Hämta all prisdata
    prices = fetch_all_prices(tickers, years=years + 1)
    if prices.empty:
        return {}

    # Hämta benchmark - säkerställ att bench_prices alltid är en 1D Series
    # (nya yfinance-versioner returnerar MultiIndex-DataFrame för "Close")
    bench_data = yf.download(benchmark, period=f"{years+1}y", auto_adjust=True, progress=False)
    bench_prices = None
    if not bench_data.empty:
        _bc = bench_data["Close"] if "Close" in bench_data.columns else bench_data.iloc[:, 0]
        bench_prices = _bc.iloc[:, 0] if isinstance(_bc, pd.DataFrame) else _bc

    # Skapa rebalanserings-datum (månatliga)
    end_date   = prices.index[-1]
    start_date = end_date - pd.DateOffset(years=years)
    dates      = pd.date_range(start=start_date, end=end_date, freq=REBALANCE_FREQ)
    dates      = [d for d in dates if d in prices.index or any(prices.index >= d)]

    if verbose:
        print(f"\n  📅 Rebalanserar {len(dates)} gånger ({years} år)")
        print(f"  🎯 Väljer topp-{top_n} aktier per period\n")

    # Backtest-loop
    portfolio_returns = []
    benchmark_returns = []
    period_details    = []

    for i in range(len(dates) - 1):
        date_now  = dates[i]
        date_next = dates[i + 1]

        # Score alla aktier vid date_now
        scores = score_at_date(prices, date_now)
        if scores.empty:
            continue

        # Välj topp-N
        top_tickers = scores.head(top_n).index.tolist()
        valid       = [t for t in top_tickers if t in prices.columns]

        if not valid:
            continue

        # Mät avkastning date_now -> date_next
        try:
            # Hitta närmaste handelsdag
            avail_now  = prices.index[prices.index >= date_now][0]
            avail_next = prices.index[prices.index >= date_next][0]

            period_prices = prices.loc[avail_now:avail_next, valid]
            if period_prices.empty or len(period_prices) < 2:
                continue

            # Likaviktad portfölj-avkastning
            start_p = period_prices.iloc[0]
            end_p   = period_prices.iloc[-1]
            # .mean().mean() hanterar både Series och DataFrame (MultiIndex)
            gross_ret = ((end_p / start_p) - 1).mean().mean()

            # Transaktionskostnad: uppskatta omsättning vs förra perioden
            prev_tickers = set(period_details[-1]["top_tickers"].split(", ")) if period_details else set()
            turnover = len(set(valid) - prev_tickers) / max(len(valid), 1)
            # 0.10 % per trade, köp + sälj = 0.20 % per omsatt position
            tx_cost = turnover * 0.002
            ret = gross_ret - tx_cost

            portfolio_returns.append(ret)

            # Benchmark-avkastning - initieras till None för att undvika NameError
            bench_ret = None
            if bench_prices is not None:
                try:
                    b_now  = bench_prices[bench_prices.index >= avail_now].iloc[0]
                    b_next = bench_prices[bench_prices.index >= avail_next].iloc[0]
                    bench_ret = (b_next / b_now) - 1
                except Exception:
                    pass
            benchmark_returns.append(bench_ret)

            period_details.append({
                "period":          date_now.strftime("%Y-%m"),
                "portfolio_ret":   round(ret * 100, 2),
                "benchmark_ret":   round(bench_ret * 100, 2) if bench_ret is not None else None,
                "alpha":           round((ret - (bench_ret or 0)) * 100, 2),
                "top_tickers":     ", ".join(valid[:5]),
            })

        except Exception as e:
            if verbose:
                print(f"  ⚠ Fel period {date_now.date()}: {e}")
            continue

    if not portfolio_returns:
        print("  ❌ Inga resultat - försök med fler aktier eller kortare period")
        return {"perioder": 0, "period_details": []}

    # Beräkna statistik
    port_arr = np.array(portfolio_returns)
    bench_arr = np.array([r for r in benchmark_returns if r is not None])

    # Kumulativ avkastning
    cum_port  = np.prod(1 + port_arr) - 1
    cum_bench = np.prod(1 + bench_arr) - 1 if len(bench_arr) > 0 else None

    # Annualiserad
    n_years   = len(port_arr) / 12
    ann_port  = (1 + cum_port)  ** (1 / n_years) - 1 if n_years > 0 else 0
    ann_bench = (1 + cum_bench) ** (1 / n_years) - 1 if (cum_bench is not None and n_years > 0) else None

    # Sharpe ratio - subtraherar riskfri ränta (~4 % per år = 0.33 %/mån)
    rf_monthly = 0.04 / 12
    sharpe = ((port_arr.mean() - rf_monthly) / port_arr.std() * np.sqrt(12)) if port_arr.std() > 0 else 0

    # Hit rate (% perioder som slog benchmark)
    hit_rate = None
    if len(bench_arr) == len(port_arr):
        hit_rate = (port_arr > bench_arr).mean()

    # Max drawdown
    cum_values = np.cumprod(1 + port_arr)
    rolling_max = np.maximum.accumulate(cum_values)
    drawdowns   = (cum_values - rolling_max) / rolling_max
    max_dd      = drawdowns.min()

    results = {
        "perioder":             len(port_arr),
        "år_testat":            round(n_years, 1),
        "kumulativ_avkastning": round(cum_port  * 100, 1),
        "kumulativ_benchmark":  round(cum_bench * 100, 1) if cum_bench is not None else None,
        "annualiserad_port":    round(ann_port  * 100, 1),
        "annualiserad_bench":   round(ann_bench * 100, 1) if ann_bench is not None else None,
        "alpha_annualiserad":   round((ann_port - (ann_bench or 0)) * 100, 1) if ann_bench else None,
        "sharpe_ratio":         round(sharpe, 2),
        "hit_rate_pct":         round(hit_rate * 100, 1) if hit_rate is not None else None,
        "max_drawdown_pct":     round(max_dd * 100, 1),
        "snitt_månadsret":      round(port_arr.mean() * 100, 2),
        "period_details":       period_details,  # list of dicts -- UI converts to DataFrame
    }

    return results


# ═══════════════════════════════════════════════════════════════
# OUTPUT
# ═══════════════════════════════════════════════════════════════

def print_backtest_results(results: dict):
    """Skriv ut backtest-resultaten i ett läsbart format."""
    if not results:
        return

    print("\n" + "═" * 60)
    print("📊 BACKTEST-RESULTAT")
    print("═" * 60)
    print(f"  Period testad:        {results['år_testat']} år ({results['perioder']} månader)")
    print(f"  Kumulativ avkastning: {results['kumulativ_avkastning']:+.1f}%")
    if results.get("kumulativ_benchmark"):
        print(f"  Benchmark (SPY):      {results['kumulativ_benchmark']:+.1f}%")
    print(f"")
    print(f"  Annualiserad (port):  {results['annualiserad_port']:+.1f}%/år")
    if results.get("annualiserad_bench"):
        print(f"  Annualiserad (bench): {results['annualiserad_bench']:+.1f}%/år")
    if results.get("alpha_annualiserad") is not None:
        print(f"  Alpha (överprestanda):{results['alpha_annualiserad']:+.1f}%/år")
    print(f"")
    print(f"  Sharpe ratio:         {results['sharpe_ratio']:.2f}  (>1.0 = bra)")
    if results.get("hit_rate_pct"):
        print(f"  Hit rate vs bench:    {results['hit_rate_pct']:.0f}%  (>50% = slår index)")
    print(f"  Max drawdown:         {results['max_drawdown_pct']:.1f}%")
    print(f"  Snitt månadsavkastning:{results['snitt_månadsret']:+.2f}%")
    print("═" * 60)

    # Spara detaljerad rapport
    if "period_details" in results and not results["period_details"].empty:
        report_dir = Path(config.REPORT_DIR)
        report_dir.mkdir(exist_ok=True)
        date_str   = datetime.now().strftime("%Y-%m-%d")
        csv_path   = report_dir / f"backtest_{date_str}.csv"
        results["period_details"].to_csv(csv_path, index=False)
        print(f"\n  💾 Detaljerad rapport sparad: {csv_path}")


def save_backtest_markdown(results: dict):
    """Genererar en markdown-rapport av backtestet för Claude Pro."""
    if not results:
        return

    lines = ["# 📊 Backtest-rapport\n"]
    lines.append(f"**Period:** {results['år_testat']} år ({results['perioder']} månader)  ")
    lines.append(f"**Benchmark:** SPY (S&P 500 ETF)\n")
    lines.append("## Sammanfattning\n")
    lines.append("| Metric | Modell | Benchmark |")
    lines.append("|--------|--------|-----------|")
    lines.append(f"| Kumulativ avkastning | **{results['kumulativ_avkastning']:+.1f}%** | {results.get('kumulativ_benchmark', 'N/A')}% |")
    lines.append(f"| Annualiserad | **{results['annualiserad_port']:+.1f}%/år** | {results.get('annualiserad_bench', 'N/A')}%/år |")
    lines.append(f"| Sharpe ratio | **{results['sharpe_ratio']:.2f}** | ~0.8 (historiskt SPY) |")
    lines.append(f"| Hit rate vs benchmark | **{results.get('hit_rate_pct', 'N/A')}%** | 50% |")
    lines.append(f"| Max drawdown | **{results['max_drawdown_pct']:.1f}%** | ~-35% (2020) |")

    if "period_details" in results:
        lines.append("\n## Per period\n")
        lines.append("| Period | Portfölj | Benchmark | Alpha | Topp-5 |")
        lines.append("|--------|----------|-----------|-------|--------|")
        for _, row in results["period_details"].tail(24).iterrows():
            lines.append(
                f"| {row['period']} | {row['portfolio_ret']:+.1f}% | "
                f"{row.get('benchmark_ret', '-')}% | "
                f"{row.get('alpha', '-'):+.1f}% | "
                f"{row.get('top_tickers', '')[:40]} |"
            )

    report_dir = Path(config.REPORT_DIR)
    report_dir.mkdir(exist_ok=True)
    date_str   = datetime.now().strftime("%Y-%m-%d")
    path       = report_dir / f"backtest_report_{date_str}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  📝 Markdown-rapport: {path}")
    return str(path)


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backtest av aktiescannerens scoringmodell")
    parser.add_argument("--years", type=int, default=3,  help="Antal år att backtesta (default: 3)")
    parser.add_argument("--top",   type=int, default=20, help="Antal aktier i portföljen (default: 20)")
    parser.add_argument("--bench", type=str, default="SPY", help="Benchmark-ticker (default: SPY)")
    args = parser.parse_args()

    print(f"\n🔬 Startar backtest...")
    print(f"   Testar: {args.years} år, topp-{args.top} aktier, benchmark: {args.bench}")
    print(f"   Universum: {len(BACKTEST_TICKERS)} aktier\n")

    results = run_backtest(
        tickers   = BACKTEST_TICKERS,
        years     = args.years,
        top_n     = args.top,
        benchmark = args.bench,
    )

    print_backtest_results(results)
    save_backtest_markdown(results)


# ══════════════════════════════════════════════════════════════
# WALK-FORWARD BACKTEST
# ══════════════════════════════════════════════════════════════

def run_walk_forward_backtest(
    tickers:       list = None,
    total_years:   int  = 4,
    train_months:  int  = 24,    # Träna på 24 månader
    test_months:   int  = 6,     # Testa på 6 månader
    top_n:         int  = 20,
    benchmark:     str  = "SPY",
    verbose:       bool = True,
) -> dict:
    """
    Walk-forward backtest - mer realistisk än standard-backtesten.

    Princip:
    Istället för att testa på samma data du tränat på, rullar du framåt:

      [Train 2020-2022] -> [Test Q1-Q2 2022]
                          [Train 2020-Q2 2022] -> [Test Q3-Q4 2022]
                                                 [Train 2020-Q4 2022] -> [Test Q1-Q2 2023]
                                                                        ...

    Detta avslöjar om modellen faktiskt generaliserar till ny data,
    eller om den bara memorerat historiska mönster.

    Resultat visar:
    - Avkastning per test-period (out-of-sample)
    - Konsistens över tid (presterar den i alla regimer?)
    - Hur stabil modellen är
    """
    tickers = tickers or BACKTEST_TICKERS

    if verbose:
        print(f"\n  🔬 Walk-forward backtest")
        print(f"     Total period: {total_years} år")
        print(f"     Träningsfönster: {train_months} mån")
        print(f"     Test-fönster: {test_months} mån")
        print(f"     Topp-{top_n} aktier per period\n")

    # Hämta all prisdata
    prices = fetch_all_prices(tickers, years=total_years + 1)
    if prices.empty:
        return {}

    bench_data = yf.download(benchmark, period=f"{total_years+1}y",
                              auto_adjust=True, progress=False)
    bench_prices = bench_data["Close"] if not bench_data.empty else None

    # Bygg test-fönster
    end_date    = prices.index[-1]
    start_date  = end_date - pd.DateOffset(years=total_years)
    test_starts = pd.date_range(
        start_date + pd.DateOffset(months=train_months),
        end_date - pd.DateOffset(months=test_months),
        freq=f"{test_months}MS",  # Månads-start frequency
    )

    if len(test_starts) == 0:
        if verbose:
            print("  ⚠ För kort period för walk-forward - minska train_months")
        return {}

    fold_results = []

    for fold_idx, test_start in enumerate(test_starts, 1):
        test_end = test_start + pd.DateOffset(months=test_months)
        if test_end > end_date:
            test_end = end_date

        if verbose:
            print(f"  📊 Fold {fold_idx}: testar {test_start.date()} -> {test_end.date()}")

        # Skapa månadsvisa rebalanseringspunkter inom test-fönstret
        test_dates = pd.date_range(test_start, test_end, freq="ME")
        test_dates = [d for d in test_dates if any(prices.index >= d)]

        fold_portfolio_rets = []
        fold_bench_rets     = []

        for i in range(len(test_dates) - 1):
            date_now  = test_dates[i]
            date_next = test_dates[i + 1]

            # Score baserat på data som fanns vid date_now
            scores = score_at_date(prices, date_now)
            if scores.empty:
                continue

            top_tickers = scores.head(top_n).index.tolist()
            valid       = [t for t in top_tickers if t in prices.columns]
            if not valid:
                continue

            try:
                avail_now  = prices.index[prices.index >= date_now][0]
                avail_next = prices.index[prices.index >= date_next][0]
                period_prices = prices.loc[avail_now:avail_next, valid]

                if period_prices.empty or len(period_prices) < 2:
                    continue

                start_p = period_prices.iloc[0]
                end_p   = period_prices.iloc[-1]
                ret     = ((end_p / start_p) - 1).mean()
                fold_portfolio_rets.append(ret)

                if bench_prices is not None:
                    b_now  = bench_prices[bench_prices.index >= avail_now].iloc[0]
                    b_next = bench_prices[bench_prices.index >= avail_next].iloc[0]
                    fold_bench_rets.append((b_next / b_now) - 1)

            except Exception:
                continue

        if fold_portfolio_rets:
            port_arr  = np.array(fold_portfolio_rets)
            bench_arr = np.array(fold_bench_rets) if fold_bench_rets else np.array([])

            cum_port  = np.prod(1 + port_arr) - 1
            cum_bench = np.prod(1 + bench_arr) - 1 if len(bench_arr) > 0 else None

            fold_results.append({
                "fold":            fold_idx,
                "period":          f"{test_start.date()} -> {test_end.date()}",
                "portfolio_ret":   round(cum_port * 100, 2),
                "benchmark_ret":   round(cum_bench * 100, 2) if cum_bench is not None else None,
                "alpha":           round((cum_port - (cum_bench or 0)) * 100, 2),
                "n_rebalances":    len(fold_portfolio_rets),
            })

            if verbose:
                alpha_txt = f"alpha {(cum_port-(cum_bench or 0))*100:+.1f}%" if cum_bench else ""
                print(f"     -> Port: {cum_port*100:+.1f}%, Bench: "
                      f"{(cum_bench or 0)*100:+.1f}%, {alpha_txt}")

    if not fold_results:
        return {}

    # Aggregera resultat
    folds_df = pd.DataFrame(fold_results)

    avg_port_ret  = folds_df["portfolio_ret"].mean()
    avg_bench_ret = folds_df["benchmark_ret"].mean() if folds_df["benchmark_ret"].notna().any() else None
    avg_alpha     = folds_df["alpha"].mean() if folds_df["alpha"].notna().any() else None

    # Konsistens: andel folds som slog benchmark
    if avg_bench_ret is not None:
        consistency = (folds_df["alpha"] > 0).mean() * 100
    else:
        consistency = None

    # Stabilitet: standardavvikelse av fold-avkastningar
    stability = folds_df["portfolio_ret"].std()

    return {
        "n_folds":          len(folds_df),
        "avg_period_ret":   round(avg_port_ret, 2),
        "avg_bench_ret":    round(avg_bench_ret, 2) if avg_bench_ret else None,
        "avg_alpha":        round(avg_alpha, 2) if avg_alpha else None,
        "consistency_pct":  round(consistency, 1) if consistency else None,
        "stability":        round(stability, 2),
        "fold_details":     folds_df,
        "best_fold":        folds_df.loc[folds_df["portfolio_ret"].idxmax()].to_dict(),
        "worst_fold":       folds_df.loc[folds_df["portfolio_ret"].idxmin()].to_dict(),
    }


def print_walk_forward_results(results: dict):
    if not results:
        print("  ❌ Inga walk-forward-resultat")
        return

    print("\n" + "═" * 60)
    print("📊 WALK-FORWARD BACKTEST-RESULTAT")
    print("═" * 60)
    print(f"  Antal fold:        {results['n_folds']}")
    print(f"  Snittavkastning:   {results['avg_period_ret']:+.1f}% per period")
    if results.get("avg_bench_ret") is not None:
        print(f"  Benchmark:         {results['avg_bench_ret']:+.1f}% per period")
    if results.get("avg_alpha") is not None:
        print(f"  Genomsnittlig alpha: {results['avg_alpha']:+.1f}%")
    if results.get("consistency_pct") is not None:
        cons = results["consistency_pct"]
        marker = "✅" if cons >= 60 else "⚠️" if cons >= 40 else "❌"
        print(f"  Konsistens:        {marker} {cons:.0f}% av folder slog benchmark")
    print(f"  Stabilitet (std):  {results['stability']:.1f}%")
    print()
    print(f"  Bästa fold:        {results['best_fold']['period']} "
          f"({results['best_fold']['portfolio_ret']:+.1f}%)")
    print(f"  Sämsta fold:       {results['worst_fold']['period']} "
          f"({results['worst_fold']['portfolio_ret']:+.1f}%)")
    print("═" * 60)

    # Tolkning
    cons = results.get("consistency_pct", 0)
    if cons is not None:
        if cons >= 60:
            print("\n  ✅ TOLKNING: Modellen är konsistent över tid och")
            print("     verkar generalisera till ny data. Lovande signal.")
        elif cons >= 40:
            print("\n  ⚠️ TOLKNING: Modellen är blandad - fungerar i vissa")
            print("     marknader men inte andra. Använd med försiktighet.")
        else:
            print("\n  ❌ TOLKNING: Modellen presterar dåligt out-of-sample.")
            print("     Risk för overfitting. Förenkla eller justera om.")


if __name__ == "__main__":
    # När backtest.py körs direkt - kör båda backtesterna
    import sys
    if "--walk-forward" in sys.argv or "--wf" in sys.argv:
        results = run_walk_forward_backtest()
        print_walk_forward_results(results)
        if results and "fold_details" in results:
            from pathlib import Path
            date_str = datetime.now().strftime("%Y-%m-%d")
            path = Path(config.REPORT_DIR) / f"walkforward_{date_str}.csv"
            results["fold_details"].to_csv(path, index=False)
            print(f"\n  💾 Sparat: {path}")
