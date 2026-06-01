"""web/pages/overview.py – Sida 1: Översikt (cockpit).

Omdesignad enligt UX-planen: en äkta dashboard på ~1,5 skärm istället för 10
staplade sektioner. Visar nyckeltal + sammanfattande zoner med genvägar vidare;
detaljer (full topplista, earnings, drill-down) bor på sina dedikerade sidor.
"""
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from web.utils import load_watchlist, load_portfolio, _get_provider, REPORT_DIR
from core import ai_analysis
from core.country_flags import flag_for_ticker

from web.ui.components import page_header, metric_card, kpi_grid, panel, data_table, empty_state
from web.ui.ai_action import ai_run_control
from web.ui import tokens as t


def _goto(page_title: str):
    """Tillfällig nav-brygga mot nuvarande session-state-navigation.
    Ersätts av st.page_link när navigationen skrivs om till st.navigation."""
    if st.button(f"Visa allt  →", key=f"goto_{page_title}", use_container_width=True):
        st.session_state["nav_page"] = page_title
        st.rerun()


def _data_age_str() -> str:
    """Hur färsk är scandatan?"""
    files = sorted(Path(REPORT_DIR).glob("scored_universe_*.csv"), reverse=True)
    if not files:
        return "ingen scandata"
    import os
    age_h = (datetime.now() - datetime.fromtimestamp(os.path.getmtime(files[0]))).total_seconds() / 3600
    if age_h < 36:
        return f"uppdaterad för {age_h:.0f}h sedan"
    return f"⚠ {age_h/24:.0f} dagar gammal"


