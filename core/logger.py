"""
logger.py
=========
Strukturerad JSON-loggning med PipelineLogger-klass.
Loggnivåer: DEBUG, INFO, WARNING, ERROR, CRITICAL.
Varje loggpost innehåller: timestamp, level, module, function, message, duration_ms.

All logg sparas per pipeline-körning i data/logs/pipeline_{mode}_{date}.json
Auto-rotation: behåll 30 dagar, ta bort äldre.

Behåller bakåtkompatibilitet med den gamla scan_loggern (log_event, scan_logger).
"""

import json
import logging
import os
import sys
import time
import traceback
import shutil
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

# ── Sökvägar ───────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
LOG_FILE        = ROOT / "data" / "scan_log.json"
MAX_LOG_ENTRIES = 90
CACHE_DIR       = ROOT / "data" / "cache"
DATA_DIR        = ROOT / "data"
LOGS_DIR        = ROOT / "data" / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# ── In-memory ring buffer för recent logs ──────────────────────────────────
_RECENT_LOGS: list[dict] = []
_MAX_RECENT_LOGS = 1000


def _make_log_entry(
    level: str,
    module: str,
    func: str,
    message: str,
    duration_ms: Optional[float] = None,
    extra: Optional[dict] = None,
) -> dict:
    """Skapa en strukturerad loggpost."""
    entry = {
        "timestamp": datetime.now().isoformat(timespec="milliseconds"),
        "level": level,
        "module": module,
        "function": func,
        "message": message,
    }
    if duration_ms is not None:
        entry["duration_ms"] = round(duration_ms, 2)
    if extra:
        entry["extra"] = extra
    return entry


def _append_recent(entry: dict):
    """Lägg till i ringbufferten och trimma."""
    _RECENT_LOGS.append(entry)
    if len(_RECENT_LOGS) > _MAX_RECENT_LOGS:
        _RECENT_LOGS[:] = _RECENT_LOGS[-_MAX_RECENT_LOGS:]


# ══════════════════════════════════════════════════════════════════════════
# PipelineLogger — Central logger för pipeline-körningar
# ══════════════════════════════════════════════════════════════════════════

