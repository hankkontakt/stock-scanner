"""
web/api/__init__.py
===================
MarketScan REST API v1.
Initialiserar API-blueprinten med alla endpoints.

Anvandning:
    from web.api import api_v1
    app.register_blueprint(api_v1)
"""

import time
from datetime import datetime
from pathlib import Path

import pandas as pd
from flask import Blueprint, Response, jsonify, request

from core import config

# Skapa blueprint
api_v1 = Blueprint("api_v1", __name__, url_prefix="/api/v1")

# ── Autentisering ─────────────────────────────────────────────────────────────────
# Endpoints utan krav på API-nyckel
_PUBLIC_ENDPOINTS = {"api_v1.health", "api_v1.version"}

try:
    from web.api.auth import require_api_key, validate_api_key, rate_limit_by_key
    _AUTH_AVAILABLE = True
except ImportError:
    _AUTH_AVAILABLE = False
    require_api_key = lambda f: f  # noqa: E731 — passthrough om auth-modul saknas


@api_v1.before_request
def _check_auth():
    """Kräv API-nyckel på alla endpoints utom de publika.
    Stöder: X-API-Key header eller Authorization: Bearer <key>
    """
    if not _AUTH_AVAILABLE:
        return  # Auth-modul saknas — passthrough (dev-läge)
    if request.endpoint in _PUBLIC_ENDPOINTS:
        return  # Publika endpoints behöver ingen nyckel

    key = request.headers.get("X-API-Key") or ""
    if not key:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            key = auth[7:]

    if not key:
        return jsonify({
            "status": "error",
            "error": {
                "code": "UNAUTHORIZED",
                "message": "API-nyckel saknas. Skicka X-API-Key-header eller Authorization: Bearer <key>.",
            },
        }), 401

    key_data = validate_api_key(key)
    if not key_data:
        return jsonify({
            "status": "error",
            "error": {"code": "UNAUTHORIZED", "message": "Ogiltig eller återkallad API-nyckel."},
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
            "error": {"code": "RATE_LIMITED", "message": "För många anrop. Försök igen om en stund."},
        }), 429


@api_v1.after_request
def _add_rate_limit_headers(response):
    """Lägg till standard rate-limit-headers på alla svar."""
    from flask import g
    if hasattr(g, "rate_limit_remaining"):
        response.headers["X-RateLimit-Limit"]     = str(g.rate_limit_limit)
        response.headers["X-RateLimit-Remaining"] = str(g.rate_limit_remaining)
        response.headers["X-RateLimit-Reset"]     = str(g.rate_limit_reset)
    return response


def _json_ok(data, took_ms: float = 0) -> dict:
    """Standard JSON-svar for lyckade anrop."""
    return {
        "status": "ok",
        "data": data,
        "meta": {
            "took_ms": round(took_ms, 2),
            "source": "cache",
            "timestamp": datetime.now().isoformat(),
        },
    }


def _json_error(code: str, message: str, status: int = 404) -> tuple:
    """Standard JSON-svar for fel."""
    return jsonify({
        "status": "error",
        "error": {"code": code, "message": message},
    }), status


def _read_scored_file() -> pd.DataFrame:
    """Las senaste scored_universe-filen. Returnerar tom DataFrame vid fel."""
    report_dir = Path("reports")
    files = sorted(report_dir.glob("scored_universe_*.csv"), reverse=True)
    if not files:
        return pd.DataFrame()
    try:
        df = pd.read_csv(files[0], low_memory=False)
        df.columns = df.columns.str.strip()
        return df
    except Exception:
        return pd.DataFrame()


def _read_scored_files() -> dict[str, pd.DataFrame]:
    """Las alla scored_universe-filer. Returnerar {datum: DataFrame}."""
    result = {}
    for f in sorted(Path("reports").glob("scored_universe_*.csv"), reverse=True):
        try:
            d = f.stem.replace("scored_universe_", "")
            df = pd.read_csv(f, low_memory=False)
            df.columns = df.columns.str.strip()
            result[d] = df
        except Exception:
            pass
    return result


