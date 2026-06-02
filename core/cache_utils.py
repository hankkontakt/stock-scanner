"""
cache_utils.py — Gemensam cache-hjalp for alla core-moduler.
Ersatter 10+ individuella pickle-baserade cache-implementationer.

Anvandning:
    from core.cache_utils import read_cache, write_cache

    data = read_cache("my_key", ttl_hours=24)
    if data is None:
        data = expensive_operation()
        write_cache("my_key", data)
"""
import hashlib
import json
import logging
import pickle
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Gemensam cache-katalog (ankar i repo-roten)
CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Cache-version stampel: okas vid inkompatibla andringar
_CACHE_VERSION = 1


def _cache_path(key: str, suffix: str = ".pkl") -> Path:
    """Generera en deterministisk cache-fil-vag baserat pa nyckel."""
    h = hashlib.md5(key.encode()).hexdigest()
    return CACHE_DIR / f"cache_{h}{suffix}"


def read_cache(key: str, ttl_hours: float = 24, use_json: bool = False) -> Any:
    """
    Las cachad data om den finns och ar farsk.

    Args:
        key: Unik identifierare for cache-posten.
        ttl_hours: Max alder i timmar. Default 24h.
        use_json: Anvand JSON istallet for pickle (for enkel data).

    Returns:
        Cachade data, eller None om cache-miss / gammal.
    """
    suffix = ".json" if use_json else ".pkl"
    p = _cache_path(key, suffix)
    if not p.exists():
        # Record cache miss
        try:
            from core.monitoring.metrics import MetricsCollector
            MetricsCollector().record_cache_miss()
        except Exception:
            pass
        return None

    try:
        # Kontrollera alder
        age_hours = (time.time() - p.stat().st_mtime) / 3600
        if age_hours > ttl_hours:
            # Record cache miss (expired)
            try:
                from core.monitoring.metrics import MetricsCollector
                MetricsCollector().record_cache_miss()
            except Exception:
                pass
            return None

        if use_json:
            data = json.loads(p.read_text(encoding="utf-8"))
        else:
            with open(p, "rb") as f:
                data = pickle.load(f)

        # Kontrollera cache-version (om sparad)
        if isinstance(data, dict) and "_cache_version" in data:
            if data["_cache_version"] != _CACHE_VERSION:
                return None
            # Record cache hit
            try:
                from core.monitoring.metrics import MetricsCollector
                MetricsCollector().record_cache_hit()
            except Exception:
                pass
            return data.get("_data")

        # Record cache hit
        try:
            from core.monitoring.metrics import MetricsCollector
            MetricsCollector().record_cache_hit()
        except Exception:
            pass

        return data
    except Exception:
        # Korrupt cache = behandla som cache-miss
        try:
            p.unlink(missing_ok=True)
        except Exception:
            pass
        return None


def write_cache(key: str, data: Any, use_json: bool = False) -> bool:
    """
    Spara data i cachen med atomisk skrivning.

    Args:
        key: Unik identifierare.
        data: Data att cacha.
        use_json: Anvand JSON istallet for pickle.

    Returns:
        True om lyckades, False vid fel.
    """
    suffix = ".json" if use_json else ".pkl"
    p = _cache_path(key, suffix)
    tmp = p.with_suffix(suffix + ".tmp")

    try:
        # Packa med cache-version for framtida kompatibilitetskontroll
        if isinstance(data, dict):
            to_save = {"_cache_version": _CACHE_VERSION, "_data": data}
        else:
            # For icke-dict data (listor, skalara, DataFrames), spara under wrapper
            to_save = {"_cache_version": _CACHE_VERSION, "_data": data}

        if use_json:
            tmp.write_text(json.dumps(to_save, ensure_ascii=False, default=str), encoding="utf-8")
        else:
            with open(tmp, "wb") as f:
                pickle.dump(to_save, f)

        tmp.replace(p)
        return True
    except Exception as e:
        logger.debug(f"Cache write misslyckades for {key}: {e}")
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        return False


def clear_cache(pattern: str = "") -> int:
    """
    Rensa cachade filer. Om pattern anges, rensas bara matchande.

    Args:
        pattern: Text-match mot filnamn (t.ex. "sector_momentum").

    Returns:
        Antal borttagna filer.
    """
    removed = 0
    for f in CACHE_DIR.glob("cache_*"):
        if not pattern or pattern in f.name:
            try:
                f.unlink()
                removed += 1
            except Exception:
                pass
    return removed


