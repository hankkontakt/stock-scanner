"""admin/users.py - Användare tab för admin page."""
import json
from datetime import date

import pandas as pd
import streamlit as st

from web.utils import DATA_DIR


def _hash_password(plain: str) -> str:
    """Hasha ett lösenord med bcrypt (rounds=12). Returnerar $2b$... sträng."""
    import bcrypt as _bcrypt
    return _bcrypt.hashpw(plain.encode("utf-8"), _bcrypt.gensalt(rounds=12)).decode("utf-8")


def render():
    st.subheader("Användare")
    st.caption("Hantera användarkonton för MarketScan.")

    try:
        from web.pages.admin import _load_users_config, _save_users_config
    except ImportError as e:
        st.error(f"Kunde inte ladda admin-funktioner: {e}")
        return

    users = _load_users_config()
    active_users = [u for u in users if u.get("active", True)]

    st.markdown(f"**{len(active_users)} aktiva användare** (utöver admin)")
    if active_users:
        user_rows = [
            {
                "Användarnamn": u["username"],
                "Namn": u.get("name", ""),
                "E-post": u.get("email", ""),
                "Tillagd": u.get("added", ""),
                "Aktiv": "JA",
            }
            for u in active_users
        ]
        st.dataframe(pd.DataFrame(user_rows), use_container_width=True, hide_index=True)
    else:
        st.info("Inga extra användare tillagda ännu.")

    st.markdown("---")
    st.markdown("### Lägg till ny användare")
    with st.form("form_add_user", clear_on_submit=True):
        col_u, col_n = st.columns(2)
        with col_u:
            new_uname = st.text_input("Användarnamn *", placeholder="t.ex. hans",
                                       help="Gemener, inga mellanslag.")
        with col_n:
            new_name = st.text_input("Visningsnamn", placeholder="t.ex. Hans")

        col_e, col_p = st.columns(2)
        with col_e:
            new_email = st.text_input("E-post (valfritt)", placeholder="hans@example.com")
        with col_p:
            new_pw = st.text_input("Lösenord *", type="password",
                                    placeholder="Minst 6 tecken",
                                    help="Lagras krypterat (bcrypt).")

        submitted_add = st.form_submit_button("Skapa användare", type="primary")
        if submitted_add:
            uname_clean = new_uname.strip().lower().replace(" ", "_")
            existing_names = [u["username"] for u in users]
            if not uname_clean:
                st.error("Ange ett användarnamn.")
            elif uname_clean == "admin":
                st.error("Användarnamnet 'admin' är reserverat.")
            elif uname_clean in existing_names:
                st.error(f"Användarnamnet `{uname_clean}` används redan.")
            elif len(new_pw) < 6:
                st.error("Lösenordet måste vara minst 6 tecken.")
            else:
                hashed_pw = _hash_password(new_pw)
                users.append({
                    "username": uname_clean,
                    "name": new_name.strip() or uname_clean.capitalize(),
                    "email": new_email.strip().lower(),
                    "password": hashed_pw,
                    "active": True,
                    "added": str(date.today()),
                })
                _save_users_config(users)
                st.success(f"Användaren **{uname_clean}** skapad!")
                st.rerun()

    if users:
        st.markdown("---")
        st.markdown("### Hantera befintliga användare")
        manage_options = [u["username"] for u in users]
        sel_uname = st.selectbox("Välj användare", manage_options, key="user_manage_sel")
        sel_user = next((u for u in users if u["username"] == sel_uname), None)

        if sel_user:
            is_active = sel_user.get("active", True)
            col_tog, col_del, col_pw = st.columns(3)
            with col_tog:
                btn_lbl = "Inaktivera" if is_active else "Aktivera"
                if st.button(btn_lbl, key="btn_user_toggle", use_container_width=True):
                    sel_user["active"] = not is_active
                    _save_users_config(users)
                    st.success(f"{'Inaktiverad' if not sel_user['active'] else 'Aktiverad'}: {sel_uname}")
                    st.rerun()
            with col_del:
                if st.button("Ta bort", key="btn_user_delete", use_container_width=True):
                    users = [u for u in users if u["username"] != sel_uname]
                    _save_users_config(users)
                    st.success(f"`{sel_uname}` borttagen.")
                    st.rerun()
            with col_pw:
                if st.button("Återställ lösenord", key="btn_user_reset", use_container_width=True):
                    st.write("Återställning görs via 'Glömt lösenord'-flödet.")
