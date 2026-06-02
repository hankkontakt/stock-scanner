"""
experience_mode.py -- Beginner/Expert mode toggle for MarketScan.

Manages user experience level with simplified vs. full-featured views.
Preference stored in st.session_state with optional persistence.
"""
from __future__ import annotations

import streamlit as st

from web.ui.icons import ic


class InvestorExperience:
    """Manages beginner/expert experience mode.

    Beginner mode: simplified view, fewer columns, more explanations, tooltips.
    Expert mode: full data, all columns, advanced filters, raw data access.

    Usage:
        exp = InvestorExperience()
        if exp.is_expert:
            # Show advanced controls
        if exp.is_beginner:
            # Show simplified view with extra explanations
    """

    SESSION_KEY = "_experience_mode"

    def __init__(self) -> None:
        if self.SESSION_KEY not in st.session_state:
            st.session_state[self.SESSION_KEY] = "beginner"

    @property
    def mode(self) -> str:
        """Current mode: 'beginner' or 'expert'."""
        return st.session_state.get(self.SESSION_KEY, "beginner")

    @property
    def is_beginner(self) -> bool:
        return self.mode == "beginner"

    @property
    def is_expert(self) -> bool:
        return self.mode == "expert"

    def set_mode(self, mode: str) -> None:
        """Set experience mode."""
        if mode in ("beginner", "expert"):
            st.session_state[self.SESSION_KEY] = mode

    def toggle(self) -> str:
        """Toggle between beginner and expert. Returns the new mode."""
        new = "expert" if self.is_beginner else "beginner"
        self.set_mode(new)
        return new

    @property
    def label(self) -> str:
        """Human-readable label for the current mode."""
        return "Nybörjarläge" if self.is_beginner else "Expertläge"

    @property
    def opposite_label(self) -> str:
        """Label for the opposite mode (for toggle button)."""
        return "Expertläge" if self.is_beginner else "Nybörjarläge"

    # ── Helper methods for conditional UI ────────────────────────────────────

    def column_config(self, all_columns: list[str]) -> list[str]:
        """Filter columns based on experience mode.

        In beginner mode, return a subset of simplified columns.
        In expert mode, return all columns.
        """
        if self.is_expert:
            return all_columns

        # Beginner mode: show only the essential, most important columns
        beginner_friendly = [
            "ticker", "name", "sector", "score_total",
            "entry_signal", "trend_signal", "current_price",
            "pe_trailing", "price_to_book",
            "roe", "revenue_growth",
            "debt_to_equity", "dividend_yield",
            "rsi_14", "return_1m",
        ]
        return [c for c in beginner_friendly if c in all_columns]

    def show_beginner_info(self, key: str = "") -> None:
        """Visa nybörjar-info om vi är i nybörjarläge. Inget visas i expertläge."""
        if not self.is_beginner:
            return

        beginner_tips = {
            "scan": (
                "**Välkommen till Veckoscannern!** "
                "Sidan listar aktier rankade av systemet. "
                "Högre score (70+) = aktien ser mer attraktiv ut baserat på "
                "fundamenta, värdering och momentum. "
                "Använd filtren i sidebaren för att avgränsa sökningen."
            ),
            "technical": (
                "**Teknisk analys** visar hur aktiens kurs rör sig. "
                "RSI under 30 kan betyda att aktien är översåld (köpläge), "
                "över 70 = köpt för mycket (var försiktig). "
                "MA200 är den viktigaste långsiktiga trendindikatorn."
            ),
            "portfolio": (
                "**Din portfölj** visar aktier du äger. "
                "Följ upp prestanda, se fördelning och få ombalanseringsförslag. "
                "Gröna värden är positiva, röda är negativa."
            ),
            "ai": (
                "**AI-analys** använder maskininlärning för att analysera aktier. "
                "Välj en aktie och analysdjup, klicka sedan på 'Kör analys'. "
                "Djupare analys ger mer heltäckande svar."
            ),
        }

        tip = beginner_tips.get(key, "")
        if tip:
            st.info(tip, icon="💡")

    def is_advanced_feature(self, feature_name: str) -> bool:
        """Check if a feature should be visible.

        Some features are only shown in expert mode.
        """
        # Features that require expert mode
        expert_only = {
            "raw_data_access", "advanced_filters", "debug_panel",
            "column_customization", "export_raw", "api_access",
            "correlation_analysis", "backtest_advanced",
        }
        if feature_name in expert_only:
            return self.is_expert
        return True  # All other features are visible in both modes

    def render_toggle(self) -> None:
        """Rendera en liten toggle-knapp i sidebar-foten."""
        target_label = self.opposite_label
        icon = ic("insights") if self.is_beginner else ic("info")

        if st.button(
            f"{icon} Byt till {target_label}",
            key="toggle_experience_mode",
            use_container_width=True,
            help=(
                "Nybörjarläge: förenklad vy med färre kolumner och mer förklaringar. "
                "Expertläge: all data, alla kolumner, avancerade filter."
            ),
        ):
            self.toggle()
            st.rerun()
