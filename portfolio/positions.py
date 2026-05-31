"""
positions.py
============
Spårar alla transaktioner och beräknar faktisk avkastning.

Problemet med holdings.csv:
  Den vet bara att du ÄGER 10 AAPL till 150 kr.
  Den vet inte NÄR du köpte, vad du SÅLT, eller din REALISERADE vinst.

Denna modul lägger till:
  - transactions.csv  : komplett transaktionslogg
  - Realiserat P&L    : faktisk vinst/förlust på sålda positioner
  - Genomsnittlig kostnadsbas : FIFO-beräkning vid delvisa försäljningar
  - Innehavstid       : hur länge du hållit varje position
  - Performance-rapport: din faktiska avkastning vs index

Transaktionsformat (transactions.csv):
  date,ticker,type,shares,price,fee
  2025-01-15,AAPL,BUY,10,150.00,7.5
  2025-06-01,AAPL,SELL,5,180.00,7.5
  2025-01-20,VOLV-B.ST,BUY,100,210.50,39.0

Kör med:
  python positions.py add-buy AAPL 10 150.00
  python positions.py add-sell AAPL 5 180.00
  python positions.py report
  python positions.py sync        # Uppdatera holdings.csv från transaktioner
"""

import argparse
import csv
import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import numpy as np

TRANSACTIONS_FILE = Path("data/transactions.csv")
HOLDINGS_FILE     = Path("data/holdings.csv")


# ══════════════════════════════════════════════════════════════
# TRANSAKTIONSHANTERING
# ══════════════════════════════════════════════════════════════

def load_transactions() -> pd.DataFrame:
    """Läser transactions.csv. Skapar tom fil om den saknas."""
    if not TRANSACTIONS_FILE.exists():
        TRANSACTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _write_transaction_header()
        return pd.DataFrame(columns=["date", "ticker", "type", "shares", "price", "fee"])

    try:
        df = pd.read_csv(TRANSACTIONS_FILE, parse_dates=["date"])
        df.columns = df.columns.str.lower().str.strip()
        df["shares"] = pd.to_numeric(df["shares"], errors="coerce")
        df["price"]  = pd.to_numeric(df["price"],  errors="coerce")
        df["fee"]    = pd.to_numeric(df["fee"],     errors="coerce").fillna(0)
        return df.sort_values("date").reset_index(drop=True)
    except Exception as e:
        print(f"⚠ Kunde inte läsa transactions.csv: {e}")
        return pd.DataFrame()


def _write_transaction_header():
    with open(TRANSACTIONS_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "ticker", "type", "shares", "price", "fee"])


