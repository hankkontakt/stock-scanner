"""
morning_scan.py
===============
Vardaglig morgonkoll kl 09:35 CET.

Tre saker:
  1. CRASH-ALERT      – öppnar något av dina innehav ned >3% / >6%?
  2. STARK UPPGÅNG    – öppnar något av dina innehav upp >3%? (ta hem vinst?)
  3. KÖPMÖJLIGHETER   – topp-50 från söndagens scan som har bra entry just nu

Skickar email:
  - Alltid om det finns alerts (crash, uppgång, köpmöjlighet)
  - Tyst (inget email) om allt är normalt och inga signaler finns

Tidszoner:
  - Stockholmsbörsen öppnar 09:00 CET  → vi kör 09:35 (35 min in, öppningsgap satt)
  - NYSE öppnar 15:30 CET              → US-aktier: använder igårkvällens stängning
  - Europeiska börser: realtidsdata tillgänglig

Kör manuellt: python morning_scan.py
GitHub Actions: morning_scan.yml (vardag 08:35 UTC = 09:35 CET vinter, 10:35 sommartid)
"""

import sys
import time
import argparse
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

import config
import alerts
import logger
import portfolio
import earnings_calendar as ec

# ── Trösklar ──────────────────────────────────────────────────────────────
CRASH_WARN_PCT    = -3.0   # % – varning (gult)
CRASH_SELL_PCT    = -6.0   # % – sälj-signal (rött)
SURGE_NOTIFY_PCT  = +3.0   # % – stark uppgång, notifiera
SURGE_TAKEHALF    = +8.0   # % – uppgång så stor att "ta hem halva" är aktuellt
MORNING_TOP_N     = 50     # Antal aktier från söndags-scan att kontrollera

# ── US börser stänger vid 22:00 CET, öppnar 15:30 CET ──────────────────────
US_SUFFIXES  = {"", None}   # Inga suffix = US
EU_OPEN_HOUR = 9            # Europeiska börser öppnar ~09:00 CET


# ══════════════════════════════════════════════════════════════
# LADDA SÖNDAGENS SCAN
# ══════════════════════════════════════════════════════════════

def load_top50_from_sunday() -> tuple[pd.DataFrame, str]:
    """
    Läser senaste scored_universe_*.csv och returnerar topp-50.
    Returnerar (df, käll-datum) eller (tom df, "").
    """
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
        # Sortera på score_total om det finns
        if "score_total" in df.columns:
            df = df.sort_values("score_total", ascending=False)
        return df.head(MORNING_TOP_N).copy(), date_str
    except Exception as e:
        print(f"  ⚠ Kunde inte läsa {latest}: {e}")
        return pd.DataFrame(), ""


# ══════════════════════════════════════════════════════════════
# PRISHÄMTNING
# ══════════════════════════════════════════════════════════════

def is_us_ticker(ticker: str) -> bool:
    """US-aktier har inget suffix (AAPL, MSFT) eller specifika US-suffix."""
    return "." not in ticker


def fetch_opening_moves(tickers: list, verbose: bool = True) -> dict:
    """
    Hämtar procentuell rörelse sedan igår för varje ticker.

    För europeiska aktier: dagens rörelse (börsen öppen)
    För US-aktier: igårkvällens stängning vs dagen innan
                   (NYSE inte öppen kl 09:35 CET)
    """
    result = {}
    eu_tickers = [t for t in tickers if not is_us_ticker(t)]
    us_tickers = [t for t in tickers if is_us_ticker(t)]

    if verbose:
        print(f"  Hämtar {len(eu_tickers)} EU + {len(us_tickers)} US-tickers...")

    # Hämta 3 dagars data för att täcka helger
    all_tickers = eu_tickers + us_tickers
    for ticker in all_tickers:
        try:
            time.sleep(0.25)
            hist = yf.Ticker(ticker).history(period="3d", auto_adjust=True)
            if hist.empty or len(hist) < 2:
                continue

            curr  = float(hist["Close"].iloc[-1])
            prev  = float(hist["Close"].iloc[-2])
            chg   = (curr / prev - 1) * 100

            # Volym-ratio (jämför med 5-dagars snitt om vi har det)
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
                "data_fresh": not is_us_ticker(ticker),  # EU = realtid, US = igår
            }
        except Exception:
            pass

    return result


