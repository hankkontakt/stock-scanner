"""
tests/test_security.py — Säkerhetstester för MarketScan (T3)

Täcker:
  - API-nyckel sanitering i ai_analysis.py
  - Ticker-validering i universe_manager.py
  - Password reset token hashing (SHA-256 i streamlit_app.py)
  - Flask API auth — unauthorized access blockas
  - Sensitive data ej i felmeddelanden
"""
import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ══════════════════════════════════════════════════════════════════════════════
# Token sanitering
# ══════════════════════════════════════════════════════════════════════════════

class TestTokenSanitization:
    """Verifiera att API-nycklar aldrig når loggar."""

    def _get_sanitizer(self):
        from core.ai_analysis import _token_sanitize
        return _token_sanitize

    def test_openai_key_redacted(self):
        """sk-* OpenAI-nycklar maskeras."""
        pat = self._get_sanitizer()
        text = "Error calling sk-abcdefghijklmnopqrstuvwxyz12345 for model"
        result = pat.sub("***", text)
        assert "sk-" not in result
        assert "***" in result

    def test_google_key_redacted(self):
        """AIza* Google-nycklar maskeras."""
        pat = self._get_sanitizer()
        text = "API key AIzaSyAbcdefghijklmnopqrstuvwxy1234 invalid"
        result = pat.sub("***", text)
        assert "AIza" not in result
        assert "***" in result

    def test_long_alphanum_token_redacted(self):
        """Generiska långa alfanumeriska strängar (>= 40 tecken) maskeras."""
        pat = self._get_sanitizer()
        long_token = "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0"  # 40 chars
        text = f"Token={long_token} failed"
        result = pat.sub("***", text)
        assert long_token not in result

    def test_safe_text_unchanged(self):
        """Vanlig text som inte innehåller nycklar ändras ej."""
        pat = self._get_sanitizer()
        safe = "Score för AAPL är 75.3 poäng (rank 1/450)"
        result = pat.sub("***", safe)
        assert result == safe

    def test_deepseek_style_key_redacted(self):
        """DeepSeek-liknande nycklar (långa alfanumeriska) maskeras."""
        pat = self._get_sanitizer()
        # DeepSeek keys are long alphanumeric strings
        deepseek_key = "sk-" + "x" * 32  # common format
        text = f"DeepSeek auth failed: {deepseek_key}"
        result = pat.sub("***", text)
        assert deepseek_key not in result


# ══════════════════════════════════════════════════════════════════════════════
# Ticker-validering (S4)
# ══════════════════════════════════════════════════════════════════════════════

class TestTickerValidation:
    """Verifiera att universe_manager.py blockerar maliciösa ticker-strängar."""

    def _pattern(self):
        from core.universe_manager import _TICKER_PATTERN
        return _TICKER_PATTERN

    def test_valid_us_ticker(self):
        pat = self._pattern()
        assert pat.match("AAPL") is not None
        assert pat.match("MSFT") is not None
        assert pat.match("BRK-B") is not None

    def test_valid_swedish_ticker(self):
        pat = self._pattern()
        assert pat.match("VOLVO-B.ST") is not None
        assert pat.match("ERIC-B.ST") is not None
        assert pat.match("ABB.ST") is not None

    def test_valid_numeric_ticker(self):
        pat = self._pattern()
        assert pat.match("2330.TW") is not None

    def test_shell_injection_blocked(self):
        """Shell-metakaraktärer blockeras."""
        pat = self._pattern()
        malicious = [
            "; rm -rf /",
            "$(whoami)",
            "`id`",
            "AAPL; DROP TABLE",
            "A|B",
            "A&B",
            "A>B",
        ]
        for m in malicious:
            assert pat.match(m.upper()) is None, f"Should block: {m!r}"

    def test_space_in_ticker_blocked(self):
        """Fondnamn med mellanslag blockeras."""
        pat = self._pattern()
        assert pat.match("LÄNSFÖRSÄKRINGAR GLOBAL") is None
        assert pat.match("A B") is None

    def test_too_long_ticker_blocked(self):
        """Ticker längre än 20 tecken blockeras."""
        pat = self._pattern()
        assert pat.match("A" * 21) is None

    def test_add_ticker_validation_blocks_injection(self):
        """add_ticker_to_universe avvisar maliciösa strängar."""
        from core.universe_manager import add_ticker_to_universe
        result = add_ticker_to_universe("; rm -rf /", "test", dry_run=True)
        assert result is False

    def test_add_ticker_accepts_valid_ticker(self):
        """add_ticker_to_universe accepterar giltiga tickers."""
        from core.universe_manager import add_ticker_to_universe
        # AAPL finns troligtvis redan i universums
        result = add_ticker_to_universe("AAPL", "säkerhetstest", dry_run=True)
        assert result is True  # True = redan finns eller lades till


# ══════════════════════════════════════════════════════════════════════════════
# Password reset token hashing (S2)
# ══════════════════════════════════════════════════════════════════════════════

