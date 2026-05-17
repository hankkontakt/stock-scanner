"""
Makrokalender — hårdkodade centralbanksbeslut och makrohändelser 2025–2026.

Källor:
  Fed FOMC:    https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
  ECB:         https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html
  Riksbanken:  https://www.riksbank.se/sv/penningpolitik/penningpolitiska-beslut/beslutsdatum/
  Norges Bank: https://www.norges-bank.no/pengepolitikk/rentemoter/
  BoE:         https://www.bankofengland.co.uk/monetary-policy/the-interest-rate-decisions
"""
import datetime

MACRO_EVENTS: list[dict] = [
    # ── Fed FOMC 2025 ──────────────────────────────────────────────────────────
    {"date": "2025-01-29", "event": "Fed FOMC-beslut",        "body": "Fed",        "flag": "🇺🇸"},
    {"date": "2025-03-19", "event": "Fed FOMC-beslut",        "body": "Fed",        "flag": "🇺🇸"},
    {"date": "2025-05-07", "event": "Fed FOMC-beslut",        "body": "Fed",        "flag": "🇺🇸"},
    {"date": "2025-06-18", "event": "Fed FOMC-beslut",        "body": "Fed",        "flag": "🇺🇸"},
    {"date": "2025-07-30", "event": "Fed FOMC-beslut",        "body": "Fed",        "flag": "🇺🇸"},
    {"date": "2025-09-17", "event": "Fed FOMC-beslut",        "body": "Fed",        "flag": "🇺🇸"},
    {"date": "2025-11-05", "event": "Fed FOMC-beslut",        "body": "Fed",        "flag": "🇺🇸"},
    {"date": "2025-12-17", "event": "Fed FOMC-beslut",        "body": "Fed",        "flag": "🇺🇸"},
    # ── Fed FOMC 2026 ──────────────────────────────────────────────────────────
    {"date": "2026-01-28", "event": "Fed FOMC-beslut",        "body": "Fed",        "flag": "🇺🇸"},
    {"date": "2026-03-18", "event": "Fed FOMC-beslut",        "body": "Fed",        "flag": "🇺🇸"},
    {"date": "2026-05-06", "event": "Fed FOMC-beslut",        "body": "Fed",        "flag": "🇺🇸"},
    {"date": "2026-06-17", "event": "Fed FOMC-beslut",        "body": "Fed",        "flag": "🇺🇸"},
    {"date": "2026-07-29", "event": "Fed FOMC-beslut",        "body": "Fed",        "flag": "🇺🇸"},
    {"date": "2026-09-16", "event": "Fed FOMC-beslut",        "body": "Fed",        "flag": "🇺🇸"},
    {"date": "2026-11-04", "event": "Fed FOMC-beslut",        "body": "Fed",        "flag": "🇺🇸"},
    {"date": "2026-12-16", "event": "Fed FOMC-beslut",        "body": "Fed",        "flag": "🇺🇸"},
    # ── ECB 2025 ───────────────────────────────────────────────────────────────
    {"date": "2025-01-30", "event": "ECB räntebesked",        "body": "ECB",        "flag": "🇪🇺"},
    {"date": "2025-03-06", "event": "ECB räntebesked",        "body": "ECB",        "flag": "🇪🇺"},
    {"date": "2025-04-17", "event": "ECB räntebesked",        "body": "ECB",        "flag": "🇪🇺"},
    {"date": "2025-06-05", "event": "ECB räntebesked",        "body": "ECB",        "flag": "🇪🇺"},
    {"date": "2025-07-24", "event": "ECB räntebesked",        "body": "ECB",        "flag": "🇪🇺"},
    {"date": "2025-09-11", "event": "ECB räntebesked",        "body": "ECB",        "flag": "🇪🇺"},
    {"date": "2025-10-30", "event": "ECB räntebesked",        "body": "ECB",        "flag": "🇪🇺"},
    {"date": "2025-12-18", "event": "ECB räntebesked",        "body": "ECB",        "flag": "🇪🇺"},
    # ── ECB 2026 ───────────────────────────────────────────────────────────────
    {"date": "2026-01-29", "event": "ECB räntebesked",        "body": "ECB",        "flag": "🇪🇺"},
    {"date": "2026-03-05", "event": "ECB räntebesked",        "body": "ECB",        "flag": "🇪🇺"},
    {"date": "2026-04-16", "event": "ECB räntebesked",        "body": "ECB",        "flag": "🇪🇺"},
    {"date": "2026-06-04", "event": "ECB räntebesked",        "body": "ECB",        "flag": "🇪🇺"},
    {"date": "2026-07-23", "event": "ECB räntebesked",        "body": "ECB",        "flag": "🇪🇺"},
    {"date": "2026-09-10", "event": "ECB räntebesked",        "body": "ECB",        "flag": "🇪🇺"},
    {"date": "2026-10-29", "event": "ECB räntebesked",        "body": "ECB",        "flag": "🇪🇺"},
    {"date": "2026-12-17", "event": "ECB räntebesked",        "body": "ECB",        "flag": "🇪🇺"},
    # ── Riksbanken 2025 ────────────────────────────────────────────────────────
    {"date": "2025-01-29", "event": "Riksbanken räntebesked", "body": "Riksbanken", "flag": "🇸🇪"},
    {"date": "2025-03-20", "event": "Riksbanken räntebesked", "body": "Riksbanken", "flag": "🇸🇪"},
    {"date": "2025-05-08", "event": "Riksbanken räntebesked", "body": "Riksbanken", "flag": "🇸🇪"},
    {"date": "2025-06-19", "event": "Riksbanken räntebesked", "body": "Riksbanken", "flag": "🇸🇪"},
    {"date": "2025-09-04", "event": "Riksbanken räntebesked", "body": "Riksbanken", "flag": "🇸🇪"},
    {"date": "2025-11-06", "event": "Riksbanken räntebesked", "body": "Riksbanken", "flag": "🇸🇪"},
    # ── Riksbanken 2026 ────────────────────────────────────────────────────────
    {"date": "2026-02-05", "event": "Riksbanken räntebesked", "body": "Riksbanken", "flag": "🇸🇪"},
    {"date": "2026-03-26", "event": "Riksbanken räntebesked", "body": "Riksbanken", "flag": "🇸🇪"},
    {"date": "2026-05-07", "event": "Riksbanken räntebesked", "body": "Riksbanken", "flag": "🇸🇪"},
    {"date": "2026-06-18", "event": "Riksbanken räntebesked", "body": "Riksbanken", "flag": "🇸🇪"},
    {"date": "2026-09-03", "event": "Riksbanken räntebesked", "body": "Riksbanken", "flag": "🇸🇪"},
    {"date": "2026-11-05", "event": "Riksbanken räntebesked", "body": "Riksbanken", "flag": "🇸🇪"},
    # ── Norges Bank 2025 ───────────────────────────────────────────────────────
    {"date": "2025-01-23", "event": "Norges Bank räntebesked","body": "Norges Bank","flag": "🇳🇴"},
    {"date": "2025-03-27", "event": "Norges Bank räntebesked","body": "Norges Bank","flag": "🇳🇴"},
    {"date": "2025-05-08", "event": "Norges Bank räntebesked","body": "Norges Bank","flag": "🇳🇴"},
    {"date": "2025-06-19", "event": "Norges Bank räntebesked","body": "Norges Bank","flag": "🇳🇴"},
    {"date": "2025-08-14", "event": "Norges Bank räntebesked","body": "Norges Bank","flag": "🇳🇴"},
    {"date": "2025-09-18", "event": "Norges Bank räntebesked","body": "Norges Bank","flag": "🇳🇴"},
    {"date": "2025-11-06", "event": "Norges Bank räntebesked","body": "Norges Bank","flag": "🇳🇴"},
    {"date": "2025-12-18", "event": "Norges Bank räntebesked","body": "Norges Bank","flag": "🇳🇴"},
    # ── BoE 2025 ───────────────────────────────────────────────────────────────
    {"date": "2025-02-06", "event": "BoE räntebesked",        "body": "BoE",        "flag": "🇬🇧"},
    {"date": "2025-03-20", "event": "BoE räntebesked",        "body": "BoE",        "flag": "🇬🇧"},
    {"date": "2025-05-08", "event": "BoE räntebesked",        "body": "BoE",        "flag": "🇬🇧"},
    {"date": "2025-06-19", "event": "BoE räntebesked",        "body": "BoE",        "flag": "🇬🇧"},
    {"date": "2025-08-07", "event": "BoE räntebesked",        "body": "BoE",        "flag": "🇬🇧"},
    {"date": "2025-09-18", "event": "BoE räntebesked",        "body": "BoE",        "flag": "🇬🇧"},
    {"date": "2025-11-06", "event": "BoE räntebesked",        "body": "BoE",        "flag": "🇬🇧"},
    {"date": "2025-12-18", "event": "BoE räntebesked",        "body": "BoE",        "flag": "🇬🇧"},
    # ── BoE 2026 ───────────────────────────────────────────────────────────────
    {"date": "2026-02-05", "event": "BoE räntebesked",        "body": "BoE",        "flag": "🇬🇧"},
    {"date": "2026-03-19", "event": "BoE räntebesked",        "body": "BoE",        "flag": "🇬🇧"},
    {"date": "2026-05-07", "event": "BoE räntebesked",        "body": "BoE",        "flag": "🇬🇧"},
    {"date": "2026-06-18", "event": "BoE räntebesked",        "body": "BoE",        "flag": "🇬🇧"},
    {"date": "2026-08-06", "event": "BoE räntebesked",        "body": "BoE",        "flag": "🇬🇧"},
    {"date": "2026-09-17", "event": "BoE räntebesked",        "body": "BoE",        "flag": "🇬🇧"},
    {"date": "2026-11-05", "event": "BoE räntebesked",        "body": "BoE",        "flag": "🇬🇧"},
    {"date": "2026-12-17", "event": "BoE räntebesked",        "body": "BoE",        "flag": "🇬🇧"},
]


def get_upcoming_macro_events(days_ahead: int = 30) -> list[dict]:
    """
    Returnerar kommande makrohändelser inom `days_ahead` dagar.
    Varje post innehåller: flag, event, body, date, days_until.
    """
    today = datetime.date.today()
    cutoff = today + datetime.timedelta(days=days_ahead)
    upcoming = []
    for ev in MACRO_EVENTS:
        try:
            d = datetime.date.fromisoformat(ev["date"])
        except ValueError:
            continue
        if today <= d <= cutoff:
            upcoming.append({**ev, "days_until": (d - today).days})
    return sorted(upcoming, key=lambda x: x["days_until"])


def get_all_events_by_month(year: int | None = None) -> dict[str, list[dict]]:
    """
    Returnerar alla händelser grupperade per månad (för kalendervy).
    year: filtrera på år (None = alla år)
    """
    result: dict[str, list[dict]] = {}
    for ev in MACRO_EVENTS:
        try:
            d = datetime.date.fromisoformat(ev["date"])
        except ValueError:
            continue
        if year is not None and d.year != year:
            continue
        key = d.strftime("%Y-%m")
        result.setdefault(key, []).append({**ev, "day": d.day})
    return result
