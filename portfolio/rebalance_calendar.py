"""
rebalance_calendar.py -- Portföljrebalanseringsverktyg
======================================================
Hanterar rebalanseringskalender och drift-övervakning:

1. Rebalanseringskalender (månadsvis, kvartalsvis, årligen)
2. Drift-analys: hur mycket har portföljen avvikit från target?
3. Trade-förslag för att återställa balans
4. Skattekostnadsestimat för simulering

Användning:
    from portfolio.rebalance_calendar import RebalanceCalendar
    cal = RebalanceCalendar()
    calendar = cal.generate_calendar(frequency="monthly", start_date="2025-01-01")
"""

import logging
from datetime import datetime, timedelta, date
from typing import Optional, Union

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class RebalanceCalendar:
    """
    Rebalanseringskalender och drift-övervakning.

    Hanterar:
      - Generering av rebalanseringsdatum
      - Drift-mätning (hur mycket vikter avvikit)
      - Triggers för rebalansering
      - Trade-förslag
      - Skattekostnadsestimat
    """

    def __init__(self):
        pass

    # ── Kalendergenerering ─────────────────────────────────────────────────

    @staticmethod
    def generate_calendar(frequency: str = "monthly",
                          start_date: Optional[Union[str, date]] = None,
                          end_date: Optional[Union[str, date]] = None) -> pd.DataFrame:
        """
        Genererar rebalanseringsdatum.

        Args:
            frequency: 'weekly', 'biweekly', 'monthly', 'quarterly', 'semiannual', 'annual'
            start_date: Startdatum (ISO-sträng eller date). Default: idag
            end_date: Slutdatum (ISO-sträng eller date). Default: +1 år

        Returns:
            DataFrame med kolumner [date, frequency, label]
        """
        # Standarddatum
        if start_date is None:
            start_date = date.today()
        elif isinstance(start_date, str):
            start_date = date.fromisoformat(start_date)

        if end_date is None:
            end_date = date(start_date.year + 1, start_date.month, start_date.day)
        elif isinstance(end_date, str):
            end_date = date.fromisoformat(end_date)

        if start_date >= end_date:
            logger.warning("start_date måste vara före end_date")
            return pd.DataFrame(columns=["date", "frequency", "label"])

        # Generera datum baserat på frekvens
        dates = []

        if frequency == "weekly":
            current = start_date
            while current <= end_date:
                # Flytta till nästa måndag
                days_ahead = 0 - current.weekday()
                if days_ahead <= 0:
                    days_ahead += 7
                current += timedelta(days=days_ahead)
                if current <= end_date:
                    dates.append({
                        "date": current,
                        "frequency": frequency,
                        "label": current.strftime("Vecka %W, %Y"),
                    })
                current += timedelta(weeks=1)

        elif frequency == "biweekly":
            current = start_date
            count = 0
            while current <= end_date:
                days_ahead = 0 - current.weekday()
                if days_ahead <= 0:
                    days_ahead += 7
                current += timedelta(days=days_ahead)
                if current <= end_date and count % 2 == 0:
                    dates.append({
                        "date": current,
                        "frequency": frequency,
                        "label": current.strftime("%b %d, %Y"),
                    })
                count += 1
                current += timedelta(weeks=1)

        elif frequency == "monthly":
            current = date(start_date.year, start_date.month, 1)
            while current <= end_date:
                dates.append({
                    "date": current,
                    "frequency": frequency,
                    "label": current.strftime("%B %Y"),
                })
                # Nästa månad
                month = current.month + 1
                year = current.year
                if month > 12:
                    month = 1
                    year += 1
                current = date(year, month, 1)

        elif frequency == "quarterly":
            quarters = [1, 4, 7, 10]  # Jan, Apr, Jul, Okt
            for year in range(start_date.year, end_date.year + 1):
                for q_month in quarters:
                    d = date(year, q_month, 1)
                    if start_date <= d <= end_date:
                        q_num = (q_month // 3) + 1 if q_month > 1 else 1
                        dates.append({
                            "date": d,
                            "frequency": frequency,
                            "label": f"Q{q_num} {year}",
                        })

        elif frequency == "semiannual":
            for year in range(start_date.year, end_date.year + 1):
                for m in [1, 7]:
                    d = date(year, m, 1)
                    if start_date <= d <= end_date:
                        dates.append({
                            "date": d,
                            "frequency": frequency,
                            "label": f"H1 {year}" if m == 1 else f"H2 {year}",
                        })

        elif frequency == "annual":
            for year in range(start_date.year, end_date.year + 1):
                d = date(year, 1, 1)
                if start_date <= d <= end_date:
                    dates.append({
                        "date": d,
                        "frequency": frequency,
                        "label": str(year),
                    })

        else:
            logger.warning(f"Okänd frekvens: {frequency}")
            return pd.DataFrame(columns=["date", "frequency", "label"])

        return pd.DataFrame(dates)

    # ── Drift-analys ───────────────────────────────────────────────────────

    @staticmethod
    def calculate_drift(portfolio: dict,
                        target_weights: dict) -> pd.DataFrame:
        """
        Beräknar drift för varje position i portföljen.

        Drift = current_weight - target_weight
        Positiv drift = överviktad, negativ = underviktad

        Args:
            portfolio: {ticker: current_weight} dict
            target_weights: {ticker: target_weight} dict

        Returns:
            DataFrame med kolumner [ticker, current, target, drift, drift_pct,
            action, urgency]
        """
        if not portfolio or not target_weights:
            return pd.DataFrame(columns=["ticker", "current", "target",
                                          "drift", "drift_pct", "action", "urgency"])

        all_tickers = set(portfolio.keys()) | set(target_weights.keys())

        rows = []
        for ticker in sorted(all_tickers):
            current = portfolio.get(ticker, 0.0)
            target = target_weights.get(ticker, 0.0)
            drift = current - target

            # Relativ drift (i procent av target)
            if target > 0:
                drift_pct = drift / target
            else:
                drift_pct = 0.0 if drift == 0 else float("inf")

            # Action
            if drift > 0.02:
                action = "Minska"
            elif drift < -0.02:
                action = "Öka"
            else:
                action = "Behåll"

            # Urgency
            if abs(drift) > 0.10:
                urgency = "Hög"
            elif abs(drift) > 0.05:
                urgency = "Medel"
            elif abs(drift) > 0.02:
                urgency = "Låg"
            else:
                urgency = "Ingen"

            rows.append({
                "ticker": ticker,
                "current": round(current, 4),
                "target": round(target, 4),
                "drift": round(drift, 4),
                "drift_pct": round(drift_pct, 4),
                "action": action,
                "urgency": urgency,
            })

        return pd.DataFrame(rows)

    # ── Rebalans-kontroll ──────────────────────────────────────────────────

    @staticmethod
    def rebalance_required(drift_df: pd.DataFrame,
                           drift_threshold: float = 0.05) -> dict:
        """
        Avgör om rebalansering behövs baserat på drift.

        Args:
            drift_df: DataFrame från calculate_drift()
            drift_threshold: Tröskel för absolut drift (t.ex. 0.05 = 5%)

        Returns:
            dict med:
                required: True om rebalansering behövs
                n_drifting: Antal positioner med drift > tröskel
                max_drift: Största absoluta driften
                total_drift: Total absolut drift
                recommendations: Kort rekommendation
        """
        if drift_df.empty:
            return {"required": False, "n_drifting": 0,
                    "max_drift": 0.0, "total_drift": 0.0,
                    "recommendations": "Ingen portföljdata"}

        # Räkna positioner med signifikant drift
        drifting = drift_df[drift_df["drift"].abs() > drift_threshold]
        n_drifting = len(drifting)
        max_drift = float(drift_df["drift"].abs().max())
        total_abs_drift = float(drift_df["drift"].abs().sum())

        if n_drifting > 0:
            required = True
            high_urgency = drift_df[drift_df["urgency"] == "Hög"]
            if len(high_urgency) > 0:
                tickers = ", ".join(high_urgency["ticker"].tolist()[:3])
                recommendations = (
                    f"Rebalansering rekommenderas. {n_drifting} position(er) "
                    f"har driftat >{drift_threshold:.0%}. "
                    f"Högsta prioritet: {tickers}"
                )
            else:
                recommendations = (
                    f"{n_drifting} position(er) har driftat >{drift_threshold:.0%}. "
                    f"Rebalansering kan övervägas."
                )
        else:
            required = False
            recommendations = (
                f"Inga positioner har driftat mer än {drift_threshold:.0%}. "
                f"Ingen rebalansering behövs."
            )

        return {
            "required": required,
            "n_drifting": n_drifting,
            "max_drift": round(max_drift, 4),
            "total_drift": round(total_abs_drift, 4),
            "recommendations": recommendations,
        }

    # ── Trade-förslag ──────────────────────────────────────────────────────

    @staticmethod
    def suggest_rebalance_trades(portfolio: dict,
                                  target_weights: dict,
                                  portfolio_value: float = 100000.0,
                                  min_trade_value: float = 1000.0) -> pd.DataFrame:
        """
        Genererar trade-förslag för att återställa balans.

        Args:
            portfolio: {ticker: current_weight}
            target_weights: {ticker: target_weight}
            portfolio_value: Totalt portföljvärde i SEK
            min_trade_value: Minimi trade-belopp (undvik små trades)

        Returns:
            DataFrame med kolumner [ticker, action, value_sek, shares (approx),
            reason]
        """
        if not portfolio or not target_weights:
            return pd.DataFrame(columns=["ticker", "action", "value_sek",
                                          "shares", "reason"])

        all_tickers = set(portfolio.keys()) | set(target_weights.keys())
        trades = []

        for ticker in sorted(all_tickers):
            current = portfolio.get(ticker, 0.0)
            target = target_weights.get(ticker, 0.0)

            drift = current - target
            abs_drift = abs(drift)

            # Ignorera små drifter
            if abs_drift < 0.005:
                continue

            trade_value = abs_drift * portfolio_value

            # Ignorera för små trades
            if trade_value < min_trade_value:
                continue

            if drift > 0:
                action = "Sälj"
                reason = f"Överviktad med {abs_drift:.1%}"
            else:
                action = "Köp"
                reason = f"Underviktad med {abs_drift:.1%}"

            trades.append({
                "ticker": ticker,
                "action": action,
                "value_sek": round(trade_value, 0),
                "current_weight": round(current, 4),
                "target_weight": round(target, 4),
                "drift": round(drift, 4),
                "reason": reason,
            })

        if not trades:
            return pd.DataFrame(columns=["ticker", "action", "value_sek",
                                          "shares", "reason"])

        trade_df = pd.DataFrame(trades)
        trade_df = trade_df.sort_values("value_sek", ascending=False)

        # Beräkna total köp/sälj
        total_buy = trade_df[trade_df["action"] == "Köp"]["value_sek"].sum()
        total_sell = trade_df[trade_df["action"] == "Sälj"]["value_sek"].sum()

        logger.info(f"Trade-förslag: köp {total_buy:,.0f} kr, sälj {total_sell:,.0f} kr")

        return trade_df

    # ── Skattekostnad ──────────────────────────────────────────────────────

    @staticmethod
    def tax_cost_estimate(trades: pd.DataFrame,
                          short_term_rate: float = 0.30,
                          long_term_rate: float = 0.20,
                          short_term_hold_days: int = 365) -> dict:
        """
        Estimerar skattekostnad för föreslagna trades.

        Detta är en förenklad modell för simuleringsändamål.
        Verklig skattekalkylering bör göras av en revisor.

        Args:
            trades: DataFrame från suggest_rebalance_trades()
            short_term_rate: Skattesats för korttidsinnehav (t.ex. 0.30)
            long_term_rate: Skattesats för långtidsinnehav (t.ex. 0.20)
            short_term_hold_days: Gräns för korttidsinnehav i dagar

        Returns:
            dict med:
                estimated_tax: Uppskattad total skattekostnad
                short_term_tax: Skatt på korttidsvinster
                long_term_tax: Skatt på långtidsvinster
                note: Varning om förenkling
        """
        if trades.empty:
            return {"estimated_tax": 0.0, "short_term_tax": 0.0,
                    "long_term_tax": 0.0,
                    "note": "Inga trades att estimera skatt för."}

        # Separera köp och sälj
        sells = trades[trades["action"] == "Sälj"]

        if sells.empty:
            return {"estimated_tax": 0.0, "short_term_tax": 0.0,
                    "long_term_tax": 0.0,
                    "note": "Inga sälj-trades. Skattekostnad uppstår vid realisering."}

        # Förenklad: antag 50% korttidsvinst, 50% långtidsvinst
        # Verklig kalkylering skulle kräva köppris, datum, etc.
        sell_value = sells["value_sek"].sum()

        # Antag 10% vinstmarginal på säljbeloppet
        estimated_gain = sell_value * 0.10

        # Fördelning kort/lång
        short_term_gain = estimated_gain * 0.5
        long_term_gain = estimated_gain * 0.5

        short_tax = short_term_gain * short_term_rate
        long_tax = long_term_gain * long_term_rate
        total_tax = short_tax + long_tax

        return {
            "estimated_tax": round(total_tax, 0),
            "short_term_tax": round(short_tax, 0),
            "long_term_tax": round(long_tax, 0),
            "total_sell_value": round(sell_value, 0),
            "assumed_gain_rate": 0.10,
            "note": (
                "Förenklad estimat för simulering. Antaganden: "
                "10% vinst på sålda positioner, 50/50 kort/lång sikt. "
                "Verklig skatt beror på faktisk vinst och innehavstid."
            ),
        }


# ══════════════════════════════════════════════════════════════════════════════
# CLI-test
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    cal = RebalanceCalendar()

    # Kalender
    monthly = cal.generate_calendar("monthly", "2025-01-01", "2025-12-31")
    print(f"Månatlig kalender: {len(monthly)} datum")
    print(monthly[["date", "label"]].to_string())

    # Drift
    portfolio = {"AAPL": 0.30, "MSFT": 0.25, "GOOGL": 0.25, "AMZN": 0.20}
    target = {"AAPL": 0.25, "MSFT": 0.25, "GOOGL": 0.25, "AMZN": 0.25}
    drift_df = cal.calculate_drift(portfolio, target)
    print("\nDrift-analys:")
    print(drift_df.to_string())

    # Rebalance check
    check = cal.rebalance_required(drift_df)
    print(f"\nRebalans-behov: {check['required']}")
    print(f"Rekommendation: {check['recommendations']}")

    # Trade suggestions
    trades = cal.suggest_rebalance_trades(portfolio, target, portfolio_value=1000000)
    print("\nTrade-förslag:")
    print(trades.to_string() if not trades.empty else "Inga trades")

    # Tax estimate
    if not trades.empty:
        tax = cal.tax_cost_estimate(trades)
        print(f"\nSkatteestimat: {tax['estimated_tax']:,.0f} kr")
