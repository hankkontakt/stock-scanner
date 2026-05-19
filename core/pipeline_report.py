"""
pipeline_report.py – Markdown/email report builder helpers for daily_pipeline.py
"""
import json
import logging

import pandas as pd

logger = logging.getLogger(__name__)


def _section(title: str, content: str, level: int = 2) -> str:
    """Bygg en markdown-sektion."""
    prefix = "#" * level
    return f"\n{prefix} {title}\n\n{content}\n"


def _table(headers: list, rows: list) -> str:
    """Bygg en markdown-tabell."""
    if not rows:
        return ""
    header = "| " + " | ".join(headers) + " |"
    sep = "| " + " | ".join(["---"] * len(headers)) + " |"
    data = []
    for row in rows:
        data.append("| " + " | ".join(str(c) for c in row) + " |")
    return header + "\n" + sep + "\n" + "\n".join(data) + "\n"


def _portfolio_table(enriched: list, show_stop_loss: bool = False) -> str:
    """Bygg en portföljtabell i markdown."""
    if not enriched:
        return "*(Inga innehav)*\n"

    headers = ["Ticker", "Score", "P&L", "Entry", "Trend"]
    if show_stop_loss:
        headers.append("Stop-loss")

    rows = []
    for h in enriched[:20]:
        pnl = f"{h['pnl_pct']:+.1f}%" if h['pnl_pct'] is not None else "—"
        row = [
            f"**{h['ticker']}**",
            f"{h['score']:.0f}" if h['score'] else "—",
            pnl,
            h['entry'],
            h['trend'],
        ]
        if show_stop_loss:
            sl = f"{h['stop_loss_pct']:+.1f}%" if h['stop_loss_pct'] else "—"
            row.append(sl)
        rows.append(row)

    return _table(headers, rows)


def _opportunity_section(opportunities: list) -> str:
    """Bygg opportunities-sektion."""
    if not opportunities:
        return ""
    out = "### ⚡ Dagens möjligheter\n\n"
    for opp in opportunities:
        emoji = opp.get("type", "•")
        ticker = opp["ticker"]
        score = opp.get("score", 0)
        reason = opp.get("reason", "")
        out += f"- {emoji} **{ticker}** (score {score:.0f}) – {reason}\n"
    return out + "\n"


def _section_header(title: str, subtitle: str = "") -> str:
    """Bygg en formaterad sektionsrubrik för mail."""
    s = f"## {title}"
    if subtitle:
        s += f" _{subtitle}_"
    return s + "\n"


def _build_ai_morning_context(indices, enriched, watchlist, top_10, bottom_5,
                               opportunities, news_text, regime, vix) -> str:
    """Bygg kontext för morgonbriefens AI-anrop."""
    ctx = {
        "indices": {t: {"change_pct": d["change_pct"], "close": d["close"]}
                    for t, d in indices.items() if d.get("change_pct") is not None},
        "portfolio": [{"ticker": h["ticker"], "pnl_total_pct": h["pnl_pct"],
                       "score": h["score"], "entry": h["entry"],
                       "stop_loss_pct": h["stop_loss_pct"], "rsi": h["rsi"]}
                      for h in enriched if h["ticker"]],
        "watchlist": [{"ticker": w, "score": None} for w in watchlist],
        "top_10": [{"ticker": t["ticker"], "score": t["score"], "entry": t["entry"]}
                   for t in top_10],
        "opportunities": opportunities,
        "news": news_text or "Inga större nyheter",
        "regime": regime or "OSÄKER",
        "vix": vix,
    }
    return json.dumps(ctx, ensure_ascii=False, default=str)


def _build_ai_evening_context(indices, enriched, watchlist, top_5, bottom_5,
                               opportunities, pnl_total, earnings_tomorrow, macro) -> str:
    """Bygg kontext för kvällsbrevets AI-anrop."""
    ctx = {
        "indices": {t: {"change_pct": d["change_pct"], "close": d["close"]}
                    for t, d in indices.items() if d.get("change_pct") is not None},
        "portfolio_daily_pnl": {"pct": pnl_total},
        "holdings": [{"ticker": h["ticker"], "pnl_daily_pct": h["pnl_pct"],
                      "score": h["score"], "entry": h["entry"],
                      "trend": h["trend"], "rsi": h["rsi"]}
                     for h in enriched],
        "watchlist_changes": watchlist,
        "top_5_today": [{"ticker": t["ticker"], "score": t["score"]} for t in top_5],
        "bottom_5_today": [{"ticker": b["ticker"], "score": b["score"]} for b in bottom_5],
        "opportunities": opportunities,
        "macro_tomorrow": macro or "Inga större makrohändelser imorgon",
        "earnings_tomorrow": earnings_tomorrow or [],
    }
    return json.dumps(ctx, ensure_ascii=False, default=str)


def _build_ai_weekly_context(scored, enriched, watchlist, top_10, bottom_5,
                              sector_momentum, opportunities, news, indices) -> str:
    """Bygg kontext för veckorapportens djupa AI-anrop."""
    sector_data = {}
    if "sector" in scored.columns and "score_total" in scored.columns:
        sec_agg = scored.groupby("sector")["score_total"].agg(["mean", "count", "max"])
        sector_data = sec_agg.to_dict("index")

    ctx = {
        "regime": "OSÄKER",
        "indices": {t: {"change_pct": d["change_pct"]}
                    for t, d in indices.items() if d.get("change_pct") is not None},
        "portfolio_weekly_summary": {
            "total_pnl_pct": sum(h["pnl_pct"] for h in enriched if h["pnl_pct"] is not None) / max(len([h for h in enriched if h["pnl_pct"] is not None]), 1),
            "best": max([h for h in enriched if h["pnl_pct"] is not None], key=lambda h: h["pnl_pct"], default={}).get("ticker", "—"),
            "worst": min([h for h in enriched if h["pnl_pct"] is not None], key=lambda h: h["pnl_pct"], default={}).get("ticker", "—"),
        },
        "holdings": enriched,
        "top_10_week": top_10,
        "bottom_5_warnings": bottom_5,
        "sector_momentum": {str(k): v for k, v in sector_data.items()},
        "opportunities": opportunities,
        "watchlist": watchlist,
        "news_highlights": news or [],
    }
    return json.dumps(ctx, ensure_ascii=False, default=str)


def _build_ai_smallcap_context(scored, enriched, watchlist, top_10, bottom_5,
                                opportunities, indices) -> str:
    """Bygg kontext för småbolagsrapportens AI-anrop."""
    ctx = {
        "universe": "smallcap",
        "n_stocks_scanned": len(scored) if not scored.empty else 0,
        "indices": {t: {"change_pct": d["change_pct"]}
                    for t, d in indices.items() if d.get("change_pct") is not None},
        "holdings": enriched,
        "top_10_smallcap": top_10,
        "bottom_5_warnings": bottom_5,
        "opportunities": opportunities,
        "watchlist": watchlist,
    }
    if not scored.empty and "score_total" in scored.columns:
        ctx["avg_score"] = float(scored["score_total"].mean())
        ctx["n_entry_ok"] = int((scored.get("entry_signal", pd.Series()) == "OK").sum())
    return json.dumps(ctx, ensure_ascii=False, default=str)
