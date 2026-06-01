"""
sector_momentum.py
==================
Filtrerar bort hela sektorer som är i nedgång.

Princip: Om hela tekniksektorn (XLK) trender nedåt vill du inte köpa
ens de bästa techaktierna - du simmar mot strömmen. Sektorer i upptrend
ger medvind; sektorer i nedtrend ger motvind.

Signaler per sektor:
  STARK UPPTREND  - ETF > MA50 > MA200, positiv 3m-momentum
  UPPTREND        - ETF > MA200
  NEUTRAL         - Blandad signal
  NEDTREND        - ETF < MA200
  STARK NEDTREND  - ETF < MA50 < MA200, negativ 3m-momentum

Applicering på scored DataFrame:
  - Aktier i STARK NEDTREND-sektorer: score sänks 20%
  - Aktier i NEDTREND-sektorer: score sänks 10%
  - Aktier i UPPTREND-sektorer: score höjs 5%
  - Aktier i STARK UPPTREND-sektorer: score höjs 10%
"""

import time
import pickle
import hashlib
from datetime import datetime, timedelta
from pathlib import Path

import yfinance as yf
import pandas as pd
import numpy as np

CACHE_DIR       = "data/cache"
SECTOR_CACHE_H  = 24
Path(CACHE_DIR).mkdir(parents=True, exist_ok=True)

# Sektor -> ETF-mappning (US-baserade, men representativa globalt)
SECTOR_ETFS = {
    "Technology":             "XLK",   # Technology Select Sector SPDR
    "Healthcare":             "XLV",   # Health Care Select Sector SPDR
    "Financial Services":     "XLF",   # Financial Select Sector SPDR
    "Consumer Cyclical":      "XLY",   # Consumer Discretionary SPDR
    "Consumer Defensive":     "XLP",   # Consumer Staples SPDR
    "Energy":                 "XLE",   # Energy Select Sector SPDR
    "Industrials":            "XLI",   # Industrial Select Sector SPDR
    "Communication Services": "XLC",   # Communication Services SPDR
    "Basic Materials":        "XLB",   # Materials Select Sector SPDR
    "Real Estate":            "XLRE",  # Real Estate Select Sector SPDR
    "Utilities":              "XLU",   # Utilities Select Sector SPDR
}
# Notering: inga dubletter - Python dict skriver tyst över dublettnycklar

# Justering av score baserat på sektormomtentum
SECTOR_SCORE_ADJUSTMENT = {
    "STARK UPPTREND":  +10,
    "UPPTREND":        +5,
    "NEUTRAL":          0,
    "NEDTREND":        -10,
    "STARK NEDTREND":  -20,
}


# ── Cache helpers ──────────────────────────────────────────────

def _cp(key):
    h = hashlib.md5(key.encode()).hexdigest()
    return Path(CACHE_DIR) / f"sectmom_{h}.pkl"

def _rc(key, max_h):
    p = _cp(key)
    if not p.exists(): return None
    if datetime.now() - datetime.fromtimestamp(p.stat().st_mtime) > timedelta(hours=max_h):
        return None
    try:
        with open(p, "rb") as f: return pickle.load(f)
    except Exception: return None

def _wc(key, data):
    try:
        with open(_cp(key), "wb") as f: pickle.dump(data, f)
    except Exception: pass


# ══════════════════════════════════════════════════════════════
# HÄMTA SEKTORMOMTENTUM
# ══════════════════════════════════════════════════════════════

def fetch_sector_momentum(verbose: bool = True) -> dict:
    """
    Hämtar momentum-data för alla sektor-ETFer.

    Returnerar dict: {sektor: {signal, trend, return_1m, return_3m,
                               above_ma50, above_ma200, etf}}
    """
    cache_key = f"sector_momentum:{datetime.now().strftime('%Y-%m-%d')}"
    cached    = _rc(cache_key, SECTOR_CACHE_H)
    if cached is not None:
        return cached

    results = {}
    seen_etfs = set()

    for sector, etf in SECTOR_ETFS.items():
        if etf in seen_etfs:
            continue
        seen_etfs.add(etf)

        try:
            time.sleep(0.3)
            hist = yf.Ticker(etf).history(period="1y", auto_adjust=True)

            if hist.empty or len(hist) < 30:
                results[sector] = _neutral_signal(etf)
                continue

            close = hist["Close"]
            current = float(close.iloc[-1])

            # MA-beräkningar
            ma50  = float(close.rolling(50).mean().iloc[-1])  if len(close) >= 50  else None
            ma200 = float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else None

            # Avkastningar
            ret_1m = float((current / close.iloc[-21]) - 1)  if len(close) >= 21  else None
            ret_3m = float((current / close.iloc[-63]) - 1)  if len(close) >= 63  else None

            above_ma50  = (current > ma50)  if ma50  is not None else None
            above_ma200 = (current > ma200) if ma200 is not None else None

            # Klassificering
            signal = _classify_signal(above_ma50, above_ma200, ret_3m)

            results[sector] = {
                "signal":      signal,
                "etf":         etf,
                "current":     round(current, 2),
                "ma50":        round(ma50,  2) if ma50  else None,
                "ma200":       round(ma200, 2) if ma200 else None,
                "above_ma50":  above_ma50,
                "above_ma200": above_ma200,
                "return_1m":   round(ret_1m, 4) if ret_1m is not None else None,
                "return_3m":   round(ret_3m, 4) if ret_3m is not None else None,
            }

        except Exception as e:
            results[sector] = _neutral_signal(etf)

    _wc(cache_key, results)

    if verbose:
        n_up   = sum(1 for v in results.values() if "UPPTREND" in v["signal"])
        n_down = sum(1 for v in results.values() if "NEDTREND" in v["signal"])
        print(f"  ✓ Sektormomtentum: {n_up} sektorer i upptrend, {n_down} i nedtrend")

    return results


def _classify_signal(above_ma50, above_ma200, ret_3m) -> str:
    """
    Klassificerar sektorsignalen baserat på MA-position OCH 3m-momentum.

    Kombinerar strukturell trend (MA) med faktisk momentum (3m-avkastning)
    för att undvika att visa 🟢 för sektorer med negativ avkastning.
    """
    if above_ma200 is None:
        return "NEUTRAL"

    r3 = ret_3m if ret_3m is not None else 0.0

    if above_ma50 and above_ma200:
        if r3 > 0.05:
            return "STARK UPPTREND"   # Över båda MA + positiv 3m-momentum
        elif r3 >= -0.02:
            return "UPPTREND"          # Över båda MA men svagt eller flat momentum
        else:
            return "NEUTRAL"           # Strukturellt upp men 3m-momentum negativ -> degradera
    elif not above_ma50 and not above_ma200:
        if r3 < -0.05:
            return "STARK NEDTREND"   # Under båda MA + negativ momentum
        return "NEDTREND"
    else:
        # En MA uppfylld, en inte
        if r3 < -0.03:
            return "NEDTREND"          # Blandad MA men tydlig nedgång
        elif r3 > 0.03:
            return "UPPTREND"          # Blandad MA men tydlig uppgång
        return "NEUTRAL"


def _neutral_signal(etf: str) -> dict:
    return {
        "signal": "NEUTRAL", "etf": etf,
        "current": None, "ma50": None, "ma200": None,
        "above_ma50": None, "above_ma200": None,
        "return_1m": None, "return_3m": None,
    }


# ══════════════════════════════════════════════════════════════
# APPLICERA PÅ SCORAD DATAFRAME
# ══════════════════════════════════════════════════════════════

def apply_sector_momentum(scored: pd.DataFrame,
                           sector_momentum: dict = None,
                           verbose: bool = True) -> pd.DataFrame:
    """
    Justerar score_total baserat på sektormomtentum.

    Lägger till kolumner:
      sector_signal     - sektorsignal (STARK UPPTREND etc.)
      sector_adjustment - poängjustering som applicerades
    """
    if sector_momentum is None:
        sector_momentum = fetch_sector_momentum(verbose=verbose)

    if not sector_momentum:
        scored["sector_signal"]     = "NEUTRAL"
        scored["sector_adjustment"] = 0
        return scored

    df = scored.copy()

    # Mappa sektor -> signal
    df["sector_signal"] = df["sector"].map(
        lambda s: sector_momentum.get(str(s), {}).get("signal", "NEUTRAL")
        if pd.notna(s) else "NEUTRAL"
    )

    # Beräkna och applicera justering
    df["sector_adjustment"] = df["sector_signal"].map(SECTOR_SCORE_ADJUSTMENT).fillna(0)
    df["score_total"]       = (df["score_total"] + df["sector_adjustment"]).clip(0, 100)

    # Uppdatera ranking
    df["rank"] = df["score_total"].rank(ascending=False, method="min").astype("Int64")

    if verbose:
        adjusted_up   = (df["sector_adjustment"] > 0).sum()
        adjusted_down = (df["sector_adjustment"] < 0).sum()
        print(f"  ✓ Sektorjustering: {adjusted_up} höjda, {adjusted_down} sänkta")

    return df


# ══════════════════════════════════════════════════════════════
# RAPPORT-SEKTION
# ══════════════════════════════════════════════════════════════

def build_sector_momentum_section(sector_momentum: dict) -> str:
    """Markdown-sektion för rapporten."""
    if not sector_momentum:
        return ""

    lines = ["\n## 📈 Sektormomtentum\n"]
    lines.append("_Sektorer i nedtrend drar ned scores för aktier i dem._\n")
    lines.append("| Sektor | ETF | Signal | 1m | 3m | MA50 | MA200 |")
    lines.append("|--------|-----|--------|----|----|------|-------|")

    # Sortera: bästa upptrend -> sämsta nedtrend
    order = ["STARK UPPTREND", "UPPTREND", "NEUTRAL", "NEDTREND", "STARK NEDTREND"]
    sorted_sectors = sorted(
        sector_momentum.items(),
        key=lambda x: order.index(x[1].get("signal", "NEUTRAL"))
    )

    signal_icons = {
        "STARK UPPTREND": "🟢🟢",
        "UPPTREND":       "🟢",
        "NEUTRAL":        "⚪",
        "NEDTREND":       "🔴",
        "STARK NEDTREND": "🔴🔴",
    }

    for sector, data in sorted_sectors:
        sig   = data.get("signal", "NEUTRAL")
        etf   = data.get("etf", "--")
        r1m   = data.get("return_1m")
        r3m   = data.get("return_3m")
        m50   = "✅" if data.get("above_ma50")  else "❌" if data.get("above_ma50") is False else "--"
        m200  = "✅" if data.get("above_ma200") else "❌" if data.get("above_ma200") is False else "--"
        r1m_s = f"{r1m*100:+.1f}%" if r1m is not None else "--"
        r3m_s = f"{r3m*100:+.1f}%" if r3m is not None else "--"

        lines.append(
            f"| {sector[:22]} | `{etf}` | "
            f"{signal_icons.get(sig,'⚪')} {sig} | "
            f"{r1m_s} | {r3m_s} | {m50} | {m200} |"
        )

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════
# SEKTOR-ROTATIONSDETEKTOR
# ══════════════════════════════════════════════════════════════