def page_overview(df: pd.DataFrame, sc_df: pd.DataFrame, holdings: pd.DataFrame = None):
    page_header("Översikt", "home", subtitle=f"Marknadsöversikt · {_data_age_str()}")

    if (df is None or df.empty) and (sc_df is None or sc_df.empty):
        empty_state("Aktiedata laddas in. Systemet uppdateras automatiskt varje vecka — "
                    "kom tillbaka snart.", icon="fresh")
        return

    has_df = df is not None and not df.empty and "score_total" in df.columns

    # ── Rad 1: Nyckeltal ─────────────────────────────────────────────────────
    if has_df:
        ranked = df.sort_values("score_total", ascending=False)
        top_row = ranked.iloc[0]
        n_stark = int((df.get("entry_signal", pd.Series()) == "STARK").sum()) \
            if "entry_signal" in df.columns else 0
        avg_score = df["score_total"].mean()
        kpi_grid([
            {"label": "Bolag i scan", "value": f"{len(df)}",
             "help": "Antal bolag i universumet just nu."},
            {"label": "STARK entry", "value": f"{n_stark}",
             "help": "Bolag med systemets starkaste köpsignal (alla faktorer pekar upp).",
             "value_color": t.POS},
            {"label": "Snittpoäng", "value": f"{avg_score:.0f}",
             "help": "Genomsnittlig score. >60 = generellt stark marknad.",
             "value_color": t.score_color(avg_score)},
            {"label": "Toppbolag", "value": str(top_row.get("ticker", "—")),
             "delta": f"{top_row.get('score_total', 0):.0f} poäng", "delta_kind": "pos",
             "help": "Högst rankade bolaget just nu.", "small": True},
        ])

    st.write("")

    # ── Rad 2: Köp nu  ·  Portfölj-snapshot ──────────────────────────────────
    col_a, col_b = st.columns(2)

    with col_a:
        with st.container(border=True):
            st.markdown("### Köp nu — starkaste signaler")
            frames = [f for f in [df, sc_df]
                      if f is not None and not f.empty and "entry_signal" in f.columns]
            combined = (pd.concat(frames, ignore_index=True).drop_duplicates("ticker")
                        if frames else pd.DataFrame())
            if not combined.empty:
                score_c = "score_total" if "score_total" in combined.columns else combined.columns[0]
                buy = combined[combined["entry_signal"] == "STARK"].sort_values(score_c, ascending=False).head(5)
                if not buy.empty:
                    show = buy[[c for c in ["ticker", "name", score_c, "sector"] if c in buy.columns]].copy()
                    show["ticker"] = show["ticker"].apply(lambda x: f"{flag_for_ticker(x)} {x}")
                    show = show.rename(columns={"ticker": "Ticker", "name": "Bolag",
                                                score_c: "Score", "sector": "Sektor"})
                    data_table(show, height=215)
                else:
                    empty_state("Inga STARK-signaler just nu.", icon="info")
            else:
                empty_state("Ingen signaldata.", icon="info")
            _goto("🔍 Veckoscanner")

    with col_b:
        with st.container(border=True):
            st.markdown("### Din portfölj")
            hlds = holdings if holdings is not None else load_portfolio()
            if hlds is not None and not hlds.empty and has_df:
                lookup = df.set_index("ticker").to_dict("index")
                review = []
                for _, h in hlds.iterrows():
                    tk = str(h["ticker"]).upper()
                    sc = lookup.get(tk, {})
                    score = sc.get("score_total", 0) or 0
                    entry = sc.get("entry_signal", "—")
                    if score and (score < 45 or entry == "EJ AKTUELL"):
                        review.append({"Ticker": f"{flag_for_ticker(tk)} {tk}",
                                       "Score": round(score), "Signal": entry})
                n_h = len(hlds)
                metric_card("Innehav", f"{n_h}", small=True,
                            help="Antal bolag i din portfölj.")
                if review:
                    st.caption(f"{len(review)} innehav att se över (låg score / ej aktuell):")
                    data_table(pd.DataFrame(review), height=140)
                else:
                    st.caption("Inga innehav kräver översyn just nu. ✓")
            else:
                empty_state("Ingen portfölj ännu — lägg till innehav.", icon="portfolio")
            _goto("💼 Portfölj")

    st.write("")

    # ── Rad 3: Marknadsläge  ·  Kommande rapporter ───────────────────────────
    col_c, col_d = st.columns(2)

    with col_c:
        with st.container(border=True):
            st.markdown("### Marknadsläge")
            if has_df and "entry_signal" in df.columns:
                counts = df["entry_signal"].value_counts()
                cc = st.columns(4)
                for i, (sig, col) in enumerate(zip(["STARK", "OK", "VÄNTA", "EJ AKTUELL"], cc)):
                    with col:
                        kind = {"STARK": t.POS, "OK": t.PRIMARY, "VÄNTA": t.WARN}.get(sig, t.NEG)
                        metric_card(sig.title()[:6], f"{int(counts.get(sig, 0))}",
                                    small=True, value_color=kind)
                # Sektorledare
                if "sector" in df.columns:
                    sect = (df.groupby("sector")["score_total"].mean()
                            .sort_values(ascending=False).head(3))
                    st.caption("Starkaste sektorer (snittpoäng):")
                    st.markdown(" · ".join(f"**{s}** {v:.0f}" for s, v in sect.items()))
            else:
                empty_state("Ingen signaldata.", icon="info")
            _goto("🏭 Sektorrotation")

    with col_d:
        with st.container(border=True):
            st.markdown("### Kommande rapporter")
            st.caption("Var försiktig med köp precis före rapport.")
            if has_df:
                try:
                    from core.earnings_calendar import upcoming_in_top
                    cal = upcoming_in_top(df, top_n=50, days_ahead=14)
                    if cal is not None and not cal.empty:
                        c = cal[["earnings_date", "days_until", "ticker"]].head(6).copy()
                        c["ticker"] = c["ticker"].apply(lambda x: f"{flag_for_ticker(x)} {x}")
                        c = c.rename(columns={"earnings_date": "Datum", "days_until": "Dagar", "ticker": "Ticker"})
                        data_table(c, height=215)
                    else:
                        empty_state("Inga rapporter inom 14 dagar.", icon="fresh")
                except Exception:
                    empty_state("Earnings-data ej tillgänglig.", icon="info")
            else:
                empty_state("Ladda scandata.", icon="info")
            _goto("🚨 Larm & Notiser")

    # ── AI-sammanfattning (infälld, djup väljs vid körning) ──────────────────
    st.write("")
    with st.expander("AI-marknadssammanfattning", expanded=False):
        st.caption("AI sammanfattar dagens marknadsläge utifrån scandatan. Välj djup nedan.")
        run, depth = ai_run_control("ov_market", default="Normal",
                                    run_label="Generera sammanfattning")
        if run:
            with st.spinner("Analyserar marknaden..."):
                try:
                    result = ai_analysis.generate_market_summary(
                        df=df if has_df else None,
                        sc_df=sc_df if (sc_df is not None and not sc_df.empty) else None,
                        provider=_get_provider(), depth=depth,
                    )
                    with st.container(border=True):
                        st.markdown(result)
                except Exception as e:
                    st.error(f"Kunde inte generera sammanfattning: {e}")