def _get_portfolio_df():
    """Las holdings.csv."""
    try:
        from portfolio.portfolio import load_holdings
        return load_holdings()
    except Exception:
        try:
            df = pd.read_csv(config.HOLDINGS_FILE)
            df.columns = df.columns.str.lower().str.strip()
            return df
        except Exception:
            return pd.DataFrame()


# ── Health ────────────────────────────────────────────────────────────────────────

@api_v1.route("/health", methods=["GET"])
def health():
    """System health check.

    Delegeerar till core.monitoring om tillgangligt, annars grundlaggande check.
    """
    start = time.time()
    status = "ok"
    checks = {"app": "running"}

    try:
        from core.monitoring import system_health_check
        health_data = system_health_check()
        if isinstance(health_data, dict):
            checks.update(health_data)
            if health_data.get("status") == "degraded":
                status = "degraded"
    except ImportError:
        # Grundlaggande check utan monitoring-modul
        checks["scored_files"] = len(list(Path("reports").glob("scored_universe_*.csv")))

    took_ms = (time.time() - start) * 1000
    return jsonify({
        "status": status,
        "data": checks,
        "meta": {"took_ms": round(took_ms, 2), "source": "live", "timestamp": datetime.now().isoformat()},
    })


@api_v1.route("/version", methods=["GET"])
def version():
    """API version info."""
    return jsonify(_json_ok({
        "api_version": "1.0.0",
        "app_version": "1.0.0",
        "app_name": "MarketScan",
        "docs_url": "/api/v1/docs",
        "swagger_json": "/api/v1/swagger.json",
    }))


# ── Stocks ───────────────────────────────────────────────────────────────────────

@api_v1.route("/stocks/<ticker>", methods=["GET"])
def stock_detail(ticker: str):
    """Fullstandig stock data (scoring, metrics, news).

    Hämta all tillgänglig information om en aktie inklusive scoring,
    nyckeltal, nyheter och AI-analys.
    """
    start = time.time()
    ticker = ticker.upper()

    df = _read_scored_file()
    if df.empty:
        return _json_error("NO_DATA", "Ingen scored data tillganglig. Kor en scan forst.")

    stock = df[df["ticker"] == ticker]
    if stock.empty:
        return _json_error("NOT_FOUND", f"Aktien {ticker} hittades inte i senaste scan")

    row = stock.iloc[0].to_dict()
    # Rensa NaN-varden
    data = {k: (v if pd.notna(v) else None) for k, v in row.items()}

    # Lagg till live-pris
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        info = t.fast_info
        data["live_price"] = round(float(info.last_price), 2) if info.last_price else None
        data["currency"] = info.currency or "USD"
    except Exception:
        data["live_price"] = data.get("price")
        data["currency"] = "USD"

    took_ms = (time.time() - start) * 1000
    return jsonify(_json_ok(data, took_ms))


@api_v1.route("/stocks/<ticker>/score", methods=["GET"])
def stock_score(ticker: str):
    """Endast scoring for en aktie."""
    start = time.time()
    ticker = ticker.upper()

    df = _read_scored_file()
    if df.empty:
        return _json_error("NO_DATA", "Ingen scored data tillganglig")

    stock = df[df["ticker"] == ticker]
    if stock.empty:
        return _json_error("NOT_FOUND", f"Aktien {ticker} hittades inte")

    score_cols = [c for c in df.columns if c.startswith("score_") or c in (
        "ticker", "name", "sector", "rank", "score_total", "conviction")]
    data = {c: (float(stock.iloc[0][c]) if pd.notna(stock.iloc[0][c]) else None)
            for c in score_cols if c in df.columns}

    took_ms = (time.time() - start) * 1000
    return jsonify(_json_ok(data, took_ms))


