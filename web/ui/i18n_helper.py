"""
web/ui/i18n_helper.py
=====================
Convenience-wrapper för i18n i Streamlit-sidor.

Användning:
    from web.ui.i18n_helper import t, get_locale

    st.write(t("portfolio"))          # "Portfölj" (sv) / "Portfolio" (en)
    st.write(t("pe_ratio"))           # "P/E-tal" (sv)
"""

import streamlit as st

from core.i18n import TranslationManager


def t(key: str, **kwargs) -> str:
    """Översätt en nyckel med den locale som är aktiv i sessionen.

    Args:
        key:    Översättningsnyckel (se core/i18n/sv.py för alla nycklar).
        **kwargs: Valfria format-parametrar, t.ex. t("hello", name="World").

    Returns:
        Översatt text — faller tillbaka på nyckeln om den saknas.
    """
    locale = st.session_state.get("locale", "sv")
    return TranslationManager(locale).t(key, **kwargs)


def get_locale() -> str:
    """Returnerar aktiv locale ("sv" | "en" | "de").  Default: "sv"."""
    return st.session_state.get("locale", "sv")


def set_locale(locale: str) -> None:
    """Sätt locale i sessionen och ladda om sidan."""
    if locale not in ("sv", "en", "de"):
        locale = "sv"
    st.session_state["locale"] = locale
