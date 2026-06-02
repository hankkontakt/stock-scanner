"""
core/options_earnings.py — Earnings Play Analyzer
=================================================
Analyserar optionsmarknadens förväntan inför earnings.
Beräknar expected move, straddle cost, historical moves,
och ger play-recommendation.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf

from core.options_chain import OptionsChain
from core.options_maxpain import expected_move
from core.options_volsurface import VolatilitySurface
from core.cache_utils import read_cache, write_cache

logger = logging.getLogger(__name__)


def _find_earnings_expiration(ticker: str, earnings_date: str) -> Optional[str]:
    """Hitta närmsta optionsexpiration efter earnings.

    Args:
        ticker: Aktiens ticker.
        earnings_date: Earnings-datum 'YYYY-MM-DD'.

    Returns:
        Expiration date 'YYYY-MM-DD' eller None.
    """
    try:
        yf_ticker = yf.Ticker(ticker)
        exps = list(yf_ticker.options)
        if not exps:
            return None
        earnings_dt = pd.to_datetime(earnings_date)
        # Hitta första expirationen efter earnings (eller samma vecka)
        for exp in exps:
            exp_dt = pd.to_datetime(exp)
            if exp_dt >= earnings_dt:
                return exp
        return exps[0]  # fallback
    except Exception:
        return None


def analyze_earnings_play(ticker: str, earnings_date: str) -> dict:
    """Analysera optionsmarknadens förväntan inför earnings.

    Args:
        ticker: Aktiens ticker.
        earnings_date: Earnings-datum 'YYYY-MM-DD'.

    Returns:
        Dict med analysdata.
    """
    try:
        exp = _find_earnings_expiration(ticker, earnings_date)
        if not exp:
            return {"error": "Ingen optionsexpiration funnen efter earnings-datumet."}

        yf_ticker = yf.Ticker(ticker)
        info = yf_ticker.info or {}
        S = float(info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose", 0))

        chain = yf_ticker.option_chain(exp)

        # Expected move från ATM-optioner
        move = _expected_move_from_chain(chain, S)

        # Straddle cost
        straddle = _calculate_straddle_cost(chain, S)

        # Break-even range
        be = break_even_range(straddle.get("straddle_price", 0), S) if straddle.get("straddle_price") else {}

        # Historical moves
        hist = historical_earnings_moves(ticker, n=8)

        # IV percentile
        ivp = VolatilitySurface.iv_percentile(ticker)

        result = {
            "ticker": ticker,
            "earnings_date": earnings_date,
            "expiration": exp,
            "current_price": S,
            "expected_move": move,
            "straddle": straddle,
            "break_even": be,
            "historical_moves": hist,
            "iv_percentile": ivp,
        }

        # Play recommendation
        result["recommendation"] = play_recommendation(
            move.get("expected_move_pct", 0) if move else 0,
            straddle.get("straddle_price", 0) if straddle else 0,
            S,
            ivp.get("percentile", 50) if ivp else 50,
        )

        return result
    except Exception as e:
        logger.error("Earnings play-analys för %s misslyckades: %s", ticker, e)
        return {"error": str(e)}


def expected_move_from_options(ticker: str, earnings_date: str) -> Optional[dict]:
    """IV-baserad expected move inför earnings.

    Args:
        ticker: Aktiens ticker.
        earnings_date: Earnings-datum.

    Returns:
        Dict med expected move-data eller None.
    """
    try:
        exp = _find_earnings_expiration(ticker, earnings_date)
        if not exp:
            return None
        yf_ticker = yf.Ticker(ticker)
        info = yf_ticker.info or {}
        S = float(info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose", 0))
        chain = yf_ticker.option_chain(exp)
        return _expected_move_from_chain(chain, S)
    except Exception as e:
        logger.error("Expected move från options misslyckades: %s", e)
        return None


def _expected_move_from_chain(chain, S: float) -> Optional[dict]:
    """Beräkna expected move från en optionskedja (privat hjälpfunktion)."""
    try:
        if chain.calls.empty or chain.puts.empty:
            return None
        strikes = chain.calls["strike"].values
        atm_idx = int(np.argmin(np.abs(strikes - S)))
        atm_strike = float(strikes[atm_idx])

        atm_call = chain.calls[chain.calls["strike"] == atm_strike]
        atm_put = chain.puts[chain.puts["strike"] == atm_strike]

        if atm_call.empty or atm_put.empty:
            return None

        call_price = float(atm_call["lastPrice"].iloc[0] or 0)
        put_price = float(atm_put["lastPrice"].iloc[0] or 0)
        move_amount = call_price + put_price

        return {
            "expected_move_pct": round(move_amount / S * 100, 2),
            "expected_move_amount": round(move_amount, 2),
            "expected_move_up": round(S + move_amount, 2),
            "expected_move_down": round(max(S - move_amount, 0), 2),
            "atm_strike": atm_strike,
            "call_price": round(call_price, 2),
            "put_price": round(put_price, 2),
        }
    except Exception as e:
        logger.error("_expected_move_from_chain misslyckades: %s", e)
        return None


def historical_earnings_moves(ticker: str, n: int = 8) -> list:
    """Hämta historiska earnings moves.

    Args:
        ticker: Aktiens ticker.
        n: Antal senaste earnings att undersöka.

    Returns:
        Lista med dicts {'date', 'move_pct', 'close_before', 'close_after'}.
    """
    try:
        yf_ticker = yf.Ticker(ticker)

        # Försök hämta earnings-dates från yfinance
        earnings = yf_ticker.earnings_dates
        if earnings is None or earnings.empty:
            return []

        earnings = earnings.head(n)
        hist = yf_ticker.history(period="6mo")

        results = []
        for idx in earnings.index:
            try:
                ed = pd.Timestamp(idx)
                # Pris dagen före earnings
                before = hist[hist.index < ed]
                if before.empty:
                    continue
                close_before = float(before["Close"].iloc[-1])

                # Pris dagen efter earnings
                after = hist[hist.index > ed]
                if after.empty:
                    continue
                close_after = float(after["Close"].iloc[0])

                move_pct = round((close_after - close_before) / close_before * 100, 2)
                results.append({
                    "date": ed.strftime("%Y-%m-%d"),
                    "move_pct": move_pct,
                    "close_before": round(close_before, 2),
                    "close_after": round(close_after, 2),
                })
            except Exception:
                continue

        return results
    except Exception as e:
        logger.error("Historiska earnings moves för %s misslyckades: %s", ticker, e)
        return []


def straddle_cost(ticker: str, earnings_date: str) -> Optional[dict]:
    """Beräkna kostnad för ATM straddle inför earnings.

    Args:
        ticker: Aktiens ticker.
        earnings_date: Earnings-datum.

    Returns:
        Dict med straddle-data eller None.
    """
    try:
        exp = _find_earnings_expiration(ticker, earnings_date)
        if not exp:
            return None
        yf_ticker = yf.Ticker(ticker)
        info = yf_ticker.info or {}
        S = float(info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose", 0))
        chain = yf_ticker.option_chain(exp)
        return _calculate_straddle_cost(chain, S)
    except Exception as e:
        logger.error("Straddle cost misslyckades: %s", e)
        return None


def _calculate_straddle_cost(chain, S: float) -> dict:
    """Beräkna ATM straddle-kostnad (privat hjälpfunktion)."""
    try:
        if chain.calls.empty or chain.puts.empty:
            return {"straddle_price": None, "straddle_pct": None}

        strikes = chain.calls["strike"].values
        atm_idx = int(np.argmin(np.abs(strikes - S)))
        atm_strike = float(strikes[atm_idx])

        atm_call = chain.calls[chain.calls["strike"] == atm_strike]
        atm_put = chain.puts[chain.puts["strike"] == atm_strike]

        if atm_call.empty or atm_put.empty:
            return {"straddle_price": None, "straddle_pct": None}

        call_price = float(atm_call["lastPrice"].iloc[0] or 0)
        put_price = float(atm_put["lastPrice"].iloc[0] or 0)
        straddle = call_price + put_price

        return {
            "straddle_price": round(straddle, 2),
            "straddle_pct": round(straddle / S * 100, 2),
            "call_price": round(call_price, 2),
            "put_price": round(put_price, 2),
            "atm_strike": atm_strike,
        }
    except Exception as e:
        logger.error("_calculate_straddle_cost misslyckades: %s", e)
        return {"straddle_price": None, "straddle_pct": None}


def break_even_range(straddle_price: float, current_price: float) -> dict:
    """Beräkna break-even range för en straddle.

    Args:
        straddle_price: Priset på straddlen (call + put).
        current_price: Nuvarande aktiepris.

    Returns:
        Dict med {'lower', 'upper', 'range_pct'}.
    """
    if not straddle_price or not current_price:
        return {"lower": None, "upper": None, "range_pct": None}

    lower = current_price - straddle_price
    upper = current_price + straddle_price
    range_pct = round((upper - lower) / current_price * 100, 2)

    return {
        "lower": round(lower, 2),
        "upper": round(upper, 2),
        "range_pct": range_pct,
    }


def play_recommendation(
    expected_move_pct: float,
    straddle_price: float,
    current_price: float,
    iv_percentile: float = 50,
    expected_move_amount: Optional[float] = None,
) -> dict:
    """Rekommendera earnings play-strategi.

    Regler:
    - Köp straddle om expected move > straddle cost * 1.3
    - Sälj strangle om IV är extremt hög (IV percentile > 80)
    - Neutral om ingen tydlig edge

    Args:
        expected_move_pct: Förväntad rörelse i procent.
        straddle_price: Priset på ATM straddle.
        current_price: Nuvarande aktiepris.
        iv_percentile: IV percentil (0-100).
        expected_move_amount: Expected move i dollar (optional).

    Returns:
        Dict med {'action', 'reason', 'edge_pct', 'confidence'}.
    """
    try:
        # Köp straddle: expected move > straddle cost * 1.3
        straddle_pct = (straddle_price / current_price * 100) if current_price and straddle_price else 0
        edge = round(expected_move_pct - straddle_pct * 1.3, 2)

        if edge > 0 and expected_move_pct > 0:
            return {
                "action": "KOP STRADDLE",
                "reason": (
                    f"Förväntad rörelse ({expected_move_pct}%) är "
                    f"{'större' if edge > 0 else 'mindre'} än 1.3x straddle-kostnad "
                    f"({straddle_pct * 1.3:.1f}%). Edge: {edge}%."
                ),
                "edge_pct": edge,
                "confidence": "HOG" if edge > 2 else "MEDEL",
            }

        # Sälj strangle om IV är extremt hög
        if iv_percentile > 80:
            return {
                "action": "SALJ STRANGLE / ICKE-DIRECTIONAL",
                "reason": (
                    f"IV är på {iv_percentile:.0f} percentilen — extremt hög. "
                    "Premium-säljande strategier (strangle, iron condor) har hög sannolikhet att lyckas."
                ),
                "edge_pct": round(straddle_pct * 0.3, 2),
                "confidence": "HOG",
            }

        # Neutral
        return {
            "action": "AVSTA / VAKTA",
            "reason": (
                f"Ingen tydlig edge. Expected move: {expected_move_pct}%, "
                f"Straddle kostar {straddle_pct:.1f}%, IV på {iv_percentile:.0f} percentilen."
            ),
            "edge_pct": edge,
            "confidence": "LAG",
        }
    except Exception as e:
        logger.error("Play recommendation misslyckades: %s", e)
        return {"action": "OKAND", "reason": str(e), "edge_pct": 0, "confidence": "LAG"}
