"""web/pages/portfolio.py – Sida 4: Portfölj"""

import datetime
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
    portfolio_value_chart, calc_period_returns, save_portfolio_snapshot,
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


def _is_fund_holding(holding_typ: str, konto_name: str, ticker: str = "") -> bool:
    """Avgör om ett enskilt innehav ska behandlas som fond (ingen scanneranalys).

    Prioritetsordning:
    1. holding_typ är explicit satt (fond/fund/etf/certificate) → styr alltid
    2. ticker innehåller mellanslag → troligen ett fondnamn sparat som ticker-nyckel
    3. holding_typ är tomt → faller tillbaka på kontotypen
    """
    if holding_typ in ("fond", "fund", "certificate"):
        return True
    if holding_typ == "etf":
        return False   # ETF:er är börshandlade – full analys
    if holding_typ == "aktier":
        return False
    # Ticker med mellanslag = fondnamn sparat som nyckel (legacy-import utan typ)
    if ticker and " " in ticker:
        return True
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
                    typ: str = "",
                    buy_date: str = "",
                    market_value: float = None,
                    isin: str = "") -> pd.DataFrame:
    """Lägg till eller uppdatera ett innehav i portföljen."""
    h = holdings.copy() if not holdings.empty else pd.DataFrame(
        columns=["ticker", "shares", "cost_basis", "konto", "typ", "buy_date", "market_value", "isin"]
    )
    for col, default in [("konto", "Huvud"), ("typ", ""), ("buy_date", ""),
                         ("market_value", None), ("isin", "")]:
        if col not in h.columns:
            h[col] = default

    mask = (h["ticker"] == ticker) & (h["konto"] == konto)
    is_new = not mask.any()
    if mask.any():
        h.loc[mask, "shares"]     = shares
        h.loc[mask, "cost_basis"] = cost_basis
        if typ:
            h.loc[mask, "typ"] = typ
        if market_value is not None:
            h.loc[mask, "market_value"] = market_value
        if buy_date:
            h.loc[mask, "buy_date"] = buy_date
        if isin:
            h.loc[mask, "isin"] = isin
    else:
        h = pd.concat([h, pd.DataFrame([{
            "ticker": ticker, "shares": shares,
            "cost_basis": cost_basis, "konto": konto, "typ": typ,
            "buy_date": buy_date, "market_value": market_value, "isin": isin,
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


def _build_score_data(holdings: pd.DataFrame, df: pd.DataFrame = None,
                      sc_df: pd.DataFrame = None) -> dict:
    """Bygg score_data-dict från scanner-DataFrames."""
    frames = [f for f in [df, sc_df] if f is not None and not getattr(f, "empty", True) and "ticker" in f.columns]
    if frames:
        combined = pd.concat(frames, ignore_index=True).drop_duplicates(subset="ticker", keep="first")
        return combined.set_index("ticker").to_dict("index")
    return {}


def _build_rows(holdings_view: pd.DataFrame, score_data: dict) -> list:
    """Bygg rad-lista från holdings_view + score_data. Returnerar list[dict]."""
    rows = []
    for _, h in holdings_view.iterrows():
        t      = str(h["ticker"]).upper()
        konto  = str(h.get("konto", "Huvud"))
        typ    = str(h.get("typ", ""))
        sc     = score_data.get(t, {})
        price  = sc.get("current_price")
        cost   = h.get("cost_basis")
        shares = h.get("shares", 0)
        is_fund_acc = _is_fund_holding(typ, konto, ticker=t)
        if is_fund_acc and not price:
            # Försök hämta live NAV via Yahoo Finance-sökning (cachat 1h)
            try:
                from web.utils import fetch_fund_nav
                fund_display_name = str(h.get("ticker", t)).strip()
                nav = fetch_fund_nav(fund_display_name)
                if nav and float(shares or 0) > 0:
                    price = nav
                    mv = nav * float(shares)
                else:
                    raise ValueError("no nav")
            except Exception:
                stored_mv = float(h.get("market_value") or 0)
                mv = stored_mv if stored_mv > 0 else (float(cost or 0) * float(shares or 0) or None)
                price = (mv / float(shares)) if mv and shares and float(shares) > 0 else None
        else:
            mv = price * float(shares) if price and shares else None
        pnl_pct = ((price / float(cost)) - 1) * 100 \
            if price and cost and float(cost) > 0 else None
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
            "Score":     sc.get("score_total") if not is_fund_acc else None,
            "Entry":     sc.get("entry_signal", "—") if not is_fund_acc else "Fond",
            "Trend":     sc.get("trend_signal", "—") if not is_fund_acc else "—",
            "Piotroski": sc.get("piotroski_f") if not is_fund_acc else None,
            "RS":        sc.get("rs_label", "—") if not is_fund_acc else "—",
            "_is_fund":  is_fund_acc,
            "_pnl_pct":  pnl_pct,
            "_market_value": mv,
        })
    return rows


def _konto_filter_section(holdings: pd.DataFrame):
    """Renderar konto-filter-UI och returnerar (holdings_view, sel_konto)."""
    konton_reg = _load_konton()
    all_konton = sorted(holdings["konto"].dropna().unique().tolist()) if "konto" in holdings.columns else ["Huvud"]
    konto_opts = ["Alla konton"] + all_konton
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

    if sel_konto != "Alla konton" and "konto" in holdings.columns:
        holdings_view = holdings[holdings["konto"] == sel_konto].copy()
    else:
        holdings_view = holdings.copy()

    return holdings_view, sel_konto


def _manage_portfolio_section(holdings: pd.DataFrame):
    """Tabbar för att hantera portföljen: Avanza-import | Sök & lägg till | Manuell | Ta bort."""
    from data_management import avanza_import
    from web.pages.admin import _search_ticker_yfinance


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
            "📄 Portföljfil — Mitt innehav fördelat per konto (CSV)",
            type=["csv"],
            key="avanza_csv_user",
            help="Filen laddas inte upp till någon server – den läses direkt i din webbläsare.",
        )

        # ── Historiska inköpskurser (valfri tilläggsfil) ─────────────────
        with st.expander("📅 Lägg även till 'Historiska inköpskurser' för exakta köpdatum (valfritt)"):
            st.markdown("""
<div style="background:#0f1a2e;border:1px solid #2a4a2a;border-radius:8px;
     padding:12px 16px;margin-bottom:10px;font-size:13px;color:#a0aec0;line-height:1.9;">
<div style="font-size:12px;font-weight:700;color:#4ade80;text-transform:uppercase;
     letter-spacing:0.08em;margin-bottom:8px;">Fördelar med att ladda upp båda filerna</div>
<ul style="margin:0;padding-left:16px;">
  <li><strong style="color:#e8eaf0;">Rätt köpdatum i portföljcharten</strong> — varje aktie
      markeras med ett ▲ på datumet du faktiskt köpte den, inte importdagen.</li>
  <li><strong style="color:#e8eaf0;">Korrekt P&L-tidslinje</strong> — avkastning räknas från
      verklig inköpsdag, ger en rättvisande bild av hur länge du hållit varje position.</li>
  <li><strong style="color:#e8eaf0;">Fungerar automatiskt</strong> — du behöver inte fylla i
      datum manuellt; filen matchas mot dina innehav via ISIN.</li>
</ul>
<div style="margin-top:10px;font-size:12px;color:#64748b;">
  Ladda ner: <strong>Min ekonomi → Analys → Exportera data →
  "Historiska inköpskurser (GAV)"</strong>
</div>
</div>
""", unsafe_allow_html=True)
            uploaded_ink = st.file_uploader(
                "Historiska inköpskurser (CSV)",
                type=["csv"],
                key="avanza_inkopskurser",
                help="Valfri — ger exakta köpdatum. Filen laddas inte upp till någon server.",
            )

        # Parsa inkopskurser om uppladdad
        inkopskurser_data: dict = {}
        if uploaded_ink is not None:
            try:
                inkopskurser_data = avanza_import.parse_inkopskurser_csv(uploaded_ink.getvalue())
                if inkopskurser_data:
                    st.success(f"✅ Historiska inköpskurser laddade — {len(inkopskurser_data)} ISIN-poster hittades.")
                    # Knapp för att uppdatera köpdatum på befintliga innehav direkt
                    if not holdings.empty and st.button(
                        "📅 Uppdatera köpdatum på befintliga innehav",
                        key="btn_update_dates", use_container_width=True,
                        help="Matchar dina innehav mot inköpskurser-filen via ISIN och skriver in rätt köpdatum."
                    ):
                        # Bygg ISIN→ticker-map från positioner-filen om tillgänglig
                        isin_map: dict[str, str] = {}
                        if "isin" in holdings.columns:
                            for _, _hr in holdings.iterrows():
                                _isin = str(_hr.get("isin", "")).strip()
                                if _isin:
                                    isin_map[_isin] = str(_hr["ticker"]).upper()

                        # Försök matcha via positioner-rådata om isin saknas i holdings
                        # Annars: läs ISIN direkt från inkopskurser via råfil-lookup
                        h_upd = holdings.copy()
                        for col in ("buy_date", "isin"):
                            if col not in h_upd.columns:
                                h_upd[col] = ""
                        n_updated = 0
                        if "isin" in h_upd.columns:
                            for idx, hrow in h_upd.iterrows():
                                isin_h = str(hrow.get("isin", "") or "").strip()
                                if not isin_h or isin_h not in inkopskurser_data:
                                    continue
                                shares = float(hrow.get("shares") or 0)
                                bd = avanza_import.get_buy_date_from_inkopskurser(
                                    isin_h, shares, inkopskurser_data
                                )
                                if bd:
                                    h_upd.at[idx, "buy_date"] = bd
                                    n_updated += 1
                        if n_updated:
                            _save_holdings_user(h_upd)
                            st.success(f"✅ Köpdatum uppdaterat för {n_updated} innehav.")
                            st.rerun()
                        else:
                            st.info("Inga ISIN-matchningar hittades — importera positioner-filen en gång så att ISIN sparas, tryck sedan här.")
                else:
                    st.warning("Kunde inte läsa inköpskurser-filen. Kontrollera att det är rätt export.")
            except Exception:
                pass

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

                    # Fonder: använd fondnamnet som lookup-nyckel (ingen ticker)
                    fund_key = name.upper()[:30] if security_type == "fund" else suggested.upper()
                    existing_vals = _existing_konto.get(fund_key) if fund_key else None
                    if existing_vals is None:
                        row_status  = "new"; status_badge = "🟢 Ny"; status_color = "#4caf50"
                        default_check = (security_type == "fund") or (bool(suggested) and security_type != "certificate")
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
                        if security_type == "fund":
                            mv_csv = float(r.get("market_value") or 0)
                            total_val = mv_csv if mv_csv > 0 else new_shares * new_cost
                            c2.caption(f"Marknadsvärde: {total_val:,.0f} kr")
                            c3.caption(f"{new_shares:.4f} andelar")
                        else:
                            c2.caption(f"Antal: {new_shares:.2f}")
                            c3.caption(f"Pris: {new_cost:.2f}")
                        if security_type == "fund":
                            c4.caption("Fonder hanteras utan ticker")
                            ticker_val = ""
                        else:
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
                    h = pd.DataFrame(columns=["ticker", "shares", "cost_basis", "konto", "typ", "buy_date"])
                n_add = n_upd = 0
                today_iso = datetime.date.today().isoformat()
                for item in import_data:
                    if not item["import"]:
                        continue
                    is_fund_item = item.get("security_type") == "fund"
                    t = item["ticker"]
                    # Fonder har inget yfinance-ticker — använd fondnamnet som nyckel
                    if is_fund_item and not t:
                        t = str(item["row"].get("name") or item["row"].get("kortnamn") or "FOND").upper()[:30]
                    if not t:
                        continue
                    s = float(item["row"].get("shares") or 0)
                    c = float(item["row"].get("cost_basis") or 0)
                    raw_mv = item["row"].get("market_value")
                    mv_import = float(raw_mv) if raw_mv is not None and str(raw_mv) not in ("", "nan") else None
                    row_typ = item.get("security_type", "")
                    if row_typ == "fund":
                        row_typ = "fond"
                    elif row_typ not in ("aktier", "fond", "etf", "certificate"):
                        row_typ = ""
                    buy_date_val = str(item["row"].get("buy_date", "") or "").strip() or today_iso
                    isin_val = str(item["row"].get("isin", "") or "").strip()
                    h = _upsert_holding(h, t, s, c, konto=konto_name, typ=row_typ,
                                        buy_date=buy_date_val, market_value=mv_import,
                                        isin=isin_val)
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
                                _isin_a = str(r.get("isin", "")).strip()
                                _shares_a = float(r.get("shares") or 0)
                                _bd_a = (
                                    avanza_import.get_buy_date_from_inkopskurser(
                                        _isin_a, _shares_a, inkopskurser_data
                                    ) if inkopskurser_data and _isin_a
                                    else None
                                ) or datetime.date.today().isoformat()
                                rows_enriched.append({
                                    "name":         r.get("name"),
                                    "shares":       r.get("shares"),
                                    "cost_basis":   r.get("cost_basis"),
                                    "market_value": r.get("market_value"),
                                    "isin":         r.get("isin"),
                                    "_suggested_ticker": suggested,
                                    "_security_type":    sec_type,
                                    "buy_date":     _bd_a,
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
                                columns=["ticker", "shares", "cost_basis", "konto", "typ", "buy_date"])
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
                            _isin_b = str(r.get("isin", "")).strip() if "isin" in df_az.columns else ""
                            _shares_b = float(r.get("shares") or 0)
                            _bd_b = (
                                avanza_import.get_buy_date_from_inkopskurser(
                                    _isin_b, _shares_b, inkopskurser_data
                                ) if inkopskurser_data and _isin_b
                                else None
                            ) or datetime.date.today().isoformat()
                            rows_enriched2.append({
                                **r.to_dict(),
                                "_suggested_ticker": suggested,
                                "_security_type": sec_type,
                                "buy_date": _bd_b,
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
            # Köpdatum
            buy_date_input = st.date_input("Köpdatum", value=datetime.date.today(),
                                           key="manual_buy_date")
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
                                        konto=m_konto, typ=m_typ,
                                        buy_date=buy_date_input.isoformat())
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
            # ── Rensa hela portföljen ────────────────────────────────────
            with st.expander("⚠️ Rensa hela portföljen"):
                st.warning("Detta tar bort **alla** aktier och fonder permanent.")
                if st.button("🗑️ Ta bort alla innehav", key="btn_clear_all",
                             type="primary", use_container_width=True):
                    empty_h = pd.DataFrame(
                        columns=["ticker", "shares", "cost_basis", "konto", "typ", "buy_date"]
                    )
                    _save_holdings_user(empty_h)
                    st.success("✅ Alla innehav borttagna.")
                    st.rerun()

            st.divider()

            tickers = holdings["ticker"].tolist()
            sel = st.selectbox("Välj aktie att hantera", tickers, key="port_remove_sel")
            _sel_match = holdings[holdings["ticker"] == sel]
            if _sel_match.empty:
                st.rerun()
                return
            row = _sel_match.iloc[0]

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
            "Kalenderår": datetime.date.today().year + year - 1,
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


# ══════════════════════════════════════════════════════════════════════════════
# SUB-TAB FUNKTIONER
# ══════════════════════════════════════════════════════════════════════════════

def _tab_overview(holdings_view: pd.DataFrame, score_data: dict, df: pd.DataFrame):
    """Sub-tab: Översikt — KPI-rad, portföljvärde-chart, period-avkastning, innehav-tabell, sektorpaj, utdelningar."""
    import streamlit.components.v1 as _sc1
    _sc1.html(
        "<script>try{var el=window.parent.document.querySelector('[data-testid=\"stMain\"]');"
        "if(!el)el=window.parent.document.body;"
        "el.scrollTo({top:0,behavior:'instant'});}catch(e){}</script>",
        height=0,
    )

    rows = _build_rows(holdings_view, score_data)
    stock_rows_ov = [r for r in rows if not r.get("_is_fund")]
    fund_rows_ov  = [r for r in rows if r.get("_is_fund")]
    n_pos      = len(stock_rows_ov)
    n_funds_ov = len(fund_rows_ov)

    # ── Toggle: styr HELA Översikt-fliken (KPI, chart, period-avkastning) ────
    _th_l, _th_r = st.columns([4, 1])
    with _th_r:
        include_funds = st.toggle(
            "🏦 Inkl. fonder",
            key="chart_incl_funds",
            value=False,
            help="Inkludera/exkludera fonder i totalt värde, portföljchart och period-avkastning",
        )

    # Beräkna KPI-värden baserat på toggle
    active_rows = rows if include_funds else stock_rows_ov
    total_mv    = sum(r.get("_market_value") or 0 for r in active_rows)
    total_inv   = sum(float(r.get("Inköpspris") or 0) * float(r.get("Antal") or 0) for r in active_rows)
    pnl_vals    = [r["_pnl_pct"] for r in active_rows if isinstance(r.get("_pnl_pct"), (int, float))]
    total_pnl_kr  = total_mv - total_inv
    total_pnl_pct = (total_pnl_kr / total_inv * 100) if total_inv > 0 else 0

    # Spara daglig snapshot (alltid med fonder, oavsett toggle)
    _all_mv  = sum(r.get("_market_value") or 0 for r in rows)
    _all_inv = sum(float(r.get("Inköpspris") or 0) * float(r.get("Antal") or 0) for r in rows)
    try:
        save_portfolio_snapshot(_all_mv, _all_inv)
    except Exception:
        pass

    pos_label = f"{n_pos}" if not n_funds_ov else f"{n_pos} + {n_funds_ov} 🏦"
    kpi_row([
        ("POSITIONER", pos_label, None),
        ("TOTALT VÄRDE", f"{total_mv:,.0f} kr", None),
        ("TOTAL P&L", f"{total_pnl_kr:+,.0f} kr", f"{total_pnl_pct:+.1f}%"),
        ("BÄST / SÄMST",
         f"+{max(pnl_vals):.1f}% / {min(pnl_vals):.1f}%" if pnl_vals else "—", None),
    ])

    # ── Innehav-detaljer (klickbar) ──────────────────────────────────────────
    with st.expander(f"📋 Visa alla innehav ({n_pos} aktier{f' + {n_funds_ov} fonder' if n_funds_ov else ''})"):
        if stock_rows_ov:
            st.markdown("**Aktier**")
            stocks_detail = [{
                "Ticker":     r["Ticker"],
                "Bolag":      (r.get("Bolag") or r["Ticker"])[:30],
                "Antal":      r.get("Antal"),
                "Inköpspris": f"{float(r['Inköpspris']):.2f}" if r.get("Inköpspris") else "—",
                "Värde":      f"{r['_market_value']:,.0f} kr" if r.get("_market_value") else "—",
                "P&L %":      f"{r['_pnl_pct']:+.1f}%" if isinstance(r.get("_pnl_pct"), float) else "—",
                "Konto":      r.get("Konto", ""),
            } for r in stock_rows_ov]
            st.dataframe(pd.DataFrame(stocks_detail), use_container_width=True, hide_index=True)
        if fund_rows_ov:
            st.markdown("**Fonder**")
            funds_detail = [{
                "Namn":            (r.get("Bolag") or r["Ticker"])[:35],
                "Antal andelar":   f"{float(r['Antal']):.4f}" if r.get("Antal") else "—",
                "GAV/andel (kr)":  f"{float(r['Inköpspris']):.2f}" if r.get("Inköpspris") else "—",
                "Inköpsvärde":     f"{float(r['Inköpspris'] or 0)*float(r['Antal'] or 0):,.0f} kr",
                "Marknadsvärde":   f"{r['_market_value']:,.0f} kr" if r.get("_market_value") else "—",
                "P&L %":           f"{r['_pnl_pct']:+.1f}%" if isinstance(r.get("_pnl_pct"), float) else "—",
                "Konto":           r.get("Konto", ""),
            } for r in fund_rows_ov]
            st.dataframe(pd.DataFrame(funds_detail), use_container_width=True, hide_index=True)

    # ── Portföljvärde-chart ──────────────────────────────────────────────────
    st.markdown("#### Portföljvärde historik")
    period_map = {"1M": "1mo", "3M": "3mo", "6M": "6mo", "1Å": "1y", "Allt": "2y"}
    _col_per, _col_bench = st.columns([3, 2])
    with _col_per:
        period_lbl = st.radio("Period", list(period_map.keys()), index=3,
                              horizontal=True, key="port_period", label_visibility="collapsed")
    with _col_bench:
        benchmark_lbl = st.selectbox(
            "Jämför mot",
            ["Ingen", "S&P 500 (SPY)", "Nasdaq (QQQ)", "OMXS30 (^OMX)", "Världsindex (ACWI)"],
            index=0, key="port_benchmark", label_visibility="collapsed",
        )
    period_yf = period_map[period_lbl]
    _bm_map = {"S&P 500 (SPY)": "SPY", "Nasdaq (QQQ)": "QQQ",
               "OMXS30 (^OMX)": "^OMX", "Världsindex (ACWI)": "ACWI"}
    benchmark_ticker = _bm_map.get(benchmark_lbl, "")

    # Fondvärde-konstant — bara om toggle är på
    fund_constant = 0.0
    if include_funds and fund_rows_ov:
        for r in fund_rows_ov:
            mv = r.get("_market_value") or 0
            if not mv:
                mv = float(r.get("Inköpspris") or 0) * float(r.get("Antal") or 0)
            fund_constant += mv

    # Chart: bara aktieposter (fonder har inga yfinance-kurser)
    stocks_hv = holdings_view[holdings_view.apply(
        lambda row: not _is_fund_holding(
            str(row.get("typ", "")), str(row.get("konto", "")), ticker=str(row.get("ticker", ""))
        ), axis=1
    )] if not holdings_view.empty else holdings_view

    with st.spinner("Hämtar prishistorik..."):
        fig = portfolio_value_chart(stocks_hv, period=period_yf, fund_constant=fund_constant,
                                    benchmark=benchmark_ticker)
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    # ── Period-avkastning (respekterar toggle) ───────────────────────────────
    _hv_for_rets = holdings_view if include_funds else (
        holdings_view[~holdings_view.apply(
            lambda _r: _is_fund_holding(str(_r.get("typ","")), str(_r.get("konto","")), ticker=str(_r.get("ticker",""))),
            axis=1
        )] if not holdings_view.empty else holdings_view
    )
    with st.spinner(""):
        period_rets = calc_period_returns(_hv_for_rets)
    if period_rets:
        cols_ret = st.columns(len(period_rets))
        for col, (label, (kr, pct)) in zip(cols_ret, period_rets.items()):
            color = "#4caf50" if pct >= 0 else "#ef5350"
            col.markdown(
                f'<div style="text-align:center;background:#1e2230;border-radius:8px;padding:8px 4px;">'
                f'<div style="font-size:10px;color:#8892a4;letter-spacing:.08em">{label}</div>'
                f'<div style="font-size:16px;font-weight:700;color:{color}">{pct:+.1f}%</div>'
                f'<div style="font-size:11px;color:#64748b">{kr:+,.0f} kr</div>'
                f'</div>', unsafe_allow_html=True
            )

    # ── Innehav-tabell + sektordiagram ───────────────────────────────────────
    col_table, col_pie = st.columns([3, 1])

    display_rows_stocks = []
    display_rows_funds  = []
    for r in rows:
        pnl_str = f"{r['_pnl_pct']:+.1f}%" if isinstance(r.get("_pnl_pct"), (int, float)) else "—"
        entry = {
            "Ticker":  r.get("Ticker", ""),
            "Bolag":   (r.get("Bolag") or "")[:25],
            "P&L %":   pnl_str,
            "Värde":   f"{r.get('_market_value', 0):,.0f} kr" if r.get("_market_value") else "—",
            "Konto":   r.get("Konto", ""),
            "_pnl":    r.get("_pnl_pct") or 0,
            "_is_fund": r.get("_is_fund", False),
        }
        if r.get("_is_fund"):
            display_rows_funds.append(entry)
        else:
            display_rows_stocks.append(entry)

    with col_table:
        if display_rows_stocks:
            df_show = pd.DataFrame(display_rows_stocks).drop(columns=["_pnl", "_is_fund"], errors="ignore")
            st.dataframe(df_show, use_container_width=True, hide_index=True)
        if display_rows_funds:
            st.caption(f"🏦 {len(display_rows_funds)} fond{'er' if len(display_rows_funds)>1 else ''} ingår — se detaljer i 📋 Visa alla innehav ovan eller i Analys-fliken")

    with col_pie:
        stock_rows_only = [r for r in rows if not r.get("_is_fund")]
        if len(stock_rows_only) > 1 and df is not None and not df.empty:
            tickers_for_pie = [r["Ticker"] for r in stock_rows_only]
            mvs = {r["Ticker"]: r.get("_market_value", 0) for r in stock_rows_only}
            try:
                fig_pie = holdings_pie(
                    holdings_view[holdings_view["ticker"].isin(tickers_for_pie)],
                    df,
                    mvs,
                )
                st.plotly_chart(fig_pie, use_container_width=True, config={"displayModeBar": False})
            except Exception:
                pass

    # ── Utdelningar ──────────────────────────────────────────────────────────
    _holdings_hash = str(sorted(holdings_view["ticker"].tolist()))
    if st.session_state.get("div_summary_hash") != _holdings_hash:
        with st.spinner("Hämtar utdelningsdata…"):
            _div_summary = _calc_dividend_summary(holdings_view, score_data)
            st.session_state["div_summary"] = _div_summary
            st.session_state["div_summary_hash"] = _holdings_hash
    else:
        _div_summary = st.session_state.get("div_summary", {})

    if _div_summary.get("total_annual_sek", 0) > 0:
        st.markdown("---")
        st.markdown("#### 💰 Utdelningar")
        kpi_row([
            ("ÅRSUTDELNING", f"{_div_summary['total_annual_sek']:,.0f} kr", None),
            ("YIELD/KOST", f"{_div_summary['avg_yield_on_cost']:.1f}%", None),
        ])

    # ── Excel-export ─────────────────────────────────────────────────────────
    try:
        port_df = pd.DataFrame(rows)
        stock_rows_exp = [r for r in rows if not r.get("_is_fund")]
        _excel_bytes = _portfolio_excel_bytes(port_df, stock_rows_exp, score_data)
        st.download_button(
            label="📥 Exportera portfölj (Excel)",
            data=_excel_bytes,
            file_name=f"portfolio_{pd.Timestamp.now().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="dl_portfolio_excel",
            help="Ladda ner portföljdata som Excel-fil med innehav + rekommendationer.",
        )
    except Exception:
        pass


def _tab_analys(holdings_view: pd.DataFrame, score_data: dict, df: pd.DataFrame):
    """Sub-tab: Analys — rekommendationer, stresstest, utdelningssimulator, AI-chat."""
    import streamlit.components.v1 as _sc1
    _sc1.html(
        "<script>try{var el=window.parent.document.querySelector('[data-testid=\"stMain\"]');"
        "if(!el)el=window.parent.document.body;"
        "el.scrollTo({top:0,behavior:'instant'});}catch(e){}</script>",
        height=0,
    )

    rows = _build_rows(holdings_view, score_data)
    stock_rows = [r for r in rows if not r.get("_is_fund")]
    fund_rows  = [r for r in rows if r.get("_is_fund")]

    # ── Rekommendationer ─────────────────────────────────────────────────────
    if stock_rows:
        st.markdown("### 💡 Rekommendationer")
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

    # ── Fonder P&L ───────────────────────────────────────────────────────────
    if fund_rows:
        st.markdown("### 🏦 Fonder")
        st.caption("Fondinnehav analyseras inte med scanner-signaler — enbart värde och P&L visas.")
        for r in fund_rows:
            cost   = float(r.get("Inköpspris") or 0)
            antal  = float(r.get("Antal") or 0)
            mv     = r.get("_market_value") or (cost * antal if cost and antal else None)
            inv    = cost * antal if cost and antal else None
            pnl_kr = (mv - inv) if mv and inv else None
            pnl_pct = r.get("_pnl_pct")
            pnl_color = "#4caf50" if (pnl_pct or 0) > 0 else "#ef5350" if (pnl_pct or 0) < 0 else "#8892a4"
            name   = (r.get("Bolag") or r["Ticker"])[:40]
            with st.container(border=True):
                c1, c2, c3, c4 = st.columns([3, 2, 2, 2])
                with c1:
                    st.markdown(f"🏦 **{name}**")
                    st.caption(f"Konto: {r['Konto']}  ·  {antal:.4f} andelar  ·  GAV {cost:.2f} kr/andel")
                with c2:
                    st.markdown(
                        f'<div style="padding-top:4px"><div style="font-size:10px;color:#8892a4;letter-spacing:.08em;text-transform:uppercase">Inköpsvärde</div>'
                        f'<div style="font-size:18px;font-weight:600;color:#e8eaf0">{inv:,.0f} kr</div></div>' if inv else "—",
                        unsafe_allow_html=True,
                    )
                with c3:
                    st.markdown(
                        f'<div style="padding-top:4px"><div style="font-size:10px;color:#8892a4;letter-spacing:.08em;text-transform:uppercase">Marknadsvärde</div>'
                        f'<div style="font-size:18px;font-weight:600;color:#e8eaf0">{mv:,.0f} kr</div></div>' if mv else "—",
                        unsafe_allow_html=True,
                    )
                with c4:
                    pnl_pct_str = f"{pnl_pct:+.1f}%" if pnl_pct is not None else "—"
                    pnl_kr_str  = f"{pnl_kr:+,.0f} kr" if pnl_kr is not None else ""
                    st.markdown(
                        f'<div style="padding-top:4px"><div style="font-size:10px;color:#8892a4;letter-spacing:.08em;text-transform:uppercase">P&L</div>'
                        f'<div style="font-size:18px;font-weight:700;color:{pnl_color}">{pnl_pct_str}</div>'
                        f'<div style="font-size:11px;color:#64748b">{pnl_kr_str}</div></div>',
                        unsafe_allow_html=True,
                    )

    st.markdown("---")

    # ── Stresstest ───────────────────────────────────────────────────────────
    with st.expander("📉 Stresstest — kraschscenarier"):
        _portfolio_stress_test(holdings_view, score_data)

    # ── Utdelningssimulator ──────────────────────────────────────────────────
    with st.expander("💰 Utdelningssimulator"):
        _dividend_simulator(holdings_view, score_data)

    # ── AI-portföljchat ──────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 🤖 AI-portföljanalys")
    _portfolio_ai_chat(holdings_view, score_data, df)


def _portfolio_ai_chat(holdings_view: pd.DataFrame, score_data: dict, df: pd.DataFrame):
    """Interaktiv AI-chat om portföljen."""
    # Snabbfrågor
    quick_q = [
        "Vad bör jag sälja baserat på nuvarande signaler?",
        "Hur diversifierad är min portfölj?",
        "Vad är min portföljs totala risk?",
        "Vilka aktier har starkast momentum just nu?",
    ]
    st.caption("Snabbfrågor:")
    q_cols = st.columns(len(quick_q))
    for col, q in zip(q_cols, quick_q):
        if col.button(q[:30] + "…", key=f"paq_{q[:15]}", use_container_width=True):
            st.session_state.setdefault("portfolio_chat_history", [])
            st.session_state["portfolio_chat_history"].append({"role": "user", "content": q})
            st.session_state["portfolio_chat_pending"] = True

    # Chathistorik
    chat_history = st.session_state.get("portfolio_chat_history", [])
    for msg in chat_history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Inmatning
    user_input = st.chat_input("Fråga om din portfölj…", key="portfolio_chat_input")
    if user_input:
        st.session_state.setdefault("portfolio_chat_history", [])
        st.session_state["portfolio_chat_history"].append({"role": "user", "content": user_input})
        st.session_state["portfolio_chat_pending"] = True
        st.rerun()

    # Besvara väntande fråga
    if st.session_state.pop("portfolio_chat_pending", False):
        history = st.session_state.get("portfolio_chat_history", [])
        last_q = history[-1]["content"] if history else ""

        # Bygg portfölj-kontext
        rows = _build_rows(holdings_view, score_data)
        ctx_lines = ["## Din portfölj\n"]
        for r in rows:
            if r.get("_is_fund"):
                ctx_lines.append(f"- **{r['Ticker']}** (fond) — {r.get('Antal',0):.0f} st à {r.get('Inköpspris',0):.2f} kr, P&L: {r.get('_pnl_pct','—')}")
            else:
                ctx_lines.append(
                    f"- **{r['Ticker']}** ({r.get('Bolag','')}) — {r.get('Antal',0):.0f} st, "
                    f"pris: {r.get('Pris nu','—')}, P&L: {r.get('_pnl_pct','—')}, "
                    f"Score: {r.get('Score','—')}, Signal: {r.get('Entry','—')}"
                )
        portfolio_context = "\n".join(ctx_lines)

        provider = st.session_state.get("ai_provider", "auto")

        with st.chat_message("assistant"):
            with st.spinner("Analyserar…"):
                try:
                    resp = ai_analysis.ai_chat(
                        messages=history,
                        system=f"Du är en portföljrådgivare. Här är användarens innehav:\n\n{portfolio_context}",
                        provider=provider,
                    )
                    st.markdown(resp)
                    st.session_state["portfolio_chat_history"].append({"role": "assistant", "content": resp})
                except Exception as e:
                    st.error(f"AI-fel: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# HUVUD-FUNKTION
# ══════════════════════════════════════════════════════════════════════════════

def page_portfolio(df: pd.DataFrame = None, holdings: pd.DataFrame = None,
                   watchlist: list = None, sc_df: pd.DataFrame = None):
    """Portfölj-sidan med 3 sub-tabs: Översikt | Analys | Hantera."""
    # Ladda alltid färsk holdings (ignorera ev. inskickad för bakåtkompatibilitet)
    holdings = load_portfolio()
    score_data = _build_score_data(holdings, df, sc_df)

    st.title("💼 Portfölj")
    _show_scan_pending_notifications()

    if holdings.empty:
        _manage_portfolio_section(holdings)
        return

    # Konto-filter
    holdings_view, _sel_konto = _konto_filter_section(holdings)

    # 3 SUB-TABS
    tab_overview, tab_analys, tab_hantera = st.tabs([
        "📊 Översikt", "🧠 Analys", "⚙️ Hantera"
    ])

    with tab_overview:
        _tab_overview(holdings_view, score_data, df)

    with tab_analys:
        _tab_analys(holdings_view, score_data, df)

    with tab_hantera:
        _manage_portfolio_section(holdings)
        _show_scan_pending_notifications()

    # ── Bevakningslista (utanför tabs, längst ner) ────────────────────────────
    if watchlist is None:
        watchlist = load_watchlist()

    st.markdown("---")
    st.subheader("⭐ Bevakningslista")
    if not watchlist:
        st.info("Bevakningslistan är tom. Sök efter aktier på 🔍 Aktie-sök och klicka 'Lägg till i bevakningslista'.")
    else:
        score_lu = {}
        if df is not None and not df.empty and "ticker" in df.columns:
            score_lu = df.set_index("ticker").to_dict("index")

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
