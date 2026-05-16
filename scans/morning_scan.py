"""
morning_scan.py
===============
Vardaglig morgonkoll kl 09:35 CET – "dagsbrev" format.

Skickar ALLTID email (dagsbrev), inte bara vid alerts.
Innehåll:
  1. MARKNADSÖVERSIKT  – OMXS30/SPY öppning, index-rörelse
  2. STOPPLOSS-ALERTS  – innehav ned >15% från inköpspris (kräver åtgärd)
  3. CRASH/SURGE       – intradag-rörelser >3% / >6%
  4. PORTFÖLJ-BRIEF    – alla innehav, kort statusrad
  5. KÖPMÖJLIGHETER    – topp-50 från söndagens scan
  6. NYHETER           – Finnhub-nyheter för innehav + bevakningslista
  7. EARNINGS-PÅMINNELSE
  8. BEVAKNINGSLISTA

Tidszoner:
  - Stockholmsbörsen öppnar 09:00 CET  → vi kör 09:35
  - NYSE öppnar 15:30 CET              → US-aktier: igårkvällens stängning

Kör manuellt: python morning_scan.py
GitHub Actions: morning_scan.yml (vardag 08:35 UTC = 09:35 CET vinter)
"""

import os
import sys
import time
import argparse
import smtplib
from datetime import date, datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import pandas as pd
import yfinance as yf

# Lägg till projektroten i sökvägen
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import config
from core import alerts
from core import logger
from core import ai_analysis
from core import email_template
from portfolio import portfolio
from core import earnings_calendar as ec
from portfolio import watchlist as wl
from core import news_fetcher

# ── Trösklar ──────────────────────────────────────────────────────────────
CRASH_WARN_PCT    = -3.0   # % – varning (gult)
CRASH_SELL_PCT    = -6.0   # % – sälj-signal (rött)
SURGE_NOTIFY_PCT  = +3.0   # % – stark uppgång, notifiera
SURGE_TAKEHALF    = +8.0   # % – uppgång så stor att "ta hem halva" är aktuellt
STOPLOSS_PCT      = -15.0  # % – stopploss-gräns mot inköpspris
MORNING_TOP_N     = 50     # Antal aktier från söndags-scan att kontrollera

# Benchmark-tickers för marknadsöversikt
BENCHMARK_TICKERS = {
    "^OMX":  "OMXS30",
    "SPY":   "S&P 500 (igår)",
    "^VIX":  "VIX",
}


# ══════════════════════════════════════════════════════════════
# LADDA SÖNDAGENS SCAN
# ══════════════════════════════════════════════════════════════

def load_top50_from_sunday() -> tuple[pd.DataFrame, str]:
    """Läser senaste scored_universe_*.csv och returnerar topp-50."""
    csvs = sorted(
        Path(config.REPORT_DIR).glob("scored_universe_*.csv"),
        reverse=True
    )
    if not csvs:
        return pd.DataFrame(), ""

    latest = csvs[0]
    date_str = latest.stem.split("_")[-1]

    try:
        df = pd.read_csv(latest)
        if "score_total" in df.columns:
            df = df.sort_values("score_total", ascending=False)
        return df.head(MORNING_TOP_N).copy(), date_str
    except Exception as e:
        print(f"  ⚠ Kunde inte läsa {latest}: {e}")
        return pd.DataFrame(), ""


# ══════════════════════════════════════════════════════════════
# MARKNADSÖVERSIKT
# ══════════════════════════════════════════════════════════════

def fetch_market_overview() -> dict:
    """
    Hämtar OMXS30 och SPY för att ge kontextuell marknadsöversikt.
    Returnerar {symbol: {name, change_pct, price, note}}.
    """
    result = {}
    for symbol, name in BENCHMARK_TICKERS.items():
        try:
            time.sleep(0.3)
            hist = yf.Ticker(symbol).history(period="3d", auto_adjust=True)
            if hist.empty or len(hist) < 2:
                continue
            curr = float(hist["Close"].iloc[-1])
            prev = float(hist["Close"].iloc[-2])
            chg  = (curr / prev - 1) * 100
            note = "" if symbol != "SPY" else "(NYSE stängt – igårkväll)"
            result[symbol] = {
                "name":       name,
                "change_pct": round(chg, 2),
                "price":      round(curr, 2),
                "note":       note,
            }
        except Exception:
            pass
    return result


