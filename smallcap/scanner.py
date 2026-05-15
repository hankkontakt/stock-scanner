"""
scanner.py – Huvudingång för svenska småbolagsscanern.

Användning:
  python smallcap/scanner.py                     # kör hela universumet, top-20
  python smallcap/scanner.py --top 10            # kortare rankinglista
  python smallcap/scanner.py --market first_north
  python smallcap/scanner.py --email             # skicka rapport via e-post
  python smallcap/scanner.py --output reports/   # spara rapport till mapp
  python smallcap/scanner.py --no-insider        # hoppa över insiderhämtning (snabbare)

GitHub Actions: se smallcap_scan.yml
"""

import argparse
import os
import sys
import smtplib
import traceback
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

# Se till att föräldramappen finns i sys.path (för data_fetcher, piotroski m.m.)
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd
import numpy as np

try:
    import yfinance as yf
    _YF_AVAILABLE = True
except ImportError:
    _YF_AVAILABLE = False
    print("⚠️  yfinance ej installerat – kör: pip install yfinance", file=sys.stderr)

# Importera data_fetcher för att aktivera curl_cffi/timeout-patchar och
# använda samma hämtningspipeline (caching, retry) som huvudskannern.
try:
    import data_fetcher as _df
    _DF_AVAILABLE = True
except ImportError:
    _df = None
    _DF_AVAILABLE = False

from smallcap.universe  import get_universe, SECTOR_GROUPS
from smallcap.filters   import apply_all_filters
from smallcap.scoring   import score_universe
from smallcap.insider   import fetch_insider_data, merge_insider_data
from smallcap.report    import build_report, save_report
from smallcap.history   import save_scores, load_prev_scores

try:
    import news_fetcher as _nf
    _NF_AVAILABLE = True
except ImportError:
    _NF_AVAILABLE = False


# ── Data­hämtning ──────────────────────────────────────────────────────────────

_FETCH_FIELDS = [
    # Pris & volym
    "currentPrice", "regularMarketPrice", "previousClose",
    "averageVolume", "averageVolume10days",
    # Marknadsvärde & multiplar
    "marketCap", "enterpriseValue", "enterpriseToEbitda",
    "priceToBook", "forwardPE", "trailingPE",
    # Balansräkning
    "debtToEquity", "currentRatio", "totalCash", "totalDebt",
    "freeCashflow", "operatingCashflow",
    # Lönsamhet
    "grossMargins", "operatingMargins", "profitMargins",
    "returnOnEquity", "returnOnAssets",
    # Tillväxt
    "revenueGrowth", "earningsGrowth",
    # Ägarskap
    "heldPercentInsiders", "heldPercentInstitutions",
    # Aktier
    "sharesOutstanding", "floatShares", "sharesPercentSharesOut",
]


def _piotroski_proxy(row: dict) -> int:
    """
    Enkel 3-faktors Piotroski-proxy när full F-Score saknas.
    Beräknar ett 1–9-värde baserat på tillgänglig data:
      +1  Positiv rörelsemarginal (>5%)   -1 negativ
      +1  Positivt operativt kassaflöde   -1 negativt
      +1  Current ratio > 1.5             -1 < 1.0
    Baseline = 4 (neutral).
    """
    import math
    score = 4

    def _f(key):
        v = row.get(key, float("nan"))
        try:
            f = float(v if v is not None else float("nan"))
            return float("nan") if math.isnan(f) else f
        except (TypeError, ValueError):
            return float("nan")

    om  = _f("operating_margin")
    ocf = _f("operating_cashflow")
    cr  = _f("current_ratio")

    if not math.isnan(om):
        score += 1 if om > 0.05 else (-1 if om < 0 else 0)
    if not math.isnan(ocf):
        score += 1 if ocf > 0 else -1
    if not math.isnan(cr):
        score += 1 if cr > 1.5 else (-1 if cr < 1.0 else 0)

    return max(1, min(9, score))


def _fetch_single(ticker: str) -> dict | None:
    """
    Hämtar info för en enskild ticker.
    Använder data_fetcher (curl_cffi-patchad, med caching och retry) om tillgänglig,
    annars raw yfinance som fallback.
    """
    try:
        if _DF_AVAILABLE:
            info = _df.fetch_stock_info(ticker)
            hist = _df.fetch_price_history(ticker, period="13mo")
        elif _YF_AVAILABLE:
            info = yf.Ticker(ticker).info
            hist = yf.Ticker(ticker).history(period="13mo", auto_adjust=True)
        else:
            return None

        if not info or len(info) < 5:
            return None

        price = info.get("currentPrice") or info.get("regularMarketPrice") or \
                info.get("previousClose", 0)
        if not price:
            return None

        # Daglig förändring
        prev_close  = info.get("previousClose", 0) or 0
        day_change  = float("nan")
        if prev_close > 0 and price:
            day_change = (price - prev_close) / prev_close

        # Momentum + vecklig förändring
        r12 = r6 = week_change = float("nan")
        if hist is not None and not hist.empty and len(hist) > 20:
            c = hist["Close"]
            r12         = float(c.iloc[-1] / c.iloc[0] - 1) if len(c) >= 252 else float("nan")
            r6          = float(c.iloc[-1] / c.iloc[max(0, len(c) - 126)] - 1)
            week_change = float(c.iloc[-1] / c.iloc[max(0, len(c) - 5)] - 1)

        name = (info.get("longName") or info.get("shortName") or "").strip()

        return {
            "ticker":            ticker,
            "name":              name,
            "current_price":     price,
            "day_change_pct":    day_change,
            "week_change_pct":   week_change,
            "avg_volume":        info.get("averageVolume") or info.get("averageVolume10days", 0),
            "market_cap":        info.get("marketCap", float("nan")),
            "ev_to_ebitda":      info.get("enterpriseToEbitda", float("nan")),
            "price_to_book":     info.get("priceToBook", float("nan")),
            "debt_to_equity":    info.get("debtToEquity", float("nan")),
            "current_ratio":     info.get("currentRatio", float("nan")),
            "total_cash":        info.get("totalCash", float("nan")),
            "total_debt":        info.get("totalDebt", float("nan")),
            "free_cash_flow":    info.get("freeCashflow", float("nan")),
            "operating_cashflow":info.get("operatingCashflow", float("nan")),
            "book_value":        info.get("bookValue", float("nan")),
            "gross_margin":      info.get("grossMargins", float("nan")),
            "operating_margin":  info.get("operatingMargins", float("nan")),
            "revenue_growth":    info.get("revenueGrowth", float("nan")),
            "earnings_growth":   info.get("earningsGrowth", float("nan")),
            "insider_pct":       info.get("heldPercentInsiders", float("nan")),
            "return_12m":        r12,
            "return_6m":         r6,
            "shares_change_pct": float("nan"),
        }
    except Exception as e:
        print(f"    ⚠️  {ticker}: {e}", file=sys.stderr)
        return None


def fetch_universe_data(tickers: list, delay: float = 0.4) -> pd.DataFrame:
    """
    Hämtar fundamentaldata för alla tickers.
    Returnerar DataFrame med en rad per ticker.
    """
    print(f"  Hämtar data för {len(tickers)} tickers ...")
    rows = []
    n = len(tickers)

    for i, ticker in enumerate(tickers, 1):
        if i % 10 == 0 or i == n:
            print(f"    {i}/{n} ...", end="\r", flush=True)
        row = _fetch_single(ticker)
        if row:
            rows.append(row)
        # data_fetcher.fetch_stock_info har inbyggd REQUEST_DELAY_SEC (0.8s);
        # lägg bara till extra delay om data_fetcher inte är tillgänglig
        if not _DF_AVAILABLE:
            import time; time.sleep(delay)

    print(f"    {n}/{n} klart.   ")
    df = pd.DataFrame(rows)
    if df.empty:
        return df

    # Piotroski-beräkning: försök med piotroski.py, fallback till proxy
    try:
        import piotroski as _piotroski
        scores = []
        for _, r in df.iterrows():
            try:
                s = _piotroski.compute(r.get("ticker", ""))
                # Om compute() returnerar None (API-miss) → proxy från tillgänglig data
                scores.append(s if s is not None else _piotroski_proxy(r.to_dict()))
            except Exception:
                scores.append(_piotroski_proxy(r.to_dict()))
        df["piotroski_score"] = scores
    except ImportError:
        # Piotroski-modulen saknas helt – beräkna proxy för alla
        df["piotroski_score"] = df.apply(
            lambda r: _piotroski_proxy(r.to_dict()), axis=1
        )

    return df


