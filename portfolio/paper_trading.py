"""
paper_trading.py
================
Simulerar köp baserat på varje veckas topp-rekommendationer.
Spårar hur systemets faktiska rekommendationer presterar live.

Det här är ditt mest värdefulla valideringsverktyg. Backtesting kan
vara snyggt på papper – paper trading visar om systemet faktiskt
funkar i verkligheten, utan att du riskerar riktiga pengar.

Princip:
  Varje söndag "köper" paper trading-läget topp-N aktier likaviktat.
  Veckan efter mäts faktisk prisrörelse. Ackumulerat track record byggs upp.

  Skillnaden mot backtest:
  - Backtesting använder historisk data du REDAN hade
  - Paper trading är genuint out-of-sample – du vet inte utfallet när
    du gör "köpet"

Sparar till:
  data/paper_trades.json     – alla simulerade positioner
  data/paper_portfolio.json  – ackumulerat P&L per vecka

Kör manuellt:
  python paper_trading.py status    – se nuvarande portfolio och P&L
  python paper_trading.py report    – detaljerad rapport

Körs automatiskt:
  scan.py anropar record_weekly_picks() i slutet av varje scan
"""

import json
import time
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import numpy as np
import yfinance as yf

TRADES_FILE    = Path("data/paper_trades.json")
PORTFOLIO_FILE = Path("data/paper_portfolio.json")
BENCHMARK      = "SPY"  # Jämförelseindex

Path("data").mkdir(exist_ok=True)


# ══════════════════════════════════════════════════════════════
# DATAHANTERING
# ══════════════════════════════════════════════════════════════

def _load(path: Path) -> dict | list:
    if not path.exists():
        return [] if "trades" in str(path) else {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return [] if "trades" in str(path) else {}


def _save(path: Path, data):
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str),
                    encoding="utf-8")


def _get_price(ticker: str) -> float | None:
    """Hämtar nuvarande pris för en ticker."""
    try:
        time.sleep(0.3)
        info = yf.Ticker(ticker).fast_info
        p = info.last_price
        return float(p) if p else None
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════
# REGISTRERA VECKANS REKOMMENDATIONER
# ══════════════════════════════════════════════════════════════

def record_weekly_picks(
    scored_df:   pd.DataFrame,
    top_n:       int  = 10,
    capital:     float = 100_000,  # Simulerat kapital per vecka (SEK)
    verbose:     bool  = True,
) -> dict:
    """
    Registrerar veckans topp-N rekommendationer som simulerade köp.
    Anropas automatiskt i slutet av scan.py.

    scored_df: Den scorade DataFramen från scan-pipeline
    top_n:     Hur många aktier att "köpa" varje vecka
    capital:   Simulerat kapital att fördela likaviktat
    """
    week_str = date.today().isoformat()
    trades   = _load(TRADES_FILE)

    # Kolla om vi redan kört denna vecka
    existing_weeks = {t["week"] for t in trades}
    if week_str in existing_weeks:
        if verbose:
            print(f"  ℹ Paper trading: redan registrerat för {week_str}")
        return {}

    # Hämta topp-N med STARK eller OK entry-signal
    candidates = scored_df.copy()
    if "entry_signal" in candidates.columns:
        # Prioritera STARK och OK, men ta med VÄNTA om vi inte får nog
        priority = {"STARK": 0, "OK": 1, "VÄNTA": 2, "EJ AKTUELL": 3}
        candidates["_prio"] = candidates["entry_signal"].map(priority).fillna(3)
        candidates = candidates.sort_values(["_prio", "score_total"], ascending=[True, False])

    top = candidates.head(top_n)

    # Hämta aktuella priser
    capital_per_stock = capital / top_n
    week_trades = []

    for _, row in top.iterrows():
        ticker = str(row["ticker"])
        price  = row.get("current_price") or _get_price(ticker)

        # Fångar None, 0, NaN – bool(float('nan')) är True så 'not price' fångar EJ nan
        if price is None or (isinstance(price, float) and (price != price)) or price == 0:
            continue

        shares = round(capital_per_stock / price, 4)

        week_trades.append({
            "week":         week_str,
            "ticker":       ticker,
            "name":         str(row.get("name", "")),
            "sector":       str(row.get("sector", "")),
            "buy_price":    round(float(price), 4),
            "shares":       shares,
            "capital":      round(capital_per_stock, 2),
            "score":        round(float(row.get("score_total", 0)), 1),
            "entry_signal": str(row.get("entry_signal", "—")),
            "status":       "OPEN",
            "sell_price":   None,
            "sell_date":    None,
            "pnl":          None,
            "pnl_pct":      None,
        })

    # Hämta benchmark-pris
    bench_price = _get_price(BENCHMARK)

    # Spara veckans "portfölj" i portfolio-filen
    portfolio = _load(PORTFOLIO_FILE)
    if isinstance(portfolio, list):
        portfolio = {}  # Migrera gammalt format

    portfolio[week_str] = {
        "capital":       capital,
        "n_picks":       len(week_trades),
        "benchmark_buy": bench_price,
        "tickers":       [t["ticker"] for t in week_trades],
    }

    # Spara
    trades.extend(week_trades)
    _save(TRADES_FILE, trades)
    _save(PORTFOLIO_FILE, portfolio)

    if verbose:
        print(f"  ✓ Paper trading: registrerade {len(week_trades)} positioner för {week_str}")
        for t in week_trades[:5]:
            print(f"     {t['ticker']:<14} @ {t['buy_price']:.2f}  (score: {t['score']:.0f})")
        if len(week_trades) > 5:
            print(f"     ... och {len(week_trades)-5} till")

    return {"week": week_str, "trades": week_trades}