def detect_sector_rotation(sector_momentum: dict = None,
                           lookback_months: int = 3,
                           min_momentum_change: float = 0.05,
                           verbose: bool = True) -> dict:
    """
    Detekterar sektorrotation genom att jämföra momentumförändring över tid.

    Princip: Om en sektor som tidigare var i bottenkvartilen plötsligt
    klättrar till toppkvartilen på 1m-basis, signalerar det rotation in.
    Om en sektor som var i toppen faller till botten, signalerar det rotation ut.

    Args:
        sector_momentum: Dict från fetch_sector_momentum() eller None för auto-fetch
        lookback_months: Historik för att beräkna momentumförändring (3 månader)
        min_momentum_change: Minsta förändring i rang för att räknas som rotation
        verbose: Skriv ut sammanfattning

    Returns:
        dict med:
        - rotating_in: [sektorer som rotar in i favör]
        - rotating_out: [sektorer som rotar ur favör]
        - top_sectors: [nuvarande topp 3 sektorer]
        - bottom_sectors: [nuvarande botten 3 sektorer]
        - momentum_changes: {sektor: {current_rank, prev_rank, rank_change, direction}}
        - rotation_intensity: "STARK" / "MÅTTLIG" / "SVAG"
    """
    if sector_momentum is None:
        sector_momentum = fetch_sector_momentum(verbose=verbose)

    if not sector_momentum:
        return {
            "rotating_in": [], "rotating_out": [],
            "top_sectors": [], "bottom_sectors": [],
            "momentum_changes": {},
            "rotation_intensity": "OKÄND",
        }

    # Beräkna momentum-score för varje sektor baserat på 1m/3m + signal
    def _momentum_score(data: dict) -> float:
        """Beräknar en numerisk momentum-score 0-100 för en sektor."""
        ret_1m = data.get("return_1m") or 0.0
        ret_3m = data.get("return_3m") or 0.0
        signal = data.get("signal", "NEUTRAL")

        # Baspoäng från signal
        signal_base = {
            "STARK UPPTREND": 85,
            "UPPTREND":       65,
            "NEUTRAL":        45,
            "NEDTREND":       25,
            "STARK NEDTREND": 10,
        }.get(signal, 45)

        # Lägg till momentum-komponent (viktad 60% signal, 40% avkastning)
        momentum_contrib = (ret_1m * 100 * 0.6 + ret_3m * 100 * 0.4)
        score = signal_base * 0.6 + max(-30, min(30, momentum_contrib))
        return max(0, min(100, score))

    # Beräkna scores och ranka
    scored_sectors = []
    for sector, data in sector_momentum.items():
        score = _momentum_score(data)
        scored_sectors.append((sector, score, data))

    # Sortera efter score (fallande)
    scored_sectors.sort(key=lambda x: x[1], reverse=True)
    n_sectors = len(scored_sectors)

    # Bestäm nuvarande rang för varje sektor
    current_ranks = {}
    for i, (sector, score, data) in enumerate(scored_sectors):
        current_ranks[sector] = i + 1  # 1 = bäst

    # För tidigare rang: använd 3m-avkastning som proxy för tidigare momentum
    # Sektorer med hög 3m-avkastning som nu har svag 1m = rotation ut
    # Sektorer med låg 3m-avkastning som nu har stark 1m = rotation in
    prev_order = sorted(
        sector_momentum.items(),
        key=lambda x: x[1].get("return_3m") or 0,
        reverse=True
    )
    prev_ranks = {}
    for i, (sector, data) in enumerate(prev_order):
        prev_ranks[sector] = i + 1

    # Beräkna rangförändring och detektera rotation
    momentum_changes = {}
    rotating_in = []
    rotating_out = []

    for sector in sector_momentum:
        curr_rank = current_ranks.get(sector, n_sectors)
        prev_rank = prev_ranks.get(sector, n_sectors)
        rank_change = prev_rank - curr_rank  # Positivt = förbättring

        # Bestäm riktning
        if rank_change >= 2:
            direction = "ROTATION IN"  # Klättrat i rang
            rotating_in.append(sector)
        elif rank_change <= -2:
            direction = "ROTATION UT"  # Fallit i rang
            rotating_out.append(sector)
        else:
            direction = "STABIL"

        momentum_changes[sector] = {
            "current_rank": curr_rank,
            "prev_rank": prev_rank,
            "rank_change": rank_change,
            "direction": direction,
            "signal": sector_momentum[sector].get("signal", "NEUTRAL"),
            "return_1m": sector_momentum[sector].get("return_1m"),
            "return_3m": sector_momentum[sector].get("return_3m"),
        }

    # Topp/botten sektorer
    top_sectors = [s for s, _, _ in scored_sectors[:min(3, n_sectors)]]
    bottom_sectors = [s for s, _, _ in scored_sectors[-min(3, n_sectors):]]

    # Rotationsintensitet
    n_rotating = len(rotating_in) + len(rotating_out)
    total = n_sectors
    if total > 0:
        rotation_pct = n_rotating / total
        if rotation_pct >= 0.4:
            intensity = "STARK"
        elif rotation_pct >= 0.2:
            intensity = "MÅTTLIG"
        else:
            intensity = "SVAG"
    else:
        intensity = "OKÄND"

    if verbose:
        print(f"  🔄 Sektorrotation: {len(rotating_in)} rotar in, {len(rotating_out)} rotar ut")
        print(f"     Intensitet: {intensity}")
        if rotating_in:
            print(f"     Rotar in: {', '.join(rotating_in)}")
        if rotating_out:
            print(f"     Rotar ut: {', '.join(rotating_out)}")

    return {
        "rotating_in": rotating_in,
        "rotating_out": rotating_out,
        "top_sectors": top_sectors,
        "bottom_sectors": bottom_sectors,
        "momentum_changes": momentum_changes,
        "rotation_intensity": intensity,
    }


