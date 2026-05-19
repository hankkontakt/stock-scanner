"""web/pages/portfolio.py – Sida 4: Portfölj"""

import json
import os
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from web.utils import (
    kpi_row, holdings_pie, num_fmt, pct_fmt,
    load_portfolio, load_watchlist, _get_provider, _get_depth,
    _active_data_dir, DATA_DIR,
)
from core import ai_analysis

# ── Kontoregister (konton.json) ───────────────────────────────────────────────

_KONTON_PATH = DATA_DIR / "konton.json"
_DEFAULT_KONTON = {
    "Huvud":       {"typ": "aktier", "color": "#4c9be8"},
    "ISK Aktier":  {"typ": "aktier", "color": "#4c9be8"},
    "ISK Fonder":  {"typ": "fond",   "color": "#f59e0b"},
    "KF":          {"typ": "aktier", "color": "#00d4aa"},
    "Depå":        {"typ": "aktier", "color": "#a78bfa"},
}


def _load_konton() -> dict:
    """Läs kontoregistret. Returnerar dict {namn: {typ, color}}."""
    try:
        return json.loads(_KONTON_PATH.read_text(encoding="utf-8"))
    except Exception:
        return dict(_DEFAULT_KONTON)


def _save_konton(konton: dict):
    _KONTON_PATH.parent.mkdir(parents=True, exist_ok=True)
    _KONTON_PATH.write_text(json.dumps(konton, indent=2, ensure_ascii=False), encoding="utf-8")


def _ensure_konto(name: str, typ: str = "aktier") -> dict:
    """Lägg till kontot i registret om det inte finns. Returnerar uppdaterat register."""
    konton = _load_konton()
    if name not in konton:
        colors = ["#4c9be8", "#00d4aa", "#f59e0b", "#a78bfa", "#f87171", "#34d399"]
        used = {v.get("color") for v in konton.values()}
        color = next((c for c in colors if c not in used), "#8892a4")
        konton[name] = {"typ": typ, "color": color}
        _save_konton(konton)
    return konton


def _is_fund_konto(konto_name: str) -> bool:
    """Returnerar True om kontot är av typen 'fond' (ingen scanneranalys)."""
    return _load_konton().get(konto_name, {}).get("typ") == "fond"


def _is_fund_holding(holding_typ: str, konto_name: str) -> bool:
    """Avgör om ett enskilt innehav ska behandlas som fond (ingen scanneranalys).

    Prioritetsordning:
    1. holding_typ är explicit satt (fond/etf/certificate) → styr alltid
    2. holding_typ är tomt → faller tillbaka på kontotypen
    3. Kontotyp "aktier" och tomt holding_typ → full scanner-analys

    Det gör att ett blandat konto (aktier + fonder i samma ISK) hanteras
    korrekt: varje innehavs egen typ styr, inte kontots typ.
    """
    if holding_typ in ("fond", "certificate"):
        return True
    if holding_typ == "etf":
        return False   # ETF:er är börshandlade – full analys
    if holding_typ == "aktier":
        return False
    # holding_typ är "" eller okänt → fall tillbaka på kontotypen
    return _is_fund_konto(konto_name)


def _save_watchlist_data(items):
    from web.pages.admin import _save_watchlist_data as _swd
    _swd(items)


def _calc_atr_stop(ticker: str, current_price: float, mult: float = 2.5) -> tuple[float | None, float | None]:
    """
    Beräknar ATR14-baserat stop-loss-nivå.
    Returnerar (stop_price, stop_pct_from_current) eller (None, None) vid fel.
    ATR (Average True Range) mäter den typiska dagliga rörelsen — stop-loss sätts
    2.5× ATR under nuvarande kurs, vilket ger tillräckligt utrymme för normal variation.
    """
    try:
        import yfinance as yf
        hist = yf.Ticker(ticker).history(period="1mo", auto_adjust=True)
        if hist.empty or len(hist) < 5:
            return None, None
        high, low, close = hist["High"], hist["Low"], hist["Close"]
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low  - close.shift()).abs(),
        ], axis=1).max(axis=1)
        atr = float(tr.rolling(14, min_periods=5).mean().iloc[-1])
        if atr <= 0 or current_price <= 0:
            return None, None
        stop = round(current_price - atr * mult, 2)
        stop_pct = round((stop / current_price - 1) * 100, 1)
        return stop, stop_pct
    except Exception:
        return None, None


def _calc_dividend_summary(holdings: pd.DataFrame, score_data: dict) -> dict:
    """
    Beräknar utdelningsöversikt för portföljen baserat på yfinance-data.
    Returnerar dict med:
        total_annual_sek  — förväntad total årsutdelning i SEK
        avg_yield_on_cost — snittavkastning på anskaffningsvärdet
        per_holding       — lista med {ticker, annual_div, yield_on_cost}
    Använder dividend_rate från yfinance info (annualiserad).
    """
    try:
        import yfinance as yf
    except ImportError:
        return {"total_annual_sek": 0, "avg_yield_on_cost": 0, "per_holding": []}

    total_annual = 0.0
    yoc_values: list[float] = []
    per_holding: list[dict] = []

    for _, h in holdings.iterrows():
        ticker = str(h.get("ticker", "")).upper()
        shares = float(h.get("shares", 0) or 0)
        cost   = float(h.get("cost_basis", 0) or 0)
        if shares <= 0:
            continue
        # Check score_data first (faster — already loaded)
        sc = score_data.get(ticker, {})
        div_rate = sc.get("dividend_rate") or sc.get("forward_annual_dividend_rate")
        if div_rate is None:
            # Fallback: fetch from yfinance (cached internally by yfinance)
            try:
                info = yf.Ticker(ticker).fast_info
                div_rate = getattr(info, "last_dividend_value", None)
                # Try full info for annual rate
                if not div_rate:
                    full = yf.Ticker(ticker).info
                    div_rate = full.get("dividendRate") or full.get("trailingAnnualDividendRate")
            except Exception:
                div_rate = None
        if not div_rate:
            per_holding.append({"ticker": ticker, "annual_div": None, "yield_on_cost": None})
            continue
        annual = float(div_rate) * shares
        total_annual += annual
        yoc = (float(div_rate) / cost * 100) if cost > 0 else None
        if yoc is not None:
            yoc_values.append(yoc)
        per_holding.append({"ticker": ticker, "annual_div": annual, "yield_on_cost": yoc})

    avg_yoc = sum(yoc_values) / len(yoc_values) if yoc_values else 0.0
    return {
        "total_annual_sek": total_annual,
        "avg_yield_on_cost": avg_yoc,
        "per_holding": per_holding,
    }


def _portfolio_excel_bytes(port_df: pd.DataFrame, rows: list, score_data: dict) -> bytes:
    """Genererar en Excel-fil med portföljdata. Returnerar bytes."""
    import io
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        # Sheet 1: Innehav
        port_df.to_excel(writer, sheet_name="Innehav", index=False)
        # Sheet 2: Rekommendationer
        rec_rows = []
        for r in rows:
            t = r["Ticker"]
            sc = score_data.get(t, {})
            entry = sc.get("entry_signal", "—")
            score = sc.get("score_total", 0) or 0
            if score >= 70 and entry == "STARK":
                rec = "Behåll / Köp mer"
            elif score >= 55:
                rec = "Behåll"
            elif score >= 40:
                rec = "Avvakta"
            else:
                rec = "Minska / Sälj"
            rec_rows.append({
                "Ticker": t, "Bolag": r.get("Bolag", ""),
                "Score": score, "Signal": entry,
                "Trend": sc.get("trend_signal", "—"),
                "Rekommendation": rec,
                "Pris": sc.get("current_price", ""),
            })
        pd.DataFrame(rec_rows).to_excel(writer, sheet_name="Rekommendationer", index=False)
        # Sheet 3: Metadata
        meta = pd.DataFrame([{
            "Exporterad": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
            "Antal innehav": len(rows),
        }])
        meta.to_excel(writer, sheet_name="Info", index=False)
    return buf.getvalue()


def _suggested_position_pct(score: float, entry: str) -> tuple[float, float]:
    """
    Föreslår positionsstorlek (% av portföljvärde) baserat på score + entry.
    Princip: sprida risken, aldrig >10% i en enskild aktie.
    Returnerar (min_pct, max_pct).
    """
    if score >= 70 and entry == "STARK":
        return 5.0, 8.0
    elif score >= 55:
        return 3.0, 6.0
    elif score >= 40:
        return 2.0, 4.0
    else:
        return 1.0, 3.0


def _save_holdings_user(df: pd.DataFrame):
    """Sparar holdings.csv i användarens datakatalog.
    För admin synkas till GitHub. För andra användare sparas lokalt OCH till GitHub
    (så att pipeline kan läsa data för personliga e-postutskick)."""
    username = st.session_state.get("username", "admin")
    if username == "admin":
        from web.pages.admin import _save_holdings_df
        _save_holdings_df(df)
    else:
        user_dir = _active_data_dir()
        user_dir.mkdir(parents=True, exist_ok=True)
        csv_content = df.to_csv(index=False)
        (user_dir / "holdings.csv").write_text(csv_content, encoding="utf-8")
        # Commit till GitHub så pipeline kan läsa data för personliga e-postutskick
        try:
            from web.pages.admin import _get_github_token, _github_commit_file
            token = _get_github_token()
            if token:
                _github_commit_file(
                    f"data/users/{username}/holdings.csv",
                    csv_content,
                    token,
                    message=f"Update portfolio for {username}",
                )
        except Exception:
            pass  # GitHub-sync misslyckades, men lokal sparning lyckades


def _upsert_holding(holdings: pd.DataFrame, ticker: str,
                    shares: float, cost_basis: float,
                    konto: str = "Huvud",
                    typ: str = "") -> pd.DataFrame:
    """Lägg till eller uppdatera ett innehav i portföljen.
    Om tickern är ny läggs den automatiskt till i nästa scan (custom_universe).

    konto: vilket konto innehavet tillhör (default 'Huvud')
    typ:   innehavets typ — 'aktier', 'fond', 'etf', 'certificate' eller ''
           (tomt = bestäms av kontotypen vid visning, se _is_fund_holding)
    """
    h = holdings.copy() if not holdings.empty else pd.DataFrame(
        columns=["ticker", "shares", "cost_basis", "konto", "typ"]
    )
    # Säkerställ att båda kolumnerna finns
    if "konto" not in h.columns:
        h["konto"] = "Huvud"
    if "typ" not in h.columns:
        h["typ"] = ""

    # Matcha på ticker + konto (samma aktie kan finnas i flera konton)
    mask = (h["ticker"] == ticker) & (h["konto"] == konto)
    is_new = not mask.any()
    if mask.any():
        h.loc[mask, "shares"]     = shares
        h.loc[mask, "cost_basis"] = cost_basis
        if typ:                          # uppdatera typ bara om den skickas med
            h.loc[mask, "typ"] = typ
    else:
        h = pd.concat([h, pd.DataFrame([{
            "ticker": ticker, "shares": shares,
            "cost_basis": cost_basis, "konto": konto, "typ": typ
        }])], ignore_index=True)
    # Auto-lägg till i scan-universum om det är en ny ticker
    if is_new:
        try:
            from core.config import add_custom_to_universe
            added = add_custom_to_universe(ticker)
            if added:
                st.session_state[f"scan_pending_{ticker}"] = True
                # Trigga targeted refresh direkt – hämtar data inom ~2 min
                try:
                    from web.pages.admin import _trigger_targeted_refresh
                    if _trigger_targeted_refresh([ticker]):
                        st.toast(
                            f"⏳ Hämtar data för **{ticker}** — klart om ~2 min",
                            icon="🔄",
                        )
                except Exception:
                    pass
        except Exception:
            pass
    return h


def _show_scan_pending_notifications():
    """Visar en blå infobox för tickers som lagts till i nästa scan."""
    pending = [
        k.replace("scan_pending_", "")
        for k, v in st.session_state.items()
        if k.startswith("scan_pending_") and v
    ]
    if pending:
        tickers_str = ", ".join(f"**{t}**" for t in pending)
        n = len(pending)
        st.info(
            f"⏳ {tickers_str} {'har lagts' if n == 1 else 'har lagts'} till i din portfölj! "
            "Detaljerad analys — som rekommendationer, score och signaler — "
            "uppdateras automatiskt inom några dagar när systemet kör sin nästa analys. "
            "Pris och grundläggande information visas redan nu."
        )


def _manage_portfolio_section(holdings: pd.DataFrame):
    """Tabbar för att hantera portföljen: Avanza-import | Sök & lägg till | Manuell | Ta bort."""
    from data_management import avanza_import
    from web.pages.admin import _search_ticker_yfinance

    label = "➕ Hantera portfölj" if not holdings.empty else "➕ Kom igång – lägg till dina aktier"
    with st.expander(label, expanded=holdings.empty):

        import streamlit.components.v1 as _sc1

        def _scroll_top():
            """Scrolla till toppen av sidan – anropas överst i varje flik."""
            _sc1.html(
                "<script>"
                "try{"
                "  var el=window.parent.document.querySelector('[data-testid=\"stMain\"]');"
                "  if(!el) el=window.parent.document.querySelector('.main');"
                "  if(!el) el=window.parent.document.body;"
                "  el.scrollTo({top:0,behavior:'instant'});"
                "}catch(e){window.parent.scrollTo(0,0);}"
                "</script>",
                height=0,
            )

        tab_avanza, tab_search, tab_manual, tab_remove = st.tabs([
            "📥 Importera från Avanza",
            "🔍 Sök & lägg till",
            "✏️ Lägg till manuellt",
            "🗑️ Ta bort aktie",
        ])

        # ══════════════════════════════════════════════════════════════════════
        # FLIK 1 – AVANZA IMPORT
        # ══════════════════════════════════════════════════════════════════════
        with tab_avanza:
            _scroll_top()
            st.markdown("""
<div style="background:#1a2235;border:1px solid #2d3250;border-radius:10px;
     padding:16px 20px;margin-bottom:14px;">
<div style="font-size:13px;font-weight:700;color:#e8eaf0;margin-bottom:12px;">
  📥 Ladda ner din portfölj från Avanza
</div>

<div style="font-size:12px;font-weight:600;color:#4c9be8;text-transform:uppercase;
     letter-spacing:0.08em;margin-bottom:8px;">Steg för steg</div>
<ol style="font-size:13px;color:#a0aec0;margin:0 0 12px 0;padding-left:18px;line-height:2.2;">
  <li>Öppna <strong style="color:#e8eaf0;">avanza.se</strong> i webbläsaren på datorn
      <span style="color:#64748b;">(fungerar ej i mobilappen)</span></li>
  <li>Klicka på <strong style="color:#e8eaf0;">Min ekonomi</strong> i vänstermenyn</li>
  <li>Klicka på fliken <strong style="color:#e8eaf0;">Analys</strong> i menyn som visas överst</li>
  <li>Scrolla ner till rubriken <strong style="color:#e8eaf0;">Exportera data</strong>
      <span style="color:#64748b;">(längst ner på sidan)</span></li>
  <li>Klicka på <strong style="color:#4c9be8;">Mitt innehav fördelat per konto</strong>
      — filen <code>positioner.csv</code> laddas ner direkt</li>
  <li>Ladda upp filen nedan — alla konton importeras på en gång</li>
</ol>

<div style="background:#0f1a2e;border:1px solid #2d3250;border-radius:6px;
     padding:10px 14px;margin-bottom:10px;font-size:12px;color:#8892a4;line-height:1.8;">
  <strong style="color:#e8eaf0;">Vad filen innehåller:</strong> alla dina konton (ISK, KF, depåer) med
  antal, inköpspris och ISIN — ingen manuell inmatning behövs.<br>
  <strong style="color:#e8eaf0;">Fonder:</strong> importeras automatiskt utan scanner-analys.<br>
  <span style="color:#f59e0b;">⚠ Välj <em>Mitt innehav fördelat per konto</em> — inte "Mitt sammanställda innehav".
  Den sammanställda varianten saknar kontouppdelning och fondklassificering.</span>
</div>

<div style="font-size:12px;color:#64748b;">
  ⚠️ <strong>Mobilapp:</strong> Exportera-funktionen saknas i Avanza-appen — använd avanza.se på dator eller surfplatta.
</div>
</div>
""", unsafe_allow_html=True)

            # ── Filuppladdning ──────────────────────────────────────────────────
            uploaded = st.file_uploader(
                "Välj Avanza-filen (CSV)",
                type=["csv"],
                key="avanza_csv_user",
                help="Filen laddas inte upp till någon server – den läses direkt i din webbläsare.",
            )
            if uploaded is not None:
                raw_bytes = uploaded.getvalue()
                _is_positioner = avanza_import.is_positioner_format(raw_bytes)

                # Gemensamma hjälpfunktioner
                from data_management.avanza_import import (
                    find_ticker, classify_security, load_custom_map,
                    kortnamn_to_ticker,
                )
                custom_map = load_custom_map()

                def _build_holding_rows(df_src, konto_name, key_prefix):
                    """Renderar gransknings-UI för en lista innehav. Returnerar import_data-lista."""
                    _existing_konto: dict[str, tuple[float, float]] = {}
                    if not holdings.empty and "konto" in holdings.columns:
                        for _, _row in holdings[holdings["konto"] == konto_name].iterrows():
                            _existing_konto[str(_row["ticker"]).upper()] = (
                                float(_row.get("shares", 0)),
                                float(_row.get("cost_basis", 0)),
                            )

                    _n_new = _n_changed = _n_same = 0
                    for _, r in df_src.iterrows():
                        _sg = str(r.get("_suggested_ticker", "")).upper()
                        _s = float(r.get("shares") or 0)
                        _c = float(r.get("cost_basis") or 0)
                        if not _sg or _sg not in _existing_konto:
                            _n_new += 1
                        elif abs(_existing_konto[_sg][0] - _s) > 0.001 or abs(_existing_konto[_sg][1] - _c) > 0.001:
                            _n_changed += 1
                        else:
                            _n_same += 1

                    _parts = []
                    if _n_new:     _parts.append(f"**{_n_new} nya**")
                    if _n_changed: _parts.append(f"**{_n_changed} ändrade**")
                    if _n_same:    _parts.append(f"{_n_same} oförändrade")
                    st.success("Hittade " + str(len(df_src)) + " innehav: " + (" · ".join(_parts) if _parts else str(len(df_src))) + ". Granska och bekräfta:")

                    import_data = []
                    n_funds = n_certs = 0
                    for i, r in df_src.iterrows():
                        name          = str(r.get("name", ""))
                        suggested     = str(r.get("_suggested_ticker", ""))
                        security_type = str(r.get("_security_type", "stock"))
                        new_shares    = float(r.get("shares") or 0)
                        new_cost      = float(r.get("cost_basis") or 0)

                        existing_vals = _existing_konto.get(suggested.upper()) if suggested else None
                        if existing_vals is None:
                            row_status  = "new"; status_badge = "🟢 Ny"; status_color = "#4caf50"
                            default_check = bool(suggested) and security_type != "certificate"
                        elif abs(existing_vals[0] - new_shares) > 0.001 or abs(existing_vals[1] - new_cost) > 0.001:
                            row_status  = "changed"; status_color = "#f59e0b"
                            _dp = []
                            if abs(existing_vals[0] - new_shares) > 0.001:
                                _dp.append(f"antal {existing_vals[0]:.0f}→{new_shares:.0f}")
                            if abs(existing_vals[1] - new_cost) > 0.001:
                                _dp.append(f"pris {existing_vals[1]:.2f}→{new_cost:.2f}")
                            status_badge = "🔄 " + ", ".join(_dp); default_check = True
                        else:
                            row_status  = "same"; status_badge = "✓ Oförändrad"
                            status_color = "#64748b"; default_check = False

                        type_badge = ""
                        if security_type == "fund":
                            type_badge = " 🏦 *Fond*"; n_funds += 1
                        elif security_type == "etf":
                            type_badge = " 📊 *ETF*"
                        elif security_type == "certificate":
                            type_badge = " ⚠️ *Certifikat*"; n_certs += 1; default_check = False

                        with st.container(border=True):
                            c1, c2, c3, c4, c5 = st.columns([3, 1, 1, 2, 1])
                            c1.markdown(f"**{name}**{type_badge}")
                            c2.caption(f"Antal: {new_shares:.2f}")
                            c3.caption(f"Pris: {new_cost:.2f}")
                            ticker_val = c4.text_input(
                                "Ticker", value=suggested, key=f"{key_prefix}_t_{i}",
                                label_visibility="collapsed", placeholder="t.ex. VOLV-B.ST",
                            ).upper().strip()
                            do_it = c5.checkbox("Ta med", value=default_check,
                                                key=f"{key_prefix}_ok_{i}", help=status_badge)
                            c1.markdown(
                                f'<span style="font-size:11px;color:{status_color};">'
                                f'{status_badge}</span>', unsafe_allow_html=True)
                        import_data.append({
                            "row": r, "ticker": ticker_val, "import": do_it,
                            "security_type": security_type, "row_status": row_status,
                        })

                    if n_funds > 0:
                        st.info(f"🏦 **{n_funds} fonder** hittades — behandlas utan scanner-signaler.")
                    if n_certs > 0:
                        st.warning(f"⚠️ **{n_certs} certifikat/turbo/warrant** identifierades och är avbockade.")
                    return import_data

                def _do_import(import_data, konto_name, konto_typ, base_h=None):
                    _ensure_konto(konto_name, konto_typ)
                    if base_h is not None:
                        h = base_h.copy()
                    elif not holdings.empty:
                        h = holdings.copy()
                    else:
                        h = pd.DataFrame(columns=["ticker", "shares", "cost_basis", "konto", "typ"])
                    n_add = n_upd = 0
                    for item in import_data:
                        if not item["import"] or not item["ticker"]:
                            continue
                        t = item["ticker"]
                        s = float(item["row"].get("shares") or 0)
                        c = float(item["row"].get("cost_basis") or 0)
                        row_typ = item.get("security_type", "")
                        if row_typ not in ("aktier", "fond", "etf", "certificate"):
                            row_typ = ""
                        h = _upsert_holding(h, t, s, c, konto=konto_name, typ=row_typ)
                        if item.get("row_status") == "new": n_add += 1
                        else: n_upd += 1
                    return h, n_add, n_upd

                try:
                    # ══════════════════════════════════════════════════════════
                    # FORMAT A: Nytt "positioner"-format (Kontonummer-kolumn)
                    # Min ekonomi → Analys → Exportera data → Mitt innehav per konto
                    # ══════════════════════════════════════════════════════════
                    if _is_positioner:
                        positioner_data = avanza_import.parse_avanza_positioner_csv(raw_bytes)
                        if not positioner_data:
                            st.error("Kunde inte läsa filen. Är det en Avanza positioner-export?")
                        else:
                            konton_reg = _load_konton()
                            total_holdings = sum(len(df) for df in positioner_data.values())
                            st.info(
                                f"✅ Hittade **{total_holdings} innehav** i **{len(positioner_data)} konton**. "
                                "Namnge kontona nedan (kontonummer visas som standard):"
                            )

                            # Bygg en lista av (kontonr, df, föreslagen_namn, föreslagen_typ)
                            account_configs = []
                            for konto_nr, df_acc in positioner_data.items():
                                # Förbered ticker-förslag direkt i DataFrame
                                rows_enriched = []
                                for _, r in df_acc.iterrows():
                                    # Fonder (av_typ == FUND): inget ticker-uppslag
                                    _is_fund_row = str(r.get("av_typ", "")).upper() == "FUND"
                                    if _is_fund_row:
                                        suggested = ""
                                        sec_type  = "fund"
                                    else:
                                        # Kortnamn-metoden först (snabbare, ingen nätverksanrop)
                                        suggested = kortnamn_to_ticker(
                                            str(r.get("kortnamn", "")), str(r.get("marknad", ""))
                                        ) or find_ticker(
                                            str(r.get("name", "")), custom_map,
                                            isin=str(r.get("isin", "")) or None,
                                        ) or ""
                                        sec_type = classify_security(str(r.get("name", "")), suggested or None)
                                    rows_enriched.append({
                                        "name":      r.get("name"),
                                        "shares":    r.get("shares"),
                                        "cost_basis": r.get("cost_basis"),
                                        "isin":      r.get("isin"),
                                        "_suggested_ticker": suggested,
                                        "_security_type":    sec_type,
                                    })
                                df_enriched = pd.DataFrame(rows_enriched)

                                # Autodetektera kontotyp
                                n_funds_acc = sum(1 for r in rows_enriched if r["_security_type"] == "fund")
                                auto_typ = "fond" if n_funds_acc > len(rows_enriched) / 2 else "aktier"

                                account_configs.append({
                                    "konto_nr": konto_nr,
                                    "df": df_enriched,
                                    "auto_typ": auto_typ,
                                    "n_funds": n_funds_acc,
                                })

                            # Kontonamn-UI: en rad per konto
                            all_import_data = {}
                            for idx, acc in enumerate(account_configs):
                                konto_nr = acc["konto_nr"]
                                df_enriched = acc["df"]
                                auto_typ = acc["auto_typ"]

                                with st.expander(
                                    f"{'🏦' if auto_typ=='fond' else '📈'} Konto {konto_nr} "
                                    f"({len(df_enriched)} innehav)",
                                    expanded=True,
                                ):
                                    cn1, cn2 = st.columns([2, 1])
                                    default_name = konto_nr  # standard = kontonummer
                                    # Kolla om kontonumret liknar ett befintligt konto
                                    for existing_name in konton_reg:
                                        if existing_name.lower() in konto_nr.lower():
                                            default_name = existing_name
                                            break
                                    acc_name = cn1.text_input(
                                        "Kontonamn",
                                        value=default_name,
                                        key=f"pos_name_{idx}",
                                        help="Vad vill du kalla det här kontot i MarketScan?",
                                    ).strip() or konto_nr
                                    acc_typ = cn2.radio(
                                        "Typ", ["aktier", "fond"],
                                        index=0 if auto_typ == "aktier" else 1,
                                        key=f"pos_typ_{idx}",
                                        help="'fond' döljer scanner-signaler",
                                    )
                                    import_rows = _build_holding_rows(
                                        df_enriched, acc_name, key_prefix=f"pos_{idx}"
                                    )
                                    all_import_data[idx] = {
                                        "name": acc_name, "typ": acc_typ, "rows": import_rows
                                    }

                            if st.button("💾 Importera alla markerade", key="btn_pos_save",
                                         type="primary", use_container_width=True):
                                h_all = holdings.copy() if not holdings.empty else pd.DataFrame(
                                    columns=["ticker", "shares", "cost_basis", "konto", "typ"])
                                total_add = total_upd = 0
                                for acc_data in all_import_data.values():
                                    h_all, n_a, n_u = _do_import(
                                        acc_data["rows"], acc_data["name"], acc_data["typ"],
                                        base_h=h_all,  # kedja konton så inget skrivs över
                                    )
                                    total_add += n_a; total_upd += n_u
                                _save_holdings_user(h_all)
                                _msg = []
                                if total_add: _msg.append(f"{total_add} nya")
                                if total_upd: _msg.append(f"{total_upd} uppdaterade")
                                st.success("✅ Klart! " + ", ".join(_msg) + " innehav sparade.")
                                st.rerun()

                    # ══════════════════════════════════════════════════════════
                    # FORMAT B: Gammalt per-konto-format (Värdepapper/Antal/Kurs…)
                    # ══════════════════════════════════════════════════════════
                    else:
                        # Konto-väljare visas bara för det gamla formatet
                        konton_reg2 = _load_konton()
                        konto_names2 = list(konton_reg2.keys())
                        c_knam, c_ktyp = st.columns([2, 1])
                        with c_knam:
                            az_konto = st.selectbox(
                                "Vilket konto tillhör filen?",
                                options=konto_names2 + ["➕ Nytt konto…"],
                                key="az_konto_sel",
                            )
                        if az_konto == "➕ Nytt konto…":
                            c_new, c_new_typ = st.columns([2, 1])
                            az_konto = c_new.text_input(
                                "Kontonamn", placeholder="t.ex. ISK Aktier", key="az_konto_ny"
                            ).strip() or "Nytt konto"
                            az_typ = c_new_typ.radio("Typ", ["aktier", "fond"], key="az_konto_typ")
                        else:
                            az_typ = konton_reg2.get(az_konto, {}).get("typ", "aktier")
                            st.caption("Kontotyp: " + ("🏦 Fondkonto" if az_typ == "fond" else "📈 Aktiekonto"))

                        with tempfile.NamedTemporaryFile(mode="wb", suffix=".csv", delete=False) as tmp:
                            tmp.write(raw_bytes)
                            tmp_path = tmp.name
                        try:
                            df_az = avanza_import.parse_avanza_csv(tmp_path)
                        finally:
                            os.unlink(tmp_path)

                        if df_az.empty:
                            st.error("Kunde inte läsa filen. Är det en Avanza-export?")
                        else:
                            # Förbered ticker-förslag
                            rows_enriched2 = []
                            for _, r in df_az.iterrows():
                                name = str(r.get("name", ""))
                                isin = str(r.get("isin", "")) if "isin" in df_az.columns else None
                                suggested = find_ticker(name, custom_map, isin=isin or None) or ""
                                sec_type  = classify_security(name, suggested or None)
                                rows_enriched2.append({
                                    **r.to_dict(),
                                    "_suggested_ticker": suggested,
                                    "_security_type": sec_type,
                                })
                            df_enriched2 = pd.DataFrame(rows_enriched2)
                            import_data2 = _build_holding_rows(df_enriched2, az_konto, "az")

                            if st.button("💾 Importera markerade", key="btn_az_save",
                                         type="primary", use_container_width=True):
                                h_new, n_add, n_upd = _do_import(import_data2, az_konto, az_typ)
                                _save_holdings_user(h_new)
                                _msg = []
                                if n_add: _msg.append(f"{n_add} nya")
                                if n_upd: _msg.append(f"{n_upd} uppdaterade")
                                st.success("✅ Klart! " + ", ".join(_msg) + " innehav sparade.")
                                st.rerun()

                except Exception as e:
                    st.error(f"Fel vid import: {e}")
                    import traceback
                    st.caption(traceback.format_exc())

        # ══════════════════════════════════════════════════════════════════════
        # FLIK 2 – SÖK & LÄGG TILL
        # ══════════════════════════════════════════════════════════════════════
        with tab_search:
            _scroll_top()
            st.caption("Sök på aktiens namn eller ticker och fyll i hur många du köpt och till vilket pris.")
            search_q = st.text_input(
                "Sök aktie",
                key="port_search_q",
                placeholder="t.ex. Volvo, AAPL, Investor...",
            )
            if search_q:
                with st.spinner("Söker..."):
                    hits = _search_ticker_yfinance(search_q)
                if hits:
                    options = {
                        f"{h['ticker']}  —  {h.get('name','')[:35]}  ({h.get('exchange','')})": h
                        for h in hits
                    }
                    chosen_label = st.selectbox("Välj aktie", list(options.keys()),
                                                key="port_search_sel")
                    chosen = options[chosen_label]

                    with st.container(border=True):
                        st.markdown(
                            f"**{chosen.get('name', chosen['ticker'])}**  "
                            f"`{chosen['ticker']}`  ·  {chosen.get('exchange','')}"
                        )
                        col_s, col_p, col_d = st.columns(3)
                        with col_s:
                            antal = st.number_input(
                                "Antal aktier",
                                min_value=0.0, value=0.0, step=1.0,
                                key="port_add_shares",
                                help="Hur många aktier du äger totalt av detta bolag.",
                            )
                        with col_p:
                            pris = st.number_input(
                                "Genomsnittligt inköpspris (kr/st)",
                                min_value=0.0, value=0.0, step=0.01,
                                key="port_add_price",
                                help="Ditt genomsnittliga inköpspris per aktie, inklusive courtage.",
                            )
                        with col_d:
                            st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
                            if st.button("➕ Lägg till i portfölj", key="btn_port_add_search",
                                         type="primary", use_container_width=True):
                                if antal <= 0:
                                    st.error("Ange antal aktier.")
                                elif pris <= 0:
                                    st.error("Ange inköpspris.")
                                else:
                                    h = _upsert_holding(holdings, chosen["ticker"], antal, pris)
                                    _save_holdings_user(h)
                                    st.success(
                                        f"✅ **{chosen['ticker']}** tillagd "
                                        f"({antal:.0f} st à {pris:.2f} kr)!"
                                    )
                                    st.rerun()
                else:
                    st.info("Inga resultat. Försök med tickern direkt, t.ex. `VOLV-B.ST`.")

        # ══════════════════════════════════════════════════════════════════════
        # FLIK 3 – MANUELL INMATNING
        # ══════════════════════════════════════════════════════════════════════
        with tab_manual:
            _scroll_top()
            st.caption("Vet du tickern? Fyll i direkt utan att söka.")
            with st.form("form_manual_add", clear_on_submit=True):
                c1, c2, c3 = st.columns([2, 2, 2])
                with c1:
                    m_ticker = st.text_input(
                        "Ticker *",
                        placeholder="t.ex. VOLV-B.ST",
                        help="Yahoo Finance-ticker. Svenska aktier slutar på .ST",
                    ).upper().strip()
                with c2:
                    m_shares = st.number_input(
                        "Antal aktier *",
                        min_value=0.0, value=0.0, step=1.0,
                    )
                with c3:
                    m_price = st.number_input(
                        "Inköpspris per aktie (kr) *",
                        min_value=0.0, value=0.0, step=0.01,
                    )
                # Kontoväljare + typ för manuell inmatning
                konton_reg_m = _load_konton()
                mc1, mc2 = st.columns([2, 1])
                m_konto = mc1.selectbox(
                    "Konto", list(konton_reg_m.keys()), key="manual_konto",
                    help="Vilket konto innehavet tillhör",
                )
                m_typ = mc2.selectbox(
                    "Typ", ["", "aktier", "fond", "etf"],
                    key="manual_typ",
                    help="Lämna tomt = bestäms av kontotypen. Välj 'fond' för aktivt förvaltade fonder i ett blandat konto.",
                )
                if st.form_submit_button("➕ Lägg till", type="primary", use_container_width=True):
                    if not m_ticker:
                        st.error("Ange ticker.")
                    elif m_shares <= 0:
                        st.error("Ange antal.")
                    elif m_price <= 0:
                        st.error("Ange inköpspris.")
                    else:
                        h = _upsert_holding(holdings, m_ticker, m_shares, m_price,
                                            konto=m_konto, typ=m_typ)
                        _save_holdings_user(h)
                        st.success(f"✅ **{m_ticker}** tillagd ({m_shares:.0f} st à {m_price:.2f} kr)!")
                        st.rerun()

        # ══════════════════════════════════════════════════════════════════════
        # FLIK 4 – TA BORT / REDIGERA
        # ══════════════════════════════════════════════════════════════════════
        with tab_remove:
            _scroll_top()
            if holdings.empty:
                st.info("Portföljen är tom – ingenting att ta bort.")
            else:
                tickers = holdings["ticker"].tolist()
                sel = st.selectbox("Välj aktie att hantera", tickers, key="port_remove_sel")
                row = holdings[holdings["ticker"] == sel].iloc[0]

                with st.container(border=True):
                    st.markdown(f"**{sel}** · {float(row['shares']):.0f} st · inköp {float(row['cost_basis']):.2f} kr/st")
                    col_edit, col_del = st.columns(2)

                    with col_edit:
                        with st.expander("✏️ Ändra antal / pris"):
                            with st.form(f"form_edit_{sel}"):
                                e_shares = st.number_input(
                                    "Antal", value=float(row["shares"]),
                                    min_value=0.0, step=1.0, key=f"e_s_{sel}",
                                )
                                e_price = st.number_input(
                                    "Inköpspris (kr/st)", value=float(row["cost_basis"]),
                                    min_value=0.0, step=0.01, key=f"e_p_{sel}",
                                )
                                if st.form_submit_button("💾 Spara", use_container_width=True):
                                    h = _upsert_holding(holdings, sel, e_shares, e_price)
                                    _save_holdings_user(h)
                                    st.success(f"✅ {sel} uppdaterad.")
                                    st.rerun()

                    with col_del:
                        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
                        if st.button(f"🗑️ Ta bort {sel}", key=f"btn_del_{sel}",
                                     use_container_width=True):
                            h = holdings[holdings["ticker"] != sel].reset_index(drop=True)
                            _save_holdings_user(h)
                            st.success(f"✅ {sel} borttagen.")
                            st.rerun()


def _portfolio_stress_test(holdings: pd.DataFrame, score_data: dict) -> None:
    """Show how portfolio would perform in market crash scenarios."""
    if holdings.empty:
        return

    with st.expander("🔥 Stresstesta portföljen", expanded=False):
        st.caption("Simulerar hur din portfölj påverkas vid marknadsfall, baserat på varje aktiens beta.")

        scenarios = {
            "Liten korrigering (-10%)": -0.10,
            "Normal björnmarknad (-20%)": -0.20,
            "Svår krasch (-30%)": -0.30,
            "Extrem krasch (-40%)": -0.40,
        }

        rows = []
        for _, h in holdings.iterrows():
            ticker = h["ticker"]
            shares = float(h.get("shares", 0))
            cost = float(h.get("cost_basis", 0))

            # Get beta and current price from score_data
            sd = score_data.get(ticker, {})
            beta_val = sd.get("beta")
            if beta_val is None or (isinstance(beta_val, float) and pd.isna(beta_val)):
                beta_val = 1.0  # default
            beta_val = float(beta_val)

            current_price = sd.get("current_price") or sd.get("close")
            if current_price and pd.notna(current_price):
                market_value = shares * float(current_price)
            elif cost > 0:
                market_value = shares * cost
            else:
                continue

            row = {"Ticker": ticker, "Beta": round(beta_val, 2), "Marknadsvärde (SEK)": round(market_value)}
            for scenario_name, market_drop in scenarios.items():
                stock_drop = market_drop * beta_val
                impact = market_value * stock_drop
                row[scenario_name] = round(impact)
            rows.append(row)

        if not rows:
            st.info("Lägg till innehav med kostnadsbas för att stresstesta portföljen.")
            return

        stress_df = pd.DataFrame(rows)

        # Portfolio totals
        total_value = stress_df["Marknadsvärde (SEK)"].sum()

        # KPI metrics for each scenario
        cols_stress = st.columns(len(scenarios))
        for col_s, (scenario_name, market_drop) in zip(cols_stress, scenarios.items()):
            total_impact = stress_df[scenario_name].sum()
            pct = total_impact / total_value * 100 if total_value else 0
            col_s.metric(
                scenario_name.split("(")[0].strip(),
                f"{total_impact:,.0f} kr",
                f"{pct:.1f}%",
                delta_color="inverse",
            )

        st.markdown("---")
        st.markdown("**Per aktie**")

        display_stress = stress_df.copy()
        for col_name in scenarios.keys():
            display_stress[col_name] = display_stress[col_name].apply(
                lambda x: f"{x:,.0f} kr" if pd.notna(x) else "—"
            )

        st.dataframe(display_stress, use_container_width=True, hide_index=True)
        if total_value:
            weighted_beta = (stress_df["Beta"] * stress_df["Marknadsvärde (SEK)"]).sum() / total_value
            st.caption(f"Portföljvärde: {total_value:,.0f} kr | Viktad beta: {weighted_beta:.2f}")


def _dividend_simulator(holdings: pd.DataFrame, score_data: dict) -> None:
    """Dividend income simulator with optional reinvestment."""
    if holdings.empty:
        return

    with st.expander("💰 Utdelningssimulator", expanded=False):
        st.caption("Projicera utdelningsinkomst baserat på nuvarande innehav och historisk utdelningsdata.")

        col_a, col_b, col_c = st.columns(3)
        years = col_a.slider("Antal år", 1, 30, 10, key="div_sim_years")
        growth_rate = col_b.slider("Utdelningstillväxt/år %", 0.0, 15.0, 5.0, step=0.5, key="div_sim_growth") / 100
        reinvest = col_c.checkbox("Återinvestera utdelningar", value=True, key="div_sim_reinvest")

        # Calculate current annual dividend per holding
        annual_total = 0.0
        per_stock = []
        portfolio_total_value = 0.0
        for _, h in holdings.iterrows():
            ticker = h["ticker"]
            shares = float(h.get("shares", 0))
            cost = float(h.get("cost_basis", 0))

            sd = score_data.get(ticker, {})
            div_rate = sd.get("dividend_rate") or sd.get("trailingAnnualDividendRate") or 0
            current_price = sd.get("current_price") or sd.get("close") or cost

            if current_price and pd.notna(current_price):
                portfolio_total_value += shares * float(current_price)

            if div_rate and pd.notna(div_rate) and float(div_rate) > 0:
                annual_div = shares * float(div_rate)
                div_yield = float(div_rate) / float(current_price) * 100 if current_price else 0
                annual_total += annual_div
                per_stock.append({
                    "Ticker": ticker,
                    "Aktier": int(shares),
                    "Utdelning/aktie (kr)": round(float(div_rate), 2),
                    "Direktavkastning": f"{div_yield:.1f}%",
                    "Årsutdelning (kr)": round(annual_div),
                })

        if annual_total == 0:
            st.info("Inga utdelande aktier i portföljen, eller data saknas.")
            return

        # Projection table
        projection = []
        cumulative = annual_total
        total_received = 0.0
        portfolio_yield = (annual_total / portfolio_total_value) if portfolio_total_value > 0 else 0.03

        for year in range(1, years + 1):
            if reinvest:
                # Reinvested dividends earn same yield
                cumulative = cumulative * (1 + growth_rate + portfolio_yield)
                year_div = cumulative
            else:
                year_div = annual_total * (1 + growth_rate) ** (year - 1)
            total_received += year_div
            projection.append({
                "År": year,
                "Kalenderår": 2026 + year - 1,
                "Årsutdelning (kr)": round(year_div),
                "Månadsutdelning (kr)": round(year_div / 12),
                "Totalt utbetalt hittills (kr)": round(total_received),
            })

        # KPIs
        proj_df = pd.DataFrame(projection)
        final_annual = proj_df.iloc[-1]["Årsutdelning (kr)"]
        total_recv = proj_df.iloc[-1]["Totalt utbetalt hittills (kr)"]

        col1_d, col2_d, col3_d = st.columns(3)
        col1_d.metric("Nuvarande årsutdelning", f"{annual_total:,.0f} kr", f"{annual_total/12:,.0f} kr/mån")
        growth_pct = (final_annual / annual_total - 1) * 100 if annual_total else 0
        col2_d.metric(f"Årsutdelning år {years}", f"{final_annual:,.0f} kr", f"+{growth_pct:.0f}%")
        col3_d.metric(f"Totalt utbetalt {years} år", f"{total_recv:,.0f} kr")

        # Chart
        import plotly.graph_objects as go
        fig_div = go.Figure()
        fig_div.add_trace(go.Bar(
            x=proj_df["Kalenderår"],
            y=proj_df["Årsutdelning (kr)"],
            marker_color="#4caf50",
            hovertemplate="År %{x}: %{y:,.0f} kr<extra></extra>",
            name="Årsutdelning",
        ))
        fig_div.update_layout(
            height=250, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#8892a4"), xaxis=dict(gridcolor="#252b3b"),
            yaxis=dict(gridcolor="#252b3b", title="kr/år"),
            margin=dict(l=0, r=0, t=20, b=0), showlegend=False,
        )
        st.plotly_chart(fig_div, use_container_width=True)

        with st.expander("Detaljerad projektion", expanded=False):
            st.dataframe(proj_df, use_container_width=True, hide_index=True)

        if per_stock:
            with st.expander("Per aktie", expanded=False):
                st.dataframe(pd.DataFrame(per_stock), use_container_width=True, hide_index=True)


