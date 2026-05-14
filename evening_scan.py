"""
evening_scan.py
===============
Vardaglig kvällsrapport kl 17:30 CET.

Alltid ett email. Kompakt och beslutscentrerat.

Innehåll:
  1. Dagens marknadsrörelser  – OMXS30, SPY, din portfölj
  2. Portfölj-dashboard       – varje innehav: dagens rörelse, total P&L, signal
  3. Håll/Sälj-analys         – baserat på söndagens score + daglig prisrörelse
  4. Vecko-P&L-trend          – hur har portföljen gått denna vecka?
  5. Kommande rapporter        – earnings inom 14 dagar
  6. Paper trading-update      – senaste stängningspriser inlagda

Kör manuellt: python evening_scan.py
GitHub Actions: evening_scan.yml (vardag 16:30 UTC = 17:30 CET vinter)
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
import numpy as np
import yfinance as yf

import config
import alerts
import logger
import portfolio
import paper_trading
import earnings_calendar as ec
import watchlist as wl
import news_fetcher

OMXS30_PROXY = "XACTOMXS3.ST"
SPY_TICKER   = "SPY"

# Trösklar för Hold/Sälj
SELL_SCORE_THRESH    = 40    # Score under detta → SÄLJ-signal
REDUCE_SCORE_THRESH  = 50    # Score under detta → MINSKA
STRONG_HOLD_THRESH   = 70    # Score över detta → BEHÅLL starkt
WEEKLY_LOSS_WARN     = -5.0  # Veckotapp % → varning
STOPLOSS_PCT         = -15.0 # % – stopploss-gräns mot inköpspris


# ══════════════════════════════════════════════════════════════
# STOPPLOSS-DETEKTERING
# ══════════════════════════════════════════════════════════════

def detect_stoploss_alerts(holdings: pd.DataFrame, prices: dict) -> list:
    """Hittar innehav ned >15% från inköpspris (cost_basis)."""
    result = []
    for _, row in holdings.iterrows():
        ticker = str(row["ticker"]).upper()
        cost   = row.get("cost_basis")
        price  = (prices.get(ticker) or {}).get("price")
        if not price or not cost:
            continue
        try:
            cost_f    = float(cost)
            total_pct = (price / cost_f - 1) * 100
            if total_pct <= STOPLOSS_PCT:
                result.append({
                    "ticker":     ticker,
                    "price":      price,
                    "cost_basis": cost_f,
                    "total_pct":  round(total_pct, 1),
                })
        except Exception:
            pass
    return sorted(result, key=lambda x: x["total_pct"])


# ══════════════════════════════════════════════════════════════
# DATAHÄMTNING
# ══════════════════════════════════════════════════════════════

def fetch_closing_prices(tickers: list) -> dict:
    """
    Hämtar slutkurser + rörelsedata för en lista tickers.
    Returnerar {ticker: {price, change_1d_pct, change_1w_pct, volume_ratio}}
    """
    result = {}
    for ticker in tickers:
        try:
            time.sleep(0.25)
            hist = yf.Ticker(ticker).history(period="10d", auto_adjust=True)
            if hist.empty or len(hist) < 2:
                continue

            close   = hist["Close"]
            curr    = float(close.iloc[-1])
            prev    = float(close.iloc[-2])
            chg_1d  = (curr / prev - 1) * 100

            # 1-veckors rörelse (~5 handelsdagar)
            week_idx  = max(0, len(close) - 6)
            week_start = float(close.iloc[week_idx])
            chg_1w    = (curr / week_start - 1) * 100 if week_start > 0 else None

            # Volym-ratio
            vol_ratio = None
            if "Volume" in hist.columns and len(hist) >= 6:
                vol_today = float(hist["Volume"].iloc[-1])
                vol_avg   = float(hist["Volume"].iloc[-6:-1].mean())
                if vol_avg > 0:
                    vol_ratio = round(vol_today / vol_avg, 2)

            result[ticker] = {
                "price":      round(curr, 2),
                "change_1d":  round(chg_1d, 2),
                "change_1w":  round(chg_1w, 2) if chg_1w is not None else None,
                "vol_ratio":  vol_ratio,
            }
        except Exception:
            pass
    return result


def fetch_market_summary() -> dict:
    """Hämtar dagens rörelse för OMXS30 och SPY."""
    summary = {}
    for name, ticker in [("OMXS30", OMXS30_PROXY), ("SPY", SPY_TICKER)]:
        try:
            time.sleep(0.3)
            hist = yf.Ticker(ticker).history(period="10d", auto_adjust=True)
            if hist.empty or len(hist) < 2:
                continue
            close     = hist["Close"]
            curr      = float(close.iloc[-1])
            prev      = float(close.iloc[-2])
            chg_1d    = (curr / prev - 1) * 100
            week_idx  = max(0, len(close) - 6)
            chg_1w    = (curr / float(close.iloc[week_idx]) - 1) * 100

            # YTD: sista handelsdagen föregående år
            prev_year = hist[hist.index.year == (date.today().year - 1)]
            ytd_start = float(prev_year["Close"].iloc[-1]) if not prev_year.empty else curr
            chg_ytd   = (curr / ytd_start - 1) * 100

            summary[name] = {
                "ticker":    ticker,
                "price":     round(curr, 2),
                "change_1d": round(chg_1d, 2),
                "change_1w": round(chg_1w, 2),
                "change_ytd":round(chg_ytd, 2),
            }
        except Exception:
            pass
    return summary


# ══════════════════════════════════════════════════════════════
# LADDA SÖNDAGENS SCORES
# ══════════════════════════════════════════════════════════════

def load_scores_for_holdings(holding_tickers: list) -> dict:
    """
    Hämtar senaste scores från söndagens scan för dina innehav.
    Returnerar {ticker: {score_total, rank, entry_signal, confidence_label, ...}}
    """
    csvs = sorted(
        Path(config.REPORT_DIR).glob("scored_universe_*.csv"),
        reverse=True
    )
    if not csvs:
        return {}

    try:
        df = pd.read_csv(csvs[0])
        df["ticker"] = df["ticker"].str.upper()
        filtered = df[df["ticker"].isin([t.upper() for t in holding_tickers])]
        return filtered.set_index("ticker").to_dict("index")
    except Exception:
        return {}


# ══════════════════════════════════════════════════════════════
# HOLD/SÄLJ-ANALYS
# ══════════════════════════════════════════════════════════════

def analyze_hold_sell(
    holdings:    pd.DataFrame,
    prices:      dict,
    scores:      dict,
    universe_size: int = 200,
) -> list:
    """
    Kombinerar söndagens score med daglig prisrörelse för varje innehav.

    Returnerar lista av dicts med:
      ticker, price, change_1d, change_1w, total_pnl_pct,
      score, rank, recommendation, reason, urgency (1=hög, 3=låg)
    """
    results = []

    for _, row in holdings.iterrows():
        ticker = str(row["ticker"]).upper()
        cost   = row.get("cost_basis")
        shares = row.get("shares", 0)
        price_data  = prices.get(ticker, {})
        score_data  = scores.get(ticker, {})

        price   = price_data.get("price")
        chg_1d  = price_data.get("change_1d")
        chg_1w  = price_data.get("change_1w")
        score   = score_data.get("score_total")
        rank    = score_data.get("rank")
        entry   = score_data.get("entry_signal", "—")
        conf    = score_data.get("confidence_label", "—")
        ma200   = score_data.get("price_vs_ma200")

        # P&L
        total_pnl_pct = ((price / float(cost)) - 1) * 100 if (price and cost and float(cost) > 0) else None
        market_value  = price * float(shares) if price else None
        pnl_today_sek = market_value * (chg_1d / 100) if (market_value and chg_1d) else None

        # Recommendation logic
        rec, reason, urgency = _build_evening_rec(
            ticker, score, rank, chg_1d, chg_1w,
            total_pnl_pct, ma200, universe_size
        )

        results.append({
            "ticker":        ticker,
            "name":          score_data.get("name", ticker)[:25],
            "price":         price,
            "change_1d":     chg_1d,
            "change_1w":     chg_1w,
            "total_pnl_pct": total_pnl_pct,
            "pnl_today_sek": pnl_today_sek,
            "market_value":  market_value,
            "score":         score,
            "rank":          rank,
            "entry_signal":  entry,
            "confidence":    conf,
            "recommendation":rec,
            "reason":        reason,
            "urgency":       urgency,
        })

    # Sortera: urgency 1 (hög) → 3 (låg), sedan total P&L fallande
    return sorted(results, key=lambda x: (x["urgency"], -(x.get("total_pnl_pct") or 0)))


def _build_evening_rec(
    ticker, score, rank, chg_1d, chg_1w,
    total_pnl_pct, ma200, universe_size
) -> tuple[str, str, int]:
    """Bestämmer kvällsrekommendation. Returnerar (rec, reason, urgency 1-3)."""

    if score is None:
        return "OKÄND", "Ingen score från senaste scan", 3

    percentile = 100 * (1 - (rank - 1) / max(universe_size, 1)) if rank else 50
    top_pct    = 100 - percentile

    # === SÄLJ-signaler (urgency 1) ===
    if chg_1d is not None and chg_1d <= -6:
        return "SÄLJ/MINSKA", f"Ned {chg_1d:.1f}% idag – kräver åtgärd", 1

    if score < SELL_SCORE_THRESH:
        return "SÄLJ", f"Score {score:.0f} – kraftigt försämrade fundamenta", 1

    if ma200 is not None and ma200 < -0.05:
        return "SÄLJ/MINSKA", f"Under MA200 ({ma200*100:.0f}%) – trendbrott", 1

    if total_pnl_pct is not None and total_pnl_pct <= -20:
        return "SÄLJ", f"Ner {total_pnl_pct:.0f}% sedan köp – stopploss-nivå", 1

    # === Minska (urgency 2) ===
    if chg_1d is not None and chg_1d <= -3:
        return "BEVAKA", f"Ned {chg_1d:.1f}% idag – håll ett öga", 2

    if chg_1w is not None and chg_1w <= -5:
        return "MINSKA", f"Ned {chg_1w:.1f}% denna vecka", 2

    if score < REDUCE_SCORE_THRESH:
        return "MINSKA", f"Score {score:.0f} – under medel (topp {top_pct:.0f}%)", 2

    # === Ta hem vinst (urgency 2) ===
    if total_pnl_pct is not None and total_pnl_pct >= 100:
        return "TA HEM HALVA", f"Upp {total_pnl_pct:.0f}% sedan köp", 2

    # === Behåll / Köp mer (urgency 3) ===
    if score >= STRONG_HOLD_THRESH and percentile >= 70:
        return "BEHÅLL STARKT", f"Score {score:.0f}, topp {top_pct:.0f}%", 3

    if percentile >= config.BUY_MORE_PERCENTILE:
        return "KÖP MER", f"Topp {top_pct:.0f}% av universumet", 3

    if percentile >= config.HOLD_PERCENTILE:
        return "BEHÅLL", f"Topp {top_pct:.0f}%", 3

    return "MINSKA", f"Under medel – topp {top_pct:.0f}%", 2


# ══════════════════════════════════════════════════════════════
# BEVAKNINGSLISTA – kvällsanalys
# ══════════════════════════════════════════════════════════════

def build_watchlist_evening_section(
    watchlist_items: list,
    prices:          dict,
    scores:          dict,
    universe_size:   int = 200,
) -> str:
    """
    Kvällsanalys av bevakningslistan.
    Visar pris, 1d/1w rörelse, score, rekommendation och nästa rapport.
    """
    if not watchlist_items:
        return ""

    lines = ["## ⭐ Bevakningslista – kvällsanalys\n"]
    lines.append("_Aktier du bevakar extra noga – inkl. köp/sälj-bedömning och nästa rapport._\n")
    lines.append("| | Ticker | Bolag | Idag | Vecka | Score | Rekommendation | Nästa rapport |")
    lines.append("|---|--------|-------|------|-------|-------|----------------|---------------|")

    for item in watchlist_items:
        ticker     = item["ticker"]
        name       = item.get("name", ticker)[:20]
        pd_data    = prices.get(ticker, {})
        sc_data    = scores.get(ticker, {})

        price   = pd_data.get("price")
        chg_1d  = pd_data.get("change_1d")
        chg_1w  = pd_data.get("change_1w")
        score   = sc_data.get("score_total")
        rank    = sc_data.get("rank")
        entry   = sc_data.get("entry_signal", "—")
        ma200   = sc_data.get("price_vs_ma200")

        chg_1d_s = f"{chg_1d:+.1f}%" if chg_1d is not None else "—"
        chg_1w_s = f"{chg_1w:+.1f}%" if chg_1w is not None else "—"
        d1_icon  = ("🟢" if chg_1d >= 0 else "🔴") if chg_1d is not None else "⚪"
        score_s  = f"{score:.0f}" if score is not None else "—"

        # Rekommendation (samma logik som portföljen)
        rec, _, _ = _build_evening_rec(
            ticker, score, rank, chg_1d, chg_1w, None, ma200, universe_size
        )
        rec_icon = {
            "SÄLJ": "🔴", "SÄLJ/MINSKA": "🔴",
            "TA HEM HALVA": "🟠", "MINSKA": "🟡", "BEVAKA": "🟡",
            "BEHÅLL": "🔵", "BEHÅLL STARKT": "🔵", "KÖP MER": "🟢",
            "KÖP": "🟢",
        }.get(rec, "⚪")

        # Earnings
        earn_s = "—"
        try:
            earn_date = sc_data.get("next_earnings_date") or sc_data.get("earnings_date")
            if earn_date:
                days = (pd.Timestamp(earn_date).date() - date.today()).days
                if 0 <= days <= 90:
                    earn_s = f"{days}d"
        except Exception:
            pass

        lines.append(
            f"| {rec_icon} | **`{ticker}`** | {name} | "
            f"{d1_icon} {chg_1d_s} | {chg_1w_s} | {score_s} | "
            f"**{rec}** | {earn_s} |"
        )

    return "\n".join(lines) + "\n"


# ══════════════════════════════════════════════════════════════
# FREDAGS-SAMMANFATTNING
# ══════════════════════════════════════════════════════════════

def build_friday_summary(
    analysis:       list,
    market:         dict,
    earnings_soon:  pd.DataFrame,
    news_by_ticker: dict,
    ticker_names:   dict,
) -> str:
    """
    Fredagsspecifik veckosammanfattning.
    Visar portföljens veckoavkastning, bästa/sämsta, marknadsfaktoid och nyhetshöjdpunkter.
    Notera: generella marknadsnyheter (global_news/swedish_news) skrivs ut separat
    via format_market_news_section_md() och inkluderas inte här.
    """
    lines = ["## 📅 Fredagssammanfattning – Veckans resultat\n"]

    # Portfölj-veckoavkastning
    week_rows = [(a["ticker"], a.get("change_1w"), a.get("market_value")) for a in analysis
                 if a.get("change_1w") is not None]
    if week_rows:
        mv_total = sum(mv or 0 for _, _, mv in week_rows if mv)
        if mv_total > 0:
            w_pct = sum((chg / 100) * (mv or 0) for _, chg, mv in week_rows) / mv_total * 100
            icon  = "🟢" if w_pct >= 0 else "🔴"
            lines.append(f"**Portfölj denna vecka: {icon} {w_pct:+.1f}%**\n")

        sorted_week = sorted(week_rows, key=lambda x: x[1], reverse=True)
        best  = sorted_week[0]
        worst = sorted_week[-1]
        lines.append(f"🏆 **Bäst:** `{best[0]}` {best[1]:+.1f}%  \n"
                     f"📉 **Sämst:** `{worst[0]}` {worst[1]:+.1f}%\n")

    # Marknadsindex vecka
    if market:
        lines.append("| Index | Vecka | YTD |")
        lines.append("|-------|-------|-----|")
        for name, d in market.items():
            w1  = d.get("change_1w", 0)
            ytd = d.get("change_ytd", 0)
            icon = "🟢" if w1 >= 0 else "🔴"
            lines.append(f"| {name} | {icon} {w1:+.1f}% | {ytd:+.1f}% |")
        lines.append("")

    # Nästa veckas rapporter (earnings preview)
    if earnings_soon is not None and not earnings_soon.empty:
        next_week = earnings_soon[earnings_soon.get("days_until", 99) <= 7] \
            if "days_until" in earnings_soon.columns else earnings_soon
        if not next_week.empty:
            lines.append("**Nästa veckas rapporter:**")
            for _, row in next_week.iterrows():
                ticker = row.get("ticker", "")
                d      = str(row.get("date", ""))[:10]
                lines.append(f"- `{ticker}` – {d}")
            lines.append("")

    # Bolagsspecifika nyhetshöjdpunkter (max 4 stycken)
    if news_by_ticker:
        lines.append("**Veckans bolagsnyhetshöjdpunkter:**")
        shown = 0
        for ticker, articles in news_by_ticker.items():
            if not articles or shown >= 4:
                break
            name = ticker_names.get(ticker, ticker)
            a    = articles[0]
            icon = "🔴" if a["age_hours"] < 24 else "🟡" if a["age_hours"] < 72 else "⚪"
            lines.append(
                f"{icon} **`{ticker}`** [{a['headline']}]({a['url']})  \n"
                f"   _{a['source']} · {a['datetime_str']}_"
            )
            shown += 1
        lines.append("")

    # Veckofaktoid
    factoid = news_fetcher.get_weekly_factoid()
    lines.append(f"> 💡 **Veckans börstips:** {factoid}\n")

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════
# RAPPORT-BYGGARE
# ══════════════════════════════════════════════════════════════

def build_evening_report(
    analysis:        list,
    market:          dict,
    earnings_soon:   pd.DataFrame,
    watchlist_items: list  = None,
    wl_prices:       dict  = None,
    wl_scores:       dict  = None,
    universe_size:   int   = 200,
    stoploss_alerts: list  = None,
    news_by_ticker:  dict  = None,
    global_news:     list  = None,
    swedish_news:    list  = None,
    is_friday:       bool  = False,
) -> str:
    """Bygger kvällsrapporten."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    stoploss_alerts = stoploss_alerts or []
    news_by_ticker  = news_by_ticker  or {}
    global_news     = global_news     or []
    swedish_news    = swedish_news    or []

    # Beräkna portfölj-totaler
    total_value    = sum(a.get("market_value") or 0 for a in analysis)
    pnl_today_sek  = sum(a.get("pnl_today_sek") or 0 for a in analysis)
    pnl_today_pct  = (pnl_today_sek / (total_value - pnl_today_sek)) * 100 \
                     if total_value > 0 else 0

    n_sell    = sum(1 for a in analysis if "SÄLJ" in a["recommendation"].upper())
    n_reduce  = sum(1 for a in analysis if "MINSKA" in a["recommendation"].upper())
    n_hold    = sum(1 for a in analysis if "BEHÅLL" in a["recommendation"].upper())
    n_buymore = sum(1 for a in analysis if "KÖP MER" in a["recommendation"].upper())

    lines = [f"# 🌆 Kvällsrapport – {now}\n", "---\n"]

    # ── Stopploss-alerts ──────────────────────────────────────
    if stoploss_alerts:
        lines.append("## 🛑 STOPPLOSS-ALERTS\n")
        lines.append("> Följande innehav är ned mer än 15% från inköpspris.\n")
        for a in stoploss_alerts:
            lines.append(
                f"🛑 **`{a['ticker']}`** ned **{a['total_pct']:.1f}%** från "
                f"inköpspris {a['cost_basis']:.2f} (nu {a['price']:.2f})\n"
            )

    # ── Marknadsöversikt ──────────────────────────────────────
    if market:
        lines.append("## 🌍 Marknaden idag\n")
        lines.append("| Index | Idag | Vecka | YTD |")
        lines.append("|-------|------|-------|-----|")
        for name, d in market.items():
            d1  = d.get("change_1d", 0)
            w1  = d.get("change_1w", 0)
            ytd = d.get("change_ytd", 0)
            i1  = "🟢" if d1 >= 0 else "🔴"
            lines.append(
                f"| **{name}** | {i1} {d1:+.1f}% | {w1:+.1f}% | {ytd:+.1f}% |"
            )
        lines.append("")

    # ── Portfölj-dashboard ────────────────────────────────────
    lines.append("## 💼 Portfölj-dashboard\n")

    port_icon = "🟢" if pnl_today_pct >= 0 else "🔴"
    lines.append(
        f"**Idag: {port_icon} {pnl_today_pct:+.1f}%** "
        f"({'+'if pnl_today_sek>=0 else ''}{pnl_today_sek:,.0f} SEK)\n"
    )

    if analysis:
        lines.append(f"Reker: 🔴 {n_sell} SÄLJ · 🟡 {n_reduce} MINSKA · "
                     f"🔵 {n_hold} BEHÅLL · 🟢 {n_buymore} KÖP MER\n")
        lines.append("| | Ticker | Idag | Vecka | Totalt | Score | Rек. |")
        lines.append("|---|--------|------|-------|--------|-------|------|")

        for a in analysis:
            rec_icon = {
                "SÄLJ": "🔴", "SÄLJ/MINSKA": "🔴",
                "TA HEM HALVA": "🟠",
                "MINSKA": "🟡", "BEVAKA": "🟡",
                "BEHÅLL": "🔵", "BEHÅLL STARKT": "🔵",
                "KÖP MER": "🟢",
            }.get(a["recommendation"], "⚪")

            d1_s   = f"{a['change_1d']:+.1f}%" if a.get("change_1d") is not None else "—"
            w1_s   = f"{a['change_1w']:+.1f}%" if a.get("change_1w") is not None else "—"
            tot_s  = f"{a['total_pnl_pct']:+.1f}%" if a.get("total_pnl_pct") is not None else "—"
            sc_s   = f"{a['score']:.0f}" if a.get("score") is not None else "—"
            d1_col = "🟢" if (a.get("change_1d") or 0) >= 0 else "🔴"

            lines.append(
                f"| {rec_icon} | **`{a['ticker']}`** {a.get('name','')[:18]} | "
                f"{d1_col} {d1_s} | {w1_s} | {tot_s} | {sc_s} | "
                f"**{a['recommendation']}** |"
            )
        lines.append("")

    # ── Åtgärder (urgency 1 och 2) ────────────────────────────
    urgent = [a for a in analysis if a["urgency"] <= 2 and
              any(k in a["recommendation"].upper()
                  for k in ["SÄLJ", "MINSKA", "TA HEM"])]

    if urgent:
        lines.append("## ⚡ Rekommenderade åtgärder\n")
        for a in urgent:
            urgency_icon = "🚨" if a["urgency"] == 1 else "⚠️"
            lines.append(
                f"{urgency_icon} **`{a['ticker']}`** → **{a['recommendation']}**  \n"
                f"_{a['reason']}_\n"
            )
    else:
        lines.append("## ✅ Åtgärder\n\nInga akuta åtgärder rekommenderas idag.\n")

    # ── Earnings-påminnelse ───────────────────────────────────
    if earnings_soon is not None and not earnings_soon.empty:
        lines.append("## 📅 Kommande rapporter (14 dagar)\n")
        for _, row in earnings_soon.iterrows():
            days   = row.get("days_until", "?")
            ticker = row.get("ticker", "")
            d      = str(row.get("date", ""))[:10]
            est    = row.get("eps_estimate")
            est_s  = f" · EPS-estimat: {est:.2f}" if pd.notna(est or float('nan')) else ""
            lines.append(f"- **`{ticker}`** – {d} (om {days} dagar){est_s}")
        lines.append("")

    # ── Bevakningslista ───────────────────────────────────────
    if watchlist_items:
        wl_section = build_watchlist_evening_section(
            watchlist_items,
            wl_prices or {},
            wl_scores or {},
            universe_size,
        )
        if wl_section:
            lines.append(wl_section)

    # ── Nyheter (Finnhub) ─────────────────────────────────────
    if news_by_ticker:
        ticker_names = {}
        if analysis:
            ticker_names.update({a["ticker"]: a.get("name", a["ticker"]) for a in analysis})
        for item in (watchlist_items or []):
            ticker_names[item["ticker"]] = item.get("name", item["ticker"])
        news_md = news_fetcher.format_news_section_md(
            news_by_ticker, ticker_names=ticker_names, header="📰 Nyheter"
        )
        if news_md:
            lines.append(news_md)

    # ── Generella marknadsnyheter ────────────────────────────
    market_news_md = news_fetcher.format_market_news_section_md(
        global_news, swedish_news, compact=not is_friday
    )
    if market_news_md:
        lines.append(market_news_md)

    # ── Fredagssammanfattning ────────────────────────────────
    if is_friday:
        ticker_names = {a["ticker"]: a.get("name", a["ticker"]) for a in analysis}
        for item in (watchlist_items or []):
            ticker_names[item["ticker"]] = item.get("name", item["ticker"])
        lines.append(build_friday_summary(
            analysis, market, earnings_soon, news_by_ticker, ticker_names
        ))

    lines.append("---\n*⚠ Inte finansiell rådgivning. MarketScan kvällsrapport.*")
    return "\n".join(lines)


def build_email_subject(
    analysis:        list,
    market:          dict,
    stoploss_alerts: list = None,
    is_friday:       bool = False,
) -> str:
    mv   = sum(a.get("market_value") or 0 for a in analysis)
    pnl  = sum(a.get("pnl_today_sek") or 0 for a in analysis)
    pct  = (pnl / (mv - pnl)) * 100 if mv > 0 else 0
    omx  = market.get("OMXS30", {}).get("change_1d", 0)
    sign = "+" if pct >= 0 else ""
    date_s = date.today().strftime("%d %b")

    if stoploss_alerts:
        tickers = ", ".join(a["ticker"] for a in stoploss_alerts[:2])
        return f"🛑 Stopploss: {tickers} – {date_s}"

    n_sell = sum(1 for a in analysis if "SÄLJ" in a["recommendation"].upper())
    if n_sell > 0:
        tickers = ", ".join(a["ticker"] for a in analysis
                            if "SÄLJ" in a["recommendation"].upper())
        return f"🚨 Sälj-signal: {tickers} – {date_s}"

    if is_friday:
        return f"📅 Fredagssammanfattning {date_s} – Portfölj {sign}{pct:.1f}% · OMXS30 {omx:+.1f}%"

    return f"📊 {date_s} – Portfölj {sign}{pct:.1f}% · OMXS30 {omx:+.1f}%"


# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Kvällsrapport – portföljstatus och hold/sälj")
    parser.add_argument("--quiet",    action="store_true")
    parser.add_argument("--no-email", action="store_true")
    args = parser.parse_args()
    v = not args.quiet

    print("🌆 KVÄLLSRAPPORT")
    print("=" * 40)

    with logger.scan_logger("evening", verbose=v) as log:

        # 1. Ladda portfölj
        holdings = portfolio.load_holdings()
        if holdings.empty:
            print("ℹ Inga innehav i holdings.csv")
            return
        log["n_holdings"] = len(holdings)
        if v: print(f"  {len(holdings)} innehav")

        # 1b. Ladda bevakningslista
        watchlist_items   = wl.load_watchlist()
        wl_tickers        = [i["ticker"] for i in watchlist_items]
        if wl_tickers and v:
            print(f"  ⭐ {len(wl_tickers)} aktier i bevakningslistan")

        # 2. Hämta slutkurser (portfölj + bevakningslista)
        print("\n📥 Hämtar slutkurser...")
        tickers     = list(holdings["ticker"].str.upper())
        all_tickers = list(set(tickers + wl_tickers))
        prices      = fetch_closing_prices(all_tickers)
        # Separera portfölj- och bevakningspriser ur samma dict (båda kan använda samma dict)
        wl_prices   = {t: prices[t] for t in wl_tickers if t in prices}
        log["n_prices"] = len(prices)
        if v: print(f"  ✓ {len(prices)} priser hämtade")

        # 3. Hämta marknad
        print("🌍 Hämtar marknadsstatus...")
        market = fetch_market_summary()

        # 4. Hämta scores från söndagens scan
        scores = load_scores_for_holdings(tickers)
        universe_size = 200
        try:
            csvs = sorted(Path(config.REPORT_DIR).glob("scored_universe_*.csv"), reverse=True)
            if csvs:
                universe_size = len(pd.read_csv(csvs[0]))
        except Exception:
            pass

        # Scores för bevakningslistan
        wl_scores = load_scores_for_holdings(wl_tickers) if wl_tickers else {}

        # 5. Analysera hold/sälj
        analysis = analyze_hold_sell(holdings, prices, scores, universe_size)
        log["n_sell_signals"] = sum(1 for a in analysis if "SÄLJ" in a["recommendation"].upper())

        # 5b. Stopploss-alerts
        stoploss_alerts = detect_stoploss_alerts(holdings, prices)
        if stoploss_alerts and v:
            print(f"\n  🛑 {len(stoploss_alerts)} stopploss-alert(s)!")
        log["n_stoploss"] = len(stoploss_alerts)

        # 6. Earnings
        earnings_soon = pd.DataFrame()
        try:
            scored_df = pd.DataFrame(list(scores.values()))
            if "ticker" not in scored_df.columns:
                scored_df["ticker"] = list(scores.keys())
            earnings_soon = ec.upcoming_in_portfolio(holdings, scored_df, days_ahead=14)
        except Exception:
            pass

        # 7. Uppdatera paper trading med stängningspriser
        try:
            paper_trading.update_prices(close_after_weeks=4, verbose=False)
        except Exception:
            pass

        # 7b. Nyheter via Finnhub + RSS
        news_by_ticker = {}
        global_news    = []
        swedish_news   = []
        finnhub_key    = os.environ.get("FINNHUB_API_KEY", "")
        is_friday      = date.today().weekday() == 4  # 4 = fredag

        print("\n📰 Hämtar nyheter...")
        if finnhub_key:
            news_tickers = list(holdings["ticker"].str.upper()) + wl_tickers
            news_days    = 5 if is_friday else 1
            if news_tickers:
                news_by_ticker = news_fetcher.fetch_news_batch(
                    news_tickers, finnhub_key, days=news_days
                )
                if news_by_ticker and v:
                    print(f"  ✓ Bolagsnyheter för {len(news_by_ticker)} aktier")
            # Generella marknadsnyheter – fler på fredagar
            max_market = 5 if is_friday else 3
            global_news = news_fetcher.fetch_global_market_news(finnhub_key, max_articles=max_market)
            if global_news and v:
                print(f"  ✓ {len(global_news)} globala marknadsnyheter")
        else:
            if v:
                print("  ℹ FINNHUB_API_KEY ej satt – bolagsnyheter hoppas över")

        max_swedish  = 5 if is_friday else 3
        swedish_news = news_fetcher.fetch_swedish_market_news(max_articles=max_swedish)
        if swedish_news and v:
            print(f"  ✓ {len(swedish_news)} svenska börsnyheter")

        # 8. Bygg rapport
        report  = build_evening_report(
            analysis, market, earnings_soon,
            watchlist_items  = watchlist_items,
            wl_prices        = wl_prices,
            wl_scores        = wl_scores,
            universe_size    = universe_size,
            stoploss_alerts  = stoploss_alerts,
            news_by_ticker   = news_by_ticker,
            global_news      = global_news,
            swedish_news     = swedish_news,
            is_friday        = is_friday,
        )
        subject = build_email_subject(analysis, market, stoploss_alerts, is_friday)

        # Spara
        Path(config.REPORT_DIR).mkdir(exist_ok=True)
        report_path = Path(config.REPORT_DIR) / f"evening_{date.today()}.md"
        report_path.write_text(report, encoding="utf-8")
        log["report_path"] = str(report_path)
        if v: print(f"\n  Rapport: {report_path}")

        # 9. Skicka email (alltid)
        if not args.no_email and alerts.email_configured():
            print(f"✉ Skickar: {subject}")
            sender, password, to = alerts._get_email_config()
            if sender and password:
                try:
                    msg = MIMEMultipart("alternative")
                    msg["Subject"] = subject
                    msg["From"]    = f"MarketScan <{sender}>"
                    msg["To"]      = to
                    msg.attach(MIMEText(report, "plain", "utf-8"))
                    html_body = alerts._markdown_to_html(report)
                    full_html = (
                        "<html><body style=\"font-family:sans-serif;"
                        "max-width:680px;margin:0 auto;padding:20px\">"
                        + html_body
                        + "<div style=\"margin-top:24px;font-size:11px;color:#999\">"
                        "Automatisk rapport från MarketScan. Inte finansiell rådgivning."
                        "</div></body></html>"
                    )
                    msg.attach(MIMEText(full_html, "html", "utf-8"))
                    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
                        s.login(sender, password)
                        s.sendmail(sender, to, msg.as_string())
                    print(f"  ✉ Email skickat till {to}")
                except Exception as e:
                    print(f"  ⚠ Email-fel: {e}")
        elif not alerts.email_configured():
            print("  ℹ Email ej konfigurerat")

        # Terminal-sammanfattning
        print(f"\n{'─'*40}")
        n_sell   = sum(1 for a in analysis if "SÄLJ" in a["recommendation"].upper())
        n_reduce = sum(1 for a in analysis if "MINSKA" in a["recommendation"].upper())
        n_hold   = sum(1 for a in analysis if "BEHÅLL" in a["recommendation"].upper())
        print(f"  Stopploss:  {len(stoploss_alerts)}")
        print(f"  SÄLJ:       {n_sell}")
        print(f"  MINSKA:     {n_reduce}")
        print(f"  BEHÅLL:     {n_hold}")
        print(f"  Nyheter:    {len(news_by_ticker)} aktier")
        if is_friday:
            print("  📅 Fredagssammanfattning inkluderad")


if __name__ == "__main__":
    main()
