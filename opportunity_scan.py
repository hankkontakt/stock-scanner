"""
opportunity_scan.py
===================
Daglig möjlighetsscan – körs varje vardag kl 09:30 (CET).

Läser cachade fundamental-scores från söndagens vecko-scan och
kombinerar med färsk prisdata för att hitta:
  1. Dip i upptrend  – kvalitetsaktie som tillfälligt fallit
  2. Utbrott         – bryter ny 52-veckorshöjd med volym
  3. Översåld studs  – stark fundamental men kraftigt nedtryckt

Tar ~2–3 minuter. Skickar email bara om signaler hittas.
"""

import sys
import time
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import yfinance as yf

import config
import alerts


# ── Ladda senaste vecko-scores ─────────────────────────────────────────────

def load_latest_scores(min_score: float = 55.0):
    """Ladda senaste scored_universe CSV. Returnerar (df, age_days) eller None."""
    csvs = sorted(Path(config.REPORT_DIR).glob("scored_universe_*.csv"), reverse=True)
    if not csvs:
        return None

    df = pd.read_csv(csvs[0])
    try:
        age_days = (date.today() - date.fromisoformat(csvs[0].stem.split("_")[-1])).days
    except Exception:
        age_days = 0

    cols = [c for c in ["ticker", "name", "sector", "score_total",
                         "entry_signal", "confidence_label"] if c in df.columns]
    df = df[cols][df["score_total"] >= min_score].copy()
    return df, age_days


# ── Hämta färsk prisdata ───────────────────────────────────────────────────

def fetch_price_data(tickers: list) -> dict:
    """Hämtar 3 månaders prishistorik + volym för varje ticker."""
    result = {}
    for ticker in tickers:
        try:
            time.sleep(0.25)
            hist = yf.Ticker(ticker).history(period="3mo", auto_adjust=True)
            if len(hist) >= 15:
                result[ticker] = hist
        except Exception:
            pass
    return result


# ── Detektera möjligheter ──────────────────────────────────────────────────

def detect_opportunities(scores_df: pd.DataFrame, price_data: dict) -> dict:
    dips, breakouts, oversold = [], [], []

    for _, row in scores_df.iterrows():
        ticker = row["ticker"]
        hist   = price_data.get(ticker)
        if hist is None:
            continue

        score  = float(row.get("score_total", 0))
        closes = hist["Close"]
        volume = hist["Volume"]

        curr    = float(closes.iloc[-1])
        p3d     = float(closes.iloc[-4])  if len(closes) >= 4  else None
        p5d     = float(closes.iloc[-6])  if len(closes) >= 6  else None
        p20d    = float(closes.iloc[-21]) if len(closes) >= 21 else None
        high52  = float(closes.max())
        avgvol  = float(volume.iloc[-21:-1].mean()) if len(volume) >= 21 else None
        todvol  = float(volume.iloc[-1])

        ret3d   = (curr / p3d  - 1) * 100 if p3d  else None
        ret5d   = (curr / p5d  - 1) * 100 if p5d  else None
        ret20d  = (curr / p20d - 1) * 100 if p20d else None
        dist52h = (curr / high52 - 1) * 100
        volrat  = (todvol / avgvol) if avgvol and avgvol > 0 else None

        base = {
            "ticker":    ticker,
            "name":      str(row.get("name", ""))[:24],
            "sector":    str(row.get("sector", "")),
            "score":     score,
            "price":     round(curr, 2),
            "entry":     str(row.get("entry_signal", "—")),
            "ret3d":     round(ret3d,  1) if ret3d  is not None else None,
            "ret5d":     round(ret5d,  1) if ret5d  is not None else None,
            "dist52h":   round(dist52h, 1),
            "volrat":    round(volrat,  1) if volrat is not None else None,
        }

        # 1. Dip i upptrend
        if score >= 65 and ret3d is not None and -12 < ret3d < -3:
            if ret20d is None or ret20d > -20:
                dips.append({**base, "signal": f"Dip {ret3d:+.1f}% (3d)"})

        # 2. Utbrott nära 52v-höjd med hög volym
        if score >= 60 and dist52h >= -3 and volrat is not None and volrat >= 1.5:
            breakouts.append({**base, "signal": f"Utbrott, vol {volrat:.1f}x snitt"})

        # 3. Översåld studs
        if score >= 70 and ret5d is not None and ret5d < -8:
            oversold.append({**base, "signal": f"Översåld {ret5d:+.1f}% (5d)"})

    key = lambda x: x["score"]
    return {
        "dips":      sorted(dips,      key=key, reverse=True)[:8],
        "breakouts": sorted(breakouts, key=key, reverse=True)[:6],
        "oversold":  sorted(oversold,  key=key, reverse=True)[:5],
    }


# ── Bygg rapport ───────────────────────────────────────────────────────────

def build_report(opps: dict, benchmarks: dict, age_days: int) -> str:
    today = datetime.now().strftime("%Y-%m-%d %H:%M")
    total = sum(len(v) for v in opps.values())

    lines = [
        f"# 🎯 Möjlighetsscan – {today}",
        f"_Fundamental scores {age_days} dag(ar) gamla · färsk prisdata_\n",
        "---\n",
    ]

    if benchmarks:
        lines.append("## 🌍 Marknaden\n")
        lines.append("| Index | Idag | 1 mån | YTD |")
        lines.append("|-------|------|-------|-----|")
        for name, d in benchmarks.items():
            d1, m1, ytd = d.get("change_1d",0), d.get("change_1m",0), d.get("change_ytd",0)
            lines.append(f"| {name} | {d1:+.1f}% | {m1:+.1f}% | {ytd:+.1f}% |")
        lines.append("")

    def table(items, headers, keys):
        if not items:
            return "_Inga signaler idag_\n"
        out = ["| " + " | ".join(headers) + " |",
               "| " + " | ".join(["---"] * len(headers)) + " |"]
        for item in items:
            out.append("| " + " | ".join(str(item.get(k, "—")) for k in keys) + " |")
        return "\n".join(out) + "\n"

    lines.append("## 🟢 Dip i upptrend – tillfälligt köpläge\n")
    lines.append(table(opps["dips"],
        ["Ticker", "Bolag", "Score", "Pris", "3d", "Entry", "Signal"],
        ["ticker", "name",  "score", "price","ret3d","entry","signal"]))

    lines.append("## 🚀 Utbrott – nära 52-veckorshöjd\n")
    lines.append(table(opps["breakouts"],
        ["Ticker", "Bolag", "Score", "Pris", "Från topp", "Signal"],
        ["ticker", "name",  "score", "price","dist52h",   "signal"]))

    lines.append("## 🔴 Översålda kvalitetsaktier – studsläge?\n")
    lines.append(table(opps["oversold"],
        ["Ticker", "Bolag", "Score", "Pris", "5d", "Signal"],
        ["ticker", "name",  "score", "price","ret5d","signal"]))

    lines.append(f"\n---\n_Totalt {total} signaler · Inte finansiell rådgivning_")
    return "\n".join(lines)


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    print("🎯 MÖJLIGHETSSCAN")
    print("=" * 40)

    # 1. Ladda vecko-scores
    print("📂 Laddar scores från vecko-scan...")
    result = load_latest_scores(min_score=55)
    if result is None:
        print("❌ Ingen vecko-scan hittad – kör scan.py först")
        sys.exit(1)
    scores_df, age_days = result
    print(f"   {len(scores_df)} aktier med score ≥55 (scores {age_days}d gamla)")

    # 2. Hämta prisdata för topp 120
    top = list(scores_df.head(120)["ticker"])
    print(f"📥 Hämtar prisdata för {len(top)} aktier (~2 min)...")
    price_data = fetch_price_data(top)
    print(f"   ✓ {len(price_data)} aktier hämtade")

    # 3. Benchmark
    print("🌍 Hämtar benchmark...")
    try:
        benchmarks = data_fetcher.fetch_benchmark_performance()
    except Exception:
        benchmarks = {}

    # 4. Hitta möjligheter
    print("🔍 Analyserar signaler...")
    opps  = detect_opportunities(scores_df, price_data)
    total = sum(len(v) for v in opps.values())
    print(f"   {len(opps['dips'])} dips · {len(opps['breakouts'])} utbrott · {len(opps['oversold'])} översålda")

    # 5. Spara rapport
    report = build_report(opps, benchmarks, age_days)
    Path("reports").mkdir(exist_ok=True)
    path = Path(f"reports/opportunity_{date.today().isoformat()}.md")
    path.write_text(report, encoding="utf-8")

    # 6. Skicka email bara om det finns signaler
    if total > 0 and alerts.email_configured():
        print("✉ Skickar email...")
        alerts._send_email(
            subject=f"🎯 MarketScan: {total} möjligheter – {date.today().strftime('%d %b')}",
            body_html=alerts._markdown_to_html(report),
            body_text=report,
        )
    elif total == 0:
        print("ℹ Inga signaler idag – email ej skickat")

    print(f"\n✅ KLART – rapport: {path}")


if __name__ == "__main__":
    main()
