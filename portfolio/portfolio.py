"""
portfolio.py
============
Analyzes the user's current holdings against the scored universe.
Generates Buy/Hold/Sell recommendations based on each holding's
rank within the universe.
"""

import pandas as pd
import numpy as np
from pathlib import Path

from core import config


def load_holdings(path: str = None) -> pd.DataFrame:
    """
    Load user holdings from CSV file.
    Expected format:
        ticker,shares,cost_basis
        AAPL,10,150.00
        VOLV-B.ST,100,210.50

    Returns empty DataFrame if file doesn't exist.
    """
    path = path or config.HOLDINGS_FILE

    if not Path(path).exists():
        print(f"  ℹ No holdings file at {path} - skipping portfolio analysis")
        print(f"    (Create one with columns: ticker,shares,cost_basis)")
        return pd.DataFrame()

    try:
        df = pd.read_csv(path)
        # Normalize column names (case-insensitive)
        df.columns = df.columns.str.lower().str.strip()
        required = {"ticker", "shares"}
        if not required.issubset(set(df.columns)):
            print(f"  ⚠ Holdings file must have columns: ticker, shares (cost_basis optional)")
            return pd.DataFrame()

        # cost_basis is optional
        if "cost_basis" not in df.columns:
            df["cost_basis"] = None

        df["ticker"] = df["ticker"].str.strip().str.upper()
        return df
    except Exception as e:
        print(f"  ⚠ Failed to load holdings: {e}")
        return pd.DataFrame()


def analyze_portfolio(holdings: pd.DataFrame, scored_universe: pd.DataFrame) -> pd.DataFrame:
    """
    Match holdings against scored universe and generate recommendations.

    Returns DataFrame with columns:
        ticker, shares, cost_basis, current_price, market_value,
        unrealized_pnl, unrealized_pnl_pct, score, rank, recommendation, reason
    """
    if holdings.empty:
        return pd.DataFrame()

    # Merge holdings with scored data
    merged = holdings.merge(
        scored_universe,
        on="ticker",
        how="left",
        suffixes=("_holding", "")
    )

    rows = []
    for _, row in merged.iterrows():
        ticker = row["ticker"]
        shares = row["shares"]
        cost_basis = row["cost_basis"]
        current_price = row.get("current_price")
        score = row.get("score_total")
        rank = row.get("rank")
        name = row.get("name", ticker)

        # Calculate financial metrics
        market_value = shares * current_price if pd.notna(current_price) else None
        cost_total = shares * cost_basis if pd.notna(cost_basis) else None
        pnl = market_value - cost_total if market_value and cost_total else None
        pnl_pct = (pnl / cost_total) if pnl is not None and cost_total else None

        # Generate recommendation
        rec, reason = _make_recommendation(row, scored_universe)

        rows.append({
            "ticker": ticker,
            "name": name,
            "shares": shares,
            "cost_basis": cost_basis,
            "current_price": current_price,
            "market_value": market_value,
            "unrealized_pnl": pnl,
            "unrealized_pnl_pct": pnl_pct,
            "score": score,
            "rank": rank,
            "recommendation": rec,
            "reason": reason,
        })

    return pd.DataFrame(rows)


def _make_recommendation(holding_row, scored_universe: pd.DataFrame) -> tuple:
    """
    Decide buy more / hold / sell based on score percentile and momentum.
    Returns (recommendation, reason) tuple.
    """
    score = holding_row.get("score_total")

    if pd.isna(score):
        return "OKÄND", "Ingen scoringdata tillgänglig (kan vara utanför universumet)"

    universe_size = len(scored_universe)
    rank = holding_row.get("rank", universe_size)
    percentile = 100 * (1 - (rank - 1) / universe_size) if universe_size > 0 else 50

    # Get key signals for reasoning
    momentum = holding_row.get("score_momentum", 50)
    rsi = holding_row.get("rsi_14")
    return_3m = holding_row.get("return_3m")

    # "Top X%" means in the top X percent (low number = better)
    top_pct = 100 - percentile

    # Decision logic
    if percentile >= config.BUY_MORE_PERCENTILE:
        # Top 20% of universe
        if rsi is not None and rsi > 75:
            return "BEHÅLL", f"I topp {top_pct:.0f}% men RSI={rsi:.0f} (överköpt) - vänta med köp"
        return "KÖP MER", f"I topp {top_pct:.0f}% av universumet, score {score:.0f}"

    elif percentile >= config.HOLD_PERCENTILE:
        # Top 20-50%
        if return_3m is not None and return_3m < -0.15:
            return "BEVAKA", f"Score {score:.0f} men ned {return_3m*100:.0f}% senaste 3 mån"
        return "BEHÅLL", f"I topp {top_pct:.0f}% av universumet"

    else:
        # Bottom 50%
        if return_3m is not None and return_3m < -0.10:
            return "SÄLJ/MINSKA", f"I bottenhalvan ({top_pct:.0f}% percentil) + nedåtgående trend"
        if top_pct > 75:
            return "SÄLJ/MINSKA", f"I sämsta 25% av universumet (percentil {top_pct:.0f})"
        return "BEVAKA", f"Score {score:.0f} (under medel) - överväg minskning"