@api_v1.route("/stocks/<ticker>/news", methods=["GET"])
def stock_news(ticker: str):
    """Nyheter for en aktie."""
    start = time.time()
    ticker = ticker.upper()

    try:
        from core.news_fetcher import fetch_company_news
        news = fetch_company_news(ticker)
        news_list = news.to_dict("records") if isinstance(news, pd.DataFrame) else news
        took_ms = (time.time() - start) * 1000
        return jsonify(_json_ok(news_list or [], took_ms))
    except ImportError:
        return _json_error("MODULE_UNAVAILABLE", "Nyhetsmodul ej tillganglig", 503)
    except Exception as e:
        return _json_error("FETCH_ERROR", f"Kunde inte hamta nyheter: {e}", 502)


@api_v1.route("/stocks/<ticker>/price", methods=["GET"])
def stock_price(ticker: str):
    """Prisdata for en aktie."""
    start = time.time()
    ticker = ticker.upper()

    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        hist = t.history(period="1y", auto_adjust=True)

        if hist.empty:
            return _json_error("NO_DATA", f"Inga prisfyndna for {ticker}")

        # Beholl endast datum och stangningskurs
        price_data = []
        for idx, row in hist.iterrows():
            price_data.append({
                "date": idx.strftime("%Y-%m-%d"),
                "open": round(float(row["Open"]), 2),
                "high": round(float(row["High"]), 2),
                "low": round(float(row["Low"]), 2),
                "close": round(float(row["Close"]), 2),
                "volume": int(row["Volume"]),
            })

        info = t.fast_info
        meta = {
            "currency": info.currency or "USD",
            "last_price": round(float(info.last_price), 2) if info.last_price else None,
            "change_pct": round(float(info.last_price or 0) / float(hist["Close"].iloc[-2]) - 1, 4) * 100 if len(hist) >= 2 else 0,
        }

        took_ms = (time.time() - start) * 1000
        return jsonify(_json_ok({"prices": price_data, "meta": meta}, took_ms))

    except Exception as e:
        return _json_error("FETCH_ERROR", f"Kunde inte hamta prisdata: {e}", 502)


@api_v1.route("/stocks/<ticker>/options", methods=["GET"])
def stock_options(ticker: str):
    """Optionskedja for en aktie (om options-modul finns)."""
    start = time.time()
    ticker = ticker.upper()

    try:
        from core.options_chain import OptionsChain
        chain = OptionsChain.fetch_chain(ticker)
        if chain is None or (isinstance(chain, pd.DataFrame) and chain.empty):
            return _json_error("NO_DATA", f"Inga options funna for {ticker}")

        data = chain.to_dict("records") if isinstance(chain, pd.DataFrame) else chain
        took_ms = (time.time() - start) * 1000
        return jsonify(_json_ok(data, took_ms))
    except ImportError:
        return _json_error("MODULE_UNAVAILABLE", "Optionsmodul ej tillganglig", 503)
    except Exception as e:
        return _json_error("FETCH_ERROR", f"Kunde inte hamta options: {e}", 502)


# ── Scans ────────────────────────────────────────────────────────────────────────

@api_v1.route("/scans/latest", methods=["GET"])
def scans_latest():
    """Senaste scan-resultat.

    Query-parametrar:
      mode: "weekly" (standard) eller "smallcap"
    """
    start = time.time()
    mode = request.args.get("mode", "weekly")

    if mode == "smallcap":
        pattern = "smallcap_scored_*.csv"
    else:
        pattern = "scored_universe_*.csv"

    files = sorted(Path("reports").glob(pattern), reverse=True)
    if not files:
        return _json_error("NO_DATA", "Inga scan-resultat funna")

    try:
        df = pd.read_csv(files[0], low_memory=False)
        data = df.head(50).to_dict("records")
        # Rensa NaN
        for row in data:
            for k, v in row.items():
                if isinstance(v, float) and pd.isna(v):
                    row[k] = None

        took_ms = (time.time() - start) * 1000
        return jsonify(_json_ok({
            "mode": mode,
            "date": files[0].stem.replace(pattern.replace("*.csv", ""), ""),
            "total": len(df),
            "results": data,
        }, took_ms))
    except Exception as e:
        return _json_error("READ_ERROR", f"Kunde inte lasa scan-data: {e}", 500)


@api_v1.route("/scans/history", methods=["GET"])
def scans_history():
    """Scan-historik.

    Query-parametrar:
      days: antal dagar bakat (standard 30)
      mode: "weekly" eller "smallcap"
    """
    start = time.time()
    try:
        days = int(request.args.get("days", 30))
    except ValueError:
        days = 30
    mode = request.args.get("mode", "weekly")

    if mode == "smallcap":
        pattern = "smallcap_scored_*.csv"
    else:
        pattern = "scored_universe_*.csv"

    files = sorted(Path("reports").glob(pattern), reverse=True)
    if not files:
        return _json_error("NO_DATA", "Ingen scan-historik funnen")

    history = []
    for f in files[:days]:
        try:
            df = pd.read_csv(f, low_memory=False)
            date_str = f.stem.replace(pattern.replace("*.csv", ""), "")
            total = len(df)
            top_score = float(df["score_total"].max()) if "score_total" in df.columns else 0
            avg_score = float(df["score_total"].mean()) if "score_total" in df.columns else 0
            history.append({
                "date": date_str,
                "total_stocks": total,
                "top_score": round(top_score, 1),
                "avg_score": round(avg_score, 1),
            })
        except Exception:
            pass

    took_ms = (time.time() - start) * 1000
    return jsonify(_json_ok(history, took_ms))


# ── Portfolio ─────────────────────────────────────────────────────────────────────

@api_v1.route("/portfolio", methods=["GET"])
def portfolio():
    """Portfoljdata med live-priser och P&L."""
    start = time.time()
    try:
        from web.app import load_holdings, get_live_price
        holdings = load_holdings()

        enriched = []
        total_value = 0
        total_cost = 0

        for h in holdings:
            live = get_live_price(h["ticker"])
            price = live["price"]
            shares = h["shares"]
            cost = h.get("cost_basis")

            market_value = round(shares * price, 2) if price else None
            cost_total = round(shares * cost, 2) if cost else None
            pnl = round(market_value - cost_total, 2) if (market_value and cost_total) else None
            pnl_pct = round(pnl / cost_total * 100, 2) if (pnl is not None and cost_total) else None

            if market_value:
                total_value += market_value
            if cost_total:
                total_cost += cost_total

            enriched.append({
                "ticker": h["ticker"],
                "name": live["name"],
                "shares": shares,
                "cost_basis": cost,
                "currency": live["currency"],
                "current_price": price,
                "market_value": market_value,
                "pnl": pnl,
                "pnl_pct": pnl_pct,
            })

        took_ms = (time.time() - start) * 1000
        return jsonify(_json_ok({
            "holdings": enriched,
            "total_value": round(total_value, 2),
            "total_cost": round(total_cost, 2),
            "total_pnl": round(total_value - total_cost, 2) if (total_value and total_cost) else None,
        }, took_ms))
    except Exception as e:
        return _json_error("FETCH_ERROR", f"Kunde inte hamta portfoljdata: {e}", 500)


@api_v1.route("/portfolio/holdings", methods=["GET"])
def portfolio_holdings():
    """Enbart innehav (utan live-priser)."""
    start = time.time()
    try:
        from web.app import load_holdings
        holdings = load_holdings()
        took_ms = (time.time() - start) * 1000
        return jsonify(_json_ok(holdings, took_ms))
    except Exception as e:
        return _json_error("FETCH_ERROR", f"Kunde inte hamta innehav: {e}", 500)


@api_v1.route("/portfolio/analysis", methods=["GET"])
def portfolio_analysis():
    """Portfoljanalys (korrelation, koncentration, diversifiering)."""
    start = time.time()
    try:
        from portfolio.portfolio_analysis import full_analysis
        df = _get_portfolio_df()
        if df.empty:
            return _json_error("NO_DATA", "Inga innehav i portfoljen")

        analysis = full_analysis(df)
        took_ms = (time.time() - start) * 1000
        return jsonify(_json_ok(analysis, took_ms))
    except ImportError:
        return _json_error("MODULE_UNAVAILABLE", "Analysmodul ej tillganglig", 503)
    except Exception as e:
        return _json_error("ANALYSIS_ERROR", f"Kunde inte analysera portfolj: {e}", 500)


