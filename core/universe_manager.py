"""
universe_manager.py — Automatisk skötsel av ticker-universums
=============================================================
Ansvarar för att:
  1. Lägga till nya aktier (från universe_discovery.py) i rätt kategori i universe.json
  2. Ta bort aktier som konsekvent presterar dåligt (låg score + låg likviditet)
  3. Spåra alla förslag + beslut i data/discovery_candidates.json
  4. Committa ändringar till GitHub (via befintlig commit-infrastruktur)

Användning:
    from core.universe_manager import run_full_maintenance, get_pending_candidates
    result = run_full_maintenance(auto_add_threshold=0.75, dry_run=False)
"""

import json
import logging
import os
import subprocess
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

ROOT     = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
REPORT_DIR = ROOT / "reports"
UNIVERSE_FILE    = DATA_DIR / "universe.json"
BLACKLIST_FILE   = DATA_DIR / "blacklist.json"
CANDIDATES_FILE  = DATA_DIR / "discovery_candidates.json"

# Tickers som aldrig tas bort automatiskt
NEVER_REMOVE = {
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "JPM", "JNJ",
    "BRK-B", "V", "MA", "UNH", "HD", "PG", "AAPL", "CSCO", "AVGO",
    "VOLVO-B.ST", "SAND.ST", "ERIC-B.ST", "ABB.ST", "SEB-A.ST", "SHB-A.ST",
}

# Kategori-mappning baserat på ticker-suffix
_SUFFIX_CATEGORY = {
    ".ST":  "OMX_SE",
    ".CO":  "NORDIC",
    ".OL":  "NORDIC",
    ".HE":  "NORDIC",
    ".L":   "UK",
    ".DE":  "GERMANY",
    ".PA":  "EUROPE",
    ".AS":  "EUROPE",
    ".MI":  "EUROPE",
    ".MC":  "EUROPE",
    ".VI":  "EUROPE",
    ".WA":  "EUROPE",
    ".LS":  "EUROPE",
    ".SW":  "EUROPE",
    ".TO":  "CANADA",
    ".AX":  "ASIA_PACIFIC",
    ".T":   "ASIA_PACIFIC",
    ".HK":  "ASIA_PACIFIC",
    ".TW":  "ASIA_PACIFIC",
    ".KS":  "ASIA_PACIFIC",
    ".NS":  "ASIA_PACIFIC",
    ".BO":  "ASIA_PACIFIC",
    ".SI":  "ASIA_PACIFIC",
    ".SA":  "BRAZIL",
    ".MX":  "BRAZIL",
}


# ── Hjälpfunktioner ─────────────────────────────────────────────────────────

def _guess_category(ticker: str) -> str:
    """Gissar universe.json-kategori baserat på börs-suffix."""
    t = ticker.upper()
    for suffix, cat in _SUFFIX_CATEGORY.items():
        if t.endswith(suffix):
            return cat
    return "US_LARGE_CAP"


def load_universe() -> dict:
    """Laddar universe.json. Returnerar {} vid fel."""
    try:
        return json.loads(UNIVERSE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_universe(data: dict) -> bool:
    """Sparar universe.json atomärt."""
    try:
        tmp = UNIVERSE_FILE.with_suffix(".tmp.json")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.rename(UNIVERSE_FILE)
        return True
    except Exception as e:
        logger.error(f"  Kunde inte spara universe.json: {e}")
        return False


def get_all_universe_tickers() -> set[str]:
    """Returnerar alla tickers i universe.json som ett set (inkl. smallcap)."""
    data = load_universe()
    tickers: set[str] = set()
    for cat, val in data.items():
        if isinstance(val, dict):
            if "tickers" in val:
                tickers.update(t.upper() for t in val["tickers"])
            if "markets" in val:
                for mkt_tickers in val["markets"].values():
                    tickers.update(t.upper() for t in mkt_tickers)
    return tickers


def load_candidates() -> dict:
    """Laddar data/discovery_candidates.json."""
    if CANDIDATES_FILE.exists():
        try:
            return json.loads(CANDIDATES_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "version":      1,
        "last_updated": None,
        "candidates":   [],
        "auto_added":   [],
        "auto_removed": [],
        "rejected":     [],
    }


def save_candidates(data: dict) -> bool:
    """Sparar data/discovery_candidates.json."""
    data["last_updated"] = date.today().isoformat()
    try:
        CANDIDATES_FILE.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8",
        )
        return True
    except Exception as e:
        logger.error(f"  Kunde inte spara discovery_candidates.json: {e}")
        return False


# ── Lägga till tickers ───────────────────────────────────────────────────────

def add_ticker_to_universe(
    ticker: str,
    reason: str,
    category: Optional[str] = None,
    source: str = "manual",
    dry_run: bool = False,
) -> bool:
    """
    Lägger till en ticker i rätt kategori i universe.json.

    Args:
        ticker:   Tickersymbolen (t.ex. "NVDA" eller "VOLVO-B.ST").
        reason:   Varför den läggs till.
        category: Kategori i universe.json. Auto-detekteras om None.
        source:   Varifrån förslaget kom.
        dry_run:  Om True, simulerar utan att skriva till fil.

    Returns:
        True om tickern lades till (eller redan fanns), False vid fel.
    """
    ticker = ticker.upper().strip()
    if not ticker:
        return False

    # Kontrollera att tickern inte redan finns
    existing = get_all_universe_tickers()
    if ticker in existing:
        logger.debug(f"  {ticker} finns redan i universums")
        return True

    if category is None:
        category = _guess_category(ticker)

    data = load_universe()
    if category not in data:
        logger.warning(f"  Kategori {category} finns inte i universe.json — använder US_LARGE_CAP")
        category = "US_LARGE_CAP"

    cat_data = data[category]
    if "tickers" not in cat_data:
        logger.error(f"  Kategorin {category} har ingen 'tickers'-lista")
        return False

    if dry_run:
        logger.info(f"  [DRY RUN] Skulle lägga till {ticker} i {category}")
        return True

    if ticker not in [t.upper() for t in cat_data["tickers"]]:
        cat_data["tickers"].append(ticker)
        data[category] = cat_data

        if not save_universe(data):
            return False

        # Logga i candidates-fil
        cands = load_candidates()
        cands["auto_added"].append({
            "ticker":  ticker,
            "reason":  reason,
            "source":  source,
            "category": category,
            "added":   date.today().isoformat(),
        })
        save_candidates(cands)

        logger.info(f"  ✅ {ticker} tillagd i {category}: {reason[:60]}")
    return True


# ── Ta bort tickers ──────────────────────────────────────────────────────────

def remove_ticker_from_universe(
    ticker: str,
    reason: str,
    dry_run: bool = False,
) -> bool:
    """
    Tar bort en ticker från universe.json och lägger den i blacklist.

    Args:
        ticker:  Tickersymbolen.
        reason:  Varför den tas bort.
        dry_run: Om True, simulerar utan att skriva.

    Returns:
        True om tickern togs bort, False om den inte hittades eller är skyddad.
    """
    ticker = ticker.upper().strip()
    if ticker in NEVER_REMOVE:
        logger.info(f"  {ticker} är skyddad — hoppar bort-tagning")
        return False

    data  = load_universe()
    found = False
    for cat, val in data.items():
        if isinstance(val, dict) and "tickers" in val:
            lst = val["tickers"]
            if ticker in [t.upper() for t in lst]:
                if dry_run:
                    logger.info(f"  [DRY RUN] Skulle ta bort {ticker} från {cat}")
                else:
                    val["tickers"] = [t for t in lst if t.upper() != ticker]
                    found = True
                break

    if not found:
        return False

    if dry_run:
        return True

    if not save_universe(data):
        return False

    # Lägg till i blacklist
    try:
        bl: dict = {}
        if BLACKLIST_FILE.exists():
            bl = json.loads(BLACKLIST_FILE.read_text(encoding="utf-8"))
        bl[ticker] = {"reason": reason, "date": date.today().isoformat(), "auto": True}
        BLACKLIST_FILE.write_text(json.dumps(bl, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        logger.warning(f"  Kunde inte uppdatera blacklist: {e}")

    # Logga i candidates-fil
    cands = load_candidates()
    cands["auto_removed"].append({
        "ticker":  ticker,
        "reason":  reason,
        "removed": date.today().isoformat(),
    })
    save_candidates(cands)

    logger.info(f"  🗑  {ticker} borttagen: {reason[:60]}")
    return True


# ── Hitta borttagningskandidater ─────────────────────────────────────────────

def get_removal_candidates(
    min_score_threshold: float = 20.0,
    min_consecutive_poor: int   = 4,
    market_cap_min_usd:   float = 20_000_000,
) -> list[dict]:
    """
    Analyserar senaste scored_universe-rapporten och hittar tickers som:
    - Har score_total < min_score_threshold
    - Har låg data_quality
    - Har market_cap < market_cap_min_usd (om tillgänglig)
    - Är redan på strike-listan (≥2 strikes)

    Returnerar lista av dikt med ticker, reason, score, data.
    """
    removal_candidates: list[dict] = []

    # Ladda senaste scored_universe
    parquets = sorted(REPORT_DIR.glob("scored_universe_*.parquet"), reverse=True)
    df = None
    if parquets:
        try:
            df = pd.read_parquet(parquets[0])
        except Exception:
            pass
    if df is None:
        csvs = sorted(REPORT_DIR.glob("scored_universe_*.csv"), reverse=True)
        if csvs:
            try:
                df = pd.read_csv(csvs[0])
            except Exception:
                pass
    if df is None or df.empty:
        return []

    existing = get_all_universe_tickers()

    # Läs strike-lista
    strike_file = DATA_DIR / "strike_list.json"
    strikes: dict = {}
    if strike_file.exists():
        try:
            strikes = json.loads(strike_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    score_col = next((c for c in ["score_total", "sc_total"] if c in df.columns), None)
    if not score_col:
        return []

    for _, row in df.iterrows():
        ticker = str(row.get("ticker", "")).upper()
        if not ticker or ticker in NEVER_REMOVE or ticker not in existing:
            continue

        score = row.get(score_col)
        if not isinstance(score, float) or pd.isna(score):
            continue

        reasons: list[str] = []

        # Låg score
        if score < min_score_threshold:
            reasons.append(f"score_total={score:.1f} < {min_score_threshold}")

        # Låg market cap (om tillgänglig och > 0)
        mc = row.get("market_cap")
        if isinstance(mc, (int, float)) and mc > 0 and mc < market_cap_min_usd:
            reasons.append(f"market_cap=${mc/1e6:.1f}M < ${market_cap_min_usd/1e6:.0f}M")

        # Strike-system
        strike_info = strikes.get(ticker)
        if strike_info and isinstance(strike_info, dict):
            strike_count = strike_info.get("count", 0)
            if strike_count >= 2:
                reasons.append(f"{strike_count} strikes i strike_list.json")

        if reasons:
            removal_candidates.append({
                "ticker":   ticker,
                "reason":   "; ".join(reasons),
                "score":    round(score, 1),
                "market_cap": int(mc) if isinstance(mc, (int, float)) and not pd.isna(mc) else None,
                "sector":   str(row.get("sector", "")),
                "entry":    str(row.get("entry_signal", "")),
            })

    removal_candidates.sort(key=lambda x: x["score"])
    return removal_candidates


# ── Hantera kandidat-pipeline ─────────────────────────────────────────────────

def add_discovery_candidates(candidates: list) -> int:
    """
    Lägger till nya kandidater i discovery_candidates.json (status=pending).
    Tickers som redan finns i pending/approved/rejected hoppas över.
    Returnerar antal nyligen tillagda.
    """
    cands = load_candidates()
    known_tickers = {
        c["ticker"]
        for c in (cands["candidates"] + cands["auto_added"] + cands["rejected"])
    }
    known_universe = get_all_universe_tickers()

    new_count = 0
    for c in candidates:
        t = c["ticker"]
        if t in known_tickers or t in known_universe:
            continue
        c["status"] = "pending"
        cands["candidates"].append(c)
        known_tickers.add(t)
        new_count += 1

    if new_count:
        save_candidates(cands)
        logger.info(f"  {new_count} nya kandidater sparade som 'pending'")
    return new_count


def approve_candidate(ticker: str, add_to_universe: bool = True) -> bool:
    """Godkänner en pending-kandidat och lägger ev. till i universe.json."""
    ticker = ticker.upper()
    cands = load_candidates()
    for c in cands["candidates"]:
        if c["ticker"] == ticker and c.get("status") == "pending":
            c["status"] = "approved"
            c["approved_date"] = date.today().isoformat()
            save_candidates(cands)
            if add_to_universe:
                return add_ticker_to_universe(
                    ticker,
                    reason=c.get("reason", "godkänd manuellt"),
                    source=c.get("source", "manual"),
                )
            return True
    return False


def reject_candidate(ticker: str, reason: str = "manuellt avvisad") -> bool:
    """Avvisar en pending-kandidat så den inte föreslås igen."""
    ticker = ticker.upper()
    cands = load_candidates()
    for c in cands["candidates"]:
        if c["ticker"] == ticker and c.get("status") == "pending":
            c["status"] = "rejected"
            c["reject_reason"] = reason
            c["rejected_date"] = date.today().isoformat()
            save_candidates(cands)
            cands["rejected"].append({"ticker": ticker, "reason": reason, "date": date.today().isoformat()})
            save_candidates(cands)
            return True
    return False


def get_pending_candidates() -> list:
    """Returnerar alla kandidater med status 'pending'."""
    return [c for c in load_candidates()["candidates"] if c.get("status") == "pending"]


# ── GitHub-commit ─────────────────────────────────────────────────────────────

def _github_commit_changes(files: list[str], message: str) -> bool:
    """Committar och pushar ändringar via git (kräver GITHUB_TOKEN i CI)."""
    try:
        token = os.getenv("GITHUB_TOKEN", "")
        if not token:
            logger.warning("  Ingen GITHUB_TOKEN – hoppar commit")
            return False
        for f in files:
            subprocess.run(["git", "add", f], cwd=ROOT, check=False, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", message, "--allow-empty"],
            cwd=ROOT, check=False, capture_output=True,
        )
        subprocess.run(
            ["git", "pull", "--rebase", "--autostash"],
            cwd=ROOT, check=False, capture_output=True,
        )
        result = subprocess.run(
            ["git", "push"],
            cwd=ROOT, check=False, capture_output=True,
        )
        return result.returncode == 0
    except Exception as e:
        logger.warning(f"  Git-commit misslyckades: {e}")
        return False


# ── Fullständigt underhållskörning ────────────────────────────────────────────

def run_full_maintenance(
    sources: Optional[list[str]] = None,
    auto_add_threshold: float = 0.80,
    auto_remove: bool = False,
    dry_run: bool = True,
    commit: bool = False,
    ai_provider: str = "auto",
    verbose: bool = True,
) -> dict:
    """
    Kör fullständigt universe-underhåll:
      1. Discovery (alla källor)
      2. Validering mot yfinance
      3. Kandidater sparas som 'pending'
      4. Auto-lägg till om confidence ≥ auto_add_threshold (default: av)
      5. Hitta borttagningskandidater
      6. Auto-ta bort om auto_remove=True (default: av)
      7. Optionellt committa till GitHub

    Args:
        sources:             Sources att köra. Default: alla.
        auto_add_threshold:  Confidence-nivå för automatisk tilläggning (0.0-1.0).
                             Sätt till 1.1 för att stänga av auto-add helt.
        auto_remove:         Om True, ta automatiskt bort borttagningskandidater.
        dry_run:             Simulera utan att skriva (åsidosätter auto_add/auto_remove).
        commit:              Committa universe.json + candidates.json till GitHub.
        ai_provider:         AI-provider för AI-källan.
        verbose:             Logga framsteg.

    Returns:
        Dikt med statistik och resultat.
    """
    from core.universe_discovery import run_discovery

    logger.info("\n" + "="*55)
    logger.info("🔍 Universe Discovery & Maintenance")
    logger.info("="*55)

    existing_universe = get_all_universe_tickers()
    logger.info(f"  Nuvarande universum: {len(existing_universe)} tickers")

    # ── Steg 1: Discovery ─────────────────────────────────────────────────
    logger.info("\n[1/4] Kör discovery...")
    candidates = run_discovery(
        sources=sources,
        validate=True,
        existing_universe=existing_universe,
        ai_provider=ai_provider,
        verbose=verbose,
    )
    logger.info(f"  {len(candidates)} validerade kandidater funna")

    # ── Steg 2: Spara som pending ─────────────────────────────────────────
    logger.info("\n[2/4] Sparar kandidater...")
    n_new = add_discovery_candidates(candidates)

    # ── Steg 3: Auto-add (om threshold + HIGH quality tier uppfylls) ─────────
    auto_added: list[str] = []
    logger.info(
        "\n[3/4] Kontrollerar auto-add "
        f"(threshold={auto_add_threshold:.0%}, kräver quality_tier=HIGH)..."
    )
    for c in candidates:
        conf = c.get("confidence", 0)
        tier = c.get("quality_tier", "MEDIUM")
        # Kräv: HIGH tier + confidence ≥ threshold (SPEC tillåts aldrig)
        if conf < auto_add_threshold or tier != "HIGH":
            continue
        fraud = c.get("fraud_flags", [])
        if fraud:
            logger.info(f"  Hoppar {c['ticker']} — fraud_flags: {fraud[:1]}")
            continue
        if dry_run:
            logger.info(
                f"  [DRY RUN] Skulle auto-lägga till {c['ticker']} "
                f"(conf={conf:.2f}, tier={tier})"
            )
            auto_added.append(c["ticker"])
        else:
            if add_ticker_to_universe(
                c["ticker"],
                reason=c.get("reason", ""),
                source=c.get("source", "discovery"),
                category=None,
                dry_run=False,
            ):
                auto_added.append(c["ticker"])

    # ── Steg 4: Borttagningskandidater ────────────────────────────────────
    logger.info("\n[4/4] Analyserar borttagningskandidater...")
    removal_cands = get_removal_candidates()
    auto_removed: list[str] = []
    if removal_cands:
        logger.info(f"  {len(removal_cands)} tickers med låg score/kvalitet:")
        for r in removal_cands[:10]:
            logger.info(f"    {r['ticker']:12s} score={r['score']:.1f}  {r['reason'][:60]}")
    if auto_remove and not dry_run:
        for r in removal_cands:
            if remove_ticker_from_universe(r["ticker"], r["reason"]):
                auto_removed.append(r["ticker"])
    elif dry_run and auto_remove:
        for r in removal_cands[:5]:
            logger.info(f"  [DRY RUN] Skulle ta bort {r['ticker']}: {r['reason']}")

    # ── Commit ─────────────────────────────────────────────────────────────
    committed = False
    if commit and not dry_run and (auto_added or auto_removed):
        n_add = len(auto_added)
        n_rem = len(auto_removed)
        msg = f"Universe: +{n_add} tickers, -{n_rem} tickers ({date.today().isoformat()})"
        committed = _github_commit_changes(
            [str(UNIVERSE_FILE), str(CANDIDATES_FILE), str(BLACKLIST_FILE)],
            msg,
        )

    result = {
        "candidates_found":   len(candidates),
        "candidates_new":     n_new,
        "auto_added":         auto_added,
        "auto_removed":       auto_removed,
        "removal_candidates": removal_cands,
        "committed":          committed,
        "dry_run":            dry_run,
        "timestamp":          datetime.now().isoformat(timespec="seconds"),
    }

    logger.info("\n" + "="*55)
    logger.info(f"✅ Underhåll klart!")
    logger.info(f"   Kandidater funna:  {len(candidates)}")
    logger.info(f"   Nya pending:       {n_new}")
    logger.info(f"   Auto-tillagda:     {len(auto_added)}")
    logger.info(f"   Borttagn.kand.:    {len(removal_cands)}")
    logger.info("="*55)

    return result
