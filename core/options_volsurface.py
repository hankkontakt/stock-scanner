"""
core/options_volsurface.py — IV Surface & Volatility Smile
===========================================================
Bygger IV-surface över strikes och expirationer,
visar volatility smile, skew, och term structure.
Beräknar IV-percentil mot historik.
"""

import logging
from datetime import datetime, timedelta
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
from core.options_greeks import implied_volatility
from core.cache_utils import read_cache, write_cache

logger = logging.getLogger(__name__)


class VolatilitySurface:
    """Bygger och analyserar IV-surface för en ticker."""

    @staticmethod
    def build_surface(ticker: str) -> Optional[pd.DataFrame]:
        """Bygg IV-surface: IV för olika strikes och expirationer.

        Args:
            ticker: Aktiens ticker.

        Returns:
            DataFrame med kolumner [strike, expiration, iv, option_type, days_to_expiry]
            eller None vid fel.
        """
        cache_key = f"vol_surface_{ticker}"
        cached = read_cache(cache_key, ttl_hours=1)
        if cached is not None:
            return cached

        try:
            yf_ticker = yf.Ticker(ticker)
            exps = list(yf_ticker.options)
            if not exps:
                logger.warning("Inga expirationer funna för %s", ticker)
                return None

            rows = []
            # Begränsa till max 10 expirationer och ~20 strikes per expiry för prestanda
            exps = exps[:10]

            for exp in exps:
                try:
                    chain = yf_ticker.option_chain(exp)
                    exp_date = pd.to_datetime(exp)
                    dte = max((exp_date - pd.Timestamp.now()).days, 0)

                    for label, df_opt in [("call", chain.calls), ("put", chain.puts)]:
                        if df_opt.empty:
                            continue
                        # Ta varannan strike för att hålla datamängden hanterbar
                        sample = df_opt.iloc[::2] if len(df_opt) > 20 else df_opt
                        for _, row in sample.iterrows():
                            iv = float(row.get("impliedVolatility", 0) or 0)
                            if iv > 0:
                                rows.append({
                                    "strike": float(row["strike"]),
                                    "expiration": exp,
                                    "iv": round(iv * 100, 2),  # procent
                                    "option_type": label,
                                    "days_to_expiry": dte,
                                })
                except Exception:
                    continue

            if not rows:
                return None

            result = pd.DataFrame(rows)
            write_cache(cache_key, result)
            return result
        except Exception as e:
            logger.error("IV-surface bygge misslyckades för %s: %s", ticker, e)
            return None

    @staticmethod
    def plot_surface(surface: pd.DataFrame) -> Optional["go.Figure"]:
        """Skapa 3D Plotly surface chart av IV.

        Args:
            surface: DataFrame från build_surface.

        Returns:
            Plotly Figure eller None.
        """
        if not _PLOTLY_AVAILABLE or surface is None or surface.empty:
            return None

        try:
            # Pivota till 2D-grid för 3D-plot
            pivot = surface.pivot_table(
                values="iv",
                index="days_to_expiry",
                columns="strike",
                aggfunc="mean",
            ).fillna(method="ffill").fillna(method="bfill")

            if pivot.empty:
                return None

            x = pivot.columns.values  # strikes
            y = pivot.index.values    # days to expiry
            z = pivot.values

            fig = go.Figure(data=[go.Surface(
                x=x, y=y, z=z,
                colorscale="Viridis",
                colorbar=dict(title="IV %"),
            )])
            fig.update_layout(
                template="plotly_dark",
                paper_bgcolor="#131722",
                scene=dict(
                    xaxis_title="Strike",
                    yaxis_title="Days to Expiry",
                    zaxis_title="IV (%)",
                    bgcolor="#1e2230",
                ),
                title="IV Surface",
                height=500,
                margin=dict(t=40, b=16, l=16, r=16),
            )
            return fig
        except Exception as e:
            logger.error("3D surface plot misslyckades: %s", e)
            return None

    @staticmethod
    def volatility_smile(ticker: str, expiration: Optional[str] = None) -> Optional["go.Figure"]:
        """Skapa volatility smile chart för en given expiration.

        Args:
            ticker: Aktiens ticker.
            expiration: 'YYYY-MM-DD'. Om None, används front-month.

        Returns:
            Plotly Figure eller None.
        """
        if not _PLOTLY_AVAILABLE:
            return None

        try:
            yf_ticker = yf.Ticker(ticker)
            if not expiration:
                exps = list(yf_ticker.options)
                if not exps:
                    return None
                expiration = exps[0]

            chain = yf_ticker.option_chain(expiration)
            if chain.calls.empty and chain.puts.empty:
                return None

            fig = go.Figure()

            if not chain.calls.empty:
                fig.add_trace(go.Scatter(
                    x=chain.calls["strike"],
                    y=chain.calls["impliedVolatility"] * 100,
                    mode="lines+markers",
                    name="Calls",
                    line=dict(color="#4caf50", width=2),
                ))
            if not chain.puts.empty:
                fig.add_trace(go.Scatter(
                    x=chain.puts["strike"],
                    y=chain.puts["impliedVolatility"] * 100,
                    mode="lines+markers",
                    name="Puts",
                    line=dict(color="#ef5350", width=2),
                ))

            fig.update_layout(
                template="plotly_dark",
                paper_bgcolor="#131722",
                plot_bgcolor="#1e2230",
                title=f"Volatility Smile — {ticker} ({expiration})",
                xaxis_title="Strike",
                yaxis_title="Implied Volatility (%)",
                height=400,
                margin=dict(t=40, b=16, l=16, r=16),
                legend=dict(orientation="h", y=1.1, x=0.5, xanchor="center"),
            )
            return fig
        except Exception as e:
            logger.error("Volatility smile misslyckades för %s: %s", ticker, e)
            return None

    @staticmethod
    def skew(ticker: str, days: int = 30) -> Optional[dict]:
        """Beräkna 25-delta put/call skew (risk reversal).

        Skew = IV(25-delta put) - IV(25-delta call).
        Positiv skew = puts dyrare = rädsla (bearish).
        Negativ skew = calls dyrare = greed (bullish).

        Args:
            ticker: Aktiens ticker.
            days: Ungefärligt DTE (hittar närmsta expiration).

        Returns:
            Dict med {'skew', 'put_iv', 'call_iv', 'expiration'} eller None.
        """
        try:
            yf_ticker = yf.Ticker(ticker)
            exps = list(yf_ticker.options)
            if not exps:
                return None

            # Hitta expiration närmast 'days' DTE
            target_date = datetime.now() + timedelta(days=days)
            closest_exp = min(exps, key=lambda e: abs(
                (pd.to_datetime(e) - pd.Timestamp(target_date)).days
            ))

            chain = yf_ticker.option_chain(closest_exp)
            if chain.calls.empty or chain.puts.empty:
                return None

            # Approximera 25-delta: ta IV vid ~25:e percentilen av strike-range
            put_iv_25 = float(chain.puts["impliedVolatility"].quantile(0.25) or 0) * 100
            call_iv_25 = float(chain.calls["impliedVolatility"].quantile(0.25) or 0) * 100
            skew_val = round(put_iv_25 - call_iv_25, 2)

            return {
                "skew": skew_val,
                "put_iv_25": round(put_iv_25, 2),
                "call_iv_25": round(call_iv_25, 2),
                "expiration": closest_exp,
            }
        except Exception as e:
            logger.error("Skew-beräkning misslyckades för %s: %s", ticker, e)
            return None

    @staticmethod
    def term_structure(ticker: str) -> Optional["go.Figure"]:
        """Skapa term structure chart (IV per expiration).

        Visar contango (stigande IV) eller backwardation (fallande IV).

        Args:
            ticker: Aktiens ticker.

        Returns:
            Plotly Figure eller None.
        """
        if not _PLOTLY_AVAILABLE:
            return None

        try:
            surface = VolatilitySurface.build_surface(ticker)
            if surface is None or surface.empty:
                return None

            # Genomsnittlig IV per expiration
            term = surface.groupby(["expiration", "days_to_expiry"]).agg(
                avg_iv=("iv", "mean"),
                call_iv=("iv", lambda x: x[surface.loc[x.index, "option_type"] == "call"].mean()),
                put_iv=("iv", lambda x: x[surface.loc[x.index, "option_type"] == "put"].mean()),
            ).reset_index().sort_values("days_to_expiry")

            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=term["days_to_expiry"],
                y=term["avg_iv"],
                mode="lines+markers",
                name="Avg IV",
                line=dict(color="#42a5f5", width=2),
            ))
            fig.add_trace(go.Scatter(
                x=term["days_to_expiry"],
                y=term["call_iv"],
                mode="lines",
                name="Call IV",
                line=dict(color="#4caf50", width=1, dash="dash"),
            ))
            fig.add_trace(go.Scatter(
                x=term["days_to_expiry"],
                y=term["put_iv"],
                mode="lines",
                name="Put IV",
                line=dict(color="#ef5350", width=1, dash="dash"),
            ))

            is_contango = (
                term["avg_iv"].iloc[-1] > term["avg_iv"].iloc[0]
                if len(term) > 1 else True
            )
            fig.update_layout(
                template="plotly_dark",
                paper_bgcolor="#131722",
                plot_bgcolor="#1e2230",
                title=f"Term Structure — {'Contango' if is_contango else 'Backwardation'}",
                xaxis_title="Days to Expiry",
                yaxis_title="IV (%)",
                height=400,
                margin=dict(t=40, b=16, l=16, r=16),
                legend=dict(orientation="h", y=1.1, x=0.5, xanchor="center"),
            )
            return fig
        except Exception as e:
            logger.error("Term structure misslyckades för %s: %s", ticker, e)
            return None

    @staticmethod
    def iv_percentile(ticker: str, days_back: int = 252) -> Optional[dict]:
        """Beräkna current IV-percentil vs historik.

        Args:
            ticker: Aktiens ticker.
            days_back: Antal dagars historik (default 252 = 1 år).

        Returns:
            Dict med {'current_iv', 'min_iv', 'max_iv', 'median_iv', 'percentile',
                       'iv_rank'} eller None.
        """
        try:
            # Hämta historisk data för IV-approximation
            yf_ticker = yf.Ticker(ticker)
            hist = yf_ticker.history(period=f"{days_back}d")
            if hist.empty:
                return None

            # Approximera historisk IV via daily range
            hist = hist.copy()
            hist["daily_return"] = hist["Close"].pct_change()
            hist_vol = hist["daily_return"].std() * np.sqrt(252) * 100  # annualiserad

            # Nuvarande IV från front-month ATM
            exps = list(yf_ticker.options)
            if not exps:
                return None

            chain = yf_ticker.option_chain(exps[0])
            S = float(hist["Close"].iloc[-1])
            if chain.calls.empty:
                return None

            strikes = chain.calls["strike"].values
            atm_idx = int(np.argmin(np.abs(strikes - S)))
            current_iv = float(chain.calls["impliedVolatility"].iloc[atm_idx] or 0) * 100

            # Approximera historisk IV-range (använd historisk vol som proxy)
            # I verkligheten skulle vi hämta historisk IV-data från en dataleverantör
            min_iv = hist_vol * 0.5
            max_iv = hist_vol * 2.0
            median_iv = hist_vol

            # Beräkna percentil
            if max_iv > min_iv:
                percentile = min(max((current_iv - min_iv) / (max_iv - min_iv) * 100, 0), 100)
            else:
                percentile = 50.0

            return {
                "current_iv": round(current_iv, 2),
                "min_iv": round(min_iv, 2),
                "max_iv": round(max_iv, 2),
                "median_iv": round(median_iv, 2),
                "percentile": round(percentile, 1),
                "iv_rank": "HOG" if percentile > 80 else "LAG" if percentile < 20 else "MEDEL",
            }
        except Exception as e:
            logger.error("IV-percentil för %s misslyckades: %s", ticker, e)
            return None
