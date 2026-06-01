"""
paper_trading.py - Paper Trading v2
====================================
Simulerar köp baserat på varje veckas topp-rekommendationer.
Spårar hur systemets faktiska rekommendationer presterar live.

NYTT i v2:
- Stop-loss (sälj automatiskt vid -X%)
- Take-profit (sälj automatiskt vid +Y%)
- Partiell försäljning (sälj 50% vid delvinst, resten vid huvudmål)
- DCA (köp mer vid dipp om score fortfarande är hög)
- Trailing stop (stop-loss som följer priset uppåt)
- AI-stop-loss (dynamiska nivåer baserat på ATR)

Sparar till:
  data/paper_trades.json     - alla simulerade positioner
  data/paper_portfolio.json  - ackumulerat P&L per vecka

Kör manuellt:
  python portfolio/paper_trading.py status           - se portfolio och P&L
  python portfolio/paper_trading.py update           - uppdatera priser + kolla stop-loss/take-profit
  python portfolio/paper_trading.py report           - detaljerad rapport
  python portfolio/paper_trading.py close_all        - stäng alla öppna positioner
"""

import json
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import numpy as np
import yfinance as yf

# Absoluta sökvägar förankrade i repo-roten. Tidigare var dessa relativa
# (Path("data/...")) vilket bröts om processen kördes från en annan CWD --
# pipelinen skrev då till en annan fil än den Streamlit-appen läste.
_ROOT          = Path(__file__).resolve().parent.parent
TRADES_FILE    = _ROOT / "data" / "paper_trades.json"
PORTFOLIO_FILE = _ROOT / "data" / "paper_portfolio.json"
BENCHMARK      = "SPY"
DEFAULT_CAPITAL = 100_000  # SEK per vecka

# ── Standardparametrar för riskhantering ───────────────────────────────────
STOP_LOSS_PCT       = -10.0   # Sälj om -10% från inköp
TAKE_PROFIT_PCT     = 25.0    # Sälj allt vid +25%
PARTIAL_PROFIT_PCT  = 12.0    # Sälj 50% vid +12%
PARTIAL_SELL_FRAC   = 0.50    # Andel att sälja vid delvinst
TRAILING_ACTIVATE   = 8.0     # Aktivera trailing när vinsten nått +8%
TRAILING_DISTANCE   = 8.0     # Trail:a stop:et 8% under högsta setts
DCA_TRIGGER         = -8.0    # Köp mer om priset fallit -8% från inköp
DCA_MULTIPLIER      = 1.5     # Köp 1.5x mer vid DCA
MAX_DCA_PER_TICKER  = 2       # Max antal DCA-köp per ticker
CLOSE_AFTER_WEEKS   = 8       # Stäng position efter N veckor oavsett

# ── Transaktionskostnader (slippage + courtage) ────────────────────────────
# Modellerar realistiska friktionskostnader för att undvika överoptimism.
# Typiska svenska mäklararvoden: 0.05-0.15% courtage + 0.05% bid-ask-spread.
COMMISSION_PCT  = 0.0010   # 0.10% courtage per affär (köp + sälj = 0.20% round-trip)
SLIPPAGE_PCT    = 0.0005   # 0.05% prisslippage per order (bid-ask-spread)

(_ROOT / "data").mkdir(exist_ok=True)


# ══════════════════════════════════════════════════════════════
# HJÄLPFUNKTIONER
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
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )


def _get_price(ticker: str) -> float | None:
    """Hämtar nuvarande pris för en ticker."""
    try:
        time.sleep(0.3)
        info = yf.Ticker(ticker).fast_info
        p = info.last_price
        return float(p) if p else None
    except Exception:
        return None


def _calculate_atr(ticker: str, period: int = 14) -> float | None:
    """Beräkna Average True Range för en ticker.
    Används för dynamiska stop-loss-nivåer.
    """
    try:
        hist = yf.Ticker(ticker).history(period="1mo", auto_adjust=True)
        if hist.empty or len(hist) < period:
            return None
        high = hist["High"]
        low = hist["Low"]
        close = hist["Close"]
        tr = pd.concat([
            high - low,
            abs(high - close.shift()),
            abs(low - close.shift()),
        ], axis=1).max(axis=1)
        atr = tr.rolling(period).mean().iloc[-1]
        return float(atr)
    except Exception:
        return None


def _ticker_to_num(ticker: str) -> float:
    """Slumpa en 'sannolikhet' baserat på ticker-namnet.
    Används för AI-stop-loss när ATR inte är tillgänglig.
    """
    h = 0
    for c in ticker:
        h = (h * 31 + ord(c)) & 0xFFFFFFFF
    return (h % 1000) / 1000.0  # 0.0-1.0


def _calculate_ai_stop(ticker: str, buy_price: float, current_price: float) -> float:
    """Beräkna dynamisk stop-loss-nivå baserat på ATR eller volatilitet.
    
    Prioritering:
    1. ATR-based: stop = current_price - (ATR x 2)
    2. Fallback: stop = buy_price x 0.88 (12% under inköp)
    """
    atr = _calculate_atr(ticker)
    if atr and atr > 0:
        atr_stop = current_price - (atr * 2)
        # Begränsa så stop:et inte är mer än 20% under inköpspriset
        max_loss = buy_price * 0.80
        return max(atr_stop, max_loss)
    # Fallback
    return buy_price * 0.88


# ══════════════════════════════════════════════════════════════
# KELLY-KALKYLATOR (exporteras till portfolio.py)
# ══════════════════════════════════════════════════════════════

def get_kelly_inputs(min_trades: int = 20) -> dict:
    """
    Beräknar win rate och win/loss-kvot från stängda paper trades.
    Används av portfolio.py för Half-Kelly positionsstorleksberäkning.

    Returns:
        win_rate (float): Andel vinnande trades
        win_loss_ratio (float): avg_vinst / avg_förlust
        n_trades (int): Antal stängda trades
        using_defaults (bool): True om för få trades för riktiga värden
    """
    trades = _load(TRADES_FILE)
    closed = [
        t for t in trades
        if t.get("status") == "CLOSED" and t.get("pnl_pct") is not None
    ]

    if len(closed) < min_trades:
        return {
            "win_rate":       0.55,
            "win_loss_ratio": 1.5,
            "n_trades":       len(closed),
            "using_defaults": True,
        }

    rets   = [t["pnl_pct"] for t in closed]
    wins   = [r for r in rets if r > 0]
    losses = [abs(r) for r in rets if r < 0]

    wr        = len(wins) / len(rets)
    avg_win   = float(np.mean(wins))   if wins   else 0.0
    avg_loss  = float(np.mean(losses)) if losses else 1.0
    wl_ratio  = avg_win / avg_loss if avg_loss > 0 else 1.5

    return {
        "win_rate":       round(wr, 4),
        "win_loss_ratio": round(wl_ratio, 4),
        "avg_win_pct":    round(avg_win, 2),
        "avg_loss_pct":   round(avg_loss, 2),
        "n_trades":       len(closed),
        "using_defaults": False,
    }


# ══════════════════════════════════════════════════════════════
# REGISTRERA VECKANS REKOMMENDATIONER
# ══════════════════════════════════════════════════════════════

def _get_kelly_fraction(min_trades: int = 10) -> float:
    """
    Beräknar Half-Kelly fraktion baserat på empirisk track record.

    Full-Kelly: f* = (p * b - q) / b  där p = win_rate, q = 1-p, b = win_loss_ratio
    Half-Kelly: 0.5 * f*

    Om för få trades -> returnerar 1.0 (equal weight default).
    """
    # Anropa direkt eftersom vi är i samma modul
    inputs = get_kelly_inputs(min_trades=min_trades)
    if inputs.get("using_defaults", True):
        return 1.0  # Fallback till equal weight om för få trades
    p = inputs["win_rate"]
    b = inputs["win_loss_ratio"]
    if b <= 0:
        return 1.0
    q = 1.0 - p
    f_star = (p * b - q) / b if b > 0 else 0
    # Half-Kelly: halvera för att undvika överbetting vid parameterosäkerhet
    half_kelly = max(0.0, min(1.0, f_star * 0.5))
    return half_kelly if half_kelly > 0.01 else 1.0


def _get_atr_multiplier(volatility_regime: str = "normal") -> float:
    """
    Auto-kalibrerad ATR-multiplikator baserat på volatilitetsregim.

    Per arkitekturrekommendationen:
    - Låg volatilitet (VIX < 15): 2.5x (mindre false stops)
    - Normal volatilitet:        2.0x (standard)
    - Hög volatilitet (VIX > 25): 1.5x (snabbare exit i turbulens)
    - 21-perioders lookback istället för 14 i höga vol-regimer
    """
    mapping = {
        "low":     2.5,
        "normal":  2.0,
        "high":    1.5,
        "extreme": 1.0,
    }
    return mapping.get(volatility_regime, 2.0)


