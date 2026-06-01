"""
piotroski.py
============
Beräknar Piotroski F-Score för varje aktie.

Bakgrund:
  Joseph Piotroski (2000) visade att ett enkelt 9-punkts system baserat
  på bokföringssignaler kan identifiera "finansiellt starka" kontra
  "finansiellt svaga" värdebolag - med signifikant avkastningsskillnad.

  Akademiskt bland de mest robusta och replikerade anomalierna.

De 9 kriterierna (1 poäng vardera):

LÖNSAMHET (F1-F4):
  F1. ROA > 0          (nettoresultat / totala tillgångar är positivt)
  F2. ROA förbättrad   (ROA i år > ROA föregående år)
  F3. OCF > 0          (operativt kassaflöde positivt)
  F4. Accrual-kvalitet (OCF / totala tillgångar > ROA)

KAPITALSTRUKTUR (F5-F7):
  F5. Lägre skuldsättning   (D/E minskat jämfört med föregående år)
  F6. Bättre likviditet     (current ratio förbättrades)
  F7. Ingen ny utspädning   (shares outstanding ej ökat > 2%)

EFFEKTIVITET (F8-F9):
  F8. Bättre bruttomarginal (gross margin förbättrades)
  F9. Bättre omsättning     (asset turnover förbättrades)

Tolkning:
  0-3: Svag finansiell ställning
  4-6: Neutral
  7-9: Stark finansiell ställning (köpsignal)

Förbättringar i denna version:
  - Lagrar historiska snapshotvärden i cache (data/piotroski_snapshots/)
    för korrekta YoY-jämförelser (F2, F5, F6, F7, F8, F9)
  - Använder operating_cashflow från yfinance för F3 (inte bara FCF)
  - Använder sharesOutstanding för F7 (utspädningskontroll)
  - Fallar tillbaka till proxy-estimat om historisk data saknas
"""

import json
import time
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import numpy as np

# ── Cache för historiska fundamental-snapshots ──────────────────────────────
_PIOTROSKI_CACHE_DIR = Path(__file__).parent.parent / "data" / "piotroski_snapshots"
_PIOTROSKI_CACHE_DIR.mkdir(parents=True, exist_ok=True)
_SNAPSHOT_TTL_DAYS = 365  # Spara snapshots i 1 år (för YoY-jämförelser)


def _snapshot_key(ticker: str) -> str:
    """Returnerar ett MD5-hashat filnamn för tickerns snapshot-cache."""
    return hashlib.md5(ticker.encode()).hexdigest()[:16]


