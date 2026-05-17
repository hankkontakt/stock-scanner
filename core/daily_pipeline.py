"""
daily_pipeline.py – Central scanner- & rapport-pipeline
======================================================
Ersätter: morning_scan.py, evening_scan.py, scan.py,
          opportunity_scan.py, ai_weekly_summary.py

Kör med:
    python -c "from core.daily_pipeline import run_pipeline; run_pipeline('morning')"
    python -c "from core.daily_pipeline import run_pipeline; run_pipeline('evening')"
    python -c "from core.daily_pipeline import run_pipeline; run_pipeline('weekly')"
    python -c "from core.daily_pipeline import run_pipeline; run_pipeline('smallcap')"
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, date
from pathlib import Path
from typing import Optional

import pandas as pd
import numpy as np

# Projektrot (för Streamlit Cloud-kompatibilitet)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import config
from core.global_markets import (
    fetch_global_indices, format_index_summary_short, get_global_market_narrative,
)
from core.email_template import send_email, build_section_header, build_pnl_cell
from core.data_fetcher import fetch_prices_only, update_scored_with_prices, fetch_universe_data
from core.scoring import score_universe
from core import ai_analysis
from core.country_flags import flag_for_ticker

# ── Sökvägar ─────────────────────────────────────────────────────────────────
DATA_DIR = ROOT / "data"
REPORT_DIR = ROOT / "reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)

# ── Logger ───────────────────────────────────────────────────────────────────
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(message)s")


# ══════════════════════════════════════════════════════════════════════════════
# DATALADDNING
# ══════════════════════════════════════════════════════════════════════════════

def _latest_report(pattern: str = "scored_universe_*.csv") -> Optional[Path]:
    """Hitta senaste rapport-CSV som matchar mönstret."""
    files = sorted(REPORT_DIR.glob(pattern), reverse=True)
    return files[0] if files else None


def _load_latest_scored(pattern: str = "scored_universe_*.csv") -> pd.DataFrame:
    """Ladda senaste scored_universe CSV."""
    path = _latest_report(pattern)
    if path and path.exists():
        df = pd.read_csv(path, low_memory=False)
        df.columns = df.columns.str.strip()
        logger.info(f"  📂 Laddade {path.name} ({len(df)} rader)")
        return df
    logger.warning("  ⚠ Ingen scored_universe CSV hittad – kör utan scandata")
    return pd.DataFrame()


def _load_portfolio() -> pd.DataFrame:
    """Ladda holdings.csv."""
    path = DATA_DIR / "holdings.csv"
    if path.exists():
        try:
            df = pd.read_csv(path)
            df["ticker"] = df["ticker"].str.upper().str.strip()
            logger.info(f"  📂 Laddade portfölj ({len(df)} innehav)")
            return df
        except Exception as e:
            logger.warning(f"  ⚠ Kunde inte ladda portfölj: {e}")
    return pd.DataFrame(columns=["ticker", "shares", "cost_basis"])


def _load_watchlist() -> list:
    """Ladda watchlist.json."""
    path = DATA_DIR / "watchlist.json"
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            logger.info(f"  📂 Laddade watchlist ({len(data)} tickers)")
            return data
        except Exception as e:
            logger.warning(f"  ⚠ Kunde inte ladda watchlist: {e}")
    return []


def _enrich_holdings(holdings: pd.DataFrame, scored: pd.DataFrame) -> list[dict]:
    """Berika portföljinnehav med scan-data."""
    if scored.empty or "ticker" not in scored.columns:
        return []

    score_lookup = scored.set_index("ticker").to_dict("index")
    enriched = []

    def _lookup(ticker_in: str) -> dict:
        """Tolerera holdings utan börssuffix: prova .ST, .HE, .CO, .OL för svenska/nordiska."""
        if not ticker_in:
            return {}
        if ticker_in in score_lookup:
            return score_lookup[ticker_in]
        if "." not in ticker_in:
            for suffix in (".ST", ".HE", ".CO", ".OL"):
                candidate = ticker_in + suffix
                if candidate in score_lookup:
                    return score_lookup[candidate]
        return {}

    for _, h in holdings.iterrows():
        t = str(h.get("ticker", "")).upper().strip()
        sc = _lookup(t)
        price = sc.get("current_price") or sc.get("close", 0)
        cost = h.get("cost_basis", 0)
        shares = h.get("shares", 0)

        try:
            mv = float(price) * float(shares) if price and shares > 0 else 0
        except (ValueError, TypeError):
            mv = 0

        pnl_pct = ((float(price) / float(cost)) - 1) * 100 if price and cost > 0 else None
        pnl_pct = round(pnl_pct, 1) if pnl_pct is not None else None

        stop_loss_pct = round(((float(cost) * 0.85) / float(cost) - 1) * 100, 1) if cost > 0 else None

        enriched.append({
            "ticker": t,
            "name": sc.get("name", t),
            "sector": sc.get("sector", "—"),
            "shares": shares,
            "cost_basis": cost,
            "price": round(float(price), 2) if price else None,
            "market_value": round(mv, 0),
            "pnl_pct": pnl_pct,
            "stop_loss_pct": stop_loss_pct,
            "score": sc.get("score_total"),
            "entry": sc.get("entry_signal", "—"),
            "trend": sc.get("trend_signal", "—"),
            "rsi": sc.get("rsi_14"),
            "vs_ma50": sc.get("price_vs_ma50"),
            "vs_ma200": sc.get("price_vs_ma200"),
        })

    return enriched


def _get_score_deltas(today_df: pd.DataFrame, yesterday_df: pd.DataFrame,
                      top_n: int = 10) -> dict:
    """
    Jämför dagens vs gårdagens scored_universe.
    Returnerar:
        movers_up:   top_n aktier med störst score-ökning
        movers_down: top_n aktier med störst score-minskning
        rsi_spikes:  aktier där RSI korsade 30↑ eller 70↓
        big_price:   aktier med >4% kursrörelse
    """
    if today_df is None or today_df.empty or yesterday_df is None or yesterday_df.empty:
        return {}
    needed_today = [c for c in ["ticker", "score_total", "rsi_14", "close"] if c in today_df.columns]
    needed_yest  = [c for c in ["ticker", "score_total", "rsi_14", "close"] if c in yesterday_df.columns]
    if "ticker" not in needed_today or "ticker" not in needed_yest:
        return {}
    merged = today_df[needed_today].merge(
        yesterday_df[needed_yest].rename(columns={
            "score_total": "score_yesterday",
            "rsi_14":      "rsi_yesterday",
            "close":       "close_yesterday",
        }),
        on="ticker", how="inner",
    )
    if "score_total" in merged.columns and "score_yesterday" in merged.columns:
        merged["score_delta"] = (merged["score_total"] - merged["score_yesterday"]).round(1)
    else:
        merged["score_delta"] = 0.0
    if "close" in merged.columns and "close_yesterday" in merged.columns:
        merged["price_delta_pct"] = (
            (merged["close"] - merged["close_yesterday"]) / merged["close_yesterday"] * 100
        ).round(1)
    else:
        merged["price_delta_pct"] = 0.0
    # RSI-korsningar
    if "rsi_14" in merged.columns and "rsi_yesterday" in merged.columns:
        merged["rsi_crossed_30up"]  = (merged["rsi_yesterday"] < 30) & (merged["rsi_14"] >= 30)
        merged["rsi_crossed_70down"] = (merged["rsi_yesterday"] > 70) & (merged["rsi_14"] <= 70)
    else:
        merged["rsi_crossed_30up"]  = False
        merged["rsi_crossed_70down"] = False

    base_cols = ["ticker", "score_total", "score_yesterday", "score_delta", "price_delta_pct"]
    return {
        "movers_up":   merged.nlargest(top_n, "score_delta")[base_cols].to_dict("records"),
        "movers_down": merged.nsmallest(top_n, "score_delta")[base_cols].to_dict("records"),
        "rsi_spikes":  merged[merged["rsi_crossed_30up"] | merged["rsi_crossed_70down"]][
            ["ticker", "rsi_14", "rsi_yesterday", "rsi_crossed_30up", "rsi_crossed_70down"]
        ].to_dict("records"),
        "big_price":   merged[merged["price_delta_pct"].abs() >= 4].nlargest(10, "price_delta_pct")[
            base_cols
        ].to_dict("records"),
    }


def _get_opportunities(scored: pd.DataFrame, max_total: int = 5) -> list[dict]:
    """Identifiera opportunities från scored_universe (inget API-anrop)."""
    if scored.empty or "score_total" not in scored.columns:
        return []

    opportunities = []
    top = scored[scored["score_total"] >= 65].copy()

    # Dip i upptrend: score >= 65, 3d retur mellan -12% och -3%
    if "return_3d" in top.columns:
        dips = top[(top["return_3d"] >= -12) & (top["return_3d"] <= -3)]
        for _, r in dips.head(4).iterrows():
            opportunities.append({
                "ticker": r.get("ticker", "?"),
                "type": "📉 Dip i upptrend",
                "score": r.get("score_total"),
                "reason": f"-{abs(r['return_3d']):.1f}% på 3 dagar",
            })

    # Utbrott: nära 52w-high
    if "pct_from_52w_high" in top.columns:
        breakouts = top[(top["pct_from_52w_high"] >= -5) & (top["pct_from_52w_high"] <= 0)]
        for _, r in breakouts.head(3).iterrows():
            opportunities.append({
                "ticker": r.get("ticker", "?"),
                "type": "🚀 Utbrott",
                "score": r.get("score_total"),
                "reason": f"{r['pct_from_52w_high']:.1f}% från ATH",
            })

    # Översåld studs: RSI < 30, score >= 70
    if "rsi_14" in top.columns:
        oversold = top[(top["rsi_14"] < 30) & (top["score_total"] >= 70)]
        for _, r in oversold.head(3).iterrows():
            opportunities.append({
                "ticker": r.get("ticker", "?"),
                "type": "🔄 Översåld studs",
                "score": r.get("score_total"),
                "reason": f"RSI {r['rsi_14']:.0f}",
            })

    # Begränsa totalt antal
    return opportunities[:max_total]


def _get_top_bottom(scored: pd.DataFrame, top_n: int = 5) -> tuple[list, list]:
    """Hämta top-N och bottom-N från scored_universe."""
    if scored.empty or "score_total" not in scored.columns:
        return [], []

    top = scored.nlargest(top_n, "score_total")
    bottom = scored.nsmallest(top_n, "score_total")

    def _fmt(df):
        return [
            {
                "ticker": r.get("ticker", "?"),
                "score": r.get("score_total"),
                "entry": r.get("entry_signal", "—"),
                "sector": r.get("sector", "—"),
                "return_1m": r.get("return_1m"),
            }
            for _, r in df.iterrows()
        ]

    return _fmt(top), _fmt(bottom)


# ══════════════════════════════════════════════════════════════════════════════
# RAPPORT-GENERATOR (Markdown → email)
# ══════════════════════════════════════════════════════════════════════════════

def _section(title: str, content: str, level: int = 2) -> str:
    """Bygg en markdown-sektion."""
    prefix = "#" * level
    return f"\n{prefix} {title}\n\n{content}\n"


def _table(headers: list, rows: list) -> str:
    """Bygg en markdown-tabell."""
    if not rows:
        return ""
    header = "| " + " | ".join(headers) + " |"
    sep = "| " + " | ".join(["---"] * len(headers)) + " |"
    data = []
    for row in rows:
        data.append("| " + " | ".join(str(c) for c in row) + " |")
    return header + "\n" + sep + "\n" + "\n".join(data) + "\n"


def _portfolio_table(enriched: list, show_stop_loss: bool = False) -> str:
    """Bygg en portföljtabell i markdown."""
    if not enriched:
        return "*(Inga innehav)*\n"

    headers = ["Ticker", "Score", "P&L", "Entry", "Trend"]
    if show_stop_loss:
        headers.append("Stop-loss")

    rows = []
    for h in enriched[:20]:
        pnl = f"{h['pnl_pct']:+.1f}%" if h['pnl_pct'] is not None else "—"
        row = [
            f"**{h['ticker']}**",
            f"{h['score']:.0f}" if h['score'] else "—",
            pnl,
            h['entry'],
            h['trend'],
        ]
        if show_stop_loss:
            sl = f"{h['stop_loss_pct']:+.1f}%" if h['stop_loss_pct'] else "—"
            row.append(sl)
        rows.append(row)

    return _table(headers, rows)


def _opportunity_section(opportunities: list) -> str:
    """Bygg opportunities-sektion."""
    if not opportunities:
        return ""
    out = "### ⚡ Dagens möjligheter\n\n"
    for opp in opportunities:
        emoji = opp.get("type", "•")
        ticker = opp["ticker"]
        score = opp.get("score", 0)
        reason = opp.get("reason", "")
        out += f"- {emoji} **{ticker}** (score {score:.0f}) – {reason}\n"
    return out + "\n"


def _section_header(title: str, subtitle: str = "") -> str:
    """Bygg en formaterad sektionsrubrik för mail."""
    s = f"## {title}"
    if subtitle:
        s += f" _{subtitle}_"
    return s + "\n"


# ══════════════════════════════════════════════════════════════════════════════
# AI-PROMPTS
# ══════════════════════════════════════════════════════════════════════════════

def _build_ai_morning_context(indices, enriched, watchlist, top_10, bottom_5,
                               opportunities, news_text, regime, vix) -> str:
    """Bygg kontext för morgonbriefens AI-anrop."""
    ctx = {
        "indices": {t: {"change_pct": d["change_pct"], "close": d["close"]}
                    for t, d in indices.items() if d.get("change_pct") is not None},
        "portfolio": [{"ticker": h["ticker"], "pnl_total_pct": h["pnl_pct"],
                       "score": h["score"], "entry": h["entry"],
                       "stop_loss_pct": h["stop_loss_pct"], "rsi": h["rsi"]}
                      for h in enriched if h["ticker"]],
        "watchlist": [{"ticker": w, "score": None} for w in watchlist],
        "top_10": [{"ticker": t["ticker"], "score": t["score"], "entry": t["entry"]}
                   for t in top_10],
        "opportunities": opportunities,
        "news": news_text or "Inga större nyheter",
        "regime": regime or "OSÄKER",
        "vix": vix,
    }
    return json.dumps(ctx, ensure_ascii=False, default=str)


def _build_ai_evening_context(indices, enriched, watchlist, top_5, bottom_5,
                               opportunities, pnl_total, earnings_tomorrow, macro) -> str:
    """Bygg kontext för kvällsbrevets AI-anrop."""
    ctx = {
        "indices": {t: {"change_pct": d["change_pct"], "close": d["close"]}
                    for t, d in indices.items() if d.get("change_pct") is not None},
        "portfolio_daily_pnl": {"pct": pnl_total},
        "holdings": [{"ticker": h["ticker"], "pnl_daily_pct": h["pnl_pct"],
                      "score": h["score"], "entry": h["entry"],
                      "trend": h["trend"], "rsi": h["rsi"]}
                     for h in enriched],
        "watchlist_changes": watchlist,
        "top_5_today": [{"ticker": t["ticker"], "score": t["score"]} for t in top_5],
        "bottom_5_today": [{"ticker": b["ticker"], "score": b["score"]} for b in bottom_5],
        "opportunities": opportunities,
        "macro_tomorrow": macro or "Inga större makrohändelser imorgon",
        "earnings_tomorrow": earnings_tomorrow or [],
    }
    return json.dumps(ctx, ensure_ascii=False, default=str)


def _build_ai_weekly_context(scored, enriched, watchlist, top_10, bottom_5,
                              sector_momentum, opportunities, news, indices) -> str:
    """Bygg kontext för veckorapportens djupa AI-anrop."""
    sector_data = {}
    if "sector" in scored.columns and "score_total" in scored.columns:
        sec_agg = scored.groupby("sector")["score_total"].agg(["mean", "count", "max"])
        sector_data = sec_agg.to_dict("index")

    ctx = {
        "regime": "OSÄKER",
        "indices": {t: {"change_pct": d["change_pct"]}
                    for t, d in indices.items() if d.get("change_pct") is not None},
        "portfolio_weekly_summary": {
            "total_pnl_pct": sum(h["pnl_pct"] for h in enriched if h["pnl_pct"] is not None) / max(len([h for h in enriched if h["pnl_pct"] is not None]), 1),
            "best": max([h for h in enriched if h["pnl_pct"] is not None], key=lambda h: h["pnl_pct"], default={}).get("ticker", "—"),
            "worst": min([h for h in enriched if h["pnl_pct"] is not None], key=lambda h: h["pnl_pct"], default={}).get("ticker", "—"),
        },
        "holdings": enriched,
        "top_10_week": top_10,
        "bottom_5_warnings": bottom_5,
        "sector_momentum": {str(k): v for k, v in sector_data.items()},
        "opportunities": opportunities,
        "watchlist": watchlist,
        "news_highlights": news or [],
    }
    return json.dumps(ctx, ensure_ascii=False, default=str)


MORNING_AI_SYSTEM_PROMPT = """Du är en personlig portföljrådgivare. Skapa en morgonbrief baserad på datan nedan.

TÄNK PÅ:
- Skriv på svenska, personligt och engagerande
- Använd emojis för att markera riktning (🟢🔴🟡)
- Var konkret med rekommendationer
- Fokusera på vad som är VIKTIGT för mottagaren just idag

STRUKTUR (800-1000 ord):
1. 🌏 **Global överblick** – Vad hände i natt? USA-stängning, Asien-öppning, Europa-öppning. VIX-nivå.
2. 💼 **Din portfölj** – Gå igenom varje innehav. Är någon nära stop-loss? Någon som sticker ut?
3. ⭐ **Dina bevakningar** – Har någon rört sig mycket? Något nytt att titta på?
4. 🏆 **Dagens hetaste** – Topp-5 just nu. Varför?
5. ⚠️ **Varningar** – Stop-loss som triggas idag, oroliga signaler
6. 📰 **Nyheter som påverkar dig** – Kort om vad som händer
7. 🎯 **Dagens fokus** – 1-2 konkreta saker att göra/hålla koll på

Avsluta med dagens humör: t.ex. "📈 Optimistisk – mycket i rörelse" eller "📉 Försiktig – oroliga signaler"
"""

EVENING_AI_SYSTEM_PROMPT = """Du är en personlig portföljrådgivare. Skapa en kvällsrapport baserad på datan nedan.

