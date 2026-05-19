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
# DATALADDNING
# ══════════════════════════════════════════════════════════════════════════════

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
    logger.warning("  ⚠ Ingen scored_universe-fil hittad – kör utan scandata")
    return pd.DataFrame()


def _save_scored(df: pd.DataFrame, path: Path):
    """Spara DataFrame som både .parquet (zstd) och .csv (för bakåtkompatibilitet).
    
    Använder atomisk skrivning: skriver först till .tmp, sedan rename.
    Detta förhindrar att en krasch mitt i skrivningen lämnar en korrupt fil
    som saboterar Streamlit-dashboarden.
    """
    csv_path = path.with_suffix(".csv")
    df.to_csv(csv_path, index=False)
    
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
        logger.warning("  ⚠ pyarrow saknas – sparar enbart .csv")
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

        # Om holding saknas i scored_universe – beräkna tekniska indikatorer från prisdata
        tech = {}
        if not sc:
            tech = _calc_tech_fallback(t)

        enriched.append({
            "ticker": t,
            "name": sc.get("name", t) if sc else t,
            "sector": sc.get("sector", "—") if sc else "—",
            "shares": shares,
            "cost_basis": cost,
            "price": round(float(price), 2) if price else None,
            "market_value": round(mv, 0),
            "pnl_pct": pnl_pct,
            "stop_loss_pct": stop_loss_pct,
            "score": sc.get("score_total") if sc else None,
            "entry": (sc.get("entry_signal", "—") if sc else tech.get("entry", "—")) or "—",
            "trend": (sc.get("trend_signal", "—") if sc else tech.get("trend", "—")) or "—",
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


from core.pipeline_report import (
    _section, _table, _portfolio_table, _opportunity_section, _section_header,
    _build_ai_morning_context, _build_ai_evening_context,
    _build_ai_weekly_context, _build_ai_smallcap_context,
)
from core.pipeline_alerts import _send_stark_alerts, _get_rec

# ══════════════════════════════════════════════════════════════════════════════
# AI-PROMPTS
# ══════════════════════════════════════════════════════════════════════════════

MORNING_AI_SYSTEM_PROMPT = """Du är en personlig portföljrådgivare. Skapa en morgonbrief baserad på datan nedan.

TÄNK PÅ:
- Skriv på svenska, personligt och engagerande
- Använd emojis för att markera riktning (🟢🔴🟡)
- Var konkret med rekommendationer
- Fokusera på vad som är VIKTIGT för mottagaren just idag
- **Nyheter finns bifogade – väg in dem i din analys**, särskilt för portfölj och bevakningar

STRUKTUR (800-1000 ord):
1. 🌏 **Global överblick** – Vad hände i natt? USA-stängning, Asien-öppning, Europa-öppning. VIX-nivå.
2. 💼 **Din portfölj** – Gå igenom varje innehav. Är någon nära stop-loss? Någon som sticker ut?
3. ⭐ **Dina bevakningar** – Har någon rört sig mycket? Något nytt att titta på? Kolla nyheter om dem!
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
- **Nyheter finns bifogade – väg in dem**, särskilt om de påverkar portfölj eller bevakningar

STRUKTUR (800-1000 ord):
1. 📊 **Dagens utveckling** – Hur gick börserna idag? (Sverige, Europa, USA öppen)
2. 💼 **Portfölj-P&L** – Hur mycket tjänade/förlorade du idag? Gå igenom varje innehav
3. ⭐ **Bevakningar som rört sig** – Någon som stack ut idag? Har de nyheter?
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
- **Nyheter finns bifogade för portfölj, bevakningar och topplaceringar – väg in dem**

STRUKTUR (1500-2000 ord):
1. 📈 **Marknadsregim & bredd** – Veckans utveckling, VIX, bredd, sektorer
2. 🌏 **Globalt** – USA, Europa, Asien – trender och makro
3. 💼 **Djup portföljanalys** – Varje innehav med trend, rekommendation, stop-loss. Kolla nyheter om dem!
4. ⭐ **Bevakningslistan** – Bör du lägga till/ta bort något? AI-bedömning. Finns nyheter?
5. 🏆 **Topp-10 köprekommendationer** – Med motivering per aktie + nyheter
6. 🔴 **Bottom-5 varningar** – Aktier att minska/undvika
7. 🏭 **Sektormomentum** – Vilka sektorer leder/släpar
8. 📰 **Nyheter & makro** – Viktigaste händelserna
9. 🎯 **Kommande vecka** – Earnings, makro, opportunities
10. ✅ **Rekommendation** – Om du bara gör EN sak denna vecka...
"""

SMALLCAP_AI_SYSTEM_PROMPT = """Du är en småbolagsspecialist. Skapa en analys av småbolagsuniverse baserat på datan nedan.

TÄNK PÅ:
- Skriv på svenska, konkret och handlingsorienterat
- Fokusera på specifika aktier och köpsignaler
- Småbolag har högre risk – påpeka stop-loss-nivåer
- Lyft fram det som sticker ut (positivt och negativt)

STRUKTUR (600-900 ord):
1. 📊 **Småbolagsöversikt** – Hur ser småbolagsmarknaden ut just nu?
2. 💼 **Din portfölj** – Gå igenom innehaven med rekommendationer
3. 🏆 **Topp-5 köpkandidater** – Starka signaler med motivering
4. ⚠️ **Varningar** – Aktier med svaga signaler eller nära stop-loss
5. 🎯 **Rekommendation** – 1-2 konkreta åtgärder just nu

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


def _pre_scan_sync_universe():
    """
    Synkar portföljinnehav och bevakningslista till custom_universe.json
    INNAN veckoscannen startar.

    Säkerställer att aktier som lagts till via webbgränssnittet sedan
    förra scannen inkluderas i DENNA scan — inte bara i nästa.
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
        2. Hämta fresh data för target-tickers (force_refresh=True → bypassa cache)
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
    logger.info(f"🎯 Targeted refresh – {len(tickers)} tickers: {', '.join(tickers)}")
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
        logger.warning(f"  ⚠ Ingen data hämtades för {tickers} – avbryter")
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
        # raw_new saknar score-kolumner ännu — det ger NaN, vilket vi fyller i steg 4
        merged_raw = pd.concat([kept, raw_new], ignore_index=True)

    # ── Steg 4: Re-scora hela df:n ────────────────────────────────────────────
    # Percentilrankning kräver hela universum — vi kan inte scora bara target-rader.
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
        from core.ml_predictor import predict_returns
        scored = predict_returns(scored, "universe")
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
            entry = row.get("entry_signal", "—")
            logger.info(f"  ✓ {row['ticker']}: score={score:.1f}, entry={entry}")

    logger.info(f"\n✅ Targeted refresh klar — {succeeded} ticker(s) uppdaterade\n")
    return succeeded


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

    Körs 1–2 gånger per dag via GitHub Actions (schema: 08:00 + 16:00 CET).
    Typiska kandidater:
    - Nyligen tillagda bevakningar/portföljinnehav vars data ännu ej hämtats
    - Tickers som misslyckades i senaste veckoscan p.g.a. API-timeout/rate-limit
    - Avnoterade tickers (dessa ger tom data och bör kännas igen)

    Returns:
        Antal tickers som uppdaterades.
    """
    logger.info(f"\n{'='*50}")
    logger.info("🔄 Refresh missing data – letar efter tickers med saknad data...")
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
    start_time = time.time()
    date_str = date.today().strftime("%Y-%m-%d")
    day_name = datetime.now().strftime("%A")

    # Städa gamla rapporter (en gång per körning är OK – snabbt)
    _cleanup_old_reports(max_days=60)

    logger.info(f"\n{'='*50}")
    logger.info(f"🚀 MarketScan Pipeline – mode={mode} – {date_str}")
    logger.info(f"{'='*50}\n")

    # ── Snabblägen som inte behöver hela pipeline-flödet ──────────────────
    if mode == "targeted":
        tickers_env = os.environ.get("TARGET_TICKERS", "")
        tickers_list = [t.strip().upper() for t in tickers_env.split(",") if t.strip()]
        if not tickers_list:
            logger.warning("  ⚠ TARGET_TICKERS env var är tom – avbryter targeted-körning")
            return
        logger.info(f"  🎯 Targeted refresh: {', '.join(tickers_list)}")
        run_targeted(tickers_list)
        return

    if mode == "refresh_missing":
        run_refresh_missing()
        return

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

        # ── Synka portfolio & bevakningslista till custom_universe FÖR SCAN ──
        # Viktigt att detta sker INNAN all_tickers byggs, annars saknas
        # nyligen tillagda tickers i denna scan (de hade annars dykt upp
        # först i nästa veckas scan).
        _pre_scan_sync_universe()

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

            # Använd sektor-neutraliserad scoring för att undvika strukturell bias
            # där tech-bolag systematiskt överrankas och värdebolag underrankas.
            # Varje faktor score beräknas INOM sektor (t.ex. P/E för tech vs fastighet).
            use_sector_neutral = getattr(config, "SCORE_MODE", "") == "sector_neutral"
            if use_sector_neutral:
                try:
                    from core.scoring import score_universe_sector_neutralized
                    scored = score_universe_sector_neutralized(raw_df)
                    logger.info(f"  ✅ Scorat {len(scored)} tickers (sektorneutralt)")
                except Exception as _sne:
                    logger.warning(f"  ⚠ Sektorneutral scoring misslyckades: {_sne} – fallback till absolut")
                    scored = score_universe(raw_df, regime=regime)
            else:
                scored = score_universe(raw_df, regime=regime)
                logger.info(f"  ✅ Scorat {len(scored)} tickers")

            # Piotroski F-Score (fundamental quality 0–9)
            try:
                from core import piotroski as _piotroski
                scored = _piotroski.add_piotroski_to_universe(scored, verbose=True)
                logger.info(f"  ✅ Piotroski beräknat")
            except Exception as _pe:
                logger.warning(f"  ⚠ Piotroski misslyckades: {_pe}")

            # Entry-signal, trend-signal, confidence-label
            try:
                from core import filters as _filters
                scored = _filters.apply_all_filters(scored, verbose=True)
                logger.info(f"  ✅ Filter/signaler applicerade: {len(scored)} tickers")
            except Exception as _fe:
                logger.warning(f"  ⚠ apply_all_filters misslyckades: {_fe}")

            csv_path = REPORT_DIR / f"scored_universe_{date_str}"
            _save_scored(scored, csv_path)
        else:
            logger.warning("  ⚠ Universe fetch returnerade tom DataFrame – laddar senaste cache")
            scored = _load_latest_scored("scored_universe_*.parquet")

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
                
                # Spara den uppdaterade parquet + csv
                csv_path = REPORT_DIR / f"scored_universe_{date_str}"
                _save_scored(scored, csv_path)
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
                    csv_path = REPORT_DIR / f"scored_universe_{date_str}"
                else:
                    csv_path = REPORT_DIR / f"smallcap_scored_{date_str}"
                _save_scored(scored, csv_path)
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

    # ═══════════════════════════════════════════════════════════════════════
    # 1e. KLASSISK PAPER TRADING (score-baserad, körs för weekly + smallcap)
    # ═══════════════════════════════════════════════════════════════════════
    if mode in ("weekly", "smallcap") and not scored.empty:
        try:
            from portfolio.paper_trading import record_weekly_picks
            pt_universe = "smallcap" if mode == "smallcap" else "universe"
            n_pt = len(record_weekly_picks(scored, top_n=10, universe=pt_universe, verbose=False))
            if n_pt:
                logger.info(f"  📊 Klassisk paper trading: {n_pt} positioner registrerade ({pt_universe})")
        except Exception as e:
            logger.warning(f"  ⚠ Klassisk paper trading hoppades över: {e}")

    # Portfölj & watchlist
    holdings = _load_portfolio()
    watchlist_raw = _load_watchlist()
    watchlist_tickers = [i.get("ticker", "") for i in watchlist_raw if i.get("ticker")]

    # Synka portföljinnehav till custom_universe så de ingår i veckoscannen
    try:
        custom_existing = set(c["ticker"] for c in config.load_custom_universe())
        universe_tickers_set = set(getattr(config, "UNIVERSE", []))
        added = 0
        for _, h in holdings.iterrows():
            t = str(h.get("ticker", "")).upper().strip()
            if not t:
                continue
            # Kolla om tickern redan finns i UNIVERSE eller custom
            if t in universe_tickers_set or t in custom_existing:
                continue
            # Kolla med suffix för svenska/nordiska aktier
            in_main = any(t + sfx in universe_tickers_set for sfx in (".ST", ".HE", ".CO", ".OL"))
            if in_main:
                continue
            in_custom = any(t + sfx in custom_existing for sfx in (".ST", ".HE", ".CO", ".OL"))
            if in_custom:
                continue
            # Lägg till med full ticker (om den redan har suffix) eller utan
            config.add_custom_to_universe(t, str(h.get("name", "")))
            added += 1
        if added:
            logger.info(f"  ➕ Lade till {added} portföljinnehav i custom_universe för veckoscannen")
    except Exception as e:
        logger.warning(f"  ⚠ Kunde inte synka portfölj till custom_universe: {e}")

    # Synka även bevakningar till custom_universe
    try:
        custom_existing_wl = set(c["ticker"] for c in config.load_custom_universe())
        universe_tickers_set_wl = set(getattr(config, "UNIVERSE", []))
        added_wl = 0
        for w in watchlist_tickers:
            if not w:
                continue
            w_up = w.upper().strip()
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
            logger.info(f"  ➕ Lade till {added_wl} bevakningar i custom_universe för veckoscannen")
    except Exception as e:
        logger.warning(f"  ⚠ Kunde inte synka bevakningar till custom_universe: {e}")

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
            # Slå upp data för bevakningar från scored universe
            watchlist_with_data = []
            if not scored.empty and "ticker" in scored.columns:
                for w in watchlist_tickers[:8]:
                    w_up = w.upper().strip()
                    match = scored[scored["ticker"] == w_up]
                    if not match.empty:
                        r = match.iloc[0]
                        sc = r.get("score_total")
                        entry = r.get("entry_signal", "—")
                        trend = r.get("trend_signal", "—")
                        rsi = r.get("rsi_14")
                        price = r.get("current_price") or r.get("close", 0)
                        watchlist_with_data.append(f"- **{flag_for_ticker(w_up)} {w_up}** – Score {sc:.0f} | {entry} | Trend: {trend} | RSI {rsi:.0f}" if sc and sc == sc else f"- **{w_up}** – (ingen score)")
                    else:
                        watchlist_with_data.append(f"- **{w_up}** – (inte i universet)")
            else:
                for w in watchlist_tickers[:5]:
                    watchlist_with_data.append(f"- {w}")
            report_lines.extend(watchlist_with_data)
            report_lines.append("")

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
            # Filtrera bort okända/tomma sektorer och NaN-snitt innan loopen
            sec = scored.groupby("sector")["score_total"].mean().sort_values(ascending=False)
            _skip_sectors = {"Unknown", "unknown", ""}
            for sector, avg in sec.items():
                # Hoppa över tomma sektornamn, "Unknown" och sektorer där avg är NaN
                if not sector or str(sector).strip() in _skip_sectors or pd.isna(avg):
                    continue
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

    elif mode == "smallcap":
        # ── Rubrik ────────────────────────────────────────────────────────
        report_lines.append(f"# 🏦 MarketScan Småbolag – {date_str}\n")
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
                pnl = f"{h['pnl_pct']:+.1f}%" if h['pnl_pct'] is not None else "—"
                score_str = f"{h['score']:.0f}" if h.get('score') is not None else "—"
                entry_str = h.get('entry') or '—'
                report_lines.append(f"- {emoji} **{flag_for_ticker(h['ticker'])} {h['ticker']}** – {pnl} | Score {score_str} | {entry_str}")
        else:
            report_lines.append("*(Inga innehav i portföljen)*")
        report_lines.append("")

        # ── Topp-10 ──────────────────────────────────────────────────────
        if top_10:
            report_lines.append(_section_header("🏆 Topp-10 småbolag"))
            for i, t in enumerate(top_10[:10], 1):
                report_lines.append(f"  {i}. **{flag_for_ticker(t['ticker'])} {t['ticker']}** – Score {t['score']:.0f} | {t['entry']} | {t['sector']}")

        # ── Bottom varningar ──────────────────────────────────────────────
        if bottom_5:
            report_lines.append(_section_header("🔴 Varningar"))
            for b in bottom_5[:5]:
                report_lines.append(f"- **{flag_for_ticker(b['ticker'])} {b['ticker']}** – Score {b['score']:.0f} | {b['entry']} | {b['sector']}")

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
        # Build set of tickers worth fetching news for – keep small to avoid rate limits
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
            logger.info(f"  📰 Hämtade nyheter för {len(news_blocks)} tickers (AI-kontext)")
    except Exception as e:
        logger.warning(f"  ⚠ Kunde inte hämta nyheter för AI: {e}")

    ai_section = ""
    try:
        logger.info("  🤖 Anropar AI...")
        provider = os.getenv("AI_PROVIDER", "auto") or "auto"

        def _add_news(base_ctx: str) -> str:
            """Append fetched news to the context using the separator ai_chat understands."""
            if pipeline_news_text:
                return base_ctx + "\n\nFärska nyheter:\n" + pipeline_news_text
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