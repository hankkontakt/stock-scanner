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
        return "Nyborjarlage" if self.is_beginner else "Expertlage"

    @property
    def opposite_label(self) -> str:
        """Label for the opposite mode (for toggle button)."""
        return "Expertlage" if self.is_beginner else "Nyborjarlage"

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
        """Show a beginner-friendly info box with explanations.

        In expert mode, nothing is shown.
        """
        if not self.is_beginner:
            return

        beginner_tips = {
            "scan": (
                "**Welcome to the Stock Scanner!** "
                "This page lists stocks ranked by our scoring system. "
                "A higher score (70+) means the stock looks more attractive "
                "based on fundamentals, valuation, and momentum. "
                "Use the filters in the sidebar to narrow down your search."
            ),
            "technical": (
                "**Technical Analysis** helps you understand how a stock's "
                "price moves. RSI below 30 can mean the stock is oversold "
                "(potential buying opportunity), while above 70 means overbought "
                "(be cautious). MA200 is the most important long-term trend indicator."
            ),
            "portfolio": (
                "**Your Portfolio** shows the stocks you own. "
                "Track performance, see allocation, and get rebalancing suggestions. "
                "Green values are positive, red values are negative."
            ),
            "ai": (
                "**AI Analysis** uses machine learning to analyze stocks and markets. "
                "Choose a stock and a depth level, then click 'Run AI Analysis'. "
                "The deeper the analysis, the more comprehensive the result."
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
        """Render a small toggle button in the sidebar footer."""
        current = self.mode
        target = "expert" if current == "beginner" else "beginner"
        icon = ic("insights") if target == "expert" else ic("info")

        if st.button(
            f"{icon} Switch to {target.capitalize()} Mode",
            key="toggle_experience_mode",
            use_container_width=True,
            help=(
                "Beginner mode: simplified view with fewer columns and more explanations. "
                "Expert mode: full data, all columns, advanced filters."
            ),
        ):
            self.toggle()
            st.rerun()
