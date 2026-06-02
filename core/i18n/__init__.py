"""
core/i18n/__init__.py
=====================
Internationaliseringssystem (i18n) for MarketScan.
Hanterar oversattningar, locale-detection och datum/tid-format.

Anvandning:
    from core.i18n import TranslationManager
    T = TranslationManager("sv")
    print(T.t("portfolio"))           # "Portfolj"
    print(T.t("pe_ratio", value=15))  # "P/E-tal: 15"
"""

from datetime import datetime
from typing import Optional


class TranslationManager:
    """Hanterar oversattningar for en given locale."""

    _instances: dict = {}

    def __new__(cls, locale: str = "sv"):
        """Singleton per locale - undviker att ladda samma oversattningar flera ganger."""
        if locale not in cls._instances:
            instance = super().__new__(cls)
            instance._initialized = False
            cls._instances[locale] = instance
        return cls._instances[locale]

    def __init__(self, locale: str = "sv"):
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self.locale = locale
        self.translations = {}
        self._load_translations(locale)

    def _load_translations(self, locale: str) -> None:
        """Ladda oversattningar for en locale."""
        try:
            if locale == "sv":
                from core.i18n.sv import TRANSLATIONS as t
            elif locale == "en":
                from core.i18n.en import TRANSLATIONS as t
            elif locale == "de":
                from core.i18n.de import TRANSLATIONS as t
            else:
                from core.i18n.sv import TRANSLATIONS as t
            self.translations = dict(t)
        except ImportError:
            self.translations = {}

    def t(self, key: str, **kwargs) -> str:
        """Oversatt en nyckel med valfria parametrar.

        Args:
            key: Oversattningsnyckel
            **kwargs: Parametrar att formattera in i oversattningen

        Returns:
            Oversatt text, eller nyckeln om oversattning saknas.
        """
        template = self.translations.get(key, key)
        try:
            return template.format(**kwargs) if kwargs else template
        except (KeyError, ValueError):
            return template

    def set_locale(self, locale: str) -> None:
        """Byt locale och ladda om oversattningar."""
        if locale != self.locale:
            self.locale = locale
            self._load_translations(locale)

    @staticmethod
    def format_date(dt: datetime, locale: str = "sv") -> str:
        """Formatera datum enligt locale.

        Args:
            dt: Datum-objekt att formatera
            locale: Sprak ("sv", "en", "de")

        Returns:
            Formaterat datum som strang
        """
        if locale == "sv":
            return dt.strftime("%Y-%m-%d")
        elif locale == "en":
            return dt.strftime("%b %d, %Y")
        elif locale == "de":
            return dt.strftime("%d.%m.%Y")
        return dt.strftime("%Y-%m-%d")

    @staticmethod
    def format_datetime(dt: datetime, locale: str = "sv") -> str:
        """Formatera datum och tid enligt locale."""
        if locale == "sv":
            return dt.strftime("%Y-%m-%d %H:%M")
        elif locale == "en":
            return dt.strftime("%b %d, %Y %I:%M %p")
        elif locale == "de":
            return dt.strftime("%d.%m.%Y %H:%M")
        return dt.strftime("%Y-%m-%d %H:%M")

    @staticmethod
    def format_number(value: float, locale: str = "sv", decimals: int = 2) -> str:
        """Formatera nummer enligt locale (decimal- och tusentalsavskiljare).

        sv: 1 234,56
        en: 1,234.56
        de: 1.234,56
        """
        if locale == "sv":
            return f"{value:,.{decimals}f}".replace(",", " ").replace(".", ",")
        elif locale == "de":
            formatted = f"{value:,.{decimals}f}"
            # Byt: tusentalsavskiljare , -> ., decimal . -> ,
            int_part, dec_part = formatted.split(".")
            int_part = int_part.replace(",", ".")
            return f"{int_part},{dec_part}"
        else:
            return f"{value:,.{decimals}f}"

    @staticmethod
    def format_currency(value: float, locale: str = "sv", currency: str = "SEK") -> str:
        """Formatera valuta enligt locale."""
        formatted = TranslationManager.format_number(value, locale)
        if locale == "sv":
            return f"{formatted} {currency}"
        elif locale == "de":
            return f"{formatted} {currency}"
        else:
            return f"{currency} {formatted}"

    @staticmethod
    def format_pct(value: float, locale: str = "sv") -> str:
        """Formatera procent enligt locale."""
        formatted = TranslationManager.format_number(value * 100, locale)
        if locale == "sv":
            return f"{formatted} %"
        elif locale == "de":
            return f"{formatted} %"
        else:
            return f"{formatted}%"

    def get_locale_name(self, locale: str = None) -> str:
        """Returnera sprakets namn pa det aktuella spraket."""
        locale = locale or self.locale
        names = {
            "sv": {"sv": "Svenska", "en": "Swedish", "de": "Schwedisch"},
            "en": {"sv": "Engelska", "en": "English", "de": "Englisch"},
            "de": {"sv": "Tyska", "en": "German", "de": "Deutsch"},
        }
        return names.get(locale, {}).get(self.locale, locale)

    def available_locales(self) -> list:
        """Returnera tillgangliga locales."""
        return ["sv", "en", "de"]
