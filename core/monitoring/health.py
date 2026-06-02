"""
health.py — System Health Check
================================
Komplett hälsokoll av systemet. Returnerar en dict med status för alla komponenter.
Allt är non-blocking med try/except. Anropas från Flask /health och admin-ui:t.
"""

import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from core import config

ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = ROOT / "data"
REPORT_DIR = ROOT / "reports"
MODELS_DIR = ROOT / "models"
CACHE_DIR = DATA_DIR / "cache"


def system_health_check() -> dict[str, Any]:
    """
    Utför en komplett hälsokoll av systemet.
    Returnerar dict med status för alla komponenter.
    """
    result: dict[str, Any] = {}

    # ── Övergripande status ────────────────────────────────────────────────
    api_keys = _check_api_keys()
    data_freshness = _check_data_freshness()
    model_status = _check_model_status()
    disk_usage = _check_disk_usage()
    recent_errors = _get_recent_errors()
    cache_stats = _get_cache_stats()
    portfolio_status = _get_portfolio_status()
    last_run = _get_last_pipeline_run()

    degraded = []
    if any(v == "missing" for v in api_keys.values()):
        degraded.append("api_keys")
    if data_freshness.get("stale", False):
        degraded.append("data_freshness")
    if model_status.get("universe_model") in ("missing", "stale"):
        degraded.append("model_status")

    overall = "degraded" if degraded else "healthy"

    result["status"] = overall
    result["api_keys"] = api_keys
    result["data_freshness"] = data_freshness
    result["model_status"] = model_status
    result["disk_usage"] = disk_usage
    result["recent_errors"] = recent_errors
    result["cache_stats"] = cache_stats
    result["portfolio_status"] = portfolio_status
    result["last_pipeline_run"] = last_run
    result["degraded_components"] = degraded
    result["checked_at"] = datetime.now().isoformat()

    return result


def _check_api_keys() -> dict[str, str]:
    """Kontrollera att API-nycklar finns konfigurerade."""
    keys = {
        "deepseek": "ok" if getattr(config, "DEEPSEEK_API_KEY", None) or os.getenv("DEEPSEEK_API_KEY") else "missing",
        "gemini": "ok" if getattr(config, "GEMINI_API_KEY", None) or os.getenv("GEMINI_API_KEY") else "missing",
        "finnhub": "ok" if getattr(config, "FINNHUB_API_KEY", None) or os.getenv("FINNHUB_API_KEY") else "missing",
    }
    return keys


def _check_data_freshness() -> dict[str, Any]:
    """Kontrollera hur färsk datan är."""
    try:
        latest = _latest_report_file("scored_universe_*")
        if latest:
            mtime = datetime.fromtimestamp(latest.stat().st_mtime)
            age_hours = (datetime.now() - mtime).total_seconds() / 3600
            return {
                "latest_scan": mtime.strftime("%Y-%m-%d %H:%M"),
                "age_hours": round(age_hours, 1),
                "file": latest.name,
                "stale": age_hours > 48,
            }
    except Exception:
        pass
    return {"latest_scan": None, "age_hours": None, "stale": True}


def _check_model_status() -> dict[str, Any]:
    """Kontrollera ML-modellernas status och ålder."""
    result: dict[str, Any] = {}
    try:
        model_files = list(MODELS_DIR.glob("*.pkl")) if MODELS_DIR.exists() else []
        universe_model = None
        for mf in model_files:
            if "universe" in mf.name.lower() or "model" in mf.name.lower():
                universe_model = mf
                break
        if universe_model:
            mtime = datetime.fromtimestamp(universe_model.stat().st_mtime)
            days = (datetime.now() - mtime).days
            result["universe_model"] = "stale" if days > 30 else "ok"
            result["days_since_training"] = days
            result["model_file"] = universe_model.name
        else:
            result["universe_model"] = "missing"
            result["days_since_training"] = None
    except Exception:
        result["universe_model"] = "missing"
        result["days_since_training"] = None
    return result


def _check_disk_usage() -> dict[str, Any]:
    """Mät diskutrymme för data- och rapportkataloger."""
    result: dict[str, Any] = {}
    try:
        data_size = _dir_size_mb(DATA_DIR) if DATA_DIR.exists() else 0
        reports_size = _dir_size_mb(REPORT_DIR) if REPORT_DIR.exists() else 0
        models_size = _dir_size_mb(MODELS_DIR) if MODELS_DIR.exists() else 0
        total = data_size + reports_size + models_size
        result["data_dir_mb"] = round(data_size, 1)
        result["reports_dir_mb"] = round(reports_size, 1)
        result["models_dir_mb"] = round(models_size, 1)
        result["total_mb"] = round(total, 1)
        result["total_gb"] = round(total / 1024, 2)
    except Exception:
        result["total_mb"] = -1
    # Ledigt diskutrymme
    try:
        import shutil
        usage = shutil.disk_usage(str(DATA_DIR))
        result["free_gb"] = round(usage.free / (1024**3), 1)
        result["total_gb_disk"] = round(usage.total / (1024**3), 1)
    except Exception:
        result["free_gb"] = None
    return result


