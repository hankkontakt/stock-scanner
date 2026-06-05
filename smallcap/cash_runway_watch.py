"""
cash_runway_watch.py - Övervakning av kassabana (Cash Runway).
=============================================================

Identifierar bolag med negativt kassaflöde och beräknar exakt
hur många månader kassan räcker. Varnar när runway < 12 månader
och flaggar akut risk (< 6 månader).

Användning:
    from smallcap.cash_runway_watch import analyze_cash_runway
    warnings = analyze_cash_runway(scored_df, verbose=True)
"""

import numpy as np
import pandas as pd
from datetime import datetime
from typing import Optional


# ── Trösklar ──────────────────────────────────────────────────────────────────
WARNING_MONTHS  = 12   # < 12 månader = gul varning
CRITICAL_MONTHS = 6    # < 6 månader = röd varning (akut emissionsrisk)
MIN_CASH_SEK    = 1_000_000  # Kassor under 1 MSEK ignoreras (för små för att vara meningsfulla)
SEK_USD_APPROX  = 0.094      # 1 SEK ≈ 0.094 USD (yfinance returnerar USD)


def calc_runway_months(row: pd.Series) -> Optional[float]:
    """
    Beräknar kassabana i månader för ett enskilt bolag.
    
    Formel: runway = total_cash / (|operating_cashflow| / 12)
    
    Returnerar:
        float: antal månader kassan räcker
        None: om bolaget har positivt OCF eller saknar data
        float("inf"): om bolaget har kassa men inget OCF-negativt
    """
    cash = row.get("total_cash", 0)
    ocf  = row.get("operating_cashflow", 0)
    fcf  = row.get("free_cash_flow", 0)
    
    # Konvertera till numeriska
    try:
        cash = float(cash) if cash is not None and not (isinstance(cash, float) and np.isnan(cash)) else 0
        ocf  = float(ocf)  if ocf  is not None and not (isinstance(ocf, float) and np.isnan(ocf)) else 0
        fcf  = float(fcf)  if fcf  is not None and not (isinstance(fcf, float) and np.isnan(fcf)) else 0
    except (TypeError, ValueError):
        return None
    
    # Använd OCF primärt, FCF som fallback (FCF inkluderar capex)
    burn_rate = ocf
    burn_source = "OCF"
    
    if burn_rate >= 0:
        # Positivt OCF - använd FCF istället om den är negativ
        if fcf < 0:
            burn_rate = fcf
            burn_source = "FCF"
        else:
            # Positivt både OCF och FCF = självfinansierande
            return None
    
    if cash < MIN_CASH_SEK:
        return 0 if burn_rate < 0 else None
    
    # Runway i månader
    monthly_burn = abs(burn_rate) / 12
    if monthly_burn <= 0:
        return None
    
    return cash / monthly_burn


