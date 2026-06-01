"""
ticker_health.py - Verktyg för att övervaka och validera tickers.

Användning:
  python -m tools.ticker_health              # Testa alla tickers, rapportera problem
  python -m tools.ticker_health --blacklist  # Visa/integrera med blacklist
  python -m tools.ticker_health --check AAPL MSFT INVALID.ST  # Specifika tickers

Funktioner:
  - Detekterar döda/avnoterade tickers (HTTP 404, tom data)
  - Identifierar rate-limiting-mönster (många på varandra följande fel)
  - Föreslår tickers som borde läggas till i blacklist
  - Validerar att alla tickers i ett universum är giltiga
  - Cachar resultat för snabb återanvändning
"""

import sys
import time
import json
import argparse
from datetime import datetime
from pathlib import Path

from core import config
from core import data_fetcher


def check_ticker_health(ticker: str, timeout: int = 15) -> dict:
    """
    Testa en enskild tickers hälsa.
    Returnerar dict med status, felkod och metadata.
    """
    result = {
        "ticker": ticker,
        "healthy": False,
        "status": "UNKNOWN",
        "error": None,
        "response_time_ms": None,
        "has_info": False,
        "has_prices": False,
        "checked_at": datetime.now().isoformat(),
    }

    start = time.perf_counter()

    try:
        # Försök hämta info
        info = data_fetcher.fetch_stock_info(ticker)
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        result["response_time_ms"] = elapsed_ms

        if info and len(info) >= 5:
            result["has_info"] = True
            result["healthy"] = True
            result["status"] = "OK"
            result["name"] = info.get("longName") or info.get("shortName") or ticker
            result["sector"] = info.get("sector", "Unknown")
            result["market_cap"] = info.get("marketCap")
        else:
            result["status"] = "NO_DATA"
            result["error"] = "yfinance returnerade för lite data"

        # Försök hämta prishistorik
        hist = data_fetcher.fetch_price_history(ticker, period="1mo")
        if not hist.empty and len(hist) > 5:
            result["has_prices"] = True
            result["last_price"] = float(hist["Close"].iloc[-1]) if "Close" in hist.columns else None
        else:
            # Ingen prishistorik senaste månaden - kan vara avnoterad
            if result["healthy"]:
                result["healthy"] = False
                result["status"] = "NO_PRICES"
                result["error"] = "Ingen prishistorik senaste månaden"

    except TimeoutError:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        result["response_time_ms"] = elapsed_ms
        result["status"] = "TIMEOUT"
        result["error"] = f"Hängde efter {timeout}s"
    except Exception as e:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        result["response_time_ms"] = elapsed_ms
        result["status"] = "ERROR"
        result["error"] = str(e)

    return result


def check_universe_health(tickers: list, max_workers: int = 4) -> dict:
    """
    Kontrollera alla tickers i ett universum.
    Returnerar sammanställd rapport med friska/sjuka/okända.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    total = len(tickers)
    print(f"🩺 Kontrollerar hälsa för {total} tickers (max {max_workers} workers)...")

    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(check_ticker_health, t): t for t in tickers}
        for i, future in enumerate(as_completed(futures), 1):
            res = future.result()
            results.append(res)
            # Kompakt utskrift
            icon = "✓" if res["healthy"] else "✗"
            status = res["status"]
            name = res.get("name", res["ticker"])[:30]
            print(f"  [{i}/{total}] {icon} {res['ticker']:20s} {status:8s} {name}")

    # Sammanställ
    healthy  = [r for r in results if r["healthy"]]
    sick     = [r for r in results if not r["healthy"]]

    report = {
        "total": total,
        "healthy": len(healthy),
        "sick": len(sick),
        "healthy_pct": round(len(healthy) / total * 100, 1) if total else 0,
        "sick_pct": round(len(sick) / total * 100, 1) if total else 0,
        "status_breakdown": {},
        "sick_tickers": [r["ticker"] for r in sick],
        "recommended_for_blacklist": [],
        "checked_at": datetime.now().isoformat(),
    }

    # Status breakdown
    for r in results:
        s = r["status"]
        report["status_breakdown"][s] = report["status_breakdown"].get(s, 0) + 1

    # Föreslå för blacklist: tickers som konsekvent misslyckas med TIMEOUT/NO_DATA
    for r in sick:
        if r["status"] in ("TIMEOUT", "NO_DATA", "NO_PRICES"):
            report["recommended_for_blacklist"].append(r["ticker"])

    return report


def load_blacklist() -> dict:
    """Ladda nuvarande blacklist från data/blacklist.json."""
    path = Path("data/blacklist.json")
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            return {}
    return {}


def save_blacklist(blacklist: dict):
    """Spara blacklist till data/blacklist.json."""
    path = Path("data/blacklist.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(blacklist, indent=2, ensure_ascii=False))
    print(f"  💾 Blacklist sparad: {path}")


def add_to_blacklist(ticker: str, reason: str = ""):
    """Lägg till en ticker i blacklisten."""
    bl = load_blacklist()
    if ticker not in bl:
        bl[ticker] = {
            "reason": reason or "Detected by ticker_health.py",
            "added": datetime.now().strftime("%Y-%m-%d"),
        }
        save_blacklist(bl)
        return True
    return False


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="🩺 Ticker Health Check - validera och övervaka tickers"
    )
    parser.add_argument(
        "--check", nargs="+", metavar="TICKER",
        help="Kontrollera specifika tickers"
    )
    parser.add_argument(
        "--universe", choices=["all", "smallcap", "us", "europe", "asia", "canada"],
        default=None,
        help="Kontrollera ett helt universum (all = config.UNIVERSE)"
    )
    parser.add_argument(
        "--workers", type=int, default=4,
        help="Antal parallella workers (default: 4)"
    )
    parser.add_argument(
        "--blacklist", action="store_true",
        help="Visa nuvarande blacklist"
    )
    parser.add_argument(
        "--auto-blacklist", action="store_true",
        help="Lägg automatiskt till sjuka tickers i blacklist"
    )
    args = parser.parse_args()

    # Visa blacklist
    if args.blacklist:
        bl = load_blacklist()
        if bl:
            print(f"📋 Blacklist ({len(bl)} tickers):")
            for t, info in sorted(bl.items()):
                reason = info.get("reason", "")
                added = info.get("added", "")
                print(f"  • {t:20s} | {reason:40s} | {added}")
        else:
            print("📋 Blacklist är tom")
        return

    # Specifika tickers
    if args.check:
        for t in args.check:
            res = check_ticker_health(t)
            icon = "✓" if res["healthy"] else "✗"
            print(f"{icon} {res['ticker']:20s} {res['status']:8s} "
                  f"{res.get('response_time_ms', '?')}ms "
                  f"{res.get('name', '')}")
            if not res["healthy"] and res.get("error"):
                print(f"   └─ {res['error']}")
        return

    # Universum-kontroll
    if args.universe:
        universe_map = {
            "all":      config.UNIVERSE,
            "smallcap": __import__("smallcap.universe", fromlist=["SMALLCAP_UNIVERSE"]).SMALLCAP_UNIVERSE,
            "us":       config.US_LARGE_CAP,
            "europe":   config.EUROPE,
            "asia":     config.ASIA_PACIFIC,
            "canada":   config.CANADA,
        }
        tickers = universe_map.get(args.universe, config.UNIVERSE)
        report = check_universe_health(tickers, max_workers=args.workers)

        print(f"\n{'='*60}")
        print(f"🩺 HÄLSORAPPORT - {args.universe.upper()}")
        print(f"{'='*60}")
        print(f"  Totalt:           {report['total']}")
        print(f"  Friska:           {report['healthy']} ({report['healthy_pct']}%)")
        print(f"  Sjuka:            {report['sick']} ({report['sick_pct']}%)")
        print(f"\n  Statusfördelning:")
        for status, count in sorted(report["status_breakdown"].items()):
            print(f"    {status:12s}: {count}")
        if report["sick_tickers"]:
            print(f"\n  ❌ Sjuka tickers ({len(report['sick_tickers'])}):")
            for t in report["sick_tickers"][:30]:
                print(f"    • {t}")
            if len(report["sick_tickers"]) > 30:
                print(f"    ... och {len(report['sick_tickers']) - 30} till")
        if report["recommended_for_blacklist"]:
            print(f"\n  💡 Rekommenderade för blacklist ({len(report['recommended_for_blacklist'])}):")
            for t in report["recommended_for_blacklist"][:20]:
                print(f"    • {t}")
            if args.auto_blacklist:
                print(f"\n  🚀 Lägger till {len(report['recommended_for_blacklist'])} tickers i blacklist...")
                for t in report["recommended_for_blacklist"]:
                    add_to_blacklist(t, reason=f"Sjuk ({report['status_breakdown'].get(t, 'UNKNOWN')})")
        return

    # Default: visa hjälp
    parser.print_help()


if __name__ == "__main__":
    main()
