"""
macro_regime.py
===============
Detekterar marknadsregim (tjur/björn/osäker) och anpassar systemet därefter.

Logik:
  TJUR:    SPY > MA200 + VIX < 22 + 3m return > 0
  OSÄKER:  Blandade signaler
  BJÖRN:   SPY < MA200 + VIX > 28 ELLER 3m return < -8%

I björnmarknad: höj kraven för KÖP-signal, ge mindre vikt till momentum.
"""

import time
import pickle
import hashlib
from datetime import datetime, timedelta
from pathlib import Path

import yfinance as yf
import pandas as pd
import numpy as np

CACHE_DIR    = "data/cache"
REGIME_CACHE = 6   # timmar
Path(CACHE_DIR).mkdir(parents=True, exist_ok=True)


def _cp(key):
    h = hashlib.md5(key.encode()).hexdigest()
    return Path(CACHE_DIR) / f"regime_{h}.pkl"

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
    except: pass


def detect_regime() -> dict:
    """Hämtar SPY + VIX och bestämmer marknadsregim."""
    cached = _rc("regime", REGIME_CACHE)
    if cached is not None:
        return cached

    result = {
        "regime":         "OSÄKER",
        "spy_vs_ma200":   None,
        "vix_level":      None,
        "spy_3m_return":  None,
        "confidence":     0.5,
        "as_of":          datetime.now().strftime("%Y-%m-%d %H:%M"),
        "notes":          [],
    }

    try:
        time.sleep(0.3)
        spy = yf.Ticker("SPY").history(period="1y")
        if spy.empty or len(spy) < 200:
            return result

        spy_close = spy["Close"]
        current   = spy_close.iloc[-1]
        ma200     = spy_close.rolling(200).mean().iloc[-1]
        spy_3m    = (current / spy_close.iloc[-63] - 1) if len(spy_close) >= 63 else 0

        result["spy_vs_ma200"]  = float((current / ma200) - 1)
        result["spy_3m_return"] = float(spy_3m)

        time.sleep(0.3)
        vix       = yf.Ticker("^VIX").history(period="3mo")
        vix_level = float(vix["Close"].iloc[-1]) if not vix.empty else 20.0
        result["vix_level"] = vix_level

        signals = {
            "spy_well_above":   result["spy_vs_ma200"] > 0.05,
            "spy_well_below":   result["spy_vs_ma200"] < -0.05,
            "vix_calm":         vix_level < 18,
            "vix_elevated":     vix_level > 25,
            "vix_panic":        vix_level > 32,
            "momentum_positive":spy_3m > 0.02,
            "momentum_negative":spy_3m < -0.05,
        }

        bull_pts = sum([signals["spy_well_above"], signals["vix_calm"], signals["momentum_positive"]])
        bear_pts = sum([signals["spy_well_below"], signals["vix_elevated"], signals["momentum_negative"], signals["vix_panic"]])

        if bull_pts >= 2 and bear_pts == 0:
            result["regime"]     = "TJUR"
            result["confidence"] = min(1.0, bull_pts / 3)
            result["notes"].append(f"SPY +{result['spy_vs_ma200']*100:.1f}% över MA200, VIX {vix_level:.1f}")
        elif bear_pts >= 2:
            result["regime"]     = "BJÖRN"
            result["confidence"] = min(1.0, bear_pts / 4)
            result["notes"].append(f"SPY {result['spy_vs_ma200']*100:.1f}% under MA200, VIX {vix_level:.1f}")
            if signals["vix_panic"]:
                result["notes"].append("⚠ VIX > 32 – panik-nivå")
        else:
            result["regime"] = "OSÄKER"
            result["notes"].append(f"Blandade signaler – VIX {vix_level:.1f}")

        _wc("regime", result)
        return result

    except Exception as e:
        print(f"  ⚠ Kunde inte hämta regim-data: {e}")
        return result


