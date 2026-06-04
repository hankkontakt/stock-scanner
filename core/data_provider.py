"""
core/data_provider.py
=====================
DataProvider-abstraktion för MarketScan.
Möjliggör byte av datakälla (yfinance → Polygon.io, IEX Cloud etc.) utan
att ändra resten av systemet.

E1-implementation: Abstrakt interface + YFinanceProvider (default).
Framtida providers: PolygonProvider, IEXProvider, CachingProvider.

Användning:
    from core.data_provider import get_provider
    provider = get_provider()
    history = provider.get_price_history("AAPL", period="1y")
    info = provider.get_info("AAPL")
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


class DataProvider(ABC):
    """Abstrakt interface för datakällor.

    Alla providers måste implementera dessa metoder för att vara
    utbytbara mot varandra utan att övrig kod ändras.
    """

    @abstractmethod
    def get_price_history(self, ticker: str, period: str = "1y",
                          interval: str = "1d") -> pd.DataFrame:
        """Returnerar OHLCV-prishistorik för en aktie.

        Args:
            ticker: Ticker-symbol (t.ex. "AAPL", "VOLV-B.ST")
            period: Historikperiod (t.ex. "1y", "6mo", "3mo")
            interval: Dataintervall ("1d", "1wk", "1mo")

        Returns:
            DataFrame med kolumner [Open, High, Low, Close, Volume]
            Returnerar tom DataFrame vid fel.
        """
        ...

    @abstractmethod
    def get_info(self, ticker: str) -> dict[str, Any]:
        """Returnerar fundamental data för en aktie (P/E, ROE, market cap etc.).

        Returns:
            Dict med nyckeltal. Returnerar {} vid fel.
        """
        ...

    @abstractmethod
    def get_fast_info(self, ticker: str) -> dict[str, Any]:
        """Returnerar snabb marknadsdata (live-pris, currency).

        Returns:
            Dict med minst {"price": float|None, "currency": str|None}.
        """
        ...

    def get_name(self) -> str:
        """Returnerar providernamn (för logging/diagnostik)."""
        return self.__class__.__name__


class YFinanceProvider(DataProvider):
    """DataProvider-implementering baserad på yfinance (default).

    Används för alla datahämtningar i produktion. Är gratis men
    informellt API — kan sluta fungera utan varsel.
    """

    def get_price_history(self, ticker: str, period: str = "1y",
                          interval: str = "1d") -> pd.DataFrame:
        try:
            import yfinance as yf
            t = yf.Ticker(ticker)
            df = t.history(period=period, interval=interval, auto_adjust=True)
            return df if df is not None else pd.DataFrame()
        except Exception as e:
            logger.debug("YFinanceProvider.get_price_history('%s') fel: %s", ticker, e)
            return pd.DataFrame()

    def get_info(self, ticker: str) -> dict[str, Any]:
        try:
            import yfinance as yf
            info = yf.Ticker(ticker).info
            return dict(info) if info else {}
        except Exception as e:
            logger.debug("YFinanceProvider.get_info('%s') fel: %s", ticker, e)
            return {}

    def get_fast_info(self, ticker: str) -> dict[str, Any]:
        try:
            import yfinance as yf
            fi = yf.Ticker(ticker).fast_info
            return {
                "price": float(fi.last_price) if fi.last_price else None,
                "currency": fi.currency or "USD",
                "market_cap": float(fi.market_cap) if fi.market_cap else None,
            }
        except Exception as e:
            logger.debug("YFinanceProvider.get_fast_info('%s') fel: %s", ticker, e)
            return {"price": None, "currency": None}


class CachingProvider(DataProvider):
    """Wrapper som cacchar anrop till en annan provider.

    Minskar antalet API-anrop genom att spara svar i minnet.
    TTL är per metod för att balansera freshness vs. prestanda.
    """

    def __init__(self, inner: DataProvider,
                 price_ttl_s: int = 3600,
                 info_ttl_s: int = 86400):
        self._inner = inner
        self._price_ttl = price_ttl_s
        self._info_ttl = info_ttl_s
        self._cache: dict[str, tuple[float, Any]] = {}

    def _get_cached(self, key: str, ttl: int) -> tuple[bool, Any]:
        import time
        if key in self._cache:
            ts, val = self._cache[key]
            if time.time() - ts < ttl:
                return True, val
        return False, None

    def _set_cached(self, key: str, val: Any) -> None:
        import time
        self._cache[key] = (time.time(), val)

    def get_price_history(self, ticker: str, period: str = "1y",
                          interval: str = "1d") -> pd.DataFrame:
        key = f"price:{ticker}:{period}:{interval}"
        hit, val = self._get_cached(key, self._price_ttl)
        if hit:
            return val
        try:
            result = self._inner.get_price_history(ticker, period, interval)
        except Exception as e:
            logger.debug("CachingProvider.get_price_history('%s') fel: %s", ticker, e)
            return pd.DataFrame()
        self._set_cached(key, result)
        return result

    def get_info(self, ticker: str) -> dict[str, Any]:
        key = f"info:{ticker}"
        hit, val = self._get_cached(key, self._info_ttl)
        if hit:
            return val
        try:
            result = self._inner.get_info(ticker)
        except Exception as e:
            logger.debug("CachingProvider.get_info('%s') fel: %s", ticker, e)
            return {}
        self._set_cached(key, result)
        return result

    def get_fast_info(self, ticker: str) -> dict[str, Any]:
        key = f"fast:{ticker}"
        hit, val = self._get_cached(key, 300)  # 5 min TTL för live-pris
        if hit:
            return val
        result = self._inner.get_fast_info(ticker)
        self._set_cached(key, result)
        return result

    def get_name(self) -> str:
        return f"CachingProvider({self._inner.get_name()})"


# ── Singleton-hantering ──────────────────────────────────────────────────────

_DEFAULT_PROVIDER: DataProvider | None = None


def get_provider() -> DataProvider:
    """Returnerar den aktiva DataProvider-instansen (singleton).

    Respekterar feature flag "data_provider_v2":
    - False (default): YFinanceProvider utan caching
    - True: YFinanceProvider med CachingProvider-wrapper
    """
    global _DEFAULT_PROVIDER
    if _DEFAULT_PROVIDER is None:
        try:
            from core.feature_flags import is_enabled
            if is_enabled("data_provider_v2"):
                _DEFAULT_PROVIDER = CachingProvider(YFinanceProvider())
                logger.debug("DataProvider: CachingProvider(YFinanceProvider) aktiverad")
            else:
                _DEFAULT_PROVIDER = YFinanceProvider()
        except Exception:
            _DEFAULT_PROVIDER = YFinanceProvider()
    return _DEFAULT_PROVIDER


def set_provider(provider: DataProvider) -> None:
    """Ersätter den aktiva DataProvider (för testning/mocking)."""
    global _DEFAULT_PROVIDER
    _DEFAULT_PROVIDER = provider
