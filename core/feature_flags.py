"""
core/feature_flags.py
=====================
Enkelt feature flag-system för MarketScan.
Läser flaggor från data/feature_flags.json utan kod-deploy.

Användning:
    from core.feature_flags import is_enabled, set_flag
    if is_enabled("new_scoring_v2"):
        # ny kod
    else:
        # gammal kod

E5-implementation: JSON-fil, ingen extern dependency, admin-UI kan skriva flaggor.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_FLAGS_FILE = Path(__file__).resolve().parent.parent / "data" / "feature_flags.json"

# Defaults — säkra värden som behåller befintlig beteende
_DEFAULT_FLAGS: dict[str, Any] = {
    # Aktiverade fixes (satta till True som en del av audit-arbetet)
    "live_fx_rates": True,          # P4: live FX-kurser via yfinance
    "enhanced_rsi_filter": True,    # P3: RSI None → VÄNTA
    "atomic_csv_writes": True,      # D1: atomic tmp→rename CSV-skrivningar
    "sha256_ml_models": True,       # P5/S3: SHA-256 verifiering av ML-modeller

    # Under utveckling / experimentella
    "new_ml_features": False,       # Ny feature engineering (ej klar)
    "beta_scoring_v2": False,       # Experimentell scoring-version
    "walk_forward_cv": False,       # M6: walk-forward CV för ML (kostar CPU)
    "ai_ensemble_mode": False,      # Kör flera AI-providers parallellt
    "pydantic_settings": False,     # E7: Pydantic Settings (opt-in)
    "data_provider_v2": False,      # E1: ny DataProvider-abstraktion (opt-in)

    # Admin/debug
    "debug_scoring": False,         # Logga detaljerade scoring-steg
    "verbose_data_fetch": False,    # Detaljerad logging av datahämtning
    "dry_run_mode": False,          # Kör pipeline utan att skriva output
}

_FLAGS_CACHE: dict[str, Any] = {}
_FLAGS_MTIME: float = 0.0


def _load_flags() -> dict[str, Any]:
    """Läser feature_flags.json (med caching baserat på fil-mtime)."""
    global _FLAGS_CACHE, _FLAGS_MTIME
    try:
        mtime = _FLAGS_FILE.stat().st_mtime if _FLAGS_FILE.exists() else 0.0
        if mtime == _FLAGS_MTIME and _FLAGS_CACHE:
            return _FLAGS_CACHE
        if _FLAGS_FILE.exists():
            data = json.loads(_FLAGS_FILE.read_text(encoding="utf-8"))
            _FLAGS_CACHE = {**_DEFAULT_FLAGS, **data}
        else:
            _FLAGS_CACHE = dict(_DEFAULT_FLAGS)
        _FLAGS_MTIME = mtime
        return _FLAGS_CACHE
    except Exception as e:
        logger.debug("feature_flags._load_flags misslyckades: %s", e)
        return dict(_DEFAULT_FLAGS)


def is_enabled(flag: str, default: bool = False) -> bool:
    """Returnerar True om flaggan är aktiverad.

    Args:
        flag: Flaggnamn (t.ex. "live_fx_rates", "beta_scoring_v2")
        default: Standardvärde om flaggan inte finns i filen eller defaults

    Returns:
        bool: True om flaggan är satt till True
    """
    flags = _load_flags()
    val = flags.get(flag, _DEFAULT_FLAGS.get(flag, default))
    return bool(val)


def get_flag(flag: str, default: Any = None) -> Any:
    """Returnerar flaggans värde (kan vara str, int, list etc.)."""
    flags = _load_flags()
    return flags.get(flag, _DEFAULT_FLAGS.get(flag, default))


def get_all_flags() -> dict[str, Any]:
    """Returnerar alla flaggor med aktuella värden (merged med defaults)."""
    return dict(_load_flags())


def set_flag(flag: str, value: Any) -> bool:
    """Skriver ett flaggvärde till data/feature_flags.json.

    Används av Admin-UI för att ändra flaggor utan kod-deploy.

    Returns:
        True om skrivning lyckades, annars False.
    """
    global _FLAGS_CACHE, _FLAGS_MTIME
    try:
        _FLAGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        current = {}
        if _FLAGS_FILE.exists():
            try:
                current = json.loads(_FLAGS_FILE.read_text(encoding="utf-8"))
            except Exception:
                current = {}
        current[flag] = value
        tmp = _FLAGS_FILE.with_suffix(".tmp.json")
        tmp.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_FLAGS_FILE)
        # Invalidera cache
        _FLAGS_CACHE = {}
        _FLAGS_MTIME = 0.0
        logger.info("feature_flags: satte '%s' = %r", flag, value)
        return True
    except Exception as e:
        logger.error("feature_flags.set_flag('%s') misslyckades: %s", flag, e)
        return False


def _ensure_flags_file_exists() -> None:
    """Skapar feature_flags.json med defaults om den inte finns."""
    if not _FLAGS_FILE.exists():
        try:
            _FLAGS_FILE.parent.mkdir(parents=True, exist_ok=True)
            _FLAGS_FILE.write_text(
                json.dumps(_DEFAULT_FLAGS, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass
