"""
daily_scan.py
=============
Daglig portföljkoll – körs varje vardag kl 18:00.

Gör INTE en full scan av 535 aktier (det tar för lång tid).
Kollar bara:
  1. Hur dina innehav gått idag
  2. Marknadsläget (OMXS30, SPY)
  3. Om något kräver omedelbar åtgärd (SÄLJ-signal)
  4. Benchmark-jämförelse (du vs OMXS30 vs SPY)
  5. Skickar kompakt email-update

Körs av GitHub Actions varje vardag kl 18:00 CET.
Kör manuellt: python daily_scan.py
"""

import sys
import time
import argparse
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import numpy as np
import yfinance as yf

import config
import portfolio
import alerts
import logger
import paper_trading


# OMXS30-proxy: XACT OMXS30 ETF (bästa tillgängliga via yfinance)
OMXS30_PROXY = "XACTOMXS3.ST"
SPY_TICKER   = "SPY"


# ══════════════════════════════════════════════════════════════
# DATAHÄMTNING
# ══════════════════════════════════════════════════════════════

def fetch_today_prices(tickers: list) -> dict:
    """
    Hämtar dagens prisrörelse för en lista tickers.
    Returnerar {ticker: {"price": x, "change_pct": y, "prev_close": z}}
    """
    result = {}
    for ticker in tickers:
        try:
            time.sleep(0.3)
            hist = yf.Ticker(ticker).history(period="2d", auto_adjust=True)
            if len(hist) < 2:
                continue
            prev  = float(hist["Close"].iloc[-2])
            curr  = float(hist["Close"].iloc[-1])
            change = (curr / prev - 1) * 100
            result[ticker] = {
                "price":      round(curr, 2),
                "prev_close": round(prev, 2),
                "change_pct": round(change, 2),
            }
        except Exception:
            pass
    return result


def fetch_benchmark_performance() -> dict:
    """
    Hämtar daglig och YTD-avkastning för OMXS30 och SPY.
    """
    benchmarks = {}
    for name, ticker in [("OMXS30", OMXS30_PROXY), ("SPY", SPY_TICKER)]:
        try:
            time.sleep(0.3)
            hist = yf.Ticker(ticker).history(period="1y", auto_adjust=True)
            if hist.empty:
                continue

            curr  = float(hist["Close"].iloc[-1])
            prev  = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else curr

            # YTD: från sista handelsdagen föregående år
            year_start = hist[hist.index.year == date.today().year]
            ytd_start  = float(year_start["Close"].iloc[0]) if not year_start.empty else curr

            # 1-månads
            m1_idx = max(0, len(hist) - 22)
            m1_start = float(hist["Close"].iloc[m1_idx])

            benchmarks[name] = {
                "ticker":     ticker,
                "price":      round(curr, 2),
                "change_1d":  round((curr / prev - 1) * 100, 2),
                "change_1m":  round((curr / m1_start - 1) * 100, 2),
                "change_ytd": round((curr / ytd_start - 1) * 100, 2),
            }
        except Exception:
            pass

    return benchmarks


# ══════════════════════════════════════════════════════════════
# ALERT-DETEKTERING
# ══════════════════════════════════════════════════════════════

def detect_alerts(
    holdings_df:   pd.DataFrame,
    prices_today:  dict,
) -> list:
    """
    Söker efter situationer som kräver omedelbar uppmärksamhet.

    Triggers:
    - Fall > 5% idag           → BEVAKA
    - Fall > 8% idag           → SÄLJ/MINSKA
    - Totalt P&L < -15%        → BEVAKA
    - Totalt P&L < -25%        → SÄLJ-signal
    """
    found = []

    for _, row in holdings_df.iterrows():
        ticker = row["ticker"]
        today  = prices_today.get(ticker, {})
        change = today.get("change_pct")
        curr   = today.get("price")

        if change is None:
            continue

        # Daglig rörelse
        if change <= -8:
            found.append({
                "ticker":   ticker,
                "message":  f"Föll {change:.1f}% idag",
                "action":   "SÄLJ/MINSKA",
                "priority": 1,
            })
        elif change <= -5:
            found.append({
                "ticker":   ticker,
                "message":  f"Föll {change:.1f}% idag",
                "action":   "BEVAKA",
                "priority": 2,
            })

        # Total P&L (om kostnadsbas finns)
        cost = row.get("cost_basis")
        if curr and cost and cost > 0:
            total_pnl_pct = (curr / cost - 1) * 100
            if total_pnl_pct <= -25:
                found.append({
                    "ticker":   ticker,
                    "message":  f"Ner {total_pnl_pct:.0f}% sedan köp",
                    "action":   "SÄLJ",
                    "priority": 1,
                })
            elif total_pnl_pct <= -15:
                found.append({
                    "ticker":   ticker,
                    "message":  f"Ner {total_pnl_pct:.0f}% sedan köp",
                    "action":   "BEVAKA",
                    "priority": 2,
                })

    # Sortera: högst prioritet först
    return sorted(found, key=lambda x: x["priority"])


