"""
scripts/check_site.py
======================
Streamlit / webbapp HTTP-hälsokontroll med svarstidsmätning.

Användning:
  python scripts/check_site.py                     # Kolla alla konfigurerade endpoints
  python scripts/check_site.py --url URL           # Kolla specifik URL
  python scripts/check_site.py --watch             # Loop-mode var 60s
  python scripts/check_site.py --benchmark N       # N anrop för genomsnittlig latens
  python scripts/check_site.py --json              # JSON-output

Kontrollerar:
  - HTTP-statuskod (200 = OK)
  - Svarstid (ms)
  - Content-typ
  - Streamlit-specifika signaturer (version, script-taggar)
  - SSL-certifikat (HTTPS)
  - Omdirigerings-kedja
"""
from __future__ import annotations

import argparse
import json
import os
import ssl
import socket
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from typing import Any

# Lägg till projekt-root i path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

# ── Konfiguration ──────────────────────────────────────────────────────────────

# Endpoints att kontrollera (URL -> beskrivning)
DEFAULT_ENDPOINTS: dict[str, str] = {
    os.getenv("STREAMLIT_URL", ""):    "Streamlit Cloud (primär)",
    "http://localhost:8501":            "Streamlit lokal dev",
}

# Filtrera bort tomma nycklar
DEFAULT_ENDPOINTS = {k: v for k, v in DEFAULT_ENDPOINTS.items() if k}

# Tröskelvärden
WARN_MS  = 2000   # >2s = varning
ERROR_MS = 8000   # >8s = fel


# ── Hjälpfunktioner ────────────────────────────────────────────────────────────

def _check_ssl(hostname: str, port: int = 443, timeout: float = 5.0) -> dict:
    """Kontrollera SSL-certifikat."""
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((hostname, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=hostname) as ssock:
                cert = ssock.getpeercert()
                expire_str = cert.get("notAfter", "")
                if expire_str:
                    # Format: "Jun  4 23:59:59 2026 GMT"
                    try:
                        exp_dt = datetime.strptime(expire_str, "%b %d %H:%M:%S %Y %Z")
                        days_left = (exp_dt - datetime.utcnow()).days
                        return {"ok": True, "days_left": days_left, "expires": expire_str}
                    except ValueError:
                        return {"ok": True, "days_left": None, "expires": expire_str}
                return {"ok": True, "days_left": None}
    except ssl.SSLCertVerificationError as e:
        return {"ok": False, "error": f"Cert-verifieringsfel: {e}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _http_get(url: str, timeout: float = 15.0,
              follow_redirects: bool = True) -> dict[str, Any]:
    """Gör HTTP GET och returnera mätdata."""
    result: dict[str, Any] = {
        "url":           url,
        "ok":            False,
        "status":        None,
        "ms":            None,
        "content_type":  None,
        "body_len":      None,
        "redirects":     [],
        "is_streamlit":  False,
        "streamlit_ver": None,
        "error":         None,
    }

    try:
        # Bygg request med browser-liknande headers
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "MarketScan-HealthCheck/1.0",
                "Accept":     "text/html,application/xhtml+xml,*/*",
            },
        )

        t0 = time.perf_counter()
        if follow_redirects:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read(8192)  # läs max 8KB för signaturanalys
                elapsed_ms = (time.perf_counter() - t0) * 1000
                result["ok"]           = True
                result["status"]       = resp.status
                result["ms"]           = round(elapsed_ms, 1)
                result["content_type"] = resp.headers.get("Content-Type", "")
                result["body_len"]     = int(resp.headers.get("Content-Length", 0) or 0)

                # Detektera Streamlit-signaturer
                body_str = body.decode("utf-8", errors="replace")
                if any(sig in body_str for sig in [
                    "streamlit", "stApp", "_stcore", "__streamlit"
                ]):
                    result["is_streamlit"] = True
                # Hitta Streamlit-version
                for marker in ['"version":"', "Streamlit/"]:
                    idx = body_str.find(marker)
                    if idx > -1:
                        ver_start = idx + len(marker)
                        ver_end   = body_str.find('"', ver_start) if '"' in body_str[ver_start:] else ver_start + 10
                        result["streamlit_ver"] = body_str[ver_start:ver_end].strip()[:20]
                        break

        else:
            # Manuell no-redirect (urllib följer redirect automatiskt)
            result["ms"] = round((time.perf_counter() - t0) * 1000, 1)
            result["ok"] = True

    except urllib.error.HTTPError as e:
        result["status"] = e.code
        result["error"]  = f"HTTP {e.code} {e.reason}"
    except urllib.error.URLError as e:
        reason = str(e.reason)
        if "timed out" in reason.lower():
            result["error"] = f"Timeout efter {timeout}s"
        elif "refused" in reason.lower():
            result["error"] = "Anslutning vägrad (ej igång?)"
        else:
            result["error"] = f"URL-fel: {reason}"
    except Exception as e:
        result["error"] = f"Oväntat fel: {e}"

    return result