def analyze_cash_runway(
    df: pd.DataFrame,
    verbose: bool = True,
    include_healthy: bool = False,
) -> pd.DataFrame:
    """
    Analyserar kassabana för alla bolag i DataFrame.
    
    Args:
        df: DataFrame med kolumnerna total_cash, operating_cashflow, free_cash_flow, ticker
        verbose: Skriv ut sammanfattning
        include_healthy: Inkludera även bolag med OK kassabana i resultatet
    
    Returns:
        DataFrame med kolumner: ticker, name, cash, ocf, fcf, runway_months,
                                runway_status, burn_rate_monthly
    """
    rows = []
    
    for _, row in df.iterrows():
        ticker = row.get("ticker", "?")
        runway = calc_runway_months(row)
        
        if runway is None:
            continue  # Positivt kassaflöde eller saknar data
        
        cash = row.get("total_cash", 0)
        ocf  = row.get("operating_cashflow", 0)
        fcf  = row.get("free_cash_flow", 0)
        mkcap = row.get("market_cap", 0)
        name = row.get("name", "")
        
        try:
            cash = float(cash) if not (isinstance(cash, float) and np.isnan(cash)) else 0
            mkcap_sek = float(mkcap) / SEK_USD_APPROX if not (isinstance(mkcap, float) and np.isnan(mkcap)) and float(mkcap) > 0 else 0
        except (TypeError, ValueError):
            mkcap_sek = 0
        
        # Status
        if runway < CRITICAL_MONTHS:
            status = "🔴 KRITISK"
        elif runway < WARNING_MONTHS:
            status = "🟡 VARNING"
        else:
            status = "🟢 OK"
        
        if not include_healthy and status == "🟢 OK":
            continue
        
        monthly_burn = abs(ocf) / 12 if ocf < 0 else (abs(fcf) / 12 if fcf < 0 else 0)
        
        rows.append({
            "ticker": ticker,
            "name": str(name)[:40] if name else "",
            "cash_msek": round(cash / 1_000_000, 1) if cash > 0 else 0,
            "ocf_msek": round(ocf / 1_000_000, 1),
            "fcf_msek": round(fcf / 1_000_000, 1),
            "monthly_burn_msek": round(monthly_burn / 1_000_000, 1),
            "runway_months": round(runway, 1),
            "runway_status": status,
            "mkcap_msek": round(mkcap_sek / 1_000_000, 0) if mkcap_sek > 0 else 0,
        })
    
    result = pd.DataFrame(rows)
    if result.empty:
        if verbose:
            print("  ✅ Cash Runway: alla bolag har positivt kassaflöde")
        return result
    
    # Sortera: kortast runway först
    result = result.sort_values("runway_months", ascending=True).reset_index(drop=True)
    
    if verbose:
        n_critical = (result["runway_status"] == "🔴 KRITISK").sum()
        n_warning = (result["runway_status"] == "🟡 VARNING").sum()
        n_ok = (result["runway_status"] == "🟢 OK").sum()
        print("\n  💰 Cash Runway Watch:")
        print(f"    🔴 Kritisk (< {CRITICAL_MONTHS}m): {n_critical} bolag")
        print(f"    🟡 Varning (< {WARNING_MONTHS}m): {n_warning} bolag")
        print(f"    🟢 OK (>= {WARNING_MONTHS}m): {n_ok} bolag")
        
        # Visa de mest kritiska
        critical = result[result["runway_status"] == "🔴 KRITISK"].head(5)
        if not critical.empty:
            print("\n    Mest akuta emissionsrisker:")
            for _, r in critical.iterrows():
                print(f"      {r['ticker']:12s} - {r['runway_months']:.0f}m kvar, "
                      f"bränner {r['monthly_burn_msek']:.1f} MSEK/mån")
    
    return result


def build_runway_section(runway_df: pd.DataFrame) -> str:
    """
    Bygger en markdown-sektion för rapporten om cash runway.
    
    Args:
        runway_df: DataFrame från analyze_cash_runway()
    
    Returns:
        Markdown-sträng
    """
    if runway_df.empty:
        return "## 💰 Cash Runway\n\n_Alla rankade bolag har positivt kassaflöde._\n"
    
    lines = ["## 💰 Cash Runway Watch\n",
             "Bolag med negativt kassaflöde - hur länge räcker kassan?\n",
             "| Ticker | Kassabana | Status | Bränner/mån | Kassa | OCF |",
             "|--------|----------:|:------:|-----------:|-----:|----:|"]
    
    for _, r in runway_df.iterrows():
        lines.append(
            f"| {r['ticker']} | **{r['runway_months']:.0f}m** | {r['runway_status']} | "
            f"{r['monthly_burn_msek']:.1f}M | {r['cash_msek']:.0f}M | {r['ocf_msek']:.0f}M |"
        )
    
    lines.append("")
    lines.append("_Kassabana = total_cash / (|operating_cashflow| / 12). "
                 "🔴 <6m = akut emissionsrisk, 🟡 <12m = bevaka._\n")
    
    return "\n".join(lines)