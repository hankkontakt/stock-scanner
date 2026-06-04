"""
daily_pipeline.py - Central scanner- & rapport-pipeline
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
from core.email_template import send_email, build_section_header
from core.data_fetcher import fetch_prices_only, update_scored_with_prices, fetch_universe_data
from core.scoring import score_universe
from core import ai_analysis
from core.country_flags import flag_for_ticker

# ── Sökvägar ─────────────────────────────────────────────────────────────────
DATA_DIR = ROOT / "data"
REPORT_DIR = ROOT / "reports"
AI_CACHE_DIR = ROOT / "data" / "ai_cache"
REPORT_DIR.mkdir(parents=True, exist_ok=True)
AI_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# ── Logger ───────────────────────────────────────────────────────────────────
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(message)s")


# ══════════════════════════════════════════════════════════════════════════════
# A1-SPLIT STATUS: Delvis genomförd
# Extraherade moduler (ny kod bör importera direkt från dessa):
#   - core.pipeline_helpers     — data-I/O, _save_scored, _load_portfolio etc.
#   - core.pipeline_performance — _timed_stage, get_performance_summary etc.
#   - core.pipeline_report      — rapport-byggare, AI-kontext (redan existerande)
#   - core.pipeline_alerts      — alert-sändning (redan existerande)
# Funktionerna nedan är kvar för backward compatibility.
# TODO(A1): Ta bort duplikaten och låt alla anropare importera från modulerna.
# ══════════════════════════════════════════════════════════════════════════════

# ── DATALADDNING ──────────────────────────────────────────────────────────────

def _latest_report(pattern: str = "scored_universe_*.parquet") -> Optional[Path]:
    """Hitta senaste rapportfil som matchar mönstret.
    Prioriterar .parquet (snabbare), fallback till .csv."""
    # Första: leta efter .parquet
    files = sorted(REPORT_DIR.glob(pattern), reverse=True)
    if files:
        return files[0]
    # Andra: fallback till .csv (för bakåtkompatibilitet)
    csv_pattern = pattern.replace(".parquet", ".csv")
    if csv_pattern != pattern:
        csv_files = sorted(REPORT_DIR.glob(csv_pattern), reverse=True)
        if csv_files:
            logger.info(f"  ℹ Hittade .csv (ingen .parquet): {csv_files[0].name}")
            return csv_files[0]
    return None


def _load_latest_scored(pattern: str = "scored_universe_*.parquet") -> pd.DataFrame:
    """Ladda senaste scored_universe (parquet eller csv)."""
    path = _latest_report(pattern)
    if path and path.exists():
        if path.suffix == ".parquet":
            df = pd.read_parquet(path)
        else:
            df = pd.read_csv(path, low_memory=False)
        df.columns = df.columns.str.strip()
        logger.info(f"  📂 Laddade {path.name} ({len(df)} rader)")
        return df
    logger.warning("  ⚠ Ingen scored_universe-fil hittad - kör utan scandata")
    return pd.DataFrame()


def _load_all_recent_scored(max_age_days: int = 14,
                             pattern: str = "scored_universe_*.parquet") -> pd.DataFrame:
    """Ladda ALLA scored_universe-parquets från de senaste max_age_days dagarna.

    Returnerar en unifierad DataFrame där varje ticker representeras av sin
    SENASTE scoring. Detta ger en mycket bredare täckningsbas än att bara ladda
    den senaste filen — om ticker A rate-limiterades förra veckan men inte
    för 2 veckor sedan, finns den fortfarande med.

    Täckning: ~40% (en fil) → typiskt 70-90% (union av alla tillgängliga filer).
    """
    today = pd.Timestamp.today().normalize()
    cutoff = today - pd.Timedelta(days=max_age_days)

    # Hitta alla parquets (fallback: csv) inom max_age_days
    parquet_files = sorted(REPORT_DIR.glob(pattern), reverse=True)
    if not parquet_files:
        csv_pattern = pattern.replace(".parquet", ".csv")
        parquet_files = sorted(REPORT_DIR.glob(csv_pattern), reverse=True)

    frames_with_age: list[tuple[int, pd.DataFrame]] = []  # (age_days, df)
    for path in parquet_files:
        try:
            mtime = pd.Timestamp.fromtimestamp(path.stat().st_mtime).normalize()
            age_days = int((today - mtime).days)
            if age_days > max_age_days:
                continue
            if path.suffix == ".parquet":
                df = pd.read_parquet(path)
            else:
                df = pd.read_csv(path, low_memory=False)
            df.columns = df.columns.str.strip()
            if "ticker" not in df.columns:
                continue
            frames_with_age.append((age_days, df))
            logger.info(f"  📂 Multi-merge: {path.name} ({len(df)} rader, {age_days}d gammal)")
        except Exception as _e:
            logger.debug(f"  Kunde inte läsa {path.name}: {_e}")

    if not frames_with_age:
        logger.warning("  ⚠ Inga scored_universe-filer hittades för multi-merge")
        return pd.DataFrame()

    # Bygg union: nyast data vinner per ticker (frames är sorterade nyast→äldst)
    # Sätt data_fetched_date och data_stale_days baserat på filens ålder
    seen_tickers: set[str] = set()
    result_frames: list[pd.DataFrame] = []

    for age_days, df in frames_with_age:
        df = df.copy()
        # Markera staleness om filen inte är från idag
        if age_days > 0:
            if "data_fetched_date" not in df.columns:
                df["data_fetched_date"] = str((today - pd.Timedelta(days=age_days)).date())
            df["data_stale_days"] = (
                today - pd.to_datetime(df.get("data_fetched_date", str(today.date())),
                                       errors="coerce")
            ).dt.days.fillna(age_days).clip(lower=0).astype(int)
        else:
            df["data_stale_days"] = df.get("data_stale_days", pd.Series(0, index=df.index))

        # Lägg bara till tickers som inte redan finns (nyare fil vann)
        new_mask = ~df["ticker"].str.upper().isin(seen_tickers)
        new_rows = df[new_mask]
        if not new_rows.empty:
            seen_tickers.update(new_rows["ticker"].str.upper().tolist())
            result_frames.append(new_rows)

    if not result_frames:
        return pd.DataFrame()

    merged = pd.concat(result_frames, ignore_index=True)
    logger.info(
        f"  📦 Multi-parquet union: {len(merged)} unika tickers "
        f"från {len(frames_with_age)} filer "
        f"(senaste {max_age_days} dagar)"
    )
    return merged




def _save_scored(df: pd.DataFrame, path: Path):
    """Spara DataFrame som både .parquet (zstd) och .csv (för bakåtkompatibilitet).
    
    Använder atomisk skrivning: skriver först till .tmp, sedan rename.
    Detta förhindrar att en krasch mitt i skrivningen lämnar en korrupt fil
    som saboterar Streamlit-dashboarden.
    """
    csv_path = path.with_suffix(".csv")
    csv_tmp = csv_path.with_suffix(".tmp.csv")
    df.to_csv(csv_tmp, index=False)
    csv_tmp.replace(csv_path)  # Atomisk: tmp → rename
    
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
        parquet_path = path.with_suffix(".parquet")
        tmp_path = parquet_path.with_suffix(".tmp.parquet")
        table = pa.Table.from_pandas(df)
        pq.write_table(table, tmp_path, compression="zstd")
        tmp_path.replace(parquet_path)  # ← atomisk: antingen hela eller inget
        logger.info(f"  💾 Sparade {parquet_path.name} + {csv_path.name}")
    except ImportError:
        logger.warning("  ⚠ pyarrow saknas - sparar enbart .csv")
        logger.info(f"  💾 Sparade {csv_path.name}")


def _save_ai_text(mode: str, date_str: str, text: str):
    """Spara AI-genererad text i ai_cache/ för lazy-load."""
    path = AI_CACHE_DIR / f"ai_{mode}_{date_str}.md"
    path.write_text(text, encoding="utf-8")
    logger.info(f"  💾 Sparade AI-text: {path.name}")


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


def _fetch_live_price(ticker: str) -> float | None:
    """Fetch a single live price from yfinance for holdings not in the scored universe."""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        hist = t.history(period="2d", auto_adjust=True)
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception:
        pass
    return None


def _enrich_holdings(holdings: pd.DataFrame, scored: pd.DataFrame) -> list[dict]:
    """Berika portföljinnehav med scan-data. Holdings ej i universet får live-pris och beräknad RSI/trend."""
    score_lookup: dict = {}
    if not scored.empty and "ticker" in scored.columns:
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

    def _calc_tech_fallback(ticker_in: str) -> dict:
        """Hämta prisdata och beräkna RSI, trend vs MA50/MA200 för holdings utanför universet."""
        fallback = {}
        try:
            import yfinance as yf
            t = yf.Ticker(ticker_in)
            hist = t.history(period="6mo", auto_adjust=True)
            if hist.empty or len(hist) < 20:
                return fallback
            closes = hist["Close"]
            # RSI
            delta = closes.diff()
            gain = delta.where(delta > 0, 0.0)
            loss = (-delta.where(delta < 0, 0.0))
            avg_gain = gain.rolling(14).mean()
            avg_loss = loss.rolling(14).mean()
            rs = avg_gain / avg_loss.replace(0, float('inf'))
            rsi = 100 - (100 / (1 + rs))
            fallback["rsi"] = round(rsi.iloc[-1], 1) if not rsi.empty else None
            # Trend vs MA50/MA200
            ma50 = closes.rolling(50).mean().iloc[-1] if len(closes) >= 50 else None
            ma200 = closes.rolling(200).mean().iloc[-1] if len(closes) >= 200 else None
            current_price = closes.iloc[-1]
            if ma50:
                fallback["vs_ma50"] = round((current_price / ma50 - 1) * 100, 2)
            if ma200:
                fallback["vs_ma200"] = round((current_price / ma200 - 1) * 100, 2)
            # Trend signal
            if ma50 and ma200:
                if current_price > ma50 and current_price > ma200:
                    fallback["trend"] = "Upptrend"
                elif current_price < ma50 and current_price < ma200:
                    fallback["trend"] = "Nedtrend"
                else:
                    fallback["trend"] = "Blandad"
            # Entry (estimera baserat på RSI)
            rsi_val = fallback.get("rsi")
            if rsi_val is not None:
                if rsi_val < 30:
                    fallback["entry"] = "Översåld"
                elif rsi_val > 70:
                    fallback["entry"] = "Överköpt"
                else:
                    fallback["entry"] = "Neutral"
        except Exception:
            pass
        return fallback

    if holdings is None or (hasattr(holdings, "empty") and holdings.empty):
        return enriched

    for _, h in holdings.iterrows():
        t = str(h.get("ticker", "")).upper().strip()
        if not t:
            continue
        sc = _lookup(t)
        price = sc.get("current_price") or sc.get("close", 0)
        # If holding isn't in scored universe, fetch live price so P&L is still correct
        if not price:
            price = _fetch_live_price(t) or 0
        cost = h.get("cost_basis", 0)
        shares = h.get("shares", 0)

        try:
            mv = float(price) * float(shares) if price and shares > 0 else 0
        except (ValueError, TypeError):
            mv = 0

        pnl_pct = ((float(price) / float(cost)) - 1) * 100 if price and cost > 0 else None
        pnl_pct = round(pnl_pct, 1) if pnl_pct is not None else None

        stop_loss_pct = round(((float(cost) * 0.85) / float(cost) - 1) * 100, 1) if cost > 0 else None

        # Om holding saknas i scored_universe - beräkna tekniska indikatorer från prisdata
        tech = {}
        if not sc:
            tech = _calc_tech_fallback(t)

        enriched.append({
            "ticker": t,
            "name": sc.get("name", t) if sc else t,
            "sector": sc.get("sector", "--") if sc else "--",
            "shares": shares,
            "cost_basis": cost,
            "price": round(float(price), 2) if price else None,
            "market_value": round(mv, 0),
            "pnl_pct": pnl_pct,
            "stop_loss_pct": stop_loss_pct,
            "score": sc.get("score_total") if sc else None,
            "entry": (sc.get("entry_signal", "--") if sc else tech.get("entry", "--")) or "--",
            "trend": (sc.get("trend_signal", "--") if sc else tech.get("trend", "--")) or "--",
            "rsi": sc.get("rsi_14") if sc else tech.get("rsi"),
            "vs_ma50": sc.get("price_vs_ma50") if sc else tech.get("vs_ma50"),
            "vs_ma200": sc.get("price_vs_ma200") if sc else tech.get("vs_ma200"),
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
        on="ticker", how="left",  # left: behåll ALLA dagens tickers inkl. nya
    )
    if merged.empty:
        return {}
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

    # score_yesterday kan vara NaN för nya tickers (left join) — fillna för sortering
    if "score_yesterday" not in merged.columns:
        merged["score_yesterday"] = float("nan")

    base_cols = [c for c in ["ticker", "score_total", "score_yesterday", "score_delta", "price_delta_pct"]
                 if c in merged.columns]

    # RSI-spike-kolumner: välj bara de som faktiskt finns
    rsi_spike_rows = merged[merged["rsi_crossed_30up"] | merged["rsi_crossed_70down"]]
    rsi_cols = [c for c in ["ticker", "rsi_14", "rsi_yesterday", "rsi_crossed_30up", "rsi_crossed_70down"]
                if c in rsi_spike_rows.columns]

    return {
        "movers_up":   merged.nlargest(top_n, "score_delta")[base_cols].to_dict("records"),
        "movers_down": merged.nsmallest(top_n, "score_delta")[base_cols].to_dict("records"),
        "rsi_spikes":  rsi_spike_rows[rsi_cols].to_dict("records"),
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

    # Faktorkolumner som inkluderas för mail-attribution
    _FACTOR_COLS = [
        "score_value", "score_quality", "score_momentum", "score_growth",
        "score_risk", "score_dividend", "score_sentiment", "score_short_interest",
        "pe_trailing", "price_to_book", "roe", "profit_margin",
        "return_12m", "return_6m", "revenue_growth", "earnings_growth",
        "debt_to_equity", "volatility", "dividend_yield", "sentiment_raw",
    ]

    def _fmt(df):
        rows = []
        for _, r in df.iterrows():
            entry = {
                "ticker":    r.get("ticker", "?"),
                "score":     r.get("score_total"),
                "entry":     r.get("entry_signal", "--"),
                "sector":    r.get("sector", "--"),
                "return_1m": r.get("return_1m"),
            }
            # Inkludera faktordata för email-attribution
            for col in _FACTOR_COLS:
                if col in r.index:
                    entry[col] = r.get(col)
            rows.append(entry)
        return rows

    return _fmt(top), _fmt(bottom)


from core.pipeline_report import (
    _section, _table, _portfolio_table, _opportunity_section, _section_header,
    _build_ai_morning_context, _build_ai_evening_context,
    _build_ai_weekly_context, _build_ai_smallcap_context,
    format_factor_attribution_md,
)
from core.pipeline_alerts import _send_stark_alerts, _get_rec

# ══════════════════════════════════════════════════════════════════════════════
# PIPELINE PERFORMANCE TRACKING
# A1-split: Importeras från core.pipeline_performance (ny modul).
# Gamla anropare via daily_pipeline fortsätter att fungera (re-export).
# ══════════════════════════════════════════════════════════════════════════════

from core.pipeline_performance import (  # noqa: E402
    _timed_stage, _record_perf,
    get_performance_summary, get_slowest_stages, get_performance_trend,
    _PERF_LOCK, _PERF_HISTORY,
)

# Dessa importer och modulhänvisningar (ovan) ersätter de inliner-definitionerna.
# Behåll threading/collections-import som backup för kod som refererar direkt.
import threading
from collections import defaultdict, deque
from contextlib import contextmanager

# ══════════════════════════════════════════════════════════════════════════════
# AI-PROMPTS
# ══════════════════════════════════════════════════════════════════════════════

MORNING_AI_SYSTEM_PROMPT = """Du är en personlig portföljrådgivare. Skapa en morgonbrief baserad på datan nedan.

TÄNK PÅ:
- Skriv på svenska, personligt och engagerande
- Använd emojis för att markera riktning (🟢🔴🟡)
- Var konkret med rekommendationer
- Fokusera på vad som är VIKTIGT för mottagaren just idag
- **Nyheter finns bifogade - väg in dem i din analys**, särskilt för portfölj och bevakningar

STRUKTUR (800-1000 ord):
1. 🌏 **Global överblick** - Vad hände i natt? USA-stängning, Asien-öppning, Europa-öppning. VIX-nivå.
2. 💼 **Din portfölj** - Gå igenom varje innehav. Är någon nära stop-loss? Någon som sticker ut?
3. ⭐ **Dina bevakningar** - Har någon rört sig mycket? Något nytt att titta på? Kolla nyheter om dem!
4. 🏆 **Dagens hetaste** - Topp-5 just nu. Varför?
5. ⚠️ **Varningar** - Stop-loss som triggas idag, oroliga signaler
6. 📰 **Nyheter som påverkar dig** - Kort om vad som händer
7. 🎯 **Dagens fokus** - 1-2 konkreta saker att göra/hålla koll på

Avsluta med dagens humör: t.ex. "📈 Optimistisk - mycket i rörelse" eller "📉 Försiktig - oroliga signaler"
"""

EVENING_AI_SYSTEM_PROMPT = """Du är en personlig portföljrådgivare. Skapa en kvällsrapport baserad på datan nedan.

TÄNK PÅ:
- Skriv på svenska, personligt och engagerande
- Använd emojis för att markera riktning (🟢🔴🟡)
- Var konkret med rekommendationer
- Analysera dagen och blicka framåt
- **Nyheter finns bifogade - väg in dem**, särskilt om de påverkar portfölj eller bevakningar

STRUKTUR (800-1000 ord):
1. 📊 **Dagens utveckling** - Hur gick börserna idag? (Sverige, Europa, USA öppen)
2. 💼 **Portfölj-P&L** - Hur mycket tjänade/förlorade du idag? Gå igenom varje innehav
3. ⭐ **Bevakningar som rört sig** - Någon som stack ut idag? Har de nyheter?
4. 🏆 **Dagens topp-5 & botten-5** - Bästa och sämsta aktierna
5. 🔮 **Imorgon** - Makro-siffror, earnings, opportunities som uppstått
6. 🎯 **Handlingsplan** - Vad göra imorgon bitti? Köp, sälj, avvakta?

Avsluta med: "Imorgon tittar jag extra på [aktie] - för att [anledning]"
"""

WEEKLY_AI_SYSTEM_PROMPT = """Du är en senior portföljförvaltare. Skapa en DIUP veckoanalys baserad på datan nedan.

TÄNK PÅ:
- Skriv på svenska, analytiskt och insiktsfullt
- Använd emojis sparsamt (🟢🔴 för riktning)
- Detta är en DJUP analys - inte en snabb överblick
- Var modig med rekommendationer
- **Nyheter finns bifogade för portfölj, bevakningar och topplaceringar - väg in dem**

STRUKTUR (1500-2000 ord):
1. 📈 **Marknadsregim & bredd** - Veckans utveckling, VIX, bredd, sektorer
2. 🌏 **Globalt** - USA, Europa, Asien - trender och makro
3. 💼 **Djup portföljanalys** - Varje innehav med trend, rekommendation, stop-loss. Kolla nyheter om dem!
4. ⭐ **Bevakningslistan** - Bör du lägga till/ta bort något? AI-bedömning. Finns nyheter?
5. 🏆 **Topp-10 köprekommendationer** - Med motivering per aktie + nyheter
6. 🔴 **Bottom-5 varningar** - Aktier att minska/undvika
7. 🏭 **Sektormomentum** - Vilka sektorer leder/släpar
8. 📰 **Nyheter & makro** - Viktigaste händelserna
9. 🎯 **Kommande vecka** - Earnings, makro, opportunities
10. ✅ **Rekommendation** - Om du bara gör EN sak denna vecka...
"""

SMALLCAP_AI_SYSTEM_PROMPT = """Du är en småbolagsspecialist. Skapa en analys av småbolagsuniverse baserat på datan nedan.

TÄNK PÅ:
- Skriv på svenska, konkret och handlingsorienterat
- Fokusera på specifika aktier och köpsignaler
- Småbolag har högre risk - påpeka stop-loss-nivåer
- Lyft fram det som sticker ut (positivt och negativt)

STRUKTUR (600-900 ord):
1. 📊 **Småbolagsöversikt** - Hur ser småbolagsmarknaden ut just nu?
2. 💼 **Din portfölj** - Gå igenom innehaven med rekommendationer
3. 🏆 **Topp-5 köpkandidater** - Starka signaler med motivering
4. ⚠️ **Varningar** - Aktier med svaga signaler eller nära stop-loss
5. 🎯 **Rekommendation** - 1-2 konkreta åtgärder just nu

Avsluta med en kortsiktig utsikt för småbolag: "Läge: KÖPA / AVVAKTA / MINSKA"
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


def _looks_like_ticker(ticker: str) -> bool:
    """
    True om strängen ser ut som en giltig börsticker.

    Filtrerar bort fondnamn och andra icke-tickers som annars
    läggs till i custom_universe och misslyckas i varje scan
    (t.ex. "LÄNSFÖRSÄKRINGAR GLOBAL INDEX" — en fond utan ticker).

    Regler:
      - Inte tom
      - Inga mellanslag (tickers har aldrig mellanslag)
      - Max 15 tecken (längsta riktiga tickers är ~12, t.ex. TLEVISACPO.MX)
    """
    if not ticker:
        return False
    t = str(ticker).strip()
    if not t or " " in t or len(t) > 15:
        return False
    return True


def _pre_scan_sync_universe():
    """
    Synkar portföljinnehav och bevakningslista till custom_universe.json
    INNAN veckoscannen startar.

    Säkerställer att aktier som lagts till via webbgränssnittet sedan
    förra scannen inkluderas i DENNA scan -- inte bara i nästa.
    """
    holdings  = _load_portfolio()
    watchlist_raw = _load_watchlist()
    watchlist_tickers = [i.get("ticker", "") for i in watchlist_raw if i.get("ticker")]

    existing  = set(c["ticker"] for c in config.load_custom_universe())
    universe_set = set(getattr(config, "UNIVERSE", []))
    added = 0

    all_candidates = []
    if not holdings.empty and "ticker" in holdings.columns:
        all_candidates += [str(h).upper().strip() for h in holdings["ticker"].tolist()]
    all_candidates += [w.upper().strip() for w in watchlist_tickers]

    for ticker in all_candidates:
        if not ticker:
            continue
        if not _looks_like_ticker(ticker):
            logger.info(f"  ⏭ Hoppar över icke-ticker (t.ex. fondnamn): {ticker!r}")
            continue
        if ticker in universe_set or ticker in existing:
            continue
        # Kolla om variant med suffix redan finns
        if any(ticker + sfx in universe_set or ticker + sfx in existing
               for sfx in (".ST", ".HE", ".CO", ".OL", ".L", ".DE")):
            continue
        config.add_custom_to_universe(ticker, "")
        existing.add(ticker)  # uppdatera lokal set för deduplicering
        added += 1

    if added:
        logger.info(f"  ➕ Pre-scan sync: {added} nya tickers tillagda i custom_universe")
    else:
        logger.info("  ✓ Pre-scan sync: inga nya tickers att lägga till")


