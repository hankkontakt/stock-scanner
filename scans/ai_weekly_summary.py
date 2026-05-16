"""
ai_weekly_summary.py
====================
AI-veckosammanfattning – genererar en AI-sammanfattning av veckans data.

Körs automatiskt varje söndag via GitHub Actions (.github/workflows/ai_weekly_summary.yml).

Användning:
    python scans/ai_weekly_summary.py
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Lägg till projektroten i sökvägen
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.ai_analysis import ai_analysis
from portfolio.paper_trading import load_portfolio


def load_scan_log() -> list:
    """Läs veckans scan-log."""
    log_path = Path("data/scan_log.json")
    if log_path.exists():
        log = json.loads(log_path.read_text(encoding="utf-8"))
        print(f"📊 Scan-log: {len(log)} poster")
        return log
    print("📊 Scan-log: tom (kördes inte)")
    return []


def load_latest_scored() -> list[dict]:
    """Läs senaste scored_universe.csv."""
    # Försök hitta den senaste scored-filen
    reports_dir = Path("reports")
    scored_files = sorted(reports_dir.glob("scored_universe_*.csv"), reverse=True)

    if scored_files:
        latest = scored_files[0]
        print(f"📊 Senaste scored data: {latest.name}")
        with open(latest, encoding="utf-8") as f:
            lines = f.read().strip().split("\n")
        # CSV -> list of dicts
        if len(lines) > 1:
            headers = lines[0].split(",")
            rows = []
            for line in lines[1:]:
                vals = line.split(",")
                if len(vals) == len(headers):
                    rows.append(dict(zip(headers, vals)))
            print(f"📊 Scored data: {len(rows)} rader")
            return rows

    print("📊 Scored data: saknas")
    return []


def build_prompt(portfolio: list, scored: list[dict]) -> str:
    """Bygg prompt för AI-sammanfattningen."""
    # Top 20 från scored data
    top20 = scored[:20] if scored else []
    top20_lines = []
    for r in top20:
        ticker = r.get("ticker", r.get("symbol", "?"))
        score = r.get("score", r.get("total_score", "?"))
        top20_lines.append(f"- {ticker}: {score}")

    portfolio_str = json.dumps(portfolio, indent=2, ensure_ascii=False) if portfolio else "Inga positioner"
    top20_str = "\n".join(top20_lines) if top20_lines else "Ingen data"

    return f"""
Du är MarketScan AI — en svensk aktieanalytiker.

Skriv en **veckosammanfattning på svenska** för veckan som gått (måndag–söndag).
Sammanfattningen ska vara kortfattad (max 300 ord) och innehålla:

1. **Marknadsöversikt** — hur har veckan varit?
2. **Portföljstatus** — baserat på nedanstående portfölj
3. **Vinnare/förlorare** bland de högst rankade aktierna
4. **Rekommendationer** inför kommande vecka

**Portfölj:**
{portfolio_str}

**Senaste scan-data (top 20):**
{top20_str}
"""


def main():
    """Huvudfunktion – kör AI-sammanfattning och spara till fil."""
    print("🤖 AI-veckosammanfattning startar...")

    # Ladda data
    portfolio = load_portfolio()
    print(f"📊 Portfölj: {len(portfolio)} positioner")

    scored = load_latest_scored()

    # Bygg prompt
    prompt = build_prompt(portfolio, scored)

    # Generera AI-sammanfattning
    print("🧠 Genererar AI-sammanfattning...")
    summary_text = ai_analysis(prompt, use_case="weekly_summary")

    if not summary_text:
        print("⚠ Kunde inte generera AI-sammanfattning.")
        summary_text = "Kunde inte generera AI-sammanfattning – kontrollera API-nycklar."

    print(f"✅ Sammanfattning genererad ({len(summary_text)} tecken)")

    # Spara till fil
    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)

    week_num = datetime.now().isocalendar()[1]
    year = datetime.now().year
    summary_path = reports_dir / f"ai_weekly_summary_w{week_num}_{year}.md"
    summary_path.write_text(summary_text, encoding="utf-8")
    print(f"💾 Sparad till: {summary_path}")

    # Skriv ut kort version
    print("\n" + "=" * 50)
    print(summary_text[:500])
    print("..." if len(summary_text) > 500 else "")
    print("=" * 50)


if __name__ == "__main__":
    main()
