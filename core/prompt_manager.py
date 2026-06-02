"""
core/prompt_manager.py - Prompt Management System
Hanterar mallar, versionering, A/B-testning och rendering.
Laddar templates från core/ai_prompts.py och håller versionshistorik.
"""

import hashlib
import json
import logging
import random
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

_logger = logging.getLogger(__name__)

# Fil för versionshistorik
_MODULE_DIR = Path(__file__).resolve().parent.parent
_VERSION_HISTORY_FILE = _MODULE_DIR / "data" / "prompt_version_history.json"


@dataclass
class PromptVersion:
    """En version av en prompt-template."""
    version: str
    content: str
    created_at: str = ""
    description: str = ""
    # A/B-testning: track vilken version som använts
    times_used: int = 0
    positive_signals: int = 0  # Antal signaler som gav rätt (trackas via journal)


class PromptTemplate:
    """En mall för AI-prompt med versionshantering och A/B-testning.

    Användning:
        template = PromptTemplate("stock_analysis")
        prompt_text = template.render({"ticker": "AAPL", "data": {...}})
    """

    def __init__(self, template_name: str, content: str = "",
                 version: str = "1.0", description: str = ""):
        """Skapa en PromptTemplate.

        Args:
            template_name: Namn på mallen (t.ex. "stock_analysis")
            content: Mall-text med {placeholders}
            version: Versionsnummer
            description: Kort beskrivning
        """
        self.name = template_name
        self.content = content
        self.description = description
        self.versions: list[PromptVersion] = []

        if content:
            self.versions.append(PromptVersion(
                version=version,
                content=content,
                created_at=datetime.now().isoformat()[:19],
                description=description,
            ))

    def render(self, context: dict, version: str = None, ab_test: bool = False) -> str:
        """Fyll i mallen med context-värden.

        Args:
            context: Dict med värden att fylla i
            version: Specifik versionssträng (t.ex. "1.0", "1.1", "A", "B")
            ab_test: Om True och version=None, slumpa mellan A/B-versioner

        Returns:
            Ifylld prompt-text
        """
        if ab_test and version is None:
            version = self._select_ab_version()

        selected_content = self._get_content(version)

        if not selected_content:
            # Fallback till första versionen
            if self.versions:
                selected_content = self.versions[0].content
            else:
                _logger.warning("Prompt '%s' har inga versioner!", self.name)
                return ""

        # Tracka användning
        if version:
            for v in self.versions:
                if v.version == version:
                    v.times_used += 1
                    break

        try:
            return selected_content.format(**context)
        except KeyError as e:
            # Om placeholder saknas i context, lämna den kvar
            _logger.warning("Saknad placeholder '%s' i prompt '%s'", e, self.name)
            return selected_content
        except Exception as e:
            _logger.error("Fel vid render av prompt '%s': %s", self.name, e)
            return selected_content

    def add_version(self, content: str, version: str = None,
                    description: str = "") -> str:
        """Lägg till en ny version av mallen.

        Args:
            content: Mall-text
            version: Versionssträng. Auto-inkrementeras om None
            description: Ändringsbeskrivning

        Returns:
            Versionssträngen
        """
        if version is None:
            # Auto-inkrementera
            if self.versions:
                last = max(float(v.version) for v in self.versions if v.version.replace(".", "").isdigit())
                version = f"{last + 0.1:.1f}"
            else:
                version = "1.0"

        self.versions.append(PromptVersion(
            version=version,
            content=content,
            created_at=datetime.now().isoformat()[:19],
            description=description or f"Version {version}",
        ))

        # Spara versionshistorik
        _save_version_history(self)
        return version

    def get_version(self, version: str) -> Optional[PromptVersion]:
        """Hämta en specifik version."""
        for v in self.versions:
            if v.version == version:
                return v
        return None

    def get_latest_version(self) -> Optional[str]:
        """Hämta senaste versionssträngen."""
        if not self.versions:
            return None
        return self.versions[-1].version

    def get_version_history(self) -> list[PromptVersion]:
        """Hämta alla versioner."""
        return list(self.versions)

    def _get_content(self, version: str = None) -> str:
        """Hämta content för en specifik version."""
        if version is None:
            return self.versions[-1].content if self.versions else ""

        for v in self.versions:
            if v.version == version:
                return v.content
        return ""

    def _select_ab_version(self) -> str:
        """Välj slumpmässigt mellan version A och B för A/B-test.

        Om inga A/B-versioner finns, returnera senaste versionen.

        Returns:
            Versionssträng ("A", "B", eller senaste)
        """
        ab_versions = [v for v in self.versions if v.version in ("A", "B")]
        if ab_versions:
            return random.choice(ab_versions).version

        # Fallback: om det finns minst 2 versioner, slumpa mellan de två senaste
        if len(self.versions) >= 2:
            return random.choice([self.versions[-1].version, self.versions[-2].version])

        return self.versions[-1].version if self.versions else ""

    def record_signal_outcome(self, version: str, was_correct: bool):
        """Registrera utfall för signal från denna prompt-version.

        Används för A/B-testning - tracka vilken version som ger bättre signaler.

        Args:
            version: Versionssträngen som användes
            was_correct: True om signalen visade sig korrekt
        """
        for v in self.versions:
            if v.version == version:
                v.times_used += 1
                if was_correct:
                    v.positive_signals += 1
                break