# ── E-post ─────────────────────────────────────────────────────────────────────

def send_email(subject: str, body: str) -> bool:
    """Skickar rapporten via e-post. Returnerar True vid framgång."""
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    # Stöd både EMAIL_USER/EMAIL_PASS (lokalt) och EMAIL_SENDER/EMAIL_PASSWORD (GitHub Actions)
    smtp_user = (os.environ.get("EMAIL_USER") or
                 os.environ.get("EMAIL_SENDER", ""))
    smtp_pass = (os.environ.get("EMAIL_PASS") or
                 os.environ.get("EMAIL_PASSWORD", ""))
    to_addr   = (os.environ.get("EMAIL_TO") or
                 os.environ.get("EMAIL_RECIPIENT") or
                 smtp_user)

    if not smtp_user or not smtp_pass:
        print("⚠️  E-post ej konfigurerat (EMAIL_USER/EMAIL_SENDER eller EMAIL_PASS/EMAIL_PASSWORD saknas)")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = smtp_user
    msg["To"]      = to_addr
    msg.attach(MIMEText(body, "plain", "utf-8"))

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as srv:
            srv.ehlo(); srv.starttls(); srv.ehlo()
            srv.login(smtp_user, smtp_pass)
            srv.sendmail(smtp_user, to_addr, msg.as_string())
        print(f"  ✉️  Rapport skickad till {to_addr}")
        return True
    except Exception as e:
        print(f"  ✗  E-post misslyckades: {e}", file=sys.stderr)
        return False


# ── Huvud ─────────────────────────────────────────────────────────────────────

