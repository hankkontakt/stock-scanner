"""
scoring.py – Poängmodell optimerad för svenska småbolag.

8 faktorer, totalt 100 poäng:
  Insider-ägarskap & aktivitet   18%  – skin in the game
  Free Cash Flow-yield           16%  – äkta pengar, inte earnings
  Piotroski F-Score              15%  – finansiell hälsa (akademiskt bevisad)
  Tillväxt (intäkter/vinst)      13%  – småbolag måste växa
  Balansräkning                  12%  – skuldsättning + likviditet
  Värdering (EV/EBITDA, P/B)     12%  – betala inte för dyrt
  Momentum (6/12 månaders return) 9%  – "discovery phase" – trender håller längre i small cap
  Handelslikviditet               5%  – kan du faktiskt köpa/sälja?

Bonusar (kan inte överstiga 100 totalt):
  +5  Nettokassa (cash > total skuld)
  +3  Ägare-drivet bolag (insider_pct > 20%)
  +3  Expanderande marginaler (gross margin trending up)

Avdrag (sanktioner):
  -10 Utspädning > 10% senaste 12m
  -5  Piotroski < 3 (svaga fundamenta)
"""

import numpy as np
import pandas as pd
import sys
from pathlib import Path

# Tillåt import av piotroski.py från föräldramappen
sys.path.insert(0, str(Path(__file__).parent.parent))
try:
    import piotroski as _piotroski
    _PIOTROSKI_AVAILABLE = True
except ImportError:
    _PIOTROSKI_AVAILABLE = False

def _load_weights() -> dict:
    """Läser vikter från config.py SMALLCAP_CONFIG om tillgängligt."""
    try:
        import config
        w = config.SMALLCAP_CONFIG.get("scoring_weights", {})
        if w and abs(sum(w.values()) - 1.0) < 0.01:
            # Mappa "value" → "valuation" om config använder kortformen
            return {("valuation" if k == "value" else k): v for k, v in w.items()}
    except (ImportError, AttributeError):
        pass
    return {
        "insider":    0.18,
        "fcf_yield":  0.16,
        "piotroski":  0.15,
        "growth":     0.13,
        "balance":    0.12,
        "valuation":  0.12,
        "momentum":   0.09,
        "liquidity":  0.05,
    }


# Viktning per faktor (läses från config.py om möjligt)
FACTOR_WEIGHTS = _load_weights()


# ══════════════════════════════════════════════════════════════
# HJÄLPFUNKTIONER
# ══════════════════════════════════════════════════════════════

def _winsorize(series: pd.Series, lower: float = 0.05, upper: float = 0.95) -> pd.Series:
    """Klämmer extremvärden till percentilgränser för att minska outlier-påverkan."""
    lo = series.quantile(lower)
    hi = series.quantile(upper)
    return series.clip(lo, hi)


def _percentile_score(series: pd.Series, ascending: bool = True) -> pd.Series:
    """
    Konverterar en rådata-serie till percentilpoäng 0–100.
    ascending=True → höga värden ger höga poäng
    ascending=False → låga värden ger höga poäng (t.ex. låg skuld = bra)
    """
    clean = _winsorize(series.fillna(series.median()))
    rank  = clean.rank(pct=True, ascending=ascending, na_option="bottom")
    return (rank * 100).clip(0, 100)


# ══════════════════════════════════════════════════════════════
# FAKTORBERÄKNINGAR (varje returnerar en pd.Series 0–100)
# ══════════════════════════════════════════════════════════════

def _score_insider(df: pd.DataFrame) -> pd.Series:
    """
    Insiderpoäng: ägarandel + senaste insider-aktivitet.
    Insider-ägarandel > 20% = grundar-styrt bolag = bra signal.
    Nyliga insider-köp (insider_net_buy_6m > 0) ger bonuspoäng.
    """
    # Ägarandel: heldPercentInsiders (0.0–1.0 från yfinance)
    ownership = df.get("insider_pct", pd.Series(0, index=df.index)).fillna(0)
    ownership_score = _percentile_score(ownership) * 0.60   # max 60% av poängen

    # Insider-aktivitet (om hämtad, annars 0)
    net_buy = df.get("insider_net_buy_6m", pd.Series(0, index=df.index)).fillna(0)
    activity_score = _percentile_score(net_buy) * 0.40

    return (ownership_score + activity_score).clip(0, 100)


def _score_fcf_yield(df: pd.DataFrame) -> pd.Series:
    """
    FCF-yield = free_cash_flow / market_cap.
    Mest tillförlitliga värdemåttet för småbolag (earnings kan manipuleras).
    Negativt FCF = 0 poäng (starkt negativt tecken för mogna bolag).
    """
    fcf    = df.get("free_cash_flow", pd.Series(np.nan, index=df.index))
    mkcap  = df.get("market_cap",     pd.Series(np.nan, index=df.index))

    yield_pct = pd.Series(np.nan, index=df.index)
    valid = mkcap.notna() & mkcap.gt(0) & fcf.notna()
    yield_pct[valid] = fcf[valid] / mkcap[valid]

    # Nollsätt negativ FCF
    yield_pct = yield_pct.clip(lower=0)
    return _percentile_score(yield_pct)


def _score_piotroski(df: pd.DataFrame) -> pd.Series:
    """
    Piotroski F-Score (0–9). Beräknas av piotroski.py om tillgängligt.
    Annars används kolumnen piotroski_score om den redan finns i df.
    Mapping: 7-9 → 100p, 4-6 → 50p, 0-3 → 10p
    """
    score_map = {0: 5, 1: 5, 2: 10, 3: 15, 4: 40, 5: 55, 6: 70, 7: 85, 8: 95, 9: 100}

    if "piotroski_score" in df.columns:
        return df["piotroski_score"].fillna(4).map(score_map).fillna(40).astype(float)

    # Fallback: returnera neutral poäng om vi saknar data
    return pd.Series(50.0, index=df.index)


def _score_growth(df: pd.DataFrame) -> pd.Series:
    """
    Tillväxtpoäng: viktad kombination av intäktstillväxt + vinsttillväxt.
    Intäktstillväxt väger tyngre (mer pålitlig för småbolag).
    """
    rev_growth  = df.get("revenue_growth",  pd.Series(np.nan, index=df.index))
    earn_growth = df.get("earnings_growth", pd.Series(np.nan, index=df.index))

    rev_score  = _percentile_score(rev_growth.fillna(0))
    earn_score = _percentile_score(earn_growth.fillna(0))

    # Intäkt 60%, vinst 40%
    return (rev_score * 0.6 + earn_score * 0.4).clip(0, 100)


def _score_balance(df: pd.DataFrame) -> pd.Series:
    """
    Balansräkningspoäng: skuldsättning + likviditet.
    debt_to_equity: lägre = bättre (ascending=False)
    current_ratio:  högre = bättre (ascending=True)
    """
    de = df.get("debt_to_equity", pd.Series(np.nan, index=df.index)).fillna(100)
    cr = df.get("current_ratio",  pd.Series(np.nan, index=df.index)).fillna(1.0)

    de_score = _percentile_score(de, ascending=False)
    cr_score = _percentile_score(cr, ascending=True)

    return (de_score * 0.55 + cr_score * 0.45).clip(0, 100)


def _score_valuation(df: pd.DataFrame) -> pd.Series:
    """
    Värderingspoäng: EV/EBITDA primärt (mer robust), P/B som fallback.
    Lägre multiplar = bättre = ascending=False.
    Extremt låga eller negativa multiplar filtreras (troligen outliers).
    """
    ev_ebitda = df.get("ev_to_ebitda",  pd.Series(np.nan, index=df.index))
    pb        = df.get("price_to_book", pd.Series(np.nan, index=df.index))

    # Klipp bort negativa (orimliga) värden
    ev_ebitda = ev_ebitda.where(ev_ebitda > 0)
    pb        = pb.where(pb > 0)

    # Använd EV/EBITDA om tillgänglig, annars P/B
    val = ev_ebitda.combine_first(pb)
    val = val.fillna(val.median())

    return _percentile_score(val, ascending=False)


def _score_momentum(df: pd.DataFrame) -> pd.Series:
    """
    Momentumpoäng: 12-månaders avkastning viktas tyngst.
    Småbolag har längre "discovery phase" – momentum håller 9-18m.
    """
    r12 = df.get("return_12m", pd.Series(np.nan, index=df.index)).fillna(0)
    r6  = df.get("return_6m",  pd.Series(np.nan, index=df.index)).fillna(0)

    combined = r12 * 0.65 + r6 * 0.35
    return _percentile_score(combined)


def _score_liquidity(df: pd.DataFrame) -> pd.Series:
    """
    Likviditetspoäng: genomsnittlig handelsvolym × pris ≈ daglig omsättning i SEK.
    Viktigt för småbolag – illikvida aktier kan inte säljas i stress.
    """
    vol   = df.get("avg_volume",    pd.Series(np.nan, index=df.index)).fillna(0)
    price = df.get("current_price", pd.Series(np.nan, index=df.index)).fillna(0)

    daily_turnover = vol * price
    return _percentile_score(daily_turnover)


# ══════════════════════════════════════════════════════════════
# BONUS & AVDRAG
# ══════════════════════════════════════════════════════════════

def _calc_bonuses(df: pd.DataFrame) -> pd.Series:
    """Beräknar bonuspoäng för extra positiva signaler (+0 till +11)."""
    bonus = pd.Series(0.0, index=df.index)

    # +5: Nettokassa (total_cash > total_debt)
    cash = df.get("total_cash", pd.Series(0, index=df.index)).fillna(0)
    debt = df.get("total_debt", pd.Series(0, index=df.index)).fillna(0)
    bonus += (cash > debt) * 5

    # +3: Ägarstyrt bolag (insider äger > 20%)
    insider_pct = df.get("insider_pct", pd.Series(0, index=df.index)).fillna(0)
    bonus += (insider_pct > 0.20) * 3

    # +3: Expanderande bruttomarginal (gross_margin > 40% som proxy för pricing power)
    gm = df.get("gross_margin", pd.Series(np.nan, index=df.index)).fillna(0)
    bonus += (gm > 0.40) * 3

    return bonus


def _calc_penalties(df: pd.DataFrame) -> pd.Series:
    """Beräknar avdragspoäng för varningssignaler (-0 till -15)."""
    penalty = pd.Series(0.0, index=df.index)

    # -10: Utspädning (shares_change_pct > 10%)
    if "shares_change_pct" in df.columns:
        dilution = df["shares_change_pct"].fillna(0)
        penalty += (dilution > 0.10) * 10

    # -5: Mycket låg Piotroski (< 3)
    if "piotroski_score" in df.columns:
        penalty += (df["piotroski_score"].fillna(5) < 3) * 5

    # -3: Extremt hög skuldsättning (D/E > 200%)
    de = df.get("debt_to_equity", pd.Series(0, index=df.index)).fillna(0)
    penalty += (de > 200) * 3

    return penalty


# ══════════════════════════════════════════════════════════════
# HUVUD-SCORINGFUNKTION
# ══════════════════════════════════════════════════════════════

def score_universe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Beräknar sammansatt småbolagspoäng för alla tickers i df.

    Returnerar df med nya kolumner:
      sc_insider, sc_fcf, sc_piotroski, sc_growth, sc_balance,
      sc_valuation, sc_momentum, sc_liquidity,
      sc_bonus, sc_penalty, sc_total (0–100+)

    Rankad fallande på sc_total.
    """
    out = df.copy()

    # Beräkna delpoäng
    out["sc_insider"]    = _score_insider(df)
    out["sc_fcf"]        = _score_fcf_yield(df)
    out["sc_piotroski"]  = _score_piotroski(df)
    out["sc_growth"]     = _score_growth(df)
    out["sc_balance"]    = _score_balance(df)
    out["sc_valuation"]  = _score_valuation(df)
    out["sc_momentum"]   = _score_momentum(df)
    out["sc_liquidity"]  = _score_liquidity(df)

    # Vägt sammansatt poäng (0–100 innan bonus/avdrag)
    out["sc_composite"] = (
        out["sc_insider"]   * FACTOR_WEIGHTS["insider"]   +
        out["sc_fcf"]       * FACTOR_WEIGHTS["fcf_yield"] +
        out["sc_piotroski"] * FACTOR_WEIGHTS["piotroski"] +
        out["sc_growth"]    * FACTOR_WEIGHTS["growth"]    +
        out["sc_balance"]   * FACTOR_WEIGHTS["balance"]   +
        out["sc_valuation"] * FACTOR_WEIGHTS["valuation"] +
        out["sc_momentum"]  * FACTOR_WEIGHTS["momentum"]  +
        out["sc_liquidity"] * FACTOR_WEIGHTS["liquidity"]
    )

    # Bonus och avdrag
    out["sc_bonus"]   = _calc_bonuses(df)
    out["sc_penalty"] = _calc_penalties(df)
    out["sc_total"]   = (out["sc_composite"] + out["sc_bonus"] - out["sc_penalty"]).clip(0, 110)

    # Rang
    out["sc_rank"] = out["sc_total"].rank(ascending=False, method="min").astype("Int64")

    # Stjärnklassning: ★★★★★ (>80), ★★★★ (>65), ★★★ (>50), ★★ (>35), ★ (≤35)
    out["sc_stars"] = out["sc_total"].apply(_stars)

    return out.sort_values("sc_total", ascending=False).reset_index(drop=True)


def _stars(score: float) -> str:
    if score > 80: return "★★★★★"
    if score > 65: return "★★★★"
    if score > 50: return "★★★"
    if score > 35: return "★★"
    return "★"
