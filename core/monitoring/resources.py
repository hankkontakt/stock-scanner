"""
resources.py — Memory & Resource Monitoring
============================================
Övervakar minnesanvändning, diskutrymme och datatillväxt.
Allt är non-blocking med try/except.
"""

import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = ROOT / "data"
REPORT_DIR = ROOT / "reports"
MODELS_DIR = ROOT / "models"
CACHE_DIR = DATA_DIR / "cache"

# Historik för tillväxtberäkning — cachad i denna modul
_growth_history: list[dict] = []
_last_growth_check: float = 0


def track_memory_usage() -> dict[str, Any]:
    """
    Mät peak memory usage med tracemalloc om tillgängligt.
    Returnerar dict med minnesstatistik.
    """
    result: dict[str, Any] = {
        "current_mb": None,
        "peak_mb": None,
        "method": "none",
    }
    try:
        import tracemalloc
        if tracemalloc.is_tracing():
            snapshot = tracemalloc.take_snapshot()
            stats = snapshot.statistics("lineno")
            if stats:
                total_size = sum(s.size for s in stats[:50])
                result["peak_mb"] = round(total_size / (1024**2), 2)
                result["method"] = "tracemalloc"
    except ImportError:
        pass
    except Exception:
        pass

    # Fallback: psutil
    if result["current_mb"] is None:
        try:
            import psutil
            proc = psutil.Process()
            mem = proc.memory_info()
            result["current_mb"] = round(mem.rss / (1024**2), 1)
            result["peak_mb"] = round(getattr(mem, "peak_wset", mem.rss) / (1024**2), 1)
            result["method"] = "psutil"
        except ImportError:
            pass
        except Exception:
            pass

    return result


def track_disk_usage() -> dict[str, Any]:
    """
    Mät diskutrymme för data/, reports/ och models/-kataloger.
    Returnerar dict med diskstatistik per kategori.
    """
    result: dict[str, Any] = {
        "data_mb": _dir_size_mb(DATA_DIR),
        "reports_mb": _dir_size_mb(REPORT_DIR),
        "models_mb": _dir_size_mb(MODELS_DIR) if MODELS_DIR.exists() else 0,
        "cache_mb": _dir_size_mb(CACHE_DIR) if CACHE_DIR.exists() else 0,
    }
    result["total_mb"] = round(
        result["data_mb"] + result["reports_mb"] + result["models_mb"], 1
    )
    # Ledigt diskutrymme
    try:
        import shutil
        usage = shutil.disk_usage(str(DATA_DIR))
        result["free_gb"] = round(usage.free / (1024**3), 1)
        result["total_gb_disk"] = round(usage.total / (1024**3), 1)
    except Exception:
        result["free_gb"] = None
    return result


def get_data_growth_rate(days_back: int = 30) -> dict[str, Any]:
    """
    Beräkna hur snabbt datan växer.
    Returnerar dict med daglig tillväxttakt och historik.
    """
    global _growth_history, _last_growth_check

    result: dict[str, Any] = {
        "daily_growth_mb": 0,
        "weekly_growth_mb": 0,
        "monthly_growth_mb": 0,
        "history": [],
    }

    try:
        now = time.time()
        # Uppdatera högst var 5:e minut
        if now - _last_growth_check < 300 and _growth_history:
            result["history"] = _growth_history[-30:]
            if len(_growth_history) >= 2:
                first = _growth_history[0]
                last = _growth_history[-1]
                days = (last["timestamp"] - first["timestamp"]) / 86400
                if days > 0:
                    growth_mb = last["total_mb"] - first["total_mb"]
                    result["daily_growth_mb"] = round(growth_mb / days, 2)
                    result["weekly_growth_mb"] = round(growth_mb / days * 7, 2)
                    result["monthly_growth_mb"] = round(growth_mb / days * 30, 2)
            return result

        # Mät nuvarande diskstorlek
        total = _dir_size_mb(DATA_DIR) + _dir_size_mb(REPORT_DIR)
        if MODELS_DIR.exists():
            total += _dir_size_mb(MODELS_DIR)

        _growth_history.append({
            "timestamp": now,
            "total_mb": round(total, 1),
            "date": datetime.now().strftime("%Y-%m-%d"),
        })

        # Behåll bara 90 dagar
        cutoff = now - 90 * 86400
        _growth_history[:] = [h for h in _growth_history if h["timestamp"] >= cutoff]

        if len(_growth_history) >= 2:
            first = _growth_history[0]
            last = _growth_history[-1]
            days = (last["timestamp"] - first["timestamp"]) / 86400
            if days > 0:
                growth_mb = last["total_mb"] - first["total_mb"]
                result["daily_growth_mb"] = round(growth_mb / days, 2)
                result["weekly_growth_mb"] = round(growth_mb / days * 7, 2)
                result["monthly_growth_mb"] = round(growth_mb / days * 30, 2)

        result["history"] = _growth_history[-30:]
        _last_growth_check = now

    except Exception:
        pass

    return result


def estimate_monthly_growth(months_ahead: int = 6) -> dict[str, Any]:
    """
    Prediktera framtida lagringsbehov baserat på historisk tillväxt.
    Returnerar dict med estimat per månad.
    """
    result: dict[str, Any] = {
        "current_mb": 0,
        "estimates": [],
    }
    try:
        growth = get_data_growth_rate()
        daily_mb = growth.get("daily_growth_mb", 0)
        current = _dir_size_mb(DATA_DIR) + _dir_size_mb(REPORT_DIR)
        if MODELS_DIR.exists():
            current += _dir_size_mb(MODELS_DIR)

        result["current_mb"] = round(current, 1)

        for m in range(1, months_ahead + 1):
            future = current + daily_mb * 30 * m
            result["estimates"].append({
                "month": m,
                "estimated_mb": round(future, 1),
                "estimated_gb": round(future / 1024, 2),
            })

    except Exception:
        pass

    return result


def _dir_size_mb(path: Path) -> float:
    """Summera filstorlekar i en katalog (MB)."""
    total = 0
    try:
        for f in path.rglob("*"):
            if f.is_file():
                total += f.stat().st_size
    except Exception:
        pass
    return total / (1024**2)