def _get_recent_errors(n: int = 5) -> list[dict]:
    """Hämta de senaste N felen från scan_log."""
    try:
        log_file = DATA_DIR / "scan_log.json"
        if log_file.exists():
            entries = json.loads(log_file.read_text(encoding="utf-8"))
            errors = []
            for e in reversed(entries):
                if e.get("status") == "ERROR":
                    errors.append({
                        "timestamp": e.get("timestamp", "?"),
                        "error": str(e.get("error", ""))[:200],
                        "module": e.get("scan_type", "?"),
                    })
                    if len(errors) >= n:
                        break
            return errors
    except Exception:
        pass
    return []


def _get_cache_stats() -> dict[str, Any]:
    """Statistik över cache-filer."""
    result: dict[str, Any] = {"total_files": 0, "oldest_hours": 0, "total_size_mb": 0}
    try:
        if not CACHE_DIR.exists():
            return result
        files = list(CACHE_DIR.glob("cache_*"))
        result["total_files"] = len(files)
        if files:
            now = time.time()
            ages = [(now - f.stat().st_mtime) / 3600 for f in files]
            sizes = [f.stat().st_size for f in files]
            result["oldest_hours"] = round(max(ages), 1) if ages else 0
            result["total_size_mb"] = round(sum(sizes) / (1024**2), 1)
            result["avg_age_hours"] = round(sum(ages) / len(ages), 1) if ages else 0
    except Exception:
        pass
    return result


def _get_portfolio_status() -> dict[str, Any]:
    """Läs portfolio-statistik."""
    result: dict[str, Any] = {"n_holdings": 0, "n_watchlist": 0, "n_open_trades": 0}
    try:
        holdings_file = DATA_DIR / "holdings.csv"
        if holdings_file.exists():
            df = pd.read_csv(holdings_file)
            result["n_holdings"] = len(df)
    except Exception:
        pass
    try:
        wl_file = DATA_DIR / "watchlist.json"
        if wl_file.exists():
            wl = json.loads(wl_file.read_text(encoding="utf-8"))
            result["n_watchlist"] = len(wl) if isinstance(wl, list) else 0
    except Exception:
        pass
    return result


def _get_last_pipeline_run() -> dict[str, Any]:
    """Hämta info om senaste pipeline-körning."""
    try:
        log_file = DATA_DIR / "scan_log.json"
        if log_file.exists():
            entries = json.loads(log_file.read_text(encoding="utf-8"))
            if entries:
                last = entries[-1]
                return {
                    "mode": last.get("scan_type", "?"),
                    "status": last.get("status", "?"),
                    "duration": last.get("details", {}).get("elapsed_seconds"),
                    "timestamp": last.get("timestamp", "?"),
                }
    except Exception:
        pass
    return {"mode": None, "status": None, "duration": None, "timestamp": None}


def _latest_report_file(pattern: str) -> Path | None:
    """Hitta senaste rapportfil som matchar mönster."""
    try:
        files = sorted(REPORT_DIR.glob(pattern), reverse=True)
        return files[0] if files else None
    except Exception:
        return None


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


def check_data_coverage(scored_df: pd.DataFrame) -> dict[str, Any]:
    """Kontrollera datatäckning per faktor-kolumn i scored DataFrame."""
    if scored_df is None or scored_df.empty:
        return {"total_rows": 0, "coverage": {}}

    result: dict[str, Any] = {
        "total_rows": len(scored_df),
        "coverage": {},
    }
    factor_cols = [
        "score_total", "score_value", "score_quality", "score_momentum",
        "score_growth", "score_risk", "score_dividend", "score_sentiment",
        "pe_trailing", "price_to_book", "roe", "profit_margin",
        "return_12m", "return_6m", "revenue_growth", "earnings_growth",
        "debt_to_equity", "volatility", "dividend_yield", "rsi_14",
    ]
    for col in factor_cols:
        if col in scored_df.columns:
            n_non_null = scored_df[col].notna().sum()
            pct = round(n_non_null / len(scored_df) * 100, 1)
            result["coverage"][col] = {
                "non_null": int(n_non_null),
                "coverage_pct": pct,
                "mean": round(float(scored_df[col].mean()), 2) if scored_df[col].dtype.kind in "fi" else None,
            }
    return result


def check_model_performance() -> dict[str, Any]:
    """Hämta senaste IC, hit rate och training timestamp för ML-modellen."""
    result: dict[str, Any] = {
        "last_ic": None,
        "hit_rate": None,
        "last_training": None,
        "model_available": False,
    }
    try:
        model_files = list(MODELS_DIR.glob("*.pkl")) if MODELS_DIR.exists() else []
        if model_files:
            result["model_available"] = True
            newest = max(model_files, key=lambda f: f.stat().st_mtime)
            result["last_training"] = datetime.fromtimestamp(newest.stat().st_mtime).isoformat()
    except Exception:
        pass
    return result


def save_health_snapshot():
    """Spara health snapshot till data/health/health_{date}.json."""
    try:
        health_dir = DATA_DIR / "health"
        health_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now().strftime("%Y%m%d")
        path = health_dir / f"health_{now}.json"
        data = system_health_check()
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        # Rensa gamla snapshots (behåll 90 dagar)
        files = sorted(health_dir.glob("health_*.json"), reverse=True)
        for f in files[90:]:
            f.unlink(missing_ok=True)
    except Exception:
        pass  # Non-blocking
