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
_STATE_FILE = DATA_DIR / "news_alert_state.json"

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(message)s")


# ── Dedup-state (förhindrar att samma nyhet larmas var 30:e minut) ────────────

def _load_seen() -> set:
    """Laddar redan larmade nyheter/prisrörelser för IDAG. Nollställs dagligen."""
    try:
        data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        if data.get("date") == date.today().isoformat():
            return set(data.get("seen", []))
    except Exception:
        pass
    return set()


def _save_seen(seen: set):
    """Sparar dagens larm-state. (CI committar filen så den överlever omstart.)"""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        _STATE_FILE.write_text(
            json.dumps({"date": date.today().isoformat(), "seen": sorted(seen)},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


def _alert_key(ticker: str, kind: str, detail: str) -> str:
    """Stabil nyckel för dedup: ticker + typ + innehåll (hashat)."""
    import hashlib
    raw = f"{ticker}|{kind}|{detail}".lower()
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]


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


def _is_us_ticker(ticker: str) -> bool:
    """US-tickers saknar börssuffix (ingen punkt). Finnhub company-news
    fungerar bara för dessa – nordiska/europeiska .ST/.HE/.DE m.fl. ger tomt."""
    return "." not in ticker


def _fetch_news(ticker: str, max_items: int = 3) -> list:
    """
    Hämta nyheter för en ticker.

    1. Finnhub (snabbt, men endast US-tickers).
    2. Fallback till core.news_fetcher.fetch_company_news() för icke-US-tickers
       (nordiska/europeiska) ELLER när Finnhub inte gav något. Den källan
       använder Google News RSS + Nasdaq Nordic + DuckDuckGo och fungerar för
       .ST/.HE-aktier – tidigare fick svenska innehav ALDRIG nyhetslarm.

    Returnerar lista med dict: {headline, summary, source, url, datetime}
    """
    api_key = os.getenv("FINNHUB_API_KEY", "")
    result = []

    # ── 1. Finnhub (endast meningsfullt för US-tickers) ──────────────────
    if api_key and _is_us_ticker(ticker):
        try:
            import requests
            url = "https://finnhub.io/api/v1/company-news"
            params = {
                "symbol": ticker,
                "from": date.today().strftime("%Y-%m-%d"),
                "to": date.today().strftime("%Y-%m-%d"),
                "token": api_key,
            }
            resp = requests.get(url, params=params, timeout=15)
            if resp.status_code == 200:
                articles = resp.json()
                if isinstance(articles, list):
                    for article in articles[:max_items]:
                        headline = article.get("headline", "").strip()
                        if not headline:
                            continue
                        summary = article.get("summary", "").strip()
                        result.append({
                            "headline": headline[:200],
                            "summary": summary[:300] if summary else "",
                            "source": article.get("source", "Finnhub"),
                            "url": article.get("url", ""),
                            "datetime": article.get("datetime", ""),
                        })
        except Exception:
            pass

    if result:
        return result

    # ── 2. Multi-källa fallback (fungerar för nordiska/europeiska aktier) ─
    try:
        from core.news_fetcher import fetch_company_news
        # Bara dagsfärska nyheter är relevanta för realtidslarm
        articles = fetch_company_news(ticker, days_back=1)
        for article in articles[:max_items]:
            headline = (article.get("headline") or "").strip()
            if not headline:
                continue
            result.append({
                "headline": headline[:200],
                "summary": "",
                "source": article.get("source", "News"),
                "url": article.get("url", ""),
                "datetime": article.get("datetime_str", ""),
            })
    except Exception as e:
        logger.debug(f"  ⚠ Nyhetsfallback misslyckades för {ticker}: {e}")

    return result


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

    # Sets för korrekt statusklassning
    portfolio_set = set(portfolio.keys())
    watchlist_set = set(watchlist)
    top_set       = set(top_tickers)

    # Om användaren har portfölj/watchlist: använd den
    # Om BÅDA är tomma: spamma INTE mail om random topp-10 utländska aktier.
    # (Tidigare bugg: top-10 från scored_universe drog in AFL, TRV, etc. och
    # markerade dem fel som "BEVAKAD" eftersom etiketten var binär.)
    has_user_focus = bool(portfolio_set) or bool(watchlist_set)

    all_tickers = set()
    all_tickers.update(portfolio_set)
    all_tickers.update(watchlist_set)
    if has_user_focus:
        all_tickers.update(top_set)   # Topp-10 endast som komplement
    else:
        logger.info("  ⚠ Både portfölj och watchlist är tomma – hoppar över topp-10 "
                    "för att undvika spam av aktier du inte följer.")
        top_set = set()  # Töm så ingen kan klassas som TOPP-10 nedan

    # Exkludera index
    index_suffixes = (".SS", ".SSE", ".SZ")
    tickers_to_check = [t for t in all_tickers if t and not t.startswith("^") and not t.endswith(index_suffixes)]

    logger.info(f"  👁️ Bevakar {len(tickers_to_check)} tickers:")
    logger.info(f"     Portfölj: {len(portfolio_set)}, Watchlist: {len(watchlist_set)}, "
                f"Topp-10: {len(top_set)}")

    alerts = []
    seen = _load_seen()        # Redan larmade nyheter/prisrörelser idag
    new_keys = set()           # Nya nycklar att lägga till state efter körning

    for ticker in tickers_to_check:
        status = _classify_status(ticker, portfolio_set, watchlist_set, top_set)

        # 1. Kolla nyheter (Finnhub för US, multi-källa för nordiska)
        news = _fetch_news(ticker, max_items=2)
        for article in news:
            headline = article.get("headline", "")
            if not headline:
                continue
            # Dedup: hoppa över nyheter vi redan larmat om idag
            key = _alert_key(ticker, "news", headline)
            if key in seen:
                logger.info(f"  ↩ {ticker}: redan larmad nyhet, hoppar över")
                continue
            logger.info(f"  📰 {ticker} [{status}]: {headline[:80]}...")

            # AI-bedömning
            alert = _evaluate_alert(ticker, headline, article, portfolio, status, debug)
            if alert:
                alerts.append(alert)
                new_keys.add(key)

        # 2. Kolla prisrörelse >5% (en gång per ticker+riktning per dag)
        price_alert = _check_price_move(ticker, threshold=5.0)
        if price_alert:
            direction = price_alert["direction"]
            change = price_alert["change_pct"]
            price_key = _alert_key(ticker, "price", direction)
            if price_key in seen:
                logger.info(f"  ↩ {ticker}: prisrörelse redan larmad idag, hoppar över")
            else:
                logger.info(f"  📈 {ticker} [{status}]: {direction} {change:+.1f}%")
                alert = _evaluate_price_move(ticker, price_alert, status, debug)
                if alert:
                    alerts.append(alert)
                    new_keys.add(price_key)

        # Vänta lite mellan anropen för att inte rate-limit Finnhub
        time.sleep(1.5)

    # Skicka mail om det finns alerts
    if alerts and not debug:
        _send_alert_email(alerts)
        # Spara state först EFTER lyckad bearbetning så inget tappas vid krasch
        _save_seen(seen | new_keys)

    elapsed = time.time() - start
    logger.info(f"\n✅ Klart! {len(alerts)} alerts på {elapsed:.0f}s")

    return alerts


def _classify_status(ticker: str, portfolio_set: set, watchlist_set: set, top_set: set) -> str:
    """Tre-vägs statusetikett. Prio: INNEHAV > BEVAKAD > TOPP-10 > ÖVRIGT."""
    if ticker in portfolio_set:
        return "🟢 INNEHAV"
    if ticker in watchlist_set:
        return "⭐ BEVAKAD"
    if ticker in top_set:
        return "🔥 TOPP-10"
    return "📊 ÖVRIGT"


def _evaluate_alert(ticker: str, headline: str, article: dict,
                    portfolio: dict, status: str = "📊 ÖVRIGT",
                    debug: bool = False) -> dict | None:
    """AI-värdering av en nyhet. Returnerar alert-dict om viktig."""
    is_holding = status  # behåll variabelnamnet för bakåtkompatibilitet

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
            "ai_analysis": result,
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
                          status: str = "📊 ÖVRIGT",
                          debug: bool = False) -> dict | None:
    """AI-förklaring av prisrörelse."""
    try:
        ctx = json.dumps({**price_alert, "status": status}, ensure_ascii=False)
        result = ai_analysis.ai_chat(
            f"Förklara varför {ticker} rörde sig {price_alert['change_pct']:+.1f}% idag.",
            context=ctx,
            provider="auto",
            depth="Snabb",
        )
        return {
            "type": "price_move",
            "ticker": ticker,
            "status": status,
            "change_pct": price_alert["change_pct"],
            "current_price": price_alert["current_price"],
            "ai_analysis": result if result else f"⚠️ {ticker} rörde sig {price_alert['change_pct']:+.1f}% – sök efter nyheter.",
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