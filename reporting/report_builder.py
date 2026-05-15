"""
report_builder.py
=================
Bygger en snygg, läsbar rapport istället för den kladdiga markdown-tabellen.

Design-principer:
  - Executive summary FÖRST – vad ska du göra den här veckan?
  - Topp 10 med kontext, inte topp 50 med siffror
  - Portföljsektion är mer framträdande än universum-scanning
  - Varje sektion har ett tydligt syfte
  - Fungerar som markdown (för filen) och HTML (för email)

Rapport-struktur:
  1. 🌍 Marknadsläge           – TJUR/BJÖRN + benchmark 30s
  2. ⚡ Veckans åtgärdslista   – Exakt vad du behöver göra NU
  3. 💼 Din portfölj           – Alla innehav med signal + P&L
  4. 🏆 Topp 10 köpkandidater  – De 10 bästa just nu, med skäl
  5. 📈 Sektorer               – Vilka sektorer är starka?
  6. 🔄 Förändringar           – Vad har förändrats sedan sist?
  7. 📅 Kommande rapporter     – Earnings inom 30 dagar
  8. 📄 Paper trading          – Track record
  9. 🤖 Claude-prompt          – Redo att klistras in
"""

from datetime import datetime
from pathlib import Path
import pandas as pd


def _fmt_pct(x, plus=True):
    """Formaterar ett DECIMAL-värde (0.075) som procent (+7.5%)."""
    if x is None or (hasattr(x, '__float__') and pd.isna(float(x))): return "—"
    sign = "+" if (plus and float(x) >= 0) else ""
    return f"{sign}{float(x)*100:.1f}%"

def _fmt_pct_raw(x, plus=True):
    """Formaterar ett REDAN-PROCENT-värde (7.5) som procent (+7.5%).
    Används för benchmark-data från daily_scan som lagrar t.ex. 7.59 för 7.59%."""
    if x is None or (hasattr(x, '__float__') and pd.isna(float(x))): return "—"
    sign = "+" if (plus and float(x) >= 0) else ""
    return f"{sign}{float(x):.1f}%"

def _color_pct_raw(x):
    """Emoji baserat på ett redan-procent-värde (positivt/negativt)."""
    if x is None or (hasattr(x, '__float__') and pd.isna(float(x))): return "⚪"
    return "🟢" if float(x) >= 0 else "🔴"

def _fmt_score(x):
    if x is None or pd.isna(x): return "—"
    return f"{float(x):.0f}"

def _color_pct(x):
    """Returnerar emoji baserat på riktning."""
    if x is None or pd.isna(x): return "⚪"
    return "🟢" if float(x) >= 0 else "🔴"

def _entry_icon(signal):
    return {"STARK":"🟢","OK":"🔵","VÄNTA":"🟡","EJ AKTUELL":"🔴"}.get(str(signal),"—")

def _rec_icon(rec):
    r = str(rec).upper()
    if "KÖP MER" in r: return "🟢"
    if "KÖP" in r: return "🟢"
    if "BEHÅLL" in r: return "🔵"
    if "SÄLJ" in r: return "🔴"
    if "MINSKA" in r: return "🟡"
    if "BEVAKA" in r: return "🟡"
    return "⚪"


# ══════════════════════════════════════════════════════════════
# SEKTION 1: MARKNADSLÄGE
# ══════════════════════════════════════════════════════════════

def section_regime(regime_info: dict, benchmarks: dict = None) -> str:
    if not regime_info:
        return ""

    regime  = regime_info.get("regime", "OSÄKER")
    conf    = regime_info.get("confidence", 0) * 100

    icons = {"TJUR": "🐂", "BJÖRN": "🐻", "NEUTRAL": "🟡", "OSÄKER": "❓"}
    icon  = icons.get(regime, "❓")

    lines = [f"## {icon} Marknadsläge: {regime} ({conf:.0f}% konfidens)\n"]

    notes = regime_info.get("notes", [])
    if notes:
        for note in notes[:3]:
            lines.append(f"- {note}")
        lines.append("")

    # Benchmark-tabell
    if benchmarks:
        lines.append("| Index | Idag | 1 mån | YTD |")
        lines.append("|-------|------|-------|-----|")
        for name, data in benchmarks.items():
            d1  = data.get("change_1d")
            m1  = data.get("change_1m")
            ytd = data.get("change_ytd")
            icon_d = _color_pct_raw(d1)
            lines.append(
                f"| **{name}** | {icon_d} {_fmt_pct_raw(d1)} | {_fmt_pct_raw(m1)} | {_fmt_pct_raw(ytd)} |"
            )
        lines.append("")

    if regime == "BJÖRN":
        lines.append("> ⚠️ **Björnmarknad aktiv** – systemet kräver högre score för KÖP-signaler.\n")

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════
# SEKTION 2: ÅTGÄRDSLISTA
# ══════════════════════════════════════════════════════════════

def section_action_list(analysis: pd.DataFrame, scored: pd.DataFrame) -> str:
    """
    Det viktigaste: vad behöver du faktiskt GÖRA den här veckan?
    Max 5-7 punkter. Konkret och handlingsbart.
    """
    if analysis is None or analysis.empty:
        return ""

    actions = []

    for _, row in analysis.iterrows():
        rec    = str(row.get("recommendation", ""))
        ticker = row["ticker"]
        reason = str(row.get("reason", ""))
        pnl    = row.get("unrealized_pnl_pct")

        if "SÄLJ" in rec.upper():
            pnl_s = f" (P&L: {_fmt_pct(pnl)})" if pnl is not None else ""
            actions.append(f"🔴 **SÄLJ `{ticker}`** – {reason}{pnl_s}")
        elif "KÖP MER" in rec.upper():
            actions.append(f"🟢 **KÖP MER `{ticker}`** – {reason}")
        elif "MINSKA" in rec.upper():
            actions.append(f"🟡 **MINSKA `{ticker}`** – {reason}")

    # Lägg till topp köpkandidater som INTE är i portföljen
    if scored is not None and not scored.empty:
        portfolio_tickers = set(analysis["ticker"].str.upper())
        new_candidates = scored[
            ~scored["ticker"].str.upper().isin(portfolio_tickers) &
            (scored.get("entry_signal", pd.Series("—", index=scored.index)) == "STARK")
        ].head(3)

        for _, row in new_candidates.iterrows():
            actions.append(
                f"💡 **Ny kandidat: `{row['ticker']}`** – "
                f"{str(row.get('name',''))[:25]}, score {_fmt_score(row.get('score_total'))}"
            )

    if not actions:
        return "## ⚡ Veckans åtgärder\n\n✅ Inga åtgärder krävs – portföljen ser bra ut.\n"

    lines = ["## ⚡ Veckans åtgärder\n"]
    for a in actions[:7]:
        lines.append(a)
    lines.append("")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════
# SEKTION 3: PORTFÖLJÖVERSIKT
# ══════════════════════════════════════════════════════════════

def section_portfolio(analysis: pd.DataFrame, summary: dict) -> str:
    if analysis is None or analysis.empty:
        return ""

    lines = ["## 💼 Din portfölj\n"]

    # Summaryrad
    if summary:
        n   = summary.get("n_positions", 0)
        val = summary.get("total_market_value")
        pnl = summary.get("total_unrealized_pnl")
        pct = summary.get("total_return_pct")
        avg = summary.get("average_score")

        val_s = f"{val:,.0f}" if val else "—"
        pnl_s = ""
        if pnl is not None:
            sign = "+" if pnl >= 0 else ""
            pnl_s = f" · P&L: **{sign}{pnl:,.0f}** ({_fmt_pct(pct)})"

        lines.append(f"**{n} positioner** · Marknadsvärde: {val_s}{pnl_s}")
        if avg:
            lines.append(f"Snittscore: {avg:.0f}/100\n")
        else:
            lines.append("")

    # Tabell – kompakt, fokus på det som spelar roll
    lines.append("| | Ticker | P&L idag | P&L totalt | Score | Signal |")
    lines.append("|---|--------|---------|-----------|-------|--------|")

    for _, row in analysis.iterrows():
        rec_ic = _rec_icon(row.get("recommendation"))
        ticker = row["ticker"]
        name   = str(row.get("name",""))[:20]
        score  = _fmt_score(row.get("score"))
        pnl    = row.get("unrealized_pnl_pct")
        pct_today = row.get("pnl_pct_today")  # Finns om daily_scan kört
        rec    = str(row.get("recommendation","—"))

        pnl_today_s = f"{_fmt_pct(pct_today)}" if pct_today is not None else "—"
        pnl_s       = _fmt_pct(pnl)

        lines.append(
            f"| {rec_ic} | **`{ticker}`** {name} | "
            f"{pnl_today_s} | {pnl_s} | {score} | {rec} |"
        )

    lines.append("")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════
# SEKTION 4: TOPP 10 KÖPKANDIDATER
# ══════════════════════════════════════════════════════════════

def section_top10(scored: pd.DataFrame, n: int = 10) -> str:
    if scored is None or scored.empty:
        return ""

    # Filtrera: bara STARK eller OK entry-signal
    top = scored.copy()
    if "entry_signal" in top.columns:
        strong = top[top["entry_signal"].isin(["STARK", "OK"])]
        if len(strong) >= n:
            top = strong

    top = top.head(n)

    lines = [f"## 🏆 Topp {n} köpkandidater\n"]

    for i, (_, row) in enumerate(top.iterrows(), 1):
        ticker  = row["ticker"]
        name    = str(row.get("name",""))[:30]
        sector  = str(row.get("sector",""))[:18]
        score   = _fmt_score(row.get("score_total"))
        entry   = str(row.get("entry_signal","—"))
        conf    = str(row.get("confidence_label","—"))
        trend   = "✅" if not row.get("trend_capped", False) else "⚠️"
        r12     = row.get("return_12m")
        pe      = row.get("pe_forward") or row.get("pe_trailing")
        roe     = row.get("roe")
        flag    = str(row.get("delta_flag","")) or ""
        pio     = row.get("piotroski_label","")
        rs      = str(row.get("rs_label",""))

        # Insider / Earnings signal
        ins = row.get("insider_signal")
        eps = row.get("earnings_signal")
        ins_s = "↑insiders" if ins and float(ins) > 0.65 else ""
        eps_s = "↑EPS-beat" if eps and float(eps) > 0.65 else ""
        extras = " · ".join(filter(None, [ins_s, eps_s, flag]))

        # Piotroski
        pio_s = f" · F-score: {row.get('piotroski_f','—')}/9" if pio == "STARK" else ""

        lines.append(
            f"**{i}. `{ticker}`** – {name} _{sector}_  \n"
            f"Score: **{score}** · {_entry_icon(entry)} {entry} · "
            f"Konf: {conf} · Trend: {trend}"
            + (f" · RS: {rs}" if rs and rs != "—" else "")
            + pio_s + "\n"
            + (f"12m: {_fmt_pct(r12)} · " if r12 else "")
            + (f"P/E: {pe:.1f} · " if pe and not pd.isna(pe) else "")
            + (f"ROE: {_fmt_pct(roe)}" if roe and not pd.isna(roe) else "")
            + (f"\n_{extras}_" if extras else "")
            + "\n"
        )

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════
# SEKTION 5: SEKTORER
# ══════════════════════════════════════════════════════════════

def section_sectors(sector_df: pd.DataFrame, sector_mom: dict = None) -> str:
    if (sector_df is None or sector_df.empty) and not sector_mom:
        return ""

    lines = ["## 📊 Sektorer\n"]

    if sector_mom:
        lines.append("**Sektormomtentum** (ETF-baserat):\n")
        order = ["STARK UPPTREND","UPPTREND","NEUTRAL","NEDTREND","STARK NEDTREND"]
        icons = {"STARK UPPTREND":"🟢🟢","UPPTREND":"🟢","NEUTRAL":"⚪","NEDTREND":"🔴","STARK NEDTREND":"🔴🔴"}
        sorted_sectors = sorted(sector_mom.items(),
                                key=lambda x: order.index(x[1].get("signal","NEUTRAL")))
        for s, data in sorted_sectors[:8]:
            sig  = data.get("signal","NEUTRAL")
            r3m  = data.get("return_3m")
            r3ms = f" {_fmt_pct(r3m)}" if r3m else ""  # return_3m är decimal
            lines.append(f"- {icons.get(sig,'⚪')} **{s}**{r3ms}")
        lines.append("")

    if sector_df is not None and not sector_df.empty:
        lines.append("**Universum per sektor** (snittpoäng):\n")
        lines.append("| Sektor | Aktier | Score | Bästa |")
        lines.append("|--------|--------|-------|-------|")
        for _, row in sector_df.head(10).iterrows():
            lines.append(
                f"| {row['sector']} | {row['antal']} | "
                f"{row['snitt_score']:.0f} | `{row['bästa_ticker']}` |"
            )
        lines.append("")

    return "\n".join(lines)


def _claude_prompt() -> str:
    return (
        "\n## 🤖 Klistra in i Claude Pro\n"
        "```\n"
        "Analysera min veckorapport ovan. Sök senaste 14 dagars nyheter\n"
        "för topp 10-aktierna och mina innehav.\n\n"
        "1. Finns röda flaggor bland topp 10 (skandaler, vinstvarningar,\n"
        "   regulatoriska problem, ledningsförändringar)?\n"
        "2. Bekräfta eller överrid åtgärdslistan – ska jag verkligen köpa/sälja?\n"
        "3. Vilka 3 av topp 10 är mest övertygande just nu?\n"
        "4. Är det något i mitt nuvarande innehav jag bör agera på snabbt?\n"
        "```"
    )