def run_targeted(tickers: list[str]) -> int:
    """
    Hämtar färsk data för en specifik lista aktier, uppdaterar den senaste
    scored_universe-filen och sparar tillbaka.

    Används för att direkt sätta poäng på aktier som:
    - Precis lagts till i bevakningslista / portfölj
    - Visar None/NaN i alla datapunkter i latest scored CSV

    Flöde:
        1. Ladda senaste scored_universe som base
        2. Hämta fresh data för target-tickers (force_refresh=True -> bypassa cache)
        3. Ersätt/lägg till target-rader i base-df
        4. Re-scora hela df:n (region-neutral) för korrekta percentilranker
        5. Spara uppdaterad scored_universe med dagens datum

    Returns:
        Antal tickers som lyckades.
    """
    if not tickers:
        logger.warning("run_targeted: tom ticker-lista")
        return 0

    tickers = [t.strip().upper() for t in tickers if t.strip()]
    logger.info(f"\n{'='*50}")
    logger.info(f"🎯 Targeted refresh - {len(tickers)} tickers: {', '.join(tickers)}")
    logger.info(f"{'='*50}\n")

    date_str = date.today().strftime("%Y-%m-%d")

    # ── Steg 1: Ladda befintlig scored universe som base ──────────────────────
    base_df = _load_latest_scored("scored_universe_*.parquet")
    if base_df.empty:
        base_df = _load_latest_scored("scored_universe_*.csv")
    logger.info(f"  📂 Base scored universe: {len(base_df)} rader")

    # ── Steg 2: Hämta fresh data för target-tickers ──────────────────────────
    # fetch_universe_data hämtar fundamentals + prishistorik.
    # Vi rensar cachen för dessa tickers manuellt så yfinance-data är färsk.
    try:
        from core.data_fetcher import fetch_universe_data, _CACHE_DIR as _DC
        import glob

        # Rensa alla cachade filer för dessa tickers
        cleared = 0
        for ticker in tickers:
            safe = ticker.replace("/", "_").replace(".", "_")
            for pattern in [f"{safe}_*", f"*{safe}*"]:
                for f in glob.glob(str(Path(_DC) / pattern)):
                    try:
                        Path(f).unlink()
                        cleared += 1
                    except Exception:
                        pass
        if cleared:
            logger.info(f"  🧹 Rensade {cleared} cachefiler för {len(tickers)} tickers")

        raw_new = fetch_universe_data(tickers, verbose=True)
    except Exception as e:
        logger.error(f"  ❌ fetch_universe_data misslyckades: {e}")
        return 0

    if raw_new.empty:
        logger.warning(f"  ⚠ Ingen data hämtades för {tickers} - avbryter")
        return 0

    succeeded = len(raw_new)
    logger.info(f"  ✅ Hämtade data för {succeeded}/{len(tickers)} tickers")

    # ── Steg 3: Slå ihop med base ─────────────────────────────────────────────
    if base_df.empty or "ticker" not in base_df.columns:
        merged_raw = raw_new
    else:
        # Ta bort gamla rader för dessa tickers, ersätt med nya
        kept = base_df[~base_df["ticker"].isin(raw_new["ticker"].str.upper())]
        # Justera raw_new kolumner till base_df:s kolumnuppsättning (undvik missmatch)
        common_cols = [c for c in base_df.columns if c in raw_new.columns or c.startswith("score_")]
        # raw_new saknar score-kolumner ännu -- det ger NaN, vilket vi fyller i steg 4
        merged_raw = pd.concat([kept, raw_new], ignore_index=True)

    # ── Steg 4: Re-scora hela df:n ────────────────────────────────────────────
    # Percentilrankning kräver hela universum -- vi kan inte scora bara target-rader.
    try:
        from core.scoring import score_universe
        from core.macro_regime import detect_regime

        try:
            regime = detect_regime().get("regime", "OSÄKER")
        except Exception:
            regime = "OSÄKER"

        scored = score_universe(merged_raw, regime=regime)
        logger.info(f"  ✅ Re-scorat {len(scored)} tickers (regime={regime})")
    except Exception as e:
        logger.error(f"  ❌ score_universe misslyckades: {e}")
        return 0

    # Piotroski (snabb, använder cachad data)
    try:
        from core import piotroski as _pio
        scored = _pio.add_piotroski_to_universe(scored, verbose=False)
    except Exception as e:
        logger.warning(f"  ⚠ Piotroski hoppades över: {e}")

    # Entry/trend-signaler
    try:
        from core import filters as _filters
        scored = _filters.apply_all_filters(scored, verbose=False)
    except Exception as e:
        logger.warning(f"  ⚠ apply_all_filters hoppades över: {e}")

    # ML-prediktion (om modell finns)
    try:
        from core.ml_predictor import predict_returns_sector
        scored = predict_returns_sector(scored, default_universe="universe")
    except Exception as e:
        logger.warning(f"  ⚠ ML-prediktion hoppades över: {e}")

    # ── Steg 5: Spara ────────────────────────────────────────────────────────
    csv_path = REPORT_DIR / f"scored_universe_{date_str}"
    _save_scored(scored, csv_path)
    logger.info(f"  💾 Sparad: scored_universe_{date_str}.parquet/.csv")

    # Logga hur det gick för de specifika target-tickers
    if "ticker" in scored.columns and "score_total" in scored.columns:
        target_rows = scored[scored["ticker"].isin(tickers)]
        for _, row in target_rows.iterrows():
            score = row.get("score_total", "?")
            entry = row.get("entry_signal", "--")
            logger.info(f"  ✓ {row['ticker']}: score={score:.1f}, entry={entry}")

    logger.info(f"\n✅ Targeted refresh klar -- {succeeded} ticker(s) uppdaterade\n")


def run_portfolio_refresh(verbose: bool = True) -> dict:
    """
    Lattvikts-prisrefresh av holdings.csv. Inget scoring, inget universum.
    Hamtar live-priser for alla tickers i portfoljen och uppdaterar market_value.
    Hanterar fonder (ISIN-baserade, ingen ticker) genom att hoppa over dem.
    """
    result = {"n_holdings": 0, "n_updated": 0, "n_skipped": 0}
    holdings = _load_portfolio()
    if holdings.empty:
        logger.info("  ℹ Ingen portfölj att refresh:a")
        return result

    # Filtrera bort rader utan ticker (t.ex. ISIN-baserade fonder)
    # Hoppar även över "tickers" som är fondnamn (innehåller mellanslag, >15 tecken)
    def _is_valid_ticker(t) -> bool:
        if not t or not isinstance(t, str):
            return False
        t = t.strip()
        if not t or t == "":
            return False
        if " " in t:          # fondnamn, t.ex. "LÄNSFÖRSÄKRINGAR GLOBAL INDEX"
            return False
        if len(t) > 20:       # rimlig max-längd för en ticker (t.ex. "BRK-B.ST" = 8 tecken)
            return False
        return True

    valid = holdings[holdings["ticker"].apply(_is_valid_ticker)]
    result["n_holdings"] = len(holdings)
    skipped_no_ticker = len(holdings) - len(valid)
    if skipped_no_ticker:
        skipped_names = holdings.loc[~holdings["ticker"].apply(_is_valid_ticker), "ticker"].tolist()
        logger.info(f"  ℹ Hoppar över {skipped_no_ticker} icke-ticker-rader: {skipped_names[:5]}")
    result["n_skipped"] = skipped_no_ticker

    if valid.empty:
        logger.info("  ℹ Inga ticker-baserade innehav att uppdatera")
        return result

    tickers = valid["ticker"].unique().tolist()
    if verbose:
        logger.info(f"  📡 Hamtar priser for {len(tickers)} tickers...")

    try:
        from core.data_fetcher import fetch_prices_only
        prices = fetch_prices_only(tickers, period="1mo", max_workers=8)
    except Exception as e:
        logger.error(f"  ❌ fetch_prices_only misslyckades: {e}")
        return result

    if not prices:
        logger.warning("  ⚠ Inga priser kunde hamtas")
        return result

    # fetch_prices_only returnerar dict: {ticker: {"current_price": float, ...}}
    # Bygg price_lookup med uppercase-nycklar
    price_lookup = {}
    for ticker in tickers:
        data = prices.get(ticker) or prices.get(ticker.upper())
        if data and isinstance(data, dict):
            cp = data.get("current_price")
            if cp is not None and cp > 0:
                price_lookup[ticker.upper()] = float(cp)

    updated = 0
    for idx, row in holdings.iterrows():
        t = str(row.get("ticker", "")).upper().strip()
        if not t or t not in price_lookup:
            continue
        shares = row.get("shares", 0)
        try:
            shares = float(shares)
        except (ValueError, TypeError):
            continue
        if shares <= 0:
            continue
        price = price_lookup[t]
        holdings.at[idx, "market_value"] = round(price * shares, 2)
        holdings.at[idx, "current_price"] = price
        updated += 1

    result["n_updated"] = updated
    if updated == 0:
        logger.warning("  ⚠ Inga priser kunde matchas")
        return result

    # Spara — atomisk skrivning: tmp → replace förhindrar korrupt fil vid avbrott
    try:
        _h_path = DATA_DIR / "holdings.csv"
        _h_tmp  = _h_path.with_suffix(".tmp.csv")
        holdings.to_csv(_h_tmp, index=False)
        _h_tmp.replace(_h_path)  # Atomisk rename
        if verbose:
            logger.info(f"  ✅ holdings.csv uppdaterad -- {updated} innehav med nya priser")
    except Exception as e:
        logger.error(f"  ❌ Kunde inte spara holdings.csv: {e}")

    return result

def _find_missing_data_tickers(max_tickers: int = 50) -> list[str]:
    """
    Hittar tickers i senaste scored_universe som saknar meningsfull data.

    Kriterier för "saknar data":
    - score_total är NaN ELLER
    - current_price / close saknas ELLER är 0 ELLER
    - Alla dessa saknas: pe_trailing, roe, revenue_growth, return_12m

    Returnerar max max_tickers tickers, prioriterade på att de finns i
    portfolio/watchlist (dessa är viktigast för användaren).
    """
    df = _load_latest_scored("scored_universe_*.parquet")
    if df.empty or "ticker" not in df.columns:
        return []

    # Fastställ "data saknas"-mask
    has_score = df.get("score_total", pd.Series()).notna()

    price_col = next((c for c in ("current_price", "close") if c in df.columns), None)
    if price_col:
        has_price = df[price_col].notna() & (df[price_col] > 0)
    else:
        has_price = pd.Series(False, index=df.index)

    key_fundamental_cols = [c for c in ("pe_trailing", "roe", "revenue_growth", "return_12m")
                             if c in df.columns]
    if key_fundamental_cols:
        has_fundamentals = df[key_fundamental_cols].notna().any(axis=1)
    else:
        has_fundamentals = pd.Series(False, index=df.index)

    missing_mask = (~has_score) | (~has_price) | (~has_fundamentals)
    missing_tickers = df.loc[missing_mask, "ticker"].dropna().unique().tolist()

    if not missing_tickers:
        logger.info("  ✓ Inga tickers med saknad data hittades")
        return []

    # Prioritera tickers i portfölj/watchlist
    holdings = _load_portfolio()
    wl_raw = _load_watchlist()
    priority = set()
    if not holdings.empty and "ticker" in holdings.columns:
        priority.update(holdings["ticker"].str.upper().tolist())
    priority.update(i.get("ticker", "").upper() for i in wl_raw if i.get("ticker"))

    prioritized = [t for t in missing_tickers if t in priority]
    rest = [t for t in missing_tickers if t not in priority]
    ordered = prioritized + rest

    result = ordered[:max_tickers]
    logger.info(f"  🔍 Hittade {len(missing_tickers)} tickers med saknad data"
                f" (prioriterade: {len(prioritized)}, totalt att köra: {len(result)})")
    return result


def run_refresh_missing(max_tickers: int = 50) -> int:
    """
    Hitta aktier med saknad data i senaste scored_universe och kör
    en targeted refresh på dem.

    Körs 1-2 gånger per dag via GitHub Actions (schema: 08:00 + 16:00 CET).
    Typiska kandidater:
    - Nyligen tillagda bevakningar/portföljinnehav vars data ännu ej hämtats
    - Tickers som misslyckades i senaste veckoscan p.g.a. API-timeout/rate-limit
    - Avnoterade tickers (dessa ger tom data och bör kännas igen)

    Returns:
        Antal tickers som uppdaterades.
    """
    logger.info(f"\n{'='*50}")
    logger.info("🔄 Refresh missing data - letar efter tickers med saknad data...")
    logger.info(f"{'='*50}\n")

    tickers = _find_missing_data_tickers(max_tickers=max_tickers)
    if not tickers:
        logger.info("✅ Inget att uppdatera.")
        return 0

    logger.info(f"  📋 Kör targeted refresh för {len(tickers)} tickers: "
                f"{', '.join(tickers[:10])}{'...' if len(tickers) > 10 else ''}")
    return run_targeted(tickers)


def run_pipeline(mode: str = "morning", force_refresh: bool = False):
    """
    Kör dagliga pipeline: hämta data, skapa rapport, skicka mail.

    Args:
        mode: "morning" | "evening" | "weekly" | "smallcap"
              | "targeted"      (TARGET_TICKERS-env sätts av workflow)
              | "refresh_missing" (letar upp + refreshar saknad data)
        force_refresh: Hoppa över cache, tvinga ny data
    """
    # ── Initiera PipelineLogger och MetricsCollector ──────────────────────
    from core.logger import PipelineLogger, rotate_old_logs
    pl = PipelineLogger(mode=mode, verbose=True)
    try:
        from core.monitoring.metrics import MetricsCollector
        metrics = MetricsCollector()
        metrics.pipeline_start(mode)
    except Exception:
        metrics = None

    # Log rotation (en gång per körning)
    try:
        rotate_old_logs(max_days=30)
    except Exception:
        pass

    start_time = time.time()
    date_str = date.today().strftime("%Y-%m-%d")
    day_name = datetime.now().strftime("%A")

    # Städa gamla rapporter (en gång per körning är OK - snabbt)
    _cleanup_old_reports(max_days=60)

    logger.info(f"\n{'='*50}")
    logger.info(f"🚀 MarketScan Pipeline - mode={mode} - {date_str}")
    logger.info(f"{'='*50}\n")

    pipeline_success = False

    try:
        # ── Snabblägen som inte behöver hela pipeline-flödet ───────────────
        if mode == "targeted":
            tickers_env = os.environ.get("TARGET_TICKERS", "")
            tickers_list = [t.strip().upper() for t in tickers_env.split(",") if t.strip()]
            if not tickers_list:
                logger.warning("  ⚠ TARGET_TICKERS env var är tom - avbryter targeted-körning")
                pipeline_success = True
                return
            logger.info(f"  🎯 Targeted refresh: {', '.join(tickers_list)}")
            run_targeted(tickers_list)
            pipeline_success = True
            return

        if mode == "refresh_missing":
            run_refresh_missing()
            pipeline_success = True
            return

        if mode == "retry_rate_limited":
            result = run_retry_rate_limited(
                max_passes=int(os.environ.get("RETRY_MAX_PASSES", "5")),
                pass_delay_s=int(os.environ.get("RETRY_PASS_DELAY_S", "120")),
            )
            logger.info(
                f"  ♻️ Retry klar: {result['n_succeeded']} lyckades, "
                f"{result['n_still_pending']} kvar, {result['n_skipped']} delistade"
            )
            pipeline_success = True
            return

        if mode == "portfolio_refresh":
            run_portfolio_refresh()
            pipeline_success = True
            return

        # ═══════════════════════════════════════════════════════════════════════
        # 1. LADDA DATA
        # ═══════════════════════════════════════════════════════════════════════

        # Globala index (ALLTID)
        with _timed_stage("fetch_global_indices", plogger=pl):
            logger.info("📡 Hämtar globala index...")
            indices = fetch_global_indices()
            narrative = get_global_market_narrative(indices)
            short_summary = format_index_summary_short(indices)
            vix = indices.get("^VIX", {}).get("close") if indices else None
            logger.info(f"  {short_summary}")

        # Scored universe
        if mode in ("morning", "evening"):
            scored = _load_latest_scored("scored_universe_*.parquet")
            if scored.empty:
                scored = _load_latest_scored("scored_universe_*.csv")
            _ml_universe = "universe"
        elif mode == "weekly":
            # ── Full universe scan ────────────────────────────────────────────
            # Hämtar data för ALLA tickers i UNIVERSE + custom-lista,
            # scorer dem och sparar ny scored_universe_*.csv.
            # Körs ~2-3 min med 8 workers + 30-dagars fundamentalcache.
            logger.info("🔄 Full universe scan - hämtar data för alla tickers...")
            from core.macro_regime import detect_regime

            # ── Synka portfolio & bevakningslista till custom_universe FÖR SCAN ──
            # Viktigt att detta sker INNAN all_tickers byggs, annars saknas
            # nyligen tillagda tickers i denna scan (de hade annars dykt upp
            # först i nästa veckas scan).
            _pre_scan_sync_universe()

            custom_tickers = [c["ticker"] for c in config.load_custom_universe()]
            all_tickers = list(dict.fromkeys(config.UNIVERSE + custom_tickers))
            logger.info(f"  📋 Universe: {len(all_tickers)} tickers")

            raw_df = fetch_universe_data(all_tickers, verbose=True)

            # Auto-flagga misslyckade tickers (strike-system), men bara for
            # GENUINA fetch-fel (t.ex. 404/delisted), INTE for rate-limited (429)
            # dar felet sitter hos yfinance, inte aktien.
            # Vi laser fetch_errors.json for att fa ratt status per ticker.
            try:
                from core.filters import update_ticker_health
                survived = set(raw_df["ticker"].tolist()) if not raw_df.empty and "ticker" in raw_df.columns else set()
                all_failed = [t for t in all_tickers if t not in survived]

                # Las fetch_errors.json for att fa ratt status per ticker
                _fe_path = DATA_DIR / "fetch_errors.json"
                fetch_failed = list(all_failed)

                if os.path.exists(_fe_path):
                    try:
                        _fe_data = json.loads(open(_fe_path, encoding="utf-8").read())
                        if _fe_data:
                            latest = _fe_data[-1]
                            rate_limited_set = set(latest.get("rate_limited_tickers", []))
                            genuine_fails = []
                            for t in all_failed:
                                if t in rate_limited_set:
                                    continue
                                status = "FAILED"
                                for fd in latest.get("failed_tickers", []):
                                    if fd.get("ticker") == t:
                                        status = fd.get("status", "FAILED")
                                        break
                                if status not in ("RATE_LIMITED", "TIMEOUT", "SKIPPED"):
                                    genuine_fails.append(t)
                            if genuine_fails:
                                fetch_failed = genuine_fails
                                logger.info(f"  {len(genuine_fails)} genuina fetch-fel (exkl rate-limited)")
                    except Exception:
                        pass

                if fetch_failed:
                    _warnings, _removed = update_ticker_health(
                        attempted_tickers=all_tickers,
                        survived_tickers=list(survived),
                        df_raw=raw_df,
                        fetch_failed=fetch_failed,
                    )
                    if _removed:
                        logger.info(f"  🚫 Auto-blacklistad: {[r['ticker'] for r in _removed[:5]]}")
            except Exception as _the:
                logger.warning(f"  ⚠️ ticker-health update hoppades över: {_the}")

            # ── Ladda ALLA senaste scored_universe-parquets för staleness-merge ─────
            # Sparas undan INNAN ny parquet skrivs; används efter scoring för att
            # bevara tickers som rate-limiterades denna körning (täckningsgap-fix).
            # Använder _load_all_recent_scored() (union av alla parquets ≤14 dagar)
            # istf. bara senaste, vilket ger mycket bättre täckning redan från dag 1.
            prev_scored_for_merge = _load_all_recent_scored(max_age_days=14)
            if not prev_scored_for_merge.empty:
                logger.info(f"  📂 Staleness-bas: {len(prev_scored_for_merge)} unika tickers (alla parquets ≤14 dagar)")

            if not raw_df.empty:
                # Detektera marknadsregim for dynamiska vikter
                # Detektera marknadsregim för dynamiska vikter
                try:
                    regime_info = detect_regime()
                    regime = regime_info.get("regime", "OSAKER")
                    logger.info(f"  Marknadsregim: {regime}")
                except Exception as _re:
                    regime = "OSAKER"
                    logger.warning(f"  Regime-detektion misslyckades: {_re} - kor OSKER")

                # Anvnd sektor-neutraliserad scoring
            # där tech-bolag systematiskt överrankas och värdebolag underrankas.
            # Varje faktor score beräknas INOM sektor (t.ex. P/E för tech vs fastighet).
            use_sector_neutral = getattr(config, "SCORE_MODE", "") == "sector_neutral"
            if use_sector_neutral:
                try:
                    from core.scoring import score_universe_sector_neutralized
                    scored = score_universe_sector_neutralized(raw_df, regime=regime)
                    logger.info(f"  ✅ Scorat {len(scored)} tickers (sektorneutralt, regim={regime})")
                except Exception as _sne:
                    logger.warning(f"  ⚠ Sektorneutral scoring misslyckades: {_sne} - fallback till absolut")
                    scored = score_universe(raw_df, regime=regime)
            else:
                scored = score_universe(raw_df, regime=regime)
                logger.info(f"  ✅ Scorat {len(scored)} tickers")

            # Piotroski F-Score (fundamental quality 0-9)
            try:
                from core import piotroski as _piotroski
                scored = _piotroski.add_piotroski_to_universe(scored, verbose=True)
                logger.info("  ✅ Piotroski beräknat")
            except Exception as _pe:
                logger.warning(f"  ⚠ Piotroski misslyckades: {_pe}")

            # Entry-signal, trend-signal, confidence-label
            try:
                from core import filters as _filters
                scored = _filters.apply_all_filters(scored, verbose=True)
                logger.info(f"  ✅ Filter/signaler applicerade: {len(scored)} tickers")
            except Exception as _fe:
                logger.warning(f"  ⚠ apply_all_filters misslyckades: {_fe}")

            # ── Score-delta: hur mycket har score förändrats sedan förra veckan? ──────
            # Körs INNAN staleness-merge så delta gäller nyligen hämtad data.
            try:
                if not prev_scored_for_merge.empty and "score_total" in prev_scored_for_merge.columns and not scored.empty:
                    _prev_map = (
                        prev_scored_for_merge
                        .assign(_tu=prev_scored_for_merge["ticker"].str.upper())
                        .set_index("_tu")["score_total"]
                        .to_dict()
                    )
                    scored["score_prev"] = scored["ticker"].str.upper().map(_prev_map)
                    scored["score_delta_4w"] = (scored["score_total"] - scored["score_prev"]).round(1)
                    scored.drop(columns=["score_prev"], inplace=True, errors="ignore")
                    n_improved = (scored["score_delta_4w"].fillna(0) >= 5).sum()
                    n_declined = (scored["score_delta_4w"].fillna(0) <= -5).sum()
                    logger.info(f"  📊 Score-delta: {n_improved} förbättrade (≥+5), {n_declined} försämrade (≤-5)")
                elif "score_delta_4w" not in scored.columns:
                    scored["score_delta_4w"] = float("nan")
            except Exception as _de:
                logger.warning(f"  ⚠ Score-delta hoppades över: {_de}")
                if "score_delta_4w" not in scored.columns:
                    scored["score_delta_4w"] = float("nan")

            # ── Staleness-merge: bevara föregående scorade aktier som rate-limiterades ─
            # Fixar täckningsgapet: ~40% → ~90%+ av universe representeras i parqueten.
            # Stale-rader markeras med data_stale_days > 0 och visas med ⏱ i UI.
            try:
                if not prev_scored_for_merge.empty and "ticker" in prev_scored_for_merge.columns and not scored.empty:
                    _today_ts = pd.Timestamp.today().normalize()
                    _new_tickers = set(scored["ticker"].str.upper())
                    _stale_mask = ~prev_scored_for_merge["ticker"].str.upper().isin(_new_tickers)
                    _stale_rows = prev_scored_for_merge[_stale_mask].copy()

                    if not _stale_rows.empty:
                        # Beräkna ålder på befintlig data
                        if "data_fetched_date" in _stale_rows.columns:
                            _stale_rows["data_stale_days"] = (
                                _today_ts - pd.to_datetime(_stale_rows["data_fetched_date"], errors="coerce")
                            ).dt.days.fillna(7).clip(lower=0).astype(int)
                        else:
                            _stale_rows["data_stale_days"] = 7

                        # Bara max 14 dagar gammal data
                        _stale_rows = _stale_rows[_stale_rows["data_stale_days"] <= 14]

                        if not _stale_rows.empty:
                            # Stale-rader: score_delta = 0 (inga nya prisdata)
                            _stale_rows["score_delta_4w"] = 0.0

                            # Kolumnjustering — fyll saknade kolumner med NA
                            for _col in scored.columns:
                                if _col not in _stale_rows.columns:
                                    _stale_rows[_col] = pd.NA
                            _stale_rows = _stale_rows.reindex(columns=scored.columns)

                            scored = pd.concat([scored, _stale_rows], ignore_index=True)
                            logger.info(
                                f"  📦 Staleness-merge: +{len(_stale_rows)} aktier bevarade "
                                f"(täckning nu: {len(scored)}/{len(all_tickers)} = "
                                f"{len(scored)/len(all_tickers)*100:.0f}%)"
                            )
            except Exception as _me:
                logger.warning(f"  ⚠ Staleness-merge hoppades över: {_me}")

            csv_path = REPORT_DIR / f"scored_universe_{date_str}"
            _save_scored(scored, csv_path)

            # Spara tunn backtest-snapshot (point-in-time-korrekt historik)
            try:
                from backtesting.backtest_snapshots import save_snapshot
                if save_snapshot(scored, date_str):
                    logger.info(f"  📸 Backtest-snapshot sparad: {date_str}")
                    # Score-drift-larm: jämför med föregående snapshot
                    try:
                        from core.pipeline_alerts import send_score_drift_alerts
                        send_score_drift_alerts(date_str)
                    except Exception as _dae:
                        logger.debug(f"  ℹ drift-larm hoppades över: {_dae}")
            except Exception as _sne:
                logger.debug(f"  Snapshot ej sparad: {_sne}")
            else:
                logger.warning("Universe fetch returnerade tom DataFrame - laddar senaste cache")
                scored = _load_latest_scored("scored_universe_*.parquet")
                _ml_universe = "universe"
        elif mode == "smallcap":
            scored = _load_latest_scored("smallcap_scored_*.csv")
            _ml_universe = "smallcap"
        else:
            scored = pd.DataFrame()
            _ml_universe = None

        # Guard: om scored fortfarande ar tom efter all dataladdning -> avbryt
        if scored.empty and mode in ("weekly", "smallcap", "morning", "evening"):
            logger.error("Ingen scored_universe-data tillganglig - avbryter pipeline")
            return

        # =========================================================================
        # 1b. DAGLIG RE-SCORING (endast for morning/evening)
        #     Hamta nya priser for alla tickers -> uppdatera scores
        # =========================================================================
        if mode in ("morning", "evening") and not scored.empty and "ticker" in scored.columns:
            logger.info("Hamtar nya priser...")
            try:
                tickers = scored["ticker"].dropna().unique().tolist()
                price_tickers = [t for t in tickers if not t.startswith("^")][:300]
                price_data = fetch_prices_only(price_tickers, period="6mo", max_workers=12)
                if price_data:
                    n_prices = len(price_data)
                    scored = update_scored_with_prices(scored, price_data)
                    logger.info(f"  Priser hamtade for {n_prices} tickers - scores uppdaterade")

                    # Spara den uppdaterade parquet + csv
                    csv_path = REPORT_DIR / f"scored_universe_{date_str}"
                    _save_scored(scored, csv_path)
                else:
                    logger.warning("  Inga priser kunde hamtas - anvander gordagens data")
            except Exception as e:
                logger.warning(f"  Re-scoring misslyckades: {e} - anvander gordagens data")

        # =========================================================================
        # 1c. ML-PREDIKTION (om modell finns)
        #     Lagger till predicted_return + ml_rank-kolumner och sparar back.
        # =========================================================================
        if _ml_universe and not scored.empty and "ticker" in scored.columns:
            try:
                from core.ml_predictor import predict_returns_sector
                scored_ml = predict_returns_sector(scored, default_universe=_ml_universe)
                if "predicted_return" in scored_ml.columns:
                    scored = scored_ml
                    logger.info(f"  ML-prediktioner tillagda for {_ml_universe} ({len(scored)} rader)")
                    if _ml_universe == "universe":
                        csv_path = REPORT_DIR / f"scored_universe_{date_str}"
                    else:
                        csv_path = REPORT_DIR / f"smallcap_scored_{date_str}"
                    _save_scored(scored, csv_path)
            except Exception as e:
                logger.warning(f"  ML-prediktion hoppades over: {e}")

        # =========================================================================
        # 1d. ML PAPER TRADING (om modell finns)
        #     Registrera dagens topp-N enligt ML som virtuella kop.
        # =========================================================================
        if _ml_universe and not scored.empty and "predicted_return" in scored.columns:
            try:
                from core.ml_paper_trading import record_daily_signals
                n_recorded = record_daily_signals(scored, universe=_ml_universe, top_n=10)
                if n_recorded:
                    logger.info(f"  ML paper trading: {n_recorded} signaler registrerade ({_ml_universe})")
            except Exception as e:
                logger.warning(f"  ML paper trading hoppades over: {e}")

        # =========================================================================
        # 1e. KLASSISK PAPER TRADING (score-baserad, krs for weekly + smallcap)
        # =========================================================================
        if mode in ("weekly", "smallcap") and not scored.empty:
            try:
                from portfolio.paper_trading import record_weekly_picks
                pt_universe = "smallcap" if mode == "smallcap" else "universe"
                pt_result = record_weekly_picks(scored, top_n=10, universe=pt_universe, verbose=False)
                n_pt = len(pt_result.get("trades", [])) if isinstance(pt_result, dict) else 0
                logger.info(f"  Klassisk paper trading: {n_pt} positioner registrerade ({pt_universe})")
            except Exception as e:
                logger.warning(f"  Klassisk paper trading hoppades over: {e}")

        # =========================================================================
        # 1f. UNIVERSE ROTATION (weekly-mode, efter scoring och paper trading)
        # =========================================================================
        if mode == "weekly" and not scored.empty:
            try:
                _rot_dry_run = os.getenv("ROTATION_DRY_RUN", "true").lower() not in ("false", "0", "no")
                from core.rotation_engine import run_rotation
                rotation_result = run_rotation(
                    max_replacements=5,
                    auto_execute=not _rot_dry_run,
                    use_ai=True,
                    dry_run=_rot_dry_run,
                    scored=scored,
                    provider="auto",
                )
                n_triggers = len(rotation_result.get("triggers", []))
                n_executed = len(rotation_result.get("executed", []))
                if n_triggers:
                    logger.info(f"  Rotation: {n_triggers} utlosare hittades, {n_executed} exekverade (dry_run={_rot_dry_run})")
                else:
                    logger.info("  Rotation: inga utlosare hittades")
            except Exception as e:
                logger.warning(f"  Rotation hoppades over: {e}")

        # =========================================================================
        # 1g. UNIVERSE DISCOVERY (weekly — hämtar nyhetsbaserade kandidater)
        #     Kör en snabb nyhetsbaserad scan och sparar kandidater som pending.
        #     Tung discovery (Finviz, ETF, AI) körs via GitHub Actions söndagar.
        # =========================================================================
        if mode == "weekly":
            try:
                _disc_dry_run = os.getenv("DISCOVERY_DRY_RUN", "true").lower() not in ("false", "0", "no")
                from core.universe_manager import run_full_maintenance
                disc_result = run_full_maintenance(
                    sources=["news"],        # Snabb källa — Finviz/ETF/AI körs via GitHub Actions
                    auto_add_threshold=0.88, # Konservativ: kräver HIGH-tier + ≥88% confidence
                    auto_remove=False,       # Borttagning hanteras av admin-UI
                    dry_run=_disc_dry_run,
                    commit=False,            # Commit sker via dedikerat GitHub Actions-workflow
                    ai_provider="auto",
                    verbose=False,
                )
                n_added  = len(disc_result.get("auto_added", []))
                n_new    = disc_result.get("candidates_new", 0)
                logger.info(
                    f"  Discovery: {n_new} nya pending-kandidater, "
                    f"{n_added} auto-tillagda (dry_run={_disc_dry_run})"
                )
            except Exception as e:
                logger.warning(f"  Universe discovery hoppades over: {e}")

        # Portfolj & watchlist
        holdings = _load_portfolio()
        watchlist_raw = _load_watchlist()
        watchlist_tickers = [i.get("ticker", "") for i in watchlist_raw if i.get("ticker")]

        # Synka portfoljinnehav till custom_universe sa de ingar i veckoscannen
        try:
            custom_existing = set(c["ticker"] for c in config.load_custom_universe())
            universe_tickers_set = set(getattr(config, "UNIVERSE", []))
            added = 0
            for _, h in holdings.iterrows():
                t = str(h.get("ticker", "")).upper().strip()
                if not t or not _looks_like_ticker(t):
                    continue
                if t in universe_tickers_set or t in custom_existing:
                    continue
                in_main = any(t + sfx in universe_tickers_set for sfx in (".ST", ".HE", ".CO", ".OL"))
                if in_main:
                    continue
                in_custom = any(t + sfx in custom_existing for sfx in (".ST", ".HE", ".CO", ".OL"))
                if in_custom:
                    continue
                config.add_custom_to_universe(t, str(h.get("name", "")))
                added += 1
            if added:
                logger.info(f"  Lade till {added} portfoljinnehav i custom_universe for veckoscannen")
        except Exception as e:
            logger.warning(f"  Kunde inte synka portfolj till custom_universe: {e}")

        # Synka aven bevakningar till custom_universe
        try:
            custom_existing_wl = set(c["ticker"] for c in config.load_custom_universe())
            universe_tickers_set_wl = set(getattr(config, "UNIVERSE", []))
            added_wl = 0
            for w in watchlist_tickers:
                if not w:
                    continue
                w_up = w.upper().strip()
                if not _looks_like_ticker(w_up):
                    continue
                if w_up in universe_tickers_set_wl or w_up in custom_existing_wl:
                    continue
                in_main_wl = any(w_up + sfx in universe_tickers_set_wl for sfx in (".ST", ".HE", ".CO", ".OL"))
                if in_main_wl:
                    continue
                in_custom_wl = any(w_up + sfx in custom_existing_wl for sfx in (".ST", ".HE", ".CO", ".OL"))
                if in_custom_wl:
                    continue
                config.add_custom_to_universe(w_up, "")
                added_wl += 1
            if added_wl:
                logger.info(f"  Lade till {added_wl} bevakningar i custom_universe for veckoscannen")
        except Exception as e:
            logger.warning(f"  Kunde inte synka bevakningar till custom_universe: {e}")

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
            report_lines.append(f"# 🌅 MarketScan Morgonbrief - {date_str}\n")
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
                    report_lines.append(f"- 🔴 **{flag_for_ticker(h['ticker'])} {h['ticker']}** - {h['pnl_pct']:+.1f}% sedan inköp (stop-loss vid {h['stop_loss_pct']:+.1f}%)")
                report_lines.append("")

            # ── Portfölj ─────────────────────────────────────────────────────
            report_lines.append(_section_header("💼 Din portfölj"))
            if enriched:
                for h in enriched[:10]:
                    emoji = "🟢" if (h.get("pnl_pct") or 0) >= 0 else "🔴"
                    pnl = f"{h['pnl_pct']:+.1f}%" if h['pnl_pct'] is not None else "--"
                    sl_info = f" (stop-loss vid {h['stop_loss_pct']:+.1f}%)" if h.get('stop_loss_pct') and (h.get('pnl_pct') or 0) <= -10 else ""
                    score_val = h.get('score')
                    score_str = f"{score_val:.0f}" if score_val is not None else "--"
                    entry_str = h.get('entry', '--') or '--'
                    report_lines.append(f"- {emoji} **{flag_for_ticker(h['ticker'])} {h['ticker']}** - {pnl} | Score {score_str} | {entry_str}{sl_info}")
            else:
                report_lines.append("*(Inga innehav i portföljen)*")

            # ── Bevakningar ──────────────────────────────────────────────────
            if watchlist_tickers:
                report_lines.append(_section_header("⭐ Dina bevakningar"))
                # Slå upp data för bevakningar från scored universe
                watchlist_with_data = []
                if not scored.empty and "ticker" in scored.columns:
                    for w in watchlist_tickers[:8]:
                        w_up = w.upper().strip()
                        match = scored[scored["ticker"] == w_up]
                        if not match.empty:
                            r = match.iloc[0]
                            sc = r.get("score_total")
                            entry = r.get("entry_signal", "--")
                            trend = r.get("trend_signal", "--")
                            rsi = r.get("rsi_14")
                            price = r.get("current_price") or r.get("close", 0)
                            watchlist_with_data.append(f"- **{flag_for_ticker(w_up)} {w_up}** - Score {sc:.0f} | {entry} | Trend: {trend} | RSI {rsi:.0f}" if sc and sc == sc else f"- **{w_up}** - (ingen score)")
                        else:
                            watchlist_with_data.append(f"- **{w_up}** - (inte i universet)")
                else:
                    for w in watchlist_tickers[:5]:
                        watchlist_with_data.append(f"- {w}")
                report_lines.extend(watchlist_with_data)
                report_lines.append("")

            # ── Topp-5 ───────────────────────────────────────────────────────
            if top_10:
                report_lines.append(_section_header("🏆 Dagens hetaste"))
                for t in top_10[:5]:
                    report_lines.append(f"- **{flag_for_ticker(t['ticker'])} {t['ticker']}** - Score {t['score']:.0f} | {t['entry']} | {t['sector']}")

            # ── Opportunities ────────────────────────────────────────────────
            if opportunities:
                report_lines.append(_opportunity_section(opportunities))

            # ── Kalender ─────────────────────────────────────────────────────
            try:
                from core.earnings_calendar import upcoming_in_portfolio, upcoming_in_top
                from core.macro_calendar import get_upcoming_macro_events
                holdings_df = pd.DataFrame(enriched) if enriched else pd.DataFrame()
                cal_earn = upcoming_in_portfolio(holdings_df, scored, days_ahead=7) if not holdings_df.empty else pd.DataFrame()
                if cal_earn.empty:
                    cal_earn = upcoming_in_top(scored, top_n=50, days_ahead=7)
                cal_macro = get_upcoming_macro_events(days_ahead=7)
                if not cal_earn.empty or cal_macro:
                    report_lines.append(_section_header("📅 Kommande rapporter & makro (7 dagar)"))
                    for _, row in cal_earn.head(5).iterrows():
                        ticker_c = row.get("ticker", "")
                        edate_c  = row.get("earnings_date", "?")
                        days_c   = row.get("days_until", "?")
                        report_lines.append(f"- 📊 **{ticker_c}** rapporterar {edate_c} (om {days_c} d)")
                    for ev in cal_macro[:3]:
                        report_lines.append(
                            f"- {ev.get('flag','')} **{ev.get('event','')}** — {ev.get('date','')} (om {ev.get('days_until','')} d)"
                        )
                    report_lines.append("")
            except Exception as _cal_err:
                logger.debug(f"  Kalenderdata kunde inte hämtas: {_cal_err}")

            # ── Nyheter ──────────────────────────────────────────────────────
            report_lines.append(_section_header("📰 Nyheter"))
            report_lines.append("*(Nyheter hämtas via nyhetslarm - se separat mail)*")
            report_lines.append("")

            # ── AI-sektion ───────────────────────────────────────────────────
            report_lines.append(_section_header("🤖 AI: Dagens analys"))
            report_lines.append("*Genereras nedan...*\n")

        elif mode == "evening":
            # ── Rubrik ────────────────────────────────────────────────────────
            report_lines.append(f"# 🌆 MarketScan Kvällsbrev - {date_str}\n")
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
                    pnl = f"{h['pnl_pct']:+.1f}%" if h['pnl_pct'] is not None else "--"
                    score_str = f"{h['score']:.0f}" if h.get('score') is not None else "--"
                    report_lines.append(f"- {emoji} **{flag_for_ticker(h['ticker'])} {h['ticker']}** - {pnl} | Score {score_str} | Rekommendation: {_get_rec(h)}")
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
            report_lines.append("*(Makro- och earnings-kalender - se veckorapport)*")
            report_lines.append("")

            # ── AI-sektion ───────────────────────────────────────────────────
            report_lines.append(_section_header("🤖 AI: Dagens reflektion"))
            report_lines.append("*Genereras nedan...*\n")

        elif mode == "weekly":
            # ── Rubrik ────────────────────────────────────────────────────────
            day_sv = {"Monday": "måndag", "Tuesday": "tisdag", "Wednesday": "onsdag",
                      "Thursday": "torsdag", "Friday": "fredag", "Saturday": "lördag",
                      "Sunday": "söndag"}.get(day_name, day_name)
            report_lines.append(f"# 📊 MarketScan Veckorapport - v. {datetime.now().isocalendar()[1]}\n")
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
                # Filtrera bort okända/tomma sektorer och NaN-snitt innan loopen
                sec = scored.groupby("sector")["score_total"].mean().sort_values(ascending=False)
                _skip_sectors = {"Unknown", "unknown", ""}
                for sector, avg in sec.items():
                    # Hoppa över tomma sektornamn, "Unknown" och sektorer där avg är NaN
                    if not sector or str(sector).strip() in _skip_sectors or pd.isna(avg):
                        continue
                    arrow = "🟢" if avg >= 60 else "🟡" if avg >= 45 else "🔴"
                    report_lines.append(f"- {arrow} **{sector}** - snittscore {avg:.1f}")
                report_lines.append("")

            # ── Portfölj ─────────────────────────────────────────────────────
            report_lines.append(_section_header("💼 Portföljanalys"))
            if enriched:
                for h in enriched:
                    rec = _get_rec(h)
                    emoji = "🟢" if rec in ("BEHÅLL", "KÖP MER") else "🟡" if rec == "BEVAKA" else "🔴"
                    pnl = f"{h['pnl_pct']:+.1f}%" if h['pnl_pct'] is not None else "--"
                    score_str = f"{h['score']:.0f}" if h.get('score') is not None else "--"
                    report_lines.append(f"- {emoji} **{flag_for_ticker(h['ticker'])} {h['ticker']}** - {pnl} | Score {score_str} | **{rec}**")
            else:
                report_lines.append("*(Inga innehav)*")

            # ── Topp-10 ──────────────────────────────────────────────────────
            if top_10:
                report_lines.append(_section_header("🏆 Topp-10 köprekommendationer"))
                for i, t in enumerate(top_10[:10], 1):
                    report_lines.append(
                        f"  {i}. **{flag_for_ticker(t['ticker'])} {t['ticker']}** "
                        f"- Score {t['score']:.0f} | {t['entry']} | {t['sector']}"
                    )
                    # Faktor-attribution: visa varför aktien rankas högt
                    # (defensivt: en formateringsbugg får aldrig krascha hela rapporten)
                    try:
                        attr = format_factor_attribution_md(t, compact=True)
                        if attr:
                            for attr_line in attr.split("\n"):
                                report_lines.append(f"     {attr_line}")
                            report_lines.append("")
                    except Exception as _attr_e:
                        logger.warning(f"  ⚠ Faktor-attribution hoppades över för {t.get('ticker','?')}: {_attr_e}")

            # ── Bottom-5 ─────────────────────────────────────────────────────
            if bottom_5:
                report_lines.append(_section_header("🔴 Bottom-5 varningar"))
                for b in bottom_5[:5]:
                    report_lines.append(f"- **{flag_for_ticker(b['ticker'])} {b['ticker']}** - Score {b['score']:.0f} | {b['entry']} | {b['sector']}")

            # ── Opportunities ────────────────────────────────────────────────
            if opportunities:
                report_lines.append(_opportunity_section(opportunities))

            # ── AI-sektion ───────────────────────────────────────────────────
            report_lines.append(_section_header("🤖 AI: Veckoanalys"))
            report_lines.append("*Genereras nedan...*\n")

        elif mode == "smallcap":
            # ── Rubrik ────────────────────────────────────────────────────────
            report_lines.append(f"# 🏦 MarketScan Småbolag - {date_str}\n")
            report_lines.append(f"_{short_summary}_\n")

            # ── Index-överblick ───────────────────────────────────────────────
            report_lines.append(_section_header("🌏 Marknadsläge"))
            index_lines = []
            for ticker in ["^OMX", "^GSPC", "^IXIC", "^GDAXI"]:
                data = indices.get(ticker)
                if data:
                    name = data.get("name", ticker)
                    chg = data.get("change_pct")
                    close = data.get("close")
                    if chg is not None and close is not None:
                        arrow = "🟢" if chg >= 0 else "🔴"
                        index_lines.append(f"- {name} {arrow} **{chg:+.1f}%** ({close:,.0f})")
            if index_lines:
                report_lines.extend(index_lines)
            report_lines.append("")

            # ── Universet ─────────────────────────────────────────────────────
            if not scored.empty and "score_total" in scored.columns:
                avg_score = scored["score_total"].mean()
                n_ok = int((scored.get("entry_signal", pd.Series()) == "OK").sum()) if "entry_signal" in scored.columns else 0
                report_lines.append(f"**Skannade småbolag:** {len(scored)} st | Snittscore: {avg_score:.1f} | Entry OK: {n_ok} st\n")

            # ── Portfölj ─────────────────────────────────────────────────────
            report_lines.append(_section_header("💼 Din portfölj"))
            if enriched:
                for h in enriched[:10]:
                    emoji = "🟢" if (h.get("pnl_pct") or 0) >= 0 else "🔴"
                    pnl = f"{h['pnl_pct']:+.1f}%" if h['pnl_pct'] is not None else "--"
                    score_str = f"{h['score']:.0f}" if h.get('score') is not None else "--"
                    entry_str = h.get('entry') or '--'
                    report_lines.append(f"- {emoji} **{flag_for_ticker(h['ticker'])} {h['ticker']}** - {pnl} | Score {score_str} | {entry_str}")
            else:
                report_lines.append("*(Inga innehav i portföljen)*")
            report_lines.append("")

            # ── Topp-10 ──────────────────────────────────────────────────────
            if top_10:
                report_lines.append(_section_header("🏆 Topp-10 småbolag"))
                for i, t in enumerate(top_10[:10], 1):
                    report_lines.append(f"  {i}. **{flag_for_ticker(t['ticker'])} {t['ticker']}** - Score {t['score']:.0f} | {t['entry']} | {t['sector']}")

            # ── Bottom varningar ──────────────────────────────────────────────
            if bottom_5:
                report_lines.append(_section_header("🔴 Varningar"))
                for b in bottom_5[:5]:
                    report_lines.append(f"- **{flag_for_ticker(b['ticker'])} {b['ticker']}** - Score {b['score']:.0f} | {b['entry']} | {b['sector']}")

            # ── Opportunities ────────────────────────────────────────────────
            if opportunities:
                report_lines.append(_opportunity_section(opportunities))

            # ── AI-sektion ───────────────────────────────────────────────────
            report_lines.append(_section_header("🤖 AI: Småbolagsanalys"))
            report_lines.append("*Genereras nedan...*\n")

        # ═══════════════════════════════════════════════════════════════════════
        # 3. AI-ANROP
        # ═══════════════════════════════════════════════════════════════════════

        # ─── Fetch live news for AI context (portfolio + watchlist + top-5) ─────
        pipeline_news_text = ""
        try:
            from core.news_fetcher import fetch_company_news
            # Build set of tickers worth fetching news for - keep small to avoid rate limits
            news_tickers: list[tuple[str, str | None]] = []
            seen = set()
            # Portfolio holdings
            for h in (enriched or [])[:10]:
                t = h.get("ticker")
                if t and t not in seen:
                    seen.add(t)
                    news_tickers.append((t, h.get("name")))
            # Watchlist
            for t in (watchlist_tickers or [])[:5]:
                if t and t not in seen:
                    seen.add(t)
                    news_tickers.append((t, None))
            # Top-5 picks
            for tp in (top_10 or [])[:5]:
                t = tp.get("ticker") if isinstance(tp, dict) else None
                if t and t not in seen:
                    seen.add(t)
                    news_tickers.append((t, tp.get("name") if isinstance(tp, dict) else None))

            news_blocks = []
            for ticker_, cname in news_tickers[:15]:
                try:
                    items = fetch_company_news(ticker_, days_back=3, company_name=cname) or []
                    if items:
                        lines = []
                        for n in items[:4]:
                            title = n.get("headline", n.get("title", "")).strip()
                            src = n.get("source", "")
                            age = n.get("age_hours")
                            age_s = f" ({age:.0f}h sedan)" if age is not None else ""
                            if title:
                                lines.append(f"- {title} [{src}]{age_s}")
                        if lines:
                            news_blocks.append(f"{ticker_}:\n" + "\n".join(lines))
                except Exception:
                    continue
            if news_blocks:
                pipeline_news_text = "\n\n".join(news_blocks)
            logger.info(f"  Nyheter hamtade for {len(news_blocks)} tickers (AI-kontext)")
        except Exception as e:
            logger.warning(f"  Kunde inte hamta nyheter for AI: {e}")

        ai_section = ""
        try:
            logger.info("  Anropar AI...")
            provider = os.getenv("AI_PROVIDER", "auto") or "auto"

            def _add_news(base_ctx: str) -> str:
                if pipeline_news_text:
                    return base_ctx + "\n\nFarska nyheter:\n" + pipeline_news_text
                return base_ctx

            if mode == "morning":
                ctx = _build_ai_morning_context(
                    indices, enriched, watchlist_tickers, top_10, bottom_5,
                    opportunities, "", "OSÄKER", vix
                )
                result = ai_analysis.ai_chat(
                    "Skapa dagens morgonbrief. Analysera datan och ge mig en personlig rapport.",
                    context=_add_news(ctx),
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
                    context=_add_news(ctx),
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
                    context=_add_news(ctx),
                    provider=provider,
                    depth="Extra djup",
                )
                ai_section = result

            elif mode == "smallcap":
                ctx = _build_ai_smallcap_context(
                    scored, enriched, watchlist_tickers, top_10, bottom_5,
                    opportunities, indices
                )
                result = ai_analysis.ai_chat(
                    "Skapa en småbolagsanalys. Identifiera de bästa köpkandidaterna och ge konkreta rekommendationer.",
                    context=_add_news(ctx),
                    system_prompt_override=SMALLCAP_AI_SYSTEM_PROMPT,
                    provider=provider,
                    depth="Djup",
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

        # Spara AI-text separat för lazy-load i Streamlit
        _save_ai_text(mode, date_str, ai_section)

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
            "morning": f"🌅 MarketScan Morgonbrief - {date_str}",
            "evening": f"🌆 MarketScan Kvällsbrev - {date_str}",
            "weekly": f"📊 MarketScan Veckorapport - v.{datetime.now().isocalendar()[1]}",
            "smallcap": f"🏦 MarketScan Småbolag - {date_str}",
        }
        subscription_type_map = {
            "morning":  "morning_report",
            "evening":  "evening_report",
            "weekly":   "weekly_summary",
            "smallcap": "smallcap_report",
        }
        subject = subject_map.get(mode, f"MarketScan Rapport - {date_str}")
        sub_type = subscription_type_map.get(mode, "morning_report")

        try:
            from core.email_template import load_subscribers, build_personal_portfolio_section

            # Skicka personaliserade mail per prenumerant
            subscribers = load_subscribers()
            active_subs = [
                s for s in subscribers
                if s.get("active", True) and s.get("subscriptions", {}).get(sub_type, False) and s.get("email")
            ]

            if active_subs:
                email_sent = False
                for sub in active_subs:
                    try:
                        # Bygg personlig portföljsektion om användaren har ett konto
                        personal_section = ""
                        uname = sub.get("username")
                        if uname and mode in ("morning", "weekly"):
                            personal_section = build_personal_portfolio_section(uname, scored if not scored.empty else None)

                        body = report_text
                        if personal_section:
                            body = body + "\n\n---\n\n" + personal_section

                        ok = send_email(
                            subject=subject,
                            body_markdown=body,
                            from_name="MarketScan",
                            recipients=[sub["email"]],
                        )
                        if ok:
                            logger.info(f"  ✉ Mail skickat till {sub['email']}")
                            email_sent = True
                        else:
                            logger.warning(f"  ⚠ Mail misslyckades för {sub['email']}")
                    except Exception as sub_e:
                        logger.error(f"  ❌ Mail-fel för {sub.get('email','?')}: {sub_e}")
            else:
                # Fallback: skicka till konfigurerat EMAIL_TO om inga prenumeranter
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
        # 5b. STARK-LARM PER ANVÄNDARE (bevakningslista + innehav)
        # ═══════════════════════════════════════════════════════════════════════
        if not scored.empty and mode in ("morning", "weekly"):
            try:
                _send_stark_alerts(scored, date_str)
            except Exception as e:
                logger.warning(f"  ⚠ STARK-larm misslyckades: {e}")

        # ═══════════════════════════════════════════════════════════════════════
        # 5c. KALENDER-PÅMINNELSE (enbart morning, måndagar eller 1:a dag i månaden)
        # ═══════════════════════════════════════════════════════════════════════
        if mode == "morning":
            try:
                from core.earnings_calendar import upcoming_in_portfolio, upcoming_in_top
                from core.macro_calendar import get_upcoming_macro_events
                from core.alerts import send_calendar_reminder
                _now = datetime.now()
                # Skicka kalender-mail på måndagar och 1:a varje månad
                if _now.weekday() == 0 or _now.day == 1:
                    _holdings_df = pd.DataFrame(enriched) if enriched else pd.DataFrame()
                    _cal_earn = (
                        upcoming_in_portfolio(_holdings_df, scored, days_ahead=14)
                        if not _holdings_df.empty
                        else pd.DataFrame()
                    )
                    if _cal_earn.empty:
                        _cal_earn = upcoming_in_top(scored, top_n=50, days_ahead=14)
                    _cal_macro = get_upcoming_macro_events(days_ahead=14)
                    if not _cal_earn.empty or _cal_macro:
                        _sent = send_calendar_reminder(
                            earnings_events=_cal_earn if not _cal_earn.empty else None,
                            macro_events=_cal_macro or None,
                            days_ahead=14,
                        )
                        if _sent:
                            logger.info("  📅 Kalender-påminnelse skickad")
            except Exception as _cal_e:
                logger.warning(f"  ⚠ Kalender-påminnelse misslyckades: {_cal_e}")

        # ═══════════════════════════════════════════════════════════════════════
        # 6. KLART
        # ═══════════════════════════════════════════════════════════════════════

        pipeline_success = True
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

    except Exception as pipeline_error:
        # Fånga alla pipeline-fel för metrik
        pipeline_success = False
        elapsed = time.time() - start_time
        logger.error(f"❌ Pipeline misslyckades efter {elapsed:.0f}s: {pipeline_error}")
        pl.log_error("pipeline", "PIPELINE_FAILED", str(pipeline_error)[:300])

        # ── Skyddsnät: skicka en minimal fallback-rapport om ett sent fel ──────
        # uppstår (t.ex. i rapportbygget) EFTER att scoring redan lyckats.
        # Annars går 20+ min datahämtning förlorad och användaren får inget mail.
        try:
            _email_already_sent = 'email_sent' in locals() and email_sent
            _scored_fallback = locals().get("scored")
            if (not _email_already_sent
                    and _scored_fallback is not None
                    and not _scored_fallback.empty
                    and "score_total" in _scored_fallback.columns):
                _date = date.today().strftime("%Y-%m-%d")
                _top = _scored_fallback.nlargest(10, "score_total")
                _lines = [
                    f"# ⚠️ MarketScan {mode} - ofullständig rapport ({_date})\n",
                    "Scanningen slutfördes men rapportgenereringen kraschade. "
                    "Här är de högst rankade aktierna från dagens scan ändå:\n",
                ]
                for _i, (_, _r) in enumerate(_top.iterrows(), 1):
                    _tk = _r.get("ticker", "?")
                    _sc = _r.get("score_total")
                    _sc_s = f"{_sc:.0f}" if isinstance(_sc, (int, float)) and _sc == _sc else "--"
                    _en = _r.get("entry_signal", "--")
                    _lines.append(f"  {_i}. **{_tk}** — Score {_sc_s} | {_en}")
                _lines.append(f"\n\n_Tekniskt fel: {str(pipeline_error)[:200]}_")
                from core.email_template import send_email as _send
                _send(
                    subject=f"⚠️ MarketScan {mode} (ofullständig) - {_date}",
                    body_markdown="\n".join(_lines),
                    from_name="MarketScan",
                    subscription_type={
                        "morning": "morning_report", "evening": "evening_report",
                        "weekly": "weekly_summary", "smallcap": "smallcap_report",
                    }.get(mode, "weekly_summary"),
                )
                logger.info("  ✉ Fallback-rapport skickad trots pipeline-fel")
        except Exception as _fb_e:
            logger.warning(f"  ⚠ Fallback-rapport kunde inte skickas: {_fb_e}")

        raise
    finally:
        # ── Alltid spara metrik och loggar ──────────────────────────────────
        try:
            if metrics is not None:
                metrics.pipeline_end(mode, success=pipeline_success)
        except Exception:
            pass
        # ── Logga scan-resultat till scan_log.json (admin-dashboardens källa) ──
        # Utan detta fryser "Senaste scan" på dashboarden — alla scan-typer
        # (morning/evening/weekly/smallcap) ska synas här, även krascher (ERROR).
        try:
            from core.logger import log_event
            _elapsed = round(time.time() - start_time, 1)
            _err = locals().get("pipeline_error")
            log_event(
                mode,
                "OK" if pipeline_success else "ERROR",
                details={"scan_type": mode, "elapsed_seconds": _elapsed},
                error=(str(_err)[:300] if (not pipeline_success and _err) else None),
            )
        except Exception:
            pass
        # E3: Spara strukturerade metrics
        try:
            from core.metrics import record_pipeline_run
            _n = len(scored_df) if "scored_df" in dir() and scored_df is not None and hasattr(scored_df, "__len__") else 0  # type: ignore[possibly-undefined]
            _n_err = 1 if not pipeline_success else 0
            record_pipeline_run(mode=mode, duration_s=_elapsed, n_scored=_n, n_errors=_n_err)
        except Exception:
            pass
        try:
            pl.save()
        except Exception:
            pass
        # Spara health snapshot
        try:
            from core.monitoring.health import save_health_snapshot
            save_health_snapshot()
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════════════
# RETRY RATE-LIMITED TICKERS
# ══════════════════════════════════════════════════════════════════════════════