def page_portfolio(df: pd.DataFrame, holdings: pd.DataFrame, watchlist: list,
                   sc_df: pd.DataFrame = None):
    st.title("💼 Portfölj & Bevakningslista")

    # ── Notiser för nyligen tillagda tickers som inväntar nästa scan ──────────
    _show_scan_pending_notifications()

    # ── Portföljhantering (synlig för alla användare) ─────────────────────────
    _manage_portfolio_section(holdings)
    # Ladda om portföljen om den just sparades
    holdings = load_portfolio()

    if holdings.empty:
        st.info("Portföljen är tom. Importera dina innehav från Avanza ovan ↑")
    else:
        # ── Kontofilter ───────────────────────────────────────────────────────
        konton_reg  = _load_konton()
        all_konton  = sorted(holdings["konto"].dropna().unique().tolist()) if "konto" in holdings.columns else ["Huvud"]
        konto_opts  = ["Alla konton"] + all_konton
        # Färgade konto-badges
        konto_badges = "".join(
            f'<span style="background:{konton_reg.get(k,{}).get("color","#4c9be8")}22;'
            f'border:1px solid {konton_reg.get(k,{}).get("color","#4c9be8")}55;'
            f'border-radius:4px;padding:2px 8px;margin:0 4px;font-size:12px;color:#e8eaf0;">'
            f'{"🏦 " if konton_reg.get(k,{}).get("typ")=="fond" else "📈 "}{k}</span>'
            for k in all_konton
        )
        if len(all_konton) > 1:
            st.markdown(f"<div style='margin-bottom:8px;'>Konton: {konto_badges}</div>",
                        unsafe_allow_html=True)
            sel_konto = st.selectbox("Visa konto:", konto_opts, key="port_konto_filter",
                                     label_visibility="collapsed")
        else:
            sel_konto = "Alla konton"

        # Filtrera holdings baserat på valt konto
        if sel_konto != "Alla konton" and "konto" in holdings.columns:
            holdings_view = holdings[holdings["konto"] == sel_konto].copy()
        else:
            holdings_view = holdings.copy()

        frames = [f for f in [df, sc_df] if f is not None and not f.empty and "ticker" in f.columns]
        if frames:
            combined = pd.concat(frames, ignore_index=True).drop_duplicates(subset="ticker", keep="first")
            score_data = combined.set_index("ticker").to_dict("index")
        else:
            score_data = {}

        # ── Utdelningsdata — beräkna/cachas innan tabellen byggs ──────────────
        _holdings_hash = str(sorted(holdings_view["ticker"].tolist()))
        if st.session_state.get("div_summary_hash") != _holdings_hash:
            with st.spinner("Hämtar utdelningsdata…"):
                _div_summary = _calc_dividend_summary(holdings_view, score_data)
                st.session_state["div_summary"] = _div_summary
                st.session_state["div_summary_hash"] = _holdings_hash
        else:
            _div_summary = st.session_state.get("div_summary", {})

        _div_ph_map: dict = {}
        for _ph in _div_summary.get("per_holding", []):
            _div_ph_map[_ph["ticker"]] = _ph

        rows = []
        for _, h in holdings_view.iterrows():
            t      = str(h["ticker"]).upper()
            konto  = str(h.get("konto", "Huvud"))
            typ    = str(h.get("typ", ""))
            sc     = score_data.get(t, {})
            price  = sc.get("current_price")
            cost   = h.get("cost_basis")
            shares = h.get("shares", 0)
            # Avgör per innehavs-nivå — fungerar för blandade konton
            is_fund_acc = _is_fund_holding(typ, konto)
            pnl_pct = ((price / float(cost)) - 1) * 100 \
                if price and cost and float(cost) > 0 else None
            mv = price * float(shares) if price and shares else None
            _yoc = _div_ph_map.get(t, {}).get("yield_on_cost")
            rows.append({
                "Ticker":    t,
                "Konto":     konto,
                "Bolag":     sc.get("name", t)[:30],
                "Sektor":    sc.get("sector", "—") if not is_fund_acc else "Fond",
                "Antal":     shares,
                "Inköpspris": cost,
                "Pris nu":   f"{price:.2f}" if price else "—",
                "P&L %":     f"{pnl_pct:+.1f}%" if pnl_pct is not None else "—",
                "Marknadsvärde": f"{mv:,.0f}" if mv else "—",
                "Yield/cost": f"{_yoc:.1f}%" if _yoc is not None else "—",
                # Scannerdata döljs för fondkonton
                "Score":     sc.get("score_total") if not is_fund_acc else None,
                "Entry":     sc.get("entry_signal", "—") if not is_fund_acc else "Fond",
                "Trend":     sc.get("trend_signal", "—") if not is_fund_acc else "—",
                "Piotroski": sc.get("piotroski_f") if not is_fund_acc else None,
                "RS":        sc.get("rs_label", "—") if not is_fund_acc else "—",
                "_is_fund":  is_fund_acc,
            })

        port_df = pd.DataFrame(rows)

        total_mv   = sum(float(r["Marknadsvärde"].replace(",", "").replace(" ", ""))
                        for r in rows if isinstance(r["Marknadsvärde"], str)
                        and r["Marknadsvärde"] != "—") if rows else 0
        pnl_vals   = [float(r["P&L %"].replace("%", "").replace("+", ""))
                      for r in rows if r["P&L %"] not in ("—", None)]
        avg_pnl    = sum(pnl_vals) / len(pnl_vals) if pnl_vals else 0
        best       = max(pnl_vals) if pnl_vals else 0
        worst      = min(pnl_vals) if pnl_vals else 0

        kpi_row([
            ("Positioner",       f"{len(rows)}",            None,
             "Antal aktier du för närvarande äger i din portfölj."),
            ("Totalt värde",     f"{total_mv:,.0f} kr",     None,
             "Totalt marknadsvärde av alla dina innehav baserat på senaste kurs."),
            ("Snitt P&L",        f"{avg_pnl:+.1f}%",        None,
             "Genomsnittlig vinst/förlust (Profit & Loss) för alla positioner sedan inköp. Positivt = portföljen är på plus totalt."),
            ("Bäst / Sämst",     f"+{best:.1f}% / {worst:.1f}%", None,
             "Din bästa respektive sämsta position i procent. Bra för att identifiera vinnare och förlorare i portföljen."),
        ])

        _total_div = _div_summary.get("total_annual_sek", 0)
        _avg_yoc   = _div_summary.get("avg_yield_on_cost", 0)
        if _total_div > 0 or _avg_yoc > 0:
            kpi_row([
                ("Årsutdelning (est.)", f"{_total_div:,.0f} kr", None,
                 "Förväntad total årsutdelning baserat på aktuell utdelningsnivå för dina innehav."),
                ("Snitt yield on cost", f"{_avg_yoc:.1f}%", None,
                 "Genomsnittlig direktavkastning beräknad på ditt inköpspris — visar avkastningen på investerat kapital."),
            ])

        # ── Exportknapp ────────────────────────────────────────────────────────
        try:
            _excel_bytes = _portfolio_excel_bytes(port_df, stock_rows, score_data)
            st.download_button(
                label="📥 Exportera portfölj (Excel)",
                data=_excel_bytes,
                file_name=f"portfolio_{pd.Timestamp.now().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="dl_portfolio_excel",
                help="Ladda ner portföljdata som Excel-fil med innehav + rekommendationer.",
            )
        except Exception:
            pass  # openpyxl kanske saknas – tyst fel

        # Dölj interna fält från tabellen
        display_cols = [c for c in port_df.columns if not c.startswith("_")]
        # Dölj Konto-kolumnen om det bara finns ett konto
        if len(all_konton) <= 1 and "Konto" in display_cols:
            display_cols = [c for c in display_cols if c != "Konto"]
        port_df_display = port_df[display_cols]
        col_cfg = {}
        if "Score" in port_df_display.columns:
            col_cfg["Score"] = st.column_config.ProgressColumn(
                "Score", min_value=0, max_value=100, format="%.0f"
            )
        st.dataframe(port_df_display, use_container_width=True, hide_index=True,
                     column_config=col_cfg)

        st.markdown("---")
        st.subheader("💡 Rekommendationer")

        # Dela upp aktier och fonder
        stock_rows = [r for r in rows if not r.get("_is_fund")]
        fund_rows  = [r for r in rows if r.get("_is_fund")]

        if fund_rows:
            with st.expander(f"🏦 Fonder & fondkonton ({len(fund_rows)} st) — P&L-översikt", expanded=False):
                st.caption("Fondinnehav analyseras inte med scanner-signaler. Enbart P&L och marknadsvärde visas.")
                for r in fund_rows:
                    pnl  = r.get("P&L %", "—")
                    mv   = r.get("Marknadsvärde", "—")
                    kont = r.get("Konto", "")
                    pnl_color = "#4caf50" if str(pnl).startswith("+") else "#ef5350" if str(pnl).startswith("-") else "#8892a4"
                    st.markdown(
                        f"<div style='padding:8px 12px;border:1px solid #2d3250;border-radius:8px;margin-bottom:6px;'>"
                        f"🏦 <b>{r['Ticker']}</b> <span style='color:#8892a4;font-size:12px;'>({kont})</span> &nbsp;·&nbsp; "
                        f"Marknadsvärde: <b>{mv}</b> &nbsp;·&nbsp; "
                        f"<span style='color:{pnl_color};'>P&L: {pnl}</span>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )

        if not stock_rows:
            st.info("Inga aktier i valt konto.")
        else:
            st.caption("Baserat på senaste veckoanalys. Stop-loss beräknas på den typiska dagliga rörelsen (ATR14).")
            _show_atr = st.toggle("Visa stop-loss & positionsstorlek", value=True, key="toggle_atr")

            for r in sorted(stock_rows, key=lambda x: x.get("Score") or 0, reverse=True):
                t  = r["Ticker"]
                sc = score_data.get(t, {})
                if not sc:
                    st.markdown(f"⚪ **{t}** — Analys uppdateras inom kort")
                    continue
                entry  = sc.get("entry_signal", "—")
                score  = sc.get("score_total", 0) or 0
                price_val = sc.get("current_price") or sc.get("close")

                if score >= 70 and entry == "STARK":
                    icon = "🟢"; rec = "Behåll / Köp mer"
                elif score >= 55:
                    icon = "🔵"; rec = "Behåll"
                elif score >= 40:
                    icon = "🟡"; rec = "Avvakta"
                else:
                    icon = "🔴"; rec = "Minska / Sälj"

                with st.container(border=True):
                    c1, c2 = st.columns([3, 2])
                    with c1:
                        st.markdown(f"**{icon} {t}** — {rec}")
                        st.caption(f"Score: {score:.0f}  ·  Signal: {entry}  ·  Trend: {sc.get('trend_signal', '—')}")
                with c2:
                    if _show_atr and price_val:
                        try:
                            cur = float(price_val)
                            stop_p, stop_pct = _calc_atr_stop(t, cur)
                            pos_min, pos_max = _suggested_position_pct(score, entry)
                            if stop_p:
                                color = "#ef5350" if (stop_pct or 0) < -12 else "#ffc107"
                                st.markdown(
                                    f"<span style='font-size:12px;color:{color};'>🛑 Stop-loss: "
                                    f"**{stop_p:.2f}** ({stop_pct:+.1f}%)</span>",
                                    unsafe_allow_html=True,
                                )
                            st.markdown(
                                f"<span style='font-size:12px;color:#8892a4;'>📐 Föreslaget: "
                                f"{pos_min:.0f}–{pos_max:.0f}% av portföljvärdet</span>",
                                unsafe_allow_html=True,
                            )
                        except Exception:
                            pass

        if len(stock_rows) > 1:
            st.markdown("---")
            st.plotly_chart(holdings_pie(pd.DataFrame(stock_rows).rename(columns={"Sektor": "sector"})),
                            use_container_width=True)

        # ── Stress Test + Dividend Simulator (Features 5 & 8) ─────────────
        st.markdown("---")
        _portfolio_stress_test(holdings_view, score_data)
        _dividend_simulator(holdings_view, score_data)

    # ── AI Portfolio Optimizer button (Feature 4) ──────────────────────────
    if not holdings.empty:
        st.markdown("---")
        st.subheader("🤖 AI-portföljoptimering")
        st.caption("Få AI-analys av din portfölj med förslag")
        if st.button("🤖 Analysera portfölj med AI", key="btn_portfolio_ai",
                     use_container_width=True, type="primary"):
            provider = _get_provider()
            depth = _get_depth()
            with st.spinner("Analyserar portfölj..."):
                try:
                    result = ai_analysis.analyze_portfolio(
                        holdings, df=df if not df.empty else None,
                        provider=provider,
                        depth=depth,
                    )
                    with st.container(border=True):
                        st.markdown(result)
                except Exception as e:
                    st.error(f"❌ {e}")

    # ── Dividend-kalender ───────────────────────────────────────────────────
    if not holdings.empty and "ticker" in holdings.columns:
        st.markdown("---")
        st.subheader("💰 Kommande utdelningar")
        st.caption("Estimerade nästa utdelningsdatum för dina innehav (baseras på historisk frekvens).")
        _div_days = st.slider("Visa inom (dagar)", 30, 180, 90, 30, key="div_days")
        if st.button("🔄 Hämta utdelningsdata", key="btn_div_cal", use_container_width=True):
            with st.spinner("Hämtar utdelningshistorik..."):
                try:
                    from core.dividend_calendar import get_upcoming_dividends
                    _tickers = holdings["ticker"].str.strip().str.upper().tolist()
                    _div_df = get_upcoming_dividends(_tickers, days_ahead=_div_days)
                    st.session_state["div_cal"] = _div_df
                except Exception as e:
                    st.error(f"Kunde inte hämta utdelningsdata: {e}")

        _div_result = st.session_state.get("div_cal")
        if _div_result is not None:
            if _div_result.empty:
                st.info(f"Inga förväntade utdelningar inom {_div_days} dagar.")
            else:
                def _urgency(d):
                    if d <= 7:   return "🔴"
                    if d <= 21:  return "🟡"
                    return "🟢"
                _div_result = _div_result.copy()
                _div_result["Kvar"] = _div_result["days_until"].apply(
                    lambda d: f"{_urgency(d)} {d}d")
                _div_result["Yield"] = _div_result["yield_pct"].apply(
                    lambda v: f"{v:.1f}%" if v and not pd.isna(v) else "—")
                _div_show = _div_result[["ticker", "name", "next_div", "Kvar",
                                         "amount", "Yield", "frequency"]].copy()
                _div_show.columns = ["Ticker", "Bolag", "Datum", "Kvar",
                                     "Belopp", "Årsyield", "Frekvens"]
                st.dataframe(_div_show, use_container_width=True, hide_index=True)
                st.caption("⚠️ Datum är estimat baserade på historisk frekvens — inte bekräftade.")

    # Bevakningslista
    st.markdown("---")
    st.subheader("⭐ Bevakningslista")
    if not watchlist:
        st.info("Bevakningslistan är tom. Sök efter aktier på 🔍 Aktie-sök och klicka 'Lägg till i bevakningslista'.")
    else:
        if not df.empty and "ticker" in df.columns:
            score_lu = df.set_index("ticker").to_dict("index")
        else:
            score_lu = {}

        wl_rows = []
        for item in watchlist:
            t  = item["ticker"]
            sc = score_lu.get(t, {})
            wl_rows.append({
                "Ticker":  t,
                "Bolag":   item.get("name", sc.get("name", t))[:28],
                "Sektor":  sc.get("sector", "—"),
                "Tillagd": item.get("added", "—"),
                "Score":   sc.get("score_total"),
                "Entry":   sc.get("entry_signal", "Ej scannad"),
                "Konf.":   sc.get("confidence_label", "—"),
                "Trend":   sc.get("trend_signal", "—"),
                "P/E":     num_fmt(sc.get("pe_trailing")),
                "P/B":     num_fmt(sc.get("price_to_book")),
                "ROE":     pct_fmt(sc.get("roe")),
            })

        wl_df   = pd.DataFrame(wl_rows)
        col_cfg = {}
        if "Score" in wl_df.columns:
            col_cfg["Score"] = st.column_config.ProgressColumn(
                "Score", min_value=0, max_value=100, format="%.0f"
            )
        st.dataframe(wl_df, use_container_width=True, hide_index=True,
                     column_config=col_cfg)