def clear_stale_cache(max_age_hours: float = 48) -> int:
    """
    Rensa all cache aldre an max_age_hours.

    Args:
        max_age_hours: Max alder i timmar innan rensning.

    Returns:
        Antal borttagna filer.
    """
    cutoff = time.time() - max_age_hours * 3600
    removed = 0
    for f in CACHE_DIR.glob("cache_*"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
                removed += 1
        except Exception:
            pass
    return removed


# ══════════════════════════════════════════════════════════════════════════════
# CACHE ANALYTICS
# ══════════════════════════════════════════════════════════════════════════════

class CacheAnalytics:
    """Analys och statistik över cache-innehållet."""

    @staticmethod
    def get_cache_size() -> float:
        """Total storlek i MB."""
        total = 0
        try:
            for f in CACHE_DIR.glob("cache_*"):
                total += f.stat().st_size
        except Exception:
            pass
        return round(total / (1024**2), 1)

    @staticmethod
    def get_cache_count() -> int:
        """Antal cache-filer."""
        try:
            return len(list(CACHE_DIR.glob("cache_*")))
        except Exception:
            return 0

    @staticmethod
    def get_cache_by_type() -> dict[str, int]:
        """Fördelning: fundamentals vs prices vs AI vs sentiment vs other."""
        by_type: dict[str, int] = {}
        try:
            for f in CACHE_DIR.glob("cache_*"):
                fname = f.name.lower()
                if "finnhub" in fname or "sentiment" in fname:
                    t = "sentiment"
                elif "info_" in fname or "static" in fname or "fund" in fname:
                    t = "fundamentals"
                elif "prices" in fname or "price:" in fname or "sek:" in fname:
                    t = "prices"
                else:
                    t = "other"
                by_type[t] = by_type.get(t, 0) + 1
        except Exception:
            pass
        return by_type

    @staticmethod
    def get_hit_rate() -> float:
        """
        Cache hit/miss ratio (om tracking installerad).
        Returnerar ratio 0.0-1.0, eller -1 om ingen data.
        """
        try:
            from core.monitoring.metrics import MetricsCollector
            mc = MetricsCollector()
            hits = mc.cache_hits
            misses = mc.cache_misses
            total = hits + misses
            if total == 0:
                return -1.0
            return round(hits / total, 3)
        except Exception:
            return -1.0

    @staticmethod
    def get_stale_percentage(max_age_hours: float = 48) -> float:
        """Andel gammal cache (äldre än max_age_hours)."""
        cutoff = time.time() - max_age_hours * 3600
        stale = 0
        total = 0
        try:
            for f in CACHE_DIR.glob("cache_*"):
                total += 1
                if f.stat().st_mtime < cutoff:
                    stale += 1
        except Exception:
            pass
        if total == 0:
            return 0.0
        return round(stale / total * 100, 1)

    @staticmethod
    def get_oldest_cache() -> dict | None:
        """Äldsta filens info."""
        oldest = None
        oldest_age = 0
        now = time.time()
        try:
            for f in CACHE_DIR.glob("cache_*"):
                age = now - f.stat().st_mtime
                if age > oldest_age:
                    oldest_age = age
                    oldest = {
                        "name": f.name,
                        "age_hours": round(age / 3600, 1),
                        "age_days": round(age / 86400, 1),
                        "size_kb": round(f.stat().st_size / 1024, 1),
                    }
        except Exception:
            pass
        return oldest

    @staticmethod
    def get_largest_cache(top_n: int = 10) -> list[dict]:
        """Största cache-filerna."""
        files = []
        try:
            for f in CACHE_DIR.glob("cache_*"):
                files.append({
                    "name": f.name,
                    "size_kb": round(f.stat().st_size / 1024, 1),
                    "size_mb": round(f.stat().st_size / (1024**2), 2),
                })
            files.sort(key=lambda x: x["size_kb"], reverse=True)
        except Exception:
            pass
        return files[:top_n]

    @staticmethod
    def to_dict() -> dict:
        """Sammanfattning av all cache-statistik."""
        return {
            "total_size_mb": CacheAnalytics.get_cache_size(),
            "total_files": CacheAnalytics.get_cache_count(),
            "by_type": CacheAnalytics.get_cache_by_type(),
            "hit_rate": CacheAnalytics.get_hit_rate(),
            "stale_pct_48h": CacheAnalytics.get_stale_percentage(48),
            "oldest": CacheAnalytics.get_oldest_cache(),
        }
