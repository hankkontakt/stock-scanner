"""
scan.py – Huvudscript. Kör varje söndag: python scan.py

Användning:
  python scan.py                        # Full scan (700+ aktier)
  python scan.py --quick                # Hoppa extra data
  python scan.py --quiet                # Minimal output
  python scan.py --tickers AAPL,MSFT    # Specifika tickers
  python scan.py --validate-config      # Validera konfigurationen
"""
import argparse
import sys
import os
import time
import threading
import json as _json
from datetime import datetime
from pathlib import Path
import pandas as pd

import config
import data_fetcher
import scoring
import filters
import sectors
import watchlist as wl
import news_fetcher

# ── Auto-rensa felaktigt svartlistade kända aktier vid start ─────────────────
def _auto_clean_blacklist():
    """Rensar bort kända storbolag som felaktigt hamnat i blacklist.json."""
    import json as _json
    bl_path = Path("data/blacklist.json")
    if not bl_path.exists():
        return
    try:
        bl = _json.loads(bl_path.read_text(encoding="utf-8"))
        to_remove = [t for t in list(bl.keys()) if t in filters.NEVER_BLACKLIST]
        if to_remove:
            for t in to_remove:
                del bl[t]
            bl_path.write_text(_json.dumps(bl, indent=4), encoding="utf-8")
            print(f"  🧹 Auto-rensade {len(to_remove)} felaktigt blacklistade: "
                  f"{to_remove[:8]}{'...' if len(to_remove)>8 else ''}")
    except Exception:
        pass

_auto_clean_blacklist()
import portfolio, portfolio_analysis, extra_data
import delta_tracker, macro_regime, earnings_calendar
import sentiment as sentiment_module
import piotroski
import sector_momentum
import paper_trading
import alerts as alerts_module


def fmt_pct(x, d=1):
    if x is None or pd.isna(x): return "—"
    return f"{x*100:.{d}f}%"

def fmt_num(x, d=2):
    if x is None or pd.isna(x): return "—"
    return f"{x:.{d}f}"

def fmt_cur(x):
    if x is None or pd.isna(x): return "—"
    return f"{x:,.0f}"


# ── Rapport-sektioner ──────────────────────────────────────────────────────────

def _section_executive_summary(
    scored:      pd.DataFrame,
    regime_info: dict,
    benchmarks:  dict,
    analysis:    pd.DataFrame,
) -> str:
    """
    DEL 1 – Executive Summary.
    Kortfattad marknadsöversikt: läs på ≤3 sekunder och vet om du ska vara
    aggressiv eller defensiv.
    """
    ri   = regime_info or {}
    bm   = benchmarks  or {}
    lines = ["# 📊 Veckovis Aktiescan\n", "---\n", "## 🚦 Executive Summary\n"]

    # ── Marknadsregim ─────────────────────────────────────────
    regime    = ri.get("regime", "OSÄKER")
    composite = ri.get("composite")
    vix       = ri.get("vix_level")
    breadth   = ri.get("breadth_delta")
    spy_ma200 = ri.get("spy_vs_ma200")

    regime_icon = {"TJUR": "🟢", "BJÖRN": "🔴", "OSÄKER": "🟡"}.get(regime, "⚪")
    lines.append(f"### {regime_icon} Marknadsregim: **{regime}**")
    if composite is not None:
        conf_label = "Stark" if composite >= 0.70 else "Svag" if composite <= 0.45 else "Moderat"
        lines.append(f"Sammansatt konfidenspoäng: **{composite:.2f}/1.0** ({conf_label})\n")

    # ── Nyckelindikatorer ─────────────────────────────────────
    kpi_lines = []
    if vix is not None:
        vix_icon = "🔴 HÖG" if vix >= 25 else "🟡 FÖRHÖJD" if vix >= 18 else "🟢 LÅG"
        kpi_lines.append(f"**VIX:** {vix:.1f} ({vix_icon} risk)")
    if spy_ma200 is not None:
        ma_icon = "🟢" if spy_ma200 > 0 else "🔴"
        kpi_lines.append(f"**SPY vs MA200:** {ma_icon} {spy_ma200*100:+.1f}%")
    if breadth is not None:
        br_icon = "🟢 BRED" if breadth > 0 else "🔴 SMAL"
        kpi_lines.append(f"**Marknadsbredd (RSP/SPY):** {br_icon} ({breadth:+.3f})")
    for name, data in bm.items():
        ytd = data.get("change_ytd", 0)
        d1  = data.get("change_1d", 0)
        kpi_lines.append(f"**{name}:** {d1:+.1f}% idag · {ytd:+.1f}% YTD")

    if kpi_lines:
        lines.append("\n".join(kpi_lines) + "\n")

    # ── Scan-signaler ─────────────────────────────────────────
    if not scored.empty:
        n_total  = len(scored)
        n_stark  = (scored.get("entry_signal",  pd.Series()) == "STARK").sum()
        n_hog    = (scored.get("confidence_label", pd.Series()) == "HÖG").sum()
        n_up     = (~scored.get("trend_capped", pd.Series(True))).sum()
        pct_up   = n_up / n_total * 100 if n_total else 0

        stance_icon = "🟢 AGGRESSIV" if (regime == "TJUR" and pct_up > 60) else \
                      "🔴 DEFENSIV"  if (regime == "BJÖRN" or pct_up < 35) else \
                      "🟡 NEUTRAL"
        lines.append(f"**Rekommenderad hållning: {stance_icon}**\n")
        lines.append(
            f"Scannade: **{n_total}** aktier · "
            f"**{n_stark}** STARK entry · "
            f"**{n_hog}** HÖG konfidens · "
            f"**{pct_up:.0f}%** i upptrend\n"
        )

        if regime == "BJÖRN":
            lines.append(
                "> ⚠️ **Björnmarknad aktiv** – marknadsbredden är negativ och/eller VIX spikar. "
                "Höj kraven för nya köp. Prioritera stop-losses och defensiva sektorer.\n"
            )
        elif regime == "TJUR" and pct_up > 60:
            lines.append(
                "> ✅ Bred uppgång med god marknadsbredd. Köpklimat normalläge.\n"
            )

    # ── Portfölj-snabbstatus ──────────────────────────────────
    if analysis is not None and not (isinstance(analysis, pd.DataFrame) and analysis.empty):
        try:
            df = analysis if isinstance(analysis, pd.DataFrame) else pd.DataFrame(analysis)
            n_sell  = (df["recommendation"].str.contains("SÄLJ", na=False)).sum()
            n_buy   = (df["recommendation"].str.contains("KÖP MER", na=False)).sum()
            n_hold  = (df["recommendation"].str.contains("BEHÅLL", na=False)).sum()
            lines.append(
                f"**Portfölj:** 🔴 {n_sell} SÄLJ · 🟢 {n_buy} KÖP MER · 🔵 {n_hold} BEHÅLL\n"
            )
        except Exception:
            pass

    lines.append("\n---\n")
    return "\n".join(lines)


# ── Rapport-sektioner ──────────────────────────────────────────────────────────
def _section_sectors_top5(scored: pd.DataFrame, sector_summary: pd.DataFrame) -> str:
    """
    Rankar sektorer efter potential (snitt_score) och visar de upp till 5 
    bästa aktierna i varje sektor.
    """
    if sector_summary.empty:
        return ""

    lines = ["\n## 🏭 Sektoranalys & Bästa kandidater\n"]
    lines.append("_Vilka sektorer har störst potential just nu? Rankat efter sektorns genomsnittliga score._\n")

    # 1. Sektor-rankingen (vilken sektor har störst potential?)
    lines.append("| Rank | Sektor | Snitt-score | Antal | Bästa Ticker | Max-score |")
    lines.append("|------|--------|-------------|-------|--------------|-----------|")
    
    for i, (_, row) in enumerate(sector_summary.iterrows(), 1):
        lines.append(
            f"| {i} | **{row['sector']}** | {row['snitt_score']:.1f} | "
            f"{row['antal']} | `{row['bästa_ticker']}` | {row['bästa_score']:.1f} |"
        )
    
    lines.append("\n---\n")

    # 2. Topp 5 aktier inom varje sektor
    # Vi loopar igenom alla sektorer i rankningsordning
    for _, row in sector_summary.iterrows():
        sec_name = row['sector']
        # Hämta de 5 bästa aktierna i just denna sektor
        sec_stocks = (scored[scored['sector'] == sec_name]
                      .sort_values("score_total", ascending=False)
                      .head(5))
        
        if sec_stocks.empty: 
            continue

        lines.append(f"### 📍 1-5 i {sec_name}")
        lines.append("| Ticker | Bolag | Score | Entry | Konf | Trend |")
        lines.append("|--------|-------|-------|-------|------|-------|")
        
        for _, r in sec_stocks.iterrows():
            entry = str(r.get("entry_signal", "—"))
            konf = str(r.get("confidence_label", "—"))
            trend = str(r.get("trend_signal", "—"))
            
            lines.append(
                f"| `{r['ticker']}` | {str(r.get('name', ''))[:20]} | "
                f"{r.get('score_total', 0):.1f} | {entry} | {konf} | {trend} |"
            )
        lines.append("\n")

    return "\n".join(lines)
    

    
def _section_sector_heatmap(scored: pd.DataFrame, sector_df: pd.DataFrame) -> str:
    """
    DEL 2 – Enkel sektors-heatmap: upptrend vs nedtrend-textmatris.
    Kompaktare alternativ till de djupa 1-5 per sektor-listorna.
    """
    if scored.empty or "sector" not in scored.columns:
        return ""

    up_sectors   = []
    down_sectors = []
    neutral      = []

    if sector_df is not None and not sector_df.empty and "sector" in sector_df.columns:
        for _, row in sector_df.iterrows():
            sec   = row["sector"]
            score = row.get("snitt_score", 50)
            # Bestäm trend via andel aktier i upptrend inom sektorn
            sec_stocks = scored[scored["sector"] == sec]
            if sec_stocks.empty:
                continue
            pct_up = (~sec_stocks.get("trend_capped", pd.Series(True))).mean() * 100
            if pct_up >= 60 and score >= 55:
                up_sectors.append((sec, score, pct_up))
            elif pct_up < 40 or score < 45:
                down_sectors.append((sec, score, pct_up))
            else:
                neutral.append((sec, score, pct_up))
    else:
        return ""

    lines = ["\n## 🗺️ Sektors-heatmap\n"]
    if up_sectors:
        tickers = " · ".join(
            f"**{s}** ({sc:.0f}pts, {p:.0f}% upp)"
            for s, sc, p in sorted(up_sectors, key=lambda x: -x[1])
        )
        lines.append(f"🟢 **UPPTREND:** {tickers}\n")
    if neutral:
        tickers = " · ".join(f"{s}" for s, _, _ in neutral)
        lines.append(f"🟡 **NEUTRAL:** {tickers}\n")
    if down_sectors:
        tickers = " · ".join(
            f"**{s}** ({sc:.0f}pts)"
            for s, sc, _ in sorted(down_sectors, key=lambda x: x[1])
        )
        lines.append(f"🔴 **NEDTREND:** {tickers}\n")

    return "\n".join(lines)


def _section_top_n(scored, n):
    """
    Bygger topp-N-tabellen med sektorcap på MAX 2 per sektor.
    Holdingbolag och råvarubolag är redan nedviktade via scoring.py,
    men cap 2 ger extra skydd mot att en sektor tar fler platser.

    Automatisk förfiltrering: aktier med för hög volatilitet (score_risk < 25)
    eller mycket svag Piotroski-poäng (< 2) sorteras bort innan utskrift.

    Visar listnummer (#1-10) istället för global rank, eftersom
    global rank inte stämmer efter sektorcap-filtreringen.
    """
    MAX_PER_SECTOR = 2  # Max 2 aktier per sektor i topp-N

    # ── Volatilitets- och Piotroski-förfilter (Del 2) ────────
    pre_len = len(scored)
    risk_col = "score_risk"
    pio_col  = "piotroski_score"
    filtered = scored.copy()
    if risk_col in filtered.columns:
        filtered = filtered[
            filtered[risk_col].isna() | (filtered[risk_col] >= 25)
        ]
    if pio_col in filtered.columns:
        filtered = filtered[
            filtered[pio_col].isna() | (filtered[pio_col] >= 2)
        ]
    n_removed = pre_len - len(filtered)
    filter_note = (
        f"_⚙️ Förfilter: {n_removed} aktier sorterades bort (hög volatilitet / låg Piotroski) "
        f"innan topp-{n} valdes ut._\n"
    ) if n_removed > 0 else ""

    top_list = []
    sector_counts = {}

    for _, r in filtered.iterrows():
        sec = r.get("sector", "Övrigt")
        if pd.isna(sec):
            sec = "Övrigt"

        # Sektorcap: max MAX_PER_SECTOR per sektor
        if sector_counts.get(sec, 0) < MAX_PER_SECTOR:
            top_list.append(r)
            sector_counts[sec] = sector_counts.get(sec, 0) + 1

        if len(top_list) >= n:
            break

    top = pd.DataFrame(top_list)

    lines = [f"## 🏆 Topp {n} aktier (Max {MAX_PER_SECTOR} per sektor)\n"]
    if filter_note:
        lines.append(filter_note)
    lines.append("| # | Ticker | Bolag | Score | Entry | Konf | Trend | RS | Insider | EPS | Δ |")
    lines.append("|---|--------|-------|-------|-------|------|-------|----|---------|-----|---|")
    ei = {"STARK": "🟢", "OK": "🔵", "VÄNTA": "🟡", "EJ AKTUELL": "🔴"}

    for list_pos, (_, r) in enumerate(top.iterrows(), 1):
        entry = r.get("entry_signal", "—")
        conf  = r.get("confidence_label", "—")
        trend = "✅" if not r.get("trend_capped", False) else "⚠️"
        flag  = r.get("delta_flag", "") or ""
        rs    = r.get("rs_label", "—")
        ctype = r.get("company_type", "standard")

        # Visa bolagstyp-ikon så man vet varför score kan vara rabatterat
        type_icon = " 🏦" if ctype == "holding" else " ⛏" if ctype == "commodity" else ""

        ins = r.get("insider_signal")
        eps = r.get("earnings_signal")
        ins_s = ("🟢" if ins > 0.65 else "🔴" if ins < 0.35 else "⚪") if pd.notna(ins or float("nan")) else "—"
        eps_s = ("🟢" if eps > 0.65 else "🔴" if eps < 0.35 else "⚪") if pd.notna(eps or float("nan")) else "—"

        # Använd listnummer (#1-10) inte global rank (som är missvisande efter sektorcap)
        global_rank = r.get("rank", "—")
        rank_display = f"#{list_pos} (rank {global_rank})"

        lines.append(
            f"| {rank_display} | `{r['ticker']}`{type_icon} | "
            f"{str(r.get('name', ''))[:22]} | "
            f"**{r['score_total']:.0f}** | {ei.get(entry, '—')} {entry} | "
            f"{conf} | {trend} | {rs} | {ins_s} | {eps_s} | {flag[:35]} |"
        )
    return "\n".join(lines)


def _section_sectors(sector_df):
    if sector_df is None or sector_df.empty: return ""
    lines = ["\n## 🏭 Sektorer – rankat efter styrka\n",
             "| Sektor | Aktier | Snitt-score | Bästa | Score |",
             "|--------|--------|-------------|-------|-------|"]
    for _, r in sector_df.iterrows():
        lines.append(f"| {r['sector']} | {r['antal']} | **{r['snitt_score']:.0f}** | "
                     f"`{r['bästa_ticker']}` | {r['bästa_score']:.0f} |")
    return "\n".join(lines)


def _section_portfolio(analysis, summary):
    if analysis.empty: return ""
    lines = ["\n## 💼 Din portfölj – rekommendationer\n"]
    if summary:
        lines.append("### Översikt")
        lines.append(f"- **Positioner:** {summary['n_positions']}")
        if summary.get("total_market_value"):
            lines.append(f"- **Marknadsvärde:** {fmt_cur(summary['total_market_value'])}")
        if summary.get("total_unrealized_pnl") is not None:
            p = summary["total_unrealized_pnl"]
            lines.append(f"- **P&L:** {'+' if p>=0 else ''}{fmt_cur(p)} ({fmt_pct(summary.get('total_return_pct'))})")
        avg = summary.get("average_score")
        if avg is not None and not (avg != avg):  # isnan check without importing math
            lines.append(f"- **Snittscore:** {avg:.0f}/100")
        recs = summary.get("recommendations",{})
        if recs:
            lines.append("- **Reker:** " + " · ".join(f"**{k}** {v}st" for k,v in recs.items()))
        lines.append("")
    lines.append("### Per innehav\n")
    lines.append("| Ticker | Bolag | Score | Rank | Rekommendation | Skäl | P&L |")
    lines.append("|--------|-------|-------|------|----------------|------|-----|")
    for _, r in analysis.iterrows():
        lines.append(f"| `{r['ticker']}` | {str(r.get('name',''))[:22]} | "
                     f"{fmt_num(r.get('score'),0)} | {r.get('rank','—')} | "
                     f"**{r['recommendation']}** | {str(r.get('reason',''))[:55]} | "
                     f"{fmt_pct(r.get('unrealized_pnl_pct'))} |")
    return "\n".join(lines)


def _section_claude_prompt():
    return (
        "\n## 🤖 AI-analyspromptar\n"
        "_Klistra in rapporten + dessa frågor i Claude Pro / ChatGPT för djupanalys._\n\n"

        "**1. Dataintegritet och algoritmkontroll:**\n"
        "```\n"
        "Läs det bifogade AI-datalagret (JSON/CSV) längst ner i dokumentet. "
        "Finns det några uppenbara fel i datainhämtningen (t.ex. saknade värden, NaN, eller "
        "orimliga volatilitetssiffror) som riskerar att snedvrida topplistan? Granska även om "
        "algoritmens nuvarande vikter (t.ex. Value vs Momentum) är optimala för den aktuella "
        "marknadsregimen.\n"
        "```\n\n"

        "**2. Nyhets- och riskvalidering av toppkandidater (Sök-trigger):**\n"
        "```\n"
        "Ta de 5 högst rankade aktierna från listan. Sök på nätet efter de allra senaste "
        "nyheterna, kvartalsrapporterna och eventuella makroekonomiska händelser som kan påverka "
        "dessa specifika bolag. Finns det någon fundamental anledning, nyhet eller "
        "varningsklocka som inte syns i den tekniska datan till varför jag INTE bör köpa "
        "någon av dessa idag?\n"
        "```\n\n"

        "**3. Sektormomentum och framtidsinsikter (Sök-trigger):**\n"
        "```\n"
        "Analysera sektors-heatmapen och rådatan för sektorerna i filen. Vilka underliggande "
        "trender driver de ledande sektorerna just nu? Sök efter aktuella nyheter för dessa "
        "sektorer och ge en bedömning av om detta momentum är hållbart, eller om marknaden "
        "indikerar en stundande sektorrotation.\n"
        "```\n\n"

        "**4. Portföljsynk och rebalansering:**\n"
        "```\n"
        "Utifrån min nuvarande portfölj och den rådande marknadsregimen (SPY vs MA200 och "
        "marknadsbredd): Vilka av de kurerade toppkandidaterna erbjuder bäst diversifiering "
        "för att sänka min totala portföljrisk? Identifiera även baserat på rådatan vilka av "
        "mina nuvarande innehav som visar svagast teknisk trend och därmed bör övervägas "
        "för försäljning.\n"
        "```"
    )


def _section_ai_datalayer(scored: pd.DataFrame, regime_info: dict) -> str:
    """
    DEL 3 – AI-optimerat Datalager.
    Minifierad JSON + CSV med all rådata längst ner i rapporten.
    AI-modeller kan direkt utföra exakta matematiska tväranalyser utan läsfel.
    """
    import json as _json

    lines = ["\n---\n## 📦 AI-Datalager (Maskinläsbart)\n"]
    lines.append("_Rådata för AI-analys. Klistra in hela rapporten i Claude Pro._\n")

    # ── Algoritm-metadata ─────────────────────────────────────
    fw = config.FACTOR_WEIGHTS
    meta = {
        "scan_date":      datetime.now().strftime("%Y-%m-%d %H:%M"),
        "universe_size":  len(scored),
        "regime":         (regime_info or {}).get("regime", "OSÄKER"),
        "composite":      (regime_info or {}).get("composite"),
        "vix":            (regime_info or {}).get("vix_level"),
        "spy_vs_ma200":   (regime_info or {}).get("spy_vs_ma200"),
        "breadth_delta":  (regime_info or {}).get("breadth_delta"),
        "factor_weights": fw,
        "thresholds": {
            "buy_more_percentile": config.BUY_MORE_PERCENTILE,
            "hold_percentile":     config.HOLD_PERCENTILE,
            "min_data_quality":    config.MIN_DATA_QUALITY,
            "top_n":               config.TOP_N_RECOMMENDATIONS,
        },
    }
    lines.append("### Metadata\n```json")
    lines.append(_json.dumps(meta, indent=2))
    lines.append("```\n")

    # ── Topp-50 som JSON ──────────────────────────────────────
    if not scored.empty:
        cols_to_export = [
            c for c in [
                "ticker", "name", "sector", "score_total", "rank",
                "entry_signal", "confidence_label", "trend_signal",
                "score_value", "score_quality", "score_momentum",
                "score_growth", "score_risk", "score_sentiment",
                "pe_ratio", "pb_ratio", "roe", "revenue_growth",
                "piotroski_score", "rs_label", "insider_signal",
                "earnings_signal", "data_quality", "price_vs_ma200",
            ] if c in scored.columns
        ]
        top50_df = scored.head(50)[cols_to_export].copy()

        # Rensa NaN/Inf för JSON-serialisering
        top50_df = top50_df.replace([float("inf"), float("-inf")], None)
        top50_records = []
        for row in top50_df.to_dict("records"):
            clean = {k: (None if isinstance(v, float) and pd.isna(v) else v) for k, v in row.items()}
            top50_records.append(clean)

        lines.append("### Topp-50 Aktier (JSON)\n```json")
        lines.append(_json.dumps(top50_records, ensure_ascii=False))
        lines.append("```\n")

        # ── Portfölj-aktier som CSV ───────────────────────────
        lines.append("### Alla Analyserade Aktier – Score-sammanfattning (CSV)\n```csv")
        csv_cols = [c for c in ["ticker", "name", "sector", "score_total", "rank",
                                "entry_signal", "confidence_label"] if c in scored.columns]
        lines.append(",".join(csv_cols))
        for _, row in scored[csv_cols].iterrows():
            vals = []
            for c in csv_cols:
                v = row[c]
                if isinstance(v, float) and pd.isna(v):
                    vals.append("")
                else:
                    vals.append(str(v).replace(",", ";"))
            lines.append(",".join(vals))
        lines.append("```")

    return "\n".join(lines)
            
            
def _section_cleanup(warnings, removed):
    """Skapar markdown-sektionen för automatiskt systemunderhåll."""
    if not warnings and not removed:
        return ""
    
    lines = ["\n## 🧹 Systemunderhåll (Självläkning)\n"]
    lines.append("_Systemet rensar automatiskt bort aktier som saknar data efter 3 misslyckade försök._\n")
    
    if removed:
        lines.append("### ❌ Raderade från universumet (Blacklist)")
        lines.append("| Ticker | AI Diagnos / Orsak |")
        lines.append("|--------|--------------------|")
        for item in removed:
            # item är en dict som vi skapade i filters.update_ticker_health
            ticker = item.get('ticker', 'Unknown')
            reason = item.get('reason', 'Ingen data tillgänglig')
            lines.append(f"| `{ticker}` | {reason} |")
        lines.append("") # Tom rad
    
    if warnings:
        lines.append("### ⚠️ Varning: På väg att raderas (2 strikes)")
        lines.append("Dessa aktier saknar data och raderas vid nästa misslyckade scan:")
        for w in warnings:
            lines.append(f"- `{w}`")
        lines.append("")
    
    return "\n".join(lines) + "\n"

def _section_watchlist(scored: pd.DataFrame) -> str:
    """
    Bygger bevakningslistans sektion i veckorapporten.
    Visar djupanalys per aktie: score, köp/sälj-bedömning, nyhetssentiment,
    earnings-datum, och faktorprofil.
    """
    watchlist_items = wl.load_watchlist()
    if not watchlist_items:
        return ""

    lines = ["\n## ⭐ Min Bevakningslista\n"]
    lines.append("_Aktier jag bevakar extra noga – djupanalys varje vecka._\n")

    score_lookup = {}
    if not scored.empty and "ticker" in scored.columns:
        score_lookup = scored.set_index("ticker").to_dict("index")

    for item in watchlist_items:
        ticker = item["ticker"]
        sc     = score_lookup.get(ticker, {})
        name   = sc.get("name") or item.get("name") or ticker

        score      = sc.get("score_total")
        rank       = sc.get("rank")
        entry      = sc.get("entry_signal", "EJ SCANNAD")
        conf       = sc.get("confidence_label", "—")
        trend      = sc.get("trend_signal", "—")
        rs         = sc.get("rs_label", "—")
        sector     = sc.get("sector", "—")
        universe_n = len(scored) if not scored.empty else 0

        # Köp/sälj-bedömning
        if score is None:
            rec = "EJ SCANNAD"
            rec_reason = "Aktien finns inte i nuvarande scan-universum"
        elif score >= 70 and entry == "STARK":
            rec = "KÖP"
            rec_reason = f"Stark fundamental profil (score {score:.0f}/100), HÖG konfidens"
        elif score >= 60 and entry in ("STARK", "OK"):
            rec = "BEVAKA / KÖP VID DIP"
            rec_reason = f"God fundamental kvalitet (score {score:.0f}/100), invänta bättre entry"
        elif score >= 50:
            rec = "VÄNTA"
            rec_reason = f"Medelscore ({score:.0f}/100) – fundamenta ej tillräckligt starka"
        else:
            rec = "UNDVIK"
            rec_reason = f"Svag fundamental profil (score {score:.0f}/100)"

        rec_icon = {"KÖP": "🟢", "BEVAKA / KÖP VID DIP": "🔵", "VÄNTA": "🟡", "UNDVIK": "🔴", "EJ SCANNAD": "⚪"}.get(rec, "⚪")

        lines.append(f"### {rec_icon} `{ticker}` · {name}")
        lines.append(f"_Sektor: {sector}_\n")

        if score is not None:
            rank_s = f"Rank #{rank} av {universe_n}" if rank else "—"
            lines.append(f"**Score: {score:.0f}/100** · {rank_s} · Entry: **{entry}** · Konfidens: {conf} · Trend: {trend} · RS: {rs}\n")
        else:
            lines.append("_Aktien finns inte i nuvarande scan-universum._\n")

        lines.append(f"**Rekommendation: {rec}**  \n_{rec_reason}_\n")

        # Faktorprofil (om data finns)
        v_score  = sc.get("score_value")
        q_score  = sc.get("score_quality")
        m_score  = sc.get("score_momentum")
        g_score  = sc.get("score_growth")
        r_score  = sc.get("score_risk")
        s_score  = sc.get("score_sentiment")

        factor_parts = []
        for label, val in [("Värdering", v_score), ("Kvalitet", q_score),
                           ("Momentum", m_score), ("Tillväxt", g_score),
                           ("Risk", r_score), ("Sentiment", s_score)]:
            if val is not None and not (isinstance(val, float) and pd.isna(val)):
                icon = "🟢" if val >= 70 else "🔴" if val < 40 else "🟡"
                factor_parts.append(f"{label}: {icon}{val:.0f}")

        if factor_parts:
            lines.append("**Faktorer:** " + " · ".join(factor_parts) + "\n")

        # Nyhetssentiment
        sentiment = sc.get("sentiment_raw")
        if sentiment is not None and not (isinstance(sentiment, float) and pd.isna(sentiment)):
            sent_icon = "🟢 Positiva" if sentiment > 0.6 else "🔴 Negativa" if sentiment < 0.4 else "⚪ Neutrala"
            lines.append(f"**Nyheter:** {sent_icon} (sentimentscore: {sentiment:.2f})\n")

        # Earnings-datum
        earn_date = sc.get("next_earnings_date") or sc.get("earnings_date")
        if earn_date:
            try:
                days = (pd.Timestamp(earn_date).date() - datetime.now().date()).days
                if 0 <= days <= 180:
                    urgent = " ⚠️ Rapport inom 14 dagar!" if days <= 14 else ""
                    lines.append(f"**Nästa rapport:** {str(earn_date)[:10]} (om {days} dagar){urgent}\n")
            except Exception:
                pass

        # Viktiga nyckeltal
        pe  = sc.get("pe_ratio")
        pb  = sc.get("pb_ratio")
        roe = sc.get("roe")
        rev_g = sc.get("revenue_growth")
        kv_parts = []
        if pe  and not pd.isna(pe):  kv_parts.append(f"P/E: {pe:.1f}x")
        if pb  and not pd.isna(pb):  kv_parts.append(f"P/B: {pb:.1f}x")
        if roe and not pd.isna(roe): kv_parts.append(f"ROE: {roe*100:.1f}%")
        if rev_g and not pd.isna(rev_g): kv_parts.append(f"Rev.tillväxt: {rev_g*100:.1f}%")
        if kv_parts:
            lines.append("**Nyckeltal:** " + " · ".join(kv_parts) + "\n")

        lines.append("---")

    return "\n".join(lines)


def _section_market_news(
    global_news:    list,
    swedish_news:   list,
    news_by_ticker: dict,
    holdings:       pd.DataFrame,
    scored:         pd.DataFrame,
    top_news:       dict = None,
    nasdaq_news:    list = None,
) -> str:
    """
    Marknadsnyheter för söndagsrapporten.
    Fyra delar:
      1. 📋 Nasdaq Nordic – officiella börsmeddelanden (nytt)
      2. 🇸🇪 Svenska börsnyheter (RSS)
      3. 🌍 Globala marknadsnyheter (Finnhub)
      4. 🏆 Nyheter för topp-10 rankade aktier (nytt – Google News RSS)
      5. 📰 Bolagsnyheter portfölj + bevakningslista
    """
    top_news    = top_news    or {}
    nasdaq_news = nasdaq_news or []

    if not global_news and not swedish_news and not news_by_ticker \
            and not top_news and not nasdaq_news:
        return ""

    # Ticker → namn (portfölj + bevakningslista)
    ticker_names = {}
    if holdings is not None and not holdings.empty:
        if "name" in holdings.columns:
            ticker_names.update(dict(zip(
                holdings["ticker"].str.upper(), holdings["name"]
            )))
    for item in wl.load_watchlist():
        ticker_names[item["ticker"]] = item.get("name", item["ticker"])
    # Lägg till scored-namn för topp-aktier
    if not scored.empty and "name" in scored.columns:
        for _, r in scored.head(15).iterrows():
            ticker_names[r["ticker"]] = str(r.get("name", r["ticker"]) or r["ticker"])

    parts = []

    # 1. Nasdaq Nordic
    nasdaq_md = news_fetcher.format_nasdaq_nordic_section_md(nasdaq_news, max_items=10)
    if nasdaq_md:
        parts.append(nasdaq_md)

    # 2+3. Generella marknadsnyheter (Sverige + globalt)
    market_md = news_fetcher.format_market_news_section_md(
        global_news, swedish_news, compact=False
    )
    if market_md:
        parts.append(market_md)

    # 4. Topp-10 rankade aktier – nyheter (Google News RSS)
    if top_news:
        top_md = news_fetcher.format_news_section_md(
            top_news,
            ticker_names=ticker_names,
            header="🏆 Nyheter – Veckans Topp-10 Kandidater",
        )
        if top_md:
            parts.append(top_md)

    # 5. Bolagsnyheter portfölj + bevakningslista
    if news_by_ticker:
        company_md = news_fetcher.format_news_section_md(
            news_by_ticker,
            ticker_names=ticker_names,
            header="📰 Bolagsnyheter (portfölj + bevakningslista)",
        )
        if company_md:
            parts.append(company_md)

    return "\n".join(parts)


def build_report(scored, analysis, summary, sector_df, regime_info, earnings_df, holdings, warnings=None, removed=None, sector_mom=None, benchmarks=None, global_news=None, swedish_news=None, news_by_ticker=None, top_news=None, nasdaq_news=None):
    bm = benchmarks or {}

    parts = []

    def _try(label, fn):
        try:
            result = fn()
            if result:
                parts.append(result)
        except Exception as e:
            import traceback
            print(f"  ⚠ Sektion '{label}' misslyckades: {e}")
            traceback.print_exc()

    # ── DEL 1: Executive Summary (alltid överst) ──────────────
    _try("Executive Summary", lambda: _section_executive_summary(scored, regime_info, bm, analysis))

    # ── DEL 2: Kurerad topplista + sektors-heatmap ────────────

    # 1. Detaljerad marknadsregim (expanderad)
    if regime_info:
        _try("Marknadsregim", lambda: macro_regime.build_regime_section(regime_info))

    # 2. Benchmark-tabell
    if bm:
        def _bm():
            bm_lines = ["\n## 📊 Benchmark\n",
                        "| Index | Idag | 1 månad | YTD |",
                        "|-------|------|---------|-----|"]
            for name, data in bm.items():
                d1  = data.get("change_1d",  0)
                m1  = data.get("change_1m",  0)
                ytd = data.get("change_ytd", 0)
                s1 = "+" if d1 >= 0 else ""; sm = "+" if m1 >= 0 else ""; sy = "+" if ytd >= 0 else ""
                bm_lines.append(f"| **{name}** | {s1}{d1:.1f}% | {sm}{m1:.1f}% | {sy}{ytd:.1f}% |")
            return "\n".join(bm_lines)
        _try("Benchmark", _bm)

    # 3. Sektors-heatmap (enkel textmatris, Del 2)
    _try("Sektors-heatmap", lambda: _section_sector_heatmap(scored, sector_df))

    # 4. Topp-N (med volatilitets-/Piotroski-förfilter, Del 2)
    _try("Topp-N", lambda: _section_top_n(scored, config.TOP_N_RECOMMENDATIONS))

    # 5. Piotroski
    _try("Piotroski", lambda: piotroski.build_piotroski_section(scored))

    # 6. Risk Parity
    _try("Risk Parity", lambda: portfolio_analysis._section_risk_parity(scored))

    # 7. Sektor-ETF momentum
    if sector_mom:
        _try("Sektor-momentum", lambda: sector_momentum.build_sector_momentum_section(sector_mom))

    # 8. Sektorer (detaljerad ranking)
    _try("Sektorer", lambda: _section_sectors(sector_df))

    # 9. Delta
    _try("Delta", lambda: delta_tracker.build_delta_report_section(scored))

    # 10. Earnings
    def _earn():
        pc = earnings_df.get("portfolio", pd.DataFrame()) if isinstance(earnings_df, dict) else earnings_df
        tc = earnings_df.get("top", pd.DataFrame()) if isinstance(earnings_df, dict) else pd.DataFrame()
        return earnings_calendar.build_earnings_section(pc, tc)
    _try("Earnings", _earn)

    # 11. Portfölj
    if not analysis.empty:
        _try("Portfölj", lambda: _section_portfolio(analysis, summary))
        _try("Portföljanalys", lambda: portfolio_analysis.build_portfolio_analysis_section(analysis, scored))

    # 12. Bevakningslista
    _try("Bevakningslista", lambda: _section_watchlist(scored))

    # 12.5 Marknadsnyheter (Sverige + globalt + Nasdaq Nordic + bolagsspecifikt)
    _try("Marknadsnyheter", lambda: _section_market_news(
        global_news    or [],
        swedish_news   or [],
        news_by_ticker or {},
        holdings,
        scored,
        top_news    = top_news    or {},
        nasdaq_news = nasdaq_news or [],
    ))

    # 13. Systemunderhåll
    _try("Systemunderhåll", lambda: _section_cleanup(warnings, removed))

    # 14. Paper trading
    _try("Paper trading", lambda: paper_trading.build_paper_trading_section())

    # ── DEL 3: AI-prompts + Datalager (alltid sist) ───────────
    parts.append(_section_claude_prompt())
    _try("AI-datalager", lambda: _section_ai_datalayer(scored, regime_info))
    parts.append("\n---\n*⚠ Inte finansiell rådgivning.*")

    return "\n".join(parts)


# ── Validering ─────────────────────────────────────────────────────────────────

def _validate_config() -> list:
    """
    Validerar att konfigurationen är korrekt.
    Returnerar en lista med felmeddelanden (tom lista = giltig).
    """
    errors = []

    # 1. API-nycklar
    if not config.FMP_API_KEY:
        errors.append("FMP_API_KEY saknas – krävs för fundamental data")
    if not config.FINNHUB_API_KEY:
        errors.append("FINNHUB_API_KEY saknas – sentiment hoppas över (OK)")

    # 2. Universumstorlek
    n_tickers = len(config.UNIVERSE)
    if n_tickers < 10:
        errors.append(f"UNIVERSE har bara {n_tickers} tickers (minimum 10)")
    elif n_tickers > 5000:
        errors.append(f"UNIVERSE har {n_tickers} tickers – kan orsaka timeout i GitHub Actions")

    # 3. Faktorvikter summerar till ~1.0
    w = config.FACTOR_WEIGHTS
    total = sum(w.values())
    if abs(total - 1.0) > 0.01:
        errors.append(f"FACTOR_WEIGHTS summerar till {total:.3f} (ska vara 1.0)")

    # 4. Scoringvikter för smallcap
    sc_w = config.SMALLCAP_CONFIG.get("scoring_weights", {})
    sc_total = sum(sc_w.values())
    if abs(sc_total - 1.0) > 0.01:
        errors.append(f"SMALLCAP_CONFIG scoring_weights summerar till {sc_total:.3f} (ska vara 1.0)")

    # 5. Parallel workers sanity
    if config.PARALLEL_WORKERS < 1:
        errors.append(f"PARALLEL_WORKERS={config.PARALLEL_WORKERS} (måste vara ≥ 1)")
    if config.PARALLEL_WORKERS > 32:
        errors.append(f"PARALLEL_WORKERS={config.PARALLEL_WORKERS} (kan orsaka rate limiting)")

    if config.FINNHUB_PARALLEL_WORKERS < 1:
        errors.append(f"FINNHUB_PARALLEL_WORKERS={config.FINNHUB_PARALLEL_WORKERS} (måste vara ≥ 1)")
    if config.FINNHUB_CALLS_PER_MINUTE > 60:
        errors.append(f"FINNHUB_CALLS_PER_MINUTE={config.FINNHUB_CALLS_PER_MINUTE} (max 60 för gratisnivån)")

    # 6. Trilsklar bör vara i rimligt intervall
    if not (0 < config.MIN_DATA_QUALITY <= 1):
        errors.append(f"MIN_DATA_QUALITY={config.MIN_DATA_QUALITY} (måste vara 0–1)")

    # 7. Kataloger som måste finnas
    for required_dir in ["data", "reports"]:
        p = Path(required_dir)
        if not p.exists():
            errors.append(f"Katalog '{required_dir}' finns inte")

    return errors


# ── Huvudpipeline ──────────────────────────────────────────────────────────────

def main():
    # Watchdog: force-exit if the entire scan hangs past 100 minutes.
    # Daemon thread dies with the process on normal exit; only fires on true hangs.
    def _watchdog():
        time.sleep(100 * 60)
        print("\n⏰ WATCHDOG: Scan exceeded 100 min — force-exiting to prevent GitHub hang.")
        os._exit(1)
    threading.Thread(target=_watchdog, daemon=True, name="ScanWatchdog").start()

    parser = argparse.ArgumentParser(
        description="MarketScan – multfaktor-aktiescanner",
        epilog="Exempel: python scan.py --quick --quiet"
    )
    parser.add_argument("--tickers",        help="Komma-separerade tickers")
    parser.add_argument("--quick",          action="store_true", help="Hoppa över extra data")
    parser.add_argument("--quiet",          action="store_true", help="Minimal output")
    parser.add_argument("--validate-config", action="store_true",
                        help="Validera konfigurationen och avsluta")
    args = parser.parse_args()
    v = not args.quiet

    # --validate-config: validera och avsluta
    if args.validate_config:
        errors = _validate_config()
        if errors:
            print("❌ Konfigurationsfel:")
            for err in errors:
                print(f"   • {err}")
            sys.exit(1)
        else:
            print("✅ Konfigurationen är giltig")
            sys.exit(0)

    tickers = [t.strip().upper() for t in args.tickers.split(",")] \
              if args.tickers else config.UNIVERSE

    print("🔍 MARKETSCAN"); print("="*50)
    print(f"Universum:  {len(tickers)} aktier")
    print(f"Cache:      {config.CACHE_HOURS}h\n")

    # 1. Marknadsregim
    print("🌍 Marknadsregim...")
    regime_info = macro_regime.detect_regime()
    if regime_info:
        r = regime_info.get("regime","OSÄKER"); c = regime_info.get("confidence",0)*100
        print(f"   → {r} ({c:.0f}% konfidens)")
        if r == "BJÖRN": print("   ⚠  Björnmarknad aktiv")

    # 1.6. Benchmark-data (OMXS30 + SPY)
    print("📊 Hämtar benchmark...")
    try:
        benchmarks = data_fetcher.fetch_benchmark_performance()
        omx = benchmarks.get("OMXS30", {})
        if omx:
            print(f"   OMXS30: {omx.get('change_1d',0):+.1f}% idag, {omx.get('change_ytd',0):+.1f}% YTD")
    except Exception:
        benchmarks = {}

    # 2. Datahämtning
    print("\n📥 Hämtar data...")
    df = data_fetcher.fetch_universe_data(tickers, verbose=v)
    if df.empty: print("❌ Ingen data."); sys.exit(1)
    print(f"✓ {len(df)}/{len(tickers)} aktier")

    # 3. Sentiment
    sentiment_scores = {}
    if config.FINNHUB_API_KEY:
        print("\n📰 Sentiment (Finnhub)...")
        sentiment_scores = sentiment_module.fetch_sentiment_batch(
            list(df["ticker"]), config.FINNHUB_API_KEY, verbose=v)
        print(f"✓ {len(sentiment_scores)} aktier")
    else:
        print("\nℹ  Ingen Finnhub-nyckel → sentiment neutralt")

    # 4. Scoring
    print("\n🧮 Faktorscores...")
    
    # Hämta ut det faktiska regim-ordet (t.ex. "TJUR") från Steg 1-datan
    current_regime = regime_info.get("regime", "OSÄKER") if regime_info else "OSÄKER"
    
    # Klistra in sentiment_scores i df innan vi scorar
    if sentiment_scores:
        df["sentiment_raw"] = df["ticker"].map(sentiment_scores)
    else:
        df["sentiment_raw"] = None

    # Spara rådata (efter fetch, INNAN scoring) för strike-systemets diagnostik.
    # Måste vara df (från data_fetcher), inte scored – annars ges strikes
    # om scoring tappar en ticker av interna skäl.
    df_raw = df.copy()

    # Anropa scoringen
    scored = scoring.score_universe(df, regime=current_regime)
    
    # Räkna hur många vi har innan vi rensar bort de med dålig data
    pre_filter_count = len(scored)
    
    # FILTRERING: Behåll bara de som har tillräckligt med data
    scored = scored[scored["data_quality"] >= config.MIN_DATA_QUALITY]
    
    # --- 🧹 STRIKE-SYSTEM & AI DIAGNOS ---
    # Strikes triggas BARA för tickers som inte ens kunde hämtas (tomma rader i df_raw),
    # INTE för tickers som filtrerades bort av data_quality-tröskeln.
    survived_list = scored["ticker"].tolist()

    # Hitta tickers som saknas helt i df_raw (verkliga hämtningsfel)
    fetched_set    = set(df_raw["ticker"].str.upper()) if not df_raw.empty else set()
    fetch_failed   = [t for t in tickers if t.upper() not in fetched_set]

    warnings, removed = filters.update_ticker_health(
        tickers, survived_list, df_raw, fetch_failed=fetch_failed
    )
    
    # Skriv ut status i terminalen
    diff = pre_filter_count - len(scored)
    if diff > 0:
        print(f"   Filtrerade {diff} aktier p.g.a. låg datakvalitet")
    
    if warnings:
        print(f"   ⚠️ {len(warnings)} aktier fick sin andra strike")
    if removed:
        print(f"   ❌ {len(removed)} aktier flyttades till svarta listan")
        
    print(f"   ✓ {len(scored)} aktier godkända för analys")
    # 4.5. Sektor-ETF momentum (justera scores baserat på sektortrend)
    print("\n📈 Sektormomtentum...")
    sector_mom = sector_momentum.fetch_sector_momentum(verbose=v)
    scored = sector_momentum.apply_sector_momentum(scored, sector_mom, verbose=v)

    # 4.6. Piotroski F-Score (finansiell hälsa)
    print("🏥 Piotroski F-Score...")
    scored = piotroski.add_piotroski_to_universe(scored, verbose=v)

    # 5. Extra data
    if not args.quick:
        print("\n🔬 Extra data...")
        extra_df = extra_data.fetch_extra_data_batch(
            list(scored["ticker"]), finnhub_key=config.FINNHUB_API_KEY, verbose=v)
        scored = scored.merge(extra_df, on="ticker", how="left")
        if "extra_composite" in scored.columns:
            adj = (scored["extra_composite"].fillna(0.5) - 0.5) * 10
            scored["score_total"] = (scored["score_total"] + adj).clip(0, 100)
            scored["rank"] = scored["score_total"].rank(ascending=False,method="min").astype("Int64")
    else:
        print("\nℹ  --quick: hoppar extra data")

    # 6. Filter
    print("\n🔍 Filter (trend / konfidens / entry / kvalitet)...")
    scored = filters.apply_all_filters(scored, verbose=v)
    if regime_info and regime_info.get("regime") == "BJÖRN":
        thresh = macro_regime.adjusted_thresholds("BJÖRN")
        min_s  = thresh.get("min_score_for_buy", 75)
        if "entry_signal" in scored.columns:
            mask = (scored["score_total"] < min_s) & (scored["entry_signal"] == "STARK")
            scored.loc[mask, "entry_signal"] = "OK"
            if v and mask.sum(): print(f"   Björn: {mask.sum()} STARK→OK (score<{min_s})")

    # 7. Sektorrelativ ranking
    print("\n🏭 Sektorrelativ ranking...")
    if "score_total" in scored.columns:
        scored = scored.dropna(subset=["score_total"])
    
    scored         = sectors.calc_sector_scores(scored)
    sector_summary = sectors.get_sector_summary(scored)

    # 8. Relativ styrka mot sektor-ETFer
    print("💪 Relativ styrka vs sektor-ETFer...")
    scored = portfolio_analysis.add_relative_strength(scored)

    # 9. Delta-tracking
    print("\n🔄 Delta-tracking...")
    prev = delta_tracker.load_previous_snapshot()
    if prev is not None:
        snap_date = prev["_snapshot_date"].iloc[0] if "_snapshot_date" in prev.columns else "?"
        print(f"   Föregående scan: {snap_date}")
        scored  = delta_tracker.calc_deltas(scored, prev)
        changed = (scored["delta_flag"].fillna("") != "").sum()
        print(f"   ✓ {changed} aktier med förändringar")
    else:
        print("   ℹ Första körningen – deltas nästa vecka")
        scored = delta_tracker.calc_deltas(scored, None)
    snap = delta_tracker.save_snapshot(scored)
    if v: print(f"   💾 Snapshot: {snap}")

    # 10. Portfölj
    print("\n💼 Portföljanalys...")
    holdings = portfolio.load_holdings()
    if not holdings.empty:
        print(f"   {len(holdings)} positioner")
        analysis = portfolio.analyze_portfolio(holdings, scored)
        summary  = portfolio.portfolio_summary(analysis)
    else:
        analysis = pd.DataFrame(); summary = {}

    # 11. Earnings-kalender
    print("\n📅 Earnings-kalender...")
    watch   = list(set(list(scored.head(config.TOP_N_RECOMMENDATIONS)["ticker"]) +
                       (list(holdings["ticker"]) if not holdings.empty else [])))
    portfolio_cal = earnings_calendar.upcoming_in_portfolio(holdings, scored, days_ahead=30)
    top_cal       = earnings_calendar.upcoming_in_portfolio(
        pd.DataFrame({"ticker": watch}), scored, days_ahead=14
    ) if watch else pd.DataFrame()
    earn_df = {"portfolio": portfolio_cal, "top": top_cal}
    n_earn = len(portfolio_cal) + len(top_cal)
    if n_earn: print(f"   ✓ {n_earn} kommande rapporter")

    # 11.5 Nyheter (marknad + bolagsspecifikt + Nasdaq Nordic)
    print("\n📰 Hämtar nyheter för veckorapporten...")
    global_news     = []
    swedish_news    = []
    news_by_ticker  = {}
    top_news        = {}   # Nyheter för topp-10 rankade (nytt!)
    nasdaq_news     = []
    finnhub_key     = config.FINNHUB_API_KEY
    watchlist_items = wl.load_watchlist()

    try:
        # Svenska RSS
        swedish_news = news_fetcher.fetch_swedish_market_news(max_articles=5)
        if swedish_news and v:
            print(f"   ✓ {len(swedish_news)} svenska börsnyheter")

        # Nasdaq Nordic – regulatoriska meddelanden (hel vecka)
        nasdaq_news = news_fetcher.fetch_nasdaq_nordic_news(market="SSE", max_items=10, hours_back=168)
        if nasdaq_news and v:
            print(f"   ✓ {len(nasdaq_news)} Nasdaq Nordic-meddelanden")

        # Finnhub portfölj/bevakningslista-nyheter
        if finnhub_key:
            global_news = news_fetcher.fetch_global_market_news(finnhub_key, max_articles=5)
            if global_news and v:
                print(f"   ✓ {len(global_news)} globala marknadsnyheter")
            finnhub_tickers = (
                list(holdings["ticker"].str.upper() if not holdings.empty else []) +
                [i["ticker"] for i in watchlist_items]
            )
            if finnhub_tickers:
                news_by_ticker = news_fetcher.fetch_news_batch(
                    finnhub_tickers, finnhub_key, days=3
                )
                if news_by_ticker and v:
                    print(f"   ✓ Bolagsnyheter (Finnhub): {len(news_by_ticker)} aktier")
        else:
            if v: print("   ℹ FINNHUB_API_KEY ej satt – Finnhub global/portfölj hoppas över")

        # Google News för top-10 rankade aktier (det centrala nya bidraget)
        top_tickers  = list(scored.head(10)["ticker"]) if not scored.empty else []
        top_name_map = {}
        if not scored.empty and "name" in scored.columns:
            for _, r in scored.head(10).iterrows():
                n = str(r.get("name", "") or "").strip()
                if n:
                    top_name_map[r["ticker"]] = n

        # Komplettera portfölj/bevakningslista med Google News (bättre svensk täckning)
        port_wl_name_map = {}
        if not holdings.empty and "name" in holdings.columns:
            for _, row in holdings.iterrows():
                t = str(row["ticker"]).upper()
                n = str(row.get("name", "") or "").strip()
                if n:
                    port_wl_name_map[t] = n
        for item in watchlist_items:
            t = item["ticker"]
            n = item.get("name", "")
            if n:
                port_wl_name_map[t] = n

        all_google_map = {**top_name_map, **port_wl_name_map}
        if all_google_map:
            print(f"   🔍 Google News för {len(all_google_map)} bolag (topp-10 + portfölj)...")
            google_batch = news_fetcher.fetch_company_news_google_batch(
                all_google_map, max_items=3, delay=1.3
            )
            # Separera top-10 nyheter från portfölj/bevakningslista
            for ticker, g_articles in google_batch.items():
                if ticker in top_name_map:
                    top_news[ticker] = g_articles
                # Slå ihop med Finnhub-nyheter för portfölj/wl
                existing = news_by_ticker.get(ticker, [])
                merged   = news_fetcher._merge_news(existing, g_articles, max_total=4)
                if merged:
                    news_by_ticker[ticker] = merged
            if google_batch and v:
                print(f"   ✓ Google News: {len(google_batch)} bolag "
                      f"({len(top_news)} top-rankat, {len(news_by_ticker)} total)")

    except Exception as e:
        print(f"   ⚠ Nyheter misslyckades: {e}")

    # 12. Rapport
    print("\n📝 Genererar rapport...")

    try:
        report = build_report(
            scored         = scored,
            analysis       = analysis,
            summary        = summary,
            sector_df      = sector_summary,
            regime_info    = regime_info,
            earnings_df    = earn_df,
            holdings       = holdings,
            benchmarks     = benchmarks,
            sector_mom     = sector_mom,
            warnings       = warnings,
            removed        = removed,
            global_news    = global_news,
            swedish_news   = swedish_news,
            news_by_ticker = news_by_ticker,
            top_news       = top_news,
            nasdaq_news    = nasdaq_news,
        )
    except Exception as e:
        import traceback
        print(f"\n❌ CRASH i build_report: {e}")
        traceback.print_exc()
        raise

    # --- VIKTIGT: Spara rapporten till fil ---
    Path(config.REPORT_DIR).mkdir(parents=True, exist_ok=True)
    date_str    = datetime.now().strftime("%Y-%m-%d")
    report_path = Path(config.REPORT_DIR) / config.REPORT_FILENAME_PATTERN.format(date=date_str)
    csv_path    = Path(config.REPORT_DIR) / f"scored_universe_{date_str}.csv"

    report_path.write_text(report, encoding="utf-8")
    scored.to_csv(csv_path, index=False)

    # Skicka veckorapport via email
    if not args.quiet and alerts_module.email_configured():
        print("\n✉ Skickar veckorapport via email...")
        alerts_module.send_weekly_report(
            report_md  = report,
            n_scanned  = len(scored),
            n_top      = config.TOP_N_RECOMMENDATIONS,
        )
    elif not args.quiet:
        print("\nℹ Email ej konfigurerat – lägg till EMAIL_SENDER/EMAIL_PASSWORD i config.py")

    print(f"\n{'='*50}")
    print(f"✅ KLART!")
    print(f"   Rapport: {report_path}")
    print(f"   Data:    {csv_path}")
    print(f"\n👉 Öppna rapporten och klistra in i Claude Pro\n")

    # 12.5 Paper trading – registrera veckans rekommendationer
    print("\n📄 Paper trading...")
    paper_trading.record_weekly_picks(scored, top_n=10, verbose=v)
    paper_trading.update_prices(close_after_weeks=4, verbose=False)

    # 12.9 Re-sortera scored efter alla score-justeringar
    # (sector_momentum, piotroski, extra_data ändrar alla score_total)
    if "score_total" in scored.columns:
        scored = scored.sort_values("score_total", ascending=False).reset_index(drop=True)
        scored["rank"] = range(1, len(scored) + 1)

    # 13. Topp 10 i terminalen (Snyggt avslut)
    print("🏆 TOPP 10:"); print("-" * 65)
    cols = [c for c in ["rank", "ticker", "name", "score_total", "entry_signal", "rs_label"] if c in scored.columns]
    top10 = scored.head(10)[cols].copy()
    if "score_total" in top10.columns: 
        top10["score_total"] = top10["score_total"].round(1)
    if "name" in top10.columns: 
        top10["name"] = top10["name"].astype(str).str[:25]
    print(top10.to_string(index=False))

if __name__ == "__main__":
    main()
