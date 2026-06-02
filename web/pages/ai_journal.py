"""web/pages/ai_journal.py - AI Trade Journal: track AI recommendations & outcomes"""
import json
import streamlit as st
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
from web.utils import DATA_DIR

JOURNAL_FILE = DATA_DIR / "ai_trade_journal.json"


def _load_journal() -> list:
    try:
        return json.loads(JOURNAL_FILE.read_text(encoding="utf-8")) if JOURNAL_FILE.exists() else []
    except Exception:
        return []


def _save_journal(entries: list):
    JOURNAL_FILE.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(entries, ensure_ascii=False, indent=2)
    JOURNAL_FILE.write_text(content, encoding="utf-8")
    # Committa till GitHub -- Streamlit Cloud har ephemeral filsystem
    try:
        from web.pages.admin import _get_github_token, _github_commit_file
        token = _get_github_token()
        if token:
            _github_commit_file("data/ai_trade_journal.json", content, token,
                                message="Update AI trade journal via Streamlit")
    except Exception:
        pass


def log_ai_recommendation(ticker: str, recommendation: str, score_at_time: float,
                            price_at_time: float, ai_text_snippet: str = "",
                            provider: str = "", sector: str = ""):
    """Call this when an AI analysis is performed to log the recommendation."""
    entries = _load_journal()
    # Don't duplicate within same day
    today = datetime.now().date().isoformat()
    existing = [e for e in entries if e.get("ticker") == ticker and e.get("date", "").startswith(today)]
    if existing:
        return
    entries.append({
        "date": datetime.now().isoformat()[:19],
        "ticker": ticker,
        "recommendation": recommendation,
        "score_at_time": round(score_at_time, 1) if score_at_time else None,
        "price_at_time": round(price_at_time, 2) if price_at_time else None,
        "ai_snippet": ai_text_snippet[:300] if ai_text_snippet else "",
        "provider": provider or "",
        "sector": sector or "",
        "outcome_1m": None,
        "outcome_3m": None,
        "outcome_price_1m": None,
        "outcome_price_3m": None,
    })
    # Keep last 500 entries
    _save_journal(entries[-500:])


def record_ai_signal(ticker: str, action: str, confidence: float,
                     provider: str, context: dict = None):
    """Spara varje signal från AI-ensemblen.

    Args:
        ticker: Ticker-symbol
        action: Rekommendation (STARKT KÖP/KÖP/BEVAKA/UNDVIK/SÄLJ)
        confidence: Konfidens 0.0-1.0
        provider: Providernamn eller "ensemble"
        context: Dict med extra data (t.ex. price, score, sector)
    """
    context = context or {}
    entries = _load_journal()
    entries.append({
        "date": datetime.now().isoformat()[:19],
        "ticker": ticker.upper(),
        "recommendation": action,
        "confidence": round(confidence, 2),
        "provider": provider or "ensemble",
        "score_at_time": round(context.get("score", 0), 1) if context.get("score") else None,
        "price_at_time": round(context.get("price", 0), 2) if context.get("price") else None,
        "sector": context.get("sector", ""),
        "ai_snippet": context.get("snippet", "")[:300],
        "signal_type": context.get("signal_type", "analysis"),
        "outcome_1m": None,
        "outcome_3m": None,
        "outcome_price_1m": None,
        "outcome_price_3m": None,
    })
    _save_journal(entries[-1000:])


def record_ai_verification(ticker: str, action_taken: str, actual_return_30d: float):
    """Verifiera en signal efter 30 dagar.

    Uppdaterar den senaste signalen för tickern med verkligt utfall.
    Anropas när man vill verifiera att AI:ns rekommendation stämde.

    Args:
        ticker: Ticker-symbol
        action_taken: Vilken åtgärd som vidtogs (KÖP/SÄLJ/VÄNTA)
        actual_return_30d: Verklig avkastning efter 30 dagar (%)
    """
    entries = _load_journal()
    updated = False

    # Hitta senaste signalen för tickern utan utfall
    for i in range(len(entries) - 1, -1, -1):
        entry = entries[i]
        if entry.get("ticker") == ticker.upper() and entry.get("outcome_1m") is None:
            entry["outcome_1m"] = round(actual_return_30d, 2)
            entry["outcome_price_1m"] = None  # Sätts separat om vi har prisdata
            entry["action_taken"] = action_taken
            entry["verified_at"] = datetime.now().isoformat()[:19]

            # Bedöm om signalen var korrekt
            rec = entry.get("recommendation", "")
            if rec in ("STARKT KÖP", "KÖP") and actual_return_30d > 0:
                entry["was_correct"] = True
            elif rec in ("STARKT SÄLJ", "SÄLJ", "UNDVIK") and actual_return_30d < 0:
                entry["was_correct"] = True
            elif rec in ("BEVAKA", "VÄNTA", "NEUTRAL") and abs(actual_return_30d) < 3:
                entry["was_correct"] = True
            else:
                entry["was_correct"] = False

            updated = True
            break

    if updated:
        _save_journal(entries)
        return True
    return False


def get_ai_accuracy(provider: str = None, days: int = 90) -> dict:
    """Beräkna hur ofta AI:n hade rätt.

    Args:
        provider: Filtrera på specifik provider (None = alla)
        days: Antal dagar bakåt att inkludera

    Returns:
        Dict med accuracy-statistik
    """
    entries = _load_journal()
    now = datetime.now()
    cutoff = now - timedelta(days=days)

    # Filtrera
    filtered = []
    for e in entries:
        try:
            entry_date = datetime.fromisoformat(e["date"])
            if entry_date < cutoff:
                continue
            if provider and e.get("provider") != provider:
                continue
            if e.get("was_correct") is not None:
                filtered.append(e)
        except Exception:
            continue

    if not filtered:
        return {
            "accuracy": 0,
            "total": 0,
            "correct": 0,
            "by_recommendation": {},
            "message": "Ingen verifierad data ännu. Använd 'Verifiera' efter 30 dagar."
        }

    correct = sum(1 for e in filtered if e.get("was_correct"))
    total = len(filtered)

    # Per rekommendationstyp
    by_rec = {}
    for e in filtered:
        rec = e.get("recommendation", "Okänd")
        if rec not in by_rec:
            by_rec[rec] = {"correct": 0, "total": 0}
        by_rec[rec]["total"] += 1
        if e.get("was_correct"):
            by_rec[rec]["correct"] += 1

    for rec, stats in by_rec.items():
        stats["accuracy"] = round(stats["correct"] / stats["total"] * 100, 1) if stats["total"] > 0 else 0

    return {
        "accuracy": round(correct / total * 100, 1) if total > 0 else 0,
        "total": total,
        "correct": correct,
        "by_recommendation": by_rec,
    }


def get_consensus_accuracy() -> dict:
    """Beräkna hur ofta ensemblen hade rätt vs enskilda providers.

    Jämför signaler märkta med provider="ensemble" mot singelprovider-signaler.

    Returns:
        Dict med accuracy per provider + ensemble
    """
    entries = _load_journal()
    verified = [e for e in entries if e.get("was_correct") is not None]

    stats = {}
    for e in verified:
        p = e.get("provider", "unknown")
        if p not in stats:
            stats[p] = {"correct": 0, "total": 0}
        stats[p]["total"] += 1
        if e.get("was_correct"):
            stats[p]["correct"] += 1

    result = {}
    for p, s in stats.items():
        result[p] = {
            "accuracy": round(s["correct"] / s["total"] * 100, 1) if s["total"] > 0 else 0,
            "total": s["total"],
            "correct": s["correct"],
        }

    return result


def get_best_provider_for_sector(sector: str) -> str:
    """Hitta vilken AI-provider som är bäst på en specifik sektor.

    Args:
        sector: Sektornamn (t.ex. "Technology")

    Returns:
        Providernamn med bäst träffsäkerhet i sektorn
    """
    entries = _load_journal()
    verified = [
        e for e in entries
        if e.get("was_correct") is not None
        and e.get("sector", "").lower() == sector.lower()
        and e.get("provider", "ensemble") != "ensemble"
    ]

    if not verified:
        return "deepseek"  # Default

    stats = {}
    for e in verified:
        p = e.get("provider", "unknown")
        if p not in stats:
            stats[p] = {"correct": 0, "total": 0}
        stats[p]["total"] += 1
        if e.get("was_correct"):
            stats[p]["correct"] += 1

    if not stats:
        return "deepseek"

    best = max(stats, key=lambda p: stats[p]["correct"] / max(stats[p]["total"], 1)
               if stats[p]["total"] > 0 else 0)
    return best


def _update_outcomes(entries: list, df: pd.DataFrame) -> list:
    """Update outcome prices for entries where 30/90 days have passed."""
    if df.empty or "ticker" not in df.columns:
        return entries

    price_map = {}
    if "current_price" in df.columns:
        price_map = df.set_index("ticker")["current_price"].to_dict()
    elif "close" in df.columns:
        price_map = df.set_index("ticker")["close"].to_dict()

    now = datetime.now()
    updated = []
    for entry in entries:
        e = entry.copy()
        try:
            entry_date = datetime.fromisoformat(e["date"])
            days_elapsed = (now - entry_date).days
            ticker = e.get("ticker", "")
            current_price = price_map.get(ticker)

            if current_price and e.get("price_at_time"):
                pct_change = (float(current_price) / float(e["price_at_time"]) - 1) * 100
                if days_elapsed >= 25 and e.get("outcome_1m") is None:
                    e["outcome_1m"] = round(pct_change, 2)
                    e["outcome_price_1m"] = round(float(current_price), 2)
                    # Auto-verifiera
                    rec = e.get("recommendation", "")
                    if rec in ("STARKT KÖP", "KÖP") and pct_change > 0:
                        e["was_correct"] = True
                    elif rec in ("STARKT SÄLJ", "SÄLJ", "UNDVIK") and pct_change < 0:
                        e["was_correct"] = True
                    elif rec in ("BEVAKA", "VÄNTA", "NEUTRAL") and abs(pct_change) < 3:
                        e["was_correct"] = True
                    else:
                        e["was_correct"] = False
                if days_elapsed >= 80 and e.get("outcome_3m") is None:
                    e["outcome_3m"] = round(pct_change, 2)
                    e["outcome_price_3m"] = round(float(current_price), 2)
        except Exception:
            pass
        updated.append(e)
    return updated


def page_ai_journal(df: pd.DataFrame):
    """AI Trade Journal page."""
    st.title("AI Trade Journal")
    st.caption("Spårar AI-rekommendationer och mäter träffsäkerhet över tid.")

    entries = _load_journal()

    # Update outcomes with current prices
    if not df.empty and entries:
        entries = _update_outcomes(entries, df)
        _save_journal(entries)

    if not entries:
        st.info("Journalen är tom. AI-rekommendationer loggas automatiskt när du analyserar aktier.")
        st.markdown("**Hur det fungerar:**")
        st.markdown("""
1. Analysera en aktie via AI-sidan
2. Rekommendationen sparas automatiskt med aktuellt pris
3. Efter 30 och 90 dagar beräknas utfallet automatiskt
4. Här ser du om AI:ns rekommendationer faktiskt stämde
""")
    else:
        # ---- Summary metrics ----
        completed_1m = [e for e in entries if e.get("outcome_1m") is not None]
        completed_3m = [e for e in entries if e.get("outcome_3m") is not None]
        verified = [e for e in entries if e.get("was_correct") is not None]

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Totalt loggade", len(entries))
        col2.metric("Avslutade (1m)", len(completed_1m))

        if completed_1m:
            returns_1m = [e["outcome_1m"] for e in completed_1m]
            win_rate = sum(1 for r in returns_1m if r > 0) / len(returns_1m) * 100
            avg_ret = sum(returns_1m) / len(returns_1m)
            col3.metric("Win rate (1m)", f"{win_rate:.0f}%")
            col4.metric("Avg avkastning (1m)", f"{avg_ret:+.1f}%")
        else:
            col3.metric("Win rate (1m)", "--")
            col4.metric("Avg avkastning (1m)", "--")

        # ---- Accuracy panel ----
        if verified:
            st.markdown("---")
            st.subheader("Träffsäkerhet")

            acc = get_ai_accuracy()
            consensus_acc = get_consensus_accuracy()

            c1, c2 = st.columns(2)
            with c1:
                st.metric("Total accuracy", f"{acc['accuracy']:.1f}%")
                st.caption(f"Baserat på {acc['total']} verifierade signaler")

                if consensus_acc:
                    st.markdown("**Accuracy per provider**")
                    acc_rows = []
                    for p, s in sorted(consensus_acc.items(), key=lambda x: x[1]["accuracy"], reverse=True):
                        acc_rows.append({
                            "Provider": p.capitalize(),
                            "Accuracy": f"{s['accuracy']:.1f}%",
                            "Signaler": s["total"],
                        })
                    if acc_rows:
                        st.dataframe(pd.DataFrame(acc_rows), use_container_width=True, hide_index=True)

            with c2:
                st.markdown("**Per rekommendationstyp**")
                if acc.get("by_recommendation"):
                    rec_rows = []
                    for rec, stats in acc["by_recommendation"].items():
                        rec_rows.append({
                            "Typ": rec,
                            "Accuracy": f"{stats['accuracy']:.1f}%",
                            "Antal": stats["total"],
                        })
                    st.dataframe(pd.DataFrame(rec_rows), use_container_width=True, hide_index=True)

        # ---- Breakdown by recommendation type ----
        if completed_1m:
            st.markdown("---")
            st.markdown("**Avkastning per rekommendationstyp**")
            recs = {}
            for e in completed_1m:
                rec = e.get("recommendation", "Okänd")
                if rec not in recs:
                    recs[rec] = []
                recs[rec].append(e["outcome_1m"])

            rec_rows = []
            for rec, returns in recs.items():
                rec_rows.append({
                    "Rekommendation": rec,
                    "Antal": len(returns),
                    "Win rate %": round(sum(1 for r in returns if r > 0) / len(returns) * 100, 1),
                    "Avg avkastning %": round(sum(returns) / len(returns), 2),
                    "Bäst %": round(max(returns), 2),
                    "Sämst %": round(min(returns), 2),
                })
            st.dataframe(pd.DataFrame(rec_rows), use_container_width=True, hide_index=True)

        # ---- Full log ----
        st.markdown("---")
        st.markdown("**Alla poster**")
        df_entries = pd.DataFrame(entries[::-1])  # Newest first
        show_cols = [c for c in ["date", "ticker", "recommendation", "provider", "confidence",
                                  "score_at_time", "price_at_time", "outcome_1m", "outcome_3m",
                                  "was_correct", "sector"]
                     if c in df_entries.columns]
        st.dataframe(df_entries[show_cols], use_container_width=True, hide_index=True)

    # Manual add entry
    with st.expander("Lägg till rekommendation manuellt"):
        c1, c2, c3, c4 = st.columns(4)
        m_ticker = c1.text_input("Ticker", key="journal_ticker").upper().strip()
        m_rec = c2.selectbox("Rekommendation", ["KÖP", "VÄNTA", "SÄLJ", "BEHÅLL"], key="journal_rec")
        m_price = c3.number_input("Pris", min_value=0.0, key="journal_price")
        m_score = c4.number_input("Score", min_value=0, max_value=100, key="journal_score")
        if st.button("Spara", key="journal_save") and m_ticker and m_price > 0:
            log_ai_recommendation(m_ticker, m_rec, float(m_score), float(m_price))
            st.success(f"Loggat {m_ticker} med rekommendation {m_rec}")
            st.rerun()
