"""
core/options_greeks.py — Black-Scholes Greeks Calculator
=========================================================
Beräknar delta, gamma, theta, vega, rho för optioner.
Implied volatility via Newton-Raphson.
Använder scipy.stats.norm för normalfördelning.
"""

import logging
from typing import Optional

import numpy as np
import pandas as pd
from scipy.stats import norm

logger = logging.getLogger(__name__)


def norm_cdf(x: float) -> float:
    """Kumulativ normalfördelning."""
    return float(norm.cdf(x))


def norm_pdf(x: float) -> float:
    """Täthetsfunktion för normalfördelning."""
    return float(norm.pdf(x))


def d1(S: float, K: float, T: float, r: float, sigma: float, q: float = 0) -> float:
    """Beräkna d1 i Black-Scholes-formeln.

    Args:
        S: Aktuellt aktiepris.
        K: Strike price.
        T: Tid till expiration i år.
        r: Riskfri ränta (decimal).
        sigma: Implied volatility (decimal).
        q: Utdelningsyield (decimal), default 0.

    Returns:
        d1-värdet.
    """
    if T <= 0 or sigma <= 0:
        return 0.0
    return float((np.log(S / K) + (r - q + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T)))


def d2(d1_val: float, sigma: float, T: float) -> float:
    """Beräkna d2 från d1.

    Args:
        d1_val: d1-värdet.
        sigma: Implied volatility (decimal).
        T: Tid till expiration i år.

    Returns:
        d2-värdet.
    """
    return float(d1_val - sigma * np.sqrt(T))


def calculate_greeks(
    option_type: str,
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    q: float = 0,
) -> dict:
    """Beräkna alla Greeks för en option via Black-Scholes.

    Args:
        option_type: 'call' eller 'put'.
        S: Aktuellt aktiepris.
        K: Strike price.
        T: Tid till expiration i år (t.ex. 30/365).
        r: Riskfri ränta (decimal, t.ex. 0.05 för 5%).
        sigma: Implied volatility (decimal, t.ex. 0.30 för 30%).
        q: Utdelningsyield (decimal), default 0.

    Returns:
        Dict med {'delta', 'gamma', 'theta', 'vega', 'rho'}.
        Vid ogiltiga parametrar returneras None-värden.
    """
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        g = {"delta": None, "gamma": None, "theta": None, "vega": None, "rho": None}
        return g

    try:
        d1_val = d1(S, K, T, r, sigma, q)
        d2_val = d2(d1_val, sigma, T)

        is_call = option_type.lower() == "call"

        # Delta
        if is_call:
            delta = norm_cdf(d1_val)
        else:
            delta = norm_cdf(d1_val) - 1

        # Gamma (samma för call och put)
        gamma = norm_pdf(d1_val) / (S * sigma * np.sqrt(T))

        # Theta (per dag, därav /365)
        theta_part1 = -(S * norm_pdf(d1_val) * sigma) / (2 * np.sqrt(T))
        if is_call:
            theta = (theta_part1 - r * K * np.exp(-r * T) * norm_cdf(d2_val) + q * S * np.exp(-q * T) * norm_cdf(d1_val)) / 365
        else:
            theta = (theta_part1 + r * K * np.exp(-r * T) * norm_cdf(-d2_val) - q * S * np.exp(-q * T) * norm_cdf(-d1_val)) / 365

        # Vega (per 1% IV-ändring, därav /100)
        vega = (S * norm_pdf(d1_val) * np.sqrt(T)) / 100

        # Rho (per 1% ränteändring, därav /100)
        if is_call:
            rho = (K * T * np.exp(-r * T) * norm_cdf(d2_val)) / 100
        else:
            rho = (-K * T * np.exp(-r * T) * norm_cdf(-d2_val)) / 100

        return {
            "delta": round(float(delta), 4),
            "gamma": round(float(gamma), 4),
            "theta": round(float(theta), 6),
            "vega": round(float(vega), 4),
            "rho": round(float(rho), 4),
        }
    except Exception as e:
        logger.error("Greeks-beräkning misslyckades: %s", e)
        return {"delta": None, "gamma": None, "theta": None, "vega": None, "rho": None}


