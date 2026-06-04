"""
web/pages/admin_tabs/tab_settings.py
=====================================
Admin — Flik 4: Inställningar

Sub-tabs:
  - Scoring-konfiguration (faktorvikter, feature flags)
  - API-nycklar (status, förklaringar)
  - Användare (CRUD)
  - E-post (prenumeranter, leveranslogg)
"""
from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from web.utils import DATA_DIR


# ── Hjälpfunktioner ───────────────────────────────────────────────────────────

def _hash_password(plain: str) -> str:
    """Hasha lösenord med bcrypt."""
    import bcrypt as _bcrypt
    return _bcrypt.hashpw(plain.encode("utf-8"), _bcrypt.gensalt(rounds=12)).decode("utf-8")


def _load_email_delivery_log() -> list:
    path = DATA_DIR / "email_delivery_log.json"
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []


# ── Render ────────────────────────────────────────────────────────────────────

def render():
    st.markdown('<div class="section-header">Inställningar</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-desc">Hantera konfiguration, API-nycklar, användare och e-post.</div>',
        unsafe_allow_html=True,
    )

    tab_scoring, tab_keys, tab_users, tab_email = st.tabs([
        "Scoring", "API-nycklar", "Användare", "E-post",
    ])

    # ── Sub-tab 1: Scoring-konfiguration ─────────────────────────────────────
    with tab_scoring:
        st.markdown("#### Faktorvikter")
        try:
            from core import config
            weights = config.FACTOR_WEIGHTS
            w_rows = []
            factor_desc = {
                "value": "Låga P/E, P/B, högt FCF-utfall",
                "quality": "Hög ROE, marginaler, balans",
                "momentum": "Kursmomentum 3/6/12 månader",
                "growth": "Intäkts- och vinsttillväxt",
                "risk": "Låg volatilitet, låg skuld",
                "size": "Marknadsvärde (small cap-premie)",
                "dividend": "Direktavkastning och utdelningsandel",
                "sentiment": "AI- och nyhetssentiment",
                "short_interest": "Korta positioner som andel av float",
                "options_flow": "Optionsflödessignaler",
            }
            for k, v in weights.items():
                desc = factor_desc.get(k, "")
                w_rows.append({
                    "Faktor": k.capitalize(),
                    "Vikt": f"{v*100:.1f}%",
                    "Förklaring": desc,
                })
            w_rows.append({"Faktor": "**Totalt**", "Vikt": f"{sum(weights.values())*100:.1f}%", "Förklaring": ""})
            st.dataframe(pd.DataFrame(w_rows), use_container_width=True, hide_index=True)
            st.caption(
                "Vikterna bestämmer hur mycket varje faktor påverkar slutbetyget (0–100). "
                "Justeras via data/scoring_config.json."
            )
        except Exception as e:
            st.info(f"Kunde inte läsa faktorvikter: {e}")

        st.markdown("---")
        st.markdown("#### Feature flags")
        ff_path = DATA_DIR / "feature_flags.json"
        if ff_path.exists():
            try:
                ff = json.loads(ff_path.read_text(encoding="utf-8"))
                ff_rows = []
                ff_desc = {
                    "live_fx_rates": "Hämtar live-valutakurser för likviditetsfilter",
                    "use_ai_analysis": "AI-analys av portfölj och kandidater",
                    "use_ml_predictions": "ML-baserade återvändningsprognoser",
                    "enable_smallcap": "Småbolagsscan (separat universe)",
                    "enable_news_alerts": "Nyhetsbevakning och AI-sammanfattningar",
                }
                for k, v in ff.items() if isinstance(ff, dict) else []:
                    desc = ff_desc.get(k, "")
                    ff_rows.append({"Flagga": k, "Status": "På" if v else "Av", "Förklaring": desc})
                if ff_rows:
                    st.dataframe(pd.DataFrame(ff_rows), use_container_width=True, hide_index=True)
                    st.caption("Feature flags styr vilka funktioner som är aktiva. Ändras via data/feature_flags.json.")
            except Exception:
                st.info("Kunde inte läsa feature_flags.json")
        else:
            st.info("Ingen feature_flags.json hittades.")

    # ── Sub-tab 2: API-nycklar ──────────────────────────────────────────────
    with tab_keys:
        st.markdown("#### API-nycklar och tjänster")
        st.caption("Status för alla externa tjänster som systemet använder.")

        from web.pages.admin import _get_st_secret

        api_keys = [
            ("DEEPSEEK_API_KEY", "DeepSeek", "AI-analys av aktier och portfölj", "platform.deepseek.com"),
            ("GEMINI_API_KEY", "Gemini", "AI-fallback (gratis, rate-limited)", "aistudio.google.com"),
            ("FMP_API_KEY", "Financial Modeling Prep", "Resultatkalender och earnings data", "site.financialmodelingprep.com"),
            ("FINNHUB_API_KEY", "Finnhub", "Nyhetssentiment och marknadsdata", "finnhub.io"),
            ("GITHUB_TOKEN", "GitHub", "Synkronisering av datafiler och pipeline-trigger", "github.com/settings/tokens"),
            ("EMAIL_SENDER", "E-post (avsändare)", "Skickar rapporter via SMTP", "din e-postleverantör"),
            ("EMAIL_PASSWORD", "E-post (lösenord)", "SMTP-lösenord för avsändaren", "din e-postleverantör"),
        ]
        key_rows = []
        for key, label, description, source in api_keys:
            val = _get_st_secret(key)
            status = "Satt" if val and val.strip() else "Saknas"
            key_rows.append({"Tjänst": label, "Status": status, "Användning": description, "Hämta nyckel": source})

        st.dataframe(pd.DataFrame(key_rows), use_container_width=True, hide_index=True)

        st.markdown("---")
        with st.expander("Så här sätter du API-nycklar i Streamlit Cloud"):
            st.markdown("""
1. Gå till [Streamlit Cloud](https://share.streamlit.io) → din app → **Settings → Secrets**
2. Lägg till varje nyckel på formatet:
   ```toml
   DEEPSEEK_API_KEY = "dk-xxx..."
   GEMINI_API_KEY = "AIza..."
   GITHUB_TOKEN = "ghp_xxx..."
   ```
3. Spara — appen startar om automatiskt med de nya nycklarna.
            """)

    # ── Sub-tab 3: Användare ────────────────────────────────────────────────
    with tab_users:
        st.markdown("#### Användarkonton")
        try:
            from web.pages.admin import _load_users_config, _save_users_config
        except ImportError as e:
            st.error(f"Kunde inte ladda admin-funktioner: {e}")
            return

        users = _load_users_config()
        active_users = [u for u in users if u.get("active", True)]

        st.caption(f"{len(active_users)} aktiva användare utöver admin")
        if active_users:
            user_rows = [
                {
                    "Användare": u["username"],
                    "Namn": u.get("name", ""),
                    "E-post": u.get("email", ""),
                    "Skapad": u.get("added", ""),
                }
                for u in active_users
            ]
            st.dataframe(pd.DataFrame(user_rows), use_container_width=True, hide_index=True)
        else:
            st.info("Inga extra användare tillagda.")

        st.markdown("---")
        st.markdown("#### Lägg till användare")
        with st.form("form_add_user", clear_on_submit=True):
            col_u, col_n = st.columns(2)
            with col_u:
                new_uname = st.text_input("Användarnamn", placeholder="t.ex. hans")
            with col_n:
                new_name = st.text_input("Visningsnamn", placeholder="t.ex. Hans")
            col_e, col_p = st.columns(2)
            with col_e:
                new_email = st.text_input("E-post", placeholder="hans@example.com")
            with col_p:
                new_pw = st.text_input("Lösenord", type="password", placeholder="Minst 6 tecken")

            if st.form_submit_button("Skapa användare", type="primary"):
                uname_clean = new_uname.strip().lower().replace(" ", "_")
                existing = [u["username"] for u in users]
                if not uname_clean:
                    st.error("Ange ett användarnamn.")
                elif uname_clean == "admin":
                    st.error("Användarnamnet 'admin' är reserverat.")
                elif uname_clean in existing:
                    st.error(f"Användarnamnet `{uname_clean}` används redan.")
                elif len(new_pw) < 6:
                    st.error("Lösenordet måste vara minst 6 tecken.")
                else:
                    users.append({
                        "username": uname_clean,
                        "name": new_name.strip() or uname_clean.capitalize(),
                        "email": new_email.strip().lower(),
                        "password": _hash_password(new_pw),
                        "active": True,
                        "added": str(date.today()),
                    })
                    _save_users_config(users)
                    st.success(f"Användaren **{uname_clean}** skapad!")
                    st.rerun()

        if users:
            st.markdown("---")
            st.markdown("#### Hantera befintliga användare")
            sel_uname = st.selectbox("Välj användare", [u["username"] for u in users])
            sel_user = next((u for u in users if u["username"] == sel_uname), None)
            if sel_user:
                is_active = sel_user.get("active", True)
                col_tog, col_del = st.columns(2)
                with col_tog:
                    btn_lbl = "Inaktivera" if is_active else "Aktivera"
                    if st.button(btn_lbl, use_container_width=True):
                        sel_user["active"] = not is_active
                        _save_users_config(users)
                        st.rerun()
                with col_del:
                    if st.button("Ta bort", use_container_width=True):
                        users = [u for u in users if u["username"] != sel_uname]
                        _save_users_config(users)
                        st.success(f"`{sel_uname}` borttagen.")
                        st.rerun()

    # ── Sub-tab 4: E-post ────────────────────────────────────────────────────
    with tab_email:
        st.markdown("#### E-postprenumeranter")
        try:
            from core.email_template import load_subscribers, save_subscribers

            subscribers = load_subscribers()
            st.caption(f"{len(subscribers)} prenumerant(er)")

            if subscribers:
                rows = []
                for s in subscribers:
                    email = s.get("email", "?")
                    name = s.get("name", "?")
                    subs = ", ".join(k for k, v in s.get("subscriptions", {}).items() if v)
                    rows.append({"E-post": email, "Namn": name, "Prenumerationer": subs or "--"})
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            else:
                st.info("Inga prenumeranter ännu.")

            st.markdown("---")
            st.markdown("#### Lägg till prenumerant")
            with st.form("form_add_sub"):
                col1, col2 = st.columns(2)
                with col1:
                    new_email = st.text_input("E-post", placeholder="namn@example.com")
                with col2:
                    new_name = st.text_input("Namn", placeholder="För- och efternamn")

                if st.form_submit_button("Lägg till", type="primary"):
                    if not new_email or "@" not in new_email:
                        st.error("Ange en giltig e-postadress.")
                    elif any(s["email"] == new_email for s in subscribers):
                        st.warning(f"`{new_email}` prenumererar redan.")
                    else:
                        from core.email_template import SUBSCRIPTION_TYPES
                        subscribers.append({
                            "email": new_email,
                            "name": new_name.strip() or new_email.split("@")[0],
                            "active": True,
                            "added": str(date.today()),
                            "subscriptions": {k: True for k in SUBSCRIPTION_TYPES},
                        })
                        save_subscribers(subscribers)
                        st.success(f"{new_email} tillagd!")
                        st.rerun()
        except Exception as e:
            st.info(f"Prenumeranttjänsten är inte tillgänglig: {e}")

        st.markdown("---")
        st.markdown("#### Leveranslogg")
        log = _load_email_delivery_log()
        if log:
            st.dataframe(pd.DataFrame(log[-20:]), use_container_width=True, hide_index=True)
            st.caption("Visar de 20 senaste utskicken.")
        else:
            st.info("Ingen e-postlogg ännu.")