# ══════════════════════════════════════════════════════════════
# PRISHÄMTNING
# ══════════════════════════════════════════════════════════════

def is_us_ticker(ticker: str) -> bool:
    return "." not in ticker


def fetch_opening_moves(tickers: list, verbose: bool = True) -> dict:
    """
    Hämtar procentuell rörelse sedan igår för varje ticker.
    EU-tickers: realtid. US-tickers: igårkvällens stängning.
    """
    result = {}
    eu_tickers = [t for t in tickers if not is_us_ticker(t)]
    us_tickers = [t for t in tickers if is_us_ticker(t)]

    if verbose:
        print(f"  Hämtar {len(eu_tickers)} EU + {len(us_tickers)} US-tickers...")

    for ticker in eu_tickers + us_tickers:
        try:
            time.sleep(0.25)
            hist = yf.Ticker(ticker).history(period="3d", auto_adjust=True)
            if hist.empty or len(hist) < 2:
                continue

            curr  = float(hist["Close"].iloc[-1])
            prev  = float(hist["Close"].iloc[-2])
            chg   = (curr / prev - 1) * 100

            vol_ratio = None
            if "Volume" in hist.columns and len(hist) >= 2:
                vol_today = float(hist["Volume"].iloc[-1])
                vol_prev  = float(hist["Volume"].iloc[-2])
                if vol_prev > 0:
                    vol_ratio = round(vol_today / vol_prev, 2)

            result[ticker] = {
                "change_pct": round(chg, 2),
                "price":      round(curr, 2),
                "prev_close": round(prev, 2),
                "is_us":      is_us_ticker(ticker),
                "vol_ratio":  vol_ratio,
                "data_fresh": not is_us_ticker(ticker),
            }
        except Exception:
            pass

    return result


# ══════════════════════════════════════════════════════════════
# ALERT-DETEKTERING
# ══════════════════════════════════════════════════════════════

def detect_stoploss_alerts(holdings: pd.DataFrame, price_moves: dict) -> list:
    """
    Hittar innehav ned >15% från inköpspris (cost_basis).
    Returnerar [{ticker, change_pct_total, price, cost_basis, msg}].
    """
    alerts_list = []
    for _, row in holdings.iterrows():
        ticker = str(row["ticker"]).upper()
        cost   = row.get("cost_basis")
        move   = price_moves.get(ticker, {})
        price  = move.get("price")

        if not price or not cost:
            continue
        try:
            cost_f = float(cost)
            if cost_f <= 0:
                continue
            total_pct = (price / cost_f - 1) * 100
            if total_pct <= STOPLOSS_PCT:
                alerts_list.append({
                    "ticker":    ticker,
                    "price":     price,
                    "cost_basis": cost_f,
                    "total_pct": round(total_pct, 1),
                    "msg":       f"Ned {total_pct:.1f}% från inköpspris {cost_f:.2f}",
                })
        except Exception:
            pass

    return sorted(alerts_list, key=lambda x: x["total_pct"])


def detect_portfolio_alerts(holdings: pd.DataFrame, price_moves: dict) -> dict:
    """
    Klassificerar intradag-rörelser i portföljen.
    Returnerar {crash: [...], surge: [...], normal: [...]}.
    """
    crash  = []
    surge  = []
    normal = []

    for _, row in holdings.iterrows():
        ticker = str(row["ticker"]).upper()
        move   = price_moves.get(ticker, {})
        chg    = move.get("change_pct")
        price  = move.get("price")
        cost   = row.get("cost_basis")

        if chg is None:
            continue

        total_pnl_pct = ((price / float(cost)) - 1) * 100 if (price and cost and float(cost) > 0) else None

        if chg <= CRASH_SELL_PCT:
            crash.append({
                "ticker":     ticker,
                "change_pct": chg,
                "price":      price,
                "action":     "SÄLJ/MINSKA",
                "msg":        f"Ned {chg:.1f}% vid öppning – kräver omedelbar åtgärd",
                "total_pnl":  total_pnl_pct,
            })
        elif chg <= CRASH_WARN_PCT:
            crash.append({
                "ticker":     ticker,
                "change_pct": chg,
                "price":      price,
                "action":     "BEVAKA",
                "msg":        f"Ned {chg:.1f}% – håll ett öga på utvecklingen",
                "total_pnl":  total_pnl_pct,
            })
        elif chg >= SURGE_TAKEHALF:
            surge.append({
                "ticker":     ticker,
                "change_pct": chg,
                "price":      price,
                "action":     "TA HEM HALVA",
                "msg":        f"Upp {chg:+.1f}% – överväg att ta hem vinst",
                "total_pnl":  total_pnl_pct,
            })
        elif chg >= SURGE_NOTIFY_PCT:
            surge.append({
                "ticker":     ticker,
                "change_pct": chg,
                "price":      price,
                "action":     "BEVAKA",
                "msg":        f"Upp {chg:+.1f}% – stark öppning",
                "total_pnl":  total_pnl_pct,
            })
        else:
            normal.append({
                "ticker":     ticker,
                "change_pct": chg,
                "price":      price,
            })

    return {"crash": crash, "surge": surge, "normal": normal}


