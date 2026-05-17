"""
train_ml.py — Tränar ML-modell från träningsdataset.

Använd:
    python -m scripts.train_ml --universe universe
    python -m scripts.train_ml --universe smallcap

Förutsätter att data/ml/<universe>_training.parquet finns
(skapad av scripts.build_ml_dataset).

Sparar modell till models/ml_<universe>.pkl och loggar metrics.
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

from core.ml_predictor import (  # noqa: E402
    MODELS_DIR,
    save_model,
    train_from_dataset,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")


def train(universe: str, parquet_path: Path | None = None) -> dict:
    parquet_path = parquet_path or (ROOT / "data" / "ml" / f"{universe}_training.parquet")
    if not parquet_path.exists():
        raise FileNotFoundError(
            f"Träningsdata saknas: {parquet_path}\n"
            f"Kör först: python -m scripts.build_ml_dataset --universe {universe}"
        )

    logger.info(f"🏋️  Tränar {universe}-modell från {parquet_path}")
    trained = train_from_dataset(parquet_path, universe)
    if trained is None:
        raise RuntimeError("Träning misslyckades (för lite data eller felaktig struktur)")

    save_model(trained, universe)

    # Spara metrics + metadata bredvid modellen
    metrics_file = MODELS_DIR / f"ml_{universe}_metrics.json"
    metrics_file.write_text(json.dumps({
        "universe": trained.universe,
        "trained_at": trained.trained_at,
        "n_rows": trained.n_rows,
        "feature_cols": trained.feature_cols,
        "test_metrics": trained.test_metrics,
    }, indent=2))
    logger.info(f"📄 Metrics: {metrics_file}")
    return trained.test_metrics


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", choices=["universe", "smallcap"], required=True)
    ap.add_argument("--parquet", type=Path, default=None,
                    help="Sökväg till träningsdata (default: data/ml/<universe>_training.parquet)")
    args = ap.parse_args()

    metrics = train(args.universe, args.parquet)
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