_RETRY_PENDING_PATH = DATA_DIR / "retry_pending.json"


def _read_pending_tickers() -> tuple[list[str], int]:
    """
    Läs vilka tickers som väntar på retry.
    Prio 1: retry_pending.json (state från föregående körning).
    Prio 2: fetch_errors.json (senaste scans rate_limited_tickers).
    Returnerar (tickers, pass_count).
    """
    # Prio 1: retry_pending.json
    if _RETRY_PENDING_PATH.exists():
        try:
            data = json.loads(_RETRY_PENDING_PATH.read_text(encoding="utf-8"))
            tickers = data.get("tickers", [])
            pass_count = data.get("pass_count", 0)
            created = data.get("created", "")
            # Ignorera om filen är äldre än 7 dagar (kan vara från gammal veckoscan)
            if created:
                from datetime import datetime as _dt2
                age_days = (datetime.now() - _dt2.fromisoformat(created)).days
                if age_days > 7:
                    logger.info(f"  retry_pending.json är {age_days} dagar gammal — ignoreras")
                    _RETRY_PENDING_PATH.unlink(missing_ok=True)
                    tickers = []
            if tickers:
                logger.info(f"  📋 retry_pending.json: {len(tickers)} tickers (pass {pass_count})")
                return tickers, pass_count
        except Exception as e:
            logger.warning(f"  ⚠ retry_pending.json kunde inte läsas: {e}")

    # Prio 2: fetch_errors.json senaste entry
    errors_path = DATA_DIR / "fetch_errors.json"
    if errors_path.exists():
        try:
            history = json.loads(errors_path.read_text(encoding="utf-8"))
            if history:
                latest = history[-1]
                tickers = latest.get("rate_limited_tickers", [])
                if tickers:
                    logger.info(
                        f"  📋 fetch_errors.json: {len(tickers)} rate-limitade tickers "
                        f"från senaste scan ({latest.get('timestamp', '?')[:10]})"
                    )
                    return tickers, 0
        except Exception as e:
            logger.warning(f"  ⚠ fetch_errors.json kunde inte läsas: {e}")

    return [], 0