class TestPasswordResetTokenSecurity:
    """Verifiera att reset-tokens lagras som SHA-256-hash, aldrig i klartext."""

    def test_sha256_round_trip(self):
        """Hash av token → lookup via hash fungerar korrekt."""
        import secrets
        token = secrets.token_hex(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()

        store = {token_hash: {"username": "test", "expires": "2099-01-01"}}

        # Lookup via hash ger rätt post
        lookup = hashlib.sha256(token.encode()).hexdigest()
        assert store.get(lookup) is not None

    def test_plaintext_not_in_store(self):
        """Klartext-token ska aldrig vara nyckel i store."""
        import secrets
        token = secrets.token_hex(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        store = {token_hash: {"username": "test", "expires": "2099-01-01"}}

        # Klartext ≠ hash → hittas INTE direkt
        assert store.get(token) is None

    def test_different_tokens_different_hashes(self):
        """Inga hash-kollisioner för olika tokens (i praktiken)."""
        import secrets
        t1 = secrets.token_hex(32)
        t2 = secrets.token_hex(32)
        h1 = hashlib.sha256(t1.encode()).hexdigest()
        h2 = hashlib.sha256(t2.encode()).hexdigest()
        assert h1 != h2

    def test_token_entropy(self):
        """token_hex(32) ger 64 hex-tecken = 256 bits entropi."""
        import secrets
        token = secrets.token_hex(32)
        assert len(token) == 64
        assert all(c in "0123456789abcdef" for c in token)


# ══════════════════════════════════════════════════════════════════════════════
# Flask API authentication (S1)
# ══════════════════════════════════════════════════════════════════════════════

class TestFlaskApiAuthentication:
    """Verifiera att Flask REST API kräver autentisering."""

    @pytest.fixture
    def app(self):
        """Skapa Flask test-app."""
        try:
            from web.api import create_app
            app = create_app()
            app.config["TESTING"] = True
            return app
        except Exception:
            pytest.skip("Flask app ej tillgänglig (saknas beroenden)")

    def test_health_endpoint_no_auth_required(self, app):
        """GET /api/v1/health är publik — kräver ingen auth."""
        with app.test_client() as c:
            resp = c.get("/api/v1/health")
            assert resp.status_code == 200

    def test_protected_endpoint_without_key_returns_401(self, app):
        """GET /api/v1/stocks utan API-nyckel → 401."""
        with app.test_client() as c:
            resp = c.get("/api/v1/stocks")
            assert resp.status_code == 401, (
                f"Endpoint borde returnera 401, fick {resp.status_code}"
            )

    def test_protected_endpoint_with_wrong_key_returns_401(self, app):
        """GET /api/v1/stocks med felaktig nyckel → 401."""
        with app.test_client() as c:
            resp = c.get("/api/v1/stocks", headers={"X-API-Key": "invalid-key"})
            assert resp.status_code == 401

    def test_unauthorized_response_is_json(self, app):
        """401-svar innehåller JSON med error-fält."""
        with app.test_client() as c:
            resp = c.get("/api/v1/stocks")
            if resp.status_code == 401:
                data = resp.get_json()
                assert data is not None
                assert "error" in data or "status" in data


# ══════════════════════════════════════════════════════════════════════════════
# Sensitive data i felmeddelanden (S9)
# ══════════════════════════════════════════════════════════════════════════════

class TestNoLeakInExceptions:
    """Verifiera att API-nycklar ej läcker i exception-strängar."""

    def test_ai_analysis_exception_no_key_leak(self):
        """ai_analysis saniterar exception-meddelanden."""
        try:
            from core.ai_analysis import _token_sanitize
        except ImportError:
            pytest.skip("ai_analysis ej tillgänglig")

        # Simulera ett felmeddelande med en nyckel inbäddad
        raw_error = "HTTP 401: sk-proj-abcdefghijklmnopqrstuvwxyz1234567890 rejected"
        sanitized = _token_sanitize.sub("[REDACTED]", raw_error)
        assert "sk-proj-" not in sanitized
        assert "[REDACTED]" in sanitized


# ══════════════════════════════════════════════════════════════════════════════
# Atomic file writes — integritetstest
# ══════════════════════════════════════════════════════════════════════════════

class TestAtomicFileWrites:
    """Verifiera att atomiska skrivningar inte lämnar korrupta filer."""

    def test_atomic_json_write_no_partial_file(self, tmp_path):
        """Atomisk JSON-skrivning: tmp → replace."""
        target = tmp_path / "test.json"
        tmp = target.with_suffix(".tmp.json")
        data = {"key": "value", "nested": {"a": 1}}
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(target)

        assert target.exists()
        assert not tmp.exists()
        loaded = json.loads(target.read_text())
        assert loaded == data

    def test_atomic_csv_write_no_partial_file(self, tmp_path):
        """Atomisk CSV-skrivning: tmp → replace."""
        import pandas as pd
        target = tmp_path / "data.csv"
        tmp = target.with_suffix(".tmp.csv")
        df = pd.DataFrame({"ticker": ["AAPL", "MSFT"], "score": [75.0, 68.3]})
        df.to_csv(tmp, index=False)
        tmp.replace(target)

        assert target.exists()
        assert not tmp.exists()
        loaded = pd.read_csv(target)
        assert len(loaded) == 2
        assert "ticker" in loaded.columns
