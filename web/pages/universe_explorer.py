"""
universe_explorer.py — Publik Universe Explorer
================================================
Visar för ALLA inloggade användare (inte bara admin):

  Tab 1 "Nya kandidater"   — pending HIGH/MEDIUM-kandidater med quality score och AI-verdict
  Tab 2 "Nyligen tillagda" — senaste 20 auto-tillagda tickers
  Tab 3 "Rotationslogg"    — senaste 30 rotationer med P&L-uppföljning
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT     = Path(__file__).resolve().parent.parent.parent
DATA_DIR = ROOT / "data"


def _load_candidates() -> dict:
    p = DATA_DIR / "discovery_candidates.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"candidates": [], "auto_added": [], "auto_removed": [], "rejected": []}


def _load_rotation_log() -> list:
    p = DATA_DIR / "rotation_log.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def page_universe_explorer(df=None):
    """Huvud-entrypoint för Universe Explorer-sidan."""
    from web.ui.components import page_header
    page_header("Universe Explorer", "explore",
                subtitle="Automatiskt hittade aktiekandidater och rotationshistorik. Kandidater granskas via 5-lagers quality gate innan de läggs till universum.")

    cands_data  = _load_candidates()
    pending     = [c for c in cands_data.get("candidates", []) if c.get("status") == "pending"]
    auto_added  = cands_data.get("auto_added", [])
    rotation    = _load_rotation_log()

    # Metrics-rad
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Väntar granskning", len(pending))
    m2.metric("Auto-tillagda totalt", len(auto_added))
    m3.metric("Rotationer totalt", len(rotation))
    n_high = sum(1 for c in pending if c.get("quality_tier") == "HIGH")
    m4.metric("HIGH tier pending", n_high, delta="klara för add" if n_high else None)

    tab1, tab2, tab3 = st.tabs(["⏳ Nya kandidater", "✅ Nyligen tillagda", "🔄 Rotationslogg"])

    # ── Tab 1: Pending kandidater ─────────────────────────────────────────────
    with tab1:
        if not pending:
            st.info("Inga väntande kandidater just nu. Nästa discovery körs söndagar kl 11:00 UTC.")
        else:
            # Filter
            fc1, fc2 = st.columns(2)
            with fc1:
                tier_f = st.selectbox("Quality tier", ["Alla", "HIGH", "MEDIUM", "SPECULATIVE"],
                                      key="ue_tier")
            with fc2:
                src_f = st.selectbox(
                    "Källa",
                    ["Alla"] + sorted({c.get("source", "?") for c in pending}),
                    key="ue_src",
                )

            filtered = pending
            if tier_f != "Alla":
                filtered = [c for c in filtered if c.get("quality_tier") == tier_f]
            if src_f != "Alla":
                filtered = [c for c in filtered if c.get("source") == src_f]

            tier_order = {"HIGH": 0, "MEDIUM": 1, "SPECULATIVE": 2}
            filtered = sorted(
                filtered,
                key=lambda x: (tier_order.get(x.get("quality_tier", "MEDIUM"), 1),
                               -x.get("confidence", 0)),
            )

            st.caption(f"Visar {min(len(filtered), 30)} av {len(filtered)} kandidater")

            for c in filtered[:30]:
                tier  = c.get("quality_tier", "MEDIUM")
                conf  = c.get("confidence", 0)
                score = c.get("quality_score", 0)
                yf    = c.get("yf_data") or c.get("metadata", {})
                name  = yf.get("name", c["ticker"])
                sector = yf.get("sector", "")
                mc_raw = yf.get("market_cap", 0) or 0
                mc_str = f"${mc_raw/1e9:.1f}B" if mc_raw >= 1e9 else f"${mc_raw/1e6:.0f}M" if mc_raw > 0 else "?"
                price  = yf.get("price", "?")
                fraud  = c.get("fraud_flags", [])
                ai     = c.get("ai_verdict", {})
                ai_rec = ai.get("recommendation", "")
                ai_rea = ai.get("reasoning", "")

                tier_icon = {"HIGH": "🟢", "MEDIUM": "🟡", "SPECULATIVE": "🔴"}.get(tier, "⚪")
                ai_icon   = {"ADD": "🤖✅", "SKIP": "🤖❌", "INVESTIGATE": "🤖🔍"}.get(ai_rec, "")

                with st.container(border=True):
                    col_info, col_meta = st.columns([3, 2])
                    with col_info:
                        st.markdown(
                            f"**{c['ticker']}** — {name[:30]} "
                            f"{tier_icon} {tier} (q={score:.0f}) "
                            f"| Conf: {conf:.0%} {ai_icon}"
                        )
                        detail_parts = []
                        if sector:
                            detail_parts.append(f"Sektor: {sector}")
                        if price != "?":
                            detail_parts.append(f"Pris: {price}")
                        if mc_str != "?":
                            detail_parts.append(f"Mktcap: {mc_str}")
                        st.caption(" | ".join(detail_parts) if detail_parts else "")
                        st.caption(f"Källa: `{c.get('source', '?')}` — {c.get('reason', '')[:100]}")
                    with col_meta:
                        if fraud:
                            st.caption(f"⚠ {fraud[0][:80]}")
                        if ai_rea:
                            st.caption(f"AI: {ai_rea[:120]}")
                        # Bevaknings-knapp (alla användare kan lägga på sin bevakningslista)
                        if df is not None and not df.empty:
                            if st.button(f"⭐ Bevaka", key=f"ue_watch_{c['ticker']}"):
                                st.info(f"Öppna Bevakningslistan och lägg till {c['ticker']} manuellt för nu.")

    # ── Tab 2: Nyligen tillagda ───────────────────────────────────────────────
    with tab2:
        if not auto_added:
            st.info("Inga tickers auto-tillagda ännu.")
        else:
            show = auto_added[-20:][::-1]  # Senaste 20, nyast först
            rows = []
            for a in show:
                rows.append({
                    "Ticker":   a.get("ticker", "?"),
                    "Tillagd":  a.get("added", "?"),
                    "Kategori": a.get("category", "?"),
                    "Källa":    a.get("source", "?"),
                    "Anledning": a.get("reason", "")[:80],
                })
            try:
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            except Exception:
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # ── Tab 3: Rotationslogg ──────────────────────────────────────────────────
    with tab3:
        if not rotation:
            st.info("Ingen rotationshistorik ännu. Rotation körs automatiskt när aktier tas bort ur universum.")
            st.markdown("""
