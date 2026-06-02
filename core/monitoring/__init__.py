"""
core/monitoring/ — Monitoring, metrics, health och observability.
All monitoring är non-blocking; try/except på allt.
"""
from core.monitoring.metrics import MetricsCollector
from core.monitoring.health import system_health_check
from core.monitoring.staleness import DataStalenessMonitor
from core.monitoring.resources import (
    track_memory_usage,
    track_disk_usage,
    get_data_growth_rate,
    estimate_monthly_growth,
)

__all__ = [
    "MetricsCollector",
    "system_health_check",
    "DataStalenessMonitor",
    "track_memory_usage",
    "track_disk_usage",
    "get_data_growth_rate",
    "estimate_monthly_growth",
]
