"""
news_alerts.py – Realtidslarm för portfölj, watchlist & topp-10
================================================================
Körs var 30:e minut via GitHub Actions. Kollar Finnhub (gratis)
för nyheter om dina innehav, bevakningar och dagens topp-10-aktier.

Vid relevant nyhet eller >5% kursrörelse → mail via email_template.
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, date
from pathlib import Path

import pandas as pd

# Projektrot
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import config
from core.email_template import send_email
from core import ai_analysis

DATA_DIR = ROOT / "data"
REPORT_DIR = ROOT / "reports"

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(message)s")


# ── Hjälpfunktioner ──────────────────────────────────────────────────────────

def _load_portfolio() -> dict:
    """Ladda portfölj och returnera {ticker: shares}."""
    path = DATA_DIR / "holdings.csv"
    if not path.exists():
        return {}
    try:
        df = pd.read_csv(path)
        df["ticker"] = df["ticker"].str.upper().str.strip()
        return dict(zip(df["ticker"], df.get("shares", [0] * len(df))))
    except Exception:
        return {}


def _load_watchlist() -> list:
    """Ladda watchlist och returnera lista med tickers."""
    path = DATA_DIR / "watchlist.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [i.get("ticker", "").upper().strip() for i in data if i.get("ticker")]
    except Exception:
        return []


def _load_top_tickers(n: int = 10) -> list:
    """Ladda de N bästa tickers från senaste scored_universe."""
    files = sorted(REPORT_DIR.glob("scored_universe_*.csv"), reverse=True)
    if not files:
        return []
    try:
        df = pd.read_csv(files[0], low_memory=False)
        df.columns = df.columns.str.strip()
        if "score_total" in df.columns and "ticker" in df.columns:
            return df.nlargest(n, "score_total")["ticker"].tolist()
        return df["ticker"].head(n).tolist() if "ticker" in df.columns else []
    except Exception:
        return []


def _fetch_news(ticker: str, max_items: int = 3) -> list:
    """
    Hämta nyheter för en ticker via Finnhub.
    Returnerar lista med dict: {headline, summary, source, url, datetime}
    """
    api_key = os.getenv("FINNHUB_API_KEY", "")
    if not api_key:
        return []

    try:
        import requests
        url = f"https://finnhub.io/api/v1/company-news"
        params = {
            "symbol": ticker,
            "from": date.today().strftime("%Y-%m-%d"),
            "to": date.today().strftime("%Y-%m-%d"),
            "token": api_key,
        }
        resp = requests.get(url, params=params, timeout=15)
        if resp.status_code != 200:
            return []

        articles = resp.json()
        if not isinstance(articles, list):
            return []

        result = []
        for article in articles[:max_items]:
            headline = article.get("headline", "").strip()
            summary = article.get("summary", "").strip()
            if not headline:
                continue
            result.append({
                "headline": headline[:200],
                "summary": summary[:300] if summary else "",
                "source": article.get("source", "Finnhub"),
                "url": article.get("url", ""),
                "datetime": article.get("datetime", ""),
            })
        return result
    except Exception:
        return []


def _check_price_move(ticker: str, threshold: float = 5.0) -> dict | None:
    """
    Kolla om en ticker har rört sig mer än threshold% idag.
    Använder yfinance för dagens pris vs gårdagens stängning.
    """
    try:
        import yfinance as yf
        hist = yf.Ticker(ticker).history(period="2d")
        if len(hist) < 2:
            return None
        prev_close = hist["Close"].iloc[-2]
        current = hist["Close"].iloc[-1]
        change = ((current / prev_close) - 1) * 100

        if abs(change) >= threshold:
            return {
                "ticker": ticker,
                "change_pct": round(change, 2),
                "current_price": round(current, 2),
                "direction": "upp" if change > 0 else "ned",
            }
    except Exception:
        pass
    return None


NEWS_ALERT_SYSTEM_PROMPT = """Du är en personlig portföljrådgivare som analyserar en nyhet.

Nyheten gäller en aktie som personen äger eller bevakar. Bedöm:

1. Är denna nyhet viktig för personen? (JA/NEJ)
2. Om JA: på en skala 1-5, hur viktig?
3. Förklara kort vad nyheten betyder för deras portfölj
4. Rekommendera åtgärd (om någon)