**Hur rotation fungerar:**
1. 🔴 En aktie flaggas (3 datafetchfel, låg score < 22, delistad)
2. 📊 Systemet rankar topp-10 ersättare från scored_universe (score > 55, rätt sektor)
3. 🤖 AI analyserar de 5 bästa och väljer den som bäst kompletterar universum
4. ✅ Vald ersättare läggs till automatiskt (eller kräver admin-godkännande)
""")
        else:
            show = rotation[-30:][::-1]
            rows = []
            for r in show:
                score_delta = (r.get("score_added", 0) - r.get("score_removed", 0))
                rows.append({
                    "Datum":        r.get("date", "?"),
                    "Borttagen":    r.get("removed", "?"),
                    "Score (bort)": r.get("score_removed", 0),
                    "Ersatt med":   r.get("added", "—") or "—",
                    "Score (in)":   r.get("score_added", 0),
                    "Δ Score":      f"{score_delta:+.1f}" if score_delta else "—",
                    "Anledning":    r.get("reason", "")[:60],
                })
            try:
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            except Exception:
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

            # Statistik
            if len(rows) >= 3:
                st.markdown("---")
                r1, r2, r3 = st.columns(3)
                r1.metric("Rotationer totalt", len(rotation))
                avg_delta = sum(
                    (r.get("score_added", 0) - r.get("score_removed", 0))
                    for r in rotation if r.get("score_added")
                ) / max(len([r for r in rotation if r.get("score_added")]), 1)
                r2.metric("Snitt Δ Score", f"{avg_delta:+.1f}", help="Positivt = bättre aktier in")
                n_ai = sum(1 for r in rotation if r.get("ai_reasoning"))
                r3.metric("AI-guiderade rotationer", n_ai)
