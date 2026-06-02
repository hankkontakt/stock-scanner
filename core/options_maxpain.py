"""
core/options_maxpain.py — Max Pain Calculator
==============================================
Beräknar max pain (där flest optioner förfaller värdelösa),
expected move från ATM-optioner, och support/resistance från OI-koncentration.
"""

import logging
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf

try:
    import plotly.graph_objects as go
    _PLOTLY_AVAILABLE = True
except ImportError:
    _PLOTLY_AVAILABLE = False

from core.options_chain import OptionsChain
from core.cache_utils import read_cache, write_cache

logger = logging.getLogger(__name__)


def calculate_max_pain(chain: pd.DataFrame, current_price: float) -> dict:
    """Beräkna max pain — den strike där flest optioner förfaller värdelösa.

    Max pain är summan av alla options inneboende värden (intrinsic value)
    för varje strike, och den strike med lägst totalt värde är max pain.

    Args:
        chain: DataFrame med optionskedja (calls + puts).
        current_price: Nuvarande aktiepris.

    Returns:
        Dict med {'max_pain_strike', 'max_pain_value', 'pain_curve': DataFrame}.
    """
    if chain is None or chain.empty:
        return {"max_pain_strike": None, "max_pain_value": None, "pain_curve": pd.DataFrame()}

    try:
        calls, puts = OptionsChain.extract_calls_puts(chain)
        if calls.empty and puts.empty:
            return {"max_pain_strike": None, "max_pain_value": None, "pain_curve": pd.DataFrame()}

        # Bygg pain curve
        all_strikes = sorted(set(
            list(calls["strike"].unique()) + list(puts["strike"].unique())
        ))

        pain_values = {}
        for strike in all_strikes:
            total_pain = 0.0

            # Call-pain: (strike - S) * OI om S < strike, annars 0
            c_at_strike = calls[calls["strike"] == strike]
            if not c_at_strike.empty:
                c_oi = float(c_at_strike["openInterest"].sum() or 0)
                if current_price < strike:
                    total_pain += (strike - current_price) * c_oi

            # Put-pain: (S - strike) * OI om S > strike, annars 0
            p_at_strike = puts[puts["strike"] == strike]
            if not p_at_strike.empty:
                p_oi = float(p_at_strike["openInterest"].sum() or 0)
                if current_price > strike:
                    total_pain += (current_price - strike) * p_oi

            pain_values[strike] = total_pain

        pain_series = pd.Series(pain_values)
        max_pain_strike = float(pain_series.idxmin())
        max_pain_value = float(pain_series.min())

        pain_df = pd.DataFrame({
            "strike": list(pain_values.keys()),
            "pain": list(pain_values.values()),
        }).sort_values("strike")

        return {
            "max_pain_strike": max_pain_strike,
            "max_pain_value": max_pain_value,
            "pain_curve": pain_df,
        }
    except Exception as e:
        logger.error("Max pain-beräkning misslyckades: %s", e)
        return {"max_pain_strike": None, "max_pain_value": None, "pain_curve": pd.DataFrame()}


def _render_max_pain_chart(pain_df: pd.DataFrame, current_price: float, max_pain_strike: float) -> Optional["go.Figure"]:
    """Skapa Plotly-diagram av pain curve. (privat hjälpfunktion)"""
    if not _PLOTLY_AVAILABLE or pain_df.empty:
        return None
    try:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=pain_df["strike"],
            y=pain_df["pain"],
            mode="lines+markers",
            name="Pain",
            line=dict(color="#ef5350", width=2),
            fill="tozeroy",
            fillcolor="rgba(239,83,80,0.1)",
        ))
        # Markera max pain
        fig.add_vline(
            x=max_pain_strike,
            line_dash="dash",
            line_color="#ffd600",
            annotation_text=f"Max Pain: {max_pain_strike:.2f}",
            annotation_position="top right",
        )
        # Markera current price
        fig.add_vline(
            x=current_price,
            line_dash="dot",
            line_color="#42a5f5",
            annotation_text=f"Price: {current_price:.2f}",
            annotation_position="top left",
        )
        fig.update_layout(
            template="plotly_dark",
            paper_bgcolor="#131722",
            plot_bgcolor="#1e2230",
            title="Max Pain Curve",
            xaxis_title="Strike",
            yaxis_title="Total Pain ($)",
            height=400,
            margin=dict(t=40, b=16, l=16, r=16),
        )
        return fig
    except Exception as e:
        logger.error("Kunde inte rendera max pain chart: %s", e)
        return None


