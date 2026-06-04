"""admin/import_tab.py - Avanza import tab for admin page."""
import os
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from web.utils import DATA_DIR


def render():
    st.subheader("Importera från Avanza")

    st.markdown("""
    Exportera din portfölj från Avanza:
    1. Logga in på Avanza
    2. Gå till: Konto → Depå/ISK → fliken Innehav
    3. Klicka Exportera (längst ner till höger)
    4. Spara CSV-filen
    5. Ladda upp den nedan
    """)

    uploaded = st.file_uploader("Välj Avanza-export (CSV)", type=["csv", "txt"],
                                key="avanza_upload")

    if uploaded is not None:
        try:
            df_raw = pd.read_csv(uploaded, sep=";", encoding="utf-8-sig")
            st.dataframe(df_raw.head(20), use_container_width=True)

            if st.button("Bearbeta import", key="btn_avanza_process", type="primary"):
                temp_path = os.path.join(tempfile.gettempdir(), "avanza_import.csv")
                df_raw.to_csv(temp_path, index=False)

                from data_management.avanza_import import import_holdings
                result = import_holdings(temp_path, no_interactive=True, update_holdings=False)

                if result is not None and not result.empty:
                    st.success(f"{len(result)} innehav tolkades:")
                    st.dataframe(result, use_container_width=True, hide_index=True)

                    if st.button("Spara till holdings.csv", key="btn_avanza_save"):
                        result.to_csv(DATA_DIR / "holdings.csv", index=False)
                        st.success("Sparat till holdings.csv!")
                else:
                    st.warning("Inga innehav kunde tolkas. Kontrollera att CSV-filen har ratt format.")
        except Exception as e:
            st.error(f"Kunde inte lasa filen: {e}")

    st.markdown("---")
    st.markdown("**Ticker-mappningar**")
    map_path = DATA_DIR / "ticker_map.json"
    if map_path.exists():
        try:
            import json
            mapping = json.loads(map_path.read_text(encoding="utf-8"))
            if mapping:
                st.json(mapping)
            else:
                st.info("Inga sparade mappningar.")
        except Exception as e:
            st.warning(f"Kunde inte visa mappningar: {e}")
    else:
        st.info("Ingen ticker_map.json hittades.")
