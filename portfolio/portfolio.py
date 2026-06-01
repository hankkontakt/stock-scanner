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

import yfinance as yf

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

        # ATR stop-loss endast för köprekommendationer
        atr_stop_price, atr_stop_pct = None, None
        if rec == "KÖP MER" and current_price and pd.notna(current_price):
            atr_stop_price, atr_stop_pct = _atr_stop(ticker, float(current_price))

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
            "atr_stop_price": atr_stop_price,
            "atr_stop_pct":   atr_stop_pct,
        })

    return pd.DataFrame(rows)


def _calc_atr(ticker: str, period: int = 14) -> float | None:
    """Average True Range (ATR14) för en ticker via yfinance."""
    try:
        hist = yf.Ticker(ticker).history(period="1mo", auto_adjust=True)
        if hist.empty or len(hist) < period:
            return None
        tr = pd.concat([
            hist["High"] - hist["Low"],
            abs(hist["High"] - hist["Close"].shift()),
            abs(hist["Low"]  - hist["Close"].shift()),
        ], axis=1).max(axis=1)
        atr = float(tr.rolling(period).mean().iloc[-1])
        return atr if not pd.isna(atr) else None
    except Exception:
        return None


def _atr_stop(ticker: str, price: float, mult: float = 2.5) -> tuple:
    """
    Beräknar ATR-baserad stop-loss.
    Returns: (stop_price, stop_pct) eller (None, None) om ATR ej tillgänglig.
    """
    atr = _calc_atr(ticker)
    if not atr or atr <= 0:
        return None, None
    stop = price - atr * mult
    return round(stop, 2), round((stop / price - 1) * 100, 1)


def _shrinkage_kelly(portfolio_value: float, num_positions: int = 10) -> dict:
    """
    Kelly-kriterium med shrinkage mot equal weight enligt Baker & McHale (2013).
    
    Formel: w_opt = (1-φ) x w_kelly + φ x (1/N)
    där:
      - w_kelly = Half-Kelly (standard)
      - 1/N     = equal weight
      - φ       = shrinkage intensity (0=full Kelly, 1=full equal weight)
    
    φ bestäms av estimeringsosäkerhet:
      - φ = 0.7 när using_defaults (för få trades för pålitlig estimation)
      - φ = 0.5 när vi har >=20 trades (viss tilltro till datan)
      - φ minskar mot 0.2 när n_trades -> 100+
    
    Detta skyddar mot estimation error som annars leder till överbetting.
    """
    try:
        from portfolio.paper_trading import get_kelly_inputs
        ki = get_kelly_inputs()
    except Exception:
        ki = {"win_rate": 0.55, "win_loss_ratio": 1.5, "n_trades": 0, "using_defaults": True}

    wr = ki["win_rate"]
    wl = ki["win_loss_ratio"]
    n_trades = ki.get("n_trades", 0)
    using_defaults = ki.get("using_defaults", True)
    
    # Half-Kelly
    kelly = max(0.0, wr - (1 - wr) / wl) if wl else 0.0
    hk = max(0.02, min(0.10, kelly * 0.5))
    
    # Equal weight (1/N, clamped to reasonable range)
    ew = max(0.02, min(0.25, 1.0 / max(num_positions, 1)))
    
    # Shrinkage intensity φ baserat på antal trades
    if using_defaults or n_trades < 20:
        phi = 0.7  # Hög osäkerhet -> mest equal weight
    elif n_trades < 50:
        phi = 0.5  # Viss data -> 50/50
    elif n_trades < 100:
        phi = 0.3  # Mer data -> mer Kelly
    else:
        phi = 0.2  # Mycket data -> mest Kelly
    
    # Shrinkage: blanda Kelly och equal weight
    shrunk = (1 - phi) * hk + phi * ew
    
    return {
        "pct":          round(shrunk * 100, 1),
        "sek":          round(portfolio_value * shrunk),
        "n_trades":     n_trades,
        "using_defaults": using_defaults,
        "shrinkage_phi": phi,
        "kelly_raw":    round(hk * 100, 1),
        "equal_weight": round(ew * 100, 1),
    }


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