def _load_snapshot(ticker: str, date: datetime.date) -> Optional[dict]:
    """
    Laddar närmaste tidigare snapshot för en ticker.
    Hittar den senaste snapshot som är minst 180 dagar gammal.
    """
    # Leta efter alla snapshots för denna ticker
    prefix = _snapshot_key(ticker)
    snapshots = []
    for f in _PIOTROSKI_CACHE_DIR.glob(f"{prefix}_*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            snapshots.append(data)
        except Exception:
            continue

    if not snapshots:
        return None

    # Sortera efter datum, nyast först
    snapshots.sort(key=lambda x: x.get("_date", ""), reverse=True)

    # Hitta den senaste snapshot som är tillräckligt gammal för YoY-jämförelse
    for snap in snapshots:
        snap_date = datetime.strptime(snap["_date"], "%Y-%m-%d").date()
        age_days = (date - snap_date).days
        if 180 <= age_days <= 550:  # 6-18 månader gammal = föregående rapport
            return snap

    return None


def _save_snapshot(ticker: str, values: dict):
    """Sparar nuvarande fundamentala snapshot för framtida YoY-jämförelser."""
    key = _snapshot_key(ticker)
    date_str = datetime.now().strftime("%Y-%m-%d")
    path = _PIOTROSKI_CACHE_DIR / f"{key}_{date_str}.json"
    if path.exists():
        return  # Redan sparad idag
    payload = {"_date": date_str, "_ticker": ticker, **values}
    try:
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def calc_piotroski(row: pd.Series, ticker: str = "") -> dict:
    """
    Beräknar F-Score för en enskild aktie från ett metrics-dict.

    Indata (från data_fetcher.extract_metrics eller smallcap scanner):
      - roa, free_cash_flow, operating_cashflow,
        market_cap, price_to_book, total_debt, total_cash,
        debt_to_equity, current_ratio, gross_margin,
        operating_margin, revenue_growth, earnings_growth,
        sharesOutstanding (eller shares_outstanding),
        insider_pct

    Returnerar dict med:
      - f_score (0-9)
      - criteria (dict med varje kriteriums värde)
      - label (STARK/NEUTRAL/SVAG)
    """
    criteria = {}

    # ── Hämta nuvarande värden ───────────────────────────────────────────
    roa = row.get("roa")
    fcf = row.get("free_cash_flow")
    ocf = row.get("operating_cashflow") or fcf  # Fallback till FCF om OCF saknas
    mc = row.get("market_cap")
    pb = row.get("price_to_book")
    de = row.get("debt_to_equity")
    cr = row.get("current_ratio")
    gm = row.get("gross_margin")
    om = row.get("operating_margin")
    rg = row.get("revenue_growth")
    eg = row.get("earnings_growth")
    insider = row.get("insider_pct")
    shares = row.get("sharesOutstanding") or row.get("shares_outstanding")

    # Approximera totala tillgångar = market_cap / price_to_book (om tillgängligt)
    total_assets = None
    if pd.notna(mc) and pd.notna(pb) and pb > 0:
        total_assets = mc / pb

    # ── F1: ROA > 0 ──────────────────────────────────────────────────────
    criteria["F1_roa_positive"] = int(pd.notna(roa) and roa > 0)

    # ── F2: ROA förbättrad (jämför med historisk snapshot) ───────────────
    if pd.notna(roa) and ticker:
        prev = _load_snapshot(ticker, datetime.now().date())
        if prev and "roa" in prev and prev["roa"] is not None:
            criteria["F2_roa_improving"] = int(roa > prev["roa"])
        elif pd.notna(eg):
            # Fallback: använd earnings_growth > 0 (men lägre tillförlitlighet)
            criteria["F2_roa_improving"] = int(eg > 0)
        else:
            criteria["F2_roa_improving"] = 0
    elif pd.notna(eg):
        criteria["F2_roa_improving"] = int(eg > 0)
    else:
        criteria["F2_roa_improving"] = 0

    # ── F3: Operativt kassaflöde > 0 ────────────────────────────────────
    if pd.notna(ocf):
        criteria["F3_ocf_positive"] = int(ocf > 0)
    elif pd.notna(fcf):
        criteria["F3_ocf_positive"] = int(fcf > 0)
    else:
        criteria["F3_ocf_positive"] = 0

    # ── F4: Accrual-kvalitet (OCF/Assets > ROA) ─────────────────────────
    if total_assets and total_assets > 0 and pd.notna(ocf) and pd.notna(roa):
        ocf_ratio = ocf / total_assets
        criteria["F4_accrual_quality"] = int(ocf_ratio > roa)
    elif mc and mc > 0 and pd.notna(fcf) and pd.notna(roa):
        # Approximation: FCF / market_cap > ROA
        fcf_ratio = fcf / mc
        criteria["F4_accrual_quality"] = int(fcf_ratio > roa)
    else:
        criteria["F4_accrual_quality"] = 0

    # ── F5: Skuldsättning minskad (jämför med historisk snapshot) ───────
    if pd.notna(de) and ticker:
        prev = _load_snapshot(ticker, datetime.now().date())
        if prev and "debt_to_equity" in prev and prev["debt_to_equity"] is not None:
            criteria["F5_lower_leverage"] = int(de < prev["debt_to_equity"])
        else:
            # Fallback: nivåbaserat (D/E < 100 = OK)
            criteria["F5_lower_leverage"] = int(de < 100)
    elif pd.notna(de):
        criteria["F5_lower_leverage"] = int(de < 100)
    else:
        criteria["F5_lower_leverage"] = 0

    # ── F6: Bättre likviditet (jämför med historisk snapshot) ───────────
    if pd.notna(cr) and ticker:
        prev = _load_snapshot(ticker, datetime.now().date())
        if prev and "current_ratio" in prev and prev["current_ratio"] is not None:
            criteria["F6_better_liquidity"] = int(cr > prev["current_ratio"])
        else:
            # Fallback: nivåbaserat (CR > 1.5 = OK)
            criteria["F6_better_liquidity"] = int(cr > 1.5)
    elif pd.notna(cr):
        criteria["F6_better_liquidity"] = int(cr > 1.5)
    else:
        criteria["F6_better_liquidity"] = 0

    # ── F7: Ingen utspädning (jämför shares outstanding med snapshot) ───
    if pd.notna(shares) and shares > 0 and ticker:
        prev = _load_snapshot(ticker, datetime.now().date())
        if prev and "shares_outstanding" in prev and prev["shares_outstanding"] is not None:
            prev_shares = prev["shares_outstanding"]
            dilution = (shares / prev_shares) - 1 if prev_shares > 0 else 0
            criteria["F7_no_dilution"] = int(dilution < 0.02)  # < 2% utspädning
        elif pd.notna(insider):
            # Fallback: insiderägande > 3% = troligen ingen utspädning
            criteria["F7_no_dilution"] = int(insider > 0.03)
        else:
            # Default: antag ingen utspädning om data saknas
            criteria["F7_no_dilution"] = 1
    elif pd.notna(insider):
        criteria["F7_no_dilution"] = int(insider > 0.03)
    else:
        criteria["F7_no_dilution"] = 1

    # ── F8: Bättre bruttomarginal (jämförbättring (jämför med snapshot) ────
    if pd.notna(gm) and ticker:
        prev = _load_snapshot(ticker, datetime.now().date())
        if prev and "gross_margin" in prev and prev["gross_margin"] is not None:
            criteria["F8_better_gross_margin"] = int(gm > prev["gross_margin"])
        elif pd.notna(rg):
            # Fallback: GM > 30% + positiv tillväxt
            criteria["F8_better_gross_margin"] = int(gm > 0.30 and rg > 0)
        elif gm is not None:
            criteria["F8_better_gross_margin"] = int(gm > 0.30)
        else:
            criteria["F8_better_gross_margin"] = 0
    elif pd.notna(gm):
        criteria["F8_better_gross_margin"] = int(gm > 0.30)
    else:
        criteria["F8_better_gross_margin"] = 0

    # ── F9: Bättre omsättningseffektivitet ───────────────────────────── ─
    # Approximera asset turnover-förbättring via om -> om historisk finns
    if pd.notna(om) and ticker:
        prev = _load_snapshot(ticker, datetime.now().date())
        if prev and "operating_margin" in prev and prev["operating_margin"] is not None:
            criteria["F9_asset_turnover"] = int(om > prev["operating_margin"])
        elif pd.notna(rg) and pd.notna(om):
            # Omsättningstillväxt + förbättrad marginal = effektivisering
            criteria["F9_asset_turnover"] = int(om > 0.10 and rg > 0)
        else:
            criteria["F9_asset_turnover"] = int(om > 0.15) if pd.notna(om) else 0
    elif pd.notna(om):
        criteria["F9_asset_turnover"] = int(om > 0.15)
    else:
        criteria["F9_asset_turnover"] = 0

    # ── Summera ──────────────────────────────────────────────────────────
    f_score = sum(criteria.values())

    if f_score >= 7:
        label = "STARK"
    elif f_score >= 4:
        label = "NEUTRAL"
    else:
        label = "SVAG"

    # ── Spara snapshot för framtida YoY-jämförelser ─────────────────────
    if ticker:
        snapshot = {
            "roa": float(roa) if pd.notna(roa) else None,
        }
        # Bara spara fält som faktiskt används i YoY
        if pd.notna(de):
            snapshot["debt_to_equity"] = float(de)
        if pd.notna(cr):
            snapshot["current_ratio"] = float(cr)
        if pd.notna(gm):
            snapshot["gross_margin"] = float(gm)
        if pd.notna(om):
            snapshot["operating_margin"] = float(om)
        if pd.notna(shares):
            snapshot["shares_outstanding"] = float(shares)
        _save_snapshot(ticker, snapshot)

    return {
        "f_score": f_score,
        "label":   label,
        "criteria": criteria,
    }


def add_piotroski_to_universe(scored: pd.DataFrame,
                               verbose: bool = True) -> pd.DataFrame:
    """
    Beräknar Piotroski F-Score för hela universumet och lägger till kolumner.

    Nya kolumner:
      - piotroski_f    : 0-9 score
      - piotroski_label: STARK / NEUTRAL / SVAG
      - piotroski_boost: score-justering (+8 för STARK, -8 för SVAG)
    """
    df = scored.copy()

    f_scores = []
    labels   = []

    for _, row in df.iterrows():
        ticker = str(row.get("ticker", ""))
        result = calc_piotroski(row, ticker=ticker)
        f_scores.append(result["f_score"])
        labels.append(result["label"])

    df["piotroski_f"]     = f_scores
    df["piotroski_label"] = labels

    # Score-boost/penalty per arkitekturrekommendationen:
    # STARK -> +8, NEUTRAL -> 0, SVAG -> -8
    boost_map = {"STARK": +8, "NEUTRAL": 0, "SVAG": -8}
    df["piotroski_boost"] = df["piotroski_label"].map(boost_map).fillna(0)
    df["score_total"]     = (df["score_total"] + df["piotroski_boost"]).clip(0, 100)

    # Uppdatera ranking
    df["rank"] = df["score_total"].rank(ascending=False, method="min").astype("Int64")

    if verbose:
        stark   = (df["piotroski_label"] == "STARK").sum()
        neutral = (df["piotroski_label"] == "NEUTRAL").sum()
        svag    = (df["piotroski_label"] == "SVAG").sum()
        print(f"  ✓ Piotroski: {stark} STARK, {neutral} NEUTRAL, {svag} SVAG")

    return df


def build_piotroski_section(scored: pd.DataFrame, n: int = 15) -> str:
    """Markdown-sektion som visar Piotroski-fördelningen för topp aktier."""
    if "piotroski_f" not in scored.columns:
        return ""

    lines = ["\n## 🏥 Piotroski F-Score (finansiell hälsa)\n"]
    lines.append("_9-punkts finansiell hälsokoll. 7-9 = STARK, 4-6 = NEUTRAL, 0-3 = SVAG_\n")
    lines.append("| Rank | Ticker | Bolag | F-Score | Status | Score |")
    lines.append("|------|--------|-------|---------|--------|-------|")

    label_icons = {"STARK": "🟢", "NEUTRAL": "⚪", "SVAG": "🔴"}

    for _, row in scored.head(n).iterrows():
        f  = row.get("piotroski_f", "--")
        lb = row.get("piotroski_label", "--")
        lines.append(
            f"| {row['rank']} | `{row['ticker']}` | "
            f"{str(row.get('name',''))[:22]} | "
            f"**{f}/9** | {label_icons.get(lb,'⚪')} {lb} | "
            f"{row['score_total']:.0f} |"
        )

    # Statistik
    stark   = (scored["piotroski_label"] == "STARK").sum()  if "piotroski_label" in scored.columns else 0
    neutral = (scored["piotroski_label"] == "NEUTRAL").sum() if "piotroski_label" in scored.columns else 0
    svag    = (scored["piotroski_label"] == "SVAG").sum()    if "piotroski_label" in scored.columns else 0
    lines.append(f"\n_Universum: {stark} STARK * {neutral} NEUTRAL * {svag} SVAG_")

    return "\n".join(lines)