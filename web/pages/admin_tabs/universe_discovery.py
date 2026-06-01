"""admin_tabs/universe_discovery.py — Universe Discovery & Underhåll

Visar:
  • Pending-kandidater från alla källor (godkänn / avvisa)
  • Auto-tillagda tickers
  • Borttagningskandidater (låg score, låg likviditet)
  • Kör discovery manuellt
  • Statistik per källa
"""
from pathlib import Path

import pandas as pd
import streamlit as st


def render():
    st.subheader("🔍 Universe Discovery")
    st.caption(
        "Systemet hittar automatiskt nya potentiella aktier från Finviz, index-tillägg, "
        "nyheter och AI, validerar dem mot yfinance och presenterar dem här för granskning."
    )

    from core.universe_manager import (
        load_candidates, approve_candidate, reject_candidate,
        get_removal_candidates, get_all_universe_tickers, save_candidates,
    )

    cands_data = load_candidates()
    pending   = [c for c in cands_data["candidates"] if c.get("status") == "pending"]
    approved  = cands_data.get("auto_added", [])
    removed   = cands_data.get("auto_removed", [])
    rejected  = [c for c in cands_data["candidates"] if c.get("status") == "rejected"]

    # ── Metrics ─────────────────────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Väntar granskning", len(pending))
    c2.metric("Tillagda (auto)", len(approved))
    c3.metric("Borttagna (auto)", len(removed))
    c4.metric("Avvisade", len(rejected))
    # ── Rotation Preview ──────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 🔄 Rotation Preview")
    with st.expander("Visa senaste rotation-status och kör rotation nu", expanded=False):
        try:
            from core.rotation_engine import load_rotation_log
            rot_log = load_rotation_log()
            if rot_log:
                recent = rot_log[-10:]
                st.caption(f"Senaste {len(recent)} rotationerna (av {len(rot_log)} totalt):")
                rrows = []
                for r in reversed(recent):
                    rrows.append({
                        "Datum": r.get("date", ""),
                        "Borttagen": r.get("removed", ""),
                        "Tillagd": r.get("added", "") or "—",
                        "Anledning": r.get("reason", "")[:60],
                        "Score delta": f"{r.get('score_removed', 0):.0f}->{r.get('score_added', 0):.0f}",
                    })
                st.dataframe(rrows, use_container_width=True, hide_index=True)
            else:
                st.info("Inga rotationer loggade anu.")

            col_r1, col_r2 = st.columns([2, 1])
            with col_r1:
                rot_dry_run = st.checkbox("Dry run (simulera)", value=True, key="rot_dry_run")
            with col_r2:
                if st.button("Kör rotation nu", key="btn_run_rotation"):
                    with st.spinner("Kör rotation..."):
                        try:
                            from core.rotation_engine import run_rotation
                            result = run_rotation(
                                max_replacements=5,
                                auto_execute=not rot_dry_run,
                                use_ai=True,
                                dry_run=rot_dry_run,
                            )
                            n_t = len(result.get("triggers", []))
                            n_e = len(result.get("executed", []))
                            if rot_dry_run:
                                st.info(f"{n_t} utlösare hittades (dry run - inget ändrat)")
                                if n_t:
                                    for t in result["triggers"][:5]:
                                        st.write(f"- {t['ticker']}: {t['reason']}")
                            else:
                                st.success(f"{n_e} rotationer exekverade, {n_t} utlösare totalt")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Rotation misslyckades: {e}")
        except Exception as e:
            st.error(f"Kunde inte ladda rotationslogg: {e}")


    # ── Kör discovery manuellt ────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 🚀 Kör discovery")
    with st.expander("Starta discovery-scan", expanded=False):
        col_src, col_opts = st.columns([2, 1])
        with col_src:
            sources = st.multiselect(
                "Källor att söka",
                ["finviz", "index", "news", "ai", "etf"],
                default=["index", "news", "ai"],
                key="disc_sources",
            )
        with col_opts:
            dry_run  = st.checkbox("Dry run (simulera)", value=True, key="disc_dry")
            auto_add = st.slider("Auto-add threshold (confidence)", 0.70, 1.0, 0.90, 0.05, key="disc_threshold")

        if st.button("▶ Kör discovery nu", key="btn_run_discovery"):
            if not sources:
                st.warning("Välj minst en källa.")
            else:
                with st.spinner("Kör discovery... (kan ta 1-3 minuter beroende på källor)"):
                    try:
                        from core.universe_manager import run_full_maintenance
                        result = run_full_maintenance(
                            sources=sources,
                            auto_add_threshold=auto_add,
                            auto_remove=False,
                            dry_run=dry_run,
                            commit=False,
                            verbose=True,
                        )
                        st.success(
                            f"Klart! Hittade {result['candidates_found']} kandidater, "
                            f"{result['candidates_new']} nya. "
                            f"Auto-tillagda: {len(result['auto_added'])}."
                        )
                        if result["auto_added"]:
                            st.info(f"Auto-tillagda: {', '.join(result['auto_added'])}")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Discovery misslyckades: {e}")

    # ── Pending-kandidater ────────────────────────────────────────────────
    st.markdown("---")
    st.markdown(f"### ⏳ Väntar granskning ({len(pending)})")

    if not pending:
        st.info("Inga väntande kandidater. Kör en discovery ovan för att hitta nya aktier.")
    else:
        # Filtrera
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            source_filter = st.selectbox(
                "Filtrera källa",
                ["Alla"] + sorted({c.get("source", "?") for c in pending}),
                key="disc_source_filter",
            )
        with col_f2:
            region_filter = st.selectbox(
                "Filtrera region",
                ["Alla"] + sorted({c.get("region", "?") for c in pending}),
                key="disc_region_filter",
            )

        col_f3, _ = st.columns(2)
        with col_f3:
            tier_filter = st.selectbox(
                "Filtrera quality tier",
                ["Alla", "HIGH", "MEDIUM", "SPECULATIVE"],
                key="disc_tier_filter",
            )

        filtered = pending
        if source_filter != "Alla":
            filtered = [c for c in filtered if c.get("source") == source_filter]
        if region_filter != "Alla":
            filtered = [c for c in filtered if c.get("region") == region_filter]
        if tier_filter != "Alla":
            filtered = [c for c in filtered if c.get("quality_tier", "MEDIUM") == tier_filter]

        # Sortera: HIGH tier + högst confidence först
        tier_order = {"HIGH": 0, "MEDIUM": 1, "SPECULATIVE": 2}
        filtered = sorted(
            filtered,
            key=lambda x: (tier_order.get(x.get("quality_tier", "MEDIUM"), 1), -x.get("confidence", 0)),
        )

        for c in filtered[:50]:
            ticker   = c["ticker"]
            source   = c.get("source", "?")
            reason   = c.get("reason", "")
            conf     = c.get("confidence", 0)
            region   = c.get("region", "")
            tier     = c.get("quality_tier", "MEDIUM")
            q_score  = c.get("quality_score", 0)
            fraud    = c.get("fraud_flags", [])
            yf       = c.get("yf_data") or c.get("metadata", {})
            name     = yf.get("name", "")
            mc_raw   = yf.get("market_cap", 0) or 0
            mc_str   = f"${mc_raw/1e9:.1f}B" if mc_raw >= 1e9 else f"${mc_raw/1e6:.0f}M" if mc_raw > 0 else "?"
            price    = yf.get("price", "?")
            sector   = yf.get("sector", "")

            conf_color = "#16a34a" if conf >= 0.75 else "#f59e0b" if conf >= 0.55 else "#dc2626"
            tier_badge = {
                "HIGH":        "🟢 HIGH",
                "MEDIUM":      "🟡 MEDIUM",
                "SPECULATIVE": "🔴 SPEC",
            }.get(tier, tier)
            label = (
                f"**{ticker}** — {name[:25] if name else ''} "
                f"| {tier_badge} (q={q_score:.0f}) "
                f"| Källa: `{source}` | Region: {region} | "
                f"Conf: <span style='color:{conf_color}'>{conf:.0%}</span>"
            )

            with st.container(border=True):
                col_l, col_b1, col_b2 = st.columns([6, 1, 1])
                with col_l:
                    st.markdown(label, unsafe_allow_html=True)
                    detail = []
                    if sector:
                        detail.append(f"Sektor: {sector}")
                    if price and price != "?":
                        detail.append(f"Pris: {price}")
                    if mc_str != "?":
                        detail.append(f"Market cap: {mc_str}")
                    if detail:
                        st.caption(" | ".join(detail))
                    st.caption(f"Anledning: {reason[:120]}")
                    if fraud:
                        for f_flag in fraud[:2]:
                            st.caption(f"⚠ {f_flag}")
                with col_b1:
                    if st.button("✅ Lägg till", key=f"approve_{ticker}"):
                        if approve_candidate(ticker):
                            st.success(f"{ticker} tillagd!")
                            st.rerun()
                        else:
                            st.error(f"Kunde inte lägga till {ticker}")
                with col_b2:
                    if st.button("❌ Avvisa", key=f"reject_{ticker}"):
                        if reject_candidate(ticker):
                            st.info(f"{ticker} avvisad")
                            st.rerun()

        if len(filtered) > 50:
            st.caption(f"Visar 50 av {len(filtered)} — filtrera för att se fler")

    # ── Borttagningskandidater ────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### ⚠️ Borttagningskandidater (låg score / låg likviditet)")
    with st.expander("Visa tickers som kan behöva tas bort", expanded=False):
        try:
            removal = get_removal_candidates()
        except Exception as e:
            st.error(f"Kunde inte hämta borttagningskandidater: {e}")
            removal = []

        if not removal:
            st.success("Inga uppenbara borttagningskandidater just nu.")
        else:
            st.warning(
                f"{len(removal)} tickers har låg score eller hög strike-count. "
                "Granska dem och ta bort manuellt om det behövs."
            )
            rdf = pd.DataFrame(removal)
            st.dataframe(rdf, use_container_width=True, hide_index=True)

            st.caption(
                "För att ta bort en ticker: använd 'Universe Health'-tabben eller kör "
                "`remove_ticker_from_universe()` i pipeline."
            )

    # ── Tillagda ─────────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown(f"### ✅ Auto-tillagda ({len(approved)})")
    if approved:
        with st.expander("Visa tillagda tickers", expanded=False):
            adf = pd.DataFrame(approved)
            st.dataframe(adf, use_container_width=True, hide_index=True)
    else:
        st.caption("Inga tickers auto-tillagda ännu.")

    # ── Käll-statistik ────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 📊 Käll-statistik")
    all_candidates = cands_data.get("candidates", [])
    if all_candidates:
        source_counts = {}
        for c in all_candidates:
            src = c.get("source", "okänd")
            source_counts[src] = source_counts.get(src, 0) + 1
        src_df = pd.DataFrame(
            [{"Källa": k, "Antal kandidater": v} for k, v in sorted(source_counts.items(), key=lambda x: -x[1])]
        )
        st.dataframe(src_df, use_container_width=True, hide_index=True)
    else:
        st.caption("Ingen käll-statistik ännu.")

    # ── Avvisade ─────────────────────────────────────────────────────────
    if rejected:
        st.markdown("---")
        with st.expander(f"Avvisade kandidater ({len(rejected)})", expanded=False):
            rjdf = pd.DataFrame([
                {"Ticker": c["ticker"], "Källa": c.get("source", "?"),
                 "Anledning": c.get("reject_reason", ""), "Datum": c.get("rejected_date", "")}
                for c in rejected
            ])
            st.dataframe(rjdf, use_container_width=True, hide_index=True)

    # ── Rensa gamla pending ───────────────────────────────────────────────
    st.markdown("---")
    if st.button("🧹 Rensa gamla pending (äldre än 30 dagar)", key="btn_cleanup_pending"):
        from datetime import timedelta
        import datetime as dt
        cutoff = (dt.date.today() - timedelta(days=30)).isoformat()
        cands = load_candidates()
        before = len([c for c in cands["candidates"] if c.get("status") == "pending"])
        cands["candidates"] = [
            c for c in cands["candidates"]
            if not (c.get("status") == "pending" and c.get("discovered", "9999") < cutoff)
        ]
        after = len([c for c in cands["candidates"] if c.get("status") == "pending"])
        save_candidates(cands)
        st.success(f"Rensade {before - after} gamla pending-kandidater")
        st.rerun()
