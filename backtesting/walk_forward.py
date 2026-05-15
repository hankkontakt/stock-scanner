"""
walk_forward.py
===============
Walk-forward backtest – det enda backtest-sättet som inte fuskar.

Problem med vanlig backtest:
  Du optimerar vikter på 2018-2024-data, testar på samma 2018-2024-data.
  Det är som att öva på facit. Modellen ser fantastisk ut men funkar inte live.

Walk-forward:
  Träna på 2018-2020 → Testa "blint" på 2021
  Träna på 2018-2021 → Testa "blint" på 2022
  Träna på 2018-2022 → Testa "blint" på 2023
  ...
  Du ser om modellen faktiskt generaliserar.

Kör med:
  python walk_forward.py                  # Standard 4 år
  python walk_forward.py --years 5 --top 20
"""

import argparse
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from core import currency
from core import config
from backtesting.backtest import score_at_date, fetch_all_prices

REBALANCE_FREQ      = "ME"
HOLDING_PERIOD_DAYS = 21
BENCHMARK           = "SPY"


def walk_forward_backtest(
    tickers:        list,
    years:          int = 4,
    top_n:          int = 20,
    train_years:    int = 2,
    test_months:    int = 12,
    benchmark:      str = "SPY",
    verbose:        bool = True,
) -> dict:
    """
    Walk-forward-test över flera år.

    För varje "fönster":
      1. Träna (= se historiken) i `train_years` år
      2. Testa "blint" framåt i `test_months` månader
      3. Glid fram fönstret 12 månader
      4. Repetera

    Returnerar resultat med out-of-sample-prestanda.
    """
    
    
    
    prices = fetch_all_prices(tickers, years=years + train_years + 1)
    if prices.empty:
        print("❌ Ingen prisdata")
        return {}
        
    # Konvertera alla priser till SEK INNAN testet börjar
    prices = currency.convert_prices_to_sek(prices)
    
    bench_data = yf.download(benchmark, period=f"{years+train_years+1}y",
                              auto_adjust=True, progress=False)
    bench_prices = bench_data["Close"] if not bench_data.empty else None

    # Bestäm test-fönster
    end_date   = prices.index[-1]
    start_date = end_date - pd.DateOffset(years=years)

    # Skapa start-datum för varje walk-forward-fönster
    test_starts = pd.date_range(start=start_date, end=end_date - pd.DateOffset(months=test_months),
                                  freq=f"{test_months}MS")

    if len(test_starts) == 0:
        print("❌ För kort period för walk-forward")
        return {}

    if verbose:
        print(f"\n🔬 Walk-forward konfiguration:")
        print(f"   Träningsfönster: {train_years} år")
        print(f"   Testfönster:     {test_months} månader")
        print(f"   Antal fönster:   {len(test_starts)}")
        print(f"   Tickers:         {len(tickers)}")
        print(f"   Topp-N:          {top_n}\n")

    all_period_results = []
    window_summaries   = []

    for window_idx, test_start in enumerate(test_starts, 1):
        test_end = test_start + pd.DateOffset(months=test_months)
        if test_end > end_date:
            test_end = end_date

        if verbose:
            print(f"  Fönster {window_idx}/{len(test_starts)}: "
                  f"Testar {test_start.date()} → {test_end.date()} (out-of-sample)")

        # Månatliga rebalansering inom test-perioden
        rebalance_dates = pd.date_range(start=test_start, end=test_end, freq=REBALANCE_FREQ)

        window_returns       = []
        window_bench_returns = []

        for i in range(len(rebalance_dates) - 1):
            d_now  = rebalance_dates[i]
            d_next = rebalance_dates[i + 1]

            # Score vid d_now (använder bara historik fram tills då)
            scores = score_at_date(prices, d_now)
            if scores.empty:
                continue

            top_tickers = scores.head(top_n).index.tolist()
            valid       = [t for t in top_tickers if t in prices.columns]
            if not valid:
                continue

            try:
                avail_now  = prices.index[prices.index >= d_now ].min()
                avail_next = prices.index[prices.index >= d_next].min()

                p_now  = prices.loc[avail_now,  valid]
                p_next = prices.loc[avail_next, valid]
                
                # --- ⚖️ RISK PARITY & DYNAMISKA AVGIFTER ---
                
                # 1. Beräkna vikter baserat på historik (6 mån innan rebalansering)
                hist_start = avail_now - pd.DateOffset(months=6)
                # Vi skivar ut historiken direkt ur vår stora prices-tabell
                hist_prices = prices.loc[hist_start:avail_now, valid]
                
                if len(hist_prices) > 20:
                    vols = hist_prices.pct_change().std() * np.sqrt(252)
                    inv_vols = 1.0 / vols.replace(0, np.nan)
                    weights = inv_vols / inv_vols.sum()
                else:
                    weights = pd.Series(1.0 / len(valid), index=valid)

                # 2. Beräkna rå avkastning
                raw_rets = (p_next / p_now) - 1

                # 3. Dra av Avanza-avgifter (Slippage + Courtage + Valuta)
                # 0.25% för svenska (.ST), 0.55% för utländska
                fees = pd.Series([0.0025 if t.endswith(".ST") else 0.0055 for t in valid], index=valid)
                adjusted_rets = raw_rets - fees

                # 4. Slutlig viktad avkastning för denna månad
                ret = (adjusted_rets * weights).sum()
                
                # --------------------------------------------

                window_returns.append(ret)

                if bench_prices is not None:
                    b_now  = bench_prices[bench_prices.index >= avail_now ].iloc[0]
                    b_next = bench_prices[bench_prices.index >= avail_next].iloc[0]
                    window_bench_returns.append(b_next / b_now - 1)

                all_period_results.append({
                    "window":     window_idx,
                    "period":     d_now.strftime("%Y-%m"),
                    "port_ret":   round(ret * 100, 2),
                    "bench_ret":  round((b_next / b_now - 1) * 100, 2) if bench_prices is not None else None,
                })
            except Exception:
                continue

        # Sammanfatta fönstret
        # Sammanfatta fönstret
        if window_returns:
            port_cum  = np.prod([1 + r for r in window_returns])      - 1
            
            # ---------------------------------------------------------
            # 🌟 SURVIVORSHIP BIAS PENALTY
            # ---------------------------------------------------------
            # Dra av ett årligt "straff" på 1.5% för att yfinance saknar 
            # avnoterade bolag. Vi anpassar straffet baserat på hur många 
            # månader (perioder) fönstret testades.
            port_cum -= (0.015 / 12) * len(window_returns)
            # ---------------------------------------------------------
            
            bench_cum = (np.prod([1 + r for r in window_bench_returns]) - 1) if window_bench_returns else None

            window_summaries.append({
                "window":          window_idx,
                "test_start":      test_start.strftime("%Y-%m"),
                "test_end":        test_end.strftime("%Y-%m"),
                "n_periods":       len(window_returns),
                "port_return":     round(port_cum * 100, 2),
                "bench_return":    round(bench_cum * 100, 2) if bench_cum is not None else None,
                "alpha":           round((port_cum - (bench_cum or 0)) * 100, 2) if bench_cum is not None else None,
                "beat_benchmark":  port_cum > (bench_cum or 0) if bench_cum is not None else None,
            })

            if verbose:
                bench_str = f", Bench: {bench_cum*100:+.1f}%" if bench_cum is not None else ""
                print(f"     → Port: {port_cum*100:+.1f}%{bench_str}")

    # Sammanlagd statistik
    if not window_summaries:
        return {}

    ws_df = pd.DataFrame(window_summaries)
    pd_df = pd.DataFrame(all_period_results)

    avg_port_per_year   = ws_df["port_return"].mean()
    avg_bench_per_year  = ws_df["bench_return"].mean() if "bench_return" in ws_df.columns else None
    avg_alpha           = ws_df["alpha"].mean()         if "alpha" in ws_df.columns else None
    pct_windows_winning = ws_df["beat_benchmark"].mean() * 100 if "beat_benchmark" in ws_df.columns else None

    # Out-of-sample Sharpe
    if not pd_df.empty:
        rets = pd_df["port_ret"].values / 100
        oos_sharpe = (rets.mean() / rets.std() * np.sqrt(12)) if rets.std() > 0 else 0
    else:
        oos_sharpe = None

    return {
        "n_windows":            len(window_summaries),
        "avg_port_return":      round(avg_port_per_year, 2),
        "avg_bench_return":     round(avg_bench_per_year, 2) if avg_bench_per_year else None,
        "avg_alpha":            round(avg_alpha, 2) if avg_alpha is not None else None,
        "pct_windows_winning":  round(pct_windows_winning, 1) if pct_windows_winning else None,
        "oos_sharpe":           round(oos_sharpe, 2) if oos_sharpe else None,
        "windows":              ws_df,
        "all_periods":          pd_df,
    }