def _save_pending_tickers(tickers: list[str], pass_count: int, source_mode: str = "weekly") -> None:
    """Spara återstående tickers till retry_pending.json. Raderar filen om listan är tom."""
    if not tickers:
        _RETRY_PENDING_PATH.unlink(missing_ok=True)
        logger.info("  ✅ retry_pending.json raderad — inga kvarvarande tickers")
        return
    data = {
        "created": datetime.now().isoformat(timespec="seconds"),
        "source_mode": source_mode,
        "pass_count": pass_count,
        "n_tickers": len(tickers),
        "tickers": sorted(tickers),
    }
    _RETRY_PENDING_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"  💾 retry_pending.json: {len(tickers)} tickers kvar (pass {pass_count})")


def _latest_rate_limited_in_batch(pending_set: set[str]) -> list[str]:
    """
    Läs rate_limited_tickers från senaste entry i fetch_errors.json
    och filtrera till de som fanns i vår pending-mängd.
    """
    errors_path = DATA_DIR / "fetch_errors.json"
    if not errors_path.exists():
        return []
    try:
        history = json.loads(errors_path.read_text(encoding="utf-8"))
        if history:
            latest_rl = history[-1].get("rate_limited_tickers", [])
            return [t for t in latest_rl if t.upper() in pending_set]
    except Exception:
        pass
    return []


def _load_blacklist_set() -> set[str]:
    bl_path = DATA_DIR / "blacklist.json"
    try:
        return set(json.loads(bl_path.read_text(encoding="utf-8")).keys()) if bl_path.exists() else set()
    except Exception:
        return set()


def run_retry_rate_limited(max_passes: int = 5, pass_delay_s: int = 120) -> dict:
    """
    Iterativ retry för rate-limitade tickers från senaste weekly/smallcap scan.

    Varje yttre pass anropar run_targeted() (som internt kör pass1 + pass2 retry).
    Tickers som fortfarande är rate-limitade efter pass2 sparas och retryars i
    nästa yttre pass, med ökande fördröjning (120s, 240s, 360s...).

    Avbrottskriterier:
    - Alla tickers lyckades (tom pending-lista).
    - En ticker blacklistas (genuint delistad/404) → hoppas över automatiskt.
    - max_passes yttre pass körda utan att listan töms → sparar kvarvarande i
      retry_pending.json och avslutar (nästa schemalagda körning plockar upp dem).

    Args:
        max_passes:    Max antal yttre pass i EN körning (varje pass = pass1+pass2 internt).
        pass_delay_s:  Bas-fördröjning (s) mellan yttre pass; multipliceras med pass-numret.

    Returns:
        dict: passes_run, n_succeeded, n_still_pending, n_skipped
    """
    logger.info("\n" + "=" * 60)
    logger.info("♻️  Retry rate-limitade tickers — iterativt till alla klarar sig")
    logger.info("=" * 60)

    pending, pass_count = _read_pending_tickers()

    if not pending:
        logger.info("  ✅ Inga rate-limitade tickers att retry:a — avslutar")
        return {"passes_run": 0, "n_succeeded": 0, "n_still_pending": 0, "n_skipped": 0}

    # Filtrera bort redan blacklistade (genuint delistade sedan senaste scan)
    blacklist = _load_blacklist_set()
    initial = len(pending)
    pending = [t for t in pending if t.upper() not in blacklist]
    n_skipped = initial - len(pending)
    if n_skipped:
        logger.info(f"  🚫 {n_skipped} tickers redan i blacklist — hoppas över")

    if not pending:
        logger.info("  ✅ Inga tickers kvar efter blacklist-filter")
        _save_pending_tickers([], pass_count)
        return {"passes_run": 0, "n_succeeded": 0, "n_still_pending": 0, "n_skipped": n_skipped}

    logger.info(f"  📋 {len(pending)} tickers att försöka hämta (max {max_passes} pass)")

    total_succeeded = 0
    passes_run = 0

    for pass_num in range(1, max_passes + 1):
        if not pending:
            break

        passes_run = pass_num
        pending_set = set(t.upper() for t in pending)

        # Exponentiell fördröjning mellan yttre pass (hoppa över delay på pass 1)
        if pass_num > 1:
            delay = pass_delay_s * pass_num   # 240s, 360s, 480s...
            logger.info(f"\n  ⏳ Pass {pass_num}: väntar {delay}s (Yahoo-begränsningar varierar över tid)...")
            time.sleep(delay)

        logger.info(f"\n  🔄 Yttre pass {pass_num}/{max_passes}: {len(pending)} tickers")

        # Notera blacklist INNAN hämtning → identifiera nydelistade i detta pass
        bl_before = _load_blacklist_set()

        # Kör targeted fetch + re-score + merge (pass1 + pass2 sker inuti run_targeted)
        try:
            n_ok = run_targeted(pending)
        except Exception as e:
            logger.warning(f"  ⚠ run_targeted kastade undantag i pass {pass_num}: {e}")
            n_ok = 0

        # Vilka är fortfarande rate-limitade efter internt pass1+pass2?
        still_rate_limited = _latest_rate_limited_in_batch(pending_set)

        # Nydelistade = auto-blacklistade under detta pass
        bl_after = _load_blacklist_set()
        new_blacklisted = (bl_after - bl_before) & pending_set
        n_skipped += len(new_blacklisted)

        # Lyckade = alla pending minus kvarvarande rate-limited minus nydelistade
        succeeded_this_pass = len(pending) - len(still_rate_limited) - len(new_blacklisted)
        total_succeeded += max(0, succeeded_this_pass)

        if new_blacklisted:
            logger.info(
                f"  🚫 {len(new_blacklisted)} nydelistade (auto-blacklistade): "
                f"{', '.join(sorted(new_blacklisted)[:8])}"
            )
        if still_rate_limited:
            sample = ', '.join(still_rate_limited[:8])
            tail = '...' if len(still_rate_limited) > 8 else ''
            logger.info(f"  ⚠ {len(still_rate_limited)} fortfarande rate-limitade: {sample}{tail}")

        logger.info(
            f"  ✅ Pass {pass_num} klart: {succeeded_this_pass} lyckades, "
            f"{len(still_rate_limited)} kvar, {len(new_blacklisted)} delistade"
        )

        # Nästa iteration arbetar bara på de som fortfarande är rate-limitade
        pending = still_rate_limited

        # Spara kvarstående state (raderas automatiskt om pending är tom)
        _save_pending_tickers(pending, pass_count + pass_num)

    # Sammanfattning
    logger.info(
        f"\n  📊 Retry klar: {total_succeeded} lyckades, "
        f"{len(pending)} kvar för nästa körning, {n_skipped} delistade, "
        f"{passes_run}/{max_passes} pass körda"
    )
    return {
        "passes_run":      passes_run,
        "n_succeeded":     total_succeeded,
        "n_still_pending": len(pending),
        "n_skipped":       n_skipped,
    }


# ══════════════════════════════════════════════════════════════════════════════
# UNIVERSE AUDIT
# ══════════════════════════════════════════════════════════════════════════════

def run_universe_audit(min_snapshots: int = 2) -> dict:
    """
    Jämför universe.json mot alla tillgängliga scored_universe-parquet-snapshots.
    Identifierar tickers som aldrig eller sällan lyckas hämtas.

    Returnerar dict med:
      never_appeared:    tickers aldrig i någon snapshot (genuint döda/404)
      rarely_appeared:   tickers i < 33% av snapshots (kroniskt rate-limitade)
      always_present:    tickers i >= 80% av snapshots (pålitliga)
      n_snapshots:       antal snapshots som analyserades
      coverage_pct:      % av universe som alltid finns

    Sparar resultatet i data/universe_audit.json.
    """
    import glob as _glob

    snapshot_files = sorted(
        _glob.glob(str(REPORT_DIR / "scored_universe_*.parquet"))
    )

    if len(snapshot_files) < min_snapshots:
        msg = f"Bara {len(snapshot_files)} snapshot(s) — behöver {min_snapshots} för meningsfull analys"
        logger.warning(f"  run_universe_audit: {msg}")
        result = {
            "generated": datetime.now().isoformat(),
            "error": msg,
            "n_snapshots": len(snapshot_files),
            "never_appeared": [],
            "rarely_appeared": [],
            "always_present": [],
            "coverage_pct": 0,
        }
        _audit_path = DATA_DIR / "universe_audit.json"
        _audit_path.write_text(
            json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return result

    # Räkna förekomster per ticker
    ticker_counts: dict[str, int] = {}
    n_ok = 0
    for fpath in snapshot_files:
        try:
            snap = pd.read_parquet(fpath, columns=["ticker"])
            for t in snap["ticker"].str.upper().tolist():
                ticker_counts[t] = ticker_counts.get(t, 0) + 1
            n_ok += 1
        except Exception as _e:
            logger.debug(f"  audit: kunde inte läsa {fpath}: {_e}")

    n_snaps = n_ok
    universe_tickers = set(t.upper() for t in config.UNIVERSE)

    never_appeared   = sorted(t for t in universe_tickers if ticker_counts.get(t, 0) == 0)
    rarely_appeared  = sorted(
        t for t in universe_tickers
        if 0 < ticker_counts.get(t, 0) < n_snaps * 0.33
    )
    always_present   = sorted(
        t for t in universe_tickers
        if ticker_counts.get(t, 0) >= max(1, n_snaps * 0.80)
    )
    coverage_pct = round(len(always_present) / len(universe_tickers) * 100, 1) if universe_tickers else 0.0

    result = {
        "generated": datetime.now().isoformat(),
        "n_snapshots": n_snaps,
        "n_universe": len(universe_tickers),
        "coverage_pct": coverage_pct,
        "never_appeared": never_appeared,
        "rarely_appeared": rarely_appeared,
        "always_present": always_present,
    }

    _audit_path = DATA_DIR / "universe_audit.json"
    _audit_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    logger.info(
        f"  📋 Universe audit klar: {len(never_appeared)} aldrig, "
        f"{len(rarely_appeared)} sällan, {len(always_present)} alltid "
        f"({coverage_pct:.0f}% täckning) — {n_snaps} snapshots"
    )
    return result


# ══════════════════════════════════════════════════════════════════════════════
# CLI-ENTRY
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "morning"
    if mode not in ("morning", "evening", "weekly", "smallcap"):
        print("Användning: python -m core.daily_pipeline [morning|evening|weekly|smallcap]")
        sys.exit(1)
    run_pipeline(mode=mode)