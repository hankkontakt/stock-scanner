"""admin/cache_tab.py – Cache and AI log tabs for admin page."""
import json
import time
from datetime import datetime
from pathlib import Path

import streamlit as st

from web.utils import DATA_DIR, REPORT_DIR

_CACHE_DIR = DATA_DIR / "cache"


def render_cache():
    st.subheader("Cache-hantering")

    if not _CACHE_DIR.exists():
        st.info("Cache-katalogen finns inte anu.")
    else:
        files = list(_CACHE_DIR.glob("*.pkl"))
        if not files:
            st.info("Cache-katalogen ar tom.")
        else:
            total_size_mb = sum(f.stat().st_size for f in files) / (1024 * 1024)
            st.metric("Cache-filer", len(files))
            st.metric("Total storlek", f"{total_size_mb:.1f} MB")

            age_options = {"All data": 0, "Aldre an 48 timmar": 48, "Aldre an 7 dagar": 168,
                           "Aldre an 30 dagar": 720}
            age_choice = st.selectbox("Rensa cache aldre an:", list(age_options.keys()))
            max_age = age_options[age_choice]

            if st.button("Rensa vald cache", type="primary", key="btn_clear_cache"):
                cutoff = time.time() - max_age * 3600
                removed = 0
                for f in files:
                    try:
                        if f.stat().st_mtime < cutoff:
                            f.unlink()
                            removed += 1
                    except Exception:
                        pass
                st.success(f"Rensade {removed} filer.")
                st.rerun()

            with st.expander("Lista cache-filer"):
                file_info = []
                for f in sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)[:50]:
                    age_h = (time.time() - f.stat().st_mtime) / 3600
                    size_kb = f.stat().st_size / 1024
                    file_info.append({"Fil": f.name[:50], "Alder": f"{age_h:.0f}h",
                                       "Storlek": f"{size_kb:.1f} KB"})
                st.dataframe(pd.DataFrame(file_info), use_container_width=True, hide_index=True)
                st.caption("Visar de 50 senast andrade filerna.")

    import pandas as pd

    st.markdown("---")
    st.markdown("**Rensa AI-cache**")
    ai_cache_dir = DATA_DIR / "ai_cache"
    if ai_cache_dir.exists():
        ai_files = list(ai_cache_dir.glob("*.md"))
        st.metric("AI-cache-filer", len(ai_files))
        if st.button("Rensa all AI-cache", key="btn_clear_ai"):
            from core.ai_analysis import clear_cache as _clear_ai_cache
            try:
                removed = _clear_ai_cache()
                st.success(f"Rensade {removed} AI-cache-filer.")
            except Exception as e:
                st.error(f"Misslyckades: {e}")

    st.markdown("---")
    st.markdown("**Rensa alla rapporter (utom senaste)**")
    reports = sorted(REPORT_DIR.glob("scored_universe_*.csv"))
    if len(reports) > 1:
        st.caption(f"{len(reports)} rapporter, {len(reports) - 1} kan rensas.")
        if st.button("Rensa gamla rapporter", key="btn_clear_reports"):
            for f in reports[:-1]:
                try:
                    f.unlink()
                except Exception:
                    pass
            st.success("Gamla rapporter rensade.")
            st.rerun()
    else:
        st.info("Endast 1 rapport -- inget att rensa.")


def render_ai_log():
    st.subheader("AI-logg")
    ai_log_path = DATA_DIR / "ai_usage_log.json"
    if ai_log_path.exists():
        try:
            log = json.loads(ai_log_path.read_text(encoding="utf-8"))
            if log:
                import pandas as pd
                df = pd.DataFrame(log)
                st.dataframe(df.tail(50), use_container_width=True, hide_index=True)
                st.caption(f"Totalt {len(log)} AI-anrop sedan start.")
            else:
                st.info("AI-logg ar tom.")
        except Exception as e:
            st.warning(f"Kunde inte lasa AI-logg: {e}")
    else:
        st.info("Ingen AI-logg hittades.")


def render_alarms():
    st.subheader("Larm")
    st.info("Larmhantering kommer hit i en kommande version.")
