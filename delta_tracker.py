"""
delta_tracker.py
================
Jämför aktuell scan med föregående scan och identifierar förändringar.

Det här är en av de mest värdefulla signalerna:
- En aktie som klättrar från rank 80 → 12 på en vecka är mer intressant
  än en som legat på rank 12 i månader
- Stigande score = modellen ser förbättring i fundamenta/momentum
- Fallande score = tidig varning innan priset reagerar

Sparar varje scan-snapshot till data/history/snapshot_YYYY-MM-DD.csv
Jämför automatiskt med närmaste tidigare snapshot vid nästa körning.

Flaggor som genereras:
  🆕 NY I TOPP20    – inte i topp 20 förra veckan, är det nu
  📤 LÄMNAT TOPP20  – var i topp 20, inte längre
  📈 STIGANDE       – composite score upp >7p sedan sist
  📉 FALLANDE       – composite score ned >7p sedan sist
  ⬆ +N rank        – klättrat N platser i ranking
  ⬇ -N rank        – tappat N platser i ranking
  🔔 BREAKOUT       – korsade MA200 uppåt sedan sist
"""

import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path

HISTORY_DIR  = "data/history"
MAX_LOOKBACK = 14   # Dagar bakåt att leta efter föregående snapshot

# Kolumner att spara i varje snapshot
SNAPSHOT_COLS = [
    "ticker", "score_total", "rank",
    "current_price", "rsi_14",
    "score_value", "score_quality", "score_momentum",
    "score_growth", "score_risk", "score_sentiment",
    "price_vs_ma200", "trend_capped",
    "short_pct_float",  # NEW: spåra short interest-förändringar
]

Path(HISTORY_DIR).mkdir(parents=True, exist_ok=True)


# ── Spara snapshot ─────────────────────────────────────────────

def save_snapshot(scored_df: pd.DataFrame, date_str: str = None) -> Path:
    """
    Sparar aktuell scan till history-mappen för framtida jämförelse.
    Kallas automatiskt i slutet av varje scan.
    """
    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")

    path = Path(HISTORY_DIR) / f"snapshot_{date_str}.csv"

    # Spara bara de kolumner vi behöver
    save_cols = [c for c in SNAPSHOT_COLS if c in scored_df.columns]
    scored_df[save_cols].to_csv(path, index=False)

    return path


# ── Ladda föregående snapshot ──────────────────────────────────

def load_previous_snapshot() -> pd.DataFrame | None:
    """
    Letar upp och laddar det senaste snapshot som är minst 1 dag gammalt.
    Returnerar None om inget hittas.
    """
    history_dir = Path(HISTORY_DIR)
    if not history_dir.exists():
        return None

    today = datetime.now().date()
    files = sorted(history_dir.glob("snapshot_*.csv"), reverse=True)

    for f in files:
        date_str = f.stem.replace("snapshot_", "")
        try:
            file_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            days_old  = (today - file_date).days
            if 1 <= days_old <= MAX_LOOKBACK:
                df = pd.read_csv(f)
                df["_snapshot_date"] = date_str
                return df
        except Exception:
            continue

    return None


# ── Beräkna deltas ─────────────────────────────────────────────

def calc_deltas(current_df: pd.DataFrame, previous_df: pd.DataFrame | None) -> pd.DataFrame:
    """
    Jämför nuvarande scan med föregående.
    Lägger till kolumner för förändring och flaggor.

    Nya kolonner:
        score_delta     – förändring i composite score
        rank_delta      – förändring i rank (positiv = förbättrad)
        price_change_1w – prisförändring sedan sist (%)
        delta_flag      – textuella flaggor (se modul-docstring)
        is_new          – True om aktien inte fanns i föregående scan
    """
    df = current_df.copy()

    if previous_df is None or previous_df.empty:
        df["score_delta"]     = pd.Series(dtype=float, index=df.index)
        df["rank_delta"]      = pd.Series(dtype=float, index=df.index)
        df["price_change_1w"] = pd.Series(dtype=float, index=df.index)
        df["delta_flag"]      = ""
        df["is_new"]          = False
        return df

    # Byt namn på föregående kolumner
    prev = previous_df.rename(columns={
        "score_total":    "prev_score",
        "rank":           "prev_rank",
        "current_price":  "prev_price",
        "rsi_14":         "prev_rsi",
        "price_vs_ma200": "prev_ma200",
        "trend_capped":   "prev_trend_capped",
        "short_pct_float":"prev_short",
    })

    keep_prev = ["ticker", "prev_score", "prev_rank",
                 "prev_price", "prev_rsi", "prev_ma200", "prev_trend_capped",
                 "prev_short"]
    keep_prev = [c for c in keep_prev if c in prev.columns]

    merged = df.merge(prev[keep_prev], on="ticker", how="left")

    # Beräkna deltas
    merged["score_delta"]     = pd.to_numeric(merged["score_total"] - merged["prev_score"], errors="coerce")
    merged["rank_delta"]      = pd.to_numeric(merged["prev_rank"] - merged["rank"], errors="coerce")   # Positiv = bättre
    merged["is_new"]          = merged["prev_score"].isna()

    # Short interest-förändring (procentenheter)
    if "prev_short" in merged.columns and "short_pct_float" in merged.columns:
        merged["short_delta"] = merged["short_pct_float"] - merged["prev_short"]
    else:
        merged["short_delta"] = None

    # Prisförändring
    if "prev_price" in merged.columns and "current_price" in merged.columns:
        merged["price_change_1w"] = (
            (merged["current_price"] / merged["prev_price"]) - 1
        ).where(merged["prev_price"].notna() & (merged["prev_price"] > 0))
    else:
        merged["price_change_1w"] = None

    # Generera flaggor
    universe_size = len(merged)
    merged["delta_flag"] = merged.apply(
        lambda row: _build_flag(row, universe_size), axis=1
    )

    return merged


def _build_flag(row, universe_size: int) -> str:
    """Bygg textuell flagga baserat på förändringarna."""
    flags = []

    rank      = row.get("rank")
    prev_rank = row.get("prev_rank")
    score_d   = row.get("score_delta")
    rank_d    = row.get("rank_delta")
    is_new    = row.get("is_new", False)
    vs_ma200  = row.get("price_vs_ma200")
    prev_ma200= row.get("prev_ma200")

    if is_new or pd.isna(prev_rank):
        return "🆕 NY"

    # Ny i topp 20
    if pd.notna(rank) and pd.notna(prev_rank):
        if rank <= 20 and prev_rank > 20:
            flags.append("🆕 NY I TOPP20")
        elif rank > 20 and prev_rank <= 20:
            flags.append("📤 LÄMNAT TOPP20")

    # Score-förändring
    if pd.notna(score_d):
        if score_d >= 8:
            flags.append(f"📈 +{score_d:.0f}p")
        elif score_d <= -8:
            flags.append(f"📉 {score_d:.0f}p")

    # Rank-förändring (minst 15 platser)
    if pd.notna(rank_d):
        if rank_d >= 15:
            flags.append(f"⬆ +{rank_d:.0f}")
        elif rank_d <= -15:
            flags.append(f"⬇ {rank_d:.0f}")

    # MA200-breakout (korsade uppåt)
    if (pd.notna(vs_ma200) and pd.notna(prev_ma200) and
            vs_ma200 >= 0 and prev_ma200 < 0):
        flags.append("🔔 BREAKOUT MA200")

    # Short interest-förändring
    short_d = row.get("short_delta")
    if pd.notna(short_d):
        # Procentenheter (t.ex. 0.02 = +2 percentenheter)
        if short_d <= -0.015:
            flags.append(f"💚 SHORT ↓{abs(short_d)*100:.1f}pp")  # Blankning minskar = bullish
        elif short_d >= 0.015:
            flags.append(f"💢 SHORT ↑{short_d*100:.1f}pp")       # Blankning ökar = bearish

    return " · ".join(flags)


# ── Summerings-sektion för rapporten ──────────────────────────

def build_delta_report_section(df: pd.DataFrame) -> str:
    """
    Bygger en markdown-sektion med de viktigaste förändringarna sedan sist.
    """
    if "delta_flag" not in df.columns or df["delta_flag"].isna().all():
        return ""

    lines = ["\n## 🔄 Förändringar sedan förra scanningen\n"]

    # Ny i topp 20
    new_top = df[df["delta_flag"].str.contains("NY I TOPP20", na=False)]
    if not new_top.empty:
        lines.append("### 🆕 Ny i topp 20")
        for _, row in new_top.iterrows():
            lines.append(
                f"- **`{row['ticker']}`** {row.get('name','')} "
                f"– Score {row['score_total']:.0f} "
                f"(från rank {str(row.get('prev_rank','?'))} → #{str(row.get('rank','?'))})"
            )
        lines.append("")

    # Lämnat topp 20
    left_top = df[df["delta_flag"].str.contains("LÄMNAT TOPP20", na=False)]
    if not left_top.empty:
        lines.append("### 📤 Lämnat topp 20")
        for _, row in left_top.iterrows():
            lines.append(
                f"- **`{row['ticker']}`** {row.get('name','')} "
                f"– Nu rank #{row.get('rank','?')}, score {row['score_total']:.0f}"
            )
        lines.append("")

    # Starkast stigande score (topp 5)
    rising = df[df["score_delta"].notna()].nlargest(5, "score_delta")
    rising = rising[rising["score_delta"] >= 5]
    if not rising.empty:
        lines.append("### 📈 Starkast stigande score")
        for _, row in rising.iterrows():
            d = row["score_delta"]
            lines.append(
                f"- **`{row['ticker']}`** {row.get('name','')} "
                f"– Score {row['score_total']:.0f} "
                f"(+{d:.0f}p sedan sist, rank #{row.get('rank','?')})"
            )
        lines.append("")

    # Starkast fallande score (topp 5)
    falling = df[df["score_delta"].notna()].nsmallest(5, "score_delta")
    falling = falling[falling["score_delta"] <= -5]
    if not falling.empty:
        lines.append("### 📉 Starkast fallande score")
        for _, row in falling.iterrows():
            d = row["score_delta"]
            lines.append(
                f"- **`{row['ticker']}`** {row.get('name','')} "
                f"– Score {row['score_total']:.0f} "
                f"({d:.0f}p sedan sist)"
            )
        lines.append("")

    # MA200-breakouts
    breakouts = df[df["delta_flag"].str.contains("BREAKOUT", na=False)]
    if not breakouts.empty:
        lines.append("### 🔔 MA200-breakouts")
        for _, row in breakouts.iterrows():
            lines.append(
                f"- **`{row['ticker']}`** {row.get('name','')} "
                f"– Korsade MA200 uppåt, score {row['score_total']:.0f}"
            )
        lines.append("")

    return "\n".join(lines)
