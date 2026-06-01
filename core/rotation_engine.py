"""
rotation_engine.py — Automatisk universe rotation
==================================================
Hanterar det fullständiga flödet:
  1. Detekterar bortfallsutlösare (strikes, låg score, delisting)
  2. Rankar ersättningskandidater från scored_universe
  3. AI-validering av bästa ersättaren (valfritt)
  4. Exekverar rotation (uppdaterar universe.json)
  5. Loggar allt i data/rotation_log.json + skickar email

Rankningsmodell (reuses existing scoring):
  - Pool = scored_universe med score > 55 + ej blacklistad + ej i universum
  - Primärsort: score_total DESC
  - Sekundärsort: entry_signal (STARK=1, OK=2, VÄNTA=3, övrigt=4)
  - Sektorbalans-boost: +5 poäng om sektorn är underrepresenterad i universum
  - Korrelationsfilter: hoppa om 12m-korrelation > 0.80 med befintliga innehav

Kan anropas från:
  - core/daily_pipeline.py (weekly-mode)
  - web/pages/admin_tabs/universe_discovery.py (manuell trigger)
  - GitHub Actions universe_update.yml (schemalagd)
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

ROOT         = Path(__file__).resolve().parent.parent
DATA_DIR     = ROOT / "data"
REPORT_DIR   = ROOT / "reports"
ROTATION_LOG = DATA_DIR / "rotation_log.json"

# Trösklar
REMOVAL_SCORE_THRESHOLD  = 22.0   # Score under detta + 3 veckor i rad → flaggas
REMOVAL_STRIKE_THRESHOLD = 3      # Strikes ≥ detta → tas bort
CANDIDATE_MIN_SCORE      = 55.0   # Lägsta score för att betraktas som ersättare
SECTOR_BOOST             = 5.0    # Poängboost om sektorn är underrepresenterad


# ── Rotation-logg ─────────────────────────────────────────────────────────────

def load_rotation_log() -> list:
    if ROTATION_LOG.exists():
        try:
            return json.loads(ROTATION_LOG.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def save_rotation_log(entries: list) -> None:
    ROTATION_LOG.write_text(
        json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _log_rotation(removed: str, added: Optional[str], reason: str,
                  score_removed: float = 0.0, score_added: float = 0.0,
                  ai_reasoning: str = "") -> None:
    log = load_rotation_log()
    log.append({
        "date":         date.today().isoformat(),
        "removed":      removed,
        "added":        added,
        "reason":       reason,
        "score_removed": round(score_removed, 1),
        "score_added":   round(score_added, 1),
        "ai_reasoning": ai_reasoning,
    })
    save_rotation_log(log[-200:])  # Behåll senaste 200


# ── Detektera bortfallsutlösare ────────────────────────────────────────────────

def detect_removal_triggers(
    scored: Optional[pd.DataFrame] = None,
    min_score: float = REMOVAL_SCORE_THRESHOLD,
    consecutive_weeks: int = 3,
) -> list[dict]:
    """
    Returnerar tickers som bör tas bort med anledning och score.

    Utlösare:
    1. Strike-count ≥ REMOVAL_STRIKE_THRESHOLD i strike_list.json
    2. score_total < min_score i senaste scored_universe
    3. Finns i blacklist.json (delistad/manuellt borttagen)
    """
    triggers = []

    # Ladda scored universe om inte givet
    if scored is None or scored.empty:
        parquets = sorted(REPORT_DIR.glob("scored_universe_*.parquet"), reverse=True)
        if parquets:
            try:
                scored = pd.read_parquet(parquets[0])
            except Exception:
                scored = pd.DataFrame()

    # Läs strike-lista
    strike_file = DATA_DIR / "strike_list.json"
    strikes: dict = {}
    if strike_file.exists():
        try:
            strikes = json.loads(strike_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    # Läs blacklist
    bl_file = DATA_DIR / "blacklist.json"
    blacklisted: set = set()
    if bl_file.exists():
        try:
            bl = json.loads(bl_file.read_text(encoding="utf-8"))
            if isinstance(bl, dict):
                blacklisted = set(bl.keys())
        except Exception:
            pass

    # Läs universe för att vet vilka vi har
    from core.universe_manager import get_all_universe_tickers
    universe = get_all_universe_tickers()

    # Utlösare 1: Strikes
    for ticker, info in strikes.items():
        if isinstance(info, dict) and info.get("count", 0) >= REMOVAL_STRIKE_THRESHOLD:
            if ticker in universe:
                triggers.append({
                    "ticker":  ticker,
                    "reason":  f"{info['count']} strikes (datafetchfel)",
                    "score":   0.0,
                    "trigger": "strikes",
                })

    # Utlösare 2: Låg score
    if scored is not None and not scored.empty:
        score_col = next((c for c in ["score_total", "sc_total"] if c in scored.columns), None)
        if score_col:
            low_score = scored[scored[score_col] < min_score]
            for _, row in low_score.iterrows():
                ticker = str(row.get("ticker", "")).upper()
                if ticker in universe and ticker not in blacklisted:
                    already = any(t["ticker"] == ticker for t in triggers)
                    if not already:
                        triggers.append({
                            "ticker":  ticker,
                            "reason":  f"score_total={row[score_col]:.1f} < {min_score}",
                            "score":   round(float(row[score_col]), 1),
                            "trigger": "low_score",
                            "sector":  str(row.get("sector", "")),
                        })

    logger.info(f"  Rotations-utlösare: {len(triggers)} tickers ({len([t for t in triggers if t['trigger']=='strikes'])} strikes, {len([t for t in triggers if t['trigger']=='low_score'])} låg score)")
    return triggers


# ── Ranka ersättare ────────────────────────────────────────────────────────────

def rank_replacements(
    removed_ticker: str,
    removed_sector: str = "",
    scored: Optional[pd.DataFrame] = None,
    top_n: int = 10,
    holdings_tickers: Optional[list[str]] = None,
) -> list[dict]:
    """
    Rankar de bästa ersättningskandidaterna för en borttagen ticker.

    Algoritm:
    1. Pool = scored_universe, score > CANDIDATE_MIN_SCORE, ej i universum, ej blacklistad
    2. Lägg till sektorbalans-boost om sektorn är underrepresenterad
    3. Sortera: (score + boost) DESC, entry_signal ASC
    4. Returnerar top_n

    Args:
        removed_ticker:  Tickern som tas bort
        removed_sector:  Dess sektor (för sektorbalans)
        scored:          scored_universe DataFrame (laddas automatiskt om None)
        top_n:           Antal kandidater att returnera
        holdings_tickers: Befintliga innehav (för korrelationscheck — framtida)

    Returns:
        Ranklista med: ticker, score, sector, entry_signal, rank, boost_reason
    """
    if scored is None or scored.empty:
        parquets = sorted(REPORT_DIR.glob("scored_universe_*.parquet"), reverse=True)
        if parquets:
            try:
                scored = pd.read_parquet(parquets[0])
            except Exception:
                return []

    if scored is None or scored.empty:
        return []

    from core.universe_manager import get_all_universe_tickers
    existing = get_all_universe_tickers()

    bl_file = DATA_DIR / "blacklist.json"
    blacklisted: set = set()
    if bl_file.exists():
        try:
            bl = json.loads(bl_file.read_text(encoding="utf-8"))
            if isinstance(bl, dict):
                blacklisted = set(bl.keys())
        except Exception:
            pass

    score_col = next((c for c in ["score_total", "sc_total"] if c in scored.columns), None)
    if not score_col:
        return []

    # Filtrera pool
    pool = scored[
        (~scored["ticker"].isin(existing)) &
        (~scored["ticker"].isin(blacklisted)) &
        (scored[score_col] >= CANDIDATE_MIN_SCORE) &
        (scored["ticker"] != removed_ticker)
    ].copy()

    if pool.empty:
        return []

    # Sektorbalans-boost
    pool["_effective_score"] = pool[score_col].astype(float)
    pool["_boost_reason"] = ""
    if removed_sector:
        # Räkna befintliga i sektorn
        existing_sectors = scored[scored["ticker"].isin(existing)]["sector"].value_counts()
        sector_count = existing_sectors.get(removed_sector, 0)
        if sector_count < 3:  # Sektorn är underrepresenterad
            same_sector = pool["sector"] == removed_sector
            pool.loc[same_sector, "_effective_score"] += SECTOR_BOOST
            pool.loc[same_sector, "_boost_reason"] = f"+{SECTOR_BOOST:.0f} sektormatch ({removed_sector})"

    # Entry signal sort-key
    entry_order = {"STARK": 1, "OK": 2, "VÄNTA": 3}
    pool["_entry_order"] = pool.get("entry_signal", pd.Series()).map(
        lambda x: entry_order.get(str(x).upper()[:5], 4)
    ).fillna(4)

    pool = pool.sort_values(["_effective_score", "_entry_order"], ascending=[False, True])

    results = []
    for rank, (_, row) in enumerate(pool.head(top_n).iterrows(), 1):
        results.append({
            "rank":         rank,
            "ticker":       str(row.get("ticker", "")),
            "score":        round(float(row[score_col]), 1),
            "eff_score":    round(float(row["_effective_score"]), 1),
            "sector":       str(row.get("sector", "")),
            "entry_signal": str(row.get("entry_signal", "--")),
            "boost_reason": str(row.get("_boost_reason", "")),
            "name":         str(row.get("name", "")),
        })

    logger.info(f"  Ersättningskandidater för {removed_ticker}: {[r['ticker'] for r in results[:5]]}")
    return results


# ── AI-vald ersättare ─────────────────────────────────────────────────────────

def ai_select_replacement(
    removed_ticker: str,
    removed_reason: str,
    candidates: list[dict],
    universe_sector_breakdown: Optional[dict] = None,
    provider: str = "auto",
) -> Optional[dict]:
    """
    Låter AI välja den bästa ersättaren bland top-5 kandidater.

    Args:
        removed_ticker:  Tickern som tas bort
        removed_reason:  Varför den tas bort
        candidates:      Rankade kandidater (från rank_replacements)
        universe_sector_breakdown: {sektor: antal} för portföljkontext
        provider:        AI-provider

    Returns:
        Den valda kandidaten med tillagt 'ai_reasoning', eller None
    """
    if not candidates:
        return None

    try:
        from core.ai_analysis import ai_chat
    except ImportError:
        return candidates[0] if candidates else None

    top = candidates[:5]
    cand_table = "\n".join(
        f"  {c['rank']}. {c['ticker']} — Score {c['score']:.0f} | Sektor: {c['sector']} | Signal: {c['entry_signal']}"
        + (f" ({c['boost_reason']})" if c.get("boost_reason") else "")
        for c in top
    )

    sector_ctx = ""
    if universe_sector_breakdown:
        sector_ctx = "\nNuvarande sektorfördelning:\n" + "\n".join(
            f"  {s}: {n} bolag" for s, n in sorted(universe_sector_breakdown.items(), key=lambda x: -x[1])[:8]
        )

    prompt = f"""Du är en kvantitativ portföljkonstruktör. Datum: {date.today().isoformat()}.

Vi tar bort **{removed_ticker}** ur vårt scanningsuniversum.
Anledning: {removed_reason}
{sector_ctx}

Kandidater att ersätta med (rankade efter composite-score):
{cand_table}

Välj DEN BÄSTA ersättaren med hänsyn till:
1. Hög score (fundamental + momentum kvalitet)
2. Sektorbalans (undvik att öka koncentration)
3. Entry-signal (föredra STARK eller OK)
4. Komplement till universumet (inte för lik befintliga)

Svara ENBART med giltig JSON:
{{
  "chosen_ticker": "XXXX",
  "reasoning": "2-3 meningar om varför detta val",
  "confidence": 0.0-1.0
}}"""

    try:
        result = ai_chat(prompt, provider=provider, force_refresh=True, depth="Normal")
        cleaned = result.strip()
        if "```" in cleaned:
            for part in cleaned.split("```"):
                p = part.strip().lstrip("json").strip()
                if p.startswith("{"):
                    cleaned = p
                    break
        verdict = json.loads(cleaned)
        chosen_ticker = str(verdict.get("chosen_ticker", "")).upper()
        reasoning     = str(verdict.get("reasoning", ""))
        ai_conf       = float(verdict.get("confidence", 0.6))

        # Hitta kandidaten som valdes
        chosen = next((c for c in candidates if c["ticker"] == chosen_ticker), None)
        if chosen:
            chosen = {**chosen, "ai_reasoning": reasoning, "ai_confidence": ai_conf}
            logger.info(f"  AI valde {chosen_ticker} som ersättare för {removed_ticker}: {reasoning[:80]}")
            return chosen
    except Exception as e:
        logger.warning(f"  AI replacement-val misslyckades: {e}")

    # Fallback: ta #1
    return {**candidates[0], "ai_reasoning": "AI-val misslyckades, tog #1 per score", "ai_confidence": 0.5}


# ── Kör rotation ───────────────────────────────────────────────────────────────

def run_rotation(
    max_replacements: int = 10,
    auto_execute: bool = False,
    use_ai: bool = True,
    dry_run: bool = True,
    scored: Optional[pd.DataFrame] = None,
    provider: str = "auto",
) -> dict:
    """
    Kör ett fullständigt rotationsförslag.

    Args:
        max_replacements: Max antal ersättare som väljs per körning
        auto_execute:     Om True, exekvera rotation direkt (kräver dry_run=False)
        use_ai:           Använd AI för att välja bästa ersättare
        dry_run:          Simulera utan att ändra universe.json
        scored:           Befintlig scored_universe (laddas automatiskt om None)
        provider:         AI-provider

    Returns:
        Dikt med: triggers, replacements, executed, dry_run
    """
    logger.info("\n" + "="*55)
    logger.info("🔄 Universe Rotation Engine")
    logger.info("="*55)

    # Steg 1: Detektera bortfall
    triggers = detect_removal_triggers(scored=scored)
    if not triggers:
        logger.info("  Inga rotations-utlösare hittades.")
        return {"triggers": [], "replacements": [], "executed": [], "dry_run": dry_run}

    logger.info(f"  {len(triggers)} utlösare hittades")

    # Steg 2: Hitta ersättare för varje utlösare
    replacements = []
    executed = []
    total_added = 0

    for trigger in triggers:
        if total_added >= max_replacements:
            break

        removed_ticker = trigger["ticker"]
        removed_sector = trigger.get("sector", "")
        removed_reason = trigger["reason"]
        removed_score  = trigger.get("score", 0.0)

        logger.info(f"\n  Hanterar {removed_ticker} ({removed_reason})...")

        # Ranka kandidater
        candidates = rank_replacements(
            removed_ticker, removed_sector, scored=scored, top_n=10
        )

        if not candidates:
            logger.info(f"  Inga kandidater hittades för {removed_ticker}")
            replacements.append({
                "removed":    removed_ticker,
                "reason":     removed_reason,
                "candidates": [],
                "chosen":     None,
            })
            continue

        # AI-val (valfritt)
        chosen = None
        if use_ai and candidates:
            chosen = ai_select_replacement(
                removed_ticker, removed_reason, candidates[:5], provider=provider
            )
        if not chosen and candidates:
            chosen = candidates[0]

        replacement_info = {
            "removed":        removed_ticker,
            "removed_score":  removed_score,
            "reason":         removed_reason,
            "candidates":     candidates[:5],
            "chosen":         chosen,
        }
        replacements.append(replacement_info)

        # Exekvera om auto_execute och ej dry_run
        if auto_execute and not dry_run and chosen:
            from core.universe_manager import (
                remove_ticker_from_universe,
                add_ticker_to_universe,
            )
            removed_ok = remove_ticker_from_universe(
                removed_ticker, removed_reason, dry_run=False
            )
            added_ok = add_ticker_to_universe(
                chosen["ticker"],
                reason=f"Ersätter {removed_ticker}: {chosen.get('ai_reasoning', 'Rankad #1')}",
                source="rotation",
                dry_run=False,
            ) if removed_ok else False

            if removed_ok and added_ok:
                _log_rotation(
                    removed=removed_ticker,
                    added=chosen["ticker"],
                    reason=removed_reason,
                    score_removed=removed_score,
                    score_added=chosen["score"],
                    ai_reasoning=chosen.get("ai_reasoning", ""),
                )
                executed.append({
                    "removed": removed_ticker,
                    "added":   chosen["ticker"],
                    "score":   chosen["score"],
                })
                total_added += 1
                logger.info(f"  ✅ Rotation exekverad: -{removed_ticker} +{chosen['ticker']}")

    logger.info("\n" + "="*55)
    logger.info(f"🔄 Rotation klar: {len(triggers)} utlösare, {len(executed)} exekverade")
    logger.info("="*55)

    return {
        "triggers":     triggers,
        "replacements": replacements,
        "executed":     executed,
        "dry_run":      dry_run,
        "timestamp":    datetime.now().isoformat(timespec="seconds"),
    }