def _detect_volatility_regime() -> str:
    """
    Detekterar volatilitetsregim baserat på SPY/OXSX 30-dagars historisk vol.

    Returns:
        "low", "normal", "high", "extreme"
    """
    try:
        import yfinance as yf
        spy = yf.Ticker("SPY")
        hist = spy.history(period="3mo", auto_adjust=True)
        if hist.empty or len(hist) < 30:
            return "normal"
        close = hist["Close"]
        returns = close.pct_change().dropna()
        trailing_vol = returns.tail(30).std() * np.sqrt(252)
        # Tolkning
        if trailing_vol < 0.15:
            return "low"
        elif trailing_vol < 0.22:
            return "normal"
        elif trailing_vol < 0.30:
            return "high"
        else:
            return "extreme"
    except Exception:
        return "normal"




def record_weekly_picks(
    scored_df: pd.DataFrame,
    top_n: int = 10,
    capital: float = DEFAULT_CAPITAL,
    verbose: bool = True,
    universe: str = "universe",
) -> dict:
    """
    Registrerar veckans topp-N rekommendationer som simulerade köp.
    Anropas från daily_pipeline för både stora universumet och småbolag.

    universe: "universe" (stora scan) eller "smallcap"
    V2: Sätter stop-loss, take-profit, trailing-stop vid köp.
    V3: Half-Kelly positionsstorlek + dynamisk ATR stop.
    """
    week_str = date.today().isoformat()
    trades = _load(TRADES_FILE)

    # Kolla om vi redan kört denna vecka för detta universum
    existing = {(t.get("week"), t.get("universe", "universe"))
                for t in trades if t.get("exit_reason") != "DCA"}
    if (week_str, universe) in existing:
        if verbose:
            print(f"  ℹ Paper trading ({universe}): redan registrerat för {week_str}")
        return {}

    # Hämta topp-N med STARK eller OK entry-signal
    # Välj rätt score-kolumn (smallcap kan använda sc_total)
    score_col = "sc_total" if universe == "smallcap" and "sc_total" in scored_df.columns else "score_total"
    candidates = scored_df.copy()
    if "entry_signal" in candidates.columns:
        priority = {"STARK": 0, "OK": 1, "VÄNTA": 2, "EJ AKTUELL": 3}
        candidates["_prio"] = candidates["entry_signal"].map(priority).fillna(3)
        candidates = candidates.sort_values(["_prio", score_col], ascending=[True, False])
    else:
        if score_col in candidates.columns:
            candidates = candidates.sort_values(score_col, ascending=False)

    top = candidates.head(top_n)

    # ── V3: Half-Kelly positionsstorlek per ticker ──────────────────────
    kelly_frac = _get_kelly_fraction(min_trades=10)
    if kelly_frac < 1.0 and verbose:
        print(f"  📐 Half-Kelly: {kelly_frac:.2f}x (från {get_kelly_inputs().get('n_trades', 0)} trades)")
    vol_regime = _detect_volatility_regime()
    atr_mult = _get_atr_multiplier(vol_regime)
    if atr_mult != 2.0 and verbose:
        print(f"  📐 ATR-mult: {atr_mult}x (regim: {vol_regime})")

    # Half-Kelly: minska totalt kapital om signalstyrkan är låg
    effective_capital = capital * kelly_frac
    capital_per_stock = effective_capital / top_n
    week_trades = []

    for _, row in top.iterrows():
        ticker = str(row["ticker"])
        price = row.get("current_price") or _get_price(ticker)

        if price is None or (isinstance(price, float) and (price != price)) or price == 0:
            continue

        # Applicera slippage + courtage på köp-priset (köparen betalar spread + avgift)
        effective_buy_price = float(price) * (1 + COMMISSION_PCT + SLIPPAGE_PCT)
        shares = round(capital_per_stock / effective_buy_price, 4)
        buy_price = round(effective_buy_price, 4)

        # Beräkna stop-loss och take-profit nivåer vid köp
        stop_loss_price = round(buy_price * (1 + STOP_LOSS_PCT / 100), 4)
        take_profit_price = round(buy_price * (1 + TAKE_PROFIT_PCT / 100), 4)
        partial_price = round(buy_price * (1 + PARTIAL_PROFIT_PCT / 100), 4)
        ai_stop_price = round(_calculate_ai_stop(ticker, buy_price, buy_price), 4)

        week_trades.append({
            "week":          week_str,
            "universe":      universe,
            "ticker":        ticker,
            "name":          str(row.get("name", "")),
            "sector":        str(row.get("sector", "")),
            "buy_price":     buy_price,
            "buy_date":      date.today().isoformat(),
            "shares":        shares,
            "original_shares": shares,
            "capital":       round(capital_per_stock, 2),
            "score":         round(float(row.get(score_col, 0)), 1),
            "entry_signal":  str(row.get("entry_signal", "--")),

            # Risk management
            "stop_loss":        stop_loss_price,
            "take_profit":      take_profit_price,
            "partial_profit":   partial_price,
            "trailing_stop":    None,   # Sätts när priset når TRAILING_ACTIVATE
            "trailing_high":    buy_price,
            "ai_stop":          ai_stop_price,

            # DCA
            "dca_count":         0,
            "dca_buys":          [],
            "total_invested":    capital_per_stock,

            # Status
            "status":            "OPEN",
            "sell_price":        None,
            "sell_date":         None,
            "pnl":               None,
            "pnl_pct":           None,
            "exit_reason":       None,

            # Löpande uppdateringar
            "highest_price":     buy_price,
            "current_price":     buy_price,
        })

    # Hämta benchmark-pris
    bench_price = _get_price(BENCHMARK)

    # Spara veckans "portfölj" i portfolio-filen
    portfolio = _load(PORTFOLIO_FILE)
    if isinstance(portfolio, list):
        portfolio = {}

    # Spara per universum så båda syns i portfölj-filen
    port_key = week_str if universe == "universe" else f"{week_str}_{universe}"
    portfolio[port_key] = {
        "capital":       capital,
        "universe":      universe,
        "n_picks":       len(week_trades),
        "benchmark_buy": bench_price,
        "tickers":       [t["ticker"] for t in week_trades],
    }

    trades.extend(week_trades)
    _save(TRADES_FILE, trades)
    _save(PORTFOLIO_FILE, portfolio)

    if verbose:
        print(f"  ✓ Paper trading ({universe}): registrerade {len(week_trades)} positioner för {week_str}")
        for t in week_trades[:5]:
            sl = f"SL:{t['stop_loss']:.2f}" if t.get('stop_loss') else ""
            tp = f"TP:{t['take_profit']:.2f}" if t.get('take_profit') else ""
            print(f"     {t['ticker']:<14} @ {t['buy_price']:.2f}  ({sl} {tp})")
        if len(week_trades) > 5:
            print(f"     ... och {len(week_trades)-5} till")

    return {"week": week_str, "trades": week_trades}