TÄNK PÅ:
- Skriv på svenska, personligt och engagerande
- Använd emojis för att markera riktning (🟢🔴🟡)
- Var konkret med rekommendationer
- Analysera dagen och blicka framåt

STRUKTUR (800-1000 ord):
1. 📊 **Dagens utveckling** – Hur gick börserna idag? (Sverige, Europa, USA öppen)
2. 💼 **Portfölj-P&L** – Hur mycket tjänade/förlorade du idag? Gå igenom varje innehav
3. ⭐ **Bevakningar som rört sig** – Någon som stack ut idag?
4. 🏆 **Dagens topp-5 & botten-5** – Bästa och sämsta aktierna
5. 🔮 **Imorgon** – Makro-siffror, earnings, opportunities som uppstått
6. 🎯 **Handlingsplan** – Vad göra imorgon bitti? Köp, sälj, avvakta?

Avsluta med: "Imorgon tittar jag extra på [aktie] – för att [anledning]"
"""

WEEKLY_AI_SYSTEM_PROMPT = """Du är en senior portföljförvaltare. Skapa en DIUP veckoanalys baserad på datan nedan.

TÄNK PÅ:
- Skriv på svenska, analytiskt och insiktsfullt
- Använd emojis sparsamt (🟢🔴 för riktning)
- Detta är en DJUP analys – inte en snabb överblick
- Var modig med rekommendationer

STRUKTUR (1500-2000 ord):
1. 📈 **Marknadsregim & bredd** – Veckans utveckling, VIX, bredd, sektorer
2. 🌏 **Globalt** – USA, Europa, Asien – trender och makro
3. 💼 **Djup portföljanalys** – Varje innehav med trend, rekommendation, stop-loss
4. ⭐ **Bevakningslistan** – Bör du lägga till/ta bort något? AI-bedömning
5. 🏆 **Topp-10 köprekommendationer** – Med motivering per aktie
6. 🔴 **Bottom-5 varningar** – Aktier att minska/undvika
7. 🏭 **Sektormomentum** – Vilka sektorer leder/släpar
8. 📰 **Nyheter & makro** – Viktigaste händelserna
9. 🎯 **Kommande vecka** – Earnings, makro, opportunities
10. ✅ **Rekommendation** – Om du bara gör EN sak denna vecka...
"""

NEWS_ALERT_SYSTEM_PROMPT = """Du analyserar en nyhet för en aktie som mottagaren äger eller bevakar.

Bedöm:
1. Är denna nyhet viktig för mottagaren? (JA/NEJ)
2. Om JA: på en skala 1-5, hur viktig?
3. Förklara påverkan på DERAS portfölj
4. Rekommendera åtgärd (om någon)

Skriv på svenska, max 300 ord. Använd emojis. Var konkret.
"""


# ══════════════════════════════════════════════════════════════════════════════
# HUVUDFUNKTION: run_pipeline
# ══════════════════════════════════════════════════════════════════════════════

def _cleanup_old_reports(max_days: int = 60) -> int:
    """Raderar rapportfiler äldre än max_days. Returnerar antalet raderade filer."""
    import time as _t
    cutoff = _t.time() - max_days * 86400
    patterns = ["scored_universe_*.csv", "smallcap_scored_*.csv",
                "*.md", "*.txt"]
    removed = 0
    for pat in patterns:
        for f in REPORT_DIR.glob(pat):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
                    removed += 1
            except Exception:
                pass
    if removed:
        logger.info(f"🧹 Raderade {removed} gamla rapportfiler (> {max_days} dagar)")
    return removed


def run_pipeline(mode: str = "morning", force_refresh: bool = False):
    """
    Kör dagliga pipeline: hämta data, skapa rapport, skicka mail.

    Args:
        mode: "morning" | "evening" | "weekly" | "smallcap"
        force_refresh: Hoppa över cache, tvinga ny data
    """
    start_time = time.time()
    date_str = date.today().strftime("%Y-%m-%d")
    day_name = datetime.now().strftime("%A")

    # Städa gamla rapporter (en gång per körning är OK – snabbt)
    _cleanup_old_reports(max_days=60)

    logger.info(f"\n{'='*50}")
    logger.info(f"🚀 MarketScan Pipeline – mode={mode} – {date_str}")
    logger.info(f"{'='*50}\n")

    # ═══════════════════════════════════════════════════════════════════════
    # 1. LADDA DATA
    # ═══════════════════════════════════════════════════════════════════════

    # Globala index (ALLTID)
    logger.info("📡 Hämtar globala index...")
    indices = fetch_global_indices()
    narrative = get_global_market_narrative(indices)
    short_summary = format_index_summary_short(indices)
    vix = indices.get("^VIX", {}).get("close") if indices else None
    logger.info(f"  {short_summary}")

    # Scored universe
    if mode in ("morning", "evening"):
        scored = _load_latest_scored("scored_universe_*.csv")
        _ml_universe = "universe"
    elif mode == "weekly":
        # ── Full universe scan ────────────────────────────────────────────────
        # Hämtar data för ALLA tickers i UNIVERSE + custom-lista,
        # scorer dem och sparar ny scored_universe_*.csv.
        # Körs ~2-3 min med 8 workers + 30-dagars fundamentalcache.
        logger.info("🔄 Full universe scan – hämtar data för alla tickers...")
        from core.macro_regime import detect_regime

        custom_tickers = [c["ticker"] for c in config.load_custom_universe()]
        all_tickers = list(dict.fromkeys(config.UNIVERSE + custom_tickers))
        logger.info(f"  📋 Universe: {len(all_tickers)} tickers")

        raw_df = fetch_universe_data(all_tickers, verbose=True)

        if not raw_df.empty:
            # Detektera marknadsregim för dynamiska vikter
            try:
                regime_info = detect_regime()
                regime = regime_info.get("regime", "OSÄKER")
                logger.info(f"  🌡 Marknadsregim: {regime}")
            except Exception as _re:
                regime = "OSÄKER"
                logger.warning(f"  ⚠ Regime-detektion misslyckades: {_re} – kör OSÄKER")

            scored = score_universe(raw_df, regime=regime)
            logger.info(f"  ✅ Scorat {len(scored)} tickers")

            csv_path = REPORT_DIR / f"scored_universe_{date_str}.csv"
            scored.to_csv(csv_path, index=False)
            logger.info(f"  💾 Sparade {csv_path.name}")
        else:
            logger.warning("  ⚠ Universe fetch returnerade tom DataFrame – laddar senaste cache")
            scored = _load_latest_scored("scored_universe_*.csv")

        _ml_universe = "universe"
    elif mode == "smallcap":
        scored = _load_latest_scored("smallcap_scored_*.csv")
        _ml_universe = "smallcap"
    else:
        scored = pd.DataFrame()
        _ml_universe = None

    # ═══════════════════════════════════════════════════════════════════════
    # 1b. DAGLIG RE-SCORING (endast för morning/evening)
    #     Hämta nya priser för alla tickers → uppdatera scores
    # ═══════════════════════════════════════════════════════════════════════
    if mode in ("morning", "evening") and not scored.empty and "ticker" in scored.columns:
        logger.info("📡 Hämtar nya priser för re-scoring...")
        try:
            tickers = scored["ticker"].dropna().unique().tolist()
            # Begränsa till max 100 för att inte överbelasta yfinance
            price_tickers = [t for t in tickers if not t.startswith("^")][:100]
            
            price_data = fetch_prices_only(price_tickers, period="6mo", max_workers=12)
            if price_data:
                n_prices = len(price_data)
                scored = update_scored_with_prices(scored, price_data)
                logger.info(f"  ✅ Priser hämtade för {n_prices} tickers – scores uppdaterade")
                
                # Spara den uppdaterade CSV:n
                csv_path = REPORT_DIR / f"scored_universe_{date_str}.csv"
                scored.to_csv(csv_path, index=False)
                logger.info(f"  💾 Sparade uppdaterad CSV: {csv_path.name}")
            else:
                logger.warning("  ⚠ Inga priser kunde hämtas – använder gårdagens data")
        except Exception as e:
            logger.warning(f"  ⚠ Re-scoring misslyckades: {e} – använder gårdagens data")

    # ═══════════════════════════════════════════════════════════════════════
    # 1c. ML-PREDIKTION (om modell finns)
    #     Lägger till predicted_return + ml_rank-kolumner och sparar back.
    # ═══════════════════════════════════════════════════════════════════════
    if _ml_universe and not scored.empty and "ticker" in scored.columns:
        try:
            from core.ml_predictor import predict_returns
            scored_ml = predict_returns(scored, _ml_universe)
            if "predicted_return" in scored_ml.columns:
                scored = scored_ml
                logger.info(f"  🤖 ML-prediktioner tillagda för {_ml_universe} ({len(scored)} rader)")
                # Spara back så Streamlit-appen kan visa kolumnen
                if _ml_universe == "universe":
                    csv_path = REPORT_DIR / f"scored_universe_{date_str}.csv"
                else:
                    csv_path = REPORT_DIR / f"smallcap_scored_{date_str}.csv"
                scored.to_csv(csv_path, index=False)
        except Exception as e:
            logger.warning(f"  ⚠ ML-prediktion hoppades över: {e}")

    # ═══════════════════════════════════════════════════════════════════════
    # 1d. ML PAPER TRADING (om modell finns)
    #     Registrera dagens topp-N enligt ML som virtuella köp.
    # ═══════════════════════════════════════════════════════════════════════
    if _ml_universe and not scored.empty and "predicted_return" in scored.columns:
        try:
            from core.ml_paper_trading import record_daily_signals
            n_recorded = record_daily_signals(scored, universe=_ml_universe, top_n=10)
            if n_recorded:
                logger.info(f"  📈 ML paper trading: {n_recorded} signaler registrerade ({_ml_universe})")
        except Exception as e:
            logger.warning(f"  ⚠ ML paper trading hoppades över: {e}")

    # Portfölj & watchlist
    holdings = _load_portfolio()
    watchlist_raw = _load_watchlist()
    watchlist_tickers = [i.get("ticker", "") for i in watchlist_raw if i.get("ticker")]

    # Berika portfölj
    enriched = _enrich_holdings(holdings, scored)

    # Top/bottom från scored
    top_10, bottom_5 = _get_top_bottom(scored, top_n=10)

    # Opportunities
    opportunities = _get_opportunities(scored)

    # ═══════════════════════════════════════════════════════════════════════
    # 2. GENERERA RAPPORT (Markdown)
    # ═══════════════════════════════════════════════════════════════════════

    report_lines = []

    if mode == "morning":
        # ── Rubrik ────────────────────────────────────────────────────────
        report_lines.append(f"# 🌅 MarketScan Morgonbrief – {date_str}\n")
        report_lines.append(f"_{short_summary}_\n")
        report_lines.append(f"VIX: {vix}" if vix else "")
        report_lines.append("")

        # ── Globala index ─────────────────────────────────────────────────
        report_lines.append(_section_header("🌏 Global överblick"))
        report_lines.append(f"_{narrative}_\n")
        index_lines = []
        for ticker, data in indices.items():
            name = data.get("name", ticker)
            chg = data.get("change_pct")
            close = data.get("close")
            if chg is not None and close is not None:
                arrow = "🟢" if chg >= 0 else "🔴"
                index_lines.append(f"- {name} {arrow} **{chg:+.1f}%** ({close:,.0f})")
        if index_lines:
            report_lines.extend(index_lines[:15])

        # ── Stop-loss varningar ──────────────────────────────────────────
        sl_warnings = [h for h in enriched if h.get("pnl_pct") is not None and h["pnl_pct"] <= -12]
        if sl_warnings:
            report_lines.append(_section_header("⚠️ Stop-loss varningar"))
            for h in sl_warnings:
                report_lines.append(f"- 🔴 **{flag_for_ticker(h['ticker'])} {h['ticker']}** – {h['pnl_pct']:+.1f}% sedan inköp (stop-loss vid {h['stop_loss_pct']:+.1f}%)")
            report_lines.append("")

        # ── Portfölj ─────────────────────────────────────────────────────
        report_lines.append(_section_header("💼 Din portfölj"))
        if enriched:
            for h in enriched[:10]:
                emoji = "🟢" if (h.get("pnl_pct") or 0) >= 0 else "🔴"
                pnl = f"{h['pnl_pct']:+.1f}%" if h['pnl_pct'] is not None else "—"
                sl_info = f" (stop-loss vid {h['stop_loss_pct']:+.1f}%)" if h.get('stop_loss_pct') and (h.get('pnl_pct') or 0) <= -10 else ""
                score_val = h.get('score')
                score_str = f"{score_val:.0f}" if score_val is not None else "—"
                entry_str = h.get('entry', '—') or '—'
                report_lines.append(f"- {emoji} **{flag_for_ticker(h['ticker'])} {h['ticker']}** – {pnl} | Score {score_str} | {entry_str}{sl_info}")
        else:
            report_lines.append("*(Inga innehav i portföljen)*")

        # ── Bevakningar ──────────────────────────────────────────────────
        if watchlist_tickers:
            report_lines.append(_section_header("⭐ Dina bevakningar"))
            for w in watchlist_tickers[:5]:
                report_lines.append(f"- {w}")

        # ── Topp-5 ───────────────────────────────────────────────────────
        if top_10:
            report_lines.append(_section_header("🏆 Dagens hetaste"))
            for t in top_10[:5]:
                report_lines.append(f"- **{flag_for_ticker(t['ticker'])} {t['ticker']}** – Score {t['score']:.0f} | {t['entry']} | {t['sector']}")

        # ── Opportunities ────────────────────────────────────────────────
        if opportunities:
            report_lines.append(_opportunity_section(opportunities))

        # ── Nyheter ──────────────────────────────────────────────────────
        report_lines.append(_section_header("📰 Nyheter"))
        report_lines.append("*(Nyheter hämtas via nyhetslarm – se separat mail)*")
        report_lines.append("")

        # ── AI-sektion ───────────────────────────────────────────────────
        report_lines.append(_section_header("🤖 AI: Dagens analys"))
        report_lines.append("*Genereras nedan...*\n")

    elif mode == "evening":
        # ── Rubrik ────────────────────────────────────────────────────────
        report_lines.append(f"# 🌆 MarketScan Kvällsbrev – {date_str}\n")
        report_lines.append(f"_{short_summary}_\n")

        # ── Dagens utveckling ────────────────────────────────────────────
        report_lines.append(_section_header("📊 Dagen som gick"))
        for ticker in ["^OMX", "^GDAXI", "^FTSE", "^GSPC", "^IXIC"]:
            data = indices.get(ticker)
            if data:
                name = data.get("name", ticker)
                chg = data.get("change_pct")
                close = data.get("close")
                if chg is not None and close is not None:
                    arrow = "🟢" if chg >= 0 else "🔴"
                    report_lines.append(f"- {name} {arrow} **{chg:+.1f}%** ({close:,.0f})")
        report_lines.append("")

        # ── Portfölj-P&L ─────────────────────────────────────────────────
        report_lines.append(_section_header("💼 Dagens portfölj"))
        if enriched:
            total_pnl = sum(h["pnl_pct"] for h in enriched if h["pnl_pct"] is not None)
            total_pnl = total_pnl / max(len([h for h in enriched if h["pnl_pct"] is not None]), 1)
            report_lines.append(f"**Snitt P&L: {total_pnl:+.1f}%**\n")
            for h in enriched:
                emoji = "🟢" if (h.get("pnl_pct") or 0) >= 0 else "🔴"
                pnl = f"{h['pnl_pct']:+.1f}%" if h['pnl_pct'] is not None else "—"
                score_str = f"{h['score']:.0f}" if h.get('score') is not None else "—"
                report_lines.append(f"- {emoji} **{flag_for_ticker(h['ticker'])} {h['ticker']}** – {pnl} | Score {score_str} | Rekommendation: {_get_rec(h)}")
        else:
            report_lines.append("*(Inga innehav i portföljen)*")

        # ── Dagens topp/bottom ───────────────────────────────────────────
        if top_10 or bottom_5:
            report_lines.append(_section_header("🏆 Dagens topp & botten"))
            if top_10:
                report_lines.append("**Bästa:** " + ", ".join(f"{flag_for_ticker(t['ticker'])} {t['ticker']} ({t['score']:.0f})" for t in top_10[:5]))
            if bottom_5:
                report_lines.append("**Sämsta:** " + ", ".join(f"{flag_for_ticker(b['ticker'])} {b['ticker']} ({b['score']:.0f})" for b in bottom_5[:5]))

        # ── Opportunities ────────────────────────────────────────────────
        if opportunities:
            report_lines.append(_opportunity_section(opportunities))

        # ── Imorgon ──────────────────────────────────────────────────────
        report_lines.append(_section_header("🔮 Imorgon"))
        report_lines.append("*(Makro- och earnings-kalender – se veckorapport)*")
        report_lines.append("")

        # ── AI-sektion ───────────────────────────────────────────────────
        report_lines.append(_section_header("🤖 AI: Dagens reflektion"))
        report_lines.append("*Genereras nedan...*\n")

    elif mode == "weekly":
        # ── Rubrik ────────────────────────────────────────────────────────
        day_sv = {"Monday": "måndag", "Tuesday": "tisdag", "Wednesday": "onsdag",
                  "Thursday": "torsdag", "Friday": "fredag", "Saturday": "lördag",
                  "Sunday": "söndag"}.get(day_name, day_name)
        report_lines.append(f"# 📊 MarketScan Veckorapport – v. {datetime.now().isocalendar()[1]}\n")
        report_lines.append(f"_{short_summary}_\n")

        # ── Marknadsregim ────────────────────────────────────────────────
        report_lines.append(_section_header("📈 Marknadsöversikt"))
        report_lines.append(f"- Globalt: {narrative}")
        if not scored.empty:
            avg_score = scored["score_total"].mean() if "score_total" in scored.columns else 0
            n_stark = int((scored.get("entry_signal") == "STARK").sum()) if "entry_signal" in scored.columns else 0
            report_lines.append(f"- Snittscore: {avg_score:.1f}")
            report_lines.append(f"- STARK entry-signal: {n_stark} st\n")

        # ── Sektorer ─────────────────────────────────────────────────────
        if "sector" in scored.columns and "score_total" in scored.columns:
            report_lines.append(_section_header("🏭 Sektorer"))
            sec = scored.groupby("sector")["score_total"].mean().sort_values(ascending=False)
            for sector, avg in sec.items():
                arrow = "🟢" if avg >= 60 else "🟡" if avg >= 45 else "🔴"
                report_lines.append(f"- {arrow} **{sector}** – snittscore {avg:.1f}")
            report_lines.append("")

        # ── Portfölj ─────────────────────────────────────────────────────
        report_lines.append(_section_header("💼 Portföljanalys"))
        if enriched:
            for h in enriched:
                rec = _get_rec(h)
                emoji = "🟢" if rec in ("BEHÅLL", "KÖP MER") else "🟡" if rec == "BEVAKA" else "🔴"
                pnl = f"{h['pnl_pct']:+.1f}%" if h['pnl_pct'] is not None else "—"
                score_str = f"{h['score']:.0f}" if h.get('score') is not None else "—"
                report_lines.append(f"- {emoji} **{flag_for_ticker(h['ticker'])} {h['ticker']}** – {pnl} | Score {score_str} | **{rec}**")
        else:
            report_lines.append("*(Inga innehav)*")

        # ── Topp-10 ──────────────────────────────────────────────────────
        if top_10:
            report_lines.append(_section_header("🏆 Topp-10 köprekommendationer"))
            for i, t in enumerate(top_10[:10], 1):
                report_lines.append(f"  {i}. **{flag_for_ticker(t['ticker'])} {t['ticker']}** – Score {t['score']:.0f} | {t['entry']} | {t['sector']}")

        # ── Bottom-5 ─────────────────────────────────────────────────────
        if bottom_5:
            report_lines.append(_section_header("🔴 Bottom-5 varningar"))
            for b in bottom_5[:5]:
                report_lines.append(f"- **{flag_for_ticker(b['ticker'])} {b['ticker']}** – Score {b['score']:.0f} | {b['entry']} | {b['sector']}")

        # ── Opportunities ────────────────────────────────────────────────
        if opportunities:
            report_lines.append(_opportunity_section(opportunities))

        # ── AI-sektion ───────────────────────────────────────────────────
        report_lines.append(_section_header("🤖 AI: Veckoanalys"))
        report_lines.append("*Genereras nedan...*\n")

    # ═══════════════════════════════════════════════════════════════════════
    # 3. AI-ANROP
    # ═══════════════════════════════════════════════════════════════════════

    ai_section = ""
    try:
        logger.info("  🤖 Anropar AI...")
        provider = os.getenv("AI_PROVIDER", "auto") or "auto"

        if mode == "morning":
            ctx = _build_ai_morning_context(
                indices, enriched, watchlist_tickers, top_10, bottom_5,
                opportunities, "", "OSÄKER", vix
            )
            result = ai_analysis.ai_chat(
                "Skapa dagens morgonbrief. Analysera datan och ge mig en personlig rapport.",
                context=ctx,
                provider=provider,
                depth="Djup",
            )
            ai_section = result

        elif mode == "evening":
            total_pnl = 0
            if enriched:
                vals = [h["pnl_pct"] for h in enriched if h["pnl_pct"] is not None]
                total_pnl = sum(vals) / len(vals) if vals else 0

            ctx = _build_ai_evening_context(
                indices, enriched, watchlist_tickers, top_10, bottom_5,
                opportunities, total_pnl, [], "Inga"
            )
            result = ai_analysis.ai_chat(
                "Skapa dagens kvällsrapport. Analysera datan och ge mig en personlig sammanfattning.",
                context=ctx,
                provider=provider,
                depth="Djup",
            )
            ai_section = result

        elif mode == "weekly":
            ctx = _build_ai_weekly_context(
                scored, enriched, watchlist_tickers, top_10, bottom_5,
                {}, opportunities, "", indices
            )
            result = ai_analysis.ai_chat(
                "Skapa en djup veckoanalys. Analysera datan och ge mig en fullständig rapport med rekommendationer.",
                context=ctx,
                provider=provider,
                depth="Extra djup",
            )
            ai_section = result

        logger.info(f"  ✅ AI-svar mottaget ({len(ai_section)} tecken)")
    except Exception as e:
        logger.error(f"  ❌ AI-anrop misslyckades: {e}")
        ai_section = f"⚠️ AI-analys kunde inte genereras: {e}"

    # Lägg AI-sektionen i rapporten (ersätt placeholder)
    report_text = "\n".join(report_lines)
    report_text = report_text.replace("*Genereras nedan...*\n", "")
    report_text += f"\n\n{ai_section}\n"

    # ═══════════════════════════════════════════════════════════════════════
    # 4. SPARA RAPPORT
    # ═══════════════════════════════════════════════════════════════════════

    prefix = {"morning": "morning", "evening": "evening", "weekly": "weekly", "smallcap": "smallcap"}
    report_file = REPORT_DIR / f"{prefix.get(mode, mode)}_{date_str}.md"
    report_file.write_text(report_text, encoding="utf-8")
    logger.info(f"  💾 Rapport sparad: {report_file}")

    # ═══════════════════════════════════════════════════════════════════════
    # 5. SKICKA MAIL
    # ═══════════════════════════════════════════════════════════════════════

    subject_map = {
        "morning": f"🌅 MarketScan Morgonbrief – {date_str}",
        "evening": f"🌆 MarketScan Kvällsbrev – {date_str}",
        "weekly": f"📊 MarketScan Veckorapport – v.{datetime.now().isocalendar()[1]}",
        "smallcap": f"🏦 MarketScan Småbolag – {date_str}",
    }
    subscription_type_map = {
        "morning":  "morning_report",
        "evening":  "evening_report",
        "weekly":   "weekly_summary",
        "smallcap": "smallcap_report",
    }
    subject = subject_map.get(mode, f"MarketScan Rapport – {date_str}")
    sub_type = subscription_type_map.get(mode, "morning_report")

    try:
        email_sent = send_email(
            subject=subject,
            body_markdown=report_text,
            from_name="MarketScan",
            subscription_type=sub_type,
        )
        if email_sent:
            logger.info(f"  ✉ Mail skickat: {subject}")
        else:
            logger.warning("  ⚠ Mail kunde inte skickas (kontrollera EMAIL-inställningar)")
    except Exception as e:
        logger.error(f"  ❌ Mail-fel: {e}")

    # ═══════════════════════════════════════════════════════════════════════
    # 6. KLART
    # ═══════════════════════════════════════════════════════════════════════

    elapsed = time.time() - start_time
    logger.info(f"\n{'='*50}")
    logger.info(f"✅ Pipeline klar! ({elapsed:.0f}s)")
    logger.info(f"{'='*50}\n")

    return {
        "mode": mode,
        "date": date_str,
        "report_file": str(report_file),
        "email_sent": email_sent if 'email_sent' in locals() else False,
        "elapsed_seconds": elapsed,
    }


def _get_rec(h: dict) -> str:
    """Rekommendation baserat på score och entry-signal."""
    score = h.get("score") or 0
    entry = h.get("entry", "—")
    pnl = h.get("pnl_pct") or 0

    if score >= 75 and entry == "STARK":
        return "KÖP MER 🟢"
    elif score >= 65 and entry in ("STARK", "OK"):
        return "BEHÅLL 🟢"
    elif score >= 50:
        return "BEVAKA 🟡"
    elif score >= 35:
        return "ÖVERVÄG MINSKA 🟠"
    else:
        return "SÄLJ/MINSKA 🔴"


# ══════════════════════════════════════════════════════════════════════════════
# CLI-ENTRY
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "morning"
    if mode not in ("morning", "evening", "weekly", "smallcap"):
        print(f"Användning: python -m core.daily_pipeline [morning|evening|weekly|smallcap]")
        sys.exit(1)
    run_pipeline(mode=mode)