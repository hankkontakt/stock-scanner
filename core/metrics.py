"""
core/metrics.py
===============
Strukturerade metrics för MarketScan-pipelinen.
Sparar timing, felräknare och business-metrics till data/metrics/.

Användning:
    from core.metrics import record_metric, record_pipeline_run, get_metric_summary
    record_metric("pipeline_duration_s", 45.2, tags={"mode": "morning"})
    record_metric("n_tickers_scored", 800, tags={"mode": "morning"})
    record_pipeline_run("morning", duration_s=42.1, n_scored=800)

E3-implementation: Enkel JSONL-baserad metrics-lagring med 10k entries per metric.
Visualiseras i Admin-panelen (web/pages/admin_tabs/metrics.py).
"""
from __future__ import annotations

import json
import logging
import os
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_METRICS_DIR = Path(__file__).resolve().parent.parent / "data" / "metrics"
_MAX_ENTRIES = 10_000  # rullande buffer per metric-fil


def _metrics_path(name: str) -> Path:
    """Returnerar sökvägen till en metrics JSONL-fil."""
    safe_name = name.replace("/", "_").replace(" ", "_")
    return _METRICS_DIR / f"{safe_name}.jsonl"


def record_metric(name: str, value: float, tags: dict | None = None) -> None:
    """Sparar en mätpunkt till data/metrics/<name>.jsonl.

    Args:
        name: Metric-namn (t.ex. "pipeline_duration_s", "n_tickers_scored")
        value: Numeriskt värde
        tags: Valfria taggar (t.ex. {"mode": "morning", "universe": "main"})
    """
    try:
        _METRICS_DIR.mkdir(parents=True, exist_ok=True)
        path = _metrics_path(name)

        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "v": round(float(value), 6),
        }
        if tags:
            entry["tags"] = {str(k): str(v) for k, v in tags.items()}

        # Atomisk append (append mode är atomisk per POSIX)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        # Rullande trim: om filen är för stor, behåll de senaste MAX_ENTRIES
        _trim_if_needed(path)
    except Exception as e:
        logger.debug("metrics.record_metric('%s') misslyckades: %s", name, e)


def _trim_if_needed(path: Path) -> None:
    """Trimmar metrics-filen till MAX_ENTRIES om den är för stor."""
    try:
        if path.stat().st_size < 2 * 1024 * 1024:  # < 2 MB → ingen trimning
            return
        lines = path.read_text(encoding="utf-8").splitlines()
        if len(lines) > _MAX_ENTRIES:
            trimmed = lines[-_MAX_ENTRIES:]
            tmp = path.with_suffix(".tmp.jsonl")
            tmp.write_text("\n".join(trimmed) + "\n", encoding="utf-8")
            tmp.replace(path)
    except Exception:
        pass


def get_recent_metrics(name: str, limit: int = 100) -> list[dict]:
    """Returnerar de senaste N mätpunkterna för en metric.

    Returns:
        Lista med dicts: [{"ts": "...", "v": float, "tags": {...}}, ...]
    """
    path = _metrics_path(name)
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        result = []
        for line in lines[-limit:]:
            line = line.strip()
            if line:
                try:
                    result.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return result
    except Exception as e:
        logger.debug("get_recent_metrics('%s') misslyckades: %s", name, e)
        return []


def get_metric_summary(name: str, last_n: int = 100) -> dict:
    """Returnerar statistik för en metric: min, max, medel, p50, p95.

    Returns:
        Dict med statistik, eller tom dict om ingen data finns.
    """
    entries = get_recent_metrics(name, limit=last_n)
    if not entries:
        return {}
    values = [e["v"] for e in entries if "v" in e]
    if not values:
        return {}
    values_sorted = sorted(values)
    n = len(values_sorted)
    return {
        "count": n,
        "min": round(min(values_sorted), 4),
        "max": round(max(values_sorted), 4),
        "mean": round(statistics.mean(values_sorted), 4),
        "p50": round(values_sorted[n // 2], 4),
        "p95": round(values_sorted[min(int(n * 0.95), n - 1)], 4),
        "last": round(values_sorted[-1], 4) if values_sorted else None,
        "last_ts": entries[-1].get("ts") if entries else None,
    }


def record_pipeline_run(
    mode: str,
    duration_s: float,
    n_scored: int,
    n_errors: int = 0,
    extra: dict | None = None,
) -> None:
    """Convenience: sparar pipeline-metrics för en körning.

    Sparar: pipeline_duration_s, n_tickers_scored, n_pipeline_errors,
            pipeline_run (counter=1 med alla taggar).
    """
    tags = {"mode": mode}
    if extra:
        tags.update({k: str(v) for k, v in extra.items()})

    record_metric("pipeline_duration_s", duration_s, tags=tags)
    record_metric("n_tickers_scored", n_scored, tags=tags)
    if n_errors > 0:
        record_metric("n_pipeline_errors", n_errors, tags=tags)
    record_metric("pipeline_run", 1, tags=tags)  # counter


def list_metrics() -> list[str]:
    """Returnerar alla metrics som har data."""
    if not _METRICS_DIR.exists():
        return []
    return [p.stem for p in sorted(_METRICS_DIR.glob("*.jsonl"))]