def get_buy_recommendations(
    holdings: pd.DataFrame,
    scored_universe: pd.DataFrame,
    portfolio_value: float = 0,
) -> pd.DataFrame:
    """
    Utökat analyze_portfolio() med Half-Kelly positionsstorlek och
    ATR-baserade stop-loss strängar redo för visning i UI.

    Returnerar samma DataFrame som analyze_portfolio() plus:
        kelly_pct (float): Föreslagen portföljandel i procent
        kelly_suggested_sek (float): Kronbelopp baserat på Half-Kelly
        kelly_note (str): Läsbar förklaring
        stop_loss_str (str): Formaterad stop-loss för KÖP MER-rader
    """
    analysis = analyze_portfolio(holdings, scored_universe)
    if analysis.empty:
        return analysis

    if portfolio_value <= 0 and "market_value" in analysis.columns:
        portfolio_value = float(analysis["market_value"].sum(skipna=True))

    n_pos = len(analysis)
    ki = _shrinkage_kelly(portfolio_value, num_positions=n_pos)
    analysis["kelly_pct"]           = ki["pct"]
    analysis["kelly_suggested_sek"] = ki["sek"]
    
    phi_note = f" (φ={ki['shrinkage_phi']:.0f})" if ki.get("shrinkage_phi") is not None else ""
    analysis["kelly_note"] = (
        f"Shrinkage-Kelly: {ki['pct']:.0f}% av portföljvärdet = {ki['sek']:,.0f} kr"
        + phi_note
        + (" (standardvärden - för få trades)" if ki.get("using_defaults") else
           f" ({ki['n_trades']} stängda trades)")
        + f" | Kelly raw: {ki['kelly_raw']:.0f}% | Equal weight: {ki['equal_weight']:.0f}%"
    )

    def _fmt_stop(row) -> str:
        if row.get("recommendation") == "KÖP MER" and pd.notna(row.get("atr_stop_price")):
            return (
                f"Stop-loss: {row['atr_stop_price']:.2f}"
                f" ({row['atr_stop_pct']:.1f}% under kurs, ATR14)"
            )
        return ""

    analysis["stop_loss_str"] = analysis.apply(_fmt_stop, axis=1)
    return analysis


# ══════════════════════════════════════════════════════════════
# KORRELATIONSANALYS
# ══════════════════════════════════════════════════════════════

def analyze_correlation(holdings: pd.DataFrame, period: str = "6mo") -> dict:
    """
    Analyserar korrelation mellan dina innehav.
    Hög korrelation = koncentrerad risk (alla rör sig tillsammans).

    Returnerar:
        correlation_matrix     - DataFrame med parvis korrelation
        avg_pairwise_corr      - snitt-korrelation (0-1)
        max_corr_pair          - (tickerA, tickerB, korrelation)
        concentration_warning  - True om snitt > 0.7
        diversification_score  - 0-100 (högre = bättre diversifierat)
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
        lines.append(f"- `{pair[0]}` ↔ `{pair[1]}` - korrelation **{val:.2f}**")
        lines.append("")

    if corr_info.get("concentration_warning"):
        lines.append("⚠️ **Varning:** Dina innehav är starkt korrelerade. "
                    "Du har i praktiken färre oberoende positioner än det ser ut.")
        lines.append("Överväg att lägga till aktier från andra sektorer eller geografier.")
        lines.append("")
    elif div_score >= 70:
        lines.append("✅ **Bra diversifiering** - dina innehav rör sig oberoende av varandra.")
        lines.append("")

    # Tolkningsguide
    lines.append("> *0.0-0.3 = oberoende * 0.3-0.6 = måttligt * 0.6-1.0 = starkt korrelerade*")

    return "\n".join(lines)
