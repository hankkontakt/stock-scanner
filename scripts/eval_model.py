"""
scripts/eval_model.py — Utvärdering och jämförelse av ML-modeller.

Användning:
    python -m scripts.eval_model                                         # utvärdera ranker
    python -m scripts.eval_model --compare-objectives                     # jämför ndcg vs rank_ic
    python -m scripts.eval_model --compare-all                            # XGBoost vs Ranker vs Ensemble
    python -m scripts.eval_model --gate                                   # deploy-gate: deploya bara om bättre
    python -m scripts.eval_model --universe smallcap --plot               # smallcap + plott
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from core.ml_evaluation import compare_models, evaluate_model, per_date_ic, ic_significance, decile_spread
from core.ml_ranker import RANKER_FEATURES, TECH_FEATURES, MODELS_DIR, load_ranker_metrics, _fit_model, _walk_forward_validate
from core.ml_validation import purged_walk_forward_folds, deflated_sharpe_ratio

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def _load_data(universe: str) -> pd.DataFrame:
    """Ladda träningsdata för angivet universum."""
    data_path = ROOT / "data" / "ml" / f"{universe}_training.parquet"
    if not data_path.exists():
        logger.error("Träningsdata saknas: %s", data_path)
        sys.exit(1)
    df = pd.read_parquet(data_path)
    df = df.dropna(subset=["forward_return_30d"]).copy()
    df = df[df["forward_return_30d"].between(-0.9, 5.0)]
    df = df.sort_values("date").reset_index(drop=True)
    return df


def _run_objective_comparison(df: pd.DataFrame, universe: str) -> list[dict]:
    """Kör alla tre objektivlägen och returnera jämförelsetabell."""
    feature_cols = [c for c in RANKER_FEATURES if c in df.columns]
    results = []

    for obj in ["lambdarank_ndcg", "rank_ic", "xgboost_cs"]:
        logger.info("Kör objektiv: %s", obj)
        wf_results = _walk_forward_validate(df, feature_cols, objective_mode=obj)

        if not wf_results:
            logger.warning("  Inga resultat för %s", obj)
            continue

        ic_values = [r["ic"] for r in wf_results if r.get("ic") is not None]
        spread_values = [r["decile_spread"] for r in wf_results if r.get("decile_spread") is not None]

        mean_ic = float(np.mean(ic_values)) if ic_values else 0.0
        std_ic = float(np.std(ic_values)) if ic_values else 0.0
        icir = mean_ic / std_ic if std_ic > 0 else 0.0
        mean_spread = float(np.mean(spread_values)) if spread_values else 0.0

        # DSR: estimate from number of trials
        dsr = deflated_sharpe_ratio(
            observed_sharpe=icir,
            num_trials=max(len(wf_results), 3),
            T=len(ic_values) * 21,  # approx trading days
        )

        results.append({
            "objective": obj,
            "ic_mean": round(mean_ic, 4),
            "ic_std": round(std_ic, 4),
            "icir": round(icir, 4),
            "decile_spread": round(mean_spread, 4),
            "dsr": round(dsr, 4),
            "n_folds": len(wf_results),
        })
        logger.info("  %s: IC=%.4f, spread=%.4f, DSR=%.4f", obj, mean_ic, mean_spread, dsr)

    return results


def cmd_eval(args):
    """Utvärdera befintlig modell."""
    df = _load_data(args.universe)
    result = evaluate_model(
        ROOT / "data" / "ml" / f"{args.universe}_training.parquet",
        args.universe, "ranker",
    )
    if result:
        stats = result.get("ic_stats", {})
        print(f"\n  IC: {stats.get('mean', 0):.4f} ± {stats.get('std', 0):.4f}")
        print(f"  IR: {stats.get('ir', 0):.4f}")
        print(f"  p-value: {stats.get('p_value', 1):.4f}")
        print(f"  Decil-spread: {result.get('decile_spread', 0):.4f}")
        print(f"  Prediktioner: {result.get('n_predictions', 0):,}")


def cmd_compare_objectives(args):
    """Jämför alla objektivlägen."""
    df = _load_data(args.universe)
    results = _run_objective_comparison(df, args.universe)

    print("\n" + "="*80)
    print(f"  OBJEKTIVJÄMFÖRELSE — {args.universe}")
    print("="*80)
    print(f"  {'Objektiv':<25} {'IC':<10} {'ICIR':<10} {'Spread':<10} {'DSR':<10} {'Folds':<8}")
    print(f"  {'─'*25} {'─'*10} {'─'*10} {'─'*10} {'─'*10} {'─'*8}")
    for r in results:
        print(f"  {r['objective']:<25} {r['ic_mean']:<10.4f} {r['icir']:<10.4f} "
              f"{r['decile_spread']:<10.4f} {r['dsr']:<10.4f} {r['n_folds']:<8}")

    if results:
        best = max(results, key=lambda r: (r["ic_mean"], r["decile_spread"], r["dsr"]))
        print(f"\n  >>> Vinnare: {best['objective']} (IC={best['ic_mean']:.4f}, spread={best['decile_spread']:.4f}, DSR={best['dsr']:.4f})")

    # Spara
    out = MODELS_DIR / f"objective_comparison_{args.universe}.json"
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    logger.info("Jämförelse sparad: %s", out.name)


def cmd_compare_all(args):
    """Jämför alla modeller (XGBoost vs Ranker vs om ensemble finns)."""
    data_path = ROOT / "data" / "ml" / f"{args.universe}_training.parquet"
    result = compare_models(data_path, args.universe)
    summary = result.get("summary", {})

    print("\n" + "="*60)
    print(f"  MODELLJÄMFÖRELSE — {args.universe}")
    print("="*60)
    print(f"  LightGBM-ranker IC: {summary.get('ranker_ic', 0):.4f}")
    print(f"  XGBoost IC:         {summary.get('xgboost_ic', 0):.4f}")
    print(f"  IC-förbättring:     {summary.get('ic_improvement', 0):+.4f}")
    print(f"  Ranker decil-spread: {summary.get('ranker_spread', 0):.4f}")
    print(f"  XGBoost decil-spread: {summary.get('xgboost_spread', 0):.4f}")
    print(f"  Vinnare: {summary.get('winner', '?').upper()}")
    print(f"  Deploya ranker: {'✅ JA' if summary.get('deploy_ranker') else '❌ NEJ'}")
    print("="*60)


def cmd_gate(args):
    """Deploy-gate: jämför ny modell mot deployad och avgör om deploy."""
    df = _load_data(args.universe)
    feature_cols = [c for c in RANKER_FEATURES if c in df.columns]

    # Hämta deployad modells metrics
    deployed = load_ranker_metrics(args.universe)
    old_ic = 0.0
    old_spread = 0.0
    if deployed is not None and isinstance(deployed, dict):
        tm = deployed.get("test_metrics")
        if tm and isinstance(tm, dict):
            old_ic = tm.get("ic", 0.0) or 0.0
            old_spread = tm.get("wf_avg_spread", 0.0) or 0.0

    # Träna och utvärdera ny modell
    wf_results = _walk_forward_validate(df, feature_cols)
    new_ic = float(np.mean([r["ic"] for r in wf_results])) if wf_results else 0.0
    new_spread = float(np.mean([r["decile_spread"] for r in wf_results])) if wf_results else 0.0

    # Beräkna DSR
    ic_values = [r["ic"] for r in wf_results if r.get("ic") is not None]
    icir = float(np.mean(ic_values) / np.std(ic_values)) if len(ic_values) > 1 else 0.0
    dsr = deflated_sharpe_ratio(icir, max(len(wf_results), 3), len(ic_values) * 21)

    deploy = (new_ic > old_ic) and (new_spread > old_spread) and (dsr > 0.5)

    print(f"\n  Deploy-gate — {args.universe}")
    print(f"  {'Metric':<20} {'Nuvarande':<12} {'Ny':<12} {'Krav':<12}")
    print(f"  {'─'*20} {'─'*12} {'─'*12} {'─'*12}")
    print(f"  {'IC':<20} {old_ic:<12.4f} {new_ic:<12.4f} {'> gammal':<12}")
    print(f"  {'Decil-spread':<20} {old_spread:<12.4f} {new_spread:<12.4f} {'> gammal':<12}")
    print(f"  {'DSR':<20} {'':<12} {dsr:<12.4f} {'> 0.5':<12}")
    print(f"\n  >>> Beslut: {'✅ DEPLOYA' if deploy else '❌ BEHÅLL NUVARANDE'}")


def main():
    parser = argparse.ArgumentParser(description="ML Model Evaluation")
    parser.add_argument("--universe", default="universe", choices=["universe", "smallcap"])
    parser.add_argument("--plot", action="store_true", help="Plotta grafer (kräver matplotlib)")

    sub = parser.add_subparsers(dest="command")

    sub.add_parser("eval", help="Utvärdera ranker")
    sub.add_parser("compare-objectives", help="Jämför ndcg vs rank_ic vs xgboost")
    sub.add_parser("compare-all", help="Jämför ranker vs XGBoost vs Ensemble")
    sub.add_parser("gate", help="Deploy-gate")

    args = parser.parse_args()

    if args.command == "compare-objectives":
        cmd_compare_objectives(args)
    elif args.command == "compare-all":
        cmd_compare_all(args)
    elif args.command == "gate":
        cmd_gate(args)
    else:
        cmd_eval(args)


if __name__ == "__main__":
    main()