def implied_volatility(
    price: float,
    S: float,
    K: float,
    T: float,
    r: float,
    option_type: str,
    q: float = 0,
    max_iter: int = 100,
    tol: float = 1e-6,
) -> Optional[float]:
    """Beräkna implied volatility via Newton-Raphson.

    Args:
        price: Marknadspris på optionen.
        S: Aktuellt aktiepris.
        K: Strike price.
        T: Tid till expiration i år.
        r: Riskfri ränta.
        option_type: 'call' eller 'put'.
        q: Utdelningsyield.
        max_iter: Maximalt antal iterationer.
        tol: Tolerans för konvergens.

    Returns:
        Implied volatility som decimal, eller None om konvergens misslyckas.
    """
    if T <= 0 or price <= 0:
        return None

    # Black-Scholes prissättning
    def _bs_price(sig: float) -> float:
        d1_val = d1(S, K, T, r, sig, q)
        d2_val = d2(d1_val, sig, T)
        if option_type.lower() == "call":
            return float(S * np.exp(-q * T) * norm_cdf(d1_val) - K * np.exp(-r * T) * norm_cdf(d2_val))
        else:
            return float(K * np.exp(-r * T) * norm_cdf(-d2_val) - S * np.exp(-q * T) * norm_cdf(-d1_val))

    # Vega (derivata m.a.p. sigma)
    def _vega(sig: float) -> float:
        d1_val = d1(S, K, T, r, sig, q)
        return float(S * norm_pdf(d1_val) * np.sqrt(T))

    sigma_est = 0.3  # Startgissning: 30% IV
    for _ in range(max_iter):
        try:
            v = _vega(sigma_est)
            if abs(v) < 1e-12:
                break
            diff = _bs_price(sigma_est) - price
            sigma_est -= diff / v
            if abs(diff) < tol:
                return round(max(float(sigma_est), 0.001), 4)
            # Håll sigma inom rimliga gränser
            sigma_est = max(0.001, min(2.0, sigma_est))
        except Exception:
            return None

    logger.warning("IV konvergerade inte för (S=%.2f, K=%.2f, pris=%.2f)", S, K, price)
    return None if sigma_est <= 0 else round(float(sigma_est), 4)


def greek_sensitivities(ticker: str, greek: str = "delta") -> Optional[pd.DataFrame]:
    """Beräkna ett visst Greek för alla optioner i kedjan.

    Args:
        ticker: Aktiens ticker.
        greek: Vilket Greek som ska beräknas ('delta', 'gamma', 'theta', 'vega', 'rho').

    Returns:
        DataFrame med strike, option_type och det valda Greek-värdet.
    """
    from core.options_chain import OptionsChain

    try:
        chain = OptionsChain.fetch_chain(ticker)
        if chain is None or chain.empty:
            return None

        # Hämta current price
        yf_ticker = __import__("yfinance", fromlist=["Ticker"]).Ticker(ticker)
        info = yf_ticker.info or {}
        S = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose")
        if S is None:
            logger.warning("Kunde inte hämta pris för %s", ticker)
            return None
        S = float(S)

        r = 0.05  # Riskfri ränta (approximativ)
        rows = []
        for _, row in chain.iterrows():
            K = float(row["strike"])
            # Beräkna T från expiration
            exp_str = str(row.get("expiration", ""))
            try:
                exp_date = pd.to_datetime(exp_str)
                T = max((exp_date - pd.Timestamp.now()).days / 365.0, 0.01)
            except Exception:
                T = 0.5  # fallback ~6 mån

            # Försök använd impliedVolatility från yfinance, annars 0.3
            iv = float(row.get("impliedVolatility", 0.3) or 0.3)
            opt_type = str(row.get("option_type", "call"))

            g = calculate_greeks(opt_type, S, K, T, r, iv)
            val = g.get(greek)
            rows.append({
                "strike": K,
                "option_type": opt_type,
                greek: val,
                "iv": iv,
            })

        result = pd.DataFrame(rows)
        return result
    except Exception as e:
        logger.error("Greek-sensitivity för %s misslyckades: %s", ticker, e)
        return None