class PipelineLogger:
    """
    Logger för en pipeline-körning.
    Mäter stage-timingar, samlar fel och varningar, och loggar strukturerat.

    Användning:
        pl = PipelineLogger(mode="morning")
        pl.start_stage("fetch_data")
        # ... hämta data ...
        pl.end_stage()
        pl.log_error("AAPL", "TIMEOUT", "API timeout efter 7s")
        pl.log_warning("MSFT", "LOW_VOLUME", "Volym 20% under snitt")
        pl.info("Pipeline klar")
    """

    def __init__(self, mode: str = "morning", verbose: bool = True):
        self.mode = mode
        self.verbose = verbose
        self._start_time = time.time()
        self._stages: dict[str, float] = {}        # stage_name -> start_time
        self._stage_durations: dict[str, float] = {}  # stage_name -> total_ms
        self._stage_calls: dict[str, int] = {}       # stage_name -> count
        self._errors: list[dict] = []
        self._warnings: list[dict] = []
        self._logs: list[dict] = []
        self._date_str = datetime.now().strftime("%Y-%m-%d")

        self._log(logging.INFO, "__init__", f"PipelineLogger startad — mode={mode}")

    # ── Stage-timing ──────────────────────────────────────────────────────

    def start_stage(self, stage_name: str):
        """Börja mätning av en pipeline-stage."""
        self._stages[stage_name] = time.time()
        self._log(logging.DEBUG, "start_stage", f"Stage start: {stage_name}")

    def end_stage(self, stage_name: Optional[str] = None) -> float:
        """
        Avsluta mätning av en pipeline-stage.
        Om stage_name utelämnas, avslutas den senast startade.
        Returnerar duration i ms.
        """
        if stage_name is None:
            if not self._stages:
                return 0.0
            stage_name = list(self._stages.keys())[-1]

        start = self._stages.pop(stage_name, None)
        if start is None:
            return 0.0

        duration_ms = (time.time() - start) * 1000
        self._stage_durations[stage_name] = self._stage_durations.get(stage_name, 0) + duration_ms
        self._stage_calls[stage_name] = self._stage_calls.get(stage_name, 0) + 1

        self._log(logging.INFO, "end_stage",
                  f"Stage end: {stage_name}",
                  duration_ms=duration_ms)
        return duration_ms

    # ── Strukturerad loggning ─────────────────────────────────────────────

    def debug(self, message: str, **extra):
        self._log(logging.DEBUG, None, message, extra=extra or None)

    def info(self, message: str, **extra):
        self._log(logging.INFO, None, message, extra=extra or None)

    def warning(self, message: str, **extra):
        self._log(logging.WARNING, None, message, extra=extra or None)

    def error(self, message: str, **extra):
        self._log(logging.ERROR, None, message, extra=extra or None)

    def critical(self, message: str, **extra):
        self._log(logging.CRITICAL, None, message, extra=extra or None)

    def log_error(self, ticker: str, error_type: str, detail: str):
        """Strukturerad felloggning för en ticker."""
        entry = {
            "ticker": ticker,
            "error_type": error_type,
            "detail": detail,
            "timestamp": datetime.now().isoformat(),
        }
        self._errors.append(entry)
        self._log(logging.ERROR, "log_error",
                  f"Fel: {ticker} — {error_type}: {detail[:100]}")

    def log_warning(self, ticker: str, warning_type: str, detail: str):
        """Strukturerad varningsloggning för en ticker."""
        entry = {
            "ticker": ticker,
            "warning_type": warning_type,
            "detail": detail,
            "timestamp": datetime.now().isoformat(),
        }
        self._warnings.append(entry)
        self._log(logging.WARNING, "log_warning",
                  f"Varning: {ticker} — {warning_type}: {detail[:100]}")

    # ── Export ────────────────────────────────────────────────────────────

    def get_stage_timings(self) -> dict[str, float]:
        """Returnera dict med alla stage-timingar (ms)."""
        return dict(self._stage_durations)

    def get_error_summary(self) -> dict[str, Any]:
        """Sammanfattning av fel per pipeline-körning."""
        by_type: dict[str, int] = defaultdict(int)
        for e in self._errors:
            by_type[e["error_type"]] += 1
        return {
            "total_errors": len(self._errors),
            "total_warnings": len(self._warnings),
            "errors_by_type": dict(by_type),
            "errors": self._errors[-20:],
            "warnings": self._warnings[-20:],
        }

    def get_recent_logs(self, n: int = 100) -> list[dict]:
        """Returnera de senaste N loggposterna för denna pipeline-körning."""
        return self._logs[-n:]

    def get_elapsed(self) -> float:
        """Returnera total körtid i sekunder."""
        return time.time() - self._start_time

    def save(self):
        """Spara pipeline-logg till data/logs/pipeline_{mode}_{date}.json"""
        try:
            path = LOGS_DIR / f"pipeline_{self.mode}_{self._date_str}.json"
            data = {
                "mode": self.mode,
                "date": self._date_str,
                "elapsed_seconds": round(self.get_elapsed(), 2),
                "stage_timings": self._stage_durations,
                "stage_calls": self._stage_calls,
                "total_errors": len(self._errors),
                "total_warnings": len(self._warnings),
                "errors": self._errors[-50],
                "warnings": self._warnings[-50],
                "logs": self._logs[-200],
                "saved_at": datetime.now().isoformat(),
            }
            path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
        except Exception:
            pass

    # ── Interna ───────────────────────────────────────────────────────────

    def _log(self, level: int, func_name: Optional[str], message: str,
             duration_ms: Optional[float] = None, extra: Optional[dict] = None):
        """Intern loggmetod — skapar en strukturerad post."""
        import traceback
        try:
            # Hämta anropande modul
            frame = traceback.extract_stack()[-3]
            module = Path(frame.filename).stem if frame.filename else "?"
            func = func_name or frame.name or "?"

            entry = _make_log_entry(
                level=logging.getLevelName(level),
                module=module,
                func=func,
                message=message,
                duration_ms=duration_ms,
                extra=extra,
            )

            self._logs.append(entry)
            _append_recent(entry)

            # Skriv ut om verbose eller ERROR+
            if self.verbose or level >= logging.WARNING:
                level_icon = {
                    "DEBUG": "🔍", "INFO": "ℹ", "WARNING": "⚠",
                    "ERROR": "❌", "CRITICAL": "🚨",
                }.get(entry["level"], "ℹ")
                dur_str = f" ({duration_ms:.0f}ms)" if duration_ms else ""
                print(f"  {level_icon} {entry['message']}{dur_str}")

        except Exception:
            pass  # Non-blocking — aldrig krascha i loggern


# ══════════════════════════════════════════════════════════════════════════
# GLOBAL FUNCTIONS (bakåtkompatibilitet)
# ══════════════════════════════════════════════════════════════════════════

# Global PipelineLogger-instans (används när man inte skapar en egen)
_global_pl: Optional[PipelineLogger] = None


def get_pipeline_logger(mode: str = "morning") -> PipelineLogger:
    """Hämta eller skapa global PipelineLogger."""
    global _global_pl
    if _global_pl is None or _global_pl.mode != mode:
        _global_pl = PipelineLogger(mode=mode, verbose=False)
    return _global_pl


def json_log(level: str, message: str, module: Optional[str] = None, **extra):
    """
    Logga en strukturerad JSON-post direkt (utan PipelineLogger).
    Används för enkel loggning utanför pipeline-kontext.
    """
    try:
        entry = _make_log_entry(
            level=level.upper(),
            module=module or "?",
            func="?",
            message=message,
            extra=extra or None,
        )
        _append_recent(entry)
        # Skriv ut
        if level.upper() in ("ERROR", "CRITICAL", "WARNING"):
            print(f"  {level.upper()}: {message}")
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════
# AUTO-REMEDIATION (bevarad från original)
# ══════════════════════════════════════════════════════════════════════════