# ══════════════════════════════════════════════════════════════
# KÖPMÖJLIGHETER FRÅN TOPP-50
# ══════════════════════════════════════════════════════════════

def find_opportunities(top50: pd.DataFrame, price_moves: dict, holdings: pd.DataFrame) -> list:
    """
    Hittar köpmöjligheter bland topp-50 som inte redan finns i portföljen.
    Dip i upptrend (-2% till -8%) eller breakout (+1% till +5%, volym ≥1.3x).
    """
    portfolio_tickers = set(holdings["ticker"].str.upper()) if not holdings.empty else set()
    opportunities = []

    for _, row in top50.iterrows():
        ticker = str(row.get("ticker", "")).upper()
        if ticker in portfolio_tickers:
            continue

        entry_signal = str(row.get("entry_signal", "")).upper()
        score        = row.get("score_total", 0)
        move         = price_moves.get(ticker, {})
        chg          = move.get("change_pct")

        if chg is None or score < 60:
            continue

        if -8.0 <= chg <= -2.0 and entry_signal in ("STARK", "OK"):
            opportunities.append({
                "ticker":  ticker,
                "name":    str(row.get("name", ""))[:30],
                "score":   round(float(score), 1),
                "change":  chg,
                "type":    "DIP",
                "signal":  entry_signal,
                "msg":     f"Dipp {chg:.1f}% i upptrend – potentiell entry",
                "sector":  str(row.get("sector", "")),
            })
        elif 1.0 <= chg <= 5.0 and entry_signal == "STARK":
            vol = move.get("vol_ratio", 1.0) or 1.0
            if vol >= 1.3:
                opportunities.append({
                    "ticker":  ticker,
                    "name":    str(row.get("name", ""))[:30],
                    "score":   round(float(score), 1),
                    "change":  chg,
                    "type":    "BREAKOUT",
                    "signal":  entry_signal,
                    "msg":     f"Uppgång {chg:+.1f}% med {vol:.1f}x volym",
                    "sector":  str(row.get("sector", "")),
                })

    return sorted(opportunities, key=lambda x: x["score"], reverse=True)[:5]


# ══════════════════════════════════════════════════════════════
# BEVAKNINGSLISTA – morgonkoll
# ══════════════════════════════════════════════════════════════

def build_watchlist_morning_section(
    watchlist_items: list,
    price_moves:     dict,
    scored_df:       pd.DataFrame,
) -> str:
    if not watchlist_items:
        return ""

    lines = ["## Bevakningslista – morgonstatus\n"]
    lines.append("| Ticker | Bolag | Idag | Score | Signal | Nästa rapport |")
    lines.append("|--------|-------|------|-------|--------|---------------|")

    score_lookup = {}
    if not scored_df.empty and "ticker" in scored_df.columns:
        score_lookup = scored_df.set_index("ticker").to_dict("index")

    for item in watchlist_items:
        ticker = item["ticker"]
        name   = item.get("name", ticker)[:22]
        move   = price_moves.get(ticker, {})
        chg    = move.get("change_pct")
        chg_s  = f"{chg:+.1f}%" if chg is not None else "—"
        chg_icon = ("🟢" if chg >= 0 else "🔴") if chg is not None else "⚪"

        sc      = score_lookup.get(ticker, {})
        score   = sc.get("score_total")
        signal  = sc.get("entry_signal", "—")
        score_s = f"{score:.0f}" if score is not None else "—"

        earn_s = "—"
        try:
            earn_date = sc.get("next_earnings_date") or sc.get("earnings_date")
            if earn_date:
                days = (pd.Timestamp(earn_date).date() - date.today()).days
                if 0 <= days <= 90:
                    earn_s = f"{days}d"
        except Exception:
            pass

        sign_chg = "+" if chg is not None and chg >= 0 else ""
        chg_display = f"{sign_chg}{chg:.1f}%" if chg is not None else "—"
        lines.append(
            f"| `{ticker}` | {name} | {chg_display} | {score_s} | {signal} | {earn_s} |"
        )

    return "\n".join(lines) + "\n"