# ══════════════════════════════════════════════════════════════
# STOP-LOSS / TAKE-PROFIT / DCA CHECK
# ══════════════════════════════════════════════════════════════

def _check_risk_management(trade: dict, current_price: float, today: date) -> dict:
    """
    Kontrollera riskhantering för en enskild trade.
    Returnerar dict med åtgärder som ska vidtas.

    Prioriteringsordning:
    1. Stop-loss (hård gräns)
    2. Take-profit (full)
    3. Partiell försäljning
    4. Trailing stop
    5. DCA (köp mer)
    6. AI-stop-loss (dynamiskt)
    """
    actions = {"sell_all": False, "sell_fraction": 0, "dca": False,
               "exit_reason": None, "new_stop": None}

    buy_price = trade["buy_price"]
    pnl_pct = ((current_price / buy_price) - 1) * 100

    # Uppdatera högsta pris setts
    trade["highest_price"] = max(trade["highest_price"], current_price)

    # 1. Stop-loss (hård gräns)
    if trade.get("stop_loss") and current_price <= trade["stop_loss"]:
        actions["sell_all"] = True
        actions["exit_reason"] = f"stop_loss_{STOP_LOSS_PCT:.0f}%"
        return actions

    # 2. AI-stop-loss (dynamiskt - om priset är under den beräknade AI-nivån)
    ai_stop = _calculate_ai_stop(trade["ticker"], buy_price, current_price)
    trade["ai_stop"] = round(ai_stop, 4)
    if current_price <= ai_stop:
        actions["sell_all"] = True
        actions["exit_reason"] = "ai_stop_loss"
        return actions

    # 3. Take-profit (full) - om vi redan inte sålt delvis
    partial_sold = trade.get("partial_sold", False)
    if not partial_sold and trade.get("take_profit") and current_price >= trade["take_profit"]:
        actions["sell_all"] = True
        actions["exit_reason"] = f"take_profit_{TAKE_PROFIT_PCT:.0f}%"
        return actions

    # 4. Partiell försäljning (sälj 50% vid delvinst)
    if not partial_sold and trade.get("partial_profit") and current_price >= trade["partial_profit"]:
        actions["sell_fraction"] = PARTIAL_SELL_FRAC
        actions["exit_reason"] = f"partial_{PARTIAL_PROFIT_PCT:.0f}%"
        return actions

    # 5. Trailing stop
    if pnl_pct >= TRAILING_ACTIVATE:
        # Uppdatera trailing high om priset stiger
        if current_price > trade.get("trailing_high", buy_price):
            trade["trailing_high"] = current_price
            new_stop = current_price * (1 - TRAILING_DISTANCE / 100)
            trade["trailing_stop"] = round(new_stop, 4)
            actions["new_stop"] = trade["trailing_stop"]

        # Kolla om trailing-stop är triggat
        if trade.get("trailing_stop") and current_price <= trade["trailing_stop"]:
            actions["sell_all"] = True
            actions["exit_reason"] = f"trailing_stop_{TRAILING_DISTANCE:.0f}%"
            return actions

    # 6. DCA - köp mer om priset fallit och score fortfarande är hög
    if pnl_pct <= DCA_TRIGGER and trade["dca_count"] < MAX_DCA_PER_TICKER:
        actions["dca"] = True

    return actions


def _execute_dca(trade: dict, current_price: float) -> dict:
    """Utför DCA-köp och returnerar uppdaterad trade."""
    dca_count = trade["dca_count"] + 1
    # Köpbelopp = ursprungligt kapital x DCA_MULTIPLIER för varje DCA
    dca_amount = trade["capital"] * DCA_MULTIPLIER
    dca_shares = dca_amount / current_price

    trade["dca_count"] = dca_count
    trade["dca_buys"].append({
        "date": str(date.today()),
        "price": round(current_price, 4),
        "shares": round(dca_shares, 4),
        "amount": round(dca_amount, 2),
    })
    trade["shares"] = round(trade["shares"] + dca_shares, 4)
    trade["buy_price"] = round(
        (trade["buy_price"] * trade["original_shares"] + current_price * dca_shares)
        / trade["shares"],
        4,
    )
    trade["total_invested"] = round(trade["total_invested"] + dca_amount, 2)

    # Uppdatera stop-loss baserat på nytt snittpris
    trade["stop_loss"] = round(trade["buy_price"] * (1 + STOP_LOSS_PCT / 100), 4)

    return trade


# ══════════════════════════════════════════════════════════════
# UPPDATERA PRISER OCH BERÄKNA P&L
# ══════════════════════════════════════════════════════════════

def update_prices(close_after_weeks: int = CLOSE_AFTER_WEEKS,
                  verbose: bool = True) -> dict:
    """
    Uppdaterar priser för öppna positioner och kontrollerar
    stop-loss, take-profit, trailing stop och DCA.

    V2: Risk management i varje uppdatering.
    """
    trades = _load(TRADES_FILE)
    today = date.today()
    closed = []
    dcas = []
    updated = 0

    for trade in trades:
        if trade["status"] != "OPEN":
            continue

        trade_date = datetime.strptime(trade["week"], "%Y-%m-%d").date()
        age_weeks = (today - trade_date).days / 7

        current_price = _get_price(trade["ticker"])
        if not current_price:
            continue

        # Beräkna P&L
        pnl = (current_price - trade["buy_price"]) * trade["shares"]
        pnl_pct = (current_price / trade["buy_price"] - 1) * 100

        trade["current_price"] = round(current_price, 4)
        trade["pnl"] = round(pnl, 2)
        trade["pnl_pct"] = round(pnl_pct, 2)
        updated += 1

        # Kontrollera riskhantering
        actions = _check_risk_management(trade, current_price, today)

        # Utför DCA före stop-loss-check (om trigger)
        if actions.get("dca") and not actions.get("sell_all"):
            trade = _execute_dca(trade, current_price)
            dcas.append(trade["ticker"])
            # Uppdatera P&L efter DCA
            pnl = (current_price - trade["buy_price"]) * trade["shares"]
            pnl_pct = (current_price / trade["buy_price"] - 1) * 100
            trade["pnl"] = round(pnl, 2)
            trade["pnl_pct"] = round(pnl_pct, 2)

        # Partiell försäljning
        sell_frac = actions.get("sell_fraction", 0)
        if sell_frac > 0:
            sell_shares = round(trade["shares"] * sell_frac, 4)
            partial_pnl = (current_price - trade["buy_price"]) * sell_shares
            trade["shares"] = round(trade["shares"] - sell_shares, 4)
            trade["partial_sold"] = True
            trade["partial_sold_shares"] = sell_shares
            trade["partial_sold_price"] = current_price
            trade["partial_sold_pnl"] = round(partial_pnl, 2)

            # Uppdatera stop-loss för kvarvarande position
            trade["stop_loss"] = round(trade["buy_price"] * (1 + STOP_LOSS_PCT / 100), 4)

            if verbose:
                print(f"     🔶 Partiell försäljning: {trade['ticker']} - "
                      f"sålde {sell_shares:.2f} st @ {current_price:.2f} "
                      f"(P&L {partial_pnl:+.2f})")

        # Stäng position
        if actions.get("sell_all") or age_weeks >= close_after_weeks:
            trade["status"] = "CLOSED"
            # Applicera sälj-friktioner: säljaren förlorar spread + courtage
            effective_sell_price = current_price * (1 - COMMISSION_PCT - SLIPPAGE_PCT)
            trade["sell_price"] = round(effective_sell_price, 4)
            trade["sell_date"] = today.isoformat()
            trade["exit_reason"] = actions.get("exit_reason") or f"time_{close_after_weeks}w"

            # Om vi redan sålt delvis, inkludera det i totalen
            total_pnl = trade.get("pnl", 0) or 0
            if trade.get("partial_sold_pnl"):
                total_pnl += trade["partial_sold_pnl"]
            trade["pnl"] = round(total_pnl, 2)

            closed.append(trade)

    _save(TRADES_FILE, trades)

    if verbose:
        n_closed = len(closed)
        n_dcas = len(dcas)
        msg = f"  ✓ Paper trading v2: uppdaterade {updated} priser"
        if n_closed:
            msg += f", stängde {n_closed} positioner"
        if n_dcas:
            msg += f", utförde DCA på {n_dcas} tickers"
        print(msg)
        if n_closed:
            for c in closed[:5]:
                reason = c.get("exit_reason", "?")
                print(f"     🔴 {c['ticker']} - {c['pnl']:+.2f} ({c['pnl_pct']:+.1f}%) | {reason}")
            if n_closed > 5:
                print(f"     ... och {n_closed-5} till")

    return {"updated": updated, "closed": len(closed), "dcas": len(dcas)}


# ══════════════════════════════════════════════════════════════
# STATISTIK & RAPPORT
# ══════════════════════════════════════════════════════════════

def calc_statistics() -> dict:
    """Beräknar samlad statistik för alla stängda paper trades."""
    trades = _load(TRADES_FILE)
    portfolio = _load(PORTFOLIO_FILE)

    closed = [t for t in trades if t["status"] == "CLOSED" and t.get("pnl_pct") is not None]

    if not closed:
        return {"status": "Inga stängda positioner ännu"}

    rets = [t["pnl_pct"] for t in closed]

    # Per vecka - vägd genomsnittlig avkastning
    weeks = {}
    for t in closed:
        w = t["week"]
        if w not in weeks:
            weeks[w] = []
        weeks[w].append(t["pnl_pct"])

    weekly_rets = [np.mean(v) for v in weeks.values()]

    sharpe = (np.mean(weekly_rets) / np.std(weekly_rets) * np.sqrt(52)) \
        if len(weekly_rets) > 1 and np.std(weekly_rets) > 0 else None

    win_rate = sum(1 for r in rets if r > 0) / len(rets) * 100 if rets else 0

    # Exit reason statistik
    exit_reasons = {}
    for t in closed:
        reason = t.get("exit_reason", "unknown")
        exit_reasons[reason] = exit_reasons.get(reason, 0) + 1

    # DCA statistik
    dca_trades = [t for t in closed if t.get("dca_count", 0) > 0]
    dca_avg_pnl = np.mean([t["pnl_pct"] for t in dca_trades]) if dca_trades else None

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
        "exit_reasons":      exit_reasons,
        "dca_trades":        len(dca_trades),
        "dca_avg_pnl":       round(dca_avg_pnl, 2) if dca_avg_pnl is not None else None,
    }