# ── Alerts ───────────────────────────────────────────────────────────────────────

@api_v1.route("/alerts", methods=["GET"])
def alerts():
    """Aktiva larm."""
    start = time.time()
    try:
        from core.alerts import load_alerts
        alerts_data = load_alerts()
        alerts_list = alerts_data.to_dict("records") if isinstance(alerts_data, pd.DataFrame) else alerts_data
        took_ms = (time.time() - start) * 1000
        return jsonify(_json_ok(alerts_list or [], took_ms))
    except ImportError:
        return _json_error("MODULE_UNAVAILABLE", "Larmmodul ej tillganglig", 503)
    except Exception as e:
        return _json_error("FETCH_ERROR", f"Kunde inte hamta larm: {e}", 500)


# ── Sectors ──────────────────────────────────────────────────────────────────────

@api_v1.route("/sectors", methods=["GET"])
def sectors():
    """Sektor-data."""
    start = time.time()
    try:
        from core.sectors import get_sector_data
        df = _read_scored_file()
        if df.empty:
            return _json_error("NO_DATA", "Ingen scored data")

        sector_data = get_sector_data(df)
        took_ms = (time.time() - start) * 1000
        return jsonify(_json_ok(sector_data, took_ms))
    except ImportError:
        return _json_error("MODULE_UNAVAILABLE", "Sektormodul ej tillganglig", 503)
    except Exception as e:
        return _json_error("FETCH_ERROR", f"Kunde inte hamta sektor-data: {e}", 500)


# ── Markets ──────────────────────────────────────────────────────────────────────

@api_v1.route("/markets/global", methods=["GET"])
def markets_global():
    """Globala index."""
    start = time.time()
    try:
        from core.global_markets import fetch_global_indices
        indices = fetch_global_indices()
        took_ms = (time.time() - start) * 1000
        return jsonify(_json_ok(indices, took_ms))
    except ImportError:
        return _json_error("MODULE_UNAVAILABLE", "Globala marknader ej tillgangligt", 503)
    except Exception as e:
        return _json_error("FETCH_ERROR", f"Kunde inte hamta index: {e}", 500)


@api_v1.route("/markets/macro", methods=["GET"])
def markets_macro():
    """Makro-regim."""
    start = time.time()
    try:
        from core.macro_regime import get_regime
        regime = get_regime()
        took_ms = (time.time() - start) * 1000
        return jsonify(_json_ok(regime, took_ms))
    except ImportError:
        return _json_error("MODULE_UNAVAILABLE", "Makromodul ej tillganglig", 503)
    except Exception as e:
        return _json_error("FETCH_ERROR", f"Kunde inte hamta makrodata: {e}", 500)


# ── Search ────────────────────────────────────────────────────────────────────────

@api_v1.route("/search", methods=["GET"])
def search():
    """Ticker-sokning via yfinance Search."""
    start = time.time()
    q = request.args.get("q", "").strip()
    if len(q) < 1:
        return _json_error("INVALID_INPUT", "Sokparameter 'q' kravs (minst 1 tecken)", 400)

    try:
        import yfinance as yf
        results = yf.Search(q, max_results=10).quotes
        filtered = []
        for r in results:
            if r.get("quoteType") in ("EQUITY", "ETF"):
                filtered.append({
                    "ticker": r.get("symbol", ""),
                    "name": r.get("shortname") or r.get("longname") or "",
                    "exchange": r.get("exchange") or r.get("fullExchangeName") or "",
                    "type": r.get("quoteType", ""),
                })

        took_ms = (time.time() - start) * 1000
        return jsonify(_json_ok(filtered, took_ms))
    except Exception as e:
        return _json_error("SEARCH_ERROR", f"Sokning misslyckades: {e}", 502)