def auto_remediate(error: Exception, traceback_str: str) -> str:
    """
    Analyserar felet och vidtar automatiska åtgärder.
    Returnerar beskrivning av vad som gjordes.
    """
    actions = []
    err_lower = str(error).lower() + traceback_str.lower()

    # 1. Rate limit / Too Many Requests -> rensa cache
    if "429" in err_lower or "too many requests" in err_lower:
        cleared = clear_stale_cache(max_age_hours=0)
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

    # 3. Gamla cache-filer
    if "pickle" in err_lower or "unpickling" in err_lower or "attributeerror" in err_lower:
        cleared = clear_stale_cache(max_age_hours=24)
        actions.append(f"Rensade {cleared} potentiellt korrupta cache-filer")

    # 4. Minne / MemoryError
    if "memory" in err_lower:
        cleared = clear_stale_cache(max_age_hours=0)
        actions.append(f"Rensade all cache pga minnesbrist ({cleared} filer)")

    # 5. Import-fel
    if "importerror" in err_lower or "modulenotfounderror" in err_lower:
        actions.append("Import-fel - kontrollera requirements.txt")

    # 6. Generell åtgärd
    if not actions:
        cleared = clear_stale_cache(max_age_hours=48)
        if cleared > 0:
            actions.append(f"Rensade {cleared} gamla cache-filer som förebyggande åtgärd")

    return " | ".join(actions) if actions else "Ingen automatisk åtgärd möjlig"


# ══════════════════════════════════════════════════════════════════════════
# LOG-HANTERING (bevarad från original)
# ══════════════════════════════════════════════════════════════════════════

def _load_log() -> list:
    if not LOG_FILE.exists():
        return []
    try:
        return json.loads(LOG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_log(entries: list):
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    entries = entries[-MAX_LOG_ENTRIES:]
    LOG_FILE.write_text(
        json.dumps(entries, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8"
    )


def log_event(
    scan_type: str,
    status: str,
    details: dict = None,
    error: str = None,
    remediation: str = None,
):
    """Loggar en händelse till scan_log.json."""
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

    # Logga även via PipelineLogger om aktiv
    try:
        pl = _global_pl
        if pl:
            level = "ERROR" if status == "ERROR" else "WARNING" if status == "WARNING" else "INFO"
            msg = f"Scan {scan_type}: {status}"
            if error:
                msg += f" — {error[:100]}"
            pl._log(getattr(logging, level, logging.INFO), "log_event", msg)
    except Exception:
        pass


@contextmanager
def scan_logger(scan_type: str, verbose: bool = True):
    """
    Context manager som loggar en hel scan-session.
    Bakåtkompatibel med original-implementationen.

    Användning:
      with scan_logger("full") as log:
          log["n_tickers"] = 535
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

        remedy = auto_remediate(e, err_msg)

        log_event(
            scan_type, "ERROR",
            details={**meta, "elapsed_seconds": elapsed},
            error=err_msg[-500:],
            remediation=remedy,
        )

        if verbose:
            print(f"\n❌ Scan misslyckades efter {elapsed:.0f}s")
            print(f"   Fel: {str(e)[:100]}")
            if remedy:
                print(f"   Auto-remediation: {remedy}")
        raise


# ══════════════════════════════════════════════════════════════════════════
# CACHE-HANTERING (bevarad från original)
# ══════════════════════════════════════════════════════════════════════════

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


# ══════════════════════════════════════════════════════════════════════════
# STATUS & RAPPORT (bevarad från original)
# ══════════════════════════════════════════════════════════════════════════

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


def get_recent_logs_global(n: int = 100) -> list[dict]:
    """Hämta de senaste N loggposterna från hela systemet (ring buffer)."""
    return _RECENT_LOGS[-n:]


# ══════════════════════════════════════════════════════════════════════════
# AUTO-ROTATION (körs en gång per dag)
# ══════════════════════════════════════════════════════════════════════════

def rotate_old_logs(max_days: int = 30):
    """
    Ta bort pipeline-loggfiler äldre än max_days.
    Anropas en gång per dag från pipeline eller cron.
    """
    try:
        if not LOGS_DIR.exists():
            return
        cutoff = datetime.now() - timedelta(days=max_days)
        removed = 0
        for f in LOGS_DIR.glob("pipeline_*.json"):
            try:
                mtime = datetime.fromtimestamp(f.stat().st_mtime)
                if mtime < cutoff:
                    f.unlink()
                    removed += 1
            except Exception:
                pass
        if removed:
            print(f"🧹 Raderade {removed} gamla loggfiler (> {max_days} dagar)")
    except Exception:
        pass