# ══════════════════════════════════════════════════════════════
# UPPDATERA PRISER OCH BERÄKNA P&L
# ══════════════════════════════════════════════════════════════

def update_prices(close_after_weeks: int = 4, verbose: bool = True) -> dict:
    """
    Uppdaterar priser för öppna positioner och stänger de som är
    äldre än close_after_weeks veckor.

    Returnerar sammanfattning av stängda positioner.
    """
    trades  = _load(TRADES_FILE)
    today   = date.today()
    closed  = []
    updated = 0

    for trade in trades:
        if trade["status"] != "OPEN":
            continue

        trade_date = datetime.strptime(trade["week"], "%Y-%m-%d").date()
        age_weeks  = (today - trade_date).days / 7

        current_price = _get_price(trade["ticker"])
        if not current_price:
            continue

        pnl     = (current_price - trade["buy_price"]) * trade["shares"]
        pnl_pct = (current_price / trade["buy_price"] - 1) * 100

        trade["current_price"] = round(current_price, 4)
        trade["pnl"]           = round(pnl, 2)
        trade["pnl_pct"]       = round(pnl_pct, 2)
        updated += 1

        # Stäng positioner äldre än close_after_weeks
        if age_weeks >= close_after_weeks:
            trade["status"]     = "CLOSED"
            trade["sell_price"] = current_price
            trade["sell_date"]  = today.isoformat()
            closed.append(trade)

    _save(TRADES_FILE, trades)

    if verbose and updated:
        print(f"  ✓ Paper trading: uppdaterade {updated} priser, stängde {len(closed)} positioner")

    return {"updated": updated, "closed": len(closed)}


# ══════════════════════════════════════════════════════════════
# STATISTIK & RAPPORT
# ══════════════════════════════════════════════════════════════

def calc_statistics() -> dict:
    """Beräknar samlad statistik för alla stängda paper trades."""
    trades    = _load(TRADES_FILE)
    portfolio = _load(PORTFOLIO_FILE)

    closed = [t for t in trades if t["status"] == "CLOSED" and t.get("pnl_pct") is not None]

    if not closed:
        return {"status": "Inga stängda positioner ännu"}

    rets = [t["pnl_pct"] for t in closed]

    # Per vecka – vägd genomsnittlig avkastning
    weeks = {}
    for t in closed:
        w = t["week"]
        if w not in weeks:
            weeks[w] = []
        weeks[w].append(t["pnl_pct"])

    weekly_rets = [np.mean(v) for v in weeks.values()]

    sharpe = (np.mean(weekly_rets) / np.std(weekly_rets) * np.sqrt(52)) \
             if len(weekly_rets) > 1 and np.std(weekly_rets) > 0 else None

    win_rate = sum(1 for r in rets if r > 0) / len(rets) * 100

    # Benchmark-jämförelse
    bench_rets = []
    for week_str, week_data in portfolio.items():
        if not isinstance(week_data, dict):
            continue
        bench_buy = week_data.get("benchmark_buy")
        if not bench_buy:
            continue
        # Hämta benchmark-pris 4 veckor senare (approx)
        bench_sell = _get_price(BENCHMARK)
        if bench_sell:
            bench_rets.append((bench_sell / bench_buy - 1) * 100)

    return {
        "n_trades":          len(closed),
        "n_weeks":           len(weeks),
        "avg_return_pct":    round(np.mean(rets), 2),
        "median_return_pct": round(np.median(rets), 2),
        "win_rate_pct":      round(win_rate, 1),
        "best_trade":        max(closed, key=lambda t: t["pnl_pct"]),
        "worst_trade":       min(closed, key=lambda t: t["pnl_pct"]),
        "sharpe":            round(sharpe, 2) if sharpe else None,
        "avg_weekly_ret":    round(np.mean(weekly_rets), 2),
        "weekly_rets":       weekly_rets,
    }