# ── Globalt register över templates ──────────────────────────────────────────

_templates: dict[str, PromptTemplate] = {}


def _load_prompts_from_module():
    """Ladda prompt-templates från core/ai_prompts.py."""
    try:
        from core import ai_prompts

        # Hämta alla SYSTEM_PROMPT_*-konstanter
        for attr_name in dir(ai_prompts):
            if attr_name.startswith("SYSTEM_PROMPT_"):
                template_name = attr_name.replace("SYSTEM_PROMPT_", "").lower()
                content = getattr(ai_prompts, attr_name)
                if isinstance(content, str) and len(content) > 50:
                    register_template(
                        template_name,
                        content,
                        description=f"System prompt: {template_name}",
                    )

        _logger.debug("Laddade %d templates från ai_prompts.py", len(_templates))
    except ImportError as e:
        _logger.warning("Kunde inte ladda ai_prompts.py: %s", e)
    except Exception as e:
        _logger.error("Fel vid laddning av prompts: %s", e)


def register_template(name: str, content: str, version: str = "1.0",
                      description: str = "") -> PromptTemplate:
    """Registrera en prompt-template.

    Args:
        name: Template-namn (t.ex. "stock_analysis")
        content: Prompt-text med {placeholders}
        version: Versionssträng
        description: Beskrivning

    Returns:
        PromptTemplate-instansen
    """
    name = name.lower().strip()
    if name in _templates:
        # Lägg till som ny version om den redan finns
        _templates[name].add_version(content, version=version, description=description)
    else:
        tpl = PromptTemplate(name, content, version=version, description=description)
        _templates[name] = tpl
    return _templates[name]


def get_template(name: str) -> Optional[PromptTemplate]:
    """Hämta en prompt-template.

    Args:
        name: Template-namn (case-insensitive)

    Returns:
        PromptTemplate eller None
    """
    name = name.lower().strip()

    # Lazy-load om inte redan laddad
    if not _templates:
        _load_prompts_from_module()

    return _templates.get(name)


def render(template_name: str, context: dict, version: str = None,
           ab_test: bool = False) -> str:
    """Fyll i en prompt-template med context.

    Args:
        template_name: Namnet på mallen
        context: Dict med värden att fylla i
        version: Specifik version
        ab_test: Om True, slumpa mellan A/B-versioner

    Returns:
        Ifylld prompt-text
    """
    tpl = get_template(template_name)
    if tpl is None:
        _logger.warning("Template '%s' hittades inte", template_name)
        return ""

    return tpl.render(context, version=version, ab_test=ab_test)


def list_templates() -> dict[str, PromptTemplate]:
    """Lista alla tillgängliga templates.

    Returns:
        Dict med template-namn -> PromptTemplate
    """
    if not _templates:
        _load_prompts_from_module()
    return dict(_templates)


def get_version_history(template_name: str) -> list[PromptVersion]:
    """Hämta versionshistorik för en template.

    Args:
        template_name: Template-namn

    Returns:
        Lista med PromptVersion-objekt
    """
    tpl = get_template(template_name)
    if tpl is None:
        return []
    return tpl.get_version_history()


def _save_version_history(template: PromptTemplate):
    """Spara versionshistorik till disk."""
    try:
        history = {}
        if _VERSION_HISTORY_FILE.exists():
            try:
                history = json.loads(_VERSION_HISTORY_FILE.read_text(encoding="utf-8"))
            except Exception:
                history = {}

        versions_json = []
        for v in template.versions:
            versions_json.append({
                "version": v.version,
                "created_at": v.created_at,
                "description": v.description,
                "times_used": v.times_used,
                "positive_signals": v.positive_signals,
            })

        history[template.name] = {
            "versions": versions_json,
            "description": template.description,
        }

        _VERSION_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        _VERSION_HISTORY_FILE.write_text(
            json.dumps(history, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        _logger.warning("Kunde inte spara versionshistorik: %s", e)


def load_version_history() -> dict:
    """Ladda versionshistorik från disk."""
    try:
        if _VERSION_HISTORY_FILE.exists():
            return json.loads(_VERSION_HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        _logger.warning("Kunde inte ladda versionshistorik: %s", e)
    return {}
