"""
core/gdpr.py
============
GDPR Data Management for MarketScan.
Hanterar export, borttagning och anonymisering av anvandardata enligt GDPR.

Alla personuppgifts-operationer loggas i data/gdpr_log.json for revision.
"""

import csv
import hashlib
import io
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
GDPR_LOG = DATA_DIR / "gdpr_log.json"


def _log_gdpr(action: str, username: str, details: str = ""):
    """Logga en personuppgifts-operation for revision."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "action": action,
        "username": username,
        "details": details,
    }
    logs = []
    try:
        if GDPR_LOG.exists():
            logs = json.loads(GDPR_LOG.read_text(encoding="utf-8"))
    except Exception:
        logs = []
    logs.append(log_entry)
    try:
        GDPR_LOG.write_text(json.dumps(logs, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


class GDPRManager:
    """Hanterar GDPR-relaterade operationer for anvandardata."""

    PII_FILES = [
        "email_subscribers.json",
        "users_config.json",
        "activity_log.json",
        "password_reset_tokens.json",
    ]

    def __init__(self):
        self.data_dir = DATA_DIR

    # ── Data Inventory ───────────────────────────────────────────────────────────

    def get_data_inventory(self) -> list[dict]:
        """Lista ALLA datafiler med PII-innehall.

        Returns:
            Lista av dict med path, pii_fields, record_count.
        """
        inventory = []

        # email_subscribers.json
        es_path = self.data_dir / "email_subscribers.json"
        if es_path.exists():
            try:
                data = json.loads(es_path.read_text(encoding="utf-8"))
                count = len(data) if isinstance(data, list) else 0
                inventory.append({
                    "path": "data/email_subscribers.json",
                    "pii_fields": ["email", "username"],
                    "record_count": count,
                })
            except Exception:
                inventory.append({
                    "path": "data/email_subscribers.json",
                    "pii_fields": ["email", "username"],
                    "record_count": 0,
                })

        # users_config.json
        uc_path = self.data_dir / "users_config.json"
        if uc_path.exists():
            try:
                data = json.loads(uc_path.read_text(encoding="utf-8"))
                users = data.get("users", [])
                inventory.append({
                    "path": "data/users_config.json",
                    "pii_fields": ["username", "name", "email"],
                    "record_count": len(users),
                })
            except Exception:
                inventory.append({
                    "path": "data/users_config.json",
                    "pii_fields": ["username", "name", "email"],
                    "record_count": 0,
                })

        # activity_log.json
        al_path = self.data_dir / "activity_log.json"
        if al_path.exists():
            try:
                data = json.loads(al_path.read_text(encoding="utf-8"))
                count = len(data) if isinstance(data, list) else 0
                inventory.append({
                    "path": "data/activity_log.json",
                    "pii_fields": ["username"],
                    "record_count": count,
                })
            except Exception:
                inventory.append({
                    "path": "data/activity_log.json",
                    "pii_fields": ["username"],
                    "record_count": 0,
                })

        # password_reset_tokens.json
        pr_path = self.data_dir / "password_reset_tokens.json"
        if pr_path.exists():
            try:
                data = json.loads(pr_path.read_text(encoding="utf-8"))
                count = len(data) if isinstance(data, list) else 0
                inventory.append({
                    "path": "data/password_reset_tokens.json",
                    "pii_fields": ["username", "email"],
                    "record_count": count,
                })
            except Exception:
                inventory.append({
                    "path": "data/password_reset_tokens.json",
                    "pii_fields": ["username", "email"],
                    "record_count": 0,
                })

        # holdings.csv (anvandarens portfoljdata)
        hc_path = self.data_dir / "holdings.csv"
        if hc_path.exists():
            try:
                with open(hc_path, encoding="utf-8") as f:
                    count = sum(1 for _ in csv.DictReader(f))
                inventory.append({
                    "path": "data/holdings.csv",
                    "pii_fields": ["ticker (indirekt PII via portfolj)"],
                    "record_count": count,
                })
            except Exception:
                inventory.append({
                    "path": "data/holdings.csv",
                    "pii_fields": ["ticker (indirekt PII via portfolj)"],
                    "record_count": 0,
                })

        return inventory

    # ── Export User Data ─────────────────────────────────────────────────────────

    def export_user_data(self, username: str) -> dict:
        """Samla ALLA data om en anvandare.

        Args:
            username: Anvandarnamnet att exportera data for.

        Returns:
            Dict med all anvandardata.
        """
        user_data = {
            "username": username,
            "export_date": datetime.now().isoformat(),
            "data_sources": {},
        }

        # Hämta email_subscribers
        es_path = self.data_dir / "email_subscribers.json"
        if es_path.exists():
            try:
                data = json.loads(es_path.read_text(encoding="utf-8"))
                user_sub = [s for s in (data if isinstance(data, list) else [])
                           if s.get("username") == username]
                if user_sub:
                    user_data["data_sources"]["email_subscriptions"] = user_sub
            except Exception:
                pass

        # Hämta users_config
        uc_path = self.data_dir / "users_config.json"
        if uc_path.exists():
            try:
                data = json.loads(uc_path.read_text(encoding="utf-8"))
                users = data.get("users", [])
                user_cfg = [u for u in users if u.get("username") == username]
                if user_cfg:
                    user_data["data_sources"]["user_config"] = user_cfg
            except Exception:
                pass

        # Hämta activity_log
        al_path = self.data_dir / "activity_log.json"
        if al_path.exists():
            try:
                data = json.loads(al_path.read_text(encoding="utf-8"))
                user_activities = [a for a in (data if isinstance(data, list) else [])
                                  if a.get("username") == username]
                if user_activities:
                    user_data["data_sources"]["activity_log"] = user_activities
            except Exception:
                pass

        # Hämta password_reset_tokens
        pr_path = self.data_dir / "password_reset_tokens.json"
        if pr_path.exists():
            try:
                data = json.loads(pr_path.read_text(encoding="utf-8"))
                user_tokens = [t for t in (data if isinstance(data, list) else [])
                              if t.get("username") == username]
                if user_tokens:
                    user_data["data_sources"]["password_reset_tokens"] = user_tokens
            except Exception:
                pass

        # Hämta holdings
        hc_path = self.data_dir / "holdings.csv"
        if hc_path.exists():
            try:
                with open(hc_path, encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    rows = [r for r in reader]
                if rows:
                    user_data["data_sources"]["holdings"] = rows
            except Exception:
                pass

        _log_gdpr("export", username, f"Exporterade data for {username}")
        return user_data

    # ── Delete User Data ─────────────────────────────────────────────────────────

    def delete_user_data(self, username: str) -> bool:
        """Anonymisera/ta bort ALLA data om en anvandare.

        Args:
            username: Anvandarnamnet att ta bort data for.

        Returns:
            True om lyckades, False annars.
        """
        success = True

        # email_subscribers
        es_path = self.data_dir / "email_subscribers.json"
        if es_path.exists():
            try:
                data = json.loads(es_path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    data = [s for s in data if s.get("username") != username]
                    es_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                success = False

        # users_config (mark as deleted)
        uc_path = self.data_dir / "users_config.json"
        if uc_path.exists():
            try:
                data = json.loads(uc_path.read_text(encoding="utf-8"))
                users = data.get("users", [])
                data["users"] = [u for u in users if u.get("username") != username]
                uc_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                success = False

        # activity_log
        al_path = self.data_dir / "activity_log.json"
        if al_path.exists():
            try:
                data = json.loads(al_path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    data = [a for a in data if a.get("username") != username]
                    al_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                success = False

        # password_reset_tokens
        pr_path = self.data_dir / "password_reset_tokens.json"
        if pr_path.exists():
            try:
                data = json.loads(pr_path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    data = [t for t in data if t.get("username") != username]
                    pr_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                success = False

        # holdings (rensa)
        hc_path = self.data_dir / "holdings.csv"
        try:
            if hc_path.exists():
                # Skriv tom CSV med rubriker
                with open(hc_path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(["ticker", "shares", "cost_basis"])
        except Exception:
            success = False

        _log_gdpr("delete", username, f"Tog bort all data for {username}")
        return success

    # ── Anonymize User ──────────────────────────────────────────────────────────

    def anonymize_user(self, username: str) -> bool:
        """Anonymisera en anvandare - byt ut namn mot hash, behall analytics.

        Args:
            username: Anvandarnamnet att anonymisera.

        Returns:
            True om lyckades, False annars.
        """
        user_hash = hashlib.sha256(username.encode()).hexdigest()[:16]
        success = True

        # users_config: byt username till hash, ta bort email
        uc_path = self.data_dir / "users_config.json"
        if uc_path.exists():
            try:
                data = json.loads(uc_path.read_text(encoding="utf-8"))
                users = data.get("users", [])
                for u in users:
                    if u.get("username") == username:
                        u["username"] = f"anon_{user_hash}"
                        u["name"] = "Anonymiserad"
                        u["email"] = ""
                        u["anonymized"] = True
                        u["anonymized_at"] = datetime.now().isoformat()
                        break
                uc_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                success = False

        # activity_log: byt username till hash
        al_path = self.data_dir / "activity_log.json"
        if al_path.exists():
            try:
                data = json.loads(al_path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    for a in data:
                        if a.get("username") == username:
                            a["username"] = f"anon_{user_hash}"
                    al_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                success = False

        # email_subscribers: ta bort email, byt username
        es_path = self.data_dir / "email_subscribers.json"
        if es_path.exists():
            try:
                data = json.loads(es_path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    for s in data:
                        if s.get("username") == username:
                            s["username"] = f"anon_{user_hash}"
                            s["email"] = ""
                            s["anonymized"] = True
                    es_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                success = False

        # password_reset_tokens
        pr_path = self.data_dir / "password_reset_tokens.json"
        if pr_path.exists():
            try:
                data = json.loads(pr_path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    data = [t for t in data if t.get("username") != username]
                    pr_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                success = False

        _log_gdpr("anonymize", username, f"Anonymiserade {username} -> anon_{user_hash}")
        return success

    # ── Privacy Report ──────────────────────────────────────────────────────────

    def generate_privacy_report(self) -> dict:
        """Generera en GDPR-kompatibel rapport over personuppgiftsbehandlingen.

        Returns:
            Dict med rapportdata.
        """
        inventory = self.get_data_inventory()
        total_pii_records = sum(item.get("record_count", 0) for item in inventory)

        # Las GDPR-loggen
        gdpr_operations = []
        try:
            if GDPR_LOG.exists():
                gdpr_operations = json.loads(GDPR_LOG.read_text(encoding="utf-8"))
        except Exception:
            pass

        report = {
            "report_date": datetime.now().isoformat(),
            "organization": "MarketScan",
            "data_categories": inventory,
            "total_pii_records": total_pii_records,
            "data_retention_days": {
                "email_subscribers.json": "Tills avprenumeration",
                "users_config.json": "Tills konto raderas",
                "activity_log.json": "90 dagar",
                "password_reset_tokens.json": "24 timmar",
                "holdings.csv": "Tills konto raderas",
            },
            "gdpr_operations_count": len(gdpr_operations),
            "latest_operations": gdpr_operations[-20:] if gdpr_operations else [],
            "rights_info": {
                "right_to_access": "Anvand 'Exportera min data' i installningar.",
                "right_to_erasure": "Anvand 'Ta bort mitt konto' i installningar.",
                "right_to_rectification": "Kontakta admin for att andra uppgifter.",
                "right_to_data_portability": "Data kan exporteras som JSON eller CSV.",
            },
        }
        return report
