"""
report.py – Markdown-rapportbyggare för svenska småbolag.

Genererar en strukturerad rapport med:
  1. Exekutiv sammanfattning  – snabb blick på marknadsläge
  2. Topp-5 Spotlight         – de fem starkaste kandidaterna med pris & trend
  3. Poängtabell (Top-N)      – rankad lista med marknadsdatakolumner
  4. Faktortabell             – detaljerade delpoäng per faktor
  5. Tematiska sektioner      – Bästa värdering · Starkast tillväxt · Högst momentum
  6. Djupdyk (Top-5)          – utförliga profiler per bolag
  7. Sektoröversikt           – genomsnittlig poäng per sektor
  8. Röda flaggor             – bolag med varningssignaler
  9. Insideraktivitet         – sammanfattning av insiderköp/-sälj
  10. Metodförklaring         – kort om hur scoringen fungerar

Används av scanner.py via build_report().
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

from .scoring import _stars
from .universe import SECTOR_GROUPS

# ── Konstanter ────────────────────────────────────────────────────────────────
_RANK_MEDALS     = ["🥇", "🥈", "🥉", "4.", "5."]


def _fmt_pct(v, decimals: int = 1) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "—"
    return f"{v*100:+.{decimals}f}%"


def _fmt_val(v, fmt: str = ".1f", fallback: str = "—") -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return fallback
    return format(v, fmt)


def _fmt_price(v) -> str:
    """Formaterar pris med lämpligt antal decimaler."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "—"
    if v >= 100:
        return f"{v:.0f}"
    if v >= 10:
        return f"{v:.1f}"
    return f"{v:.2f}"


def _fmt_mkcap(v_sek: float) -> str:
    if np.isnan(v_sek):
        return "—"
    if v_sek >= 1e9:
        return f"{v_sek/1e9:.1f} Gsek"
    return f"{v_sek/1e6:.0f} Msek"


def _pct_arrow(v) -> str:
    """Lägger till ↑/↓ pil på en procentförändring."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "—"
    symbol = "↑" if v > 0 else ("↓" if v < 0 else "")
    return f"{symbol}{abs(v)*100:.1f}%"


# ── Sektortillhörighet ────────────────────────────────────────────────────────

def _sector_for(ticker: str) -> str:
    t = ticker.upper()
    for sector, tickers in SECTOR_GROUPS.items():
        if t in [x.upper() for x in tickers]:
            return sector
    return "Övrigt"


# ══════════════════════════════════════════════════════════════════════════════
# AVSNITT 1 – EXEKUTIV SAMMANFATTNING
# ══════════════════════════════════════════════════════════════════════════════

def _section_summary(scored: pd.DataFrame, n_before: int) -> str:
    n_after  = len(scored)
    n_fil    = n_before - n_after
    date_str = datetime.today().strftime("%d %b %Y")

    five_star = (scored["sc_stars"] == "★★★★★").sum()
    four_star = (scored["sc_stars"] == "★★★★").sum()
    avg_score = scored["sc_total"].mean()
    top1      = scored.iloc[0] if n_after > 0 else None

    lines = [
        f"# 🏆 Svenska Småbolag – Rapport {date_str}",
        "",
        "## Sammanfattning",
        "",
        f"| | |",
        f"|---|---|",
        f"| Analyserade bolag | {n_before} |",
        f"| Filterbortfall    | {n_fil} ({n_fil/n_before*100:.0f}%) |",
        f"| Kvar efter filter | **{n_after}** |",
        f"| Snittpoäng (kvar) | {avg_score:.1f}/100 |",
        f"| ★★★★★ bolag      | {five_star} |",
        f"| ★★★★ bolag       | {four_star} |",
        "",
    ]

    if top1 is not None:
        sector  = _sector_for(top1["ticker"])
        price   = _fmt_price(top1.get("current_price", float("nan")))
        day_chg = _pct_arrow(top1.get("day_change_pct", float("nan")))
        lines += [
            f"### 🥇 Toppbolag: {top1['ticker']}",
            f"**{top1.get('sc_stars','?')}  {top1['sc_total']:.1f}/100 poäng**  "
            f"|  Sektor: {sector}  |  Pris: {price}  |  Dag: {day_chg}",
            "",
        ]

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# AVSNITT 2 – TOPP-5 SPOTLIGHT
# ══════════════════════════════════════════════════════════════════════════════

def _section_top5(scored: pd.DataFrame, prev_scores: dict) -> str:
    """Kompakt topp-5-tabell med pris, dag%, vecka%, sektor och trendpil."""
    from .history import arrow as trend_arrow

    top = scored.head(5)
    lines = [
        "## 🎯 Topp 5 – Starkaste Kandidaterna",
        "",
        "| # | Ticker | ⭐ | Poäng | Trend | Sektor | Pris | Dag | Vecka |",
        "|---|--------|-----|------:|:-----:|--------|-----:|----:|------:|",
    ]

    for i, (_, r) in enumerate(top.iterrows()):
        medal   = _RANK_MEDALS[i]
        ticker  = r.get("ticker", "?")
        stars   = r.get("sc_stars", "?")
        total   = r.get("sc_total", float("nan"))
        trend   = trend_arrow(ticker, float(total), prev_scores)
        sector  = _sector_for(ticker)
        price   = _fmt_price(r.get("current_price", float("nan")))
        day     = _pct_arrow(r.get("day_change_pct", float("nan")))
        week    = _pct_arrow(r.get("week_change_pct", float("nan")))
        lines.append(
            f"| {medal} | **{ticker}** | {stars} | **{total:.1f}** | {trend} "
            f"| {sector} | {price} | {day} | {week} |"
        )

    return "\n".join(lines) + "\n"


# ══════════════════════════════════════════════════════════════════════════════
# AVSNITT 3 – POÄNGTABELL (rankningslista)
# ══════════════════════════════════════════════════════════════════════════════

def _section_score_table(scored: pd.DataFrame, top_n: int, prev_scores: dict) -> str:
    """Rankingstabell med marknadsdatakolumner + trendpil."""
    from .history import arrow as trend_arrow

    top = scored.head(top_n)

    header = "| Rank | Ticker | ⭐ | Poäng | Trend | Sektor | Pris | Dag% | Vecka% |"
    sep    = "|---:|:-------|-----|------:|:-----:|--------|-----:|----:|------:|"

    rows = [f"## Top-{top_n} Rankinglista\n", header, sep]

    for rank, (_, r) in enumerate(top.iterrows(), 1):
        ticker  = r.get("ticker", "?")
        stars   = r.get("sc_stars", "?")
        total   = r.get("sc_total", float("nan"))
        trend   = trend_arrow(ticker, float(total), prev_scores)
        sector  = _sector_for(ticker)
        price   = _fmt_price(r.get("current_price", float("nan")))
        day     = _pct_arrow(r.get("day_change_pct", float("nan")))
        week    = _pct_arrow(r.get("week_change_pct", float("nan")))
        rows.append(
            f"| {rank} | {ticker} | {stars} | **{total:.1f}** | {trend} "
            f"| {sector} | {price} | {day} | {week} |"
        )

    return "\n".join(rows) + "\n"


def _section_factor_table(scored: pd.DataFrame, top_n: int) -> str:
    """Detaljerad faktortabell (delpoäng) för topp-N."""
    factor_cols = [
        ("sc_insider",   "Insider"),
        ("sc_fcf",       "FCF"),
        ("sc_piotroski", "Piotroski"),
        ("sc_growth",    "Tillväxt"),
        ("sc_balance",   "Balans"),
        ("sc_valuation", "Värdering"),
        ("sc_momentum",  "Momentum"),
    ]

    top    = scored.head(top_n)
    header = "| Ticker | " + " | ".join(c[1] for c in factor_cols) + " |"
    sep    = "|:-------|" + "".join("---:|" for _ in factor_cols)

    rows = ["## Faktortabell (delpoäng 0–100)\n", header, sep]

    for _, r in top.iterrows():
        ticker = r.get("ticker", "?")
        cells  = [ticker]
        for col, _ in factor_cols:
            v = r.get(col, float("nan"))
            try:
                cells.append(f"{float(v):.0f}")
            except (ValueError, TypeError):
                cells.append("—")
        rows.append("| " + " | ".join(cells) + " |")

    return "\n".join(rows) + "\n"


# ══════════════════════════════════════════════════════════════════════════════
# AVSNITT 4 – TEMATISKA SEKTIONER
# ══════════════════════════════════════════════════════════════════════════════

def _thematic_block(
    scored: pd.DataFrame,
    sort_col: str,
    title: str,
    extra_cols: list[tuple[str, str]],
    top_n: int = 5,
) -> str:
    """Generisk tematisk sektion – sorterar på sort_col och visar top_n."""
    sub = scored.dropna(subset=[sort_col]).sort_values(sort_col, ascending=False).head(top_n)
    if sub.empty:
        return ""

    base_cols  = [("ticker", "Ticker"), ("sc_stars", "⭐"), ("sc_total", "Poäng")]
    all_cols   = base_cols + extra_cols

    header = "| " + " | ".join(c[1] for c in all_cols) + " |"
    sep    = "|:-------|" + "".join("---:|" for _ in all_cols[1:])

    rows = [f"### {title}\n", header, sep]
    for _, r in sub.iterrows():
        cells = []
        for col, _ in all_cols:
            v = r.get(col, "—")
            if col == "ticker":
                cells.append(f"**{v}**")
            elif col == "sc_stars":
                cells.append(str(v))
            elif col == "sc_total":
                cells.append(f"{float(v):.1f}" if v != "—" else "—")
            elif col in ("revenue_growth", "earnings_growth",
                         "day_change_pct", "week_change_pct", "return_12m", "return_6m"):
                cells.append(_fmt_pct(v if v != "—" else float("nan")))
            elif col == "sector":
                cells.append(_sector_for(r.get("ticker", "")))
            else:
                try:
                    cells.append(f"{float(v):.1f}")
                except (ValueError, TypeError):
                    cells.append(str(v) if v not in (None, "—") else "—")
        rows.append("| " + " | ".join(cells) + " |")

    return "\n".join(rows) + "\n"


def _section_thematic(scored: pd.DataFrame) -> str:
    lines = ["## 💡 Tematiska Topp-listor\n"]

    # Bästa värdering
    lines.append(_thematic_block(
        scored, "sc_valuation",
        "💰 Bästa Värdering (EV/EBITDA · P/B)",
        [("sc_valuation", "Värdering"), ("ev_to_ebitda", "EV/EBITDA"), ("price_to_book", "P/B")],
    ))

    # Starkast tillväxt
    lines.append(_thematic_block(
        scored, "sc_growth",
        "📈 Starkast Tillväxt",
        [("sc_growth", "Tillväxt"), ("revenue_growth", "Omsättn."), ("earnings_growth", "Vinst")],
    ))

    # Högst momentum
    lines.append(_thematic_block(
        scored, "sc_momentum",
        "🚀 Högst Momentum",
        [("sc_momentum", "Momentum"), ("return_12m", "12m"), ("return_6m", "6m"),
         ("week_change_pct", "Vecka")],
    ))

    # Starkast FCF-yield
    lines.append(_thematic_block(
        scored, "sc_fcf",
        "💵 Starkast FCF-yield",
        [("sc_fcf", "FCF-poäng"), ("gross_margin", "Bruttomarg."), ("sc_balance", "Balans")],
    ))

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# AVSNITT 5 – DJUPDYK (topp-N profiler)
# ══════════════════════════════════════════════════════════════════════════════

def _company_profile(row: pd.Series, prev_scores: dict, news: list = None) -> str:
    from .history import arrow as trend_arrow, delta_str

    t      = row.get("ticker", "?")
    stars  = row.get("sc_stars", "?")
    total  = row.get("sc_total", float("nan"))
    sector = _sector_for(t)
    trend  = trend_arrow(t, float(total), prev_scores)
    delta  = delta_str(t, float(total), prev_scores)

    # Marknadsdata
    price    = _fmt_price(row.get("current_price", float("nan")))
    day_chg  = _pct_arrow(row.get("day_change_pct", float("nan")))
    week_chg = _pct_arrow(row.get("week_change_pct", float("nan")))

    # Nyckeltal
    insider_pct = row.get("insider_pct", float("nan"))
    fcf         = row.get("free_cash_flow", float("nan"))
    mkcap       = row.get("market_cap", float("nan"))
    de          = row.get("debt_to_equity", float("nan"))
    cr          = row.get("current_ratio", float("nan"))
    rev_g       = row.get("revenue_growth", float("nan"))
    piotroski   = row.get("piotroski_score", float("nan"))
    ev_eb       = row.get("ev_to_ebitda", float("nan"))
    r12         = row.get("return_12m", float("nan"))
    r6          = row.get("return_6m", float("nan"))
    signal      = row.get("insider_signal", "N/A")

    # Marknadsvärde i SEK
    SEK_USD   = 0.094
    mkcap_sek = mkcap / SEK_USD if not np.isnan(mkcap) and mkcap > 0 else float("nan")

    # FCF-yield
    fcf_yield = float("nan")
    if not np.isnan(fcf) and not np.isnan(mkcap) and mkcap > 0:
        fcf_yield = fcf / mkcap

    lines = [
        f"### {stars} {t} — {total:.1f} poäng  {trend} ({delta}p)",
        f"**Sektor:** {sector}",
        "",
        "| Nyckeltal | Värde |",
        "|---|---|",
        f"| Marknadsvärde | {_fmt_mkcap(mkcap_sek)} |",
        f"| Pris (senast) | {price} |",
        f"| Förändring dag / vecka | {day_chg} / {week_chg} |",
        f"| Avkastning 6m / 12m   | {_fmt_pct(r6)} / {_fmt_pct(r12)} |",
        f"| Insiderägarandel | {_fmt_pct(insider_pct, 1) if not np.isnan(insider_pct) else '—'} |",
        f"| Insideraktivitet | {signal} |",
        f"| FCF-yield | {_fmt_pct(fcf_yield)} |",
        f"| Piotroski F-Score | {_fmt_val(piotroski, '.0f')}/9 |",
        f"| Omsättningstillväxt | {_fmt_pct(rev_g)} |",
        f"| Skuldsättning D/E | {_fmt_val(de, '.0f')}% |",
        f"| Current Ratio | {_fmt_val(cr)} |",
        f"| EV/EBITDA | {_fmt_val(ev_eb)} |",
        "",
    ]

    # Poängdetaljer
    score_cols = [
        ("sc_insider",   "Insider"),
        ("sc_fcf",       "FCF"),
        ("sc_piotroski", "Piotroski"),
        ("sc_growth",    "Tillväxt"),
        ("sc_balance",   "Balans"),
        ("sc_valuation", "Värdering"),
        ("sc_momentum",  "Momentum"),
        ("sc_liquidity", "Likviditet"),
    ]
    parts = []
    for col, label in score_cols:
        v = row.get(col, float("nan"))
        try:
            parts.append(f"{label}: {float(v):.0f}")
        except (ValueError, TypeError):
            pass
    if parts:
        lines.append(f"**Poängfördelning:** {' · '.join(parts)}")
        lines.append("")

    # Nyheter (Google News RSS om tillgängliga)
    if news:
        lines.append("**Senaste nyheter:**")
        for a in news[:3]:
            age_h = a.get("age_hours", 999)
            icon  = "🔴" if age_h < 6 else "🟡" if age_h < 24 else "⚪"
            url   = a.get("url", "")
            title = f"[{a['headline']}]({url})" if url else a["headline"]
            src   = a.get("source", "")
            dt_s  = a.get("datetime_str", "—")
            meta  = f"_{src} · {dt_s}_" if src else f"_{dt_s}_"
            lines.append(f"{icon} {title}  \n   {meta}")
        lines.append("")

    return "\n".join(lines)


def _section_profiles(
    scored:       pd.DataFrame,
    top_n:        int,
    prev_scores:  dict,
    company_news: dict = None,
) -> str:
    top          = scored.head(top_n)
    company_news = company_news or {}
    parts        = [f"## Djupdyk – Top {top_n}\n"]
    for _, row in top.iterrows():
        ticker = row.get("ticker", "")
        news   = company_news.get(ticker, [])
        parts.append(_company_profile(row, prev_scores, news=news))
        parts.append("---\n")
    return "\n".join(parts)


# ══════════════════════════════════════════════════════════════════════════════
# AVSNITT 6 – SEKTORÖVERSIKT
# ══════════════════════════════════════════════════════════════════════════════

def _section_sectors(scored: pd.DataFrame) -> str:
    scored = scored.copy()
    scored["sector"] = scored["ticker"].apply(_sector_for)

    agg = (scored.groupby("sector")["sc_total"]
           .agg(["mean", "count"])
           .rename(columns={"mean": "Snittpoäng", "count": "Antal"})
           .sort_values("Snittpoäng", ascending=False))

    lines = ["## Sektoröversikt\n", "| Sektor | Bolag | Snittpoäng |",
             "|---|---:|---:|"]
    for sector, r in agg.iterrows():
        stars = _stars(r["Snittpoäng"])
        lines.append(f"| {sector} | {int(r['Antal'])} | {stars} {r['Snittpoäng']:.1f} |")

    return "\n".join(lines) + "\n"


# ══════════════════════════════════════════════════════════════════════════════
# AVSNITT 7 – RÖDA FLAGGOR
# ══════════════════════════════════════════════════════════════════════════════

def _section_red_flags(scored: pd.DataFrame) -> str:
    from .filters import get_red_flags
    flags_df = get_red_flags(scored)
    flags_df = flags_df[flags_df["n_flags"] > 0].head(15)

    if flags_df.empty:
        return "## ⚠️ Röda Flaggor\n\n_Inga varningssignaler bland rankade bolag._\n"

    lines = ["## ⚠️ Röda Flaggor\n",
             "Dessa bolag passerade de hårda filtren men har ändå varningssignaler:\n",
             "| Ticker | Flaggor |",
             "|---|---|"]
    for _, r in flags_df.iterrows():
        lines.append(f"| **{r['ticker']}** | {r['flags']} |")

    return "\n".join(lines) + "\n"


# ══════════════════════════════════════════════════════════════════════════════
# AVSNITT 8 – INSIDERAKTIVITET
# ══════════════════════════════════════════════════════════════════════════════

def _section_insider_activity(scored: pd.DataFrame) -> str:
    from .insider import get_insider_summary
    summary = get_insider_summary(scored, top_n=5)
    return f"## 🕵️ Insideraktivitet (senaste 6m)\n\n{summary}\n"


# ══════════════════════════════════════════════════════════════════════════════
# AVSNITT 9 – METOD
# ══════════════════════════════════════════════════════════════════════════════

_METHOD_TEXT = """## ℹ️ Metodik

**Scoringmodell – 8 faktorer (100p totalt):**

| Faktor | Vikt | Beskrivning |
|---|---:|---|
| Insiderägande | 18% | Ägarandel + nettotransaktioner 6m |
| FCF-yield | 16% | Fritt kassaflöde / marknadsvärde |
| Piotroski F-Score | 15% | 9-punkts finansiell hälsoscore (proxy om fullständig data saknas) |
| Tillväxt | 13% | Omsättningstillväxt (60%) + vinsttillväxt (40%) |
| Balansräkning | 12% | D/E inverterat (55%) + current ratio (45%) |
| Värdering | 12% | EV/EBITDA inverterat (primärt), P/B fallback |
| Momentum | 9% | 12m-avkastning (65%) + 6m-avkastning (35%) |
| Likviditet | 5% | Daglig omsättning i SEK |

**Bonusar:** +5p nettokassa · +3p grundarstyrt (>20% insider) · +3p bruttomarginal >40%

**Avdrag:** −10p utspädning >10% · −5p Piotroski <3 · −3p D/E >200%

**Hårda filter (eliminerar):** illikviditet <500k SEK/dag · market cap utanför 30M–25G SEK ·
negativt eget kapital · current ratio <0.5 · D/E >300% · Piotroski ≤2 · utspädning >30%

**Trendindikatorer:** ▲ poäng ökat >2p · ▼ minskat >2p · → stabilt · • ny ticker

_Data från Yahoo Finance (yfinance). Rapporten är inte finansiell rådgivning._
"""


# ══════════════════════════════════════════════════════════════════════════════
# HUVUD-FUNKTION
# ══════════════════════════════════════════════════════════════════════════════

def _section_nasdaq_nordic(nasdaq_news: list) -> str:
    """Nasdaq Nordic regulatoriska nyheter – wrapper mot news_fetcher."""
    if not nasdaq_news:
        return ""
    try:
        import sys
        from pathlib import Path
        _root = Path(__file__).parent.parent
        if str(_root) not in sys.path:
            sys.path.insert(0, str(_root))
        import news_fetcher as _nf
        return _nf.format_nasdaq_nordic_section_md(nasdaq_news, max_items=8)
    except Exception:
        return ""


def build_report(
    scored:       pd.DataFrame,
    n_universe:   int,
    top_n:        int                       = 20,
    profiles_n:   int                       = 5,
    insider_df:   Optional[pd.DataFrame]    = None,
    prev_scores:  Optional[dict]            = None,
    company_news: Optional[dict]            = None,
    nasdaq_news:  Optional[list]            = None,
) -> str:
    """
    Bygger en fullständig Markdown-rapport.

    Args:
        scored:      DataFrame från scoring.score_universe() + merge_insider_data()
        n_universe:  Antal tickers INNAN filtrering
        top_n:       Antal bolag i rankingtabellen
        profiles_n:  Antal bolag med djupdyk-profil
        insider_df:  Råinsiderdata (oanvänt direkt; scored ska ha merged kolumner)
        prev_scores: Dict {ticker: score} från föregående körning (trend-pilar)

    Returns:
        Markdown-sträng redo att sparas som .md eller skickas i e-post.
    """
    if prev_scores  is None: prev_scores  = {}
    if company_news is None: company_news = {}
    if nasdaq_news  is None: nasdaq_news  = []

    if scored.empty:
        return (
            f"# 🏆 Svenska Småbolag – Rapport {datetime.today().strftime('%d %b %Y')}\n\n"
            "_Inga bolag passerade filtren. Kontrollera data-hämtningen._\n"
        )

    parts = [
        _section_summary(scored, n_universe),
        _section_top5(scored, prev_scores),
        _section_score_table(scored, top_n=top_n, prev_scores=prev_scores),
        _section_factor_table(scored, top_n=top_n),
        _section_thematic(scored),
        _section_profiles(scored, top_n=profiles_n, prev_scores=prev_scores,
                          company_news=company_news),
        _section_sectors(scored),
        _section_red_flags(scored),
        _section_insider_activity(scored),
    ]

    # Nasdaq Nordic (om nyheter finns)
    nasdaq_md = _section_nasdaq_nordic(nasdaq_news)
    if nasdaq_md:
        parts.append(nasdaq_md)

    parts.append(_METHOD_TEXT)

    return "\n\n".join(parts)


def save_report(report: str, output_dir: str = ".") -> str:
    """Sparar rapporten till fil och returnerar sökvägen."""
    from pathlib import Path
    date_str = datetime.today().strftime("%Y-%m-%d")
    path = Path(output_dir) / f"smallcap_report_{date_str}.md"
    path.write_text(report, encoding="utf-8")
    return str(path)
