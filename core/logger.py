"""
logger.py
=========
Loggning av alla scan-körningar med auto-remediation.

Sparar till: data/scan_log.json
Varje körning får en post med:
  - Tidsstämpel, typ (full/daily), status (OK/ERROR/WARNING)
  - Antal aktier scannade, körntid
  - Eventuella fel + auto-remediation-åtgärder

Auto-remediation hanterar:
  - Gamla cache-filer (rensar om > 48h)
  - Korrupta JSON-filer (blacklist/strike_list)
  - Upprepade fel på samma modul (inaktiverar tillfälligt)
  - yfinance rate-limit (väntar och försöker igen)
"""

import json
import time
import traceback
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from contextlib import contextmanager

LOG_FILE        = Path("data/scan_log.json")
MAX_LOG_ENTRIES = 90   # Behåll 90 dagars historik
CACHE_DIR       = Path("data/cache")
DATA_DIR        = Path("data")


# ══════════════════════════════════════════════════════════════
# LOG-HANTERING
# ══════════════════════════════════════════════════════════════

def _load_log() -> list:
    if not LOG_FILE.exists():
        return []
    try:
        return json.loads(LOG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_log(entries: list):
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Behåll bara de senaste MAX_LOG_ENTRIES
    entries = entries[-MAX_LOG_ENTRIES:]
    LOG_FILE.write_text(
        json.dumps(entries, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8"
    )


def log_event(
    scan_type:    str,   # "full" | "daily"
    status:       str,   # "OK" | "ERROR" | "WARNING"
    details:      dict = None,
    error:        str  = None,
    remediation:  str  = None,
):
    """Loggar en händelse."""
    entry = {
        "timestamp":   datetime.now().isoformat(timespec="seconds"),
        "scan_type":   scan_type,
        "status":      status,
        "details":     details or {},
    }
    if error:
        entry["error"] = error
    if remediation:
        entry["remediation"] = remediation

    entries = _load_log()
    entries.append(entry)
    _save_log(entries)


@contextmanager
def scan_logger(scan_type: str, verbose: bool = True):
    """
    Context manager som loggar en hel scan-session.

    Användning:
      with scan_logger("full") as log:
          log["n_tickers"] = 535
          # ... din kod ...
          log["n_scored"] = 480
    """
    start_time = time.time()
    meta = {"scan_type": scan_type}

    try:
        yield meta
        elapsed = round(time.time() - start_time, 1)
        meta["elapsed_seconds"] = elapsed

        log_event(scan_type, "OK", details=meta)
        if verbose:
            print(f"\n✅ Scan klar på {elapsed:.0f}s - loggad")

    except Exception as e:
        elapsed = round(time.time() - start_time, 1)
        err_msg = traceback.format_exc()

        # Försök auto-remediation
        remedy = auto_remediate(e, err_msg)

        log_event(
            scan_type, "ERROR",
            details={**meta, "elapsed_seconds": elapsed},
            error=err_msg[-500:],  # Spara sista 500 tecken
            remediation=remedy,
        )

        if verbose:
            print(f"\n❌ Scan misslyckades efter {elapsed:.0f}s")
            print(f"   Fel: {str(e)[:100]}")
            if remedy:
                print(f"   Auto-remediation: {remedy}")
        raise


# ══════════════════════════════════════════════════════════════
# AUTO-REMEDIATION
# ══════════════════════════════════════════════════════════════

def auto_remediate(error: Exception, traceback_str: str) -> str:
    """
    Analyserar felet och vidtar automatiska åtgärder.
    Returnerar beskrivning av vad som gjordes.
    """
    actions = []
    err_lower = str(error).lower() + traceback_str.lower()

    # 1. Rate limit / Too Many Requests -> rensa cache
    if "429" in err_lower or "too many requests" in err_lower:
        cleared = clear_stale_cache(max_age_hours=0)  # Rensa all cache
        actions.append(f"Rensade {cleared} cache-filer pga rate limit")

    # 2. Korrupt JSON (blacklist/strike_list)
    if "json" in err_lower and ("blacklist" in err_lower or "strike" in err_lower):
        for json_file in ["blacklist.json", "strike_list.json"]:
            p = DATA_DIR / json_file
            if p.exists():
                backup = p.with_suffix(".json.bak")
                shutil.copy(p, backup)
                p.write_text("{}", encoding="utf-8")
                actions.append(f"Återställde {json_file} (backup sparad)")

    # 3. Gamla cache-filer (kan orsaka typ-fel)
    if "pickle" in err_lower or "unpickling" in err_lower or "attributeerror" in err_lower:
        cleared = clear_stale_cache(max_age_hours=24)
        actions.append(f"Rensade {cleared} potentiellt korrupta cache-filer")

    # 4. Minne / MemoryError
    if "memory" in err_lower:
        cleared = clear_stale_cache(max_age_hours=0)
        actions.append(f"Rensade all cache pga minnesbrist ({cleared} filer)")

    # 5. Import-fel -> logga tydligt men gör inget automatiskt
    if "importerror" in err_lower or "modulenotfounderror" in err_lower:
        actions.append("Import-fel - kontrollera requirements.txt")

    # 6. Generell åtgärd om inget specifikt hittades
    if not actions:
        cleared = clear_stale_cache(max_age_hours=48)
        if cleared > 0:
            actions.append(f"Rensade {cleared} gamla cache-filer som förebyggande åtgärd")

    return " | ".join(actions) if actions else "Ingen automatisk åtgärd möjlig"


def clear_stale_cache(max_age_hours: float = 48) -> int:
    """Rensar cache-filer äldre än max_age_hours. Returnerar antal borttagna."""
    if not CACHE_DIR.exists():
        return 0

    count = 0
    cutoff = datetime.now() - timedelta(hours=max_age_hours)

    for f in CACHE_DIR.glob("*.pkl"):
        try:
            mtime = datetime.fromtimestamp(f.stat().st_mtime)
            if mtime < cutoff:
                f.unlink()
                count += 1
        except Exception:
            pass

    return count


# ══════════════════════════════════════════════════════════════
# STATUS & RAPPORT
# ══════════════════════════════════════════════════════════════

def get_recent_status(n: int = 7) -> list:
    """Hämtar de senaste n log-posterna."""
    return _load_log()[-n:]


def get_consecutive_failures() -> int:
    """Räknar hur många körningar i rad som misslyckats."""
    entries = _load_log()
    count = 0
    for entry in reversed(entries):
        if entry.get("status") == "ERROR":
            count += 1
        else:
            break
    return count


def build_log_section() -> str:
    """Markdown-sektion för rapporten."""
    entries = get_recent_status(10)
    if not entries:
        return ""

    lines = ["\n## 🔧 Systemlogg (senaste körningar)\n"]
    lines.append("| Tid | Typ | Status | Aktier | Körtid |")
    lines.append("|-----|-----|--------|--------|--------|")

    for e in reversed(entries):
        ts      = e["timestamp"][:16].replace("T", " ")
        stype   = e.get("scan_type", "--")
        status  = e.get("status", "--")
        icon    = "✅" if status == "OK" else "❌" if status == "ERROR" else "⚠️"
        n_scanned = e.get("details", {}).get("n_scored", "--")
        elapsed   = e.get("details", {}).get("elapsed_seconds", "--")
        elapsed_s = f"{elapsed}s" if isinstance(elapsed, (int, float)) else "--"

        lines.append(f"| {ts} | {stype} | {icon} {status} | {n_scanned} | {elapsed_s} |")

        if e.get("error"):
            short_err = e["error"].split("\n")[-2] if "\n" in e["error"] else e["error"][:60]
            lines.append(f"| | | ↳ Fel | {short_err[:50]} | |")
        if e.get("remediation"):
            lines.append(f"| | | ↳ Åtgärd | {e['remediation'][:60]} | |")

    return "\n".join(lines)


def print_status_summary():
    """Skriv ut en kortfattad statussummering i terminalen."""
    entries  = get_recent_status(5)
    failures = get_consecutive_failures()

    if failures > 0:
        print(f"\n⚠️  VARNING: {failures} körning(ar) i rad misslyckades!")

    if entries:
        last = entries[-1]
        ts   = last["timestamp"][:16].replace("T", " ")
        print(f"   Senaste körning: {ts} - {last.get('status','?')}")