# ══════════════════════════════════════════════════════════════
# RAPPORT-BYGGARE
# ══════════════════════════════════════════════════════════════

def build_morning_report(
    portfolio_alerts: dict,
    opportunities:    list,
    earnings_soon:    pd.DataFrame,
    top50_date:       str,
    holdings:         pd.DataFrame,
    price_moves:      dict,
    market_overview:  dict         = None,
    stoploss_alerts:  list         = None,
    news_by_ticker:   dict         = None,
    global_news:      list         = None,
    swedish_news:     list         = None,
    nasdaq_news:      list         = None,
    watchlist_items:  list         = None,
    top50_df:         pd.DataFrame = None,
) -> tuple[str, str]:
    """Bygger dagsbrevet. Returnerar (markdown, email-ämne)."""
    now    = datetime.now().strftime("%Y-%m-%d %H:%M")
    crash  = portfolio_alerts.get("crash",  [])
    surge  = portfolio_alerts.get("surge",  [])
    normal = portfolio_alerts.get("normal", [])
    stoploss_alerts = stoploss_alerts or []
    news_by_ticker  = news_by_ticker  or {}
    global_news     = global_news     or []
    swedish_news    = swedish_news    or []
    nasdaq_news     = nasdaq_news     or []

    # ── Ämnesrad (alltid informativ) ──────────────────────────
    omxs30_data = (market_overview or {}).get("^OMX", {})
    omx_chg     = omxs30_data.get("change_pct")
    omx_s       = f"OMXS30 {omx_chg:+.1f}%" if omx_chg is not None else ""

    if stoploss_alerts:
        tickers  = ", ".join(a["ticker"] for a in stoploss_alerts[:2])
        subject  = f"MarketScan: Stopploss {tickers} – {date.today().strftime('%d %b')}"
    elif crash and any(a["action"] == "SÄLJ/MINSKA" for a in crash):
        tickers  = ", ".join(a["ticker"] for a in crash if a["action"] == "SÄLJ/MINSKA")
        subject  = f"MarketScan: Alert {tickers} – {date.today().strftime('%d %b')}"
    elif crash:
        tickers  = ", ".join(a["ticker"] for a in crash)
        subject  = f"MarketScan: Varning {tickers} – {omx_s or date.today().strftime('%d %b')}"
    elif surge and any(a["action"] == "TA HEM HALVA" for a in surge):
        tickers  = ", ".join(a["ticker"] for a in surge if a["action"] == "TA HEM HALVA")
        subject  = f"MarketScan: Stark uppgang {tickers} – {date.today().strftime('%d %b')}"
    elif opportunities:
        first   = opportunities[0]
        typ     = "Dip" if first["type"] == "DIP" else "Breakout"
        subject  = f"MarketScan: {typ} {first['ticker']} – {omx_s or date.today().strftime('%d %b')}"
    else:
        subject = f"MarketScan Morgon {date.today().strftime('%d %b')} – {omx_s or 'Inga signaler'}"

    # ── Rapport ───────────────────────────────────────────────
    lines = [f"# MarketScan · Morgon – {now}\n", "---\n"]

    # 1. Marknadsöversikt
    if market_overview:
        lines.append("## Marknad\n")
        lines.append("| Index | Rorelse | Kurs |")
        lines.append("|-------|---------|------|")
        for sym, d in market_overview.items():
            chg   = d["change_pct"]
            sign  = "+" if chg >= 0 else ""
            note  = f" _{d['note']}_" if d.get("note") else ""
            lines.append(f"| {d['name']}{note} | {sign}{chg:+.2f}% | {d['price']:.2f} |")
        lines.append("")

    # 2. Stopploss-alerts (kritiska – visas högst upp)
    if stoploss_alerts:
        lines.append("## Stopploss\n")
        lines.append("> Foljande innehav ar ned mer an 15% fran inkopspris och bor ses over.\n")
        for a in stoploss_alerts:
            lines.append(
                f"**`{a['ticker']}`** – ned **{a['total_pct']:.1f}%** fran "
                f"inkopspris {a['cost_basis']:.2f} (nuvarande {a['price']:.2f})  \n"
                f"_{a['msg']}_\n"
            )

    # 3. Intradag-alerts (crash/surge)
    if crash:
        lines.append("## Alerts\n")
        for a in sorted(crash, key=lambda x: x["change_pct"]):
            pnl_s = f" (Totalt P&L: {a['total_pnl']:+.1f}%)" if a.get("total_pnl") is not None else ""
            lines.append(
                f"**`{a['ticker']}`** {a['change_pct']:+.1f}% "
                f"\u2192 **{a['action']}**  \n_{a['msg']}{pnl_s}_\n"
            )

    if surge:
        lines.append("## Stark uppgang\n")
        for a in sorted(surge, key=lambda x: x["change_pct"], reverse=True):
            pnl_s = f" (Totalt: {a['total_pnl']:+.1f}%)" if a.get("total_pnl") is not None else ""
            lines.append(
                f"**`{a['ticker']}`** {a['change_pct']:+.1f}% "
                f"\u2192 **{a['action']}**  \n_{a['msg']}{pnl_s}_\n"
            )

    # 4. Portfölj-brief (alla innehav)
    if not holdings.empty and price_moves:
        lines.append("## Portfolj\n")
        lines.append("| Ticker | Idag | Pris | Totalt |")
        lines.append("|--------|------|------|--------|")
        all_holding_rows = list(holdings.iterrows())
        for _, row in all_holding_rows:
            ticker  = str(row["ticker"]).upper()
            move    = price_moves.get(ticker, {})
            chg     = move.get("change_pct")
            price   = move.get("price")
            cost    = row.get("cost_basis")
            if chg is None:
                continue
            price_s   = f"{price:.2f}" if price else "—"
            total_s   = "—"
            if price and cost:
                try:
                    total_pct = (price / float(cost) - 1) * 100
                    total_s   = f"{total_pct:+.1f}%"
                except Exception:
                    pass
            lines.append(f"| `{ticker}` | {chg:+.1f}% | {price_s} | {total_s} |")
        lines.append("")

    # 5. Köpmöjligheter
    if opportunities:
        lines.append(f"## Kopmojligheter (topp-50 fran {top50_date})\n")
        for opp in opportunities:
            lines.append(
                f"**`{opp['ticker']}`** {opp['name']} "
                f"_{opp['sector']}_  \n"
                f"Score: **{opp['score']:.0f}** \xB7 {opp['change']:+.1f}% \xB7 "
                f"{opp['signal']} \xB7 {opp['msg']}\n"
            )

    # 6. Nyheter (Finnhub)
    if news_by_ticker:
        ticker_names = {}
        if not holdings.empty and "ticker" in holdings.columns and "name" in holdings.columns:
            ticker_names.update(
                dict(zip(holdings["ticker"].str.upper(), holdings.get("name", holdings["ticker"])))
            )
        for item in (watchlist_items or []):
            ticker_names[item["ticker"]] = item.get("name", item["ticker"])

        news_md = news_fetcher.format_news_section_md(
            news_by_ticker, ticker_names=ticker_names, header="Nyheter (senaste 24h)"
        )
        if news_md:
            lines.append(news_md)

    # 6b. Nasdaq Nordic – regulatoriska börsmeddelanden
    nasdaq_md = news_fetcher.format_nasdaq_nordic_section_md(nasdaq_news, max_items=5)
    if nasdaq_md:
        lines.append(nasdaq_md)

    # 7. Earnings-påminnelse
    if earnings_soon is not None and not earnings_soon.empty:
        lines.append("## Kommande rapporter\n")
        for _, row in earnings_soon.iterrows():
            days   = row.get("days_until", "?")
            ticker = row.get("ticker", "")
            d      = str(row.get("date", ""))[:10]
            lines.append(f"- **`{ticker}`** rapporterar **{d}** (om {days} dagar)")
        lines.append("")

    # 8. Generella marknadsnyheter (kompakt, 3+3)
    market_news_md = news_fetcher.format_market_news_section_md(
        global_news, swedish_news, compact=True
    )
    if market_news_md:
        lines.append(market_news_md)

    # 9. Bevakningslista
    if watchlist_items:
        wl_section = build_watchlist_morning_section(
            watchlist_items, price_moves, top50_df if top50_df is not None else pd.DataFrame()
        )
        if wl_section:
            lines.append(wl_section)

    # Statusrad om inga alerts
    has_alerts = bool(crash or surge or stoploss_alerts or opportunities)
    if not has_alerts:
        lines.append("## Status\n\nInga signaler – marknaden oppnar normalt.\n")

    lines.append("---\n*Inte finansiell radgivning. MarketScan morgonkoll.*")
    return "\n".join(lines), subject


# ══════════════════════════════════════════════════════════════
# EMAIL (delegeras till email_template)
# ══════════════════════════════════════════════════════════════

def send_email(subject: str, report: str) -> bool:
    """Skickar email via gemensam email-engine."""
    return email_template.send_email(
        subject=subject,
        body_markdown=report,
        from_name="MarketScan Morgonkoll",
    )


# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Morgonkoll – dagsbrev med marknadsöversikt")
    parser.add_argument("--quiet",       action="store_true")
    parser.add_argument("--no-email",    action="store_true")
    parser.add_argument("--force-email", action="store_true",
                        help="(Deprecated) Email skickas alltid numera")
    args = parser.parse_args()
    v = not args.quiet

    print("🌅 MORGONKOLL")
    print("=" * 40)

    with logger.scan_logger("morning", verbose=v) as log:

        # 1. Ladda söndagens topp-50
        print("📊 Laddar senaste scan...")
        top50, top50_date = load_top50_from_sunday()
        if top50.empty:
            print("  ⚠ Ingen scan hittad – kör python scan.py först")
        else:
            age_days = (date.today() - date.fromisoformat(top50_date)).days
            print(f"  ✓ Topp-50 från {top50_date} ({age_days} dagar gammal)")
            if age_days > 8:
                print("  ⚠ Scanen är mer än 8 dagar gammal – kör en ny söndagsscan")

        # 2. Ladda portfölj och bevakningslista
        holdings         = portfolio.load_holdings()
        watchlist_items  = wl.load_watchlist()
        watchlist_tickers = [i["ticker"] for i in watchlist_items]
        log["n_holdings"] = len(holdings)
        if v:
            print(f"  ✓ {len(holdings)} innehav laddade")
        if watchlist_tickers and v:
            print(f"  ⭐ {len(watchlist_tickers)} aktier i bevakningslistan")

        # 3. Hämta marknadsöversikt (benchmarks)
        print("\n📈 Hämtar marknadsöversikt (OMXS30/SPY/VIX)...")
        market_overview = fetch_market_overview()
        if market_overview and v:
            for sym, d in market_overview.items():
                sign = "+" if d["change_pct"] >= 0 else ""
                print(f"  {d['name']}: {sign}{d['change_pct']:.2f}%")

        # 4. Hämta priser för alla tickers
        all_tickers = list(set(
            list(holdings["ticker"].str.upper() if not holdings.empty else []) +
            list(top50["ticker"].str.upper() if not top50.empty else []) +
            watchlist_tickers
        ))
        print(f"\n📥 Hämtar priser ({len(all_tickers)} tickers)...")
        price_moves = fetch_opening_moves(all_tickers, verbose=v)
        log["n_prices"] = len(price_moves)
        print(f"  ✓ {len(price_moves)} priser hämtade")

        # 5. Stopploss-alerts
        stoploss_alerts = []
        if not holdings.empty:
            stoploss_alerts = detect_stoploss_alerts(holdings, price_moves)
            if stoploss_alerts and v:
                print(f"\n  🛑 {len(stoploss_alerts)} stopploss-alert(s)!")
        log["n_stoploss"] = len(stoploss_alerts)

        # 6. Intradag-alerts
        portfolio_alerts = {"crash": [], "surge": [], "normal": []}
        if not holdings.empty:
            portfolio_alerts = detect_portfolio_alerts(holdings, price_moves)
            n_crash = len(portfolio_alerts["crash"])
            n_surge = len(portfolio_alerts["surge"])
            if n_crash:
                print(f"  🚨 {n_crash} crash/varnings-alert(s) i portföljen!")
            if n_surge:
                print(f"  🚀 {n_surge} stark uppgång(ar) i portföljen!")
        log["n_crash"] = len(portfolio_alerts.get("crash", []))
        log["n_surge"] = len(portfolio_alerts.get("surge", []))

        # 7. Köpmöjligheter
        opportunities = []
        if not top50.empty and not holdings.empty:
            opportunities = find_opportunities(top50, price_moves, holdings)
            if opportunities and v:
                print(f"  💡 {len(opportunities)} köpmöjlighet(er) identifierade")
        log["n_opportunities"] = len(opportunities)

        # 8. Earnings-påminnelse
        earnings_soon = pd.DataFrame()
        try:
            if not holdings.empty:
                scored_placeholder = top50 if not top50.empty else pd.DataFrame()
                earnings_soon = ec.upcoming_in_portfolio(
                    holdings, scored_placeholder, days_ahead=7
                )
        except Exception:
            pass

        # 9. Nyheter (Finnhub + Google News RSS + Nasdaq Nordic)
        news_by_ticker  = {}
        global_news     = []
        swedish_news    = []
        nasdaq_news     = []
        finnhub_key     = os.environ.get("FINNHUB_API_KEY", "")

        print("\n📰 Hämtar nyheter...")

        # 9a. Finnhub bolagsnyheter (fungerar bra för US-aktier)
        if finnhub_key:
            news_tickers = (
                list(holdings["ticker"].str.upper() if not holdings.empty else []) +
                watchlist_tickers
            )
            if news_tickers:
                news_by_ticker = news_fetcher.fetch_news_batch(
                    news_tickers, finnhub_key, days=1
                )
                if news_by_ticker and v:
                    print(f"  ✓ Bolagsnyheter (Finnhub): {len(news_by_ticker)} aktier")
            global_news = news_fetcher.fetch_global_market_news(finnhub_key, max_articles=3)
            if global_news and v:
                print(f"  ✓ {len(global_news)} globala marknadsnyheter")
        else:
            if v:
                print("  ℹ FINNHUB_API_KEY ej satt – Finnhub hoppas över")

        # 9b. Google News RSS per bolag (bättre täckning för svenska aktier)
        # Bygg ticker→namn-mapping från portfölj + bevakningslista
        ticker_name_map = {}
        if not holdings.empty:
            for _, row in holdings.iterrows():
                t = str(row["ticker"]).upper()
                n = str(row.get("name", "") or "").strip()
                if n:
                    ticker_name_map[t] = n
        for item in watchlist_items:
            t = item["ticker"]
            n = item.get("name", "")
            if n:
                ticker_name_map[t] = n

        if ticker_name_map:
            print(f"  🔍 Google News för {len(ticker_name_map)} bolag...")
            google_by_ticker = news_fetcher.fetch_company_news_google_batch(
                ticker_name_map, max_items=3, delay=1.3
            )
            # Slå ihop Finnhub + Google; Google kompletterar där Finnhub saknar täckning
            for ticker, g_articles in google_by_ticker.items():
                existing = news_by_ticker.get(ticker, [])
                news_by_ticker[ticker] = news_fetcher._merge_news(existing, g_articles, max_total=4)
            if google_by_ticker and v:
                print(f"  ✓ Google News: {len(google_by_ticker)} bolag")

        # 9c. Nasdaq Nordic – regulatoriska börsmeddelanden (Stockholm)
        print("  📋 Nasdaq Nordic...")
        nasdaq_news = news_fetcher.fetch_nasdaq_nordic_news(market="SSE", max_items=6, hours_back=24)
        if nasdaq_news and v:
            print(f"  ✓ {len(nasdaq_news)} Nasdaq Nordic-meddelanden")

        # 9d. Svenska RSS-nyheter (Placera/DI/Realtid)
        swedish_news = news_fetcher.fetch_swedish_market_news(max_articles=3)
        if swedish_news and v:
            print(f"  ✓ {len(swedish_news)} svenska börsnyheter")

        # 10. Bygg rapport
        report, subject = build_morning_report(
            portfolio_alerts, opportunities, earnings_soon,
            top50_date, holdings, price_moves,
            market_overview  = market_overview,
            stoploss_alerts  = stoploss_alerts,
            news_by_ticker   = news_by_ticker,
            global_news      = global_news,
            swedish_news     = swedish_news,
            nasdaq_news      = nasdaq_news,
            watchlist_items  = watchlist_items,
            top50_df         = top50,
        )

        # 10b. AI Morning Brief (Feature 6)
        ai_brief = ""
        try:
            print("\n🤖 Genererar AI-morgonbrief...")
            # Bygg data för AI-anropet
            bench_data = {}
            for sym, d in (market_overview or {}).items():
                bench_data[d.get("name", sym)] = {
                    "change_pct": d.get("change_pct"),
                    "price": d.get("price"),
                }
            portfolio_data = {
                "num_holdings": len(holdings),
                "holdings": []
            }
            if not holdings.empty and price_moves:
                for _, row in holdings.iterrows():
                    t = str(row["ticker"]).upper()
                    m = price_moves.get(t, {})
                    portfolio_data["holdings"].append({
                        "ticker": t,
                        "change_pct": m.get("change_pct"),
                        "price": m.get("price"),
                        "cost_basis": row.get("cost_basis"),
                    })
            ai_alerts = []
            for a in stoploss_alerts:
                ai_alerts.append({"type": "stoploss", "ticker": a["ticker"], "pct": a["total_pct"]})
            for a in portfolio_alerts.get("crash", []):
                ai_alerts.append({"type": "crash", "ticker": a["ticker"], "pct": a["change_pct"], "action": a["action"]})
            for a in portfolio_alerts.get("surge", []):
                ai_alerts.append({"type": "surge", "ticker": a["ticker"], "pct": a["change_pct"], "action": a["action"]})
            ai_opps = []
            for o in opportunities:
                ai_opps.append({"ticker": o["ticker"], "type": o["type"], "score": o["score"], "msg": o["msg"]})

            ai_brief = ai_analysis.generate_morning_brief(
                market_data=bench_data,
                portfolio_data=portfolio_data,
                alerts_list=ai_alerts,
                opportunities=ai_opps,
            )
            if ai_brief and not ai_brief.startswith("⚠") and not ai_brief.startswith("ℹ"):
                report += f"\n\n## Sammanfattning\n\n{ai_brief}\n"
                print("  ✓ AI-morgonbrief tillagd i rapporten")
            else:
                print(f"  ℹ AI-morgonbrief hoppades över: {ai_brief[:60] if ai_brief else 'tomt svar'}")
        except Exception as e:
            print(f"  ⚠ AI-morgonbrief misslyckades: {e}")

        # Spara rapport
        Path(config.REPORT_DIR).mkdir(exist_ok=True)
        report_path = Path(config.REPORT_DIR) / f"morning_{date.today()}.md"
        report_path.write_text(report, encoding="utf-8")
        log["report_path"] = str(report_path)

        # 11. Skicka email (alltid, om inte --no-email)
        if not args.no_email and email_template.email_configured():
            print(f"\n✉ Skickar dagsbrev: {subject}")
            ok = send_email(subject, report)
            if ok:
                _, _, to = email_template._get_email_config()
                print(f"  ✉ Email skickat till {to}")
        elif not email_template.email_configured():
            print("\n  ℹ Email ej konfigurerat – hoppar över")

        # Terminal-sammanfattning
        print(f"\n{'─'*40}")
        print(f"  Stopploss:       {len(stoploss_alerts)}")
        print(f"  Crash alerts:    {len(portfolio_alerts.get('crash', []))}")
        print(f"  Uppgångar:       {len(portfolio_alerts.get('surge', []))}")
        print(f"  Köpmöjligheter:  {len(opportunities)}")
        print(f"  Bolagsnyheter:   {len(news_by_ticker)} aktier")
        print(f"  Svenska nyheter: {len(swedish_news)}")
        print(f"  Globala nyheter: {len(global_news)}")
        print(f"  Nasdaq Nordic:   {len(nasdaq_news)}")
        print(f"  Rapport:         {report_path}")


if __name__ == "__main__":
    main()
