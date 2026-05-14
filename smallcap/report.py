"""
report.py – Markdown-rapportbyggare för svenska småbolag.

Genererar en strukturerad rapport med:
  1. Exekutiv sammanfattning  – snabb blick på marknadsläge och topplistor
  2. Poängtabell (Top-N)      – rankad lista med nyckeltal
  3. Djupdyk (Top-5)          – utförliga profiler per bolag
  4. Sektoröversikt           – genomsnittlig poäng per sektor
  5. Röda flaggor             – bolag som passerat men ändå har varningssignaler
  6. Insideraktivitet         – sammanfattning av insiderköp/-sälj
  7. Metodförklaring          – kort om hur scoringen fungerar

Används av scanner.py via build_report().
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

from .universe import SECTOR_GROUPS

# ── Konstanter ────────────────────────────────────────────────────────────────
_STAR_THRESHOLDS = [(80, "★★★★★"), (65, "★★★★"), (50, "★★★"), (35, "★★"), (0, "★")]


def _stars(score: float) -> str:
    for threshold, label in _STAR_THRESHOLDS:
        if score > threshold:
            return label
    return "★"


def _fmt_pct(v, decimals: int = 1) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "—"
    return f"{v*100:+.{decimals}f}%"


def _fmt_val(v, fmt: str = ".1f", fallback: str = "—") -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return fallback
    return format(v, fmt)


def _fmt_mkcap(v_sek: float) -> str:
    if np.isnan(v_sek):
        return "—"
    if v_sek >= 1e9:
        return f"{v_sek/1e9:.1f} Gsek"
    return f"{v_sek/1e6:.0f} Msek"


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
        f"| Filterbortfall    | {n_fil} ({n_fil/n_before*100:.0f}% om {n_before}>0) |",
        f"| Kvar efter filter | **{n_after}** |",
        f"| Snittpoäng (kvar) | {avg_score:.1f}/100 |",
        f"| ★★★★★ bolag      | {five_star} |",
        f"| ★★★★ bolag       | {four_star} |",
        "",
    ]

    if top1 is not None:
        lines += [
            f"### 🥇 Toppbolag: {top1['ticker']}",
            f"**{top1.get('sc_stars','?')}  {top1['sc_total']:.1f}/100 poäng**  |  "
            f"Sektor: {_sector_for(top1['ticker'])}",
            "",
        ]

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# AVSNITT 2 – POÄNGTABELL
# ══════════════════════════════════════════════════════════════════════════════

def _section_score_table(scored: pd.DataFrame, top_n: int = 20) -> str:
    cols = [
        ("ticker",        "Ticker"),
        ("sc_stars",      "⭐"),
        ("sc_total",      "Poäng"),
        ("sc_insider",    "Insider"),
        ("sc_fcf",        "FCF"),
        ("sc_piotroski",  "Piotroski"),
        ("sc_growth",     "Tillväxt"),
        ("sc_balance",    "Balans"),
        ("sc_valuation",  "Värdering"),
        ("sc_momentum",   "Momentum"),
    ]

    top = scored.head(top_n)

    header = "| " + " | ".join(c[1] for c in cols) + " |"
    sep    = "| " + " | ".join(":---" if i == 0 else "---:" for i, _ in enumerate(cols)) + " |"

    rows = [header, sep]
    for _, r in top.iterrows():
        cells = []
        for col, _ in cols:
            v = r.get(col, "—")
            if col == "sc_total":
                cells.append(f"**{v:.1f}**")
            elif col in ("sc_stars", "ticker"):
                cells.append(str(v))
            else:
                try:
                    cells.append(f"{float(v):.0f}")
                except (ValueError, TypeError):
                    cells.append(str(v) if v is not None else "—")
        rows.append("| " + " | ".join(cells) + " |")

    return f"## Top-{top_n} Rankinglista\n\n" + "\n".join(rows) + "\n"


# ══════════════════════════════════════════════════════════════════════════════
# AVSNITT 3 – DJUPDYK (topp-N profiler)
# ══════════════════════════════════════════════════════════════════════════════

def _company_profile(row: pd.Series) -> str:
    t      = row.get("ticker", "?")
    stars  = row.get("sc_stars", "?")
    total  = row.get("sc_total", float("nan"))
    sector = _sector_for(t)

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

    # Marknadsvärde i SEK (yfinance returnerar USD, grov approximation)
    SEK_USD = 0.094
    mkcap_sek = mkcap / SEK_USD if not np.isnan(mkcap) and mkcap > 0 else float("nan")

    lines = [
        f"### {stars} {t} — {total:.1f} poäng",
        f"**Sektor:** {sector}",
        "",
        "| Nyckeltal | Värde |",
        "|---|---|",
        f"| Marknadsvärde | {_fmt_mkcap(mkcap_sek)} |",
        f"| Insiderägarandel | {_fmt_pct(insider_pct,1) if not np.isnan(insider_pct) else '—'} |",
        f"| Insider­aktivitet | {signal} |",
        f"| FCF-yield | {_fmt_pct(fcf/mkcap if not np.isnan(fcf) and not np.isnan(mkcap) and mkcap>0 else float('nan'))} |",
        f"| Piotroski F-Score | {_fmt_val(piotroski, '.0f')}/9 |",
        f"| Omsättningstillväxt | {_fmt_pct(rev_g)} |",
        f"| Skuldsättning D/E | {_fmt_val(de, '.0f')}% |",
        f"| Current Ratio | {_fmt_val(cr)} |",
        f"| EV/EBITDA | {_fmt_val(ev_eb)} |",
        f"| Avkastning 6m | {_fmt_pct(r6)} |",
        f"| Avkastning 12m | {_fmt_pct(r12)} |",
        "",
    ]

    # Poäng­detaljer
    score_cols = [
        ("sc_insider",   "Insider"),
        ("sc_fcf",       "FCF-yield"),
        ("sc_piotroski", "Piotroski"),
        ("sc_growth",    "Tillväxt"),
        ("sc_balance",   "Balans"),
        ("sc_valuation", "Värdering"),
        ("sc_momentum",  "Momentum"),
        ("sc_liquidity", "Likviditet"),
    ]
    score_parts = []
    for col, label in score_cols:
        v = row.get(col, float("nan"))
        try:
            score_parts.append(f"{label}: {float(v):.0f}")
        except (ValueError, TypeError):
            pass
    if score_parts:
        lines.append(f"**Poängfördelning:** {' · '.join(score_parts)}")
        lines.append("")

    return "\n".join(lines)


def _section_profiles(scored: pd.DataFrame, top_n: int = 5) -> str:
    top = scored.head(top_n)
    parts = [f"## Djupdyk – Top {top_n}\n"]
    for _, row in top.iterrows():
        parts.append(_company_profile(row))
        parts.append("---\n")
    return "\n".join(parts)


# ══════════════════════════════════════════════════════════════════════════════
# AVSNITT 4 – SEKTORÖVERSIKT
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
# AVSNITT 5 – RÖDA FLAGGOR
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
# AVSNITT 6 – INSIDERAKTIVITET
# ══════════════════════════════════════════════════════════════════════════════

def _section_insider_activity(scored: pd.DataFrame) -> str:
    from .insider import get_insider_summary
    summary = get_insider_summary(scored, top_n=5)
    return f"## 🕵️ Insideraktivitet (senaste 6m)\n\n{summary}\n"


# ══════════════════════════════════════════════════════════════════════════════
# AVSNITT 7 – METOD
# ══════════════════════════════════════════════════════════════════════════════

_METHOD_TEXT = """## ℹ️ Metodik

**Scoringmodell – 8 faktorer (100p totalt):**

| Faktor | Vikt | Beskrivning |
|---|---:|---|
| Insiderägande | 18% | Ägarandel + netto­transaktioner 6m |
| FCF-yield | 16% | Fritt kassaflöde / marknadsvärde |
| Piotroski F-Score | 15% | Akademisk 9-punkts finansiell hälsa |
| Tillväxt | 13% | Omsättningstillväxt (60%) + vinsttillväxt (40%) |
| Balansräkning | 12% | D/E inverterat (55%) + current ratio (45%) |
| Värdering | 12% | EV/EBITDA inverterat (primärt), P/B fallback |
| Momentum | 9% | 12m-avkastning (65%) + 6m-avkastning (35%) |
| Likviditet | 5% | Daglig omsättning i SEK |

**Bonusar:** +5p nettokassa · +3p grundarstyrt (>20% insider) · +3p bruttomarginal >40%

**Avdrag:** −10p utspädning >10% · −5p Piotroski <3 · −3p D/E >200%

**Hårda filter (eliminerar):** illikviditet <300k SEK/dag · market cap utanför 30M–10B SEK ·
negativt eget kapital · current ratio <0.4 · D/E >300% · Piotroski ≤2 · utspädning >30%

_Data från Yahoo Finance (yfinance). Rapporten är inte finansiell rådgivning._
"""


# ══════════════════════════════════════════════════════════════════════════════
# HUVUD-FUNKTION
# ══════════════════════════════════════════════════════════════════════════════

def build_report(
    scored: pd.DataFrame,
    n_universe: int,
    top_n: int = 20,
    profiles_n: int = 5,
    insider_df: Optional[pd.DataFrame] = None,
) -> str:
    """
    Bygger en fullständig Markdown-rapport.

    Args:
        scored:     DataFrame från scoring.score_universe() + merge_insider_data()
        n_universe: Antal tickers INNAN filtrering (för statistik)
        top_n:      Antal bolag i rankingtabellen
        profiles_n: Antal bolag med djupdyk-profil
        insider_df: Råinsiderdata (oanvänt direkt, men scored ska ha merged kolumner)

    Returns:
        Markdown-sträng redo att sparas som .md eller skickas i e-post.
    """
    if scored.empty:
        return (
            f"# 🏆 Svenska Småbolag – Rapport {datetime.today().strftime('%d %b %Y')}\n\n"
            "_Inga bolag passerade filtren. Kontrollera data-hämtningen._\n"
        )

    parts = [
        _section_summary(scored, n_universe),
        _section_score_table(scored, top_n=top_n),
        _section_profiles(scored, top_n=profiles_n),
        _section_sectors(scored),
        _section_red_flags(scored),
        _section_insider_activity(scored),
        _METHOD_TEXT,
    ]

    return "\n\n".join(parts)


def save_report(report: str, output_dir: str = ".") -> str:
    """Sparar rapporten till fil och returnerar sökvägen."""
    from pathlib import Path
    date_str = datetime.today().strftime("%Y-%m-%d")
    path = Path(output_dir) / f"smallcap_report_{date_str}.md"
    path.write_text(report, encoding="utf-8")
    return str(path)