def portfolio_summary(analysis: pd.DataFrame) -> dict:
    """Generate aggregate stats for the whole portfolio."""
    if analysis.empty:
        return {}

    total_value = analysis["market_value"].sum(skipna=True)
    total_cost = (analysis["shares"] * analysis["cost_basis"]).sum(skipna=True)
    total_pnl = analysis["unrealized_pnl"].sum(skipna=True)

    # Concentration: largest position as % of portfolio
    if total_value > 0:
        analysis["weight"] = analysis["market_value"] / total_value
        max_weight = analysis["weight"].max()
        top_3_concentration = analysis["weight"].nlargest(3).sum()
    else:
        max_weight = None
        top_3_concentration = None

    rec_counts = analysis["recommendation"].value_counts().to_dict()

    return {
        "n_positions": len(analysis),
        "total_market_value": total_value,
        "total_cost_basis": total_cost,
        "total_unrealized_pnl": total_pnl,
        "total_return_pct": (total_pnl / total_cost) if total_cost else None,
        "average_score": analysis["score"].mean(),
        "max_position_weight": max_weight,
        "top_3_concentration": top_3_concentration,
        "recommendations": rec_counts,
    }


# ══════════════════════════════════════════════════════════════
# KORRELATIONSANALYS
# ══════════════════════════════════════════════════════════════

def analyze_correlation(holdings: pd.DataFrame, period: str = "6mo") -> dict:
    """
    Analyserar korrelation mellan dina innehav.
    Hög korrelation = koncentrerad risk (alla rör sig tillsammans).

    Returnerar:
        correlation_matrix     – DataFrame med parvis korrelation
        avg_pairwise_corr      – snitt-korrelation (0-1)
        max_corr_pair          – (tickerA, tickerB, korrelation)
        concentration_warning  – True om snitt > 0.7
        diversification_score  – 0-100 (högre = bättre diversifierat)
    """
    import yfinance as yf

    if holdings is None or holdings.empty or len(holdings) < 2:
        return {}

    tickers = holdings["ticker"].tolist()

    try:
        # Hämta priser
        prices = yf.download(
            tickers, period=period,
            auto_adjust=True, progress=False, threads=True,
        )

        if isinstance(prices.columns, pd.MultiIndex):
            prices = prices["Close"]

        # Beräkna dagliga returns
        returns = prices.pct_change().dropna()

        if returns.empty or len(returns.columns) < 2:
            return {}

        # Korrelationsmatris
        corr_matrix = returns.corr()

        # Snittkorrelation (exklusive diagonal)
        upper_tri = corr_matrix.where(
            np.triu(np.ones(corr_matrix.shape), k=1).astype(bool)
        )
        avg_corr = upper_tri.stack().mean()

        # Högsta korrelation
        upper_tri_clean = upper_tri.stack().dropna()
        if len(upper_tri_clean) > 0:
            max_pair_idx = upper_tri_clean.idxmax()
            max_corr_val = upper_tri_clean.max()
        else:
            max_pair_idx = None
            max_corr_val = None

        # Diversifierings-score: 100 = okorrelerat, 0 = identiska
        diversification = (1 - max(0, avg_corr)) * 100

        return {
            "correlation_matrix":    corr_matrix.round(2),
            "avg_pairwise_corr":     round(avg_corr, 3),
            "max_corr_pair":         max_pair_idx,
            "max_corr_value":        round(max_corr_val, 3) if max_corr_val else None,
            "concentration_warning": avg_corr > 0.7,
            "diversification_score": round(diversification, 0),
        }

    except Exception as e:
        print(f"  ⚠ Korrelationsanalys misslyckades: {e}")
        return {}


def build_correlation_section(corr_info: dict) -> str:
    """Markdown-sektion för korrelationsanalys."""
    if not corr_info:
        return ""

    div_score = corr_info.get("diversification_score", 50)
    avg_corr  = corr_info.get("avg_pairwise_corr", 0)

    icon = "✅" if div_score >= 60 else "⚠️" if div_score >= 40 else "🚨"

    lines = ["\n## 🔗 Portföljens diversifiering\n"]
    lines.append(f"**{icon} Diversifierings-score: {div_score:.0f}/100**  ")
    lines.append(f"Genomsnittlig parvis korrelation: **{avg_corr:.2f}**")
    lines.append("")

    if corr_info.get("max_corr_pair") and corr_info.get("max_corr_value"):
        pair = corr_info["max_corr_pair"]
        val  = corr_info["max_corr_value"]
        lines.append(f"### Mest korrelerade par")
        lines.append(f"- `{pair[0]}` ↔ `{pair[1]}` – korrelation **{val:.2f}**")
        lines.append("")

    if corr_info.get("concentration_warning"):
        lines.append("⚠️ **Varning:** Dina innehav är starkt korrelerade. "
                    "Du har i praktiken färre oberoende positioner än det ser ut.")
        lines.append("Överväg att lägga till aktier från andra sektorer eller geografier.")
        lines.append("")
    elif div_score >= 70:
        lines.append("✅ **Bra diversifiering** – dina innehav rör sig oberoende av varandra.")
        lines.append("")

    # Tolkningsguide
    lines.append("> *0.0-0.3 = oberoende · 0.3-0.6 = måttligt · 0.6-1.0 = starkt korrelerade*")

    return "\n".join(lines)