Skriv på svenska, max 300 ord. Använd emojis. Var konkret."""


# ══════════════════════════════════════════════════════════════════════════════
# HUVUDFUNKTION
# ══════════════════════════════════════════════════════════════════════════════

def check_alerts(debug: bool = False) -> list:
    """
    Huvudfunktion: kolla alla relevanta tickers för nyheter och prisrörelser.

    Args:
        debug: Om True, logga utan att skicka mail

    Returns:
        Lista med alert-dicts som triggades
    """
    start = time.time()
    date_str = date.today().strftime("%Y-%m-%d")
    logger.info(f"\n{'='*50}")
    logger.info(f"🚨 News Alerts – {date_str}")
    logger.info(f"{'='*50}\n")

    # Samla alla tickers att bevaka
    portfolio = _load_portfolio()
    watchlist = _load_watchlist()
    top_tickers = _load_top_tickers(10)

    all_tickers = set()
    all_tickers.update(portfolio.keys())  # Innehav (viktigast)
    all_tickers.update(watchlist)         # Bevakningar
    all_tickers.update(top_tickers)       # Dagens topp-10

    # Exkludera index
    index_suffixes = (".SS", ".SSE", ".SZ")
    tickers_to_check = [t for t in all_tickers if t and not t.startswith("^") and not t.endswith(index_suffixes)]

    logger.info(f"  👁️ Bevakar {len(tickers_to_check)} tickers:")
    logger.info(f"     Portfölj: {len(portfolio)}, Watchlist: {len(watchlist)}, Topp-10: {len(top_tickers)}")

    alerts = []

    for ticker in tickers_to_check:
        # 1. Kolla nyheter via Finnhub
        news = _fetch_news(ticker, max_items=2)
        for article in news:
            headline = article.get("headline", "")
            source = article.get("source", "")
            logger.info(f"  📰 {ticker}: {headline[:80]}...")

            # AI-bedömning
            alert = _evaluate_alert(ticker, headline, article, portfolio, debug)
            if alert:
                alerts.append(alert)

        # 2. Kolla prisrörelse >5%
        price_alert = _check_price_move(ticker, threshold=5.0)
        if price_alert:
            direction = price_alert["direction"]
            change = price_alert["change_pct"]
            logger.info(f"  📈 {ticker}: {direction} {change:+.1f}%")

            # AI-förklaring av rörelsen
            alert = _evaluate_price_move(ticker, price_alert, debug)
            if alert:
                alerts.append(alert)

        # Vänta lite mellan anropen för att inte rate-limit Finnhub
        time.sleep(1.5)

    # Skicka mail om det finns alerts
    if alerts and not debug:
        _send_alert_email(alerts)

    elapsed = time.time() - start
    logger.info(f"\n✅ Klart! {len(alerts)} alerts på {elapsed:.0f}s")

    return alerts


def _evaluate_alert(ticker: str, headline: str, article: dict,
                    portfolio: dict, debug: bool = False) -> dict | None:
    """AI-värdering av en nyhet. Returnerar alert-dict om viktig."""
    is_holding = "🟢 INNEHAV" if ticker in portfolio else "⭐ BEVAKAD"

    try:
        ctx = json.dumps({
            "ticker": ticker,
            "headline": headline[:200],
            "status": is_holding,
            "in_portfolio": ticker in portfolio,
        }, ensure_ascii=False)

        # Använd AI för att bedöma relevans
        result = ai_analysis.ai_chat(
            f"Analysera denna nyhet för {ticker}: {headline}",
            context=ctx,
            provider="auto",
            depth="Snabb",
        )

        # Kort svar = ingen viktig nyhet
        if not result or len(result) < 50:
            return None

        return {
            "type": "news",
            "ticker": ticker,
            "headline": headline,
            "status": is_holding,
            "source": article.get("source", ""),
            "ai_analysis": result[:500],
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.debug(f"  ⚠ AI-bedömning misslyckades: {e}")
        # Fallback: om AI inte fungerar, skicka ändå vid intressant rubrik
        important_keywords = ["vinstvarning", "vinst", "förvärv", "fusion", "börsintroduktion",
                              "konkurs", "uppköp", "nya besked", "FDA", "myndighetsbeslut",
                              "prospekt", "företrädesemission", "split"]
        if any(kw in headline.lower() for kw in important_keywords):
            return {
                "type": "news",
                "ticker": ticker,
                "headline": headline,
                "status": is_holding,
                "source": article.get("source", ""),
                "ai_analysis": f"⚠️ Automatisk alert: rubriken innehåller nyckelord som kan vara viktiga.",
                "timestamp": datetime.now().isoformat(),
            }
    return None


def _evaluate_price_move(ticker: str, price_alert: dict,
                          debug: bool = False) -> dict | None:
    """AI-förklaring av prisrörelse."""
    try:
        ctx = json.dumps(price_alert, ensure_ascii=False)
        result = ai_analysis.ai_chat(
            f"Förklara varför {ticker} rörde sig {price_alert['change_pct']:+.1f}% idag.",
            context=ctx,
            provider="auto",
            depth="Snabb",
        )
        return {
            "type": "price_move",
            "ticker": ticker,
            "change_pct": price_alert["change_pct"],
            "current_price": price_alert["current_price"],
            "ai_analysis": result[:500] if result else f"⚠️ {ticker} rörde sig {price_alert['change_pct']:+.1f}% – sök efter nyheter.",
            "timestamp": datetime.now().isoformat(),
        }
    except Exception:
        return None


def _send_alert_email(alerts: list):
    """Skicka ett mail med alla alerts som triggats."""
    if not alerts:
        return

    date_str = date.today().strftime("%Y-%m-%d")
    md_lines = [f"# 🚨 MarketScan Larm – {date_str}\n"]
    md_lines.append(f"_{len(alerts)} händelser sedan senaste kontroll_\n")

    for alert in alerts:
        t = alert["ticker"]
        if alert["type"] == "news":
            md_lines.append(f"## 📰 {alert['status']} – {t}\n")
            md_lines.append(f"**{alert['headline']}**\n")
            if alert.get("source"):
                md_lines.append(f"Källa: {alert['source']}\n")
        elif alert["type"] == "price_move":
            direction = "🟢" if alert["change_pct"] >= 0 else "🔴"
            md_lines.append(f"## 📈 {t} {direction} {alert['change_pct']:+.1f}%\n")
            md_lines.append(f"Pris: {alert['current_price']} SEK\n")

        if alert.get("ai_analysis"):
            md_lines.append(f"\n🧠 **AI-analys:**\n{alert['ai_analysis']}\n")
        md_lines.append("---\n")

    md_lines.append("\n*Detta är ett automatiskt larm från MarketScan*\n")

    body = "\n".join(md_lines)

    try:
        email_sent = send_email(
            subject=f"🚨 MarketScan Larm – {date_str} ({len(alerts)} händelser)",
            body_markdown=body,
            from_name="MarketScan Alerts",
        )
        if email_sent:
            logger.info(f"  ✉ Larmmail skickat ({len(alerts)} alerts)")
    except Exception as e:
        logger.error(f"  ❌ Kunde inte skicka larmmail: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    debug = "--debug" in sys.argv
    check_alerts(debug=debug)