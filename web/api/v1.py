"""
web/api/v1.py
=============
MarketScan REST API v1 - alternative entry point.
All endpoints ar definierade i web/api/__init__.py.

Anvandning direkt:
    from web.api.v1 import api_v1
    app.register_blueprint(api_v1)

Anvandning via __init__:
    from web.api import api_v1
"""

from web.api import api_v1

__all__ = ["api_v1"]