def print_walk_forward_results(results: dict):
    if not results:
        return

    print("\n" + "═" * 64)
    print("🎯 WALK-FORWARD BACKTEST – OUT-OF-SAMPLE RESULTAT")
    print("═" * 64)
    print(f"  Antal fönster (1-årsperioder): {results['n_windows']}")
    print(f"  Snitt-avkastning portfölj:     {results['avg_port_return']:+.1f}%/år")
    if results.get("avg_bench_return"):
        print(f"  Snitt-avkastning benchmark:    {results['avg_bench_return']:+.1f}%/år")
    if results.get("avg_alpha") is not None:
        print(f"  Snitt-alpha (överprestanda):   {results['avg_alpha']:+.1f}%/år")
    if results.get("pct_windows_winning") is not None:
        print(f"  Andel vinnande fönster:        {results['pct_windows_winning']:.0f}%")
    if results.get("oos_sharpe"):
        print(f"  Out-of-sample Sharpe:          {results['oos_sharpe']:.2f}")
    print("═" * 64)

    # Per fönster
    if "windows" in results and not results["windows"].empty:
        print("\n  📅 PER FÖNSTER:\n")
        print(f"  {'Fönster':<8} {'Period':<18} {'Port':>8} {'Bench':>8} {'Alpha':>8} {'Vann?':<6}")
        print("  " + "-" * 60)
        for _, row in results["windows"].iterrows():
            won = "✓" if row.get("beat_benchmark") else "✗"
            bench = f"{row['bench_return']:+.1f}%" if row.get("bench_return") is not None else "—"
            alpha = f"{row['alpha']:+.1f}%" if row.get("alpha") is not None else "—"
            print(f"  {row['window']:<8} {row['test_start']} → {row['test_end']}  "
                  f"{row['port_return']:+.1f}% {bench:>8} {alpha:>8} {won:>5}")

    # Spara CSV
    if "windows" in results:
        date_str = datetime.now().strftime("%Y-%m-%d")
        path = Path(config.REPORT_DIR) / f"walk_forward_{date_str}.csv"
        Path(config.REPORT_DIR).mkdir(parents=True, exist_ok=True)
        results["windows"].to_csv(path, index=False)
        print(f"\n  💾 Resultat sparat: {path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Walk-forward backtest")
    parser.add_argument("--years", type=int, default=4)
    parser.add_argument("--top",   type=int, default=20)
    parser.add_argument("--train", type=int, default=2)
    parser.add_argument("--test",  type=int, default=12, help="månader per test-fönster")
    parser.add_argument("--bench", type=str, default="SPY")
    args = parser.parse_args()

    results = walk_forward_backtest(
        tickers     = config.UNIVERSE[:100],
        years       = args.years,
        top_n       = args.top,
        train_years = args.train,
        test_months = args.test,
        benchmark   = args.bench,
    )

    print_walk_forward_results(results)
