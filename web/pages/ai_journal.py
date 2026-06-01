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
                            price_at_time: float, ai_text_snippet: str = ""):
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
        "outcome_1m": None,
        "outcome_3m": None,
        "outcome_price_1m": None,
        "outcome_price_3m": None,
    })
    # Keep last 500 entries
    _save_journal(entries[-500:])


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
        # Still show manual add form when empty
    else:
        # Summary metrics
        completed_1m = [e for e in entries if e.get("outcome_1m") is not None]
        completed_3m = [e for e in entries if e.get("outcome_3m") is not None]

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

        st.markdown("---")

        # Breakdown by recommendation type
        if completed_1m:
            st.markdown("**Träffsäkerhet per rekommendationstyp**")
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
            st.markdown("---")

        # Full log
        st.markdown("**Alla poster**")
        df_entries = pd.DataFrame(entries[::-1])  # Newest first
        show_cols = [c for c in ["date", "ticker", "recommendation", "score_at_time", "price_at_time",
                                  "outcome_1m", "outcome_3m"] if c in df_entries.columns]
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
