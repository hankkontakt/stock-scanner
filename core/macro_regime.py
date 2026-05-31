"""
macro_regime.py
===============
Detekterar marknadsregim (tjur/björn/osäker) och anpassar systemet därefter.

Logik (kontinuerlig scoring, 0.0 = extremt björn, 1.0 = extremt tjur):
  SPY vs MA200  (vikt 35%): -10% → 0.0, 0% → 0.5, +10% → 1.0
  VIX           (vikt 25%): 30+ → 0.0, 22.5 → 0.5, 15 → 1.0
  3m-momentum   (vikt 20%): -8% → 0.0, 0% → 0.5, +8% → 1.0
  Marknadsbredd (vikt 10%): RSP/SPY-kvot vs 60-dagars snitt (bred vs smal uppgång)
  Yieldkurva    (vikt 10%): 10y−3m Treasury-spread (inverterad = varning)

  composite >= 0.62 → TJUR
  composite <= 0.38 → BJÖRN
  annars           → OSÄKER

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
    except Exception: pass


def detect_regime() -> dict:
    """
    Hämtar SPY, VIX, RSP (marknadsbredd) och räntor.
    Klassificerar regim med kontinuerlig scoring istället för binära trösklar.
    """
    cached = _rc("regime", REGIME_CACHE)
    if cached is not None:
        return cached

    result = {
        "regime":        "OSÄKER",
        "spy_vs_ma200":  None,
        "vix_level":     None,
        "spy_3m_return": None,
        "breadth_delta": None,
        "yield_spread":  None,
        "credit_spread_delta": None,  # HYG/TLT ratio vs 20-day avg
        "composite":     None,
        "confidence":    0.5,
        "as_of":         datetime.now().strftime("%Y-%m-%d %H:%M"),
        "notes":         [],
    }

    try:
        # --- SPY: trend och momentum ---
        time.sleep(0.3)
        spy = yf.Ticker("SPY").history(period="1y")
        if spy.empty or len(spy) < 200:
            return result

        spy_close    = spy["Close"]
        current      = spy_close.iloc[-1]
        ma200        = spy_close.rolling(200).mean().iloc[-1]
        spy_vs_ma200 = float((current / ma200) - 1)
        spy_3m       = float((current / spy_close.iloc[-63] - 1) if len(spy_close) >= 63 else 0)

        result["spy_vs_ma200"]  = spy_vs_ma200
        result["spy_3m_return"] = spy_3m

        # --- VIX ---
        time.sleep(0.3)
        vix       = yf.Ticker("^VIX").history(period="3mo")
        vix_level = float(vix["Close"].iloc[-1]) if not vix.empty else 20.0
        result["vix_level"] = vix_level

        # --- Marknadsbredd: RSP/SPY-kvot (equal-weight vs cap-weight) ---
        # Stiger RSP mer än SPY = bred uppgång (bra); faller RSP relativt = smal/megabolags-driven uppgång
        breadth_component = 0.5
        try:
            time.sleep(0.3)
            rsp = yf.Ticker("RSP").history(period="6mo")
            if not rsp.empty:
                rsp_close   = rsp["Close"]
                spy_aligned = spy_close.reindex(rsp_close.index).ffill()
                ratio       = rsp_close / spy_aligned
                ratio_ma60  = ratio.rolling(60).mean().iloc[-1]
                ratio_now   = ratio.iloc[-1]
                breadth_delta = float((ratio_now / ratio_ma60) - 1)
                result["breadth_delta"] = breadth_delta
                breadth_component = float(np.clip(0.5 + breadth_delta * 5, 0.0, 1.0))
        except Exception:
            pass

        # --- Yieldkurva: 10-årig minus 3-månaders Treasury ---
        # ^TNX = 10-år, ^IRX = 13-veckor; båda i procent (t.ex. 4.3)
        yield_component = 0.5
        try:
            time.sleep(0.3)
            t10 = yf.Ticker("^TNX").history(period="1mo")
            t3m = yf.Ticker("^IRX").history(period="1mo")
            if not t10.empty and not t3m.empty:
                spread = float(t10["Close"].iloc[-1]) - float(t3m["Close"].iloc[-1])
                result["yield_spread"] = spread
                # +2% → 1.0 (normal), 0% → 0.5, -2% → 0.0 (kraftigt inverterad)
                yield_component = float(np.clip(0.5 + spread / 4, 0.0, 1.0))
        except Exception:
            pass

        # --- Kreditspread: HYG/TLT ratio (high-yield vs treasuries) ---
        # Stigande HYG vs TLT = risk-pa (bullish), fallande = risk-av (bearish)
        # Kreditspreadar vidgas INNAN aktier faller (1-2 v ledande indikator)
        credit_component = 0.5
        try:
            time.sleep(0.3)
            hyg = yf.Ticker("HYG").history(period="3mo")
            tlt = yf.Ticker("TLT").history(period="3mo")
            if not hyg.empty and not tlt.empty:
                hyg_close = hyg["Close"]
                tlt_close = tlt["Close"]
                ratio = hyg_close / tlt_close
                ratio_ma20 = ratio.rolling(20).mean().iloc[-1]
                ratio_now = ratio.iloc[-1]
                credit_delta = (ratio_now / ratio_ma20 - 1) if ratio_ma20 else 0
                result["credit_spread_delta"] = float(credit_delta)
                # ±5% → 0.0-1.0: -5% = 0.0 (kreditstress), 0% = 0.5, +5% = 1.0 (risk-pa)
                credit_component = float(np.clip(0.5 + credit_delta * 10, 0.0, 1.0))
        except Exception:
            pass

        # --- Kontinuerlig scoring per signal (0.0–1.0) ---
        spy_component = float(np.clip(0.5 + spy_vs_ma200 * 5,  0.0, 1.0))  # ±10% → ±0.5
        vix_component = float(np.clip(1 - (vix_level - 15) / 15, 0.0, 1.0)) # 15→1.0, 30→0.0
        mom_component = float(np.clip(0.5 + spy_3m * 6.25,    0.0, 1.0))  # ±8% → ±0.5

        composite = (
            spy_component     * 0.30 +  # Minskad från 0.35
            vix_component     * 0.20 +  # Minskad från 0.25
            mom_component     * 0.15 +  # Minskad från 0.20
            breadth_component * 0.10 +
            yield_component   * 0.10 +
            credit_component  * 0.15   # Ny: kreditspread (HYG/TLT)
        )
        result["composite"] = float(composite)

        # --- Klassificering ---
        if composite >= 0.62:
            result["regime"]     = "TJUR"
            result["confidence"] = min(0.85, composite)
        elif composite <= 0.38:
            result["regime"]     = "BJÖRN"
            result["confidence"] = min(0.85, 1 - composite)
        else:
            result["regime"]     = "OSÄKER"
            result["confidence"] = 0.5

        # --- Anteckningar ---
        result["notes"].append(
            f"SPY {spy_vs_ma200*100:+.1f}% vs MA200 | VIX {vix_level:.1f} | 3m {spy_3m*100:+.1f}%"
        )
        if result["breadth_delta"] is not None:
            label = "bred uppgång" if result["breadth_delta"] > 0.02 else \
                    "koncentrerad (megabolag)" if result["breadth_delta"] < -0.02 else "neutral bredd"
            result["notes"].append(f"Marknadsbredd (RSP/SPY): {result['breadth_delta']*100:+.1f}% → {label}")
        if result["yield_spread"] is not None:
            inv = " ⚠ INVERTERAD" if result["yield_spread"] < 0 else ""
            result["notes"].append(f"Yieldkurva (10y−3m): {result['yield_spread']:+.2f}%{inv}")
        if vix_level > 32:
            result["notes"].append("⚠ VIX > 32 – panik-nivå")
        if result.get("credit_spread_delta") is not None:
            credit_label = "risk-pa (HYG stiger)" if result["credit_spread_delta"] > 0.02 else \
                           "risk-av (HYG faller)" if result["credit_spread_delta"] < -0.02 else "neutral kreditmarknad"
            result["notes"].append(f"Kreditspread (HYG/TLT): {result['credit_spread_delta']*100:+.1f}% → {credit_label}")

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
    if regime_info.get("breadth_delta") is not None:
        lines.append(f"| Marknadsbredd (RSP/SPY) | {regime_info['breadth_delta']*100:+.1f}% |")
    if regime_info.get("yield_spread") is not None:
        inv = " ⚠" if regime_info["yield_spread"] < 0 else ""
        lines.append(f"| Yieldkurva (10y−3m) | {regime_info['yield_spread']:+.2f}%{inv} |")
    if regime_info.get("credit_spread_delta") is not None:
        lines.append(f"| Kreditspread (HYG/TLT) | {regime_info['credit_spread_delta']*100:+.1f}% |")
    if regime_info.get("composite") is not None:
        lines.append(f"| Sammansatt signal | {regime_info['composite']:.2f} / 1.00 |")

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
