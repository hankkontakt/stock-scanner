"""
price_alerts.py — Prishantera prislarm.

PriceAlertManager hanterar användardefinierade prislarm:
  - set_alert(ticker, condition, target_price, note)
  - check_alerts(scored_df) — kollar alla larm mot senaste data
  - get_active_alerts() / get_triggered_history() — lista/sök
  - Sparar i data/price_alerts.json
  - Integrerar med AlertEngine
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    import pandas as pd

logger = logging.getLogger(__name__)

_PRICE_ALERTS_FILE = Path(__file__).resolve().parent.parent / "data" / "price_alerts.json"
_LOCK = threading.Lock()

# Villkor som stöds
CONDITIONS = [
    "above",            # Pris går över target
    "below",            # Pris går under target
    "crosses_ma50",     # Korsar MA50 uppåt
    "crosses_ma200",    # Korsar MA200 uppåt
    "rsi_above_70",     # RSI över 70 (överköpt)
    "rsi_below_30",     # RSI under 30 (översåld)
    "change_pct",       # Daglig procentuell förändring över target
    "volume_spike",     # Volym över target (andel av snitt)
]


class PriceAlertManager:
    """Hanterar användardefinierade prislarm."""

    def __init__(self, data_path: Optional[Path] = None) -> None:
        """
        Args:
            data_path: Sökväg till JSON-fil (default: data/price_alerts.json).
        """
        self._path = data_path or _PRICE_ALERTS_FILE
        self._alerts: list[dict[str, Any]] = []
        self._load()

    # ── CRUD ───────────────────────────────────────────────────────────

    def set_alert(
        self,
        ticker: str,
        condition: str,
        target_price: Optional[float] = None,
        note: str = "",
    ) -> tuple[bool, str]:
        """Skapa ett nytt prislarm.

        Args:
            ticker: Aktiens ticker (t.ex. "AAPL").
            condition: Villkor från CONDITIONS-listan.
            target_price: Målpris (krävs för above/below/change_pct/volume_spike).
            note: Valfri anteckning.

        Returns:
            (True, "OK") eller (False, "Felmeddelande").
        """
        ticker = ticker.strip().upper()
        condition = condition.strip().lower()

        if condition not in CONDITIONS:
            return False, f"Ogiltigt villkor '{condition}'. Välj från: {', '.join(CONDITIONS)}"

        if condition in ("above", "below", "change_pct", "volume_spike") and target_price is None:
            return False, f"Villkoret '{condition}' kräver ett target_price"

        with _LOCK:
            # Kolla om larmet redan finns (samma ticker + condition + price)
            for alert in self._alerts:
                if (alert["ticker"] == ticker
                        and alert["condition"] == condition
                        and alert.get("target_price") == target_price
                        and not alert.get("triggered")):
                    return False, f"Larm för {ticker} ({condition}) finns redan"

            alert: dict[str, Any] = {
                "ticker": ticker,
                "condition": condition,
                "target_price": target_price,
                "note": note.strip(),
                "created": datetime.now().isoformat()[:19],
                "triggered": False,
                "triggered_at": None,
                "triggered_price": None,
                "triggered_message": None,
            }
            self._alerts.append(alert)
            self._save()
            return True, f"Larm skapat för {ticker} ({condition})"

    def remove_alert(self, index: int) -> bool:
        """Ta bort ett larm via index.

        Args:
            index: Index i alertlistan.

        Returns:
            True om borttaget.
        """
        with _LOCK:
            if 0 <= index < len(self._alerts):
                self._alerts.pop(index)
                self._save()
                return True
            return False

    def clear_triggered(self) -> int:
        """Rensa alla utlösta larm.

        Returns:
            Antal borttagna larm.
        """
        with _LOCK:
            before = len(self._alerts)
            self._alerts = [a for a in self._alerts if not a.get("triggered")]
            self._save()
            return before - len(self._alerts)

    def update_alert(self, index: int, **kwargs) -> bool:
        """Uppdatera ett befintligt larm.

        Args:
            index: Index i alertlistan.
            **kwargs: Fält att uppdatera (target_price, note, condition).

        Returns:
            True om uppdaterat.
        """
        with _LOCK:
            if 0 <= index < len(self._alerts):
                alert = self._alerts[index]
                for key, val in kwargs.items():
                    if key in ("target_price", "note", "condition"):
                        if key == "condition" and val not in CONDITIONS:
                            return False
                        alert[key] = val
                alert["modified"] = datetime.now().isoformat()[:19]
                self._save()
                return True
            return False

    # ── Query ──────────────────────────────────────────────────────────

    def get_active_alerts(self, ticker: Optional[str] = None) -> list[dict[str, Any]]:
        """Hämta aktiva (ej utlösta) larm.

        Args:
            ticker: Valfri ticker att filtrera på.

        Returns:
            Lista av larm-dicts.
        """
        result = [a for a in self._alerts if not a.get("triggered")]
        if ticker:
            result = [a for a in result if a["ticker"] == ticker.upper()]
        return result

    def get_triggered_history(self, ticker: Optional[str] = None, days: int = 30) -> list[dict[str, Any]]:
        """Hämta utlösta larm inom N dagar.

        Args:
            ticker: Valfri ticker att filtrera på.
            days: Antal dagar bakåt.

        Returns:
            Lista av utlösta larm.
        """
        cutoff = datetime.now() - __import__("datetime").timedelta(days=days)
        result = []
        for a in self._alerts:
            if a.get("triggered") and a.get("triggered_at"):
                try:
                    triggered_dt = datetime.fromisoformat(a["triggered_at"])
                    if triggered_dt >= cutoff:
                        if ticker and a["ticker"] != ticker.upper():
                            continue
                        result.append(a)
                except (ValueError, TypeError):
                    result.append(a)
        return sorted(result, key=lambda x: x.get("triggered_at", ""), reverse=True)

    def get_all(self) -> list[dict[str, Any]]:
        """Hämta alla larm (aktiva + utlösta)."""
        return list(self._alerts)

    def count_active(self) -> int:
        """Antal aktiva larm."""
        return sum(1 for a in self._alerts if not a.get("triggered"))

    # ── Check-alerts (kör mot scored DataFrame) ────────────────────────

    def check_alerts(self, scored_df: "pd.DataFrame") -> list[dict[str, Any]]:
        """Kontrollera alla aktiva larm mot senaste prisdata.

        Args:
            scored_df: DataFrame med ticker, current_price/close,
                       rsi_14, volume, price_vs_ma50, price_vs_ma200, m.fl.

        Returns:
            Lista av nyligen utlösta larm (med trigger_info).
        """
        import pandas as pd

        if scored_df is None or scored_df.empty:
            return []

        # Bygg uppslagsdict
        df = scored_df.copy()
        if "ticker" not in df.columns:
            return []

        df = df.set_index("ticker")
        price_col = "current_price" if "current_price" in df.columns else "close"

        active = self.get_active_alerts()
        triggered: list[dict[str, Any]] = []

        for alert in active:
            ticker = alert["ticker"]
            if ticker not in df.index:
                continue

            row = df.loc[ticker]
            current_price = row.get(price_col) or row.get("close") or row.get("price")
            if current_price is None or pd.isna(current_price):
                continue

            current_price = float(current_price)
            condition = alert["condition"]
            target = alert.get("target_price")
            trigger_msg = None

            try:
                if condition == "above" and target is not None:
                    if current_price >= target:
                        trigger_msg = (
                            f"{ticker} nådde {current_price:.2f} — över målpris {target:.2f}"
                        )

                elif condition == "below" and target is not None:
                    if current_price <= target:
                        trigger_msg = (
                            f"{ticker} föll till {current_price:.2f} — under målpris {target:.2f}"
                        )

                elif condition == "crosses_ma50":
                    ma50 = row.get("price_vs_ma50")
                    if ma50 is not None and not pd.isna(ma50):
                        # price_vs_ma50 = (price/ma50 - 1). Negativt->positivt = kors uppåt
                        prev = row.get("price_vs_ma50")
                        # Vi har bara en snapshot, så vi kollar om priset är nära MA50
                        if -0.01 < float(ma50) < 0.01:
                            trigger_msg = (
                                f"{ticker} handlas nära MA50 ({float(ma50):.1%}) — "
                                f"pris {current_price:.2f}"
                            )

                elif condition == "crosses_ma200":
                    ma200 = row.get("price_vs_ma200")
                    if ma200 is not None and not pd.isna(ma200):
                        if -0.01 < float(ma200) < 0.01:
                            trigger_msg = (
                                f"{ticker} handlas nära MA200 ({float(ma200):.1%}) — "
                                f"pris {current_price:.2f}"
                            )

                elif condition == "rsi_above_70":
                    rsi = row.get("rsi_14")
                    if rsi is not None and not pd.isna(rsi):
                        if float(rsi) > 70:
                            trigger_msg = (
                                f"{ticker} RSI={float(rsi):.0f} — överköpt (över 70)"
                            )

                elif condition == "rsi_below_30":
                    rsi = row.get("rsi_14")
                    if rsi is not None and not pd.isna(rsi):
                        if float(rsi) < 30:
                            trigger_msg = (
                                f"{ticker} RSI={float(rsi):.0f} — översåld (under 30)"
                            )

                elif condition == "change_pct" and target is not None:
                    change = row.get("change_pct") or row.get("day_change_pct")
                    if change is not None and not pd.isna(change):
                        if abs(float(change)) >= target:
                            trigger_msg = (
                                f"{ticker} rörde sig {float(change):+.1f}% "
                                f"(tröskel: {target:+.0f}%)"
                            )

                elif condition == "volume_spike" and target is not None:
                    volume = row.get("volume")
                    avg_vol = row.get("avg_volume")
                    if (volume is not None and avg_vol is not None
                            and not pd.isna(volume) and not pd.isna(avg_vol)
                            and float(avg_vol) > 0):
                        ratio = float(volume) / float(avg_vol)
                        if ratio >= target:
                            trigger_msg = (
                                f"{ticker} volym {ratio:.1f}x snittet "
                                f"(tröskel: {target:.0f}x)"
                            )

                if trigger_msg:
                    alert["triggered"] = True
                    alert["triggered_at"] = datetime.now().isoformat()[:19]
                    alert["triggered_price"] = current_price
                    alert["triggered_message"] = trigger_msg

                    triggered.append(dict(alert))

            except (ValueError, TypeError) as e:
                logger.debug("check_alert error for %s: %s", ticker, e)
                continue

        # Spara uppdaterad state om något utlöstes
        if triggered:
            with _LOCK:
                self._save()

        return triggered

    # ── Integration med AlertEngine ────────────────────────────────────

    def check_and_alert(
        self,
        scored_df: "pd.DataFrame",
        engine: Any,
    ) -> list[dict[str, Any]]:
        """Kontrollera larm och skicka via AlertEngine.

        Args:
            scored_df: Scorad DataFrame.
            engine: AlertEngine-instans.

        Returns:
            Lista av utlösta larm.
        """
        triggered = self.check_alerts(scored_df)
        for alert in triggered:
            engine.send_alert(
                message_type="price_alert",
                message_data={
                    "message": alert["triggered_message"],
                    "ticker": alert["ticker"],
                    "title": f"Prislarm: {alert['ticker']}",
                    "condition": alert["condition"],
                    "price": alert.get("triggered_price"),
                },
                priority="MEDIUM",
            )
        return triggered

    # ── Interna ────────────────────────────────────────────────────────

    def _load(self) -> None:
        """Ladda larm från JSON-fil."""
        try:
            if self._path.exists():
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._alerts = data if isinstance(data, list) else data.get("alerts", [])
        except Exception as e:
            logger.debug("Kunde inte ladda prislarm: %s", e)
            self._alerts = []

    def _save(self) -> None:
        """Spara larm till JSON-fil."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "updated": datetime.now().isoformat()[:19],
                "count_active": self.count_active(),
                "alerts": self._alerts,
            }
            self._path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as e:
            logger.warning("Kunde inte spara prislarm: %s", e)
