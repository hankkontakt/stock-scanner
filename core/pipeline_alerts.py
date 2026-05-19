"""
pipeline_alerts.py – STARK signal alert system for daily_pipeline.py
"""
import json
import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

_STARK_STATE_FILE = Path(__file__).resolve().parent.parent / "data" / "stark_alert_state.json"


def _load_stark_state() -> dict:
    """Laddar state för senast sedda STARK-signaler per användare."""
    try:
        if _STARK_STATE_FILE.exists():
            return json.loads(_STARK_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_stark_state(state: dict):
    try:
        _STARK_STATE_FILE.write_text(
            json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except Exception:
        pass


def _send_stark_alerts(scored: "pd.DataFrame", date_str: str):
    """
    Kollar bevakningslista + innehav per prenumerant.
    Skickar ett omedelbart e-postlarm om en ny STARK-signal dyker upp
    (dvs. fanns ej i föregående körning).
    """
    from core.email_template import load_subscribers, send_email

    DATA_ROOT = Path(__file__).resolve().parent.parent / "data"

    # Bygg upp en snabb ticker→data-dict för alla STARK-aktier
    score_lu = scored.set_index("ticker").to_dict("index") if not scored.empty else {}
    stark_tickers: set[str] = {
        t for t, d in score_lu.items()
        if d.get("entry_signal") == "STARK" and (d.get("score_total") or 0) >= 60
    }

    if not stark_tickers:
        return  # Inga STARK-signaler alls idag → inget att skicka

    state    = _load_stark_state()
    new_state = state.copy()
    subscribers = load_subscribers()

    for sub in subscribers:
        if not sub.get("active"):
            continue
        if not sub.get("subscriptions", {}).get("stark_alerts", False):
            continue
        email = sub.get("email", "")
        if not email:
            continue

        uname    = sub.get("username", "")
        prev_seen: set[str] = set(state.get(uname or email, []))

        # Ladda användarens bevakningslista + innehav
        user_dir = DATA_ROOT if not uname or uname == "admin" else DATA_ROOT / "users" / uname
        watched: set[str] = set()
        try:
            wl_path = user_dir / "watchlist.json"
            if wl_path.exists():
                wl = json.loads(wl_path.read_text(encoding="utf-8"))
                watched.update(item["ticker"] for item in wl if item.get("ticker"))
        except Exception:
            pass
        try:
            h_path = user_dir / "holdings.csv"
            if h_path.exists():
                import pandas as _pd
                hdf = _pd.read_csv(h_path)
                watched.update(str(t).upper() for t in hdf["ticker"].dropna())
        except Exception:
            pass

        if not watched:
            continue

        # Nya STARK-signaler = finns i watched + är STARK idag + var INTE STARK senast
        new_stark = sorted(stark_tickers & watched - prev_seen)
        if not new_stark:
            new_state[uname or email] = list(stark_tickers & watched)
            continue

        # Bygg e-postinnehåll
        lines = [f"## ⚡ Nya STARK-signaler – {date_str}\n"]
        lines.append("Dessa aktier på din bevakning/portfölj har nu systemets starkaste köpsignal:\n")
        for t in new_stark:
            d = score_lu.get(t, {})
            score = d.get("score_total", 0) or 0
            trend = d.get("trend_signal", "—")
            price = d.get("current_price") or d.get("close")
            name  = d.get("name", t)
            p_str = f" | Kurs: {price:.2f}" if price else ""
            lines.append(
                f"- **{t}** ({name[:30]}) — Score: {score:.0f} | Trend: {trend}{p_str}"
            )
        lines.append(
            "\n\n> ⚠️ **Kontrollera alltid nyheter, trend och fundamenta innan du agerar.** "
            "En STARK-signal innebär att samtliga faktorer pekar uppåt — men ingen analys är "
            "en garanti för framtida avkastning."
        )

        ok = send_email(
            subject=f"⚡ STARK-signal: {', '.join(new_stark[:3])}{'…' if len(new_stark) > 3 else ''} – {date_str}",
            body_markdown="\n".join(lines),
            from_name="MarketScan",
            recipients=[email],
        )
        if ok:
            logger.info(f"  ⚡ STARK-larm skickat till {email}: {new_stark}")

        new_state[uname or email] = list(stark_tickers & watched)

    _save_stark_state(new_state)


def _get_rec(h: dict) -> str:
    """Rekommendation baserat på score och entry-signal."""
    score = h.get("score") or 0
    entry = h.get("entry", "—")
    pnl = h.get("pnl_pct") or 0

    if score >= 75 and entry == "STARK":
        return "KÖP MER 🟢"
    elif score >= 65 and entry in ("STARK", "OK"):
        return "BEHÅLL 🟢"
    elif score >= 50:
        return "BEVAKA 🟡"
    elif score >= 35:
        return "ÖVERVÄG MINSKA 🟠"
    else:
        return "SÄLJ/MINSKA 🔴"