def adjusted_weights(base_weights: dict, regime: str) -> dict:
    """Justerar faktorvikter baserat på marknadsregim."""
    w = base_weights.copy()

    if regime == "BJÖRN":
        adjustments = {"quality": +0.08, "risk": +0.05, "dividend": +0.02,
                       "momentum": -0.07, "growth": -0.05, "value": -0.03}
    elif regime == "TJUR":
        adjustments = {"momentum": +0.03, "growth": +0.02, "value": -0.02, "dividend": -0.03}
    else:
        adjustments = {}

    for factor, adj in adjustments.items():
        if factor in w:
            w[factor] = max(0.0, w[factor] + adj)

    total = sum(w.values())
    if total > 0:
        w = {k: v / total for k, v in w.items()}

    return w


def adjusted_thresholds(regime: str) -> dict:
    """Returnerar threshold-justeringar baserat på regim."""
    if regime == "BJÖRN":
        return {"min_score_for_buy": 75, "min_confidence": "HÖG", "max_top_n": 10}
    elif regime == "TJUR":
        return {"min_score_for_buy": 60, "min_confidence": "MEDEL", "max_top_n": 50}
    else:
        return {"min_score_for_buy": 67, "min_confidence": "MEDEL", "max_top_n": 30}


def apply_regime_to_scored(scored: pd.DataFrame, regime_info: dict) -> pd.DataFrame:
    """
    Applicerar regim-justeringar på scored DataFrame.
    I björnmarknad: höjer krav för KÖP, dämpar entry-signaler.
    """
    df = scored.copy()
    regime = regime_info.get("regime", "OSÄKER")

    if regime == "BJÖRN" and "entry_signal" in df.columns:
        # Endast aktier med score >= 75 OCH HÖG konfidens får STARK
        thr = adjusted_thresholds(regime)
        min_score = thr["min_score_for_buy"]

        def downgrade(row):
            signal = row.get("entry_signal", "")
            score  = row.get("score_total", 0) or 0
            conf   = row.get("confidence_label", "")
            if signal == "STARK" and (score < min_score or conf != "HÖG"):
                return "VÄNTA"  # Nedgradera i björnmarknad
            return signal

        df["entry_signal"] = df.apply(downgrade, axis=1)

    return df


def build_regime_section(regime_info: dict, macro: dict = None) -> str:
    """Markdown-sektion för rapporten. Andra parametern är för kompatibilitet."""
    if not regime_info:
        return ""

    emoji = {"TJUR": "🐂", "BJÖRN": "🐻", "OSÄKER": "❓"}.get(regime_info["regime"], "")

    lines = [f"\n## {emoji} Marknadsregim: **{regime_info['regime']}**\n"]
    lines.append(f"_Konfidens: {regime_info['confidence']*100:.0f}%_  ")
    lines.append(f"_Per: {regime_info.get('as_of', '?')}_\n")

    lines.append("| Indikator | Värde |")
    lines.append("|-----------|-------|")
    if regime_info.get("spy_vs_ma200") is not None:
        lines.append(f"| SPY vs MA200 | {regime_info['spy_vs_ma200']*100:+.1f}% |")
    if regime_info.get("vix_level") is not None:
        lines.append(f"| VIX | {regime_info['vix_level']:.1f} |")
    if regime_info.get("spy_3m_return") is not None:
        lines.append(f"| SPY 3-mån | {regime_info['spy_3m_return']*100:+.1f}% |")

    if regime_info.get("notes"):
        lines.append("\n**Anmärkningar:**")
        for n in regime_info["notes"]:
            lines.append(f"- {n}")

    # Konsekvens för rekommendationer
    if regime_info["regime"] == "BJÖRN":
        lines.append("\n⚠ **Björnmarknads-läge aktivt:** Kraven för KÖP-signal är höjda. Endast aktier med score ≥ 75 OCH HÖG konfidens får STARK entry.")
    elif regime_info["regime"] == "TJUR":
        lines.append("\n✅ **Tjurmarknad:** Standardvikter används. Momentum-faktorn har lätt förhöjd vikt.")

    return "\n".join(lines)