# ══════════════════════════════════════════════════════════════
# ALERT-DETEKTERING
# ══════════════════════════════════════════════════════════════

def detect_portfolio_alerts(
    holdings: pd.DataFrame,
    price_moves: dict,
) -> dict:
    """
    Klassificerar rörelser i dina innehav.

    Returnerar:
    {
      "crash":   [{"ticker", "change_pct", "price", "action", "msg"}, ...],
      "surge":   [{"ticker", "change_pct", "price", "action", "msg"}, ...],
      "normal":  [{"ticker", "change_pct", "price"}, ...],
    }
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

def find_opportunities(
    top50:       pd.DataFrame,
    price_moves: dict,
    holdings:    pd.DataFrame,
) -> list:
    """
    Hittar köpmöjligheter bland topp-50 som:
      - Inte redan finns i portföljen
      - Har STARK eller OK entry-signal från söndagens scan
      - Öppnat i "sweet spot": pullback -2% till -6% från föregående stängning
        (dipp i upptrend) ELLER nära en breakout (+1% till +4%)
    """
    portfolio_tickers = set(holdings["ticker"].str.upper()) if not holdings.empty else set()
    opportunities = []

    for _, row in top50.iterrows():
        ticker = str(row.get("ticker", "")).upper()

        # Hoppa över egna innehav
        if ticker in portfolio_tickers:
            continue

        entry_signal = str(row.get("entry_signal", "")).upper()
        score        = row.get("score_total", 0)
        move         = price_moves.get(ticker, {})
        chg          = move.get("change_pct")

        if chg is None or score < 60:
            continue

        # Dipp i upptrend: aktien fallit 2-8% idag men är stark fundamentalt
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
        # Breakout: aktien stiger med volym, stark fundamental
        elif 1.0 <= chg <= 5.0 and entry_signal == "STARK":
            vol = move.get("vol_ratio", 1.0) or 1.0
            if vol >= 1.3:  # Kräv minst 30% högre volym än igår
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

    # Sortera: dips och breakouts efter score
    return sorted(opportunities, key=lambda x: x["score"], reverse=True)[:5]


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
) -> tuple[str, str]:
    """
    Bygger rapporten. Returnerar (markdown, email-ämne).
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    crash  = portfolio_alerts.get("crash",  [])
    surge  = portfolio_alerts.get("surge",  [])
    normal = portfolio_alerts.get("normal", [])

    has_alerts = bool(crash or surge or opportunities)

    # ── Ämnesrad ──────────────────────────────────────────────
    if crash and any(a["action"] == "SÄLJ/MINSKA" for a in crash):
        tickers = ", ".join(a["ticker"] for a in crash if a["action"] == "SÄLJ/MINSKA")
        subject = f"🚨 CRASH ALERT: {tickers} – MarketScan {date.today().strftime('%d %b')}"
    elif crash:
        tickers = ", ".join(a["ticker"] for a in crash)
        subject = f"⚠️ Varning: {tickers} ned vid öppning – MarketScan {date.today().strftime('%d %b')}"
    elif surge and any(a["action"] == "TA HEM HALVA" for a in surge):
        tickers = ", ".join(a["ticker"] for a in surge if a["action"] == "TA HEM HALVA")
        subject = f"🚀 Stark uppgång: {tickers} – ta hem vinst? {date.today().strftime('%d %b')}"
    elif opportunities:
        first = opportunities[0]
        typ   = "Dipp" if first["type"] == "DIP" else "Breakout"
        subject = f"💡 {typ}: {first['ticker']} ({first['score']:.0f}p) – MarketScan {date.today().strftime('%d %b')}"
    else:
        subject = f"✅ Morgon OK – inga alerts {date.today().strftime('%d %b')}"

    # ── Rapport ───────────────────────────────────────────────
    lines = [f"# 🌅 Morgonkoll – {now}\n", "---\n"]

    # Crash-alerts
    if crash:
        lines.append("## 🚨 Portfölj-alerts\n")
        for a in sorted(crash, key=lambda x: x["change_pct"]):
            icon = "🔴" if a["action"] == "SÄLJ/MINSKA" else "🟡"
            pnl_s = f" · Totalt P&L: {a['total_pnl']:+.1f}%" if a.get("total_pnl") is not None else ""
            lines.append(
                f"{icon} **`{a['ticker']}`** {a['change_pct']:+.1f}% "
                f"→ **{a['action']}**  \n_{a['msg']}{pnl_s}_\n"
            )

    # Surge-alerts
    if surge:
        lines.append("## 🚀 Stark uppgång i portföljen\n")
        for a in sorted(surge, key=lambda x: x["change_pct"], reverse=True):
            pnl_s = f" · Totalt: {a['total_pnl']:+.1f}%" if a.get("total_pnl") is not None else ""
            lines.append(
                f"🟢 **`{a['ticker']}`** {a['change_pct']:+.1f}% "
                f"→ **{a['action']}**  \n_{a['msg']}{pnl_s}_\n"
            )

    # Normal portfölj-översikt
    if normal:
        lines.append("## 💼 Övriga innehav\n")
        lines.append("| Ticker | Idag | Pris |")
        lines.append("|--------|------|------|")
        for n in sorted(normal, key=lambda x: x["change_pct"]):
            sign = "+" if n["change_pct"] >= 0 else ""
            icon = "🟢" if n["change_pct"] >= 0 else "🔴"
            lines.append(f"| `{n['ticker']}` | {icon} {sign}{n['change_pct']:.1f}% | {n['price']:.2f} |")
        lines.append("")

    # Köpmöjligheter
    if opportunities:
        lines.append(f"## 💡 Köpmöjligheter (topp-50 från {top50_date})\n")
        for opp in opportunities:
            type_icon = "📉" if opp["type"] == "DIP" else "📈"
            lines.append(
                f"{type_icon} **`{opp['ticker']}`** {opp['name']} "
                f"_{opp['sector']}_  \n"
                f"Score: **{opp['score']:.0f}** · {opp['change']:+.1f}% · "
                f"{opp['signal']} · {opp['msg']}\n"
            )
    elif not has_alerts:
        lines.append("## ℹ️ Status\n\n✅ Inga signaler – allt normalt.\n")

    # Earnings-påminnelse
    if earnings_soon is not None and not earnings_soon.empty:
        lines.append("## 📅 Kommande rapporter (dina innehav)\n")
        for _, row in earnings_soon.iterrows():
            days = row.get("days_until", "?")
            ticker = row.get("ticker", "")
            d = str(row.get("date", ""))[:10]
            lines.append(f"- **`{ticker}`** rapporterar **{d}** (om {days} dagar)")
        lines.append("")

    lines.append("---\n*⚠ Inte finansiell rådgivning. MarketScan morgonkoll.*")
    return "\n".join(lines), subject


# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Morgonkoll – crash alert + köpmöjligheter")
    parser.add_argument("--quiet",      action="store_true")
    parser.add_argument("--no-email",   action="store_true")
    parser.add_argument("--force-email",action="store_true",
                        help="Skicka email även utan alerts (för test)")
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

        # 2. Ladda portfölj
        holdings = portfolio.load_holdings()
        log["n_holdings"] = len(holdings)
        if v:
            print(f"  ✓ {len(holdings)} innehav laddade")

        # 3. Hämta priser
        all_tickers = list(set(
            list(holdings["ticker"].str.upper() if not holdings.empty else []) +
            list(top50["ticker"].str.upper() if not top50.empty else [])
        ))

        print(f"\n📥 Hämtar priser ({len(all_tickers)} tickers)...")
        price_moves = fetch_opening_moves(all_tickers, verbose=v)
        log["n_prices"] = len(price_moves)
        print(f"  ✓ {len(price_moves)} priser hämtade")

        # 4. Detektera portfolio-alerts
        portfolio_alerts = {"crash": [], "surge": [], "normal": []}
        if not holdings.empty:
            portfolio_alerts = detect_portfolio_alerts(holdings, price_moves)
            n_crash = len(portfolio_alerts["crash"])
            n_surge = len(portfolio_alerts["surge"])
            if n_crash:
                print(f"\n  🚨 {n_crash} crash/varnings-alert(s) i portföljen!")
            if n_surge:
                print(f"  🚀 {n_surge} stark uppgång(ar) i portföljen!")
        log["n_crash"]  = len(portfolio_alerts.get("crash", []))
        log["n_surge"]  = len(portfolio_alerts.get("surge", []))

        # 5. Hitta köpmöjligheter
        opportunities = []
        if not top50.empty and not holdings.empty:
            opportunities = find_opportunities(top50, price_moves, holdings)
            if opportunities and v:
                print(f"  💡 {len(opportunities)} köpmöjlighet(er) identifierade")
        log["n_opportunities"] = len(opportunities)

        # 6. Earnings-påminnelse
        earnings_soon = pd.DataFrame()
        try:
            if not holdings.empty:
                scored_placeholder = top50 if not top50.empty else pd.DataFrame()
                earnings_soon = ec.upcoming_in_portfolio(
                    holdings, scored_placeholder, days_ahead=7
                )
        except Exception:
            pass

        # 7. Bygg rapport
        report, subject = build_morning_report(
            portfolio_alerts, opportunities, earnings_soon,
            top50_date, holdings, price_moves
        )

        # Spara rapport
        Path(config.REPORT_DIR).mkdir(exist_ok=True)
        report_path = Path(config.REPORT_DIR) / f"morning_{date.today()}.md"
        report_path.write_text(report, encoding="utf-8")
        log["report_path"] = str(report_path)

        # 8. Skicka email
        has_alerts = bool(
            portfolio_alerts.get("crash") or
            portfolio_alerts.get("surge") or
            opportunities
        )

        should_email = (has_alerts or args.force_email) and not args.no_email

        if should_email and alerts.email_configured():
            print(f"\n✉ Skickar: {subject}")
            import smtplib
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText

            # Konvertera till enkel HTML
            html = "<br>".join(
                f"<b>{l}</b>" if l.startswith("#") else l
                for l in report.split("\n")
            )

            sender, password, to = alerts._get_email_config()
            if sender and password:
                msg = MIMEMultipart("alternative")
                msg["Subject"] = subject
                msg["From"]    = f"MarketScan <{sender}>"
                msg["To"]      = to
                msg.attach(MIMEText(report, "plain", "utf-8"))

                # Använd alerts-modulens HTML-konvertering
                html_body = alerts._markdown_to_html(report)
                full_html = f"""<html><body style="font-family:sans-serif;max-width:680px;margin:0 auto;padding:20px">
                {html_body}
                <div style="margin-top:24px;font-size:11px;color:#999">
                Automatisk rapport från MarketScan. Inte finansiell rådgivning.
                </div></body></html>"""
                msg.attach(MIMEText(full_html, "html", "utf-8"))

                try:
                    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
                        s.login(sender, password)
                        s.sendmail(sender, to, msg.as_string())
                    print(f"  ✉ Email skickat till {to}")
                except Exception as e:
                    print(f"  ⚠ Email-fel: {e}")
        elif not has_alerts and not args.force_email:
            print("\n  ✅ Inga alerts – inget email skickat")
        elif not alerts.email_configured():
            print("\n  ℹ Email ej konfigurerat")

        # Terminal-sammanfattning
        print(f"\n{'─'*40}")
        print(f"  Crash alerts:    {len(portfolio_alerts.get('crash', []))}")
        print(f"  Uppgångar:       {len(portfolio_alerts.get('surge', []))}")
        print(f"  Köpmöjligheter:  {len(opportunities)}")
        print(f"  Rapport:         {report_path}")


if __name__ == "__main__":
    main()
