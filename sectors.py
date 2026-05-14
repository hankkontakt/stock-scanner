"""
sectors.py
==========
Sektorrelativ ranking – jämför varje aktie mot sin sektor
istället för globalt. Mer rättvis jämförelse mellan t.ex.
techbolag (aldrig "billiga") och banker (alltid "billiga").

Metod:
1. Beräkna global percentil-rank (som tidigare)
2. Beräkna sektorintern percentil-rank
3. Kombinera: 50% global + 50% sektoriell
   (justerbar via SECTOR_BLEND i config)
"""

import pandas as pd
import numpy as np


# Standardvikt för sektoriell vs global ranking (0-1)
# 0.0 = helt global (som tidigare)
# 1.0 = helt sektoriell
# 0.5 = hälften vardera (rekommenderat)
SECTOR_BLEND = 0.5

# Minsta antal aktier i en sektor för att göra sektoriell ranking
# Om sektorn har färre aktier används global ranking
MIN_SECTOR_SIZE = 4


def calc_sector_scores(df: pd.DataFrame, blend: float = SECTOR_BLEND) -> pd.DataFrame:
    """
    Beräknar sektoriella scores och blandar med globala.

    Ny kolumn: score_total_sector (den blandade versionen)
    Gamla score_total behålls för jämförelse.
    """
    df = df.copy()

    if "sector" not in df.columns or "score_total" not in df.columns:
        df["score_total_sector"] = df["score_total"]
        df["sector_rank"]        = df.get("rank", pd.Series(range(len(df))))
        return df

    score_cols = [
        "score_value", "score_quality", "score_momentum",
        "score_growth", "score_risk", "score_sentiment", "score_dividend"
    ]
    available = [c for c in score_cols if c in df.columns]

    sector_percentiles = []

    for ticker_idx in df.index:
        sector = df.loc[ticker_idx, "sector"]

        if pd.isna(sector) or sector in ("Unknown", ""):
            sector_percentiles.append(None)
            continue

        # Hämta alla aktier i samma sektor
        sector_mask   = df["sector"] == sector
        sector_df     = df[sector_mask]

        if len(sector_df) < MIN_SECTOR_SIZE:
            sector_percentiles.append(None)
            continue

        # Beräkna composite score inom sektorn (re-rank)
        sector_scores = sector_df[available].mean(axis=1)

        # Percentil för denna aktie inom sektorn
        own_score = sector_scores.loc[ticker_idx]
        pct       = (sector_scores < own_score).sum() / len(sector_scores)
        sector_percentiles.append(pct * 100)

    df["score_sector_pct"] = sector_percentiles

    # Global percentil (0-100)
    df["score_global_pct"] = df["score_total"].rank(pct=True) * 100

    # Blandad score
    has_sector = df["score_sector_pct"].notna()
    df["score_total_sector"] = df["score_global_pct"].copy()  # fallback = global

    # För aktier med sektoriell data: blanda
    df.loc[has_sector, "score_total_sector"] = (
        (1 - blend) * df.loc[has_sector, "score_global_pct"] +
        blend       * df.loc[has_sector, "score_sector_pct"]
    )

    # Ny ranking baserat på blandad score
    df["sector_rank"] = df["score_total_sector"].rank(
        ascending=False, method="min"
    ).astype("Int64")

    return df


def get_sector_summary(df: pd.DataFrame) -> pd.DataFrame:
    """
    Sammanfattning per sektor: snittpoäng, antal aktier, bästa aktie.
    Användbart för att se vilka sektorer som är starka just nu.
    """
    if "sector" not in df.columns:
        return pd.DataFrame()

    # Vi skapar en säker lambda som hanterar sektorer med enbart NaN-poäng
    def find_best_ticker(group_tickers):
        group_scores = df.loc[group_tickers.index, "score_total"]
        if group_scores.notna().any():
            # Hittar positionen för max-score (hanterar NaN genom fillna)
            return group_tickers.iloc[group_scores.fillna(-1).argmax()]
        return "—"

    summary = df.groupby("sector").agg(
        antal        = ("ticker", "count"),
        snitt_score  = ("score_total", "mean"),
        bästa_ticker = ("ticker", find_best_ticker),
        bästa_score  = ("score_total", "max"),
    ).reset_index()

    summary["snitt_score"] = summary["snitt_score"].round(1)
    summary["bästa_score"] = summary["bästa_score"].round(1)

    return summary.sort_values("snitt_score", ascending=False)
