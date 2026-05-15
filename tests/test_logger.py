"""
Test: logger.py
Kontrollerar grundläggande loggfunktioner.
"""
import json
import time
from pathlib import Path
from datetime import datetime

import pytest


class TestLogger:
    """Testar loggning och auto-remediation."""

    @pytest.fixture(autouse=True)
    def _temp_log(self, tmp_path):
        """Använder temporär loggfil."""
        import logger as _logger
        self._orig_log = _logger.LOG_FILE
        _logger.LOG_FILE = tmp_path / "scan_log.json"
        yield
        _logger.LOG_FILE = self._orig_log

    def test_log_event_ok(self):
        """log_event() måste spara OK-status."""
        import logger
        logger.log_event("full", "OK", details={"n_tickers": 100})
        entries = logger._load_log()
        assert len(entries) == 1
        assert entries[0]["status"] == "OK"
        assert entries[0]["scan_type"] == "full"

    def test_log_event_with_error(self):
        """log_event() måste spara ERROR med felmeddelande."""
        import logger
        logger.log_event("daily", "ERROR", details={}, error="Test error")
        entries = logger._load_log()
        assert len(entries) == 1
        assert entries[0]["status"] == "ERROR"
        assert entries[0]["error"] == "Test error"

    def test_scan_logger_ok(self):
        """scan_logger context manager måste logga OK vid lyckad körning."""
        import logger
        with logger.scan_logger("full", verbose=False) as meta:
            meta["n_tickers"] = 50
            meta["n_scored"] = 45
        entries = logger._load_log()
        assert len(entries) == 1
        assert entries[0]["status"] == "OK"

    def test_scan_logger_error(self):
        """scan_logger context manager måste logga ERROR vid exception."""
        import logger
        try:
            with logger.scan_logger("full", verbose=False):
                raise ValueError("Krasch!")
        except ValueError:
            pass
        entries = logger._load_log()
        assert len(entries) == 1
        assert entries[0]["status"] == "ERROR"

    def test_consecutive_failures(self):
        """get_consecutive_failures() måste räkna rätt."""
        import logger
        # Logga 2 errors
        logger.log_event("full", "ERROR", error="err1")
        logger.log_event("full", "ERROR", error="err2")
        assert logger.get_consecutive_failures() == 2
        # Logga en OK
        logger.log_event("full", "OK")
        assert logger.get_consecutive_failures() == 0

    def test_clear_stale_cache(self, tmp_path):
        """clear_stale_cache() måste rensa gamla filer."""
        import logger
        old_cache = logger.CACHE_DIR
        logger.CACHE_DIR = tmp_path / "cache"
        logger.CACHE_DIR.mkdir(parents=True, exist_ok=True)

        # Skapa en gammal cache-fil
        old_file = logger.CACHE_DIR / "old.pkl"
        old_file.touch()

        # Sätt mtime bakåt i tiden
        old_mtime = (datetime.now().timestamp() - 3600 * 48)
        import os
        os.utime(old_file, (old_mtime, old_mtime))

        # clear_stale_cache(max_age_hours=1) borde ta bort den
        count = logger.clear_stale_cache(max_age_hours=1)
        assert count >= 1
        assert not old_file.exists()

        logger.CACHE_DIR = old_cache

    def test_build_log_section(self):
        """build_log_section() måste returnera markdown."""
        import logger
        logger.log_event("full", "OK", details={"n_scored": 100, "elapsed_seconds": 30.0})
        section = logger.build_log_section()
        assert isinstance(section, str)
        assert "Systemlogg" in section

    def test_auto_remediate_rate_limit(self):
        """auto_remediate måste identifiera 429 rate-limit."""
        import logger
        # Simulera rate-limit error
        err = Exception("HTTP 429 Too Many Requests")
        remedy = logger.auto_remediate(err, "429 error occurred")
        assert remedy and "rate limit" in remedy.lower()
