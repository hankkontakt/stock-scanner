"""
audit_baseline.py — FAS 0: Etablera ärlig baslinje för nuvarande modellprestanda.

Kör nuvarande ml_evaluation.compare_models() på befintlig träningsdata
och skriver models/baseline_report.json med:
  - ranker-IC (före och efter embargo, om båda finns)
  - xgboost-IC
  - decil-spread
  - antal datum, datumspann, antal unika tickers, andel NaN i forward_return_30d

Användning:
    python -m scripts.audit_baseline
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logger = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"
REPORT_PATH = MODELS_DIR / "baseline_report.json"


def _load_training_data() -> pd.DataFrame:
    """Ladda träningsdata. Försök flera källor."""
    # Kolla efter build_ml_dataset-output
    data_dir = Path(__file__).resolve().parent.parent / "data"
    possible_paths = [
        data_dir / "ml_training_data.parquet",
        data_dir / "training_data.parquet",
        data_dir / "scored_universe.parquet",
    ]
    for p in possible_paths:
        if p.exists():
            logger.info("Loading training data from %s", p)
            return pd.read_parquet(p)

    # Försök hitta i reports/
    reports_dir = Path(__file__).resolve().parent.parent / "reports"
    parquet_files = list(reports_dir.glob("scored_universe_*.parquet"))
    if parquet_files:
        latest = max(parquet_files, key=lambda f: f.stat().st_mtime)
        logger.info("Loading training data from %s", latest)
        return pd.read_parquet(latest)

    raise FileNotFoundError(
        "No training data found. Run build_ml_dataset.py first, "
        "or place ml_training_data.parquet in data/"
    )


def audit_baseline() -> dict:
    """Kör baseline-audit och returnera rapport-dict."""
    df = _load_training_data()
    logger.info("Loaded %d rows, %d columns", len(df), len(df.columns))

    if "forward_return_30d" not in df.columns:
        logger.warning("No forward_return_30d column — trying to build training data")
        from scripts.build_ml_dataset import build_dataset
        df = build_dataset()
        logger.info("Built dataset: %d rows", len(df))

    # Grundstatistik
    dates = pd.to_datetime(df["date"]).nunique() if "date" in df.columns else 0
    tickers = df["ticker"].nunique() if "ticker" in df.columns else 0
    date_min = str(pd.to_datetime(df["date"]).min().date()) if "date" in df.columns and len(df) else "N/A"
    date_max = str(pd.to_datetime(df["date"]).max().date()) if "date" in df.columns and len(df) else "N/A"
    nan_ratio = float(df["forward_return_30d"].isna().mean()) if "forward_return_30d" in df.columns else 1.0

    report: dict = {
        "baseline_date": datetime.now().isoformat(),
        "data_stats": {
            "rows": len(df),
            "unique_dates": dates,
            "unique_tickers": tickers,
            "date_range": f"{date_min} → {date_max}",
            "forward_return_nan_ratio": nan_ratio,
        },
        "models": {},
    }

    # Kör purged walk-forward direkt med ranker-funktionen
    try:
        logger.info("Running purged walk-forward validation...")
        from core.ml_ranker import RANKER_FEATURES, _walk_forward_validate

        feature_cols = [c for c in RANKER_FEATURES if c in df.columns]
        wf_results = _walk_forward_validate(df, feature_cols)

        if wf_results:
            ic_values = [r["ic"] for r in wf_results if r.get("ic") is not None]
            spread_values = [r["decile_spread"] for r in wf_results if r.get("decile_spread") is not None]
            report["models"]["ranker_purged"] = {
                "ic_mean": float(np.mean(ic_values)) if ic_values else 0,
                "ic_std": float(np.std(ic_values)) if ic_values else 0,
                "icir": float(np.mean(ic_values) / np.std(ic_values)) if len(ic_values) > 1 else 0,
                "decile_spread": float(np.mean(spread_values)) if spread_values else 0,
                "n_folds": len(wf_results),
                "embargo_applied": True,
            }
            logger.info("Purged IC: mean=%.4f, spread=%.4f",
                        report["models"]["ranker_purged"]["ic_mean"],
                        report["models"]["ranker_purged"]["decile_spread"])
    except Exception as e:
        logger.warning("Purged walk-forward failed: %s", e)
        report["models"]["ranker_purged_error"] = str(e)

    # Spara rapport
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    logger.info("Baseline report saved to %s", REPORT_PATH)

    return report


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    report = audit_baseline()
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
