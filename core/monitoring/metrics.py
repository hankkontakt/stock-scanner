"""
metrics.py — Prometheus Metrics Collector
=========================================
Singleton-klass som samlar in pipeline-metrik i minnet och dumpar till JSON
efter varje pipeline-körning. Data sparas i `data/metrics/` för Grafana/Prometheus.

Alla räknare är trådsäkra (threading.Lock). Ingen blockering vid fel.
"""

import json
import os
import threading
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional


_METRICS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "metrics"
_METRICS_DIR.mkdir(parents=True, exist_ok=True)


class MetricsCollector:
    """Singleton: samlar pipeline-metrik i minnet med trådsäkerhet."""

    _instance: Optional["MetricsCollector"] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self._mutex = threading.Lock()

        # Histogram — pipeline duration per mode
        self.pipeline_duration: dict[str, list[float]] = defaultdict(list)

        # Histogram — fetch duration
        self.fetch_duration: list[float] = []

        # Histogram — scoring duration
        self.scoring_duration: list[float] = []

        # Räknare
        self.tickers_fetched: int = 0
        self.tickers_failed: int = 0
        self.ai_calls: int = 0
        self.ai_tokens_input: int = 0
        self.ai_tokens_output: int = 0
        self.email_sent: dict[str, int] = defaultdict(int)
        self.cache_hits: int = 0
        self.cache_misses: int = 0
        self.pipeline_success: dict[str, int] = defaultdict(int)
        self.pipeline_failure: dict[str, int] = defaultdict(int)

        # Gauge — score distribution (percentiler)
        self.scoring_distribution: dict[str, Optional[float]] = {
            "0.5": None, "0.75": None, "0.9": None, "0.95": None,
        }

        # Gauge — senaste lyckade scan
        self.latest_scan_timestamp: Optional[float] = None

        # Resetta varje pipeline-körning
        self._pipeline_start: Optional[float] = None

    # ── Context managers ───────────────────────────────────────────────────

    def pipeline_start(self, mode: str):
        """Anropa i början av run_pipeline()."""
        self._pipeline_start = time.time()
        with self._mutex:
            self.tickers_fetched = 0
            self.tickers_failed = 0

    def pipeline_end(self, mode: str, success: bool = True):
        """Anropa i slutet av run_pipeline()."""
        start = self._pipeline_start
        if start is not None:
            duration = time.time() - start
            with self._mutex:
                self.pipeline_duration[mode].append(duration)
                if success:
                    self.pipeline_success[mode] += 1
                    self.latest_scan_timestamp = time.time()
                else:
                    self.pipeline_failure[mode] += 1
        self._dump_snapshot()

    def record_fetch_duration(self, seconds: float):
        with self._mutex:
            self.fetch_duration.append(seconds)

    def record_scoring_duration(self, seconds: float):
        with self._mutex:
            self.scoring_duration.append(seconds)

    def record_ticker_fetched(self, n: int = 1):
        with self._mutex:
            self.tickers_fetched += n

    def record_ticker_failed(self, n: int = 1):
        with self._mutex:
            self.tickers_failed += n

    def record_ai_call(self, provider: str = "deepseek", tokens_input: int = 0, tokens_output: int = 0):
        with self._mutex:
            self.ai_calls += 1
            self.ai_tokens_input += tokens_input
            self.ai_tokens_output += tokens_output

    def record_email_sent(self, email_type: str = "morning"):
        with self._mutex:
            self.email_sent[email_type] += 1

    def record_cache_hit(self):
        with self._mutex:
            self.cache_hits += 1

    def record_cache_miss(self):
        with self._mutex:
            self.cache_misses += 1

    def record_scoring_distribution(self, p50: Optional[float], p75: Optional[float],
                                     p90: Optional[float], p95: Optional[float]):
        with self._mutex:
            self.scoring_distribution = {
                "0.5": p50, "0.75": p75, "0.9": p90, "0.95": p95,
            }

    # ── Export ─────────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Exportera all metrik som dict (för JSON-serialisering)."""
        with self._mutex:
            return {
                "pipeline_duration_seconds": dict(self.pipeline_duration),
                "fetch_duration_seconds": self.fetch_duration[-1000:] if self.fetch_duration else [],
                "scoring_duration_seconds": self.scoring_duration[-1000:] if self.scoring_duration else [],
                "tickers_fetched_total": self.tickers_fetched,
                "tickers_failed_total": self.tickers_failed,
                "ai_calls_total": self.ai_calls,
                "ai_tokens_input_total": self.ai_tokens_input,
                "ai_tokens_output_total": self.ai_tokens_output,
                "email_sent_total": dict(self.email_sent),
                "cache_hits_total": self.cache_hits,
                "cache_misses_total": self.cache_misses,
                "pipeline_success_total": dict(self.pipeline_success),
                "pipeline_failure_total": dict(self.pipeline_failure),
                "scoring_distribution": dict(self.scoring_distribution),
                "latest_scan_timestamp": self.latest_scan_timestamp,
                "exported_at": datetime.now().isoformat(),
            }

    def _dump_snapshot(self):
        """Dump aktuell metrik till JSON-fil (anropas efter varje pipeline-körning)."""
        try:
            now = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = _METRICS_DIR / f"metrics_{now}.json"
            path.write_text(
                json.dumps(self.to_dict(), indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
            # Rensa gamla snapshot (behåll 100 senaste)
            files = sorted(_METRICS_DIR.glob("metrics_*.json"), reverse=True)
            for f in files[100:]:
                f.unlink(missing_ok=True)
        except Exception:
            pass  # Non-blocking — aldrig krascha

    def get_prometheus_text(self) -> str:
        """Generera Prometheus exposition-format (text)."""
        d = self.to_dict()
        lines = ["# HELP pipeline_duration_seconds Pipeline duration per mode",
                 "# TYPE pipeline_duration_seconds histogram"]
        for mode, values in d.get("pipeline_duration_seconds", {}).items():
            for v in values:
                lines.append(f'pipeline_duration_seconds{{mode="{mode}"}} {v}')

        lines.extend([
            "# HELP fetch_duration_seconds Data fetch duration",
            "# TYPE fetch_duration_seconds histogram",
        ])
        for v in d.get("fetch_duration_seconds", []):
            lines.append(f"fetch_duration_seconds {v}")

        lines.extend([
            "# HELP scoring_duration_seconds Scoring duration",
            "# TYPE scoring_duration_seconds histogram",
        ])
        for v in d.get("scoring_duration_seconds", []):
            lines.append(f"scoring_duration_seconds {v}")

        lines.append("# HELP tickers_fetched_total Total tickers fetched")
        lines.append("# TYPE tickers_fetched_total counter")
        lines.append(f"tickers_fetched_total {d.get('tickers_fetched_total', 0)}")

        lines.append("# HELP tickers_failed_total Total tickers that failed")
        lines.append("# TYPE tickers_failed_total counter")
        lines.append(f"tickers_failed_total {d.get('tickers_failed_total', 0)}")

        lines.append('# HELP ai_calls_total AI API calls')
        lines.append('# TYPE ai_calls_total counter')
        lines.append(f'ai_calls_total{{provider="deepseek"}} {d.get("ai_calls_total", 0)}')

        lines.append('# HELP ai_tokens_total AI tokens consumed')
        lines.append('# TYPE ai_tokens_total counter')
        lines.append(f'ai_tokens_total{{provider="deepseek",direction="input"}} {d.get("ai_tokens_input_total", 0)}')
        lines.append(f'ai_tokens_total{{provider="deepseek",direction="output"}} {d.get("ai_tokens_output_total", 0)}')

        for etype, count in d.get("email_sent_total", {}).items():
            lines.append(f'email_sent_total{{type="{etype}"}} {count}')

        lines.append(f"cache_hits_total {d.get('cache_hits_total', 0)}")
        lines.append(f"cache_misses_total {d.get('cache_misses_total', 0)}")

        for mode, count in d.get("pipeline_success_total", {}).items():
            lines.append(f'pipeline_success_total{{mode="{mode}"}} {count}')
        for mode, count in d.get("pipeline_failure_total", {}).items():
            lines.append(f'pipeline_failure_total{{mode="{mode}"}} {count}')

        for quantile, value in d.get("scoring_distribution", {}).items():
            if value is not None:
                lines.append(f'scoring_distribution{{quantile="{quantile}"}} {value}')

        ts = d.get("latest_scan_timestamp")
        if ts:
            lines.append(f"latest_scan_timestamp {ts}")

        return "\n".join(lines)