def print_status(verbose: bool = True):
    """Skriver ut nuvarande portföljstatus i terminalen."""
    trades = _load(TRADES_FILE)
    portfolio = _load(PORTFOLIO_FILE)

    open_trades = [t for t in trades if t["status"] == "OPEN"]
    closed_trades = [t for t in trades if t["status"] == "CLOSED"]

    print(f"\n{'═'*65}")
    print("📄 PAPER TRADING v2 - STATUS")
    print(f"{'═'*65}")
    print(f"  Öppna positioner:   {len(open_trades)}")
    print(f"  Stängda positioner: {len(closed_trades)}")

    if open_trades:
        print(f"\n  Öppna positioner:")
        print(f"  {'Ticker':<14} {'Köp':>8} {'Senast':>8} {'P&L%':>8}  {'SL':>8} {'TP':>8} {'Trail':>8}")
        print(f"  {'─'*14} {'─'*8} {'─'*8} {'─'*8}  {'─'*8} {'─'*8} {'─'*8}")
        for t in sorted(open_trades, key=lambda x: x["week"], reverse=True):
            curr = t.get("current_price", t["buy_price"])
            pnl_pct = t.get("pnl_pct", 0) or 0
            sign = "+" if pnl_pct >= 0 else ""
            sl = t.get("stop_loss", 0)
            tp = t.get("take_profit", 0)
            trail = t.get("trailing_stop", 0)
            ts = f"{trail:.2f}" if trail else "-"
            print(f"  {t['ticker']:<14} {t['buy_price']:>8.2f} {curr:>8.2f} "
                  f"{sign}{pnl_pct:>7.1f}%  {sl:>8.2f} {tp:>8.2f} {ts:>8}")
            # Visa DCA om någon
            if t.get("dca_count", 0) > 0:
                print(f"  {' '*14} {'─ DCA x'}{t['dca_count']}")

    stats = calc_statistics()
    if "n_trades" in stats:
        print(f"\n  {'─'*50}")
        print(f"  Track record ({stats['n_weeks']} veckor):")
        print(f"  Snittavkastning/trade:  {stats['avg_return_pct']:+.2f}%")
        print(f"  Medianavkastning:       {stats['median_return_pct']:+.2f}%")
        print(f"  Win rate:               {stats['win_rate_pct']:.0f}%")
        if stats.get("sharpe"):
            print(f"  Sharpe (annualiserad):  {stats['sharpe']:.2f}")
        print(f"\n  Bästa trade: {stats['best_trade']['ticker']} "
              f"{stats['best_trade']['pnl_pct']:+.1f}%")
        print(f"  Sämsta trade: {stats['worst_trade']['ticker']} "
              f"{stats['worst_trade']['pnl_pct']:+.1f}%")

        # Exit reason fördelning
        if stats.get("exit_reasons"):
            print(f"\n  Exit-anledningar:")
            for reason, count in sorted(stats["exit_reasons"].items(), key=lambda x: -x[1]):
                reason_name = {
                    f"stop_loss_{STOP_LOSS_PCT:.0f}%": f"🚫 Stop-loss ({STOP_LOSS_PCT:.0f}%)",
                    f"take_profit_{TAKE_PROFIT_PCT:.0f}%": f"✅ Take-profit ({TAKE_PROFIT_PCT:.0f}%)",
                    f"partial_{PARTIAL_PROFIT_PCT:.0f}%": f"🔶 Delvinst ({PARTIAL_PROFIT_PCT:.0f}%)",
                    f"trailing_stop_{TRAILING_DISTANCE:.0f}%": f"🔻 Trailing stop ({TRAILING_DISTANCE:.0f}%)",
                    "ai_stop_loss": "🤖 AI stop-loss",
                }.get(reason, reason)
                print(f"    {reason_name}: {count} st")
    else:
        print(f"\n  {stats['status']}")

    print(f"{'═'*65}\n")


def build_paper_trading_section(top_n: int = 5) -> str:
    """
    Bygger en markdown-sektion för veckans rapport.
    Visar track record och senaste öppna positioner.
    """
    trades = _load(TRADES_FILE)
    stats = calc_statistics()

    if not trades:
        return ""

    open_trades = [t for t in trades if t["status"] == "OPEN"]
    closed_trades = [t for t in trades if t["status"] == "CLOSED"]

    lines = ["\n## 📄 Paper trading - Track record (v2)\n"]

    # Statistik
    if "n_trades" in stats:
        lines.append(f"**{stats['n_weeks']} veckor** * "
                     f"Snitt: **{stats['avg_return_pct']:+.2f}%/trade** * "
                     f"Median: **{stats['median_return_pct']:+.2f}%** * "
                     f"Win rate: **{stats['win_rate_pct']:.0f}%** * "
                     f"Sharpe: **{stats.get('sharpe', '--')}**\n")

        if stats.get("exit_reasons"):
            parts = []
            for reason, count in sorted(stats["exit_reasons"].items(), key=lambda x: -x[1]):
                icon = "✅" if "profit" in reason else "🚫" if "stop" in reason or "loss" in reason else "🔶"
                parts.append(f"{icon} {reason.replace('_', ' ')}: {count}")
            lines.append("  " + " * ".join(parts) + "\n")
    else:
        lines.append("_Inga stängda positioner ännu - resultaten visas efter 4 veckor_\n")

    # Senaste stängda positioner
    if closed_trades:
        recent = sorted(closed_trades, key=lambda t: t.get("sell_date", ""), reverse=True)[:top_n]
        lines.append("### Senaste avslutade")
        lines.append("| Vecka | Ticker | Köp | Sälj | P&L % | Exit |")
        lines.append("|-------|--------|-----|------|-------|------|")
        for t in recent:
            sign = "+" if t.get("pnl_pct", 0) >= 0 else ""
            reason = t.get("exit_reason", "--")
            if reason:
                reason = reason.replace("_", " ")[:20]
            lines.append(
                f"| {t['week']} | `{t['ticker']}` | "
                f"{t['buy_price']:.2f} | {t.get('sell_price', '--'):.2f} | "
                f"**{sign}{t.get('pnl_pct', 0):.1f}%** | {reason} |"
            )
        lines.append("")

    # Öppna positioner
    if open_trades:
        lines.append("### Öppna positioner")
        lines.append("| Vecka | Ticker | Köp | Senast | P&L % | Stop-loss | Take-profit |")
        lines.append("|-------|--------|-----|--------|-------|-----------|-------------|")
        for t in sorted(open_trades, key=lambda x: x["week"], reverse=True)[:top_n]:
            sign = "+" if t.get("pnl_pct", 0) >= 0 else ""
            sl = t.get("stop_loss", 0)
            tp = t.get("take_profit", 0)
            lines.append(
                f"| {t['week']} | `{t['ticker']}` | "
                f"{t['buy_price']:.2f} | {t.get('current_price', '--'):.2f} | "
                f"**{sign}{t.get('pnl_pct', 0):.1f}%** | "
                f"{sl:.2f} | {tp:.2f} |"
            )
        lines.append("")

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════
# CLI-ENTRY
# ══════════════════════════════════════════════════════════════

def close_all_positions():
    """Stänger alla öppna positioner (nöd-försäljning)."""
    trades = _load(TRADES_FILE)
    n_closed = 0
    today = date.today().isoformat()

    for trade in trades:
        if trade["status"] != "OPEN":
            continue
        price = _get_price(trade["ticker"]) or trade["buy_price"]
        pnl = (price - trade["buy_price"]) * trade["shares"]
        pnl_pct = (price / trade["buy_price"] - 1) * 100
        trade["status"] = "CLOSED"
        trade["sell_price"] = round(price, 4)
        trade["sell_date"] = today
        trade["exit_reason"] = "manual_close_all"
        trade["pnl"] = round(pnl, 2)
        trade["pnl_pct"] = round(pnl_pct, 2)
        n_closed += 1

    _save(TRADES_FILE, trades)
    print(f"  ✅ Stängde {n_closed} positioner manuellt.\n")
    print_status()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Paper Trading v2 - simulera systemets rekommendationer med riskhantering"
    )
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("status", help="Visa nuvarande status och track record")
    p_upd = sub.add_parser("update", help="Uppdatera priser + kolla stop-loss/take-profit/DCA")
    p_upd.add_argument("--close-after", type=int, default=CLOSE_AFTER_WEEKS,
                       help=f"Stäng positioner äldre än N veckor (default: {CLOSE_AFTER_WEEKS})")
    sub.add_parser("report", help="Detaljerad rapport")
    sub.add_parser("close_all", help="Stäng alla öppna positioner (nödförsäljning)")

    args = parser.parse_args()

    if args.cmd == "status":
        update_prices(verbose=False)
        print_status()

    elif args.cmd == "update":
        result = update_prices(close_after_weeks=args.close_after, verbose=True)
        print(f"\n  Sammanfattning: {result['updated']} uppdaterade, "
              f"{result['closed']} stängda, {result['dcas']} DCA\n")
        print_status()

    elif args.cmd == "report":
        update_prices(verbose=False)
        stats = calc_statistics()
        print("\n📊 Detaljerad statistik:")
        for k, v in stats.items():
            if k not in ("best_trade", "worst_trade", "weekly_rets"):
                print(f"  {k}: {v}")

    elif args.cmd == "close_all":
        close_all_positions()

    else:
        parser.print_help()
        print("\nExempel:")
        print("  python portfolio/paper_trading.py status")
        print("  python portfolio/paper_trading.py update")
        print("  python portfolio/paper_trading.py close_all")