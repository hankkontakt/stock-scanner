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
        return None

    try:
        # Kontrollera alder
        age_hours = (time.time() - p.stat().st_mtime) / 3600
        if age_hours > ttl_hours:
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
            return data.get("_data")

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