def add_transaction(ticker: str, tx_type: str, shares: float,
                    price: float, fee: float = None,
                    tx_date: str = None) -> bool:
    """
    Lägger till en transaktion.

    tx_type: "BUY" eller "SELL"
    fee:     Om None, beräknas automatiskt (0.25% SE, 0.55% utland)
    """
    ticker = ticker.upper().strip()
    tx_type = tx_type.upper()

    if tx_type not in ("BUY", "SELL"):
        print(f"⚠ Ogiltigt transaktionstyp: {tx_type}. Använd BUY eller SELL.")
        return False

    if shares <= 0 or price <= 0:
        print("⚠ Antal och pris måste vara positiva.")
        return False

    if fee is None:
        # Avanza-liknande courtage
        fee_pct = 0.0025 if ticker.endswith(".ST") else 0.0055
        fee     = max(1.0, round(shares * price * fee_pct, 2))

    if tx_date is None:
        tx_date = date.today().isoformat()

    # Kolla att vi inte säljer mer än vi äger
    if tx_type == "SELL":
        current_holdings = calc_current_holdings()
        owned = current_holdings.get(ticker, {}).get("shares", 0)
        if shares > owned + 0.001:
            print(f"⚠ Du försöker sälja {shares} {ticker} men äger bara {owned:.2f}")
            return False

    try:
        with open(TRANSACTIONS_FILE, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([tx_date, ticker, tx_type, shares, price, fee])

        print(f"✓ {tx_type} {shares} {ticker} @ {price} (avgift: {fee:.2f})")
        return True
    except Exception as e:
        print(f"⚠ Fel vid sparning: {e}")
        return False


# ══════════════════════════════════════════════════════════════
# FIFO-BERÄKNING
# ══════════════════════════════════════════════════════════════

def calc_current_holdings() -> dict:
    """
    Beräknar nuvarande innehav via FIFO.

    Returnerar dict: {ticker: {shares, avg_cost, total_cost, first_buy_date}}
    """
    txs = load_transactions()
    if txs.empty:
        return {}

    holdings = {}

    for _, tx in txs.iterrows():
        ticker  = str(tx["ticker"]).upper()
        tx_type = str(tx["type"]).upper()
        shares  = float(tx["shares"])
        price   = float(tx["price"])
        fee     = float(tx["fee"]) if pd.notna(tx["fee"]) else 0
        tx_date = tx["date"]

        if tx_type == "BUY":
            if ticker not in holdings:
                holdings[ticker] = {
                    "shares":         0.0,
                    "total_cost":     0.0,
                    "first_buy_date": tx_date,
                    "lots":           [],  # FIFO-lots: [(shares, cost_per_share, date)]
                }

            cost_per_share = (shares * price + fee) / shares
            holdings[ticker]["shares"]     += shares
            holdings[ticker]["total_cost"] += shares * price + fee
            holdings[ticker]["lots"].append((shares, cost_per_share, tx_date))

        elif tx_type == "SELL" and ticker in holdings:
            # FIFO: sälj från äldsta lot
            remaining_to_sell = shares
            new_lots = []
            for lot_shares, lot_cost, lot_date in holdings[ticker]["lots"]:
                if remaining_to_sell <= 0:
                    new_lots.append((lot_shares, lot_cost, lot_date))
                elif remaining_to_sell >= lot_shares:
                    remaining_to_sell -= lot_shares
                    holdings[ticker]["total_cost"] -= lot_shares * lot_cost
                else:
                    # Partiell försäljning av denna lot
                    holdings[ticker]["total_cost"] -= remaining_to_sell * lot_cost
                    new_lots.append((lot_shares - remaining_to_sell, lot_cost, lot_date))
                    remaining_to_sell = 0

            holdings[ticker]["shares"] -= shares
            holdings[ticker]["lots"]    = new_lots

    # Beräkna genomsnittlig kostnadsbas
    result = {}
    for ticker, h in holdings.items():
        if h["shares"] > 0.001:
            avg_cost = h["total_cost"] / h["shares"] if h["shares"] > 0 else 0
            result[ticker] = {
                "shares":         round(h["shares"], 4),
                "avg_cost":       round(avg_cost, 4),
                "total_cost":     round(h["total_cost"], 2),
                "first_buy_date": h["first_buy_date"],
            }

    return result


def calc_realized_pnl() -> pd.DataFrame:
    """
    Beräknar realiserat P&L för alla genomförda försäljningar.

    Returnerar DataFrame med en rad per försäljning.
    """
    txs = load_transactions()
    if txs.empty:
        return pd.DataFrame()

    # Spåra lots per ticker
    lots_by_ticker = {}  # {ticker: [(shares, cost_per_share, buy_date)]}
    realized_rows  = []

    for _, tx in txs.iterrows():
        ticker  = str(tx["ticker"]).upper()
        tx_type = str(tx["type"]).upper()
        shares  = float(tx["shares"])
        price   = float(tx["price"])
        fee     = float(tx["fee"]) if pd.notna(tx["fee"]) else 0
        tx_date = tx["date"]

        if tx_type == "BUY":
            if ticker not in lots_by_ticker:
                lots_by_ticker[ticker] = []
            cost_per_share = (shares * price + fee) / shares
            lots_by_ticker[ticker].append([shares, cost_per_share, tx_date])

        elif tx_type == "SELL" and ticker in lots_by_ticker:
            remaining    = shares
            sell_revenue = shares * price - fee
            cost_basis   = 0

            new_lots = []
            for lot in lots_by_ticker[ticker]:
                lot_shares, lot_cost, lot_date = lot
                if remaining <= 0:
                    new_lots.append(lot)
                elif remaining >= lot_shares:
                    cost_basis += lot_shares * lot_cost
                    remaining  -= lot_shares
                else:
                    cost_basis        += remaining * lot_cost
                    new_lots.append([lot_shares - remaining, lot_cost, lot_date])
                    remaining = 0

            lots_by_ticker[ticker] = new_lots
            pnl     = sell_revenue - cost_basis
            pnl_pct = (pnl / cost_basis) if cost_basis > 0 else None

            # Hitta ursprungligt köp-datum
            buy_dates = [l[2] for l in lots_by_ticker.get(ticker, [])]
            first_buy = min(buy_dates) if buy_dates else None

            realized_rows.append({
                "sell_date":   tx_date,
                "ticker":      ticker,
                "shares_sold": shares,
                "sell_price":  price,
                "sell_fee":    fee,
                "cost_basis":  round(cost_basis, 2),
                "revenue":     round(sell_revenue, 2),
                "pnl":         round(pnl, 2),
                "pnl_pct":     round(pnl_pct * 100, 2) if pnl_pct else None,
            })

    return pd.DataFrame(realized_rows)


# ══════════════════════════════════════════════════════════════
# PERFORMANCE-RAPPORT
# ══════════════════════════════════════════════════════════════

def generate_performance_report(current_prices: dict = None) -> str:
    """
    Skapar en performance-rapport.

    current_prices: {ticker: current_price} – om None hämtas via yfinance
    """
    txs      = load_transactions()
    holdings = calc_current_holdings()
    realized = calc_realized_pnl()

    if txs.empty and not holdings:
        return "Inga transaktioner ännu. Lägg till med: python positions.py add-buy TICKER ANTAL PRIS"

    lines = ["# 📊 Positions-rapport\n"]
    lines.append(f"**Genererad:** {datetime.now().strftime('%Y-%m-%d %H:%M')}  ")
    lines.append(f"**Transaktioner:** {len(txs)} st\n")

    # ── Nuvarande innehav ─────────────────────────────────────
    if holdings:
        lines.append("## 💼 Nuvarande innehav\n")
        lines.append("| Ticker | Antal | Snitt-kurs | Totalkostnad | Nuv. pris | Papper P&L | Innehavstid |")
        lines.append("|--------|-------|------------|--------------|-----------|------------|-------------|")

        total_cost  = 0
        total_value = 0

        for ticker, h in holdings.items():
            # Hämta nuvarande pris
            curr_price = None
            if current_prices:
                curr_price = current_prices.get(ticker)
            if curr_price is None:
                try:
                    import yfinance as yf
                    info = yf.Ticker(ticker).fast_info
                    curr_price = float(info.last_price) if info.last_price else None
                except Exception:
                    pass

            mkt_val = h["shares"] * curr_price if curr_price else None
            pnl     = mkt_val - h["total_cost"] if mkt_val else None
            pnl_pct = (pnl / h["total_cost"] * 100) if (pnl is not None and h["total_cost"] > 0) else None

            # Innehavstid
            if pd.notna(h["first_buy_date"]):
                try:
                    first = pd.to_datetime(h["first_buy_date"]).date()
                    days  = (date.today() - first).days
                    hold_str = f"{days}d" if days < 365 else f"{days//365}y {(days%365)//30}m"
                except Exception:
                    hold_str = "—"
            else:
                hold_str = "—"

            if mkt_val:
                total_value += mkt_val
            total_cost += h["total_cost"]

            pnl_s     = f"{'+' if pnl >= 0 else ''}{pnl:,.0f}" if pnl is not None else "—"
            pnl_pct_s = f"{'+' if pnl_pct >= 0 else ''}{pnl_pct:.1f}%" if pnl_pct is not None else "—"
            curr_s    = f"{curr_price:,.2f}" if curr_price else "—"

            lines.append(
                f"| `{ticker}` | {h['shares']:.2f} | {h['avg_cost']:,.2f} | "
                f"{h['total_cost']:,.0f} | {curr_s} | "
                f"**{pnl_s}** ({pnl_pct_s}) | {hold_str} |"
            )

        total_pnl = total_value - total_cost if total_value > 0 else None
        total_pnl_pct = (total_pnl / total_cost * 100) if total_pnl and total_cost > 0 else None
        lines.append(f"\n**Totalt investerat:** {total_cost:,.0f}")
        if total_value > 0:
            pnl_sign = '+' if total_pnl >= 0 else ''
            lines.append(f"**Totalt marknadsvärde:** {total_value:,.0f}")
            lines.append(f"**Orealiserat P&L:** **{pnl_sign}{total_pnl:,.0f}** "
                         f"({pnl_sign}{total_pnl_pct:.1f}%)")

    # ── Realiserat P&L ────────────────────────────────────────
    if not realized.empty:
        lines.append("\n## 💰 Realiserat P&L\n")
        total_real = realized["pnl"].sum()
        total_wins = (realized["pnl"] > 0).sum()
        total_loss = (realized["pnl"] < 0).sum()
        win_rate   = total_wins / len(realized) * 100

        lines.append(f"**Totalt realiserat P&L:** "
                     f"**{'+' if total_real >= 0 else ''}{total_real:,.0f}**  ")
        lines.append(f"**Vinstaffärer:** {total_wins} st ({win_rate:.0f}%) · "
                     f"**Förlustaffärer:** {total_loss} st\n")

        lines.append("| Datum | Ticker | Antal | Sälj-kurs | P&L | P&L % |")
        lines.append("|-------|--------|-------|-----------|-----|-------|")

        for _, row in realized.sort_values("sell_date", ascending=False).head(20).iterrows():
            pnl_sign = "+" if row["pnl"] >= 0 else ""
            lines.append(
                f"| {str(row['sell_date'])[:10]} | `{row['ticker']}` | "
                f"{row['shares_sold']:.2f} | {row['sell_price']:,.2f} | "
                f"**{pnl_sign}{row['pnl']:,.0f}** | "
                f"{pnl_sign}{row.get('pnl_pct', 0):.1f}% |"
            )

    return "\n".join(lines)


def sync_to_holdings_csv():
    """
    Uppdaterar holdings.csv baserat på aktuella transaktioner.
    Ersätter manuell redigering av holdings.csv.
    """
    holdings = calc_current_holdings()

    rows = []
    for ticker, h in holdings.items():
        rows.append({
            "ticker":     ticker,
            "shares":     h["shares"],
            "cost_basis": h["avg_cost"],
        })

    df = pd.DataFrame(rows)
    df.to_csv(HOLDINGS_FILE, index=False)
    print(f"✓ holdings.csv uppdaterad med {len(rows)} positioner")
    return df


# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Positionshantering och P&L-tracker")
    sub = parser.add_subparsers(dest="cmd")

    # add-buy
    p_buy = sub.add_parser("add-buy", help="Registrera ett köp")
    p_buy.add_argument("ticker"); p_buy.add_argument("shares", type=float)
    p_buy.add_argument("price",  type=float)
    p_buy.add_argument("--fee",  type=float, default=None)
    p_buy.add_argument("--date", default=None)

    # add-sell
    p_sell = sub.add_parser("add-sell", help="Registrera en försäljning")
    p_sell.add_argument("ticker"); p_sell.add_argument("shares", type=float)
    p_sell.add_argument("price",  type=float)
    p_sell.add_argument("--fee",  type=float, default=None)
    p_sell.add_argument("--date", default=None)

    # report
    sub.add_parser("report", help="Visa performance-rapport")

    # sync
    sub.add_parser("sync", help="Uppdatera holdings.csv från transaktioner")

    args = parser.parse_args()

    if args.cmd == "add-buy":
        add_transaction(args.ticker, "BUY", args.shares, args.price, args.fee, args.date)
        sync_to_holdings_csv()

    elif args.cmd == "add-sell":
        add_transaction(args.ticker, "SELL", args.shares, args.price, args.fee, args.date)
        sync_to_holdings_csv()

    elif args.cmd == "report":
        report = generate_performance_report()
        print(report)

        # Spara som markdown
        path = Path("reports") / f"positions_{date.today()}.md"
        path.parent.mkdir(exist_ok=True)
        path.write_text(report, encoding="utf-8")
        print(f"\n💾 Sparad: {path}")

    elif args.cmd == "sync":
        sync_to_holdings_csv()

    else:
        parser.print_help()
        print("\nExempel:")
        print("  python positions.py add-buy  AAPL 10 150.00")
        print("  python positions.py add-sell AAPL  5 180.00")
        print("  python positions.py report")
        print("  python positions.py sync")
