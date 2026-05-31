"""
convert_snapshots.py – Konvertera befintliga scored_universe_*.csv till bt_snapshots.

Kör en gång för att bootstrap backtest-systemet med historiska data:
    python -m scripts.convert_snapshots

Skapar snapshots i data/bt_snapshots/snapshot_YYYY-MM-DD.parquet från
reports/scored_universe_YYYY-MM-DD.csv, så att run_snapshot_backtest()
fungerar direkt istället för att vänta 6-12 veckor.
"""

import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from backtesting.backtest_snapshots import SNAPSHOT_DIR, save_snapshot

REPORT_DIR = _ROOT / "reports"

# Kolumnmappning: CSV-kolumnnamn -> snapshot-kolumnnamn
_COLUMN_ALIASES = {
    "close": "current_price",
    "sc_total": "score_total",
    "sc_value": "score_value",
    "sc_quality": "score_quality",
    "sc_momentum": "score_momentum",
    "sc_growth": "score_growth",
    "sc_risk": "score_risk",
    "sc_dividend": "score_dividend",
    "sc_sentiment": "score_sentiment",
    "sc_short_interest": "score_short_interest",
    "longName": "name",
    "shortName": "name",
}

# Kolumner som save_snapshot() behåller (keep_cols i backtest_snapshots.py)
_KEEP_COLS = [
    "ticker", "score_total", "score_value", "score_quality",
    "score_momentum", "score_growth", "score_risk", "score_dividend",
    "score_sentiment", "score_short_interest",
    "entry_signal", "current_price", "sector", "name",
    "return_12m", "return_6m", "return_3m",
]


def convert_scored_to_snapshots(
    reports_glob: str = "scored_universe_*.csv",
    dry_run: bool = False,
    verbose: bool = True,
) -> int:
    """
    Konvertera alla scored_universe_*.csv-filer till bt_snapshots.

    Args:
        reports_glob: Filnamnsmönster att leta efter i REPORTS_DIR
        dry_run: Om True, rapportera utan att skriva filer
        verbose: Skriv ut detaljer

    Returns:
        Antal snapshots skapade (eller skulle skapas om dry_run=True)
    """
    files = sorted(REPORT_DIR.glob(reports_glob))
    if not files:
        if verbose:
            print(f"Inga filer matchar '{reports_glob}' i {REPORT_DIR}")
        return 0

    created = 0
    skipped = 0

    for f in files:
        # Extrahera datum från filnamn: scored_universe_2026-05-14.csv
        try:
            date_str = f.stem.replace("scored_universe_", "")
            # Validera datumformat
            pd.Timestamp(date_str)
        except (ValueError, IndexError):
            if verbose:
                print(f"  !! Kan inte tolka datum från {f.name} – hoppar över")
            skipped += 1
            continue

        # Kolla om snapshot redan finns
        snapshot_path = SNAPSHOT_DIR / f"snapshot_{date_str}.parquet"
        if snapshot_path.exists() and not dry_run:
            if verbose:
                print(f"  -> {date_str}: snapshot finns redan – hoppar över")
            skipped += 1
            continue

        # Ladda CSV
        try:
            df = pd.read_csv(f, low_memory=False)
            df.columns = df.columns.str.strip()
        except Exception as e:
            if verbose:
                print(f"  !! {f.name}: kan inte läsa – {e}")
            skipped += 1
            continue

        if df.empty:
            if verbose:
                print(f"  !! {f.name}: tom DataFrame – hoppar över")
            skipped += 1
            continue

        # Mappa kolumner (hantera alias)
        for old_name, new_name in _COLUMN_ALIASES.items():
            if old_name in df.columns and new_name not in df.columns:
                df = df.rename(columns={old_name: new_name})

        # Begränsa till de kolumner som save_snapshot() förväntar sig
        available = [c for c in _KEEP_COLS if c in df.columns]
        missing = [c for c in _KEEP_COLS if c not in df.columns]

        if not available:
            if verbose:
                print(f"  !! {f.name}: inga användbara kolumner hittades")
            skipped += 1
            continue

        if missing and verbose:
            print(f"  i {f.name}: saknar kolumner: {', '.join(missing)}")

        snap_df = df[available].copy()

        if dry_run:
            if verbose:
                print(f"  -> {date_str}: skulle skapa snapshot ({len(snap_df)} rader, "
                      f"{len(available)}/{len(_KEEP_COLS)} kolumner)")
            created += 1
            continue

        # Spara via save_snapshot() från backtest_snapshots
        try:
            ok = save_snapshot(snap_df, date_str=date_str)
            if ok:
                if verbose:
                    print(f"  OK {date_str}: snapshot skapad ({len(snap_df)} rader)")
                created += 1
            else:
                if verbose:
                    print(f"  -> {date_str}: snapshot finns redan (save_snapshot returnerade False)")
                skipped += 1
        except Exception as e:
            if verbose:
                print(f"  ERROR  {date_str}: misslyckades – {e}")
            skipped += 1

    if verbose:
        print(f"\nSammanfattning: {created} skapade, {skipped} hoppade över ({len(files)} filer totalt)")
    return created


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Konvertera scored_universe CSV -> bt_snapshots")
    parser.add_argument("--dry-run", action="store_true", help="Visa vad som skulle göras utan att skriva")
    args = parser.parse_args()

    n = convert_scored_to_snapshots(dry_run=args.dry_run)
    if n > 0:
        print(f"Klar. {n} snapshot(s) skapades.")
    else:
        print("Inga nya snapshots skapades.")
