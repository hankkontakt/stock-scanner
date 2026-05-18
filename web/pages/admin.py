"""web/pages/admin.py – Admin-sida + delade filhanteringsfunktioner"""

import json
import os
import tempfile
from datetime import date

import pandas as pd
import requests
import streamlit as st
import yfinance as yf

from pathlib import Path

from web.utils import (
    DATA_DIR, REPORT_DIR, load_watchlist, load_portfolio, _get_provider,
)
from core import config

USERS_CONFIG_FILE = DATA_DIR / "users_config.json"


def _load_users_config() -> list:
    """Ladda listan med admin-hanterade användare från data/users_config.json."""
    try:
        return json.loads(USERS_CONFIG_FILE.read_text(encoding="utf-8")).get("users", [])
    except Exception:
        return []


def _save_users_config(users: list):
    """Spara användarkonfigurationen lokalt och committa till GitHub."""
    content = json.dumps({"users": users}, indent=2, ensure_ascii=False)
    USERS_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    USERS_CONFIG_FILE.write_text(content, encoding="utf-8")
    token = _get_github_token()
    if token:
        _github_commit_file("data/users_config.json", content, token)


# ══════════════════════════════════════════════════════════════════════════════
# DELADE HJÄLPFUNKTIONER (filhantering, GitHub, sökning)
# ══════════════════════════════════════════════════════════════════════════════

def _github_commit_file(repo_path: str, content: str, token: str,
                         owner: str = "hankkontakt", repo: str = "stock-scanner") -> bool:
    """Committar en fil till GitHub via Contents API så att ändringar överlever Streamlit Cloud-omstarter."""
    import base64
    if not token:
        return False
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "MarketScan-Streamlit",
    }
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{repo_path}"
    try:
        sha = None
        get_resp = requests.get(url, headers=headers, timeout=10)
        if get_resp.status_code == 200:
            sha = get_resp.json().get("sha")
        payload = {
            "message": f"chore: update {repo_path} via Streamlit",
            "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
            "branch": "main",
        }
        if sha:
            payload["sha"] = sha
        resp = requests.put(url, json=payload, headers=headers, timeout=15)
        return resp.status_code in (200, 201)
    except Exception:
        return False


def _get_github_token() -> str:
    """Hämtar GITHUB_TOKEN från Streamlit Secrets eller miljövariabel."""
    token = os.getenv("GITHUB_TOKEN", "")
    if not token:
        try:
            token = st.secrets.get("GITHUB_TOKEN", "")
        except Exception:
            pass
    return token or ""


def _save_holdings_df(df: pd.DataFrame) -> bool:
    """Spara holdings.csv lokalt och committa till GitHub för Streamlit Cloud-persistens.
    Sparar i användarens katalog (admin → data/, övriga → data/users/{username}/).
    GitHub-commit görs bara för admin (den globala data/holdings.csv speglas i repot)."""
    from web.utils import _active_data_dir
    user_dir = _active_data_dir()
    csv_content = df.to_csv(index=False)
    try:
        (user_dir / "holdings.csv").write_text(csv_content, encoding="utf-8")
    except Exception:
        pass
    # Committa till GitHub bara för admin (data/ finns i repot, data/users/ gör det inte)
    if st.session_state.get("username", "admin") == "admin":
        token = _get_github_token()
        if token:
            ok = _github_commit_file("data/holdings.csv", csv_content, token)
            if not ok:
                st.warning("⚠️ Kunde inte synka till GitHub – ändringen kan försvinna vid omstart.")
    return True


def _save_watchlist_data(items: list):
    """Spara watchlist.json i användarens katalog.
    GitHub-commit görs bara för admin."""
    from web.utils import _active_data_dir
    user_dir = _active_data_dir()
    content = json.dumps(items, indent=2, ensure_ascii=False)
    path = user_dir / "watchlist.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(content, encoding="utf-8")
    except Exception:
        pass
    if st.session_state.get("username", "admin") == "admin":
        token = _get_github_token()
        if token:
            _github_commit_file("data/watchlist.json", content, token)


def _search_ticker_yfinance(query: str):
    """Sök ticker via yfinance. Returnerar hits_list."""
    if not query or len(query) < 2:
        return []

    hits = []
    error = None
    try:
        clean_q = query.strip().upper()

        is_ticker_like = (
            " " not in clean_q and len(clean_q) <= 15 and
            (clean_q.replace(".", "").replace("-", "").isalpha())
        )
        if is_ticker_like:
            try:
                info = yf.Ticker(clean_q).fast_info
                hits.append({
                    "ticker": clean_q,
                    "name": getattr(info, "exchange", clean_q) or clean_q,
                    "exchange": getattr(info, "exchange", ""),
                })
            except Exception:
                pass

        try:
            results = yf.Search(query, max_results=20).quotes or []
        except Exception as e:
            error = str(e)
            results = []

        seen = {h["ticker"] for h in hits}
        for r in results:
            sym = r.get("symbol", "")
            if not sym or sym in seen:
                continue
            if r.get("quoteType", "") in ("EQUITY", "ETF", "MUTUALFUND", "INDEX"):
                hits.append({
                    "ticker": sym,
                    "name": r.get("shortname") or r.get("longname") or "",
                    "exchange": r.get("exchange", ""),
                })
                seen.add(sym)

        hits.sort(key=lambda h: (
            0 if h.get("exchange", "") in ("STO", "OMX", "HE", "CO", "OL", "DE", "PA", "L", "SW") else 1
        ))
        return hits[:15]

    except Exception as e:
        return hits


def _check_admin_access() -> bool:
    """Kontrollera om den inloggade användaren är admin.

    - Med multi-user-auth: username == 'admin' i session_state
    - Lokalt (ingen auth konfigurerad): alltid True
    """
    username = st.session_state.get("username", "")

    # Om ingen autentisering är aktiv (lokal körning utan credentials-secret)
    # → kontrollera gammal ADMIN_PASSWORD-logik som fallback
    if not username:
        admin_pw = ""
        try:
            admin_pw = st.secrets.get("ADMIN_PASSWORD", "")
        except Exception:
            pass
        if not admin_pw:
            admin_pw = os.getenv("ADMIN_PASSWORD", "")
        if not admin_pw:
            return True  # Lokal körning utan lösenord → öppet
        if st.session_state.get("admin_authenticated", False):
            return True
        st.title("🔒 Admin – Lösenordsskyddad sida")
        st.info("Logga in med admin-kontot för att se den här sidan.")
        return False

    # Multi-user-läge: kräv username == 'admin'
    if username == "admin":
        return True

    st.error("⛔ Åtkomst nekad – endast admin kan se den här sidan.")
    st.stop()
    return False


def _trigger_gh_workflow(token: str, owner: str, repo: str,
                         workflow: str, label: str, inputs: dict = None):
    """Trigga en GitHub Actions workflow_dispatch."""
    url = f"https://api.github.com/repos/{owner}/{repo}/actions/workflows/{workflow}/dispatches"
    payload = {"ref": "main"}
    if inputs:
        payload["inputs"] = inputs
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "MarketScan-Streamlit",
    }
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
        if resp.status_code in (204, 201, 200):
            st.success(f"✅ **{label}** startad via GitHub Actions!")
        else:
            st.error(f"❌ Kunde inte starta {label}: HTTP {resp.status_code}"
                     f"\n{resp.text[:200]}")
    except Exception as e:
        st.error(f"❌ Nätverksfel: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# ADMIN-SIDA
# ══════════════════════════════════════════════════════════════════════════════

def page_admin():
    """Admin-sida – kräver lösenord."""

    if not _check_admin_access():
        if st.session_state.get("admin_authenticated", False):
            if st.button("🚪 Logga ut från admin", key="btn_admin_logout"):
                st.session_state["admin_authenticated"] = False
                st.rerun()
        return

    st.title("🔧 Admin – Hantera portfölj, bevakning & scannar")

    tab_wl, tab_hold, tab_scan, tab_import, tab_health, tab_email, tab_users = st.tabs([
        "⭐ Bevakningslista", "💼 Portfölj", "🚀 Starta scan", "📥 Avanza-import",
        "🩺 Universe Health", "📧 E-post", "👥 Användare"
    ])

    # ── Flik 1: Bevakningslista ────────────────────────────────────────────────
    with tab_wl:
        st.subheader("⭐ Bevakningslista")

        items = load_watchlist()

        if items:
            wl_df = pd.DataFrame(items)
            st.dataframe(wl_df, use_container_width=True, hide_index=True)

            remove_ticker = st.selectbox(
                "Ta bort ticker", [""] + [i["ticker"] for i in items],
                key="wl_remove"
            )
            if remove_ticker and st.button("🗑️ Ta bort", key="btn_wl_remove"):
                items = [i for i in items if i["ticker"] != remove_ticker]
                _save_watchlist_data(items)
                st.success(f"`{remove_ticker}` borttagen från bevakningslistan!")
                st.rerun()
        else:
            st.info("Bevakningslistan är tom.")

        st.markdown("---")
        st.markdown("### Lägg till ny ticker")

        search_q = st.text_input("Sök aktie (ticker eller namn)", key="wl_search",
                                 placeholder="t.ex. AAPL, VOLV-B.ST, Investor")
        if search_q:
            hits = _search_ticker_yfinance(search_q)
            if hits:
                options = {f"{h['ticker']} — {h['name'][:40]}": h for h in hits}
                selected = st.selectbox("Välj från sökresultat", list(options.keys()),
                                        key="wl_hit")
                if selected:
                    h = options[selected]
                    col1, col2 = st.columns([2, 1])
                    if col1.button("✅ Lägg till i bevakningslistan", key="btn_wl_add"):
                        new_ticker = h["ticker"]
                        exists = any(i["ticker"] == new_ticker for i in items)
                        if not exists:
                            items.append({
                                "ticker": new_ticker,
                                "name": h["name"],
                                "added": str(date.today()),
                            })
                            _save_watchlist_data(items)
                            st.success(f"`{new_ticker}` tillagd i bevakningslistan!")
                            st.rerun()
                        else:
                            st.info(f"`{new_ticker}` finns redan i bevakningslistan.")
            else:
                st.caption("Inga sökresultat. Prova med annat sökord.")

        with st.expander("Eller lägg till manuellt (ticker)"):
            manual_ticker = st.text_input("Ticker (t.ex. AAPL)", key="wl_manual",
                                          max_chars=15,
                                          placeholder="Ticker-symbol").upper().strip()
            manual_name = st.text_input("Namn (valfritt)", key="wl_manual_name")
            if st.button("➕ Lägg till", key="btn_wl_manual"):
                if manual_ticker:
                    exists = any(i["ticker"] == manual_ticker for i in items)
                    if not exists:
                        items.append({
                            "ticker": manual_ticker,
                            "name": manual_name or manual_ticker,
                            "added": str(date.today()),
                        })
                        _save_watchlist_data(items)
                        st.success(f"`{manual_ticker}` tillagd!")
                        st.rerun()
                    else:
                        st.info(f"`{manual_ticker}` finns redan.")
                else:
                    st.warning("Ange en ticker.")

    # ── Flik 2: Portfölj ──────────────────────────────────────────────────
    with tab_hold:
        st.subheader("💼 Portfölj (holdings.csv)")

        holdings = load_portfolio()

        col_del_left, col_del_right = st.columns([3, 1])
        with col_del_left:
            if not holdings.empty:
                remove_h = st.selectbox(
                    "Välj innehav att ta bort",
                    [""] + holdings["ticker"].tolist(),
                    key="hold_remove"
                )
            else:
                remove_h = ""
        with col_del_right:
            if remove_h and st.button("🗑️ Ta bort", key="btn_hold_remove",
                                      use_container_width=True):
                holdings = load_portfolio()
                if remove_h in holdings["ticker"].values:
                    holdings = holdings[holdings["ticker"] != remove_h]
                    ok = _save_holdings_df(holdings)
                    if ok:
                        st.cache_data.clear()
                        st.success(f"`{remove_h}` borttagen från portföljen!")
                        st.rerun()
                    else:
                        st.error("Kunde inte spara. Kontrollera filrättigheter.")
                else:
                    st.info(f"`{remove_h}` finns inte i portföljen.")

        if not holdings.empty:
            st.dataframe(holdings, use_container_width=True, hide_index=True)
        else:
            st.info("Portföljen är tom. Lägg till innehav nedan.")

        st.markdown("---")
        st.markdown("### Lägg till / uppdatera innehav")

        search_h = st.text_input("Sök aktie (ticker eller namn) – valfritt", key="hold_search",
                                 placeholder="t.ex. AAPL, VOLV-B.ST, Investor")
        suggested_ticker = ""
        if search_h:
            hits, search_err = _search_ticker_yfinance(search_h), None
            if isinstance(hits, tuple):
                hits, search_err = hits
            if hits:
                options = {f"{h['ticker']} — {h['name'][:40]}": h for h in hits}
                selected = st.selectbox("Välj från sökresultat", [""] + list(options.keys()),
                                        key="hold_hit")
                if selected:
                    suggested_ticker = options[selected]["ticker"]
            else:
                if search_err:
                    st.warning(f"Sökning misslyckades: {search_err} — ange ticker manuellt nedan.")
                else:
                    st.caption("Inga träffar. Prova att skriva bolagsnamnet på engelska, eller ange tickern direkt (t.ex. INVE-B.ST).")

        if suggested_ticker:
            st.session_state["hold_ticker_input"] = suggested_ticker

        col1, col2, col3 = st.columns(3)
        with col1:
            ticker = st.text_input(
                "Ticker *",
                key="hold_ticker_input",
                placeholder="AAPL"
            ).upper().strip()
        with col2:
            shares = st.number_input("Antal aktier", min_value=0.0, max_value=10_000_000.0,
                                     step=1.0, format="%.2f", key="hold_shares")
        with col3:
            cost = st.number_input("Inköpspris (SEK)", min_value=0.0, max_value=10_000_000.0,
                                   step=1.0, format="%.2f", key="hold_cost")

        saved = st.button("💾 Spara i portföljen", key="btn_hold_save",
                          use_container_width=True, type="primary")

        if saved:
            ticker = st.session_state.get("hold_ticker_input", "").upper().strip()
            shares = st.session_state.get("hold_shares", 0)
            cost = st.session_state.get("hold_cost", 0)

            if not ticker:
                st.warning("Ange en ticker.")
            elif shares <= 0:
                st.warning("Ange antal aktier (> 0).")
            elif cost <= 0:
                st.warning("Ange inköpspris (> 0).")
            else:
                holdings = load_portfolio()
                if ticker in holdings["ticker"].values:
                    holdings.loc[holdings["ticker"] == ticker, "shares"] = shares
                    holdings.loc[holdings["ticker"] == ticker, "cost_basis"] = cost
                    msg = f"`{ticker}` uppdaterad i portföljen!"
                else:
                    new_row = pd.DataFrame([{"ticker": ticker, "shares": shares,
                                              "cost_basis": cost}])
                    holdings = pd.concat([holdings, new_row], ignore_index=True)
                    msg = f"`{ticker}` tillagd i portföljen!"
                ok = _save_holdings_df(holdings)
                if ok:
                    st.cache_data.clear()
                    st.success(msg)
                    st.rerun()
                else:
                    st.error("Kunde inte spara portföljen. Se felmeddelandet ovan.")

    # ── Flik 3: GitHub Actions – starta scannar ─────────────────────────────
    with tab_scan:
        st.subheader("🚀 Starta scanning via GitHub Actions")
        st.caption("Triggar en scanning i GitHub. Scannern körs i molnet (även när din dator är avstängd).")

        _secrets_token = ""
        try:
            if hasattr(st, "secrets"):
                _secrets_token = st.secrets.get("GITHUB_TOKEN", "")
        except Exception:
            _secrets_token = ""
        gh_token = os.getenv("GITHUB_TOKEN") or _secrets_token
        gh_owner = os.getenv("GITHUB_OWNER") or "hankkontakt"
        gh_repo  = os.getenv("GITHUB_REPO")  or "stock-scanner"

        if not gh_token:
            gh_token = st.text_input(
                "GitHub token (krävs för att starta scannar)",
                type="password",
                key="gh_token_input",
                placeholder="ghp_...",
            )
        else:
            st.success("✅ GitHub token läst från miljövariabel/Secrets")

        col_a, col_b = st.columns(2)

        with col_a:
            st.markdown("**🌅 Morgonbrief (vardagar)**")
            if st.button("▶️ Starta morgonbrief", key="btn_morning",
                         disabled=not gh_token, use_container_width=True):
                _trigger_gh_workflow(gh_token, gh_owner, gh_repo,
                                     "daily_scan.yml", "Morgonbrief",
                                     inputs={"mode": "morning"})
                st.toast("Morgonbrief startad! ⏳", icon="🌅")

            st.markdown("**🌆 Kvällsbrev (vardagar)**")
            if st.button("▶️ Starta kvällsbrev", key="btn_evening",
                         disabled=not gh_token, use_container_width=True):
                _trigger_gh_workflow(gh_token, gh_owner, gh_repo,
                                     "daily_scan.yml", "Kvällsbrev",
                                     inputs={"mode": "evening"})
                st.toast("Kvällsbrev startad! ⏳", icon="🌆")

        with col_b:
            st.markdown("**📊 Veckoscan (lördagar)**")
            if st.button("▶️ Starta veckoscan", key="btn_weekly",
                         disabled=not gh_token, use_container_width=True):
                _trigger_gh_workflow(gh_token, gh_owner, gh_repo,
                                     "daily_scan.yml", "Veckoscan",
                                     inputs={"mode": "weekly"})
                st.toast("Veckoscan startad! ⏳", icon="📊")

            st.markdown("**🏆 Småbolagsscan (måndagar)**")
            if st.button("▶️ Starta småbolagsscan", key="btn_smallcap",
                         disabled=not gh_token, use_container_width=True):
                _trigger_gh_workflow(gh_token, gh_owner, gh_repo,
                                     "daily_scan.yml", "Småbolagsscan",
                                     inputs={"mode": "smallcap"})
                st.toast("Småbolagsscan startad! ⏳", icon="🏆")

        st.markdown("---")
        st.info(
            "Scan-resultaten visas här när GitHub Actions har kört klart och "
            "committat tillbaka CSV-filerna (tar 2–10 min beroende på scannern). "
            "Uppdatera sidan för att se nya resultat."
        )

    # ── Flik 4: Avanza-import ──────────────────────────────────────────────
    with tab_import:
        st.subheader("📥 Importera portfölj från Avanza CSV")
        st.caption("Exportera din portfölj från Avanza som CSV och ladda upp här.")

        from data_management import avanza_import

        uploaded = st.file_uploader("Välj Avanza CSV-fil", type=["csv"],
                                    key="avanza_csv")
        if uploaded is not None:
            try:
                with tempfile.NamedTemporaryFile(mode="wb", suffix=".csv", delete=False) as tmp:
                    tmp.write(uploaded.getvalue())
                    tmp_path = tmp.name
                try:
                    df_avanza = avanza_import.parse_avanza_csv(tmp_path)
                finally:
                    os.unlink(tmp_path)

                if df_avanza.empty:
                    st.error(
                        "Kunde inte läsa filen. Kontrollera att det är en "
                        "Avanza-export (kolumner: namn, antal, inköpspris)."
                    )
                else:
                    st.success(f"Läste {len(df_avanza)} rader från Avanza-filen.")
                    st.caption("Granska och bekräfta importen nedan.")

                    rows = []
                    for _, r in df_avanza.iterrows():
                        rows.append({
                            "name": r.get("name", ""),
                            "shares": r.get("shares", 0),
                            "cost_basis": r.get("cost_basis", 0),
                        })

                    import_data = []
                    for i, row in enumerate(rows):
                        hits = _search_ticker_yfinance(row["name"])
                        suggested = hits[0]["ticker"] if hits else ""
                        with st.container(border=True):
                            cc1, cc2, cc3, cc4, cc5 = st.columns([3, 1, 1, 2, 2])
                            with cc1:
                                st.markdown(f"**{row['name']}**")
                            with cc2:
                                st.markdown(f"Antal: {row['shares']}")
                            with cc3:
                                st.markdown(f"Pris: {row['cost_basis']}")
                            with cc4:
                                ticker_val = st.text_input(
                                    "Ticker", value=suggested,
                                    key=f"import_ticker_{i}",
                                    label_visibility="collapsed",
                                ).upper().strip()
                            with cc5:
                                import_me = st.checkbox("Importera", value=True,
                                                        key=f"import_ok_{i}")
                            import_data.append({
                                "row": row,
                                "ticker": ticker_val,
                                "import": import_me,
                            })

                    if st.button("✅ Bekräfta import", type="primary",
                                 use_container_width=True):
                        holdings = load_portfolio()
                        n_add = 0
                        n_upd = 0
                        for item in import_data:
                            if not item["import"] or not item["ticker"]:
                                continue
                            t = item["ticker"]
                            s = float(item["row"]["shares"])
                            c = item["row"]["cost_basis"]
                            if t in holdings["ticker"].values:
                                holdings.loc[holdings["ticker"] == t, "shares"] = s
                                holdings.loc[holdings["ticker"] == t, "cost_basis"] = c
                                n_upd += 1
                            else:
                                new_row = pd.DataFrame([{
                                    "ticker": t, "shares": s, "cost_basis": c
                                }])
                                holdings = pd.concat([holdings, new_row], ignore_index=True)
                                n_add += 1
                        _save_holdings_df(holdings)
                        st.success(f"Import klar! {n_add} tillagda, {n_upd} uppdaterade.")
                        st.rerun()
            except Exception as e:
                    st.error(f"Fel vid läsning av fil: {e}")

    # ── Flik 5: Universe Health ────────────────────────────────────────────
    with tab_health:
        st.subheader("🩺 Universe Health – underhåll av aktieuniversum")
        st.caption(
            "Upptäck avnoterade/ogiltiga tickers, hantera svartlista "
            "och hitta nya intressanta aktier med AI-hjälp."
        )

        try:
            from core.universe_health import (
                detect_invalid_tickers, suggest_replacements,
                find_new_stocks, run_health_check,
                load_blacklist, add_to_blacklist, remove_from_blacklist,
            )
        except ImportError as e:
            st.error(f"Kunde inte ladda universe_health-modulen: {e}")
            return

        blacklist = load_blacklist()
        st.markdown(f"**Svartlista:** {len(blacklist)} tickers")

        with st.expander("📋 Visa svartlista", expanded=False):
            if blacklist:
                st.dataframe(pd.DataFrame(blacklist), use_container_width=True, hide_index=True)

                remove_bl = st.selectbox(
                    "Ta bort från svartlistan",
                    [""] + [i.get("ticker", "") for i in blacklist],
                    key="bl_remove",
                )
                if remove_bl and st.button("🗑️ Ta bort", key="btn_bl_remove"):
                    if remove_from_blacklist(remove_bl):
                        st.success(f"`{remove_bl}` borttagen från svartlistan!")
                        st.rerun()
            else:
                st.info("Svartlistan är tom.")

        with st.expander("➕ Lägg till i svartlistan manuellt", expanded=False):
            col_bl_t, col_bl_r = st.columns([2, 3])
            with col_bl_t:
                bl_ticker = st.text_input("Ticker", key="bl_add_ticker",
                                          max_chars=15,
                                          placeholder="AAPL").upper().strip()
            with col_bl_r:
                bl_reason = st.text_input("Anledning", key="bl_add_reason",
                                          placeholder="t.ex. avnoterad")
            if st.button("➕ Lägg till i svartlistan", key="btn_bl_add"):
                if bl_ticker:
                    if add_to_blacklist(bl_ticker, bl_reason or "manuell"):
                        st.success(f"`{bl_ticker}` tillagd i svartlistan!")
                        st.rerun()
                    else:
                        st.info(f"`{bl_ticker}` finns redan i svartlistan.")
                else:
                    st.warning("Ange en ticker.")

        st.markdown("---")

        st.markdown("### 🔍 Kör hälsokontroll")
        st.caption("Kontrollerar alla tickers i senaste scandatan mot yfinance.")

        health_provider = st.selectbox(
            "AI-provider för nya aktieförslag",
            ["auto", "deepseek", "gemini"],
            format_func=lambda k: {
                "auto": f"Auto ({config.AI_PROVIDER})",
                "deepseek": "DeepSeek (komplex, kostar)",
                "gemini": "Gemini (enkel, gratis)",
            }.get(k, k),
            key="health_provider",
        )

        if st.button("🩺 Kör hälsokontroll", key="btn_health_check",
                     type="primary", use_container_width=True):
            with st.spinner("Kör hälsokontroll (kan ta några minuter)..."):
                try:
                    reports = sorted(REPORT_DIR.glob("scored_universe_*.csv"), reverse=True)
                    if not reports:
                        st.warning("Ingen scandata hittad. Kör en scan först.")
                    else:
                        df_health = pd.read_csv(reports[0], low_memory=False)
                        df_health.columns = df_health.columns.str.strip()

                        result = run_health_check(df=df_health, provider=health_provider)
                        st.success("✅ Hälsokontroll klar!")

                        col_h1, col_h2, col_h3 = st.columns(3)
                        with col_h1:
                            st.metric("Ogiltiga tickers", len(result.get("invalid_tickers", [])))
                        with col_h2:
                            st.metric("Svartlistade", result.get("blacklist_count", 0))
                        with col_h3:
                            st.metric("Nya AI-förslag", len(result.get("new_stocks", [])))

                        invalid = result.get("invalid_tickers", [])
                        if invalid:
                            st.markdown("---")
                            st.error(f"⚠️ Hittade {len(invalid)} ogiltiga/avnoterade tickers!")
                            inv_df = pd.DataFrame(invalid)
                            st.dataframe(inv_df, use_container_width=True, hide_index=True)

                            st.markdown("### 💡 Ersättningsförslag")
                            suggestions = result.get("suggestions", {})
                            for bad_ticker, replacements in suggestions.items():
                                with st.expander(f"`{bad_ticker}` → ersättningsförslag", expanded=True):
                                    if replacements:
                                        rep_df = pd.DataFrame(replacements)
                                        st.dataframe(rep_df, use_container_width=True, hide_index=True)
                                        if st.button(f"➕ Lägg till `{replacements[0]['ticker']}` i bevakningslistan",
                                                     key=f"health_add_{bad_ticker}"):
                                            items = load_watchlist()
                                            if not any(i["ticker"] == replacements[0]["ticker"] for i in items):
                                                items.append({
                                                    "ticker": replacements[0]["ticker"],
                                                    "name": replacements[0].get("name", ""),
                                                    "added": str(date.today()),
                                                })
                                                _save_watchlist_data(items)
                                                st.success(f"{replacements[0]['ticker']} tillagd i bevakningslistan!")
                                                st.rerun()
                                            else:
                                                st.info("Finns redan i bevakningslistan.")
                                    else:
                                        st.caption("Inga ersättningsförslag tillgängliga.")
                        else:
                            st.success("✅ Alla tickers verkar vara giltiga!")

                        new_stocks = result.get("new_stocks", [])
                        if new_stocks:
                            st.markdown("---")
                            st.subheader("🚀 AI-förslag: nya intressanta aktier")
                            st.caption("AI-genererade förslag på aktier att titta närmare på.")
                            for s in new_stocks:
                                ticker_s = s.get("ticker", "?")
                                name_s = s.get("name", "")
                                reason_s = s.get("reason", "")
                                with st.container(border=True):
                                    col_s1, col_s2 = st.columns([3, 1])
                                    with col_s1:
                                        st.markdown(f"**{ticker_s}** – {name_s}")
                                        if reason_s:
                                            st.caption(reason_s)
                                    with col_s2:
                                        if st.button("➕ Lägg till", key=f"health_new_{ticker_s}"):
                                            items = load_watchlist()
                                            if not any(i["ticker"] == ticker_s for i in items):
                                                items.append({
                                                    "ticker": ticker_s,
                                                    "name": name_s or ticker_s,
                                                    "added": str(date.today()),
                                                })
                                                _save_watchlist_data(items)
                                                st.success(f"{ticker_s} tillagd i bevakningslistan!")
                                                st.rerun()
                                            else:
                                                st.info("Finns redan i bevakningslistan.")

                except Exception as e:
                    st.error(f"❌ Hälsokontroll misslyckades: {e}")

        st.markdown("---")
        st.markdown("### ⚡ Snabbkontroll")
        st.caption("Kontrollera om specifika tickers är ogiltiga (utan AI-förslag).")
        if st.button("🔍 Kör snabbkontroll", key="btn_health_quick",
                     use_container_width=True):
            with st.spinner("Kontrollerar tickers..."):
                try:
                    reports = sorted(REPORT_DIR.glob("scored_universe_*.csv"), reverse=True)
                    if reports:
                        df_quick = pd.read_csv(reports[0], low_memory=False)
                        df_quick.columns = df_quick.columns.str.strip()
                        invalid = detect_invalid_tickers(df_quick)
                        if invalid:
                            st.error(f"⚠️ Hittade {len(invalid)} ogiltiga tickers")
                            st.dataframe(pd.DataFrame(invalid), use_container_width=True, hide_index=True)
                        else:
                            st.success("✅ Alla tickers verkar giltiga!")
                except Exception as e:
                    st.error(f"❌ {e}")

    # ── Flik 6: E-post-prenumeranter ──────────────────────────────────────────
    with tab_email:
        st.subheader("📧 E-post-prenumeranter")
        st.caption(
            "Hantera vilka som får rapporter och vilka typer de prenumererar på. "
            "Listan sparas i repot via GitHub API – inga ändringar i Secrets krävs."
        )

        try:
            from core.email_template import (
                load_subscribers, save_subscribers, SUBSCRIPTION_TYPES,
                email_configured, send_email as _send_test_email,
            )
        except ImportError as e:
            st.error(f"Kunde inte ladda email_template: {e}")
            return

        if not email_configured():
            st.warning(
                "⚠️ Email är inte konfigurerat. "
                "Sätt `EMAIL_SENDER` och `EMAIL_PASSWORD` i Streamlit Secrets eller config.py."
            )

        subs = load_subscribers()

        if subs:
            sub_rows = []
            for s in subs:
                row = {
                    "E-post": s.get("email", ""),
                    "Namn": s.get("name", ""),
                    "Aktiv": "✅" if s.get("active", True) else "❌",
                    "Tillagd": s.get("added", ""),
                }
                for key, label in SUBSCRIPTION_TYPES.items():
                    row[label] = "✓" if s.get("subscriptions", {}).get(key, False) else ""
                sub_rows.append(row)
            st.dataframe(pd.DataFrame(sub_rows), use_container_width=True, hide_index=True)
        else:
            st.info("Inga prenumeranter ännu. Lägg till den första nedan.")

        st.markdown("---")

        with st.expander("➕ Lägg till ny prenumerant", expanded=len(subs) == 0):
            with st.form("form_add_subscriber", clear_on_submit=True):
                col_e, col_n = st.columns([3, 2])
                with col_e:
                    new_email = st.text_input("E-postadress *", placeholder="namn@example.com")
                with col_n:
                    new_name = st.text_input("Namn (valfritt)", placeholder="Henrik")

                st.markdown("**Prenumerationstyper:**")
                sub_cols = st.columns(2)
                new_subs: dict[str, bool] = {}
                for i, (key, label) in enumerate(SUBSCRIPTION_TYPES.items()):
                    with sub_cols[i % 2]:
                        new_subs[key] = st.checkbox(label, value=(key in ("morning_report", "failure_alerts")),
                                                    key=f"new_sub_{key}")

                submitted_add = st.form_submit_button("➕ Lägg till", type="primary")
                if submitted_add:
                    new_email = new_email.strip().lower()
                    if not new_email or "@" not in new_email:
                        st.error("Ange en giltig e-postadress.")
                    elif any(s["email"] == new_email for s in subs):
                        st.warning(f"`{new_email}` finns redan.")
                    else:
                        subs.append({
                            "email": new_email,
                            "name": new_name.strip(),
                            "active": True,
                            "added": str(date.today()),
                            "subscriptions": new_subs,
                        })
                        save_subscribers(subs)
                        token = _get_github_token()
                        if token:
                            content = json.dumps({"subscribers": subs}, indent=2, ensure_ascii=False)
                            ok = _github_commit_file("data/email_subscribers.json", content, token)
                            if ok:
                                st.success(f"✅ `{new_email}` tillagd och synkad till GitHub!")
                            else:
                                st.success(f"✅ `{new_email}` tillagd lokalt (GitHub-sync misslyckades).")
                        else:
                            st.success(f"✅ `{new_email}` tillagd lokalt.")
                        st.rerun()

        if subs:
            st.markdown("---")
            st.markdown("### Hantera befintliga prenumeranter")

            email_options = [s["email"] for s in subs]
            sel_email = st.selectbox("Välj prenumerant att hantera", email_options, key="sub_select")
            sel_sub = next((s for s in subs if s["email"] == sel_email), None)

            if sel_sub:
                col_act, col_del, col_test = st.columns(3)

                with col_act:
                    is_active = sel_sub.get("active", True)
                    btn_label = "⏸ Inaktivera" if is_active else "▶️ Aktivera"
                    if st.button(btn_label, key="btn_sub_toggle"):
                        sel_sub["active"] = not is_active
                        save_subscribers(subs)
                        token = _get_github_token()
                        if token:
                            content = json.dumps({"subscribers": subs}, indent=2, ensure_ascii=False)
                            _github_commit_file("data/email_subscribers.json", content, token)
                        st.rerun()

                with col_del:
                    if st.button("🗑️ Ta bort", key="btn_sub_delete"):
                        subs = [s for s in subs if s["email"] != sel_email]
                        save_subscribers(subs)
                        token = _get_github_token()
                        if token:
                            content = json.dumps({"subscribers": subs}, indent=2, ensure_ascii=False)
                            _github_commit_file("data/email_subscribers.json", content, token)
                        st.success(f"`{sel_email}` borttagen!")
                        st.rerun()

                with col_test:
                    if st.button("📤 Skicka testmail", key="btn_sub_test"):
                        if email_configured():
                            ok = _send_test_email(
                                subject="📧 MarketScan – testmail",
                                body_markdown=(
                                    "# Testmail\n\nDetta är ett testmail från MarketScan admin-panelen.\n\n"
                                    "Om du ser detta mail fungerar e-postkonfigurationen korrekt!"
                                ),
                                from_name="MarketScan",
                                recipients=[sel_email],
                            )
                            if ok:
                                st.success(f"✅ Testmail skickat till `{sel_email}`!")
                            else:
                                st.error("❌ Misslyckades. Kontrollera EMAIL_SENDER/EMAIL_PASSWORD.")
                        else:
                            st.error("Email är inte konfigurerat.")

                with st.expander(f"Redigera prenumerationer för {sel_email}", expanded=False):
                    with st.form(f"form_edit_{sel_email.replace('@','_').replace('.','_')}"):
                        st.markdown("**Välj prenumerationstyper:**")
                        edit_cols = st.columns(2)
                        edit_subs: dict[str, bool] = {}
                        for i, (key, label) in enumerate(SUBSCRIPTION_TYPES.items()):
                            with edit_cols[i % 2]:
                                current = sel_sub.get("subscriptions", {}).get(key, False)
                                edit_subs[key] = st.checkbox(label, value=current, key=f"edit_{key}_{sel_email}")
                        if st.form_submit_button("💾 Spara ändringar"):
                            sel_sub["subscriptions"] = edit_subs
                            save_subscribers(subs)
                            token = _get_github_token()
                            if token:
                                content = json.dumps({"subscribers": subs}, indent=2, ensure_ascii=False)
                                _github_commit_file("data/email_subscribers.json", content, token)
                            st.success("✅ Prenumerationer uppdaterade!")
                            st.rerun()

        st.markdown("---")
        st.markdown("### 📊 Statistik")
        col_s1, col_s2, col_s3 = st.columns(3)
        with col_s1:
            st.metric("Totalt prenumeranter", len(subs))
        with col_s2:
            st.metric("Aktiva", sum(1 for s in subs if s.get("active", True)))
        with col_s3:
            st.metric("Email konfigurerat", "✅ Ja" if email_configured() else "❌ Nej")

    # ── Flik 7: Användare ─────────────────────────────────────────────────────
    with tab_users:
        st.subheader("👥 Användare")
        st.caption(
            "Lägg till och hantera inloggningsuppgifter för andra användare. "
            "Varje användare får sin egen portfölj, bevakningslista och paper trading. "
            "Admin-kontot hanteras separat via Streamlit Secrets."
        )

        try:
            import streamlit_authenticator as stauth
            _stauth_ok = True
        except ImportError:
            st.error("❌ `streamlit-authenticator` saknas. Kör: `pip install streamlit-authenticator`")
            _stauth_ok = False

        if _stauth_ok:
            users = _load_users_config()
            active_users = [u for u in users if u.get("active", True)]
            inactive_users = [u for u in users if not u.get("active", True)]

            # ── Nuvarande användare ──────────────────────────────────────────
            st.markdown(f"**{len(active_users)} aktiva användare** (utöver admin)")
            if active_users:
                user_rows = [
                    {
                        "Användarnamn": u["username"],
                        "Namn":         u.get("name", ""),
                        "E-post":       u.get("email", ""),
                        "Tillagd":      u.get("added", ""),
                        "Aktiv":        "✅",
                    }
                    for u in active_users
                ]
                st.dataframe(pd.DataFrame(user_rows), use_container_width=True, hide_index=True)
            else:
                st.info("Inga extra användare tillagda ännu.")

            # ── Lägg till ny användare ───────────────────────────────────────
            st.markdown("---")
            st.markdown("### ➕ Lägg till ny användare")
            with st.form("form_add_user", clear_on_submit=True):
                col_u, col_n = st.columns(2)
                with col_u:
                    new_uname = st.text_input(
                        "Användarnamn *",
                        placeholder="t.ex. hans",
                        help="Gemener, inga mellanslag. Används vid inloggning.",
                    )
                with col_n:
                    new_name = st.text_input("Visningsnamn", placeholder="t.ex. Hans")

                col_e, col_p = st.columns(2)
                with col_e:
                    new_email = st.text_input("E-post (valfritt)", placeholder="hans@example.com")
                with col_p:
                    new_pw = st.text_input(
                        "Lösenord *",
                        type="password",
                        placeholder="Minst 6 tecken",
                        help="Lagras krypterat (bcrypt). Du ser det aldrig igen.",
                    )

                submitted_add = st.form_submit_button("➕ Skapa användare", type="primary")
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
                        hashed_pw = stauth.Hasher.hash(new_pw)
                        users.append({
                            "username": uname_clean,
                            "name":     new_name.strip() or uname_clean.capitalize(),
                            "email":    new_email.strip().lower(),
                            "password": hashed_pw,
                            "active":   True,
                            "added":    str(date.today()),
                        })
                        _save_users_config(users)
                        st.success(
                            f"✅ Användaren **{uname_clean}** skapad! "
                            f"De kan nu logga in med det valda lösenordet."
                        )
                        st.rerun()

            # ── Hantera befintliga användare ─────────────────────────────────
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
                        btn_lbl = "⏸ Inaktivera" if is_active else "▶️ Aktivera"
                        if st.button(btn_lbl, key="btn_user_toggle", use_container_width=True):
                            sel_user["active"] = not is_active
                            _save_users_config(users)
                            st.success(f"{'Inaktiverad' if not sel_user['active'] else 'Aktiverad'}: {sel_uname}")
                            st.rerun()

                    with col_del:
                        if st.button("🗑️ Ta bort", key="btn_user_delete", use_container_width=True):
                            users = [u for u in users if u["username"] != sel_uname]
                            _save_users_config(users)
                            st.success(f"✅ `{sel_uname}` borttagen.")
                            st.rerun()

                    with col_pw:
                        if st.button("🔑 Byt lösenord", key="btn_user_pw", use_container_width=True):
                            st.session_state["user_pw_change_target"] = sel_uname

                    if st.session_state.get("user_pw_change_target") == sel_uname:
                        with st.form(f"form_pw_{sel_uname}"):
                            new_pw2 = st.text_input("Nytt lösenord", type="password", key=f"pw2_{sel_uname}")
                            if st.form_submit_button("💾 Spara nytt lösenord"):
                                if len(new_pw2) < 6:
                                    st.error("Lösenordet måste vara minst 6 tecken.")
                                else:
                                    sel_user["password"] = stauth.Hasher.hash(new_pw2)
                                    _save_users_config(users)
                                    st.session_state.pop("user_pw_change_target", None)
                                    st.success(f"✅ Lösenord uppdaterat för `{sel_uname}`.")
                                    st.rerun()

            if inactive_users:
                with st.expander(f"Inaktiva användare ({len(inactive_users)})", expanded=False):
                    st.dataframe(
                        pd.DataFrame([
                            {"Användarnamn": u["username"], "Namn": u.get("name", ""),
                             "E-post": u.get("email", ""), "Tillagd": u.get("added", "")}
                            for u in inactive_users
                        ]),
                        use_container_width=True, hide_index=True,
                    )
