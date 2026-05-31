"""admin/config_tab.py – Konfiguration tab for admin page."""
import json
import os
from pathlib import Path

import pandas as pd
import streamlit as st

from core import config
from web.utils import DATA_DIR


def render():
    st.subheader("Konfiguration")
    st.caption("Aktuella faktorvikter och scoressattningar.")

    st.markdown("### Faktorvikter (scoring)")
    weights = config.FACTOR_WEIGHTS
    w_rows = [{"Faktor": k.capitalize(), "Vikt": f"{v*100:.1f}%"} for k, v in weights.items()]
    w_rows.append({"Faktor": "**Totalt**", "Vikt": f"{sum(weights.values())*100:.1f}%"})
    st.dataframe(pd.DataFrame(w_rows), use_container_width=True, hide_index=True)

    st.markdown("### Smabolagskonfiguration")
    sc = config.SMALLCAP_CONFIG
    sc_rows = []
    for k, v in sc.items():
        if isinstance(v, dict):
            for sk, sv in v.items():
                sc_rows.append({"Installning": f"{k}.{sk}", "Varde": str(sv)})
        else:
            sc_rows.append({"Installning": k, "Varde": str(v)})
    st.dataframe(pd.DataFrame(sc_rows), use_container_width=True, hide_index=True)

    st.markdown("### Miljovariabler & Secrets")
    secrets_to_show = ["DEEPSEEK_API_KEY", "GEMINI_API_KEY", "FMP_API_KEY",
                       "FINNHUB_API_KEY", "EMAIL_SENDER", "EMAIL_TO", "SITE_PASSWORD"]
    secret_rows = []
    for key in secrets_to_show:
        val = os.getenv(key, "") or ""
        try:
            if not val:
                val = st.secrets.get(key, "")
        except Exception:
            pass
        secret_rows.append({"Nyckel": key, "Varde": "Satt" if val else "Saknas"})

    st.dataframe(pd.DataFrame(secret_rows), use_container_width=True, hide_index=True)
    st.caption("*Varden visas inte av sakerhetsskal. 'Satt' = nyckeln ar konfigurerad.*")
