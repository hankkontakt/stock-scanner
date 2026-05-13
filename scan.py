"""
scan.py – Huvudscript. Kör varje söndag: python scan.py
"""
import warnings
warnings.filterwarnings("ignore")  # <--- MÅSTE LIGGA HÄR UPPE!

import argparse, sys, os, time, threading
from datetime import datetime
from pathlib import Path
import pandas as pd

import config, data_fetcher, scoring, filters, sectors
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
        sec_stocks = scored[scored['sector'] == sec_name].head(5)
        
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
    

    
def _section_top_n(scored, n):
    # --- NY SEKTORTAK-LOGIK ---
    top_list = []
    sector_counts = {}
    
    for _, r in scored.iterrows():
        sec = r.get("sector", "Övrigt")
        if pd.isna(sec): 
            sec = "Övrigt"
            
        # Lägg bara till aktien om vi har färre än 5 från denna sektor
        if sector_counts.get(sec, 0) < 5:
            top_list.append(r)
            sector_counts[sec] = sector_counts.get(sec, 0) + 1
            
        if len(top_list) >= n:
            break
            
    top = pd.DataFrame(top_list)
    # --------------------------

    lines = [f"## 🏆 Topp {n} aktier (Max 5 per sektor)\n"]
    lines.append("| Rank | Ticker | Bolag | Score | Entry | Konf | Trend | RS | Insider | EPS | Δ |")
    lines.append("|------|--------|-------|-------|-------|------|-------|----|---------|-----|---|")
    ei = {"STARK":"🟢","OK":"🔵","VÄNTA":"🟡","EJ AKTUELL":"🔴"}
    for _, r in top.iterrows():
        entry = r.get("entry_signal","—"); conf = r.get("confidence_label","—")
        trend = "✅" if not r.get("trend_capped",False) else "⚠️"
        flag  = r.get("delta_flag","") or ""; rs = r.get("rs_label","—")
        ins = r.get("insider_signal"); eps = r.get("earnings_signal")
        ins_s = ("🟢" if ins>0.65 else "🔴" if ins<0.35 else "⚪") if pd.notna(ins or float("nan")) else "—"
        eps_s = ("🟢" if eps>0.65 else "🔴" if eps<0.35 else "⚪") if pd.notna(eps or float("nan")) else "—"
        lines.append(f"| {r['rank']} | `{r['ticker']}` | {str(r.get('name',''))[:22]} | "
                     f"**{r['score_total']:.0f}** | {ei.get(entry,'—')} {entry} | "
                     f"{conf} | {trend} | {rs} | {ins_s} | {eps_s} | {flag[:35]} |")
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
        if summary.get("average_score"):
            lines.append(f"- **Snittscore:** {summary['average_score']:.0f}/100")
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
    return ("\n## 🤖 Klistra in i Claude Pro\n```\n"
            "Här är min veckovisa scan. Sök senaste 30 dagars nyheter för topp 20\n"
            "och mina innehav. Filtrera bort röda flaggor.\n\n"
            "Ge mig:\n"
            "1. Topp 10 köpkandidater med motivering\n"
            "2. Bekräfta/överrid rekommendationerna för mina innehav\n"
            "3. Varningssignaler jag missat\n"
            "4. Är jag för exponerad mot en sektor?\n"
            "5. Vad säger makrobilden just nu?\n```")
            
            
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
        lines.append(", ".join([f"`{w}`" for w in warnings]))
        lines.append("")
    
    return "\n".join(lines) + "\n"

def build_report(scored, analysis, summary, sector_df, regime_info, earnings_df, holdings, warnings=None, removed=None, sector_mom=None, benchmarks=None):
    fw   = config.FACTOR_WEIGHTS
    bm   = benchmarks or {}
    date = datetime.now().strftime("%Y-%m-%d %H:%M")
    stark  = (scored.get("entry_signal",pd.Series())=="STARK").sum() if "entry_signal" in scored.columns else 0
    high_c = (scored.get("confidence_label",pd.Series())=="HÖG").sum() if "confidence_label" in scored.columns else 0
    in_up  = (~scored.get("trend_capped",pd.Series(True))).sum() if "trend_capped" in scored.columns else 0

    parts = [
        "# 📊 Veckovis Aktiescan",
        f"**Datum:** {date}  \n**Scannade:** {len(scored)} aktier",
        f"**Vikter:** Value {fw['value']*100:.0f}% · Quality {fw['quality']*100:.0f}% · "
        f"Momentum {fw['momentum']*100:.0f}% · Growth {fw['growth']*100:.0f}% · "
        f"Risk {fw['risk']*100:.0f}% · Sentiment {fw.get('sentiment',0)*100:.0f}%",
        f"**Signaler:** {in_up} upptrend · {high_c} HÖG konfidens · {stark} STARK entry",
        "\n---\n",
    ]

    def _try(label, fn):
        try:
            result = fn()
            if result:
                parts.append(result)
        except Exception as e:
            import traceback
            print(f"  ⚠ Sektion '{label}' misslyckades: {e}")
            traceback.print_exc()

    # 1. Marknadsregim
    if regime_info:
        _try("Marknadsregim", lambda: macro_regime.build_regime_section(regime_info))

    # Benchmark
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

    # 2. Topp-N
    _try("Topp-N", lambda: _section_top_n(scored, config.TOP_N_RECOMMENDATIONS))

    # 2.5. Piotroski
    _try("Piotroski", lambda: piotroski.build_piotroski_section(scored))

    # 3. Risk Parity
    _try("Risk Parity", lambda: portfolio_analysis._section_risk_parity(scored))

    # 3.5. Sektor-ETF momentum
    if sector_mom:
        _try("Sektor-momentum", lambda: sector_momentum.build_sector_momentum_section(sector_mom))

    # 4. Sektorer
    _try("Sektorer", lambda: _section_sectors(sector_df))

    # 5. Delta
    _try("Delta", lambda: delta_tracker.build_delta_report_section(scored))

    # 6. Earnings
    def _earn():
        pc = earnings_df.get("portfolio", pd.DataFrame()) if isinstance(earnings_df, dict) else earnings_df
        tc = earnings_df.get("top", pd.DataFrame()) if isinstance(earnings_df, dict) else pd.DataFrame()
        return earnings_calendar.build_earnings_section(pc, tc)
    _try("Earnings", _earn)

    # 7. Portfölj
    if not analysis.empty:
        _try("Portfölj", lambda: _section_portfolio(analysis, summary))
        _try("Portföljanalys", lambda: portfolio_analysis.build_portfolio_analysis_section(analysis, scored))

    # 8. Sektoranalys Topp 5
    _try("Sektoranalys Topp5", lambda: _section_sectors_top5(scored, sector_df))

    # 9. Systemunderhåll
    _try("Systemunderhåll", lambda: _section_cleanup(warnings, removed))

    # 9.5. Paper trading
    _try("Paper trading", lambda: paper_trading.build_paper_trading_section())

    # 10. Avslutning
    parts.append(_section_claude_prompt())
    parts.append("\n---\n*⚠ Inte finansiell rådgivning.*")
    
    return "\n".join(parts)


# ── Huvudpipeline ──────────────────────────────────────────────────────────────

def main():
    # Watchdog: force-exit if the entire scan hangs past 100 minutes.
    # Daemon thread dies with the process on normal exit; only fires on true hangs.
    def _watchdog():
        time.sleep(100 * 60)
        print("\n⏰ WATCHDOG: Scan exceeded 100 min — force-exiting to prevent GitHub hang.")
        os._exit(1)
    threading.Thread(target=_watchdog, daemon=True, name="ScanWatchdog").start()

    parser = argparse.ArgumentParser()
    parser.add_argument("--tickers", help="Komma-separerade tickers")
    parser.add_argument("--quick",   action="store_true", help="Hoppa över extra data")
    parser.add_argument("--quiet",   action="store_true", help="Minimal output")
    args = parser.parse_args()
    v = not args.quiet

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
        from daily_scan import fetch_benchmark_performance
        benchmarks = fetch_benchmark_performance()
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

    # Anropa scoringen
    scored = scoring.score_universe(df, regime=current_regime)
    
    # Spara en kopia av ALLA scorade aktier för Strike-systemets diagnostik
    df_raw = scored.copy()
    
    # Räkna hur många vi har innan vi rensar bort de med dålig data
    pre_filter_count = len(scored)
    
    # FILTRERING: Behåll bara de som har tillräckligt med data
    scored = scored[scored["data_quality"] >= config.MIN_DATA_QUALITY]
    
    # --- 🧹 STRIKE-SYSTEM & AI DIAGNOS ---
    # Vi jämför ursprungslistan (tickers) med de som faktiskt klarade sig (scored)
    survived_list = scored["ticker"].tolist()
    warnings, removed = filters.update_ticker_health(tickers, survived_list, df_raw)
    
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

    # 12. Rapport
    print("\n📝 Genererar rapport...")

    try:
        report = build_report(
            scored       = scored,
            analysis     = analysis,
            summary      = summary,
            sector_df    = sector_summary,
            regime_info  = regime_info,
            earnings_df  = earn_df,
            holdings     = holdings,
            benchmarks   = benchmarks,
            sector_mom   = sector_mom,
            warnings     = warnings,
            removed      = removed,
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
