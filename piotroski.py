"""
piotroski.py
============
Beräknar Piotroski F-Score för varje aktie.

Bakgrund:
  Joseph Piotroski (2000) visade att ett enkelt 9-punkts system baserat
  på bokföringssignaler kan identifiera "finansiellt starka" kontra
  "finansiellt svaga" värdebolag – med signifikant avkastningsskillnad.

  Akademiskt bland de mest robusta och replikerade anomalierna.

De 9 kriterierna (1 poäng vardera):

LÖNSAMHET (F1-F4):
  F1. ROA > 0          (nettoresultat / totala tillgångar är positivt)
  F2. ROA förbättrad   (ROA i år > ROA föregående år)
  F3. OCF > 0          (operativt kassaflöde positivt)
  F4. Accrual-kvalitet (OCF / totala tillgångar > ROA – varning för aggressiv redovisning)

KAPITALSTRUKTUR (F5-F6):
  F5. Lägre skuldsättning   (long-term debt ratio minskade)
  F6. Bättre likviditet     (current ratio förbättrades)
  F7. Ingen ny utspädning   (inga nya aktier emitterade)

EFFEKTIVITET (F8-F9):
  F8. Bättre bruttomarginal (gross margin förbättrades)
  F9. Bättre omsättning     (asset turnover förbättrades)

Tolkning:
  0–3: Svag finansiell ställning (potentiell blankning)
  4–6: Neutral
  7–9: Stark finansiell ställning (köpsignal)

Notering: Beräknas på senaste 2 kvartal av yfinance-data.
Fullständig årsdata saknas ofta – vi använder bästa tillgängliga data.
"""

import pandas as pd
import numpy as np


def calc_piotroski(row: pd.Series) -> dict:
    """
    Beräknar F-Score för en enskild aktie från ett metrics-dict.

    Indata (från data_fetcher.extract_metrics):
      - roa, free_cash_flow, total_assets_approx (market_cap / price_to_book),
        debt_to_equity, current_ratio, gross_margin, operating_margin

    Returnerar dict med:
      - f_score (0-9)
      - criteria (dict med varje kriteriums värde)
      - label (STARK/NEUTRAL/SVAG)
    """
    criteria = {}

    # ── F1: ROA > 0 ──────────────────────────────────────────
    roa = row.get("roa")
    criteria["F1_roa_positive"] = int(pd.notna(roa) and roa > 0)

    # ── F2: ROA förbättrad (approx via profit margin trend) ──
    # Vi har inte tvåårdata direkt, men vi kan använda earnings_growth
    eg = row.get("earnings_growth")
    criteria["F2_roa_improving"] = int(pd.notna(eg) and eg > 0)

    # ── F3: Operativt kassaflöde > 0 ─────────────────────────
    fcf = row.get("free_cash_flow")
    criteria["F3_ocf_positive"] = int(pd.notna(fcf) and fcf > 0)

    # ── F4: Accrual-kvalitet (OCF > ROA) ─────────────────────
    # Approximation: om FCF/market_cap > ROA
    mc = row.get("market_cap")
    if pd.notna(fcf) and pd.notna(mc) and mc > 0 and pd.notna(roa):
        fcf_ratio = fcf / mc
        criteria["F4_accrual_quality"] = int(fcf_ratio > roa)
    else:
        criteria["F4_accrual_quality"] = 0

    # ── F5: Skuldsättning minskad ─────────────────────────────
    # Vi har bara nuläget, inte föregående – approximera med abs nivå
    de = row.get("debt_to_equity")
    if pd.notna(de):
        # Skuldsättning under 100% = rimlig finansiell hälsa
        criteria["F5_lower_leverage"] = int(de < 100)
    else:
        criteria["F5_lower_leverage"] = 0

    # ── F6: Bättre likviditet ─────────────────────────────────
    cr = row.get("current_ratio")
    criteria["F6_better_liquidity"] = int(pd.notna(cr) and cr > 1.5)

    # ── F7: Ingen utspädning ──────────────────────────────────
    # Approximation: om insider_pct är relativt hög indikerar det
    # att inga massiva emissioner skett nyligen
    insider = row.get("insider_pct")
    if pd.notna(insider):
        criteria["F7_no_dilution"] = int(insider > 0.03)  # >3% insider-ägande
    else:
        # Default: anta ej utspädning om vi saknar data
        criteria["F7_no_dilution"] = 1

    # ── F8: Bättre bruttomarginal ─────────────────────────────
    gm = row.get("gross_margin")
    rg = row.get("revenue_growth")
    if pd.notna(gm) and pd.notna(rg):
        # Bruttomarginal > 30% + positiv tillväxt = stark signal
        criteria["F8_better_gross_margin"] = int(gm > 0.30 and rg > 0)
    elif pd.notna(gm):
        criteria["F8_better_gross_margin"] = int(gm > 0.30)
    else:
        criteria["F8_better_gross_margin"] = 0

    # ── F9: Bättre omsättningseffektivitet ───────────────────
    # Approximation via revenue_growth / earnings_growth kvot
    # Bolag som ökar omsättningen mer än kostnaderna = effektivisering
    om = row.get("operating_margin")
    if pd.notna(om) and pd.notna(rg):
        criteria["F9_asset_turnover"] = int(om > 0.10 and rg > 0)
    elif pd.notna(om):
        criteria["F9_asset_turnover"] = int(om > 0.15)
    else:
        criteria["F9_asset_turnover"] = 0

    # ── Summera ───────────────────────────────────────────────
    f_score = sum(criteria.values())

    if f_score >= 7:
        label = "STARK"
    elif f_score >= 4:
        label = "NEUTRAL"
    else:
        label = "SVAG"

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
        result = calc_piotroski(row)
        f_scores.append(result["f_score"])
        labels.append(result["label"])

    df["piotroski_f"]     = f_scores
    df["piotroski_label"] = labels

    # Score-boost/penalty
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
        f  = row.get("piotroski_f", "—")
        lb = row.get("piotroski_label", "—")
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
    lines.append(f"\n_Universum: {stark} STARK · {neutral} NEUTRAL · {svag} SVAG_")

    return "\n".join(lines)
