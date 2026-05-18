"""web/pages/settings_page.py – Användarinställningar (e-post, notiser)"""

import streamlit as st

from core.email_template import load_subscribers, save_subscribers, SUBSCRIPTION_TYPES


def _get_user_email() -> str:
    """Hämtar e-postadressen för den inloggade användaren från credentials eller users_config."""
    username = st.session_state.get("username", "")
    # Försök hämta från Streamlit Secrets (admin)
    try:
        creds = st.secrets.get("credentials", {}).get("usernames", {})
        if username in creds and creds[username].get("email"):
            return creds[username]["email"]
    except Exception:
        pass
    # Försök hämta från users_config.json (hanterade användare)
    try:
        from pathlib import Path
        import json
        config_path = Path(__file__).resolve().parent.parent.parent / "data" / "users_config.json"
        data = json.loads(config_path.read_text(encoding="utf-8"))
        for u in data.get("users", []):
            if u.get("username") == username:
                return u.get("email", "")
    except Exception:
        pass
    return ""


def page_settings():
    st.title("⚙️ Inställningar")
    username = st.session_state.get("username", "")

    # ── E-postinställningar ───────────────────────────────────────────────────
    st.subheader("📧 E-postnotiser")
    st.caption(
        "Välj vilka e-postrapporter du vill ta emot. "
        "E-posten skickas automatiskt av MarketScan-pipelinen."
    )

    # Förifyll e-postadressen från kontoinställningarna
    default_email = _get_user_email()
    subscribers = load_subscribers()

    # Hitta befintlig post för den här användaren (matcha på username eller email)
    my_sub = next(
        (s for s in subscribers if s.get("username") == username),
        next(
            (s for s in subscribers if s.get("email") == default_email and default_email),
            None,
        ),
    )

    current_email = my_sub["email"] if my_sub else default_email
    current_subs  = my_sub.get("subscriptions", {}) if my_sub else {}
    is_active     = my_sub.get("active", True) if my_sub else True

    with st.form("form_email_settings"):
        email = st.text_input(
            "Din e-postadress",
            value=current_email,
            placeholder="namn@example.com",
        )

        st.markdown("**Prenumerationer**")
        new_subs = {}
        for key, label in SUBSCRIPTION_TYPES.items():
            new_subs[key] = st.checkbox(
                label,
                value=current_subs.get(key, False),
                key=f"sub_{key}",
            )

        active = st.checkbox(
            "Aktiv (avmarkera för att pausa alla notiser)",
            value=is_active,
            key="sub_active",
        )

        submitted = st.form_submit_button("💾 Spara inställningar", type="primary", use_container_width=True)

    if submitted:
        if not email or "@" not in email:
            st.error("Ange en giltig e-postadress.")
        else:
            # Uppdatera eller lägg till prenumerant
            updated = False
            for s in subscribers:
                if s.get("username") == username or s.get("email") == current_email:
                    s["email"]         = email
                    s["username"]      = username
                    s["active"]        = active
                    s["subscriptions"] = new_subs
                    updated = True
                    break
            if not updated:
                from datetime import date
                subscribers.append({
                    "email":         email,
                    "name":          st.session_state.get("name", username),
                    "username":      username,
                    "active":        active,
                    "added":         str(date.today()),
                    "subscriptions": new_subs,
                })

            ok = save_subscribers(subscribers)
            # Committa till GitHub så att pipeline alltid har uppdaterad lista
            try:
                from web.pages.admin import _get_github_token, _github_commit_file
                import json
                token = _get_github_token()
                if token:
                    content = json.dumps({"subscribers": subscribers}, indent=2, ensure_ascii=False)
                    _github_commit_file(
                        "data/email_subscribers.json",
                        content,
                        token,
                        message=f"Update email subscriptions for {username}",
                    )
            except Exception:
                pass

            if ok:
                st.success("✅ Inställningarna sparade!")
            else:
                st.warning("⚠️ Kunde inte spara lokalt, men ändringen skickades till GitHub.")

    # ── Status-visning ────────────────────────────────────────────────────────
    if my_sub or (submitted and email):
        # Uppdatera my_sub om vi precis sparade
        if submitted:
            subscribers = load_subscribers()
            my_sub = next(
                (s for s in subscribers if s.get("username") == username),
                None,
            )
        if my_sub:
            active_count = sum(1 for v in my_sub.get("subscriptions", {}).values() if v)
            if active_count > 0 and my_sub.get("active", True):
                st.info(
                    f"📬 Du prenumererar på **{active_count}** "
                    f"{'rapport' if active_count == 1 else 'rapporter'} "
                    f"till **{my_sub['email']}**."
                )
            elif not my_sub.get("active", True):
                st.warning("⏸️ Dina e-postnotiser är pausade.")
            else:
                st.info("Du har inga aktiva prenumerationer just nu.")
