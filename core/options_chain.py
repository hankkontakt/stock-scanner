"""
core/options_chain.py — Options Chain Fetcher
==============================================
Hämtar optionskedjor via yfinance med caching (1h TTL).
Separera calls/puts, hitta ATM strike.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

import yfinance as yf
import pandas as pd

from core.cache_utils import read_cache, write_cache

logger = logging.getLogger(__name__)

# Cache-TTL: 1 timme för optionsdata (snabb föränderlig)
_CACHE_TTL_HOURS = 1.0


class OptionsChain:
    """Hämtar och cachar optionskedjor för en given ticker."""

    @staticmethod
    def fetch_chain(ticker: str, expiration: Optional[str] = None) -> Optional[pd.DataFrame]:
        """Hämta optionskedja via yfinance.

        Args:
            ticker: Aktiens ticker (t.ex. 'AAPL').
            expiration: Specifikt utgångsdatum 'YYYY-MM-DD'. Om None, hämtas
                        närmsta tillgängliga.

        Returns:
            DataFrame med optionskedja eller None vid fel.
        """
        cache_key = f"options_chain_{ticker}_{expiration or 'front'}"
        cached = read_cache(cache_key, ttl_hours=_CACHE_TTL_HOURS)
        if cached is not None:
            return cached

        try:
            yf_ticker = yf.Ticker(ticker)
            if expiration:
                chain = yf_ticker.option_chain(expiration)
            else:
                exps = yf_ticker.options
                if not exps:
                    logger.warning("Inga optioner funna för %s", ticker)
                    return None
                chain = yf_ticker.option_chain(exps[0])

            # Kombinera calls + puts med en 'option_type'-kolumn
            calls = chain.calls.copy()
            puts = chain.puts.copy()
            if calls.empty and puts.empty:
                logger.warning("Tom optionskedja för %s", ticker)
                return None

            if not calls.empty:
                calls["option_type"] = "call"
            if not puts.empty:
                puts["option_type"] = "put"

            result = pd.concat([calls, puts], ignore_index=True)
            result["ticker"] = ticker
            result["fetch_time"] = datetime.now()

            write_cache(cache_key, result)
            return result

        except Exception as e:
            logger.error("Kunde inte hämta optionskedja för %s: %s", ticker, e)
            return None

    @staticmethod
    def fetch_all_expirations(ticker: str) -> list:
        """Hämta alla tillgängliga expiration dates.

        Args:
            ticker: Aktiens ticker.

        Returns:
            Lista med datumsträngar 'YYYY-MM-DD' sorterade stigande.
        """
        cache_key = f"options_expirations_{ticker}"
        cached = read_cache(cache_key, ttl_hours=_CACHE_TTL_HOURS)
        if cached is not None:
            return cached

        try:
            yf_ticker = yf.Ticker(ticker)
            exps = list(yf_ticker.options)
            write_cache(cache_key, exps)
            return exps
        except Exception as e:
            logger.error("Kunde inte hämta expiration dates för %s: %s", ticker, e)
            return []

    @staticmethod
    def get_atm_strike(ticker: str, current_price: float) -> Optional[float]:
        """Hitta ATM strike (närmast aktuellt pris).

        Args:
            ticker: Aktiens ticker.
            current_price: Nuvarande aktiepris.

        Returns:
            ATM-strike eller None.
        """
        try:
            exps = OptionsChain.fetch_all_expirations(ticker)
            if not exps:
                return None
            chain = OptionsChain.fetch_chain(ticker, exps[0])
            if chain is None or chain.empty:
                return None
            strikes = chain["strike"].unique()
            if len(strikes) == 0:
                return None
            return float(strikes[(strikes - current_price).abs().argmin()])
        except Exception as e:
            logger.error("Kunde inte hitta ATM strike för %s: %s", ticker, e)
            return None

    @staticmethod
    def extract_calls_puts(chain: pd.DataFrame) -> tuple:
        """Separera calls och puts från en optionskedja.

        Args:
            chain: DataFrame med optionskedja (måste ha 'option_type'-kolumn).

        Returns:
            (calls_df, puts_df) som DataFrames.
        """
        if chain is None or chain.empty:
            return pd.DataFrame(), pd.DataFrame()

        if "option_type" in chain.columns:
            calls = chain[chain["option_type"] == "call"].copy()
            puts = chain[chain["option_type"] == "put"].copy()
        else:
            # Försök detektera via kolumnnamn (yfinance rådata)
            calls = chain.copy()
            puts = pd.DataFrame()
            logger.warning("optionskedja saknar 'option_type' — returnerar allt som calls")
        return calls, puts