# ══════════════════════════════════════════════════════════════
# BENCHMARK-JÄMFÖRELSE
# ══════════════════════════════════════════════════════════════

def calc_portfolio_vs_benchmark(
    holdings_df:  pd.DataFrame,
    prices_today: dict,
    benchmarks:   dict,
) -> dict:
    """
    Jämför din portföljs dagliga rörelse med OMXS30 och SPY.
    """
    if holdings_df.empty:
        return {}

    # Beräkna viktad daglig avkastning för portföljen
    weighted_changes = []
    total_value      = 0

    for _, row in holdings_df.iterrows():
        ticker = row["ticker"]
        today  = prices_today.get(ticker, {})
        price  = today.get("price")
        change = today.get("change_pct")
        shares = row.get("shares", 0)

        if price and change is not None and shares:
            val = price * shares
            weighted_changes.append((change, val))
            total_value += val

    if not weighted_changes or total_value == 0:
        return {}

    port_change_today = sum(c * v for c, v in weighted_changes) / total_value

    result = {
        "portfolio_1d":  round(port_change_today, 2),
        "total_value":   round(total_value, 0),
        "vs_omxs30_1d":  None,
        "vs_spy_1d":     None,
    }

    if "OMXS30" in benchmarks:
        omx_1d = benchmarks["OMXS30"]["change_1d"]
        result["vs_omxs30_1d"] = round(port_change_today - omx_1d, 2)

    if "SPY" in benchmarks:
        spy_1d = benchmarks["SPY"]["change_1d"]
        result["vs_spy_1d"] = round(port_change_today - spy_1d, 2)

    return result


# ══════════════════════════════════════════════════════════════
# PORTFOLIO ENRICHMENT
# ══════════════════════════════════════════════════════════════

def enrich_portfolio_with_today(
    holdings_df:  pd.DataFrame,
    prices_today: dict,
) -> pd.DataFrame:
    """Lägger till dagens prisrörelse på varje innehav."""
    df = holdings_df.copy()

    prices_list  = []
    changes_list = []
    pnl_today    = []

    for _, row in df.iterrows():
        today  = prices_today.get(row["ticker"], {})
        price  = today.get("price")
        change = today.get("change_pct")

        prices_list.append(price)
        changes_list.append(change)

        # P&L today (SEK)
        shares = row.get("shares", 0)
        prev   = today.get("prev_close")
        if price and prev and shares:
            pnl_today.append((price - prev) * shares)
        else:
            pnl_today.append(None)

    df["current_price"]  = prices_list
    df["pnl_pct_today"]  = changes_list
    df["pnl_today_sek"]  = pnl_today

    return df


# ══════════════════════════════════════════════════════════════
# RAPPORT-BYGGARE
# ══════════════════════════════════════════════════════════════

