"""web/pages/admin.py – Admin-sida + delade filhanteringsfunktioner"""

import json
import os
import tempfile
import time
from datetime import date, datetime

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
                         owner: str = "hankkontakt", repo: str = "stock-scanner",
                         message: str = "") -> bool:
    """Committar en fil till GitHub via Contents API så att ändringar överlever Streamlit Cloud-omstarter.

    Retryar vid 409 Conflict: om SHA:n blev inaktuell mellan GET och PUT
    (t.ex. en parallell CI-commit skrev filen) hämtar vi färsk SHA och
    försöker igen. Tidigare tappades sådana skrivningar tyst.
    """
    import base64
    if not token:
        return False
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "MarketScan-Streamlit",
    }
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{repo_path}"
    commit_msg = message or f"chore: update {repo_path} via Streamlit"
    b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")

    for attempt in range(3):
        try:
            sha = None
            get_resp = requests.get(url, headers=headers, timeout=10)
            if get_resp.status_code == 200:
                sha = get_resp.json().get("sha")
            payload = {"message": commit_msg, "content": b64, "branch": "main"}
            if sha:
                payload["sha"] = sha
            resp = requests.put(url, json=payload, headers=headers, timeout=15)
            if resp.status_code in (200, 201):
                return True
            # 409 = SHA inaktuell (samtidig skrivning). Hämta färsk SHA och retry.
            if resp.status_code == 409 and attempt < 2:
                continue
            return False
        except Exception:
            if attempt < 2:
                continue
            return False
    return False


def _get_st_secret(key: str) -> str:
    """Läs ett secret från miljövariabel eller Streamlit Secrets."""
    val = os.getenv(key, "")
    if val:
        return val
    try:
        return st.secrets.get(key, "") or ""
    except Exception:
        return ""


def _get_github_token() -> str:
    """Hämtar GITHUB_TOKEN från miljövariabel eller Streamlit Secrets."""
    return _get_st_secret("GITHUB_TOKEN")


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


def _save_watchlist_data(items: list, previous_tickers: list | None = None):
    """Spara watchlist.json i användarens katalog.
    GitHub-commit görs för admin (data/watchlist.json) och för andra användare
    (data/users/{username}/watchlist.json) så att pipeline kan nå datan.

    Nya tickers som inte redan fanns i filen läggs automatiskt till i
    custom_universe.json och committas till GitHub direkt — inga manuella
    steg behövs för att en bevakning ska dyka upp i nästa scan.
    """
    from web.utils import _active_data_dir
    username = st.session_state.get("username", "admin")
    user_dir = _active_data_dir()

    # Läs befintlig bevakningslista för att hitta nya tickers
    existing_path = user_dir / "watchlist.json"
    try:
        existing_raw = json.loads(existing_path.read_text(encoding="utf-8")) if existing_path.exists() else []
        existing_ticker_set = set(i.get("ticker", "").upper().strip() for i in existing_raw)
    except Exception:
        existing_ticker_set = set(t.upper().strip() for t in (previous_tickers or []))

    content = json.dumps(items, indent=2, ensure_ascii=False)
    existing_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        existing_path.write_text(content, encoding="utf-8")
    except Exception:
        pass

    token = _get_github_token()
    if token:
        if username == "admin":
            _github_commit_file("data/watchlist.json", content, token)
        else:
            _github_commit_file(
                f"data/users/{username}/watchlist.json",
                content,
                token,
                message=f"Update watchlist for {username}",
            )

    # ── Auto-add nya tickers till custom_universe + committa filen ──────────
    # Körs bara för admin (custom_universe är global, inte per användare).
    if username == "admin":
        try:
            from core.config import add_custom_to_universe, _CUSTOM_UNIVERSE_FILE
            incoming_tickers = [
                i["ticker"].upper().strip()
                for i in items
                if i.get("ticker")
            ]
            added_to_cu = []
            for t in incoming_tickers:
                if t and t not in existing_ticker_set:
                    if add_custom_to_universe(t, ""):
                        added_to_cu.append(t)
            if added_to_cu and token:
                try:
                    cu_content = _CUSTOM_UNIVERSE_FILE.read_text(encoding="utf-8")
                    _github_commit_file(
                        "data/custom_universe.json",
                        cu_content,
                        token,
                        message=f"Add {', '.join(added_to_cu)} to scan universe",
                    )
                except Exception:
                    pass
            # ── Trigga targeted refresh direkt för nya tickers ────────────────
            if added_to_cu:
                if _trigger_targeted_refresh(added_to_cu):
                    st.toast(
                        f"⏳ Hämtar data för {', '.join(added_to_cu)} — "
                        "klart om ~2 min",
                        icon="🔄",
                    )
        except Exception:
            pass


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


def _trigger_targeted_refresh(tickers: list[str]) -> bool:
    """
    Starta en targeted-refresh av specifika tickers via GitHub Actions.
    Tyst – inga st.success/st.error-meddelanden (används vid automatiska triggers).
    Returnerar True om requesten skickades, annars False.
    """
    if not tickers:
        return False
    token = _get_github_token()
    if not token:
        return False
    import requests as _req
    owner = os.getenv("GITHUB_OWNER") or "hankkontakt"
    repo  = os.getenv("GITHUB_REPO")  or "stock-scanner"
    url = (f"https://api.github.com/repos/{owner}/{repo}"
           f"/actions/workflows/daily_scan.yml/dispatches")
    payload = {
        "ref": "main",
        "inputs": {
            "mode": "targeted",
            "tickers": ",".join(t.strip().upper() for t in tickers if t.strip()),
        },
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "MarketScan-Streamlit",
    }
    try:
        resp = _req.post(url, json=payload, headers=headers, timeout=15)
        return resp.status_code in (200, 201, 204)
    except Exception:
        return False