def max_pain_chart(chain: pd.DataFrame, current_price: float) -> Optional["go.Figure"]:
    """Plotly chart av pain curve.

    Args:
        chain: Optionskedja som DataFrame.
        current_price: Nuvarande pris.

    Returns:
        Plotly Figure eller None.
    """
    mp = calculate_max_pain(chain, current_price)
    pain_df = mp.get("pain_curve", pd.DataFrame())
    mp_strike = mp.get("max_pain_strike")
    if mp_strike is None:
        return None
    return _render_max_pain_chart(pain_df, current_price, mp_strike)


def expected_move(chain: pd.DataFrame, current_price: float) -> Optional[dict]:
    """Beräkna expected move från ATM-optioner.

    Expected move ≈ (ATM call price + ATM put price) / current_price.
    Detta är marknadens förväntade 1-standardavvikelse move till expiration.

    Args:
        chain: Optionskedja (måste ha calls + puts).
        current_price: Nuvarande aktiepris.

    Returns:
        Dict med {'expected_move_pct', 'expected_move_up', 'expected_move_down',
                   'expected_move_amount'} eller None.
    """
    if chain is None or chain.empty or not current_price:
        return None

    try:
        calls, puts = OptionsChain.extract_calls_puts(chain)
        if calls.empty or puts.empty:
            return None

        # Hitta ATM-strike
        strikes = calls["strike"].unique()
        atm_idx = int(np.argmin(np.abs(strikes - current_price)))
        atm_strike = float(strikes[atm_idx])

        # Hämta ATM call och put prices
        atm_call = calls[calls["strike"] == atm_strike]
        atm_put = puts[puts["strike"] == atm_strike]

        if atm_call.empty or atm_put.empty:
            return None

        call_price = float(atm_call["lastPrice"].iloc[0] or 0)
        put_price = float(atm_put["lastPrice"].iloc[0] or 0)

        # Expected move = call + put (approximativ)
        expected_move_amount = call_price + put_price
        expected_move_pct = (expected_move_amount / current_price) * 100

        return {
            "expected_move_pct": round(expected_move_pct, 2),
            "expected_move_amount": round(expected_move_amount, 2),
            "expected_move_up": round(current_price + expected_move_amount, 2),
            "expected_move_down": round(max(current_price - expected_move_amount, 0), 2),
            "call_price": round(call_price, 2),
            "put_price": round(put_price, 2),
            "atm_strike": atm_strike,
        }
    except Exception as e:
        logger.error("Expected move-beräkning misslyckades: %s", e)
        return None


def support_resistance_from_options(chain: pd.DataFrame) -> dict:
    """Hitta support/resistance-nivåer från open interest-koncentration.

    Höga OI-nivåer fungerar ofta som magnet/barriärpriser.

    Args:
        chain: Optionskedja.

    Returns:
        Dict med {'support_levels': [...], 'resistance_levels': [...]}.
    """
    if chain is None or chain.empty:
        return {"support_levels": [], "resistance_levels": []}

    try:
        calls, puts = OptionsChain.extract_calls_puts(chain)
        supports = []
        resistances = []

        if not puts.empty:
            # Put OI-koncentration → support (de vill inte se priset falla under)
            put_oi = puts.groupby("strike")["openInterest"].sum().sort_values(ascending=False)
            for strike, oi in put_oi.head(5).items():
                if oi > 0:
                    supports.append({"strike": float(strike), "oi": int(oi)})

        if not calls.empty:
            # Call OI-koncentration → resistance (de vill inte se priset över)
            call_oi = calls.groupby("strike")["openInterest"].sum().sort_values(ascending=False)
            for strike, oi in call_oi.head(5).items():
                if oi > 0:
                    resistances.append({"strike": float(strike), "oi": int(oi)})

        return {
            "support_levels": sorted(supports, key=lambda x: x["strike"]),
            "resistance_levels": sorted(resistances, key=lambda x: x["strike"]),
        }
    except Exception as e:
        logger.error("Support/resistance från options misslyckades: %s", e)
        return {"support_levels": [], "resistance_levels": []}