def build_daily_report(
    holdings_df:  pd.DataFrame,
    benchmarks:   dict,
    port_vs_bench: dict,
    found_alerts:  list,
) -> str:
    """Bygger markdown-rapporten för daglig uppdatering."""
    today_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# 📈 Daglig uppdatering – {today_str}\n",
        "---\n",
    ]

    # Marknadsöversikt
    lines.append("## 🌍 Marknaden idag\n")
    lines.append("| Index | Idag | 1 månad | YTD |")
    lines.append("|-------|------|---------|-----|")
    for name, data in benchmarks.items():
        d1  = data.get("change_1d",  0)
        m1  = data.get("change_1m",  0)
        ytd = data.get("change_ytd", 0)
        s1  = "+" if d1  >= 0 else ""; sm = "+" if m1  >= 0 else ""; sy = "+" if ytd >= 0 else ""
        lines.append(f"| {name} ({data['ticker']}) | **{s1}{d1:.1f}%** | {sm}{m1:.1f}% | {sy}{ytd:.1f}% |")

    # Din portfölj vs benchmark
    if port_vs_bench:
        pd_1d = port_vs_bench.get("portfolio_1d", 0)
        sign  = "+" if pd_1d >= 0 else ""
        lines.append(f"\n**Din portfölj idag: {sign}{pd_1d:.1f}%**  ")
        if port_vs_bench.get("vs_omxs30_1d") is not None:
            diff = port_vs_bench["vs_omxs30_1d"]
            sign = "+" if diff >= 0 else ""
            lines.append(f"vs OMXS30: {sign}{diff:.1f}pp  ")
        if port_vs_bench.get("vs_spy_1d") is not None:
            diff = port_vs_bench["vs_spy_1d"]
            sign = "+" if diff >= 0 else ""
            lines.append(f"vs SPY: {sign}{diff:.1f}pp")

    # Akuta alerts
    if found_alerts:
        lines.append("\n## 🚨 Kräver uppmärksamhet\n")
        for a in found_alerts:
            icon = "🔴" if a["action"] in ("SÄLJ", "SÄLJ/MINSKA") else "🟡"
            lines.append(f"- {icon} **`{a['ticker']}`**: {a['message']} → **{a['action']}**")
        lines.append("")
    else:
        lines.append("\n✅ _Inga akuta signaler idag_\n")

    # Portföljtabell
    if not holdings_df.empty:
        lines.append("## 💼 Portfölj\n")
        lines.append("| Ticker | Pris | Idag | P&L totalt | Signal |")
        lines.append("|--------|------|------|------------|--------|")

        for _, row in holdings_df.iterrows():
            price   = row.get("current_price")
            change  = row.get("pnl_pct_today")
            cost    = row.get("cost_basis")
            rec     = row.get("recommendation", "—")

            # Total P&L
            if price and cost and cost > 0:
                total_pnl = (price / cost - 1) * 100
                ts = "+" if total_pnl >= 0 else ""
                total_s = f"{ts}{total_pnl:.1f}%"
            else:
                total_s = "—"

            cs = f"{'+'  if change >= 0 else ''}{change:.1f}%" if change is not None else "—"
            ps = f"{price:.2f}" if price else "—"

            lines.append(
                f"| `{row['ticker']}` | {ps} | {cs} | {total_s} | {rec} |"
            )

    lines.append("\n---")
    lines.append("*⚠ Inte finansiell rådgivning. Automatisk rapport från MarketScan.*")

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Daglig portföljuppdatering")
    parser.add_argument("--quiet",    action="store_true")
    parser.add_argument("--no-email", action="store_true", help="Skicka ej email")
    args = parser.parse_args()
    v = not args.quiet

    print("📈 DAGLIG SCAN")
    print("=" * 40)

    with logger.scan_logger("daily", verbose=v) as log:

        # 1. Ladda portfölj
        holdings = portfolio.load_holdings()
        if holdings.empty:
            print("ℹ Inga innehav i holdings.csv")
            log["n_holdings"] = 0
            return
        print(f"   {len(holdings)} innehav laddade")
        log["n_holdings"] = len(holdings)

        # 2. Hämta dagens priser
        print("📥 Hämtar priser...")
        tickers      = list(holdings["ticker"])
        prices_today = fetch_today_prices(tickers)
        log["n_prices"] = len(prices_today)

        # 3. Berika portfölj med dagens data
        holdings = enrich_portfolio_with_today(holdings, prices_today)

        # 4. Hämta benchmark
        print("🌍 Hämtar benchmark...")
        benchmarks = fetch_benchmark_performance()
        log["benchmarks"] = list(benchmarks.keys())

        # 5. Portfölj vs benchmark
        port_vs_bench = calc_portfolio_vs_benchmark(holdings, prices_today, benchmarks)

        # 6. Detektera alerts
        found_alerts = detect_alerts(holdings, prices_today)
        log["n_alerts"] = len(found_alerts)

        if found_alerts and v:
            print(f"⚠  {len(found_alerts)} alert(s) detekterade:")
            for a in found_alerts:
                print(f"   {a['ticker']}: {a['message']} → {a['action']}")

        # 7. Uppdatera paper trading priser
        paper_trading.update_prices(verbose=False)

        # 8. Bygg rapport
        report = build_daily_report(holdings, benchmarks, port_vs_bench, found_alerts)

        # Spara rapport
        Path("reports").mkdir(exist_ok=True)
        today_str = date.today().isoformat()
        report_path = Path(f"reports/daily_{today_str}.md")
        report_path.write_text(report, encoding="utf-8")
        log["report_path"] = str(report_path)

        # 9. Skicka email
        if not args.no_email and alerts.email_configured():
            print("✉ Skickar daglig email...")
            alerts.send_daily_update(
                portfolio_df   = holdings,
                alerts         = found_alerts,
                omxs30_change  = benchmarks.get("OMXS30", {}).get("change_1d"),
                spy_change     = benchmarks.get("SPY", {}).get("change_1d"),
            )
        elif not args.no_email:
            print("ℹ Email ej konfigurerat – rapport sparad lokalt")

        # Skriv ut daglig sammanfattning
        if v:
            print(f"\n{'─'*40}")
            if port_vs_bench:
                pd_1d = port_vs_bench.get("portfolio_1d", 0)
                sign = "+" if pd_1d >= 0 else ""
                print(f"  Portfölj idag:  {sign}{pd_1d:.1f}%")
                if port_vs_bench.get("vs_omxs30_1d") is not None:
                    diff = port_vs_bench["vs_omxs30_1d"]
                    sign = "+" if diff >= 0 else ""
                    print(f"  vs OMXS30:      {sign}{diff:.1f}pp")
            print(f"  Alerts:         {len(found_alerts)}")
            print(f"  Rapport:        {report_path}")


if __name__ == "__main__":
    main()
