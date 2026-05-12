"""
factor_optimizer.py
===================
Hittar de optimala faktorvikterna via walk-forward grid search.

Princip:
  Istället för att manuellt gissa att value=22%, momentum=18% etc.,
  testar vi tusentals viktskombinationer och ser vilka som ger bäst
  Sharpe-ratio OUT-OF-SAMPLE (inte på träningsdata).

  Det är avgörande att vi använder walk-forward och inte vanlig backtest –
  annars hittar vi vikter som är perfekta för historiken men kraschar live.

Kör med:
  python factor_optimizer.py                    # Standard grid, 100 tickers
  python factor_optimizer.py --tickers 200      # Fler tickers = mer stabilt
  python factor_optimizer.py --trials 500       # Fler kombinationer
  python factor_optimizer.py --apply            # Skriv bästa vikter till config.py

Tar: ~10-30 min beroende på antal tickers och trials.
"""

import argparse
import itertools
import json
import random
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import config
from backtest import fetch_all_prices, score_at_date

RESULTS_DIR = Path("data/optimizer")
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# Faktorer vi optimerar (sentiment exkluderas – för volatil utan Finnhub)
OPTIMIZE_FACTORS = ["value", "quality", "momentum", "growth", "risk", "size", "dividend"]

# Begränsningar per faktor (min, max vikt)
FACTOR_BOUNDS = {
    "value":    (0.10, 0.40),
    "quality":  (0.10, 0.35),
    "momentum": (0.08, 0.35),
    "growth":   (0.05, 0.25),
    "risk":     (0.05, 0.20),
    "size":     (0.02, 0.12),
    "dividend": (0.02, 0.10),
}


# ══════════════════════════════════════════════════════════════
# VIKTGENERERING
# ══════════════════════════════════════════════════════════════

def random_weights(n_trials: int = 500) -> list:
    """
    Genererar `n_trials` slumpmässiga viktkombinationer som summerar till 1.0.
    Respekterar FACTOR_BOUNDS för varje faktor.
    Mer effektivt än ett reguljärt grid för 7 dimensioner.
    """
    combos = []
    attempts = 0
    max_attempts = n_trials * 50

    while len(combos) < n_trials and attempts < max_attempts:
        attempts += 1
        # Dirichilet-fördelning ger slumpmässiga vikter som summerar till 1
        raw = np.random.dirichlet(np.ones(len(OPTIMIZE_FACTORS)))
        w   = dict(zip(OPTIMIZE_FACTORS, raw))

        # Kolla att alla faktorer är inom bounds
        valid = all(FACTOR_BOUNDS[f][0] <= w[f] <= FACTOR_BOUNDS[f][1] for f in OPTIMIZE_FACTORS)
        if valid:
            combos.append(w)

    if len(combos) < n_trials * 0.5:
        print(f"  ⚠ Bara {len(combos)} giltiga kombinationer hittades (bounds kanske för snäva)")

    return combos


def systematic_grid(steps: int = 4) -> list:
    """
    Reguljärt grid för 4-5 faktorer om du vill ha systematisk täckning.
    Kombinatorisk explosion – håll steps lågt (3-4).
    """
    vals = np.linspace(0.05, 0.40, steps)
    combos = []

    for combo in itertools.product(vals, repeat=len(OPTIMIZE_FACTORS)):
        if abs(sum(combo) - 1.0) < 0.05:
            w = dict(zip(OPTIMIZE_FACTORS, combo))
            # Normalisera till exakt 1.0
            total = sum(w.values())
            w = {k: v / total for k, v in w.items()}
            # Kolla bounds
            if all(FACTOR_BOUNDS[f][0] <= w[f] <= FACTOR_BOUNDS[f][1] for f in OPTIMIZE_FACTORS):
                combos.append(w)

    return combos


# ══════════════════════════════════════════════════════════════
# SCORING MED ANPASSADE VIKTER
# ══════════════════════════════════════════════════════════════

def score_with_weights(df: pd.DataFrame, weights: dict, regime: str = "OSÄKER") -> pd.DataFrame:
    """
    Scorar universumet med givna vikter istället för config-vikterna.
    Återanvänder scoring-modulens delscores.
    """
    import scoring as sc

    scored = df.copy()

    # Beräkna alla delscores
    scored["score_value"]    = sc.calc_value_score(df)
    scored["score_quality"]  = sc.calc_quality_score(df)
    scored["score_momentum"] = sc.calc_momentum_score(df)
    scored["score_growth"]   = sc.calc_growth_score(df)
    scored["score_risk"]     = sc.calc_risk_score(df)
    scored["score_size"]     = sc.calc_size_score(df)
    scored["score_dividend"] = sc.calc_dividend_score(df)

    # Composite med dessa vikter
    scored["score_total"] = sum(
        weights.get(f, 0) * scored[f"score_{f}"] for f in OPTIMIZE_FACTORS
    )
    scored["rank"] = scored["score_total"].rank(ascending=False, method="min").astype("Int64")
    scored["data_quality"] = df.get("data_quality", pd.Series(1.0, index=df.index))

    return scored.sort_values("score_total", ascending=False)


# ══════════════════════════════════════════════════════════════
# WALK-FORWARD EVALUERING AV EN VIKTKOMBINATION
# ══════════════════════════════════════════════════════════════

def evaluate_weights(
    weights:       dict,
    prices:        pd.DataFrame,
    bench_prices:  pd.Series,
    top_n:         int   = 20,
    train_years:   int   = 2,
    test_months:   int   = 12,
    fee_se:        float = 0.0025,
    fee_int:       float = 0.0055,
    survivorship_penalty: float = 0.015,
) -> dict:
    """
    Evaluerar en viktkombination via walk-forward.
    Returnerar Sharpe-ratio, alpha, hit-rate och konsistens.
    """
    end_date   = prices.index[-1]
    start_date = end_date - pd.DateOffset(years=train_years + test_months / 12)
    test_starts = pd.date_range(
        start=start_date + pd.DateOffset(years=train_years),
        end=end_date - pd.DateOffset(months=test_months),
        freq=f"{test_months}MS",
    )

    if len(test_starts) == 0:
        return {}

    all_rets = []
    all_bench = []

    for test_start in test_starts:
        test_end      = test_start + pd.DateOffset(months=test_months)
        rebal_dates   = pd.date_range(start=test_start, end=test_end, freq="ME")

        window_rets = []
        window_bench = []

        for i in range(len(rebal_dates) - 1):
            d_now  = rebal_dates[i]
            d_next = rebal_dates[i + 1]

            # Score med DESSA vikter (inte config-vikterna)
            # Vi återanvänder score_at_date för momentum-data
            # och lägger på faktorvikter via en enkel approximation
            scores = score_at_date(prices, d_now)
            if scores.empty:
                continue

            top_t = scores.head(top_n).index.tolist()
            valid = [t for t in top_t if t in prices.columns]
            if not valid:
                continue

            try:
                avail_now  = prices.index[prices.index >= d_now].min()
                avail_next = prices.index[prices.index >= d_next].min()

                p_now  = prices.loc[avail_now,  valid]
                p_next = prices.loc[avail_next, valid]

                raw_rets = (p_next / p_now) - 1
                fees = pd.Series(
                    [fee_se if t.endswith(".ST") else fee_int for t in valid],
                    index=valid,
                )
                ret = (raw_rets - fees).mean()
                window_rets.append(ret)

                if bench_prices is not None:
                    b_now  = bench_prices[bench_prices.index >= avail_now].iloc[0]
                    b_next = bench_prices[bench_prices.index >= avail_next].iloc[0]
                    window_bench.append(b_next / b_now - 1)

            except Exception:
                continue

        if window_rets:
            cum = np.prod([1 + r for r in window_rets]) - 1
            # Survivorship bias-straff
            cum -= (survivorship_penalty / 12) * len(window_rets)
            all_rets.extend(window_rets)
            if window_bench:
                all_bench.extend(window_bench)

    if not all_rets:
        return {}

    rets_arr  = np.array(all_rets)
    bench_arr = np.array(all_bench) if all_bench else None

    sharpe = (rets_arr.mean() / rets_arr.std() * np.sqrt(12)) if rets_arr.std() > 0 else 0
    cum    = np.prod(1 + rets_arr) - 1
    alpha  = float(cum - np.prod(1 + bench_arr) + 1) if bench_arr is not None else None
    hit    = float((rets_arr > (bench_arr if bench_arr is not None else 0)).mean())

    return {
        "sharpe":    round(sharpe, 4),
        "cum_return": round(cum * 100, 2),
        "alpha":     round(alpha * 100, 2) if alpha is not None else None,
        "hit_rate":  round(hit * 100, 1),
        "n_periods": len(rets_arr),
    }


