"""
dividend_calendar.py
====================
Hämtar kommande utdelningar för en lista av tickers via yfinance.
Används i portföljvyn för att varna användaren om snart kommande utbetalningar.
"""

from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf


def get_upcoming_dividends(tickers: list, days_ahead: int = 60) -> pd.DataFrame:
    """
    Returnerar en DataFrame med förväntade kommande utdelningar.

    Logik:
    - Hämtar utdelningshistorik per ticker
    - Estimerar nästa utdelningsdatum baserat på historisk frekvens
    - Filtrerar på datum inom `days_ahead` dagar

    Returnerar kolumner:
      ticker, name, next_div_date, amount, yield_pct, frequency, days_until
    """
    today = datetime.now().date()
    cutoff = today + timedelta(days=days_ahead)
    rows = []

    for ticker in tickers:
        try:
            t = yf.Ticker(ticker)
            divs = t.dividends
            if divs is None or divs.empty:
                continue

            # Normalisera index till date
            div_dates = divs.index
            if hasattr(div_dates[0], "date"):
                div_dates = [d.date() for d in div_dates]
            else:
                div_dates = [d for d in div_dates]

            divs_indexed = list(zip(div_dates, divs.values))
            if not divs_indexed:
                continue

            last_date, last_amount = divs_indexed[-1]

            # Estimera frekvens baserat på senaste 2 utdelningar
            if len(divs_indexed) >= 2:
                prev_date = divs_indexed[-2][0]
                gap_days = (last_date - prev_date).days
                if gap_days < 50:
                    frequency = "Månadsvis"
                    period_days = 30
                elif gap_days < 100:
                    frequency = "Kvartalsvis"
                    period_days = 91
                elif gap_days < 200:
                    frequency = "Halvårsvis"
                    period_days = 182
                else:
                    frequency = "Årlig"
                    period_days = 365
            else:
                frequency = "Årlig"
                period_days = 365

            # Nästa förväntade datum
            next_date = last_date + timedelta(days=period_days)

            # Om senaste utdelning var ny tillbaka justerar vi framåt
            while next_date < today:
                next_date += timedelta(days=period_days)

            if next_date > cutoff:
                continue

            days_until = (next_date - today).days

            # Yield baserat på senaste pris
            try:
                fi = t.fast_info
                current_price = getattr(fi, "last_price", None)
                annual_div = last_amount * (365 / period_days)
                yld = (annual_div / current_price * 100) if current_price else None
            except Exception:
                yld = None

            # Bolagsnamn
            try:
                name = (t.info or {}).get("shortName", ticker)
            except Exception:
                name = ticker

            rows.append({
                "ticker":      ticker,
                "name":        name,
                "next_div":    next_date.strftime("%Y-%m-%d"),
                "amount":      round(float(last_amount), 4),
                "yield_pct":   round(yld, 2) if yld else None,
                "frequency":   frequency,
                "days_until":  days_until,
            })

        except Exception:
            continue

    if not rows:
        return pd.DataFrame(columns=["ticker", "name", "next_div", "amount",
                                     "yield_pct", "frequency", "days_until"])

    df = pd.DataFrame(rows).sort_values("days_until").reset_index(drop=True)
    return df
