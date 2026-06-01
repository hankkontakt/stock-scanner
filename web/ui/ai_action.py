"""
ai_action.py -- AI-djupväljare vid användningsstället.

Ersätter den globala djup-väljaren i sidofältet. Istället väljer användaren djup
DIREKT där AI ska köras, via en liten segmented_control bredvid kör-knappen.
Varje plats får en vettig default (chat=Snabb, aktieanalys=Normal, djupare=Djup).
"""
from __future__ import annotations

import streamlit as st

from web.ui.icons import ic

DEPTHS = ["Snabb", "Normal", "Djup", "Extra djup"]


def depth_selector(key: str, default: str = "Normal", label: str = "AI-djup") -> str:
    """Liten djup-väljare. Returnerar valt djup (str).

    Använd direkt ovanför/bredvid en AI-knapp. `key` måste vara unik per plats.
    """
    if default not in DEPTHS:
        default = "Normal"
    try:
        choice = st.segmented_control(
            label, DEPTHS, default=default, key=f"depth_{key}",
            help="Snabb = kort & billigt * Normal = standard * Djup/Extra djup = "
                 "mer kontext och längre analys (långsammare).",
        )
        return choice or default
    except Exception:
        # Fallback för äldre Streamlit utan segmented_control
        return st.radio(label, DEPTHS, index=DEPTHS.index(default),
                        horizontal=True, key=f"depth_{key}") or default


def ai_run_control(key: str, *, default: str = "Normal",
                   run_label: str = "Kör AI-analys") -> tuple[bool, str]:
    """Renderar djup-väljare + kör-knapp tillsammans vid användningsstället.

    Returnerar (clicked, depth). Exempel:
        run, depth = ai_run_control("stock_ai", default="Normal")
        if run:
            result = ai_analysis.analyze_stock(ticker, df, depth=depth)
    """
    c1, c2 = st.columns([3, 1])
    with c1:
        depth = depth_selector(key, default=default)
    with c2:
        st.write("")  # vertikal justering mot segmented_control
        clicked = st.button(f"{ic('run')} {run_label}", key=f"run_{key}",
                            type="primary", use_container_width=True)
    return clicked, depth