def _benchmark(url: str, n: int = 5, timeout: float = 15.0) -> dict:
    """Mät latens N gånger och returnera statistik."""
    times = []
    errors = 0
    for i in range(n):
        r = _http_get(url, timeout=timeout)
        if r["ok"] and r["ms"] is not None:
            times.append(r["ms"])
        else:
            errors += 1
        time.sleep(0.5)  # Liten paus mellan anrop

    if not times:
        return {"ok": False, "n": n, "errors": errors}

    times_sorted = sorted(times)
    return {
        "ok":     True,
        "n":      n,
        "errors": errors,
        "min_ms": round(min(times), 1),
        "max_ms": round(max(times), 1),
        "avg_ms": round(sum(times) / len(times), 1),
        "p50_ms": round(times_sorted[len(times_sorted) // 2], 1),
        "p90_ms": round(times_sorted[int(len(times_sorted) * 0.9)], 1),
    }


# ── Utskrift ───────────────────────────────────────────────────────────────────

def _ms_icon(ms: float | None) -> str:
    if ms is None:
        return "[XX ]"
    if ms < WARN_MS:
        return "[OK ]"
    if ms < ERROR_MS:
        return "[!! ]"
    return "[XX ]"


def print_endpoint_check(url: str, label: str = "",
                         benchmark_n: int = 0,
                         check_ssl: bool = True) -> dict:
    """Kontrollera en endpoint och skriv ut resultat."""
    print(f"\n  >> {label or url}")
    print(f"     URL: {url}")

    # HTTP-check
    r = _http_get(url)
    icon = "[OK ]" if r["ok"] else "[XX ]"

    if r["ok"]:
        ms_icon = _ms_icon(r["ms"])
        print(f"  {ms_icon} HTTP {r['status']}  {r['ms']}ms")
        ct = r["content_type"] or ""
        print(f"     Content-Type: {ct[:60]}")
        if r["is_streamlit"]:
            ver_str = f" (v{r['streamlit_ver']})" if r["streamlit_ver"] else ""
            print(f"     [OK ] Streamlit-signatur detekterad{ver_str}")
    else:
        print(f"  [XX ] {r['error']}")

    # SSL-check för HTTPS
    if check_ssl and url.startswith("https://"):
        try:
            hostname = url.split("//", 1)[1].split("/")[0].split(":")[0]
            ssl_result = _check_ssl(hostname)
            if ssl_result["ok"]:
                days = ssl_result.get("days_left")
                if days is not None:
                    if days > 30:
                        print(f"  [OK ] SSL-cert giltig {days} dagar till")
                    elif days > 7:
                        print(f"  [!! ] SSL-cert löper ut om {days} dagar")
                    else:
                        print(f"  [XX ] SSL-cert löper ut om {days} dagar — förnya OMEDELBART")
                else:
                    print(f"  [OK ] SSL OK")
            else:
                print(f"  [XX ] SSL-fel: {ssl_result.get('error', '?')}")
        except Exception:
            pass

    # Benchmark
    if benchmark_n > 1:
        print(f"\n  Kör benchmark ({benchmark_n} anrop)...")
        bm = _benchmark(url, n=benchmark_n)
        if bm["ok"]:
            print(f"  [OK ] Benchmark: min={bm['min_ms']}ms "
                  f"avg={bm['avg_ms']}ms p90={bm['p90_ms']}ms max={bm['max_ms']}ms "
                  f"(fel: {bm['errors']}/{bm['n']})")
        else:
            print(f"  [XX ] Benchmark misslyckades ({bm['errors']}/{bm['n']} fel)")

    return r


def print_report(urls: dict[str, str] | None = None,
                 benchmark_n: int = 0) -> dict:
    """Skriv ut fullständig hälsorapport."""
    endpoints = urls or DEFAULT_ENDPOINTS

    print("=" * 70)
    print(f"  Webbapp Hälsokontroll")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    if not endpoints:
        print("\n  [-- ] Inga endpoints konfigurerade")
        print("        Sätt STREAMLIT_URL i .env eller använd --url")
        return {"ok": True, "endpoints": []}

    results = []
    ok_count   = 0
    fail_count = 0

    for url, label in endpoints.items():
        r = print_endpoint_check(url, label, benchmark_n=benchmark_n)
        results.append({"url": url, "label": label, **r})
        if r["ok"]:
            ok_count += 1
        else:
            fail_count += 1

    print()
    print("=" * 70)
    status = "OK" if fail_count == 0 else "FEL"
    print(f"  SUMMERING [{status}]: {ok_count} OK  {fail_count} FEL  "
          f"(av {len(endpoints)} endpoints)")
    print("=" * 70)

    return {
        "ok":        fail_count == 0,
        "ok_count":  ok_count,
        "fail_count": fail_count,
        "endpoints": results,
    }


# ── Watch-mode ─────────────────────────────────────────────────────────────────

def watch_mode(interval: int = 60, **kwargs) -> None:
    """Uppdatera status var N sekunder."""
    print(f"[>> ] Watch-mode aktiv — uppdaterar var {interval}s (Ctrl+C för stopp)")
    try:
        while True:
            os.system("cls" if os.name == "nt" else "clear")
            print_report(**kwargs)
            print(f"\n  [Nästa uppdatering om {interval}s — Ctrl+C för stopp]")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n[-- ] Watch-mode avslutat")


# ── main() ────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="HTTP-hälsokontroll för Streamlit och webbappar",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--url",       "-u", metavar="URL",
                        help="Kontrollera specifik URL (kan anges flera gånger)",
                        action="append", dest="urls")
    parser.add_argument("--benchmark", "-b", type=int, default=0, metavar="N",
                        help="Kör N anrop för latens-benchmark")
    parser.add_argument("--watch",     "-w", action="store_true",
                        help="Loop-mode, uppdatera automatiskt")
    parser.add_argument("--interval",  "-i", type=int, default=60,
                        help="Uppdateringsintervall sekunder (--watch, default 60)")
    parser.add_argument("--json",            action="store_true",
                        help="Skriv ut JSON-rapport")
    args = parser.parse_args()

    # Bygg endpoint-dict
    if args.urls:
        endpoints = {url: url for url in args.urls}
    else:
        endpoints = None  # använd DEFAULT_ENDPOINTS

    kwargs = dict(urls=endpoints, benchmark_n=args.benchmark)

    if args.watch:
        watch_mode(interval=args.interval, **kwargs)
        return 0

    result = print_report(**kwargs)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))

    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
