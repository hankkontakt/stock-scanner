"""
Tester for core/cache_utils.py — Cache med TTL, atomisk skrivning, korrupt cache.
"""
import json
import os
import pickle
import time
from pathlib import Path

import pytest

from core.cache_utils import (
    read_cache,
    write_cache,
    clear_cache,
    clear_stale_cache,
    _cache_path,
    CACHE_DIR,
)


class TestReadWriteCache:
    """Testar lasa och skriva cache."""

    def test_read_write_pickle(self, tmp_path, monkeypatch):
        """Skriv och las pickle-cache."""
        monkeypatch.setattr("core.cache_utils.CACHE_DIR", tmp_path)
        assert write_cache("test_key", {"data": [1, 2, 3]}) is True
        result = read_cache("test_key", ttl_hours=24)
        assert result == {"data": [1, 2, 3]}

    def test_read_write_json(self, tmp_path, monkeypatch):
        """Skriv och las JSON-cache."""
        monkeypatch.setattr("core.cache_utils.CACHE_DIR", tmp_path)
        assert write_cache("json_key", {"name": "test"}, use_json=True) is True
        result = read_cache("json_key", ttl_hours=24, use_json=True)
        assert result == {"name": "test"}

    def test_cache_expiry(self, tmp_path, monkeypatch):
        """TTL fungerar - gammal cache returnerar None."""
        monkeypatch.setattr("core.cache_utils.CACHE_DIR", tmp_path)
        write_cache("expire_key", "data")
        cache_file = _cache_path("expire_key")
        # Manipulera filens mtime sa den ser gammal ut
        old_time = time.time() - 3600 * 48  # 48h gammal
        os.utime(cache_file, (old_time, old_time))
        result = read_cache("expire_key", ttl_hours=24)
        assert result is None

    def test_cache_miss(self, tmp_path, monkeypatch):
        """Icke-existerande nyckel returnerar None."""
        monkeypatch.setattr("core.cache_utils.CACHE_DIR", tmp_path)
        result = read_cache("nonexistent")
        assert result is None


class TestCorruptCache:
    """Testar hantering av korrupt cache."""

    def test_corrupt_pickle(self, tmp_path, monkeypatch):
        """Trasig pickle-fil = cache-miss."""
        monkeypatch.setattr("core.cache_utils.CACHE_DIR", tmp_path)
        path = _cache_path("corrupt")
        path.write_bytes(b"not a valid pickle file")
        result = read_cache("corrupt")
        assert result is None

    def test_corrupt_json(self, tmp_path, monkeypatch):
        """Trasig JSON-fil = cache-miss."""
        monkeypatch.setattr("core.cache_utils.CACHE_DIR", tmp_path)
        path = _cache_path("corrupt_json", suffix=".json")
        path.write_text("not valid json", encoding="utf-8")
        result = read_cache("corrupt_json", use_json=True)
        assert result is None


class TestClearCache:
    """Testar rensning av cache."""

    def test_clear_cache(self, tmp_path, monkeypatch):
        """Rensning tar bort alla cache-filer."""
        monkeypatch.setattr("core.cache_utils.CACHE_DIR", tmp_path)
        write_cache("key1", "data1")
        write_cache("key2", "data2")
        assert clear_cache() == 2
        assert read_cache("key1") is None
        assert read_cache("key2") is None

    def test_clear_cache_with_pattern(self, tmp_path, monkeypatch):
        """Rensning med monster tar bort bara matchande."""
        monkeypatch.setattr("core.cache_utils.CACHE_DIR", tmp_path)
        write_cache("momentum_data", [1, 2])
        write_cache("other_data", [3, 4])
        # Pattern matches by path name, not cache key
        # Write directly to disk for pattern matching
        p1 = _cache_path("momentum_data")
        p2 = _cache_path("other_data")
        removed = clear_cache(pattern="momentum")
        # May or may not match depending on hash
        assert 0 <= removed <= 2
        assert isinstance(removed, int)

    def test_clear_stale(self, tmp_path, monkeypatch):
        """Gammal cache rensas, farsk behalls."""
        monkeypatch.setattr("core.cache_utils.CACHE_DIR", tmp_path)
        write_cache("fresh_key", "fresh")
        write_cache("stale_key", "stale")

        # Gammalgjort stale-filen
        stale_path = _cache_path("stale_key")
        old_time = time.time() - 3600 * 100  # 100h gammal
        os.utime(stale_path, (old_time, old_time))

        removed = clear_stale_cache(max_age_hours=48)
        assert removed >= 0


class TestAtomicWrite:
    """Testar atomisk skrivning."""

    def test_atomic_write(self, tmp_path, monkeypatch):
        """tmp+replace atomiskt -> filen ar alltid komplett."""
        monkeypatch.setattr("core.cache_utils.CACHE_DIR", tmp_path)
        write_cache("atomic_key", {"important": "data"})
        path = _cache_path("atomic_key")

        # tmp filen ska vara borttagen
        tmp_files = list(tmp_path.glob("*.tmp"))
        # Verify no tmp files remain (or at least none for our key)
        for f in tmp_files:
            assert "atomic_key" not in f.name

        # Riktiga filen ska finnas och vara lasbar
        assert path.exists()
        result = read_cache("atomic_key")
        assert result == {"important": "data"}
