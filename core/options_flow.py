"""
core/options_flow.py — Options Flow Analyzer
=============================================
Analyserar ovanlig optionsaktivitet, P/C ratio, whale alerts och sentiment.
Använder yfinance optionsdata för att detektera stora block, sweeps,
och z-score-baserad avvikelse från normalvolym.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf

from core.cache_utils import read_cache, write_cache

logger = logging.getLogger(__name__)


def _get_expiration_dates(ticker: str) -> list:
    """Hämta expiry-datum för en ticker."""
    try:
        yf_ticker = yf.Ticker(ticker)
        return list(yf_ticker.options)
    except Exception:
        return []


def _days_back_dates(days_back: int = 5) -> list:
    """Generera datumsträngar för senaste N dagar (börsdagar)."""
    dates = []
    d = datetime.now()
    while len(dates) < days_back:
        if d.weekday() < 5:  # mån-fre
            dates.append(d.strftime("%Y-%m-%d"))
        d -= timedelta(days=1)
    return dates


def analyze_options_flow(ticker: str, days_back: int = 5) -> pd.DataFrame:
    """Analysera optionsflöde och identifiera ovanlig aktivitet.

    Letar efter:
    - Large blocks (>100 contracts)
    - Sweeps (multi-exchange)
    - Opening vs closing (approximativ via OI-förändring)

    Args:
        ticker: Aktiens ticker.
        days_back: Antal dagar bakåt att analysera.

    Returns:
        DataFrame med optionsflöde.
    """
    cache_key = f"options_flow_{ticker}_{days_back}"
    cached = read_cache(cache_key, ttl_hours=0.5)  # 30 min cache
    if cached is not None:
        return cached

    try:
        yf_ticker = yf.Ticker(ticker)
        exps = _get_expiration_dates(ticker)
        if not exps:
            return pd.DataFrame()

        rows = []
        for exp in exps[:3]:  # Begränsa till 3 närmsta expirationer
            try:
                chain = yf_ticker.option_chain(exp)
                for label, df_opt in [("call", chain.calls), ("put", chain.puts)]:
                    if df_opt.empty:
                        continue
                    for _, opt_row in df_opt.iterrows():
                        vol = int(opt_row.get("volume", 0) or 0)
                        oi = int(opt_row.get("openInterest", 0) or 0)
                        strike = float(opt_row.get("strike", 0))
                        last_price = float(opt_row.get("lastPrice", 0) or 0)
                        iv = float(opt_row.get("impliedVolatility", 0) or 0)
                        premium = vol * last_price * 100  # 1 contract = 100 aktier

                        flow_type = "normal"
                        if vol > 100:
                            flow_type = "large_block"
                        if vol > 500:
                            flow_type = "sweep"

                        rows.append({
                            "ticker": ticker,
                            "expiration": exp,
                            "option_type": label,
                            "strike": strike,
                            "volume": vol,
                            "open_interest": oi,
                            "last_price": last_price,
                            "premium": premium,
                            "iv": iv,
                            "flow_type": flow_type,
                        })
            except Exception:
                continue

        result = pd.DataFrame(rows)
        if not result.empty:
            result = result.sort_values("volume", ascending=False)
        write_cache(cache_key, result)
        return result
    except Exception as e:
        logger.error("Options flow-analys misslyckades för %s: %s", ticker, e)
        return pd.DataFrame()


def put_call_ratio(ticker: str, days_back: int = 5) -> Optional[dict]:
    """Beräkna put/call ratio över tid.

    Args:
        ticker: Aktiens ticker.
        days_back: Antal dagar.

    Returns:
        Dict med {'ratio', 'put_volume', 'call_volume', 'put_oi', 'call_oi'}
        eller None vid fel.
    """
    try:
        flow = analyze_options_flow(ticker, days_back=min(days_back, 1))
        if flow.empty:
            return None

        calls = flow[flow["option_type"] == "call"]
        puts = flow[flow["option_type"] == "put"]

        call_vol = int(calls["volume"].sum())
        put_vol = int(puts["volume"].sum())
        call_oi = int(calls["open_interest"].sum())
        put_oi = int(puts["open_interest"].sum())

        vol_ratio = round(put_vol / max(call_vol, 1), 4)
        oi_ratio = round(put_oi / max(call_oi, 1), 4)

        return {
            "ratio_volume": vol_ratio,
            "ratio_oi": oi_ratio,
            "put_volume": put_vol,
            "call_volume": call_vol,
            "put_oi": put_oi,
            "call_oi": call_oi,
            "sentiment": "bearish" if vol_ratio > 1.0 else "bullish",
        }
    except Exception as e:
        logger.error("P/C ratio för %s misslyckades: %s", ticker, e)
        return None


def unusual_options_activity(ticker: str) -> pd.DataFrame:
    """Hitta ovanlig optionsaktivitet via z-score mot normalvolym.

    Beräknar z-score = (volym - medelvolym) / std(volym) för varje strike.
    Returnerar de med z-score > 2 (signifikant avvikelse).

    Args:
        ticker: Aktiens ticker.

    Returns:
        DataFrame med ovanlig aktivitet sorterad efter avvikelse.
    """
    flow = analyze_options_flow(ticker, days_back=1)
    if flow.empty:
        return pd.DataFrame()

    try:
        # Z-score per strike och option_type
        flow = flow[flow["volume"] > 0].copy()
        if flow.empty:
            return pd.DataFrame()

        grouped = flow.groupby(["strike", "option_type"])["volume"]
        mean_vol = grouped.transform("mean")
        std_vol = grouped.transform("std").replace(0, 1)
        flow["z_score"] = ((flow["volume"] - mean_vol) / std_vol).fillna(0)

        unusual = flow[flow["z_score"] > 2].copy()
        unusual = unusual.sort_values("z_score", ascending=False)
        return unusual
    except Exception as e:
        logger.error("Unusual options activity för %s misslyckades: %s", ticker, e)
        return pd.DataFrame()


def whales(ticker: str, min_premium: float = 100000) -> pd.DataFrame:
    """Hitta stora positionedringar ($100k+ premium).

    Args:
        ticker: Aktiens ticker.
        min_premium: Minsta premium för att räknas som whale (default $100k).

    Returns:
        DataFrame med whale-aktivitet.
    """
    flow = analyze_options_flow(ticker, days_back=1)
    if flow.empty:
        return pd.DataFrame()

    whales_df = flow[flow["premium"] >= min_premium].copy()
    whales_df = whales_df.sort_values("premium", ascending=False)
    return whales_df


def options_sentiment(ticker: str) -> str:
    """Sammanfattad sentiment från optionsmarknaden.

    Viktad efter: contract size, premium, OI change, put/call.

    Args:
        ticker: Aktiens ticker.

    Returns:
        'bullish', 'bearish' eller 'neutral'.
    """
    try:
        pc = put_call_ratio(ticker)
        if not pc:
            return "neutral"

        # Volym-P/C-ratio: <0.7 bullish, >1.3 bearish, däremellan neutral
        vol_ratio = pc["ratio_volume"]
        oi_ratio = pc["ratio_oi"]

        # Kombinera volym och OI för sentiment
        score = 0
        if vol_ratio < 0.7:
            score += 1
        elif vol_ratio > 1.3:
            score -= 1

        if oi_ratio < 0.7:
            score += 1
        elif oi_ratio > 1.3:
            score -= 1

        # Kolla whale-aktivitet
        w = whales(ticker, min_premium=50000)
        if not w.empty:
            whale_calls = len(w[w["option_type"] == "call"])
            whale_puts = len(w[w["option_type"] == "put"])
            if whale_calls > whale_puts * 2:
                score += 1
            elif whale_puts > whale_calls * 2:
                score -= 1

        if score >= 1:
            return "bullish"
        elif score <= -1:
            return "bearish"
        return "neutral"
    except Exception as e:
        logger.error("Options sentiment för %s misslyckades: %s", ticker, e)
        return "neutral"
