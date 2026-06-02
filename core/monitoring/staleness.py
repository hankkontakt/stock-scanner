"""
staleness.py — Data Staleness Monitoring
=========================================
Övervakar ålder på alla datafiler, cache och modeller.
Ger en freshness-score (0-100) och listar föråldrade data.

Allt är non-blocking med try/except.
"""

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = ROOT / "data"
REPORT_DIR = ROOT / "reports"
MODELS_DIR = ROOT / "models"
CACHE_DIR = DATA_DIR / "cache"


class DataStalenessMonitor:
    """Övervakar ålder på alla datafiler och ger en freshness-score."""

    def __init__(self):
        self._threshold_hours_default = 48

    def check_all(self) -> dict[str, Any]:
        """
        Kolla alla datafiler och returnera status per typ.
        Returnerar dict med freshness-info för varje kategori.
        """
        now = time.time()
        report = {
            "reports": self._check_reports(now),
            "cache": self._check_cache(now),
            "models": self._check_models(now),
            "holdings": self._check_holdings(now),
            "checked_at": datetime.now().isoformat(),
        }
        return report

    def get_freshness_score(self) -> int:
        """
        Beräkna en freshness-score 0-100 (viktat medelvärde).
        Högre = färskare data.
        """
        try:
            report = self.check_all()
            scores = []

            # Reports (vikt 40%)
            rep = report.get("reports", {})
            latest_age = rep.get("latest_age_hours")
            if latest_age is not None:
                s = max(0, 100 - (latest_age / 48 * 100))
                scores.append((s, 40))

            # Cache (vikt 20%)
            cache = report.get("cache", {})
            cache_age = cache.get("oldest_hours")
            if cache_age is not None and cache.get("n_files", 0) > 0:
                s = max(0, 100 - (cache_age / 72 * 100))
                scores.append((s, 20))

            # Models (vikt 25%)
            models = report.get("models", {})
            model_age = models.get("newest_age_hours")
            if model_age is not None:
                s = max(0, 100 - (model_age / 720 * 100))  # 30 dagar = 0%
                scores.append((s, 25))

            # Holdings (vikt 15%)
            holdings = report.get("holdings", {})
            holdings_age = holdings.get("age_hours")
            if holdings_age is not None:
                s = max(0, 100 - (holdings_age / 168 * 100))  # 7 dagar = 0%
                scores.append((s, 15))

            if not scores:
                return 0
            total_weight = sum(w for _, w in scores)
            if total_weight == 0:
                return 0
            weighted = sum(s * w for s, w in scores) / total_weight
            return int(round(weighted))
        except Exception:
            return 0

    def get_stale_items(self, threshold_hours: float = 48) -> list[dict]:
        """
        Returnera lista av data som är äldre än threshold_hours.
        Varje post: {"type": str, "path": str, "age_hours": float}
        """
        stale = []
        now = time.time()
        try:
            # Reports
            for f in sorted(REPORT_DIR.glob("scored_universe_*"), reverse=True)[:1]:
                age = (now - f.stat().st_mtime) / 3600
                if age > threshold_hours:
                    stale.append({"type": "report", "path": str(f), "age_hours": round(age, 1)})
            # Cache
            if CACHE_DIR.exists():
                for f in CACHE_DIR.glob("cache_*"):
                    age = (now - f.stat().st_mtime) / 3600
                    if age > threshold_hours:
                        stale.append({"type": "cache", "path": f.name, "age_hours": round(age, 1)})
            # Models
            if MODELS_DIR.exists():
                for f in MODELS_DIR.glob("*.pkl"):
                    age = (now - f.stat().st_mtime) / 3600
                    if age > threshold_hours:
                        stale.append({"type": "model", "path": f.name, "age_hours": round(age, 1)})
            # Holdings
            holdings_file = DATA_DIR / "holdings.csv"
            if holdings_file.exists():
                age = (now - holdings_file.stat().st_mtime) / 3600
                if age > threshold_hours:
                    stale.append({"type": "holdings", "path": "holdings.csv", "age_hours": round(age, 1)})

            # Sortera: äldst först
            stale.sort(key=lambda x: x["age_hours"], reverse=True)
        except Exception:
            pass
        return stale

    def auto_refresh_suggestions(self) -> list[str]:
        """
        Föreslå automatiska åtgärder baserat på data-ålder.
        Returnerar lista med rekommendationer (str).
        """
        suggestions = []
        try:
            report = self.check_all()

            # Cache-ålder
            cache = report.get("cache", {})
            oldest = cache.get("oldest_hours", 0)
            if oldest > 72:
                suggestions.append("Kör weekly scan (cache {}h gammal)".format(round(oldest)))

            # Model-age
            models = report.get("models", {})
            model_age_days = models.get("newest_age_days", 0)
            if model_age_days > 30:
                suggestions.append(f"Träna om ML-modell (senast tränad för {int(model_age_days)} dagar sedan)")

            # Reports
            rep = report.get("reports", {})
            report_age = rep.get("latest_age_hours", 0)
            if report_age > 48:
                suggestions.append("Senaste scored_universe är {}h gammal - kör pipeline".format(round(report_age)))

            # Holdings
            holdings = report.get("holdings", {})
            holdings_age = holdings.get("age_hours", 0)
            if holdings_age > 168:
                suggestions.append(f"Portföljdata är {int(holdings_age / 24)} dagar gammal - uppdatera holdings.csv")

        except Exception:
            pass
        return suggestions

    # ── Interna hjälpmetoder ───────────────────────────────────────────────

    def _check_reports(self, now: float) -> dict[str, Any]:
        """Kolla ålder på scored_universe-rapporter."""
        result: dict[str, Any] = {"n_files": 0, "latest_age_hours": None, "latest_file": None}
        try:
            files = sorted(REPORT_DIR.glob("scored_universe_*"), reverse=True)
            if files:
                result["n_files"] = len(files)
                newest = files[0]
                age = (now - newest.stat().st_mtime) / 3600
                result["latest_age_hours"] = round(age, 1)
                result["latest_file"] = newest.name
                # Schema-kontroll: förväntar oss daily
                try:
                    from datetime import timedelta
                    cutoff = now - timedelta(hours=26).total_seconds()
                    result["within_last_26h"] = newest.stat().st_mtime > cutoff
                except Exception:
                    result["within_last_26h"] = False
        except Exception:
            pass
        return result

    def _check_cache(self, now: float) -> dict[str, Any]:
        """Kolla ålder på cache-filer."""
        result: dict[str, Any] = {"n_files": 0, "oldest_hours": None, "by_type": {}}
        try:
            if not CACHE_DIR.exists():
                return result
            files = list(CACHE_DIR.glob("cache_*"))
            result["n_files"] = len(files)
            ages = [(now - f.stat().st_mtime) / 3600 for f in files] if files else []
            result["oldest_hours"] = round(max(ages), 1) if ages else None
            # Fördelning per typ: fundamentals vs prices vs AI
            for f in files:
                fname = f.name.lower()
                if "finnhub" in fname or "sentiment" in fname:
                    t = "sentiment"
                elif "info" in fname or "static" in fname or "fund" in fname:
                    t = "fundamentals"
                elif "prices" in fname or "price" in fname or "sek:" in fname:
                    t = "prices"
                else:
                    t = "other"
                result["by_type"][t] = result["by_type"].get(t, 0) + 1
        except Exception:
            pass
        return result

    def _check_models(self, now: float) -> dict[str, Any]:
        """Kolla ålder på ML-modellerna."""
        result: dict[str, Any] = {"n_files": 0, "newest_age_hours": None, "newest_age_days": None}
        try:
            if not MODELS_DIR.exists():
                return result
            files = list(MODELS_DIR.glob("*.pkl"))
            if files:
                result["n_files"] = len(files)
                newest = max(files, key=lambda f: f.stat().st_mtime)
                age_hours = (now - newest.stat().st_mtime) / 3600
                result["newest_age_hours"] = round(age_hours, 1)
                result["newest_age_days"] = round(age_hours / 24, 1)
                result["newest_file"] = newest.name
        except Exception:
            pass
        return result

    def _check_holdings(self, now: float) -> dict[str, Any]:
        """Kolla ålder på holdings.csv."""
        result: dict[str, Any] = {"exists": False, "age_hours": None}
        try:
            path = DATA_DIR / "holdings.csv"
            if path.exists():
                result["exists"] = True
                age = (now - path.stat().st_mtime) / 3600
                result["age_hours"] = round(age, 1)
        except Exception:
            pass
        return result
