"""
core/options_strategies.py — Optionsstrategier
===============================================
Analys av Covered Call, Wheel Strategy, Protective Put,
Bull Put Spread och Bear Call Spread.
"""

import logging
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf

from core.options_greeks import calculate_greeks
from core.options_chain import OptionsChain
from core.cache_utils import read_cache, write_cache

logger = logging.getLogger(__name__)

_RISK_FREE_RATE = 0.05  # Approximativ riskfri ränta


class CoveredCallStrategy:
    """Covered Call — sälj call mot befintligt aktieinnehav."""

    @staticmethod
    def analyze(portfolio_holding: dict) -> dict:
        """Rekommendera Covered Call för ett portföljinnehav.

        Args:
            portfolio_holding: Dict med {'ticker', 'shares', 'avg_price', 'current_price'}.

        Returns:
            Dict med rekommendationer.
        """
        ticker = portfolio_holding.get("ticker", "")
        shares = int(portfolio_holding.get("shares", 0))
        avg_price = float(portfolio_holding.get("avg_price", 0))
        current_price = float(portfolio_holding.get("current_price", 0))

        if not ticker or shares <= 0 or current_price <= 0:
            return {"error": "Ogiltigt innehav.", "recommendations": []}

        try:
            chain = OptionsChain.fetch_chain(ticker)
            if chain is None or chain.empty:
                return {"error": "Kunde inte hämta optionskedja.", "recommendations": []}

            calls, _ = OptionsChain.extract_calls_puts(chain)
            if calls.empty:
                return {"error": "Inga calls tillgängliga.", "recommendations": []}

            exps = OptionsChain.fetch_all_expirations(ticker)
            if not exps:
                return {"error": "Inga expirationer.", "recommendations": []}

            # Fokusera på närmsta 2-3 expirationer
            recommendations = []
            for exp in exps[:3]:
                exp_calls = calls[calls.get("expiration", "") == exp].copy()
                if exp_calls.empty:
                    continue

                # Välj OTM strikes (20-30% över current price för yield)
                otm_calls = exp_calls[exp_calls["strike"] > current_price * 1.02].copy()
                if otm_calls.empty:
                    continue

                # Beräkna yield för varje strike
                for _, row in otm_calls.head(5).iterrows():
                    strike = float(row["strike"])
                    premium = float(row.get("lastPrice", 0) or 0)
                    if premium <= 0:
                        continue

                    yield_pct = round(premium / current_price * 100, 2)
                    delta = float(row.get("impliedVolatility", 0.3) or 0.3)
                    prob_assign = CoveredCallStrategy.probability_of_assignment(delta)

                    exp_date = pd.to_datetime(exp)
                    dte = max((exp_date - pd.Timestamp.now()).days, 1)

                    recommendations.append({
                        "strike": strike,
                        "expiration": exp,
                        "days_to_expiry": dte,
                        "premium_per_share": round(premium, 2),
                        "total_premium": round(premium * 100 * min(shares, 100), 2),
                        "yield_pct": yield_pct,
                        "annualized_yield": round(yield_pct / dte * 365, 2),
                        "delta_approx": round(delta, 3),
                        "prob_assignment_pct": round(prob_assign * 100, 1),
                        "max_profit": round((strike - current_price + premium) * 100, 2),
                        "breakeven": round(current_price - premium, 2),
                    })

            recommendations = sorted(recommendations, key=lambda r: r["annualized_yield"], reverse=True)

            return {
                "ticker": ticker,
                "shares": shares,
                "current_price": current_price,
                "cost_basis": avg_price,
                "unrealized_pnl": round((current_price - avg_price) * shares, 2),
                "recommendations": recommendations,
            }
        except Exception as e:
            logger.error("Covered Call-analys för %s misslyckades: %s", ticker, e)
            return {"error": str(e), "recommendations": []}

    @staticmethod
    def yield_enhancement(option_price: float, stock_value: float) -> float:
        """Beräkna yield enhancement från Covered Call.

        Args:
            option_price: Pris per aktie för optionen.
            stock_value: Aktievärde per aktie.

        Returns:
            Yield i procent.
        """
        if stock_value <= 0:
            return 0.0
        return round(option_price / stock_value * 100, 2)

    @staticmethod
    def probability_of_assignment(delta: float) -> float:
        """Approximera sannolikhet för assignment.

        Delta är en approximation av sannolikheten att optionen
        är ITM vid expiration.

        Args:
            delta: Optionens delta.

        Returns:
            Sannolikhet (0-1).
        """
        # För covered call: vi säljer call, så risk = delta (ITM-sannolikhet)
        return min(max(abs(float(delta)), 0), 1)


class WheelStrategy:
    """Wheel Strategy — CSP på support, CC på resistance."""

    @staticmethod
    def analyze(ticker: str) -> dict:
        """Analysera Wheel Strategy för en ticker.

        Steg 1: Sälj cash-secured put (CSP) på supportnivå.
        Steg 2: Om assigned, sälj covered call (CC) på resistance.

        Args:
            ticker: Aktiens ticker.

        Returns:
            Dict med CSP- och CC-rekommendationer.
        """
        try:
            chain = OptionsChain.fetch_chain(ticker)
            if chain is None or chain.empty:
                return {"error": "Ingen optionsdata."}

            yf_ticker = yf.Ticker(ticker)
            info = yf_ticker.info or {}
            S = float(info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose", 0))

            calls, puts = OptionsChain.extract_calls_puts(chain)
            exps = OptionsChain.fetch_all_expirations(ticker)
            if not exps:
                return {"error": "Inga expirationer."}

            # Hitta support/resistance från OI-koncentration
            from core.options_maxpain import support_resistance_from_options
            sr = support_resistance_from_options(chain)
            supports = [s["strike"] for s in sr.get("support_levels", [])]
            resistances = [r["strike"] for r in sr.get("resistance_levels", [])]

            # Om inga OI-nivåer, använd tekniska nivåer
            hist = yf_ticker.history(period="6mo")
            if not supports and not hist.empty:
                supports = [float(hist["Close"].rolling(50).mean().iloc[-1] or S * 0.95)]
            if not resistances and not hist.empty:
                resistances = [float(hist["Close"].rolling(50).mean().iloc[-1] or S * 1.05)]

            # CSP-analys (sälj put ~5-10% under price)
            csp_results = []
            if not puts.empty:
                for exp in exps[:2]:
                    exp_puts = puts[puts.get("expiration", "") == exp]
                    if exp_puts.empty:
                        continue
                    # Välj OTM puts (5-10% under current price)
                    otm_puts = exp_puts[
                        (exp_puts["strike"] >= S * 0.85) &
                        (exp_puts["strike"] <= S * 0.98)
                    ].copy()
                    for _, row in otm_puts.head(3).iterrows():
                        strike = float(row["strike"])
                        premium = float(row.get("lastPrice", 0) or 0)
                        if premium <= 0:
                            continue
                        exp_date = pd.to_datetime(exp)
                        dte = max((exp_date - pd.Timestamp.now()).days, 1)
                        annualized = WheelStrategy.calculate_annualized_return(
                            strike, premium, dte
                        )
                        csp_results.append({
                            "type": "CSP",
                            "strike": strike,
                            "expiration": exp,
                            "premium": round(premium, 2),
                            "credit": round(premium * 100, 2),
                            "days_to_expiry": dte,
                            "annualized_return": annualized,
                            "breakeven": round(strike - premium, 2),
                        })

            # CC-analys (sälj call ~5-10% över price)
            cc_results = []
            if not calls.empty:
                for exp in exps[:2]:
                    exp_calls = calls[calls.get("expiration", "") == exp]
                    if exp_calls.empty:
                        continue
                    # Välj OTM calls (5-10% över current price)
                    otm_calls = exp_calls[
                        (exp_calls["strike"] >= S * 1.02) &
                        (exp_calls["strike"] <= S * 1.15)
                    ].copy()
                    for _, row in otm_calls.head(3).iterrows():
                        strike = float(row["strike"])
                        premium = float(row.get("lastPrice", 0) or 0)
                        if premium <= 0:
                            continue
                        exp_date = pd.to_datetime(exp)
                        dte = max((exp_date - pd.Timestamp.now()).days, 1)
                        annualized = WheelStrategy.calculate_annualized_return(
                            S, premium, dte  # använd stock price istället för strike
                        )
                        cc_results.append({
                            "type": "CC",
                            "strike": strike,
                            "expiration": exp,
                            "premium": round(premium, 2),
                            "credit": round(premium * 100, 2),
                            "days_to_expiry": dte,
                            "annualized_return": annualized,
                            "breakeven": round(S - premium, 2),
                        })

            return {
                "ticker": ticker,
                "current_price": S,
                "support_levels": supports[:3],
                "resistance_levels": resistances[:3],
                "cash_secured_puts": csp_results,
                "covered_calls": cc_results,
            }
        except Exception as e:
            logger.error("Wheel strategy-analys för %s misslyckades: %s", ticker, e)
            return {"error": str(e)}

    @staticmethod
    def calculate_annualized_return(strike: float, premium: float, days_to_expiry: int) -> float:
        """Beräkna annualiserad return för CSP/CC.

        För CSP: return = premium / strike * (365 / dte)
        För CC: return = premium / stock_price * (365 / dte)

        Args:
            strike: Strike price (eller aktiepris för CC).
            premium: Mottagen premie.
            days_to_expiry: Dagar till expiration.

        Returns:
            Annualiserad return i procent.
        """
        if strike <= 0 or days_to_expiry <= 0:
            return 0.0
        return round(premium / strike * (365 / days_to_expiry) * 100, 2)


class ProtectivePutAnalysis:
    """Protective Put — köp put som försäkring för aktieinnehav."""

    @staticmethod
    def analyze(portfolio_holding: dict, protection_level: float = 0.95) -> dict:
        """Analysera kostnad för protective put (portfolio insurance).

        Args:
            portfolio_holding: Dict med {'ticker', 'shares', 'current_price'}.
            protection_level: Hur mycket skydd (0.95 = 95% av värdet).

        Returns:
            Dict med analysdata.
        """
        ticker = portfolio_holding.get("ticker", "")
        shares = int(portfolio_holding.get("shares", 0))
        current_price = float(portfolio_holding.get("current_price", 0))

        if not ticker or shares <= 0 or current_price <= 0:
            return {"error": "Ogiltigt innehav."}

        try:
            chain = OptionsChain.fetch_chain(ticker)
            if chain is None or chain.empty:
                return {"error": "Ingen optionsdata."}

            _, puts = OptionsChain.extract_calls_puts(chain)
            if puts.empty:
                return {"error": "Inga puts tillgängliga."}

            exps = OptionsChain.fetch_all_expirations(ticker)
            if not exps:
                return {"error": "Inga expirationer."}

            # Hitta put med strike ~ protection_level * current_price
            target_strike = current_price * protection_level
            results = []

            for exp in exps[:3]:
                exp_puts = puts[puts.get("expiration", "") == exp].copy()
                if exp_puts.empty:
                    continue

                # Hitta put med strike närmast target
                exp_puts["strike_diff"] = (exp_puts["strike"] - target_strike).abs()
                best = exp_puts.loc[exp_puts["strike_diff"].idxmin()]

                strike = float(best["strike"])
                premium = float(best.get("lastPrice", 0) or 0)
                if premium <= 0:
                    continue

                exp_date = pd.to_datetime(exp)
                dte = max((exp_date - pd.Timestamp.now()).days, 1)
                total_cost = premium * 100 * shares
                portfolio_value = current_price * shares
                cost_pct = round(total_cost / portfolio_value * 100, 2)

                results.append({
                    "strike": strike,
                    "expiration": exp,
                    "days_to_expiry": dte,
                    "premium_per_share": round(premium, 2),
                    "total_cost": round(total_cost, 2),
                    "portfolio_value": round(portfolio_value, 2),
                    "cost_pct": cost_pct,
                    "protection_price": round(strike, 2),
                    "max_loss_capped": round((current_price - strike) * shares + total_cost, 2),
                })

            results = sorted(results, key=lambda r: r["cost_pct"])

            return {
                "ticker": ticker,
                "shares": shares,
                "current_price": current_price,
                "portfolio_value": round(current_price * shares, 2),
                "protection_level": protection_level,
                "options": results,
            }
        except Exception as e:
            logger.error("Protective Put-analys för %s misslyckades: %s", ticker, e)
            return {"error": str(e)}


def _vertical_spread_analysis(
    ticker: str,
    spread_type: str,
    buy_strike: float,
    sell_strike: float,
    expiration: str,
) -> dict:
    """Analysera en vertical spread (privat hjälpfunktion).

    Args:
        ticker: Aktiens ticker.
        spread_type: 'bull_put' eller 'bear_call'.
        buy_strike: Strike för den köpta optionen.
        sell_strike: Strike för den sålda optionen.
        expiration: Expiration date 'YYYY-MM-DD'.

    Returns:
        Dict med analysdata.
    """
    try:
        yf_ticker = yf.Ticker(ticker)
        chain = yf_ticker.option_chain(expiration)

        if spread_type == "bull_put":
            buy = chain.puts[chain.puts["strike"] == buy_strike]
            sell = chain.puts[chain.puts["strike"] == sell_strike]
        else:  # bear_call
            buy = chain.calls[chain.calls["strike"] == buy_strike]
            sell = chain.calls[chain.calls["strike"] == sell_strike]

        if buy.empty or sell.empty:
            return {"error": "Kunde inte hitta strikes."}

        buy_price = float(buy["lastPrice"].iloc[0] or 0)
        sell_price = float(sell["lastPrice"].iloc[0] or 0)

        # Bull put spread: credit = sell - buy
        if spread_type == "bull_put":
            net_credit = sell_price - buy_price
            width = abs(sell_strike - buy_strike)
            max_profit = net_credit * 100
            max_loss = (width - net_credit) * 100
            breakeven = sell_strike - net_credit
        else:  # bear call spread
            net_credit = sell_price - buy_price
            width = abs(buy_strike - sell_strike)
            max_profit = net_credit * 100
            max_loss = (width - net_credit) * 100
            breakeven = sell_strike + net_credit

        exp_date = pd.to_datetime(expiration)
        dte = max((exp_date - pd.Timestamp.now()).days, 1)

        # Probability of profit: approximativ
        if max_loss > 0:
            risk_reward = round(max_profit / max_loss, 2)
        else:
            risk_reward = 0

        pop = round(max_profit / (max_profit + abs(max_loss)) * 100 if max_loss > 0 else 50, 1)
        annualized_return = round(
            (max_profit / max(abs(max_loss), 1)) / dte * 365 * 100, 2
        ) if max_loss != 0 else 0

        return {
            "type": spread_type,
            "ticker": ticker,
            "expiration": expiration,
            "days_to_expiry": dte,
            "buy_strike": buy_strike,
            "sell_strike": sell_strike,
            "buy_price": round(buy_price, 2),
            "sell_price": round(sell_price, 2),
            "net_credit": round(net_credit, 2),
            "max_profit": round(max_profit, 2),
            "max_loss": round(max_loss, 2),
            "breakeven": round(breakeven, 2),
            "risk_reward": risk_reward,
            "probability_of_profit": pop,
            "annualized_return": annualized_return,
        }
    except Exception as e:
        logger.error("Vertical spread-analys misslyckades: %s", e)
        return {"error": str(e)}


class BullPutSpread:
    """Bull Put Spread — sälj put, köp lägre put (credit spread)."""

    @staticmethod
    def analyze(ticker: str, expiration: str, short_strike: float, long_strike: float) -> dict:
        """Analysera Bull Put Spread.

        Args:
            ticker: Aktiens ticker.
            expiration: Expiration date.
            short_strike: Strike för såld put (högre).
            long_strike: Strike för köpt put (lägre).

        Returns:
            Dict med analysdata.
        """
        return _vertical_spread_analysis(ticker, "bull_put", long_strike, short_strike, expiration)


class BearCallSpread:
    """Bear Call Spread — sälj call, köp högre call (credit spread)."""

    @staticmethod
    def analyze(ticker: str, expiration: str, short_strike: float, long_strike: float) -> dict:
        """Analysera Bear Call Spread.

        Args:
            ticker: Aktiens ticker.
            expiration: Expiration date.
            short_strike: Strike för såld call (lägre).
            long_strike: Strike för köpt call (högre).

        Returns:
            Dict med analysdata.
        """
        return _vertical_spread_analysis(ticker, "bear_call", long_strike, short_strike, expiration)
