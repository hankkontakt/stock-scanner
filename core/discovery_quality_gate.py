"""
discovery_quality_gate.py — Kvalitetsfiltrering för universe discovery
======================================================================
Implementerar ett 4-lagers filter:

  Layer 1 – hard_exclude():    Absoluta minimikrav (penny stocks, extreme debt, shells)
  Layer 2 – quality_score():   Sektor-aware mjuka poäng (0–100)
  Layer 3 – beneish_mscore():  Resultatmanipulationsdetektering (Enron-modellen)
  Layer 4 – quality_tier():    HIGH / MEDIUM / SPECULATIVE-klassificering

Alla funktioner tar ett `info`-dikt (från yfinance.Ticker.info) +
valfritt `financials`-dikt (från yfinance.Ticker.financials/.balance_sheet)
och returnerar deterministiska, enkelt testbara resultat.

Separata trösklar för universe_type="universe" vs "smallcap".
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ── Sector-grupper ──────────────────────────────────────────────────────────

_FINANCIAL_SECTORS = {
    "Financial Services", "Banks", "Insurance", "Capital Markets",
    "Asset Management", "Consumer Finance", "Mortgage Finance",
    "Financial", "Diversified Financials",
}
_TECH_SECTORS = {
    "Technology", "Information Technology", "Software", "Semiconductors",
    "Communication Services", "Internet Content & Information",
}
_HEALTHCARE_SECTORS = {
    "Healthcare", "Biotechnology", "Pharmaceuticals",
    "Medical Devices", "Health Technology",
}
_ENERGY_MATERIAL_SECTORS = {
    "Energy", "Basic Materials", "Materials", "Mining",
    "Oil & Gas", "Oil, Gas & Consumable Fuels",
}
_UTILITY_REIT_SECTORS = {
    "Utilities", "Real Estate", "REITs",
    "Diversified REITs", "Specialty REITs",
}

# ── Hjälpfunktioner ─────────────────────────────────────────────────────────

def _get(info: dict, *keys, default=None):
    """Hämtar ett värde från info-dikt med fallback-nycklar."""
    for k in keys:
        v = info.get(k)
        if v is not None and str(v) not in ("", "None", "nan", "NaN", "Infinity", "inf"):
            try:
                return float(v) if isinstance(v, (int, float)) else v
            except (ValueError, TypeError):
                return v
    return default


def _float(info: dict, *keys, default: Optional[float] = None) -> Optional[float]:
    """Hämtar ett numeriskt värde, returnerar None om ej tillgängligt."""
    for k in keys:
        v = info.get(k)
        if v is None:
            continue
        try:
            f = float(v)
            if f != f:  # NaN
                continue
            if abs(f) > 1e18:  # Infinity-guard
                continue
            return f
        except (ValueError, TypeError):
            continue
    return default


def _is_nordic(ticker: str) -> bool:
    t = ticker.upper()
    return any(t.endswith(s) for s in (".ST", ".CO", ".OL", ".HE"))


def _detect_sector(info: dict) -> str:
    return str(info.get("sector") or info.get("industry") or "").strip()


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 1 — HARD EXCLUSION
# ══════════════════════════════════════════════════════════════════════════════

def hard_exclude(
    info: dict,
    ticker: str = "",
    universe_type: str = "universe",
) -> tuple[bool, str]:
    """
    Kontrollerar absoluta minimikrav. Returnerar (True, reason) om tickern
    ska exkluderas OAVSETT källa eller confidence.

    Args:
        info:           yfinance .info-dikt
        ticker:         Tickersymbol (för suffix-detektering)
        universe_type:  "universe" (large/mid cap) eller "smallcap"

    Returns:
        (True, reason_str)  om tickern ska exkluderas
        (False, "")         om den klarar hård filtrering
    """
    nordic = _is_nordic(ticker)
    is_small = universe_type == "smallcap"

    # Trösklar
    price_min       = 2.0 if not nordic else 2.0       # USD / SEK
    mc_min_usd      = 100_000_000 if not is_small else 5_000_000
    mc_min_sek      = 100_000_000 if not is_small else 50_000_000
    vol_min         = 100_000 if not is_small else 20_000
    turnover_min    = 500_000 if not is_small else 150_000   # USD-ekv / SEK

    # ── 1. Pris ──────────────────────────────────────────────────────────────
    price = _float(info, "currentPrice", "regularMarketPrice", "previousClose")
    if price is not None:
        if price < price_min:
            return True, f"Pris {price:.2f} < {price_min} (penny stock)"

    # ── 2. Market cap ────────────────────────────────────────────────────────
    mc = _float(info, "marketCap")
    if mc is not None and mc > 0:
        mc_min = mc_min_sek if nordic else mc_min_usd
        if mc < mc_min:
            return True, f"Market cap {mc/1e6:.0f}M < {mc_min/1e6:.0f}M minimum"

    # ── 3. Volym ─────────────────────────────────────────────────────────────
    vol = _float(info, "averageVolume", "averageVolume10days")
    if vol is not None and vol > 0:
        if vol < vol_min:
            return True, f"Daglig volym {vol:.0f} < {vol_min} minimum"

    # ── 4. QuoteType ─────────────────────────────────────────────────────────
    qt = str(info.get("quoteType") or "").upper()
    if qt and qt not in ("EQUITY", "ETF", "MUTUALFUND", ""):
        return True, f"quoteType={qt} (ej aktie/ETF)"

    # ── 5. Negativt eget kapital (utom finanssektorn) ─────────────────────
    sector = _detect_sector(info)
    if sector not in _FINANCIAL_SECTORS:
        book_val = _float(info, "bookValue")
        shares   = _float(info, "sharesOutstanding")
        if book_val is not None and shares is not None and shares > 0:
            total_equity = book_val * shares
            if total_equity < 0:
                return True, f"Negativt eget kapital ({total_equity/1e9:.2f}B)"

    # ── 6. Noll-intäkter (shell-bolag) ───────────────────────────────────────
    rev = _float(info, "totalRevenue", "revenuePerShare")
    if rev is not None and rev == 0.0:
        return True, "Noll intäkter — möjligt shell-bolag"

    # ── 7. Extremt P/E (extremvärdering) ─────────────────────────────────────
    pe = _float(info, "forwardPE", "trailingPE")
    if pe is not None and pe > 0:
        if pe > 500:
            return True, f"P/E={pe:.0f} > 500 (extremvärdering)"

    # ── 8. Extrem skuld ──────────────────────────────────────────────────────
    if sector not in _FINANCIAL_SECTORS and sector not in _UTILITY_REIT_SECTORS:
        de = _float(info, "debtToEquity")
        if de is not None and de > 0:
            if de > 800:  # 800% = 8x, extremt
                return True, f"Debt/Equity={de:.0f}% > 800% (extrem hävstång)"

    return False, ""


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 2 — QUALITY SCORE (0–100)
# ══════════════════════════════════════════════════════════════════════════════

def compute_quality_score(
    info: dict,
    ticker: str = "",
    universe_type: str = "universe",
) -> tuple[float, list[str]]:
    """
    Beräknar ett kvalitetspoäng (0–100) för en kandidat baserat på
    fundamentala nyckeltal. Returnerar (score, [flaggor]).

    Flaggor är förklarande textrader som visas i admin-UI:t.
    """
    score = 50.0  # Neutralt startpoäng
    flags: list[str] = []
    sector = _detect_sector(info)
    is_small = universe_type == "smallcap"

    # ── Lönsamhet ────────────────────────────────────────────────────────────
    roe = _float(info, "returnOnEquity")
    if roe is not None:
        roe_pct = roe * 100 if abs(roe) < 2 else roe
        if roe_pct > 15:
            score += 8
        elif roe_pct > 8:
            score += 4
        elif roe_pct < 0:
            score -= 10
            flags.append(f"Negativ ROE ({roe_pct:.1f}%)")

    profit_margin = _float(info, "profitMargins")
    if profit_margin is not None:
        pm_pct = profit_margin * 100 if abs(profit_margin) < 2 else profit_margin
        if pm_pct > 15:
            score += 6
        elif pm_pct > 5:
            score += 3
        elif pm_pct < 0:
            score -= 8
            flags.append(f"Negativ vinstmarginal ({pm_pct:.1f}%)")

    gross_margin = _float(info, "grossMargins")
    if gross_margin is not None:
        gm_pct = gross_margin * 100 if abs(gross_margin) < 2 else gross_margin
        if gm_pct > 40:
            score += 5
        elif gm_pct > 20:
            score += 2
        elif gm_pct < 10 and sector in _TECH_SECTORS:
            score -= 6
            flags.append(f"Låg bruttomarginal för tech ({gm_pct:.1f}%)")

    # ── Tillväxt ─────────────────────────────────────────────────────────────
    rev_growth = _float(info, "revenueGrowth")
    if rev_growth is not None:
        rg_pct = rev_growth * 100 if abs(rev_growth) < 2 else rev_growth
        if rg_pct > 20:
            score += 8
        elif rg_pct > 5:
            score += 4
        elif rg_pct < -10:
            score -= 8
            flags.append(f"Negativ intäktstillväxt ({rg_pct:.1f}%)")
        elif rg_pct < 0:
            score -= 4

    eps_growth = _float(info, "earningsGrowth")
    if eps_growth is not None:
        eg_pct = eps_growth * 100 if abs(eps_growth) < 2 else eps_growth
        if eg_pct > 20:
            score += 5
        elif eg_pct < -20:
            score -= 5
            flags.append(f"Kraftigt fallande EPS ({eg_pct:.1f}%)")

    # ── Skuldsättning ────────────────────────────────────────────────────────
    if sector not in _FINANCIAL_SECTORS:
        de = _float(info, "debtToEquity")
        if de is not None and de >= 0:
            de_ratio = de / 100  # yfinance ger det i procent
            if de_ratio < 0.3:
                score += 5
            elif de_ratio < 0.8:
                score += 2
            elif de_ratio > 2.0:
                score -= 8
                flags.append(f"Hög skuldsättning D/E={de_ratio:.1f}x")
            elif de_ratio > 3.0:
                score -= 15
                flags.append(f"Mycket hög skuldsättning D/E={de_ratio:.1f}x")

    # ── Kassaflöde ───────────────────────────────────────────────────────────
    fcf = _float(info, "freeCashflow")
    if fcf is not None:
        if fcf > 0:
            score += 7
        elif fcf < 0 and not is_small:
            score -= 6
            flags.append(f"Negativt fritt kassaflöde ({fcf/1e9:.2f}B)")

    # ── Analytikertäckning ───────────────────────────────────────────────────
    n_analysts = _float(info, "numberOfAnalystOpinions", "numberOfAnalysts")
    if n_analysts is not None:
        if n_analysts >= 5:
            score += 5
        elif n_analysts >= 2:
            score += 2
        elif n_analysts == 0 and not is_small:
            score -= 5
            flags.append("Inga analytiker täcker aktien")

    rec_mean = _float(info, "recommendationMean")
    if rec_mean is not None:
        # 1=Strong Buy, 5=Strong Sell
        if rec_mean <= 2.0:
            score += 6
        elif rec_mean <= 2.5:
            score += 3
        elif rec_mean >= 4.0:
            score -= 8
            flags.append(f"Analytikerkonsensus Sell ({rec_mean:.1f}/5)")

    # ── Värdering ────────────────────────────────────────────────────────────
    pe = _float(info, "forwardPE", "trailingPE")
    if pe is not None and pe > 0:
        if sector in _TECH_SECTORS:
            rev_g = _float(info, "revenueGrowth") or 0
            if pe > 60 and (rev_g * 100 if abs(rev_g) < 2 else rev_g) < 15:
                score -= 5
                flags.append(f"Högt P/E={pe:.0f} utan tillräcklig tillväxt")
        elif pe > 30:
            score -= 3
        elif pe < 12:
            score += 4  # Möjlig undervärderad

    pb = _float(info, "priceToBook")
    if pb is not None:
        if pb < 0:
            score -= 10
            flags.append(f"Negativt P/B ({pb:.2f}) — negativt eget kapital")
        elif pb > 8 and sector not in _TECH_SECTORS:
            score -= 3

    # ── Insider-ägande ───────────────────────────────────────────────────────
    insider_pct = _float(info, "heldPercentInsiders")
    if insider_pct is not None:
        ip = insider_pct * 100 if abs(insider_pct) < 2 else insider_pct
        if ip > 20:
            score += 4  # Insiders har skin in the game
        elif ip > 5:
            score += 2

    # ── Sektor-specifika bonusar/avdrag ──────────────────────────────────────
    if sector in _TECH_SECTORS:
        # Tech belönas för höga marginaler
        gm = _float(info, "grossMargins")
        if gm is not None:
            gm_pct = gm * 100 if abs(gm) < 2 else gm
            if gm_pct > 60:
                score += 5
    elif sector in _UTILITY_REIT_SECTORS:
        # Utilitys belönas för stabila utdelningar
        dy = _float(info, "dividendYield")
        if dy is not None and dy > 0:
            score += 4

    # Klamma slutpoäng
    score = max(0.0, min(100.0, score))
    return round(score, 1), flags


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 3 — BENEISH M-SCORE (bedrägeridetektering)
# ══════════════════════════════════════════════════════════════════════════════

def compute_beneish_mscore(financials: dict) -> tuple[Optional[float], str]:
    """
    Beräknar Beneish M-Score för att detektera möjlig resultatmanipulation.
    Kräver två år av finansiell data.

    Args:
        financials: Dikt med nycklar från yfinance finansiell historik:
            "revenue_t", "revenue_t1", "cogs_t", "cogs_t1",
            "receivables_t", "receivables_t1", "assets_t", "assets_t1",
            "ppe_t", "ppe_t1", "depreciation_t", "depreciation_t1",
            "sga_t", "sga_t1", "total_debt_t", "total_debt_t1",
            "current_liabilities_t", "current_liabilities_t1",
            "net_income_t", "operating_cashflow_t"

    Returns:
        (m_score, interpretation_str)
        m_score is None om data saknas
    """
    if not financials:
        return None, "Ej beräknad (data saknas)"

    def _v(key: str) -> Optional[float]:
        v = financials.get(key)
        if v is None:
            return None
        try:
            f = float(v)
            return f if (f == f and abs(f) < 1e18) else None
        except (ValueError, TypeError):
            return None

    rev_t   = _v("revenue_t")
    rev_t1  = _v("revenue_t1")
    cogs_t  = _v("cogs_t")
    cogs_t1 = _v("cogs_t1")
    rec_t   = _v("receivables_t")
    rec_t1  = _v("receivables_t1")
    ast_t   = _v("assets_t")
    ast_t1  = _v("assets_t1")
    ppe_t   = _v("ppe_t")
    ppe_t1  = _v("ppe_t1")
    dep_t   = _v("depreciation_t")
    dep_t1  = _v("depreciation_t1")
    sga_t   = _v("sga_t")
    sga_t1  = _v("sga_t1")
    ltd_t   = _v("total_debt_t")
    ltd_t1  = _v("total_debt_t1")
    cl_t    = _v("current_liabilities_t")
    cl_t1   = _v("current_liabilities_t1")
    ni_t    = _v("net_income_t")
    ocf_t   = _v("operating_cashflow_t")

    # Kräv de mest kritiska fälten
    required = [rev_t, rev_t1, ast_t, ast_t1]
    if any(v is None or v == 0 for v in required):
        return None, "Ej beräknad (otillräcklig finansiell data)"

    def _safe_div(a: Optional[float], b: Optional[float]) -> Optional[float]:
        if a is None or b is None or b == 0:
            return None
        return a / b

    # DSRI — Days Sales in Receivables Index
    dsri = None
    if rec_t and rec_t1 and rev_t and rev_t1 and rev_t > 0 and rev_t1 > 0:
        dsri = _safe_div(rec_t / rev_t, rec_t1 / rev_t1)

    # GMI — Gross Margin Index
    gmi = None
    if cogs_t and cogs_t1 and rev_t > 0 and rev_t1 > 0:
        gm_t  = (rev_t  - cogs_t)  / rev_t
        gm_t1 = (rev_t1 - cogs_t1) / rev_t1 if rev_t1 > 0 else None
        if gm_t1:
            gmi = gm_t1 / gm_t if gm_t != 0 else None

    # AQI — Asset Quality Index
    aqi = None
    if ppe_t and ppe_t1 and ast_t and ast_t1 and ast_t > 0 and ast_t1 > 0:
        aq_t  = 1 - (rec_t or 0 + ppe_t)  / ast_t  if ast_t  > 0 else None
        aq_t1 = 1 - (rec_t1 or 0 + ppe_t1) / ast_t1 if ast_t1 > 0 else None
        if aq_t and aq_t1 and aq_t1 != 0:
            aqi = aq_t / aq_t1

    # SGI — Sales Growth Index
    sgi = _safe_div(rev_t, rev_t1)

    # DEPI — Depreciation Index
    depi = None
    if dep_t and dep_t1 and ppe_t and ppe_t1 and dep_t > 0:
        d_t  = dep_t  / (dep_t  + ppe_t)  if (dep_t  + ppe_t)  > 0 else None
        d_t1 = dep_t1 / (dep_t1 + ppe_t1) if (dep_t1 + ppe_t1) > 0 else None
        if d_t and d_t1 and d_t != 0:
            depi = d_t1 / d_t

    # SGAI — SGA Expense Index
    sgai = None
    if sga_t and sga_t1 and rev_t > 0 and rev_t1 > 0:
        sgai = _safe_div(sga_t / rev_t, sga_t1 / rev_t1)

    # TATA — Total Accruals to Total Assets
    tata = None
    if ni_t is not None and ocf_t is not None and ast_t and ast_t > 0:
        tata = (ni_t - ocf_t) / ast_t

    # LVGI — Leverage Index
    lvgi = None
    if ltd_t and ltd_t1 and cl_t and cl_t1 and ast_t and ast_t1 and ast_t > 0 and ast_t1 > 0:
        lev_t  = (ltd_t  + cl_t)  / ast_t
        lev_t1 = (ltd_t1 + cl_t1) / ast_t1
        lvgi = _safe_div(lev_t, lev_t1)

    # Beräkna M-score med tillgängliga komponenter
    # Standardiserade vikter från originalmodellen
    m = -4.84
    count = 0
    if dsri  is not None: m += 0.920 * dsri;  count += 1
    if gmi   is not None: m += 0.528 * gmi;   count += 1
    if aqi   is not None: m += 0.404 * aqi;   count += 1
    if sgi   is not None: m += 0.892 * sgi;   count += 1
    if depi  is not None: m += 0.115 * depi;  count += 1
    if sgai  is not None: m -= 0.172 * sgai;  count += 1
    if tata  is not None: m += 4.679 * tata;  count += 1
    if lvgi  is not None: m -= 0.327 * lvgi;  count += 1

    if count < 3:
        return None, f"Ej beräknad (för få datapunkter: {count}/8)"

    # Tolkning
    if m > -1.00:
        interp = f"M={m:.2f} ⚠ Trolig manipulation (>-1.00) — EXKLUDERA"
    elif m > -1.78:
        interp = f"M={m:.2f} ⚠ Möjlig manipulation (>-1.78) — GRANSKA"
    elif m > -2.22:
        interp = f"M={m:.2f} 🟡 Gränszon (-1.78 till -2.22)"
    else:
        interp = f"M={m:.2f} ✅ Ingen uppenbar manipulation (<-2.22)"

    return round(m, 3), interp


def extract_financials_for_mscore(ticker_obj) -> dict:
    """
    Hämtar finansiell data från ett yfinance Ticker-objekt och
    returnerar ett dikt strukturerat för compute_beneish_mscore().
    """
    result: dict = {}
    try:
        fin  = ticker_obj.financials         # Income statement (kolumner = datum)
        bs   = ticker_obj.balance_sheet      # Balance sheet
        cf   = ticker_obj.cashflow           # Cash flow statement

        if fin is None or fin.empty:
            return result

        cols = list(fin.columns)
        if len(cols) < 2:
            return result

        # t = senaste år, t1 = föregående år
        t, t1 = cols[0], cols[1]

        def _row(df, *names):
            for n in names:
                if n in df.index:
                    return df.loc[n, t], df.loc[n, t1]
            return None, None

        rev_t,  rev_t1  = _row(fin, "Total Revenue", "Revenue")
        cogs_t, cogs_t1 = _row(fin, "Cost Of Revenue", "Cost of Goods Sold")
        sga_t,  sga_t1  = _row(fin, "Selling General Administrative", "SGA")
        ni_t,   _       = _row(fin, "Net Income", "Net Income Common Stockholders")

        if bs is not None and not bs.empty:
            rec_t,  rec_t1  = _row(bs, "Net Receivables", "Accounts Receivable")
            ast_t,  ast_t1  = _row(bs, "Total Assets")
            ppe_t,  ppe_t1  = _row(bs, "Net PPE", "Property Plant Equipment Net")
            dep_t,  dep_t1  = _row(bs, "Accumulated Depreciation",
                                   "Accumulated Depreciation Amortization Depletion")
            ltd_t,  ltd_t1  = _row(bs, "Long Term Debt", "Long-Term Debt")
            cl_t,   cl_t1   = _row(bs, "Current Liabilities", "Total Current Liabilities")

            result.update({
                "receivables_t": _safe(rec_t),   "receivables_t1": _safe(rec_t1),
                "assets_t":      _safe(ast_t),   "assets_t1":      _safe(ast_t1),
                "ppe_t":         _safe(ppe_t),   "ppe_t1":         _safe(ppe_t1),
                "depreciation_t": _safe(dep_t),  "depreciation_t1": _safe(dep_t1),
                "total_debt_t":  _safe(ltd_t),   "total_debt_t1":  _safe(ltd_t1),
                "current_liabilities_t": _safe(cl_t), "current_liabilities_t1": _safe(cl_t1),
            })

        if cf is not None and not cf.empty:
            ocf_t, _ = _row(cf, "Operating Cash Flow", "Cash From Operations",
                            "Total Cash From Operating Activities")
            result["operating_cashflow_t"] = _safe(ocf_t)

        result.update({
            "revenue_t":   _safe(rev_t),  "revenue_t1":  _safe(rev_t1),
            "cogs_t":      _safe(cogs_t), "cogs_t1":     _safe(cogs_t1),
            "sga_t":       _safe(sga_t),  "sga_t1":      _safe(sga_t1),
            "net_income_t": _safe(ni_t),
        })

    except Exception as e:
        logger.debug(f"  extract_financials_for_mscore fel: {e}")

    return result


def _safe(val):
    """Konverterar pandas-värde till float eller None."""
    if val is None:
        return None
    try:
        f = float(val)
        return f if (f == f and abs(f) < 1e18) else None
    except (ValueError, TypeError):
        return None


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 4 — DILUTION CHECK
# ══════════════════════════════════════════════════════════════════════════════

def check_dilution(info: dict, universe_type: str = "universe") -> tuple[float, str]:
    """
    Kontrollerar aktie-utspädning (nya aktier utgivna under senaste år).

    Returns:
        (dilution_pct, flag_str)
        dilution_pct: 0.0 om ingen data; positiv = utspädning
    """
    shares_now  = _float(info, "sharesOutstanding")
    shares_prev = _float(info, "floatShares")  # Approximation

    # Alternativ: hämta från share_history om tillgänglig
    shares_growth = _float(info, "sharesPercentSharesOut")

    if shares_growth is not None:
        dil = abs(shares_growth) * 100 if abs(shares_growth) < 2 else abs(shares_growth)
        threshold = 15.0 if universe_type == "universe" else 20.0
        if dil > 30:
            return dil, f"Extrem utspädning {dil:.1f}% — EXKLUDERA"
        elif dil > threshold:
            return dil, f"Hög utspädning {dil:.1f}% (threshold={threshold}%)"
        return dil, ""

    return 0.0, ""


# ══════════════════════════════════════════════════════════════════════════════
# KOMBINERAD UTVÄRDERING
# ══════════════════════════════════════════════════════════════════════════════

def evaluate_candidate(
    info: dict,
    ticker: str = "",
    universe_type: str = "universe",
    financials: Optional[dict] = None,
) -> dict:
    """
    Kör alla lager och returnerar en komplett utvärdering.

    Returns dict med:
        excluded:      bool — ska exkluderas (Layer 1 misslyckades)
        exclude_reason: str
        quality_score: float 0–100
        quality_flags: list[str]
        quality_tier:  "HIGH" | "MEDIUM" | "SPECULATIVE"
        m_score:       float | None
        m_score_text:  str
        dilution_pct:  float
        dilution_flag: str
        fraud_flags:   list[str]   — sammanfattning av alla fraud-indikationer
        confidence_delta: float    — bidrag till kandidatens confidence (positiv/negativ)
    """
    # Layer 1
    excl, excl_reason = hard_exclude(info, ticker, universe_type)

    # Layer 2
    q_score, q_flags = compute_quality_score(info, ticker, universe_type)

    # Layer 3 — M-Score (kräver separat finansiell data)
    m_score, m_text = (None, "Ej beräknad") if financials is None else \
                       compute_beneish_mscore(financials)

    # Layer 4 — Dilution
    dil_pct, dil_flag = check_dilution(info, universe_type)

    # Sänk quality_score för fraud-signaler
    fraud_flags: list[str] = []
    conf_delta = 0.0

    if m_score is not None:
        if m_score > -1.00:
            q_score = max(0, q_score - 30)
            fraud_flags.append(f"M-score={m_score:.2f} (trolig manipulation)")
            conf_delta -= 0.35
            # Trolig manipulation → exkludera direkt
            excl = True
            excl_reason = f"M-score={m_score:.2f} > -1.00 (trolig resultatmanipulation)"
        elif m_score > -1.78:
            q_score = max(0, q_score - 15)
            fraud_flags.append(f"M-score={m_score:.2f} (möjlig manipulation)")
            conf_delta -= 0.20

    if dil_pct > 30:
        q_score = max(0, q_score - 25)
        fraud_flags.append(dil_flag)
        conf_delta -= 0.20
        # Extrem utspädning → exkludera
        if not excl:
            excl = True
            excl_reason = f"Extrem utspädning {dil_pct:.1f}% > 30%"
    elif dil_pct > 15:
        q_score = max(0, q_score - 12)
        if dil_flag:
            fraud_flags.append(dil_flag)
        conf_delta -= 0.10

    # Quality Tier
    if q_score >= 65 and not fraud_flags:
        tier = "HIGH"
        conf_delta += 0.15
    elif q_score >= 40:
        tier = "MEDIUM"
    else:
        tier = "SPECULATIVE"
        conf_delta -= 0.20

    return {
        "excluded":       excl,
        "exclude_reason": excl_reason,
        "quality_score":  round(q_score, 1),
        "quality_flags":  q_flags,
        "quality_tier":   tier,
        "m_score":        m_score,
        "m_score_text":   m_text,
        "dilution_pct":   round(dil_pct, 1),
        "dilution_flag":  dil_flag,
        "fraud_flags":    fraud_flags,
        "confidence_delta": round(conf_delta, 3),
    }