def build_rotation_section(rotation_data: dict) -> str:
    """Markdown-rapportsektion för sektorrotation."""
    if not rotation_data or not rotation_data.get("momentum_changes"):
        return ""

    lines = ["\n## 🔄 Sektorrotation\n"]
    lines.append("_Sektorer som byter favör - tidig signal för omallokering._\n")

    intensity = rotation_data.get("rotation_intensity", "OKÄND")
    intensity_icon = {"STARK": "🔴", "MÅTTLIG": "🟡", "SVAG": "🟢", "OKÄND": "⚪"}
    lines.append(f"**Rotationsintensitet:** {intensity_icon.get(intensity, '⚪')} {intensity}\n")

    # Roterar in
    rotating_in = rotation_data.get("rotating_in", [])
    if rotating_in:
        lines.append("### ⬆️ Roterar IN\n")
        for sector in rotating_in:
            info = rotation_data["momentum_changes"].get(sector, {})
            r1m = info.get("return_1m")
            r3m = info.get("return_3m")
            r1m_s = f"{r1m*100:+.1f}%" if r1m is not None else "--"
            r3m_s = f"{r3m*100:+.1f}%" if r3m is not None else "--"
            chg = info.get("rank_change", 0)
            lines.append(f"- **{sector}**: Rangförändring +{chg} | 1m: {r1m_s} | 3m: {r3m_s}")

    # Roterar ut
    rotating_out = rotation_data.get("rotating_out", [])
    if rotating_out:
        lines.append("\n### ⬇️ Roterar UT\n")
        for sector in rotating_out:
            info = rotation_data["momentum_changes"].get(sector, {})
            r1m = info.get("return_1m")
            r3m = info.get("return_3m")
            r1m_s = f"{r1m*100:+.1f}%" if r1m is not None else "--"
            r3m_s = f"{r3m*100:+.1f}%" if r3m is not None else "--"
            chg = info.get("rank_change", 0)
            lines.append(f"- **{sector}**: Rangförändring {chg} | 1m: {r1m_s} | 3m: {r3m_s}")

    # Topp/botten
    tops = rotation_data.get("top_sectors", [])
    bottoms = rotation_data.get("bottom_sectors", [])
    lines.append("\n### 🏆 Topp 3 sektorer\n")
    for i, s in enumerate(tops, 1):
        info = rotation_data["momentum_changes"].get(s, {})
        sig = info.get("signal", "--")
        r1m = info.get("return_1m")
        r1m_s = f"{r1m*100:+.1f}%" if r1m is not None else "--"
        lines.append(f"{i}. **{s}** - {sig} (1m: {r1m_s})")

    lines.append("\n### 🗑️ Botten 3 sektorer\n")
    for i, s in enumerate(bottoms, 1):
        info = rotation_data["momentum_changes"].get(s, {})
        sig = info.get("signal", "--")
        r1m = info.get("return_1m")
        r1m_s = f"{r1m*100:+.1f}%" if r1m is not None else "--"
        lines.append(f"{i}. **{s}** - {sig} (1m: {r1m_s})")

    return "\n".join(lines)
