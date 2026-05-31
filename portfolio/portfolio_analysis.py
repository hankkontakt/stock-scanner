"""
portfolio_analysis.py
=====================
Avancerad portföljanalys:
1. Korrelationsmatris för dina innehav
2. Koncentrationsanalys (är du för exponerad mot en sektor/aktie?)
3. Diversifierings-förslag (vilka aktier från topp 50 sänker risken?)
4. Relativ styrka mot sektor och index
"""

import time
import pickle
import hashlib
from datetime import datetime, timedelta
from pathlib import Path

import yfinance as yf
import pandas as pd
import numpy as np

CACHE_DIR = "data/cache"
CORR_CACHE_H = 24
Path(CACHE_DIR).mkdir(parents=True, exist_ok=True)


def _cp(key):
    h = hashlib.md5(key.encode()).hexdigest()
    return Path(CACHE_DIR) / f"corr_{h}.pkl"

def _rc(key, max_h):
    p = _cp(key)
    if not p.exists(): return None
    if datetime.now() - datetime.fromtimestamp(p.stat().st_mtime) > timedelta(hours=max_h):
        return None
    try:
        with open(p, "rb") as f: return pickle.load(f)
    except: return None

def _wc(key, data):
    try:
        with open(_cp(key), "wb") as f: pickle.dump(data, f)
    except Exception: pass


# ══════════════════════════════════════════════════════════════
# KORRELATIONSANALYS
# ══════════════════════════════════════════════════════════════

def fetch_prices_for_correlation(tickers: list, period: str = "1y") -> pd.DataFrame:
    """Hämtar pris-historik för alla tickers (för korrelationsberäkning)."""
    cache_key = f"corr_prices:{','.join(sorted(tickers))}:{period}"
    cached    = _rc(cache_key, CORR_CACHE_H)
    if cached is not None:
        return cached

    try:
        data = yf.download(
            tickers, period=period, auto_adjust=True,
            progress=False, threads=True
        )
        if isinstance(data.columns, pd.MultiIndex):
            prices = data["Close"]
        else:
            prices = pd.DataFrame({tickers[0]: data["Close"]})

        prices = prices.dropna(axis=1, how="all")
        _wc(cache_key, prices)
        return prices
    except Exception as e:
        print(f"  ⚠ Korrelations-data misslyckades: {e}")
        return pd.DataFrame()


def calc_correlation_matrix(holdings: pd.DataFrame) -> pd.DataFrame:
    """Beräknar korrelationsmatris för dina innehav."""
    if holdings.empty:
        return pd.DataFrame()

    tickers = list(holdings["ticker"])
    if len(tickers) < 2:
        return pd.DataFrame()

    prices = fetch_prices_for_correlation(tickers)
    if prices.empty or len(prices.columns) < 2:
        return pd.DataFrame()

    returns = prices.pct_change().dropna()
    if len(returns) < 30:
        return pd.DataFrame()

    return returns.corr().round(2)


def analyze_concentration(holdings_analysis: pd.DataFrame,
                          scored: pd.DataFrame) -> dict:
    """
    Analyserar koncentrationsrisk i portföljen.

    Returnerar dict med:
        max_position_pct:   största positionens vikt
        top3_concentration: topp 3 positioners sammanlagda vikt
        sector_weights:     vikt per sektor
        max_sector_pct:     största sektorvikten
        n_sectors:          antal olika sektorer
        warnings:           lista med varningstexter
    """
    if holdings_analysis.empty:
        return {}

    total = holdings_analysis["market_value"].sum(skipna=True)
    if total <= 0:
        return {}

    h = holdings_analysis.copy()
    h["weight"] = h["market_value"] / total

    # Lägg på sektor från scored
    if not scored.empty and "sector" in scored.columns:
        h = h.merge(scored[["ticker", "sector"]], on="ticker", how="left", suffixes=("", "_s"))

    # Sektorvikter
    sector_weights = {}
    if "sector" in h.columns:
        sw = h.groupby("sector")["weight"].sum().sort_values(ascending=False)
        sector_weights = {s: round(w, 3) for s, w in sw.items() if pd.notna(s)}

    max_sector_pct = max(sector_weights.values()) if sector_weights else 0
    n_sectors      = len(sector_weights)

    warnings = []
    max_pos  = h["weight"].max()
    if max_pos > 0.30:
        warnings.append(f"⚠ En position utgör {max_pos*100:.0f}% av portföljen (rekommenderat <25%)")

    top3 = h.nlargest(3, "weight")["weight"].sum()
    if top3 > 0.60 and len(h) > 3:
        warnings.append(f"⚠ Topp 3 positioner utgör {top3*100:.0f}% av portföljen")

    if max_sector_pct > 0.50:
        top_sector = max(sector_weights, key=sector_weights.get)
        warnings.append(f"⚠ {max_sector_pct*100:.0f}% i {top_sector} – hög sektorrisk")

    if n_sectors < 3 and len(h) >= 4:
        warnings.append(f"⚠ Endast {n_sectors} sektorer – låg diversifiering")

    return {
        "max_position_pct":   round(max_pos, 3),
        "top3_concentration": round(top3, 3),
        "sector_weights":     sector_weights,
        "max_sector_pct":     round(max_sector_pct, 3),
        "n_sectors":          n_sectors,
        "warnings":           warnings,
    }


def suggest_diversifiers(holdings: pd.DataFrame, scored: pd.DataFrame,
                         top_n: int = 5) -> pd.DataFrame:
    """
    Föreslår aktier från topp 30 som har LÅG korrelation med ditt befintliga innehav.
    Dessa skulle sänka din portföljs totala risk om de läggs till.
    """
    if holdings.empty or scored.empty:
        return pd.DataFrame()

    holding_tickers = list(holdings["ticker"])
    top_candidates  = list(scored.head(30)["ticker"])

    # Filtrera bort de vi redan äger
    candidates = [t for t in top_candidates if t not in holding_tickers]
    if not candidates:
        return pd.DataFrame()

    # Hämta priser för alla
    all_tickers = holding_tickers + candidates
    prices      = fetch_prices_for_correlation(all_tickers, period="6mo")

    if prices.empty:
        return pd.DataFrame()

    returns = prices.pct_change().dropna()
    if len(returns) < 30:
        return pd.DataFrame()

    # För varje kandidat: snitt-korrelation mot innehav
    results = []
    for cand in candidates:
        if cand not in returns.columns:
            continue
        corrs = []
        for h in holding_tickers:
            if h in returns.columns and h != cand:
                c = returns[cand].corr(returns[h])
                if pd.notna(c):
                    corrs.append(c)
        if corrs:
            avg_corr = np.mean(corrs)
            cand_info = scored[scored["ticker"] == cand].iloc[0]
            results.append({
                "ticker":        cand,
                "name":          cand_info.get("name", ""),
                "score":         cand_info.get("score_total", 0),
                "sector":        cand_info.get("sector", ""),
                "avg_corr":      round(avg_corr, 2),
                "diversify_score": round((1 - avg_corr) * 50 + cand_info.get("score_total", 0) * 0.5, 1),
            })

    if not results:
        return pd.DataFrame()

    df = pd.DataFrame(results).sort_values("diversify_score", ascending=False)
    return df.head(top_n)


# ══════════════════════════════════════════════════════════════
# RELATIV STYRKA
# ══════════════════════════════════════════════════════════════

# Sektor → ETF-mappning (för att jämföra aktiens avkastning mot sektor)
SECTOR_ETFS = {
    "Technology":             "XLK",
    "Healthcare":             "XLV",
    "Financial Services":     "XLF",
    "Consumer Cyclical":      "XLY",
    "Consumer Defensive":     "XLP",
    "Energy":                 "XLE",
    "Industrials":            "XLI",
    "Communication Services": "XLC",
    "Basic Materials":        "XLB",
    "Real Estate":            "XLRE",
    "Utilities":              "XLU",
}


def fetch_sector_etf_return(etf: str, period: str = "3mo") -> float | None:
    """Hämtar avkastning för en sektor-ETF."""
    cache_key = f"sector_ret:{etf}:{period}"
    cached    = _rc(cache_key, 12)
    if cached is not None:
        return cached

    try:
        time.sleep(0.3)
        hist = yf.Ticker(etf).history(period=period)
        if hist.empty or len(hist) < 2:
            _wc(cache_key, None)
            return None
        ret = float(hist["Close"].iloc[-1] / hist["Close"].iloc[0] - 1)
        _wc(cache_key, ret)
        return ret
    except Exception:
        return None


def add_relative_strength(scored: pd.DataFrame) -> pd.DataFrame:
    """
    Lägger till relativ styrka mot sektor + index.

    Nya kolumner:
        sector_return_3m:  sektorns 3-mån avkastning
        relative_strength: aktiens 3-mån return / sektorns 3-mån return
        rs_label:          STARK / NORMAL / SVAG
    """
    df = scored.copy()
    df["sector_return_3m"]  = None
    df["relative_strength"] = None

    if "return_3m" not in df.columns or "sector" not in df.columns:
        df["rs_label"] = "—"
        return df

    # Cacha sektor-avkastningar
    sector_returns = {}
    for sector, etf in SECTOR_ETFS.items():
        if (df["sector"] == sector).any():
            r = fetch_sector_etf_return(etf, "3mo")
            sector_returns[sector] = r

    # Beräkna relativ styrka per aktie
    for idx, row in df.iterrows():
        sec    = row.get("sector")
        ret_3m = row.get("return_3m")
        if pd.isna(ret_3m) or sec not in sector_returns:
            continue
        sec_ret = sector_returns[sec]
        if sec_ret is None:
            continue
        df.at[idx, "sector_return_3m"] = sec_ret
        # Relativ styrka = aktien minus sektorn
        df.at[idx, "relative_strength"] = round(float(ret_3m) - float(sec_ret), 3)

    # Label
    def lbl(r):
        if r is None or pd.isna(r): return "—"
        if r > 0.05:    return "🟢 STARK"
        if r < -0.05:   return "🔴 SVAG"
        return "⚪ NORMAL"

    df["rs_label"] = df["relative_strength"].apply(lbl)
    return df


# ══════════════════════════════════════════════════════════════
# RAPPORT-SEKTIONER
# ══════════════════════════════════════════════════════════════

def build_portfolio_analysis_section(holdings_analysis: pd.DataFrame,
                                     scored: pd.DataFrame) -> str:
    """Markdown med korrelation, koncentration, diversifierare."""
    if holdings_analysis.empty:
        return ""

    lines = ["\n## 🎯 Portföljanalys – risk & diversifiering\n"]

    # Koncentration
    conc = analyze_concentration(holdings_analysis, scored)
    if conc:
        lines.append("### Koncentrationsrisk\n")
        lines.append(f"- **Största position:** {conc['max_position_pct']*100:.0f}% av portföljen")
        lines.append(f"- **Topp 3 positioner:** {conc['top3_concentration']*100:.0f}% av portföljen")
        lines.append(f"- **Antal sektorer:** {conc['n_sectors']}")
        lines.append(f"- **Största sektor:** {conc['max_sector_pct']*100:.0f}%")

        if conc["warnings"]:
            lines.append("\n**Varningar:**")
            for w in conc["warnings"]:
                lines.append(f"- {w}")

        if conc["sector_weights"]:
            lines.append("\n**Sektor-fördelning:**")
            for sec, w in list(conc["sector_weights"].items())[:6]:
                if pd.notna(sec) and sec != "Unknown":
                    bar = "█" * int(w * 30)
                    lines.append(f"- {sec}: {w*100:.0f}% `{bar}`")
        lines.append("")

    # Korrelationsmatris (om >= 2 innehav)
    if len(holdings_analysis) >= 2:
        holdings_simple = holdings_analysis[["ticker"]].copy()
        corr = calc_correlation_matrix(holdings_simple)
        if not corr.empty:
            lines.append("### Korrelationsmatris\n")
            lines.append("_Värden 0-1: högre = mer samvarierande. Korrelation > 0.7 = positionerna rör sig liknande._\n")

            # Bygg markdown-tabell
            lines.append("|  | " + " | ".join(f"`{t}`" for t in corr.columns) + " |")
            lines.append("|" + "---|" * (len(corr.columns) + 1))
            for ticker in corr.index:
                row_vals = []
                for col in corr.columns:
                    val = corr.loc[ticker, col]
                    if ticker == col:
                        row_vals.append("**1.00**")
                    elif pd.isna(val):
                        row_vals.append("—")
                    elif val > 0.7:
                        row_vals.append(f"🔴 {val:.2f}")
                    elif val > 0.4:
                        row_vals.append(f"🟡 {val:.2f}")
                    else:
                        row_vals.append(f"🟢 {val:.2f}")
                lines.append(f"| `{ticker}` | " + " | ".join(row_vals) + " |")
            lines.append("")

    # Diversifierings-förslag
    holdings_simple = holdings_analysis[["ticker"]].copy()
    diversifiers = suggest_diversifiers(holdings_simple, scored, top_n=5)
    if not diversifiers.empty:
        lines.append("### 💡 Diversifierings-förslag\n")
        lines.append("_Aktier från topp 30 med låg korrelation till din portfölj_\n")
        lines.append("| Ticker | Bolag | Sektor | Score | Korr. | Div-poäng |")
        lines.append("|--------|-------|--------|-------|-------|-----------|")
        for _, row in diversifiers.iterrows():
            lines.append(
                f"| `{row['ticker']}` | "
                f"{str(row['name'])[:25]} | "
                f"{str(row['sector'])[:15]} | "
                f"{row['score']:.0f} | "
                f"{row['avg_corr']:.2f} | "
                f"**{row['diversify_score']:.0f}** |"
            )

    return "\n".join(lines)

def calc_risk_parity_weights(tickers: list) -> pd.DataFrame:
    """Räknar ut Inverse Volatility-viktning för en lista av aktier."""
    if not tickers:
        return pd.DataFrame()

    try:
        # Vi hämtar 6 månaders historik för att få ett stabilt volatilitetsmått
        data = yf.download(tickers, period="6mo", interval="1d", progress=False)["Close"]
        
        if len(tickers) == 1:
            data = data.to_frame(name=tickers[0])

        # Beräkna annualiserad volatilitet
        returns = data.pct_change().dropna()
        volatility = returns.std() * np.sqrt(252)

        # Risk Parity: Vikt = (1/vol) / sum(1/vol)
        inv_vol = 1.0 / volatility
        weights = inv_vol / inv_vol.sum()

        df = pd.DataFrame({
            "ticker": volatility.index,
            "volatility_pct": volatility.values * 100,
            "weight_pct": weights.values * 100
        }).sort_values("weight_pct", ascending=False)
        
        return df
    except Exception as e:
        print(f"  ⚠ Kunde inte beräkna Risk Parity: {e}")
        return pd.DataFrame()

def _section_risk_parity(scored_df: pd.DataFrame) -> str:
    """Skapar markdown-tabellen för rapporten."""
    # Vi tar de 10 bäst rankade aktierna som har en köpsignal
    top_candidates = scored_df.head(10)["ticker"].tolist()
    rp_df = calc_risk_parity_weights(top_candidates)
    
    if rp_df.empty:
        return ""

    lines = ["\n## ⚖️ Risk Parity (Positionsstorlek)\n"]
    lines.append("_Hur du bör fördela 100 000 kr om du köper Topp 10 (baserat på volatilitet)._\n")
    lines.append("| Ticker | Volatilitet (Årlig) | Föreslagen Vikt | Belopp (vid 100k) |")
    lines.append("|--------|---------------------|-----------------|-------------------|")
    
    for _, row in rp_df.iterrows():
        vol = row['volatility_pct']
        risk_color = "🟢" if vol < 25 else "🟡" if vol < 40 else "🔴"
        lines.append(
            f"| `{row['ticker']}` | {vol:.1f}% {risk_color} | "
            f"**{row['weight_pct']:.1f}%** | {1000 * row['weight_pct']:,.0f} kr |"
        )
    return "\n".join(lines) + "\n"