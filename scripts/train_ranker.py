"""
scripts/train_ranker.py — Tränar LightGBM LambdaRank-ranker

Kör:
    python -m scripts.train_ranker                    # universe
    python -m scripts.train_ranker --universe smallcap
    python -m scripts.train_ranker --compare          # jämför mot XGBoost
    python -m scripts.train_ranker --eval-only        # bara utvärdera, inte spara

Förutsätter att träningsdata finns:
    data/ml/universe_training.parquet   (byggs av scripts.build_ml_dataset)

Gate:
    Ny ranker deployas bara om den slår XGBoost på IC OCH decil-spread (walk-forward).
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

from core.ml_ranker import (
    RANKER_FEATURES, MODELS_DIR, train_ranker, save_ranker, load_ranker_metrics,
)
from core.ml_evaluation import compare_models, evaluate_model

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main():
    parser = argparse.ArgumentParser(description="Tränar LightGBM-ranker")
    parser.add_argument("--universe", default="universe", choices=["universe", "smallcap"])
    parser.add_argument("--compare", action="store_true", help="Jämför ranker vs XGBoost")
    parser.add_argument("--eval-only", action="store_true", help="Utvärdera utan att spara modell")
    parser.add_argument("--plot", action="store_true", help="Plotta IC-trend och decil-graf")
    args = parser.parse_args()

    data_path = ROOT / "data" / "ml" / f"{args.universe}_training.parquet"
    if not data_path.exists():
        logger.error("❌ Träningsdata saknas: %s", data_path)
        logger.error("   Kör först: python -m scripts.build_ml_dataset --universe %s", args.universe)
        sys.exit(1)

    # ── Träna ────────────────────────────────────────────────────────────────
    if not args.eval_only:
        logger.info("🏋️  Tränar LightGBM-ranker för %s...", args.universe)
        ranker = train_ranker(data_path, args.universe)
        if ranker is None:
            logger.error("❌ Träning misslyckades")
            sys.exit(1)

        metrics = ranker.test_metrics
        ic = metrics.get("ic", 0.0)
        spread = metrics.get("wf_avg_spread", 0.0)
        hit_rate = metrics.get("hit_rate", 0.0)
        model_type = metrics.get("model_type", "unknown")

        print("\n" + "="*60)
        print(f"  LightGBM Ranker — {args.universe}")
        print("="*60)
        print(f"  Modelltyp:   {model_type}")
        print(f"  Features:    {len(ranker.feature_cols)} ({metrics.get('n_features', 0)})")
        print(f"  Träningsrader: {ranker.n_rows:,}")
        print(f"  Walk-forward folds: {metrics.get('n_folds', 0)}")
        print(f"  IC (WF avg): {ic:.4f}   [mål: > 0.050]  {'✅' if ic > 0.050 else '⚠️  (under mål)'}")
        print(f"  Decil-spread: {spread:.4f}")
        print(f"  Hit-rate:    {hit_rate:.4f}")

        # Visa per-fold detaljer
        if metrics.get("wf_folds"):
            print("\n  Walk-forward folds:")
            for fold in metrics["wf_folds"]:
                print(f"    [{fold['test_start'][:7]}→{fold['test_end'][:7]}]  "
                      f"IC={fold['ic']:.4f}  spread={fold['decile_spread']:.4f}  "
                      f"hit={fold['hit_rate']:.4f}  n={fold['n_test']}")

        # Spara modell (alltid — gate är jämförelsen nedan)
        save_ranker(ranker, args.universe)
        logger.info("✅ Ranker sparad: models/ml_ranker_%s.pkl", args.universe)

    # ── Jämförelse ───────────────────────────────────────────────────────────
    if args.compare:
        logger.info("⚖️  Jämför ranker vs XGBoost (walk-forward)...")
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
        print(f"  Ranker signifikant: {'Ja' if summary.get('ranker_significant') else 'Nej (p>0.05)'}")
        print(f"  Vinnare: {summary.get('winner', '?').upper()}")
        print(f"  Deploya ranker: {'✅ JA' if summary.get('deploy_ranker') else '❌ NEJ — XGBoost är fortfarande bättre'}")
        print("="*60)

        # Spara jämförelse-resultat
        out = ROOT / "models" / f"model_comparison_{args.universe}.json"
        out.write_text(json.dumps(result.get("summary", {}), indent=2, ensure_ascii=False))
        logger.info("Jämförelse sparad: %s", out.name)

    # ── Enbart walk-forward utvärdering ──────────────────────────────────────
    if args.eval_only:
        logger.info("📊 Utvärderar befintlig ranker-modell (inga ändringar sparas)...")
        result = evaluate_model(data_path, args.universe, "ranker")
        if result:
            stats = result.get("ic_stats", {})
            print(f"\n  IC: {stats.get('mean', 0):.4f} ± {stats.get('std', 0):.4f}")
            print(f"  IR: {stats.get('ir', 0):.4f}")
            print(f"  p-value: {stats.get('p_value', 1):.4f} ({'sig.' if stats.get('significant') else 'ej sig.'})")
            print(f"  Decil-spread: {result.get('decile_spread', 0):.4f}")
            print(f"  Prediktioner: {result.get('n_predictions', 0):,}")


if __name__ == "__main__":
    main()