def print_status(verbose: bool = True):
    """Skriver ut nuvarande portföljstatus i terminalen."""
    trades    = _load(TRADES_FILE)
    portfolio = _load(PORTFOLIO_FILE)

    open_trades   = [t for t in trades if t["status"] == "OPEN"]
    closed_trades = [t for t in trades if t["status"] == "CLOSED"]

    print(f"\n{'═'*60}")
    print("📄 PAPER TRADING – STATUS")
    print(f"{'═'*60}")
    print(f"  Öppna positioner:   {len(open_trades)}")
    print(f"  Stängda positioner: {len(closed_trades)}")

    if open_trades:
        print(f"\n  Öppna positioner (senaste 5):")
        for t in sorted(open_trades, key=lambda x: x["week"], reverse=True)[:5]:
            curr = t.get("current_price", t["buy_price"])
            pnl_pct = t.get("pnl_pct", 0) or 0
            sign = "+" if pnl_pct >= 0 else ""
            print(f"    {t['week']}  {t['ticker']:<14} "
                  f"{t['buy_price']:.2f} → {curr:.2f}  "
                  f"{sign}{pnl_pct:.1f}%")

    stats = calc_statistics()
    if "n_trades" in stats:
        print(f"\n  {'─'*40}")
        print(f"  Track record ({stats['n_weeks']} veckor):")
        print(f"  Snittavkastning/trade:  {stats['avg_return_pct']:+.2f}%")
        print(f"  Win rate:               {stats['win_rate_pct']:.0f}%")
        if stats.get("sharpe"):
            print(f"  Sharpe (annualiserad):  {stats['sharpe']:.2f}")
        print(f"\n  Bästa trade: {stats['best_trade']['ticker']} "
              f"{stats['best_trade']['pnl_pct']:+.1f}%")
        print(f"  Sämsta trade: {stats['worst_trade']['ticker']} "
              f"{stats['worst_trade']['pnl_pct']:+.1f}%")
    else:
        print(f"\n  {stats['status']}")

    print(f"{'═'*60}\n")


def build_paper_trading_section(top_n: int = 5) -> str:
    """
    Bygger en markdown-sektion för veckans rapport.
    Visar track record och senaste öppna positioner.
    """
    trades = _load(TRADES_FILE)
    stats  = calc_statistics()

    if not trades:
        return ""

    open_trades   = [t for t in trades if t["status"] == "OPEN"]
    closed_trades = [t for t in trades if t["status"] == "CLOSED"]

    lines = ["\n## 📄 Paper trading – track record\n"]

    # Statistik
    if "n_trades" in stats:
        lines.append(f"**{stats['n_weeks']} veckor** · "
                     f"Snitt: **{stats['avg_return_pct']:+.2f}%/trade** · "
                     f"Win rate: **{stats['win_rate_pct']:.0f}%** · "
                     f"Sharpe: **{stats.get('sharpe', '—')}**\n")
    else:
        lines.append("_Inga stängda positioner ännu – resultaten visas efter 4 veckor_\n")

    # Senaste stängda positioner
    if closed_trades:
        recent = sorted(closed_trades, key=lambda t: t.get("sell_date", ""), reverse=True)[:top_n]
        lines.append("### Senaste avslutade")
        lines.append("| Vecka | Ticker | Köp | Sälj | P&L % |")
        lines.append("|-------|--------|-----|------|-------|")
        for t in recent:
            sign = "+" if t.get("pnl_pct", 0) >= 0 else ""
            lines.append(
                f"| {t['week']} | `{t['ticker']}` | "
                f"{t['buy_price']:.2f} | {t.get('sell_price', '—'):.2f} | "
                f"**{sign}{t.get('pnl_pct', 0):.1f}%** |"
            )
        lines.append("")

    # Öppna positioner denna vecka
    this_week = date.today().isoformat()
    this_week_trades = [t for t in open_trades if t["week"] == this_week]
    if this_week_trades:
        lines.append("### Denna veckas simulerade köp")
        lines.append("| Ticker | Sektor | Score | Entry | Köpkurs |")
        lines.append("|--------|--------|-------|-------|---------|")
        for t in this_week_trades:
            lines.append(
                f"| `{t['ticker']}` | {t.get('sector','')[:15]} | "
                f"{t.get('score', 0):.0f} | {t.get('entry_signal','—')} | "
                f"{t['buy_price']:.2f} |"
            )

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Paper trading – simulera systemets rekommendationer")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("status",  help="Visa nuvarande status och track record")
    p_upd = sub.add_parser("update", help="Uppdatera priser för öppna positioner")
    p_upd.add_argument("--close-after", type=int, default=4,
                       help="Stäng positioner äldre än N veckor (default: 4)")
    sub.add_parser("report", help="Detaljerad rapport till fil")

    args = parser.parse_args()

    if args.cmd == "status":
        update_prices(verbose=False)  # Uppdatera priser tyst
        print_status()

    elif args.cmd == "update":
        result = update_prices(close_after_weeks=args.close_after, verbose=True)
        print_status()

    elif args.cmd == "report":
        update_prices(verbose=False)
        stats = calc_statistics()
        print("\n📊 Detaljerad statistik:")
        for k, v in stats.items():
            if k not in ("best_trade", "worst_trade", "weekly_rets"):
                print(f"  {k}: {v}")

    else:
        parser.print_help()
        print("\nExempel:")
        print("  python paper_trading.py status")
        print("  python paper_trading.py update --close-after 4")