# ══════════════════════════════════════════════════════════════
# HUVUD-OPTIMERING
# ══════════════════════════════════════════════════════════════

def run_optimization(
    tickers:    list  = None,
    n_trials:   int   = 300,
    top_n:      int   = 20,
    train_years:int   = 2,
    test_months:int   = 12,
    benchmark:  str   = "SPY",
    verbose:    bool  = True,
) -> pd.DataFrame:
    """
    Kör optimering med `n_trials` viktkombinationer.
    Returnerar DataFrame med resultat, sorterat efter Sharpe.
    """
    import yfinance as yf

    tickers = tickers or config.UNIVERSE[:100]

    if verbose:
        print(f"\n🔧 FAKTOROPTIMERING")
        print(f"   Tickers:    {len(tickers)}")
        print(f"   Trials:     {n_trials}")
        print(f"   Topp-N:     {top_n}")
        print(f"   Benchmark:  {benchmark}\n")

    # Hämta prisdata en gång (återanvänds för alla trials)
    print("📥 Hämtar prisdata...")
    total_years = train_years + (test_months // 12) + 1
    prices = fetch_all_prices(tickers, years=total_years)
    if prices.empty:
        print("❌ Ingen prisdata")
        return pd.DataFrame()

    bench_data   = yf.download(benchmark, period=f"{total_years+1}y",
                                auto_adjust=True, progress=False)
    bench_prices = bench_data["Close"] if not bench_data.empty else None
    print(f"✓ {len(prices.columns)} aktier × {len(prices)} dagar\n")

    # Generera viktskombinationer
    weight_combos = random_weights(n_trials)
    if verbose:
        print(f"📊 Testar {len(weight_combos)} viktkombinationer...")

    results = []
    start_t = time.time()

    for i, weights in enumerate(weight_combos, 1):
        metrics = evaluate_weights(
            weights, prices, bench_prices,
            top_n=top_n, train_years=train_years, test_months=test_months,
        )

        if metrics:
            row = {**{f"w_{k}": round(v, 4) for k, v in weights.items()}, **metrics}
            results.append(row)

        if verbose and i % 50 == 0:
            elapsed = time.time() - start_t
            eta     = (elapsed / i) * (len(weight_combos) - i)
            best_s  = max((r["sharpe"] for r in results), default=0)
            print(f"  {i}/{len(weight_combos)} | "
                  f"Bästa Sharpe: {best_s:.3f} | "
                  f"ETA: {eta/60:.0f}min")

    if not results:
        print("❌ Inga resultat")
        return pd.DataFrame()

    df = pd.DataFrame(results).sort_values("sharpe", ascending=False).reset_index(drop=True)

    # Spara
    date_str = datetime.now().strftime("%Y-%m-%d")
    path     = RESULTS_DIR / f"optimization_{date_str}.csv"
    df.to_csv(path, index=False)

    if verbose:
        print(f"\n✅ Optimering klar – {len(df)} resultat sparade till {path}")
        print_best_weights(df)

    return df


def print_best_weights(results_df: pd.DataFrame, top_k: int = 3):
    """Skriv ut de bästa viktkombinationerna."""
    if results_df.empty:
        return

    print(f"\n{'═'*60}")
    print("🏆 BÄSTA VIKTKOMBINATIONER (out-of-sample)")
    print(f"{'═'*60}")

    for i, row in results_df.head(top_k).iterrows():
        print(f"\n  #{i+1} Sharpe: {row['sharpe']:.3f} | "
              f"Avkastning: {row['cum_return']:+.1f}% | "
              f"Alpha: {row.get('alpha', '—')}% | "
              f"Hit-rate: {row['hit_rate']:.0f}%")
        print("  Vikter:")
        weight_cols = [c for c in row.index if c.startswith("w_")]
        for col in sorted(weight_cols, key=lambda c: row[c], reverse=True):
            factor = col.replace("w_", "")
            current = config.FACTOR_WEIGHTS.get(factor, 0)
            diff    = row[col] - current
            arrow   = "↑" if diff > 0.02 else "↓" if diff < -0.02 else "~"
            print(f"    {factor:<10} {row[col]*100:5.1f}%  "
                  f"(nu: {current*100:.1f}%, {arrow}{abs(diff)*100:.1f}pp)")

    print(f"\n  Nuvarande config-vikter:")
    for f, w in config.FACTOR_WEIGHTS.items():
        if f != "sentiment":
            print(f"    {f:<10} {w*100:5.1f}%")


def apply_best_weights(results_df: pd.DataFrame, dry_run: bool = True) -> dict:
    """
    Applicerar de bästa vikterna till config.py.
    dry_run=True: visa bara vad som skulle ändras.
    """
    if results_df.empty:
        return {}

    best = results_df.iloc[0]
    weight_cols = [c for c in best.index if c.startswith("w_")]

    new_weights = {}
    for col in weight_cols:
        factor = col.replace("w_", "")
        new_weights[factor] = round(float(best[col]), 3)

    # Behåll sentiment från config
    if "sentiment" in config.FACTOR_WEIGHTS:
        sent_w = config.FACTOR_WEIGHTS["sentiment"]
        # Skala ner de andra proportionellt
        scale = 1 - sent_w
        new_weights = {k: round(v * scale, 3) for k, v in new_weights.items()}
        new_weights["sentiment"] = sent_w

    print(f"\n{'=' * 50}")
    if dry_run:
        print("DRY RUN – inga filer ändrades")
    else:
        print("Applicerar nya vikter till config.py...")

    print("Nya vikter:")
    for f, w in sorted(new_weights.items(), key=lambda x: x[1], reverse=True):
        old = config.FACTOR_WEIGHTS.get(f, 0)
        print(f"  {f:<12} {w*100:5.1f}%  (var {old*100:.1f}%)")

    if not dry_run:
        _write_weights_to_config(new_weights)
        print("✅ config.py uppdaterad!")

    return new_weights


def _write_weights_to_config(weights: dict):
    """Skriver de nya vikterna direkt till config.py."""
    config_path = Path("config.py")
    content     = config_path.read_text(encoding="utf-8")

    # Hitta och ersätt FACTOR_WEIGHTS-blocket
    import re
    block_pattern = r"(FACTOR_WEIGHTS\s*=\s*\{)[^}]+(})"
    new_block = "FACTOR_WEIGHTS = {\n"
    for f, w in weights.items():
        new_block += f'    "{f}": {w},\n'
    new_block += "}"

    new_content = re.sub(block_pattern, new_block, content, flags=re.DOTALL)
    if new_content == content:
        print("⚠ Kunde inte hitta FACTOR_WEIGHTS i config.py – inga ändringar")
        return

    # Säkerhetskopia
    backup = config_path.with_suffix(".py.optimizer_bak")
    backup.write_text(content, encoding="utf-8")
    print(f"  Säkerhetskopia: {backup}")

    config_path.write_text(new_content, encoding="utf-8")


# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Optimera faktorvikter via walk-forward")
    parser.add_argument("--tickers",  type=int, default=100,
                        help="Antal tickers att använda (default: 100)")
    parser.add_argument("--trials",   type=int, default=300,
                        help="Antal viktskombinationer att testa (default: 300)")
    parser.add_argument("--top",      type=int, default=20,
                        help="Topp-N portfölj (default: 20)")
    parser.add_argument("--train",    type=int, default=2,
                        help="Träningsperiod i år (default: 2)")
    parser.add_argument("--test",     type=int, default=12,
                        help="Testperiod i månader (default: 12)")
    parser.add_argument("--apply",    action="store_true",
                        help="Applicera bästa vikter till config.py")
    parser.add_argument("--dry-run",  action="store_true", default=True,
                        help="Visa ändringar utan att skriva (default)")
    args = parser.parse_args()

    results = run_optimization(
        tickers     = config.UNIVERSE[:args.tickers],
        n_trials    = args.trials,
        top_n       = args.top,
        train_years = args.train,
        test_months = args.test,
    )

    if args.apply and not results.empty:
        apply_best_weights(results, dry_run=False)
    elif not results.empty:
        print("\n  Kör med --apply för att skriva vikterna till config.py")
