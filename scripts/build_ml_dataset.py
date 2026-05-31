"""
build_ml_dataset.py — Bygger träningsdataset för ml_predictor.

För varje ticker i valt universum:
  1. Hämtar N års prishistorik via yfinance
  2. För varje månadsändpunkt t: beräknar TECH_FEATURES vid t + forward_return_30d
  3. Slår ihop till en parquet under data/ml/<universe>_training.parquet

Använd:
    python -m scripts.build_ml_dataset --universe universe --years 5
    python -m scripts.build_ml_dataset --universe smallcap --years 5

Idempotent: skriver över parquet vid varje körning. Cachar inte mellanresultat.
Ticker-fel loggas men stoppar inte hela körningen.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.ml_predictor import TECH_FEATURES, compute_features_at  # noqa: E402

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")


def _get_universe(name: str) -> list:
    """Returnerar tickers för 'universe' eller 'smallcap'."""
    if name == "universe":
        from core import config
        return list(config.UNIVERSE)
    elif name == "smallcap":
        from smallcap.universe import SMALLCAP_UNIVERSE
        return list(SMALLCAP_UNIVERSE)
    raise ValueError(f"Okänt universum: {name!r}. Använd 'universe' eller 'smallcap'.")


def _build_sector_map() -> dict:
    """Bygg ticker→sektor-karta från senaste scored_universe-rapporten.

    Undviker extra yfinance-anrop genom att återanvända sektor-etiketterna som
    redan finns i scan-datan. Används för att träna per-sektor ML-modeller.
    Returnerar {} om ingen rapport finns (då blir 'sector' = "Unknown").
    """
    reports_dir = ROOT / "reports"
    files = sorted(reports_dir.glob("scored_universe_*.csv"), reverse=True)
    files += sorted(reports_dir.glob("smallcap_scored_*.csv"), reverse=True)
    sector_map = {}
    for f in files:
        try:
            sdf = pd.read_csv(f, usecols=["ticker", "sector"], low_memory=False)
            for t, s in zip(sdf["ticker"], sdf["sector"]):
                tk = str(t).upper().strip()
                if tk and tk not in sector_map and isinstance(s, str) and s:
                    sector_map[tk] = s
        except Exception:
            continue
    logger.info(f"  Sektor-karta byggd: {len(sector_map)} tickers")
    return sector_map


def _build_rows_for_ticker(ticker: str, hist: pd.DataFrame, step_days: int = 21,
                           sector: str = "Unknown") -> list:
    """Bygg en lista av {date, ticker, ...features, forward_return_30d} per
    månadsändpunkt i historiken.

    step_days=21 ≈ 1 trading-månad.
    """
    rows = []
    if hist.empty or "Close" not in hist.columns:
        return rows
    close = hist["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    volume = hist["Volume"] if "Volume" in hist.columns else None
    if isinstance(volume, pd.DataFrame):
        volume = volume.iloc[:, 0]

    n = len(close)
    # Vi behöver minst 252 + 30 dagar för att kunna beräkna features OCH ha en
    # 30-dagars framtida avkastning. Skanna med step_days steg.
    start = 252
    end = n - 30
    if end <= start:
        return rows

    for i in range(start, end, step_days):
        slice_close = close.iloc[: i + 1]
        slice_volume = volume.iloc[: i + 1] if volume is not None else None
        feats = compute_features_at(slice_close, slice_volume)

        try:
            now_price = float(close.iloc[i])
            future_price = float(close.iloc[i + 30])
        except (IndexError, ValueError):
            continue
        if not now_price:
            continue
        fwd_return = (future_price / now_price) - 1
        if not (-0.95 <= fwd_return <= 5.0):
            # Filtrera bort uppenbara split-artefakter och korrupta priser
            continue

        row = {
            "ticker": ticker,
            "sector": sector,
            "date": close.index[i].strftime("%Y-%m-%d") if hasattr(close.index[i], "strftime") else str(close.index[i]),
            **feats,
            "forward_return_30d": fwd_return,
        }
        rows.append(row)

    return rows


def build_dataset(universe: str, years: int, max_tickers: int | None = None,
                  out_path: Path | None = None) -> Path:
    """Bygger träningsdataset för givet universum."""
    tickers = _get_universe(universe)
    if max_tickers:
        tickers = tickers[:max_tickers]
    logger.info(f"Bygger ML-dataset för {universe}: {len(tickers)} tickers, {years} år historik")

    sector_map = _build_sector_map()

    import yfinance as yf

    all_rows = []
    n_ok, n_fail = 0, 0
    t0 = time.time()
    for i, ticker in enumerate(tickers, 1):
        if i % 25 == 0:
            elapsed = time.time() - t0
            logger.info(f"  [{i}/{len(tickers)}] {n_ok} ok / {n_fail} fail, {elapsed:.0f}s")
        try:
            hist = yf.download(ticker, period=f"{years}y", auto_adjust=True,
                               progress=False, threads=False)
            if hist is None or hist.empty:
                n_fail += 1
                continue
            rows = _build_rows_for_ticker(
                ticker, hist, sector=sector_map.get(ticker.upper().strip(), "Unknown")
            )
            all_rows.extend(rows)
            n_ok += 1
        except Exception as e:
            logger.debug(f"  ⚠ {ticker}: {e}")
            n_fail += 1
        # Liten throttle för att undvika rate-limit
        time.sleep(0.15)

    if not all_rows:
        raise RuntimeError(f"Inga rader byggda — alla {len(tickers)} tickers misslyckades.")

    df = pd.DataFrame(all_rows)
    out_path = out_path or (ROOT / "data" / "ml" / f"{universe}_training.parquet")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_path, index=False)
    logger.info(f"✅ Sparade {len(df)} rader från {n_ok}/{len(tickers)} tickers → {out_path}")
    return out_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", choices=["universe", "smallcap"], required=True)
    ap.add_argument("--years", type=int, default=5)
    ap.add_argument("--max-tickers", type=int, default=None,
                    help="Begränsa antalet tickers (för snabb test).")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    build_dataset(args.universe, args.years, args.max_tickers, args.out)


if __name__ == "__main__":
    main()
