"""
web/api/auth.py
===============
API Authentication for MarketScan REST API.
Hanterar API-nycklar, rate limiting och endpoint-skydd.

Funktioner:
  - generate_api_key(user): generera ny API-nyckel
  - validate_api_key(key): validera mot lagrade keys
  - rate_limit_by_key(key): rate limiting per API key
  - require_api_key: decorator for att skydda endpoints

Nycklar lagras hashade i data/api_keys.json.
"""

import functools
import hashlib
import json
import secrets
import time
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Optional

from flask import g, jsonify, request

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
API_KEYS_FILE = DATA_DIR / "api_keys.json"

# Rate limiting state (in-memory, resets vid omstart)
_rate_limit_store: dict[str, list] = {}
_rate_limit_lock = Lock()

DATA_DIR.mkdir(parents=True, exist_ok=True)


def _load_keys() -> list[dict]:
    """Ladda alla API-nycklar fran data/api_keys.json."""
    try:
        if API_KEYS_FILE.exists():
            return json.loads(API_KEYS_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []


def _save_keys(keys: list[dict]) -> bool:
    """Spara API-nycklar till data/api_keys.json."""
    try:
        API_KEYS_FILE.write_text(
            json.dumps(keys, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return True
    except Exception:
        return False


def _hash_key(key: str) -> str:
    """Hasha en API-nyckel med SHA-256."""
    return hashlib.sha256(key.encode()).hexdigest()


def generate_api_key(user: str, description: str = "") -> str:
    """Generera en ny API-nyckel for en anvandare.

    Args:
        user: Anvandarnamn som nyckeln tillhor.
        description: Beskrivning (t.ex. "CI/CD pipeline").

    Returns:
        Den genererade API-nyckeln (visas en gang).
    """
    raw_key = f"ms_{secrets.token_urlsafe(32)}"
    hashed = _hash_key(raw_key)

    keys = _load_keys()
    keys.append({
        "key_hash": hashed,
        "user": user,
        "description": description,
        "created": datetime.now().isoformat(),
        "last_used": None,
        "revoked": False,
        "rate_limit_max": 100,
        "rate_limit_window": 60,
    })
    _save_keys(keys)
    return raw_key


def validate_api_key(key: str) -> Optional[dict]:
    """Validera en API-nyckel.

    Args:
        key: API-nyckel att validera.

    Returns:
        Nyckeldata om giltig, None annars.
    """
    hashed = _hash_key(key)
    keys = _load_keys()

    for k in keys:
        if k["key_hash"] == hashed:
            if k.get("revoked", False):
                return None
            # Uppdatera last_used
            k["last_used"] = datetime.now().isoformat()
            _save_keys(keys)
            return {
                "user": k["user"],
                "rate_limit_max": k.get("rate_limit_max", 100),
                "rate_limit_window": k.get("rate_limit_window", 60),
            }
    return None


def revoke_api_key(key_hash: str) -> bool:
    """Aterkalla en API-nyckel (mark as revoked).

    Args:
        key_hash: Hash av nyckeln att aterkalla.

    Returns:
        True om aterkallad, False om ej hittad.
    """
    keys = _load_keys()
    for k in keys:
        if k["key_hash"] == key_hash and not k.get("revoked", False):
            k["revoked"] = True
            k["revoked_at"] = datetime.now().isoformat()
            _save_keys(keys)
            return True
    return False


def list_api_keys(user: str = "") -> list[dict]:
    """Lista API-nycklar (exklusive raw-keys).

    Args:
        user: Filtrera pa anvandare (tom = alla).

    Returns:
        Lista av nyckeldata (utan raw-nyckel).
    """
    keys = _load_keys()
    result = []
    for k in keys:
        if user and k["user"] != user:
            continue
        result.append({
            "key_hash": k["key_hash"][:12] + "...",
            "user": k["user"],
            "description": k.get("description", ""),
            "created": k.get("created", ""),
            "last_used": k.get("last_used"),
            "revoked": k.get("revoked", False),
        })
    return result


def get_key_usage(key_hash: str) -> int:
    """Hamta antal anvandningar for en API-nyckel."""
    # Rattningar i minnet - tillhandahalls av rate_limit_by_key
    return 0


# ── Rate Limiting ────────────────────────────────────────────────────────────────

def rate_limit_by_key(key: str, max_requests: int = 100,
                      window_seconds: int = 60) -> tuple:
    """Rate limiting per API-nyckel.

    Args:
        key: API-nyckel.
        max_requests: Max antal anrop inom fönstret.
        window_seconds: Tidsfonster i sekunder.

    Returns:
        (allowed: bool, remaining: int, reset_time: float)
    """
    now = time.time()
    hashed = _hash_key(key)

    with _rate_limit_lock:
        if hashed not in _rate_limit_store:
            _rate_limit_store[hashed] = []

        # Rensa gamla entries
        _rate_limit_store[hashed] = [
            t for t in _rate_limit_store[hashed]
            if now - t < window_seconds
        ]

        current_count = len(_rate_limit_store[hashed])
        reset_time = now + window_seconds

        if current_count >= max_requests:
            return (False, 0, reset_time)

        _rate_limit_store[hashed].append(now)
        remaining = max_requests - current_count - 1
        return (True, remaining, reset_time)


def get_client_ip() -> str:
    """Hamta klientens IP-adress (hanterar proxies)."""
    if request.headers.get("X-Forwarded-For"):
        return request.headers["X-Forwarded-For"].split(",")[0].strip()
    return request.remote_addr or "unknown"


# ── Decorator ────────────────────────────────────────────────────────────────────

def require_api_key(f):
    """Decorator som kraver giltig API-nyckel.

    Nyckeln skickas i header: X-API-Key eller Authorization: Bearer <key>
    """

    @functools.wraps(f)
    def decorated(*args, **kwargs):
        key = request.headers.get("X-API-Key") or ""

        if not key:
            auth = request.headers.get("Authorization", "")
            if auth.startswith("Bearer "):
                key = auth[7:]

        if not key:
            return jsonify({
                "status": "error",
                "error": {"code": "UNAUTHORIZED", "message": "API-nyckel saknas"},
            }), 401

        key_data = validate_api_key(key)
        if not key_data:
            return jsonify({
                "status": "error",
                "error": {"code": "UNAUTHORIZED", "message": "Ogiltig eller aterkallad API-nyckel"},
            }), 401

        # Rate limiting
        allowed, remaining, reset_time = rate_limit_by_key(
            key,
            max_requests=key_data.get("rate_limit_max", 100),
            window_seconds=key_data.get("rate_limit_window", 60),
        )

        if not allowed:
            return jsonify({
                "status": "error",
                "error": {"code": "RATE_LIMITED", "message": "For manga anrop"},
            }), 429

        # Skicka rate limit headers (görs i after_request)
        g.api_user = key_data["user"]
        g.rate_limit_remaining = remaining
        g.rate_limit_reset = int(reset_time)
        g.rate_limit_limit = key_data.get("rate_limit_max", 100)

        return f(*args, **kwargs)

    return decorated