def run_scan(
    market:       str  = "all",
    top_n:        int  = 20,
    profiles_n:   int  = 5,
    fetch_insider: bool = True,
    output_dir:   str  = ".",
    send_mail:    bool = False,
    verbose:      bool = True,
) -> tuple[pd.DataFrame, str]:
    """
    Kör hela small-cap-scanern.

    Returns:
        (scored_df, report_markdown)
    """
    print(f"\n{'='*60}")
    print(f"  🔍 Småbolagsskanner – {datetime.today().strftime('%Y-%m-%d %H:%M')}")
    print(f"  Marknad: {market.upper()}  |  Top-{top_n}")
    print(f"{'='*60}\n")

    # 1. Universum
    tickers = get_universe(market)
    print(f"  Universum: {len(tickers)} tickers\n")

    # 2. Data­hämtning
    df = fetch_universe_data(tickers)
    if df.empty:
        print("  ✗  Ingen data hämtad. Avbryter.")
        return pd.DataFrame(), "# Fel\n\nIngen data kunde hämtas.\n"

    n_universe = len(df)
    print(f"\n  Data hämtad för {n_universe} bolag")

    # 3. Hårda filter
    print("\n  Kör hårda filter ...")
    df_filtered = apply_all_filters(df, verbose=verbose)

    if df_filtered.empty:
        print("  ✗  Inga bolag kvar efter filtrering.")
        return pd.DataFrame(), "# Fel\n\nAlla bolag filtrerades bort.\n"

    # 4. Insider­data
    if fetch_insider:
        print(f"\n  Hämtar insiderdata ({len(df_filtered)} tickers) ...")
        insider_df = fetch_insider_data(df_filtered["ticker"].tolist(), delay=0.4)
        df_filtered = merge_insider_data(df_filtered, insider_df)
    else:
        insider_df = None

    # 5. Scoring
    print("\n  Beräknar poäng ...")
    scored = score_universe(df_filtered)

    top5 = scored.head(5)[["ticker", "sc_total", "sc_stars"]].to_string(index=False)
    print(f"\n  🏆 Top-5 resultat:\n{top5}\n")

    # 6. Nyheter för topp-5 profiler (Google News RSS + Nasdaq Nordic)
    company_news = {}   # {ticker: [articles]}
    nasdaq_news  = []
    if _NF_AVAILABLE:
        print("  Hämtar nyheter (Google News + Nasdaq Nordic) ...")
        # Bygg ticker→namn mapping från topp-profiles_n
        name_map = {}
        if "name" in scored.columns:
            for _, r in scored.head(profiles_n).iterrows():
                n = str(r.get("name", "") or "").strip()
                if n:
                    name_map[r["ticker"]] = n
        if name_map:
            company_news = _nf.fetch_company_news_google_batch(
                name_map, max_items=3, delay=1.3
            )
            if company_news:
                print(f"    ✓ Google News: {len(company_news)} bolag")
        # Nasdaq Nordic – regulatoriska meddelanden (Stockholm, senaste 7 dagar)
        nasdaq_news = _nf.fetch_nasdaq_nordic_news(market="SSE", max_items=8, hours_back=168)
        if nasdaq_news:
            print(f"    ✓ Nasdaq Nordic: {len(nasdaq_news)} meddelanden")

    # 7. Rapport (läser historik för trendpilar internt)
    print("  Bygger rapport ...")
    prev_scores = load_prev_scores()
    report = build_report(
        scored,
        n_universe   = n_universe,
        top_n        = top_n,
        profiles_n   = profiles_n,
        insider_df   = insider_df,
        prev_scores  = prev_scores,
        company_news = company_news,
        nasdaq_news  = nasdaq_news,
    )

    # Spara aktuella poäng för nästa körnings trendpilar
    save_scores(scored)

    # 8. Spara
    report_path = save_report(report, output_dir=output_dir)
    print(f"  ✓  Rapport sparad: {report_path}")

    # 9. E-post
    if send_mail:
        date_str = datetime.today().strftime("%d %b %Y")
        top1     = scored.iloc[0]["ticker"] if not scored.empty else "—"
        subject  = (f"📊 Småbolagsrapport {date_str} | "
                    f"Toppbolag: {top1} | {scored.iloc[0]['sc_stars']} "
                    f"{scored.iloc[0]['sc_total']:.0f}p")
        send_email(subject, report)

    print(f"\n  Klar! {len(scored)} bolag rankade.\n")
    return scored, report


def main():
    parser = argparse.ArgumentParser(
        description="Svenska Småbolagsskanner – hittar guldstjärnor bland small/micro caps"
    )
    parser.add_argument(
        "--market",
        choices=["all", "first_north", "small_cap", "spotlight"],
        default="all",
        help="Vilket marknadssegment (standard: all)",
    )
    parser.add_argument("--top",      type=int,  default=20,
                        help="Antal bolag i rankinglistan (standard: 20)")
    parser.add_argument("--profiles", type=int,  default=5,
                        help="Antal djupdyks-profiler (standard: 5)")
    parser.add_argument("--no-insider", action="store_true",
                        help="Hoppa över insiderhämtning (snabbare körning)")
    parser.add_argument("--email",    action="store_true",
                        help="Skicka rapport via e-post")
    parser.add_argument("--output",   default=".",
                        help="Mapp för rapport-filen (standard: .)")
    parser.add_argument("--quiet",    action="store_true",
                        help="Minimalt utskrift")

    args = parser.parse_args()

    try:
        scored, report = run_scan(
            market        = args.market,
            top_n         = args.top,
            profiles_n    = args.profiles,
            fetch_insider = not args.no_insider,
            output_dir    = args.output,
            send_mail     = args.email,
            verbose       = not args.quiet,
        )
    except KeyboardInterrupt:
        print("\n  Avbruten av användaren.")
        sys.exit(0)
    except Exception:
        print("\n  ✗  Fel vid körning:", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
