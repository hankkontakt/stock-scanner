"""
core/pipeline_performance.py
=============================
A1-split: Performance tracking för MarketScan-pipelinen.

Extraherade från core/daily_pipeline.py.
Innehåller: _timed_stage, _record_perf, get_performance_summary,
            get_slowest_stages, get_performance_trend.

Backward compat: daily_pipeline.py re-importerar allt härifrån.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from contextlib import contextmanager
from typing import Generator

import pandas as pd

_PERF_LOCK = threading.Lock()
_PERF_HISTORY: dict[str, deque] = defaultdict(lambda: deque(maxlen=100))


@contextmanager
def _timed_stage(name: str, plogger=None, **extra) -> Generator[dict, None, None]:
    """Context manager som mäter duration för en pipeline-stage.

    Loggar via PipelineLogger om tillgängligt.

    Användning:
        with _timed_stage("fetch_data", plogger=pl) as ctx:
            data = fetch_data()
            ctx["rows_processed"] = len(data)
    """
    start = time.time()
    meta: dict = {"name": name, "rows_processed": 0, "errors": 0}
    if plogger:
        plogger.start_stage(name)
    try:
        yield meta
        elapsed_ms = (time.time() - start) * 1000
        meta["duration_ms"] = round(elapsed_ms, 1)
        if plogger:
            plogger.end_stage(name)
        _record_perf(name, meta)
    except Exception as e:
        elapsed_ms = (time.time() - start) * 1000
        meta["duration_ms"] = round(elapsed_ms, 1)
        meta["errors"] = meta.get("errors", 0) + 1
        meta["error"] = str(e)[:100]
        if plogger:
            plogger.end_stage(name)
            plogger.log_error("pipeline", f"STAGE_FAILED:{name}", str(e)[:200])
        _record_perf(name, meta)
        raise


def _record_perf(stage: str, meta: dict) -> None:
    """Spara en prestandamätpunkt i historiken."""
    try:
        entry = {
            "timestamp": time.time(),
            "stage": stage,
            **meta,
        }
        with _PERF_LOCK:
            _PERF_HISTORY[stage].append(entry)
    except Exception:
        pass


def get_performance_summary(last_n: int = 10) -> pd.DataFrame:
    """Tabell över genomsnittlig duration per stage (senaste N körningar).

    Returns:
        DataFrame med kolumner [stage, avg_duration_ms, total_calls, errors, error_rate_pct]
    """
    rows = []
    with _PERF_LOCK:
        for stage, entries in _PERF_HISTORY.items():
            recent = list(entries)[-last_n:]
            if not recent:
                continue
            durations = [e.get("duration_ms", 0) for e in recent if e.get("duration_ms")]
            errors = sum(1 for e in recent if e.get("errors", 0) > 0)
            avg_duration = sum(durations) / len(durations) if durations else 0
            rows.append({
                "stage": stage,
                "avg_duration_ms": round(avg_duration, 1),
                "total_calls": len(recent),
                "errors": errors,
                "error_rate_pct": round(errors / len(recent) * 100, 1) if recent else 0,
            })
    if not rows:
        return pd.DataFrame(
            columns=["stage", "avg_duration_ms", "total_calls", "errors", "error_rate_pct"]
        )
    df = pd.DataFrame(rows)
    return df.sort_values("avg_duration_ms", ascending=False).reset_index(drop=True)


def get_slowest_stages(top_n: int = 5) -> list[dict]:
    """Hitta flaskhalsar — de långsammaste stage:en baserat på average duration."""
    df = get_performance_summary()
    if df.empty:
        return []
    return df.head(top_n).to_dict("records")


def get_performance_trend(stage_name: str, last_n: int = 20) -> list[dict]:
    """Hur har prestandan för en specifik stage ändrats?

    Returns:
        Lista med [{"index": int, "duration_ms": float, "timestamp": float}]
    """
    with _PERF_LOCK:
        entries = list(_PERF_HISTORY.get(stage_name, []))[-last_n:]
    return [
        {
            "index": i,
            "duration_ms": e.get("duration_ms", 0),
            "timestamp": e.get("timestamp"),
        }
        for i, e in enumerate(entries)
    ]
