"""admin/email_tab.py - E-post tab for admin page."""
from datetime import date, datetime
from pathlib import Path

import streamlit as st

from web.utils import DATA_DIR


def render():
    st.subheader("E-postprenumeranter")
    st.caption("Hantera vem som får vilka e-postrapporter.")

    from core.email_template import (
        load_subscribers, save_subscribers, SUBSCRIPTION_TYPES,
    )

    subscribers = load_subscribers()
    st.markdown(f"**{len(subscribers)} prenumerant(er)**")

    if subscribers:
        rows = []
        for s in subscribers:
            email = s.get("email", "?")
            name = s.get("name", "?")
            uname = s.get("username", "?")
            active = "Aktiv" if s.get("active", True) else "Inaktiv"
            subs = ", ".join(k for k, v in s.get("subscriptions", {}).items() if v)
            rows.append({"E-post": email, "Namn": name, "Användare": uname,
                         "Status": active, "Prenumerationer": subs or "--"})
        import pandas as pd
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info("Inga prenumeranter ännu.")

    st.markdown("---")
    st.markdown("**Lägg till prenumerant**")
    with st.form("form_add_sub"):
        col1, col2, col3 = st.columns(3)
        with col1:
            new_email = st.text_input("E-post *", placeholder="namn@example.com")
        with col2:
            new_name = st.text_input("Namn", placeholder="För- och efternamn")
        with col3:
            new_uname = st.text_input("Användarnamn",
                                       placeholder="t.ex. hans")

        st.markdown("**Prenumerationer**")
        cols = st.columns(4)
        new_subs = {}
        for i, (key, label) in enumerate(SUBSCRIPTION_TYPES.items()):
            with cols[i % 4]:
                new_subs[key] = st.checkbox(label, value=True, key=f"sub_{key}")

        submitted = st.form_submit_button("Lägg till prenumerant",
                                           type="primary", use_container_width=True)

        if submitted:
            if not new_email or "@" not in new_email:
                st.error("Ange en giltig e-postadress.")
            elif any(s["email"] == new_email for s in subscribers):
                st.warning(f"`{new_email}` prenumererar redan.")
            else:
                subscribers.append({
                    "email": new_email,
                    "name": new_name.strip() or new_email.split("@")[0],
                    "username": new_uname.strip() or "",
                    "active": True,
                    "added": str(date.today()),
                    "subscriptions": new_subs,
                })
                save_subscribers(subscribers)
                st.success(f"{new_email} tillagd som prenumerant!")
                st.rerun()

    st.markdown("---")
    st.markdown("**E-postlogg**")
    log = _load_email_delivery_log()
    if log:
        import pandas as pd
        st.dataframe(pd.DataFrame(log[-20:]), use_container_width=True, hide_index=True)
    else:
        st.info("Ingen e-postlogg anu.")


def _load_email_delivery_log() -> list:
    path = DATA_DIR / "email_delivery_log.json"
    try:
        if path.exists():
            import json
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []
