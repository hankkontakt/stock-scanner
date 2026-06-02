"""
strategy/dsl.py
===============
Domän-specifikt språk (DSL) för strategier.

Möjliggör definition av strategier i YAML-format som sedan
kan parsas och köras automatiskt.

Exempel:
    STRATEGY = '''
    name: "Min trendstrategi"
    type: "trend_following"
    params:
        fast_ma: 50
        slow_ma: 200
    filters:
        - adx > 25
        - volume > 1000000
    risk:
        stop_loss: 0.05
        trailing_stop: True
        max_position: 0.2
    costs:
        commission: 0.001
        slippage: 0.0005
    '''
"""

import copy
import re
from typing import Any, Optional

import numpy as np
import pandas as pd

from strategy.base import Strategy, run_backtest


# ── Strategi-registry ──────────────────────────────────────────────────────────

_STRATEGY_REGISTRY = {}

def register_strategy(strategy_type: str, strategy_class):
    """Registrera en strategiklass för DSL-användning."""
    _STRATEGY_REGISTRY[strategy_type] = strategy_class

def get_strategy_class(strategy_type: str):
    """Hämta en strategiklass från registryt."""
    return _STRATEGY_REGISTRY.get(strategy_type)


# Registrera standardstrategier (görs vid import)
def _register_defaults():
    try:
        from strategy.strategies.momentum_strategy import (
            TimeSeriesMomentum, CrossSectionalMomentum, DualMomentum, SeasonalityStrategy
        )
        register_strategy("time_series_momentum", TimeSeriesMomentum)
        register_strategy("cross_sectional_momentum", CrossSectionalMomentum)
        register_strategy("dual_momentum", DualMomentum)
        register_strategy("seasonality", SeasonalityStrategy)

        from strategy.strategies.mean_reversion_strategy import (
            BollingerMeanReversion, RSIMeanReversion, PairsTrading,
            MovingAverageCrossover, MACDStrategy
        )
        register_strategy("bollinger_mean_reversion", BollingerMeanReversion)
        register_strategy("rsi_mean_reversion", RSIMeanReversion)
        register_strategy("pairs_trading", PairsTrading)
        register_strategy("ma_crossover", MovingAverageCrossover)
        register_strategy("macd", MACDStrategy)

        from strategy.strategies.trend_following_strategy import (
            TrendFollowing, DonchianBreakout, SupertrendStrategy, ParabolicSARStrategy
        )
        register_strategy("trend_following", TrendFollowing)
        register_strategy("donchian_breakout", DonchianBreakout)
        register_strategy("supertrend", SupertrendStrategy)
        register_strategy("parabolic_sar", ParabolicSARStrategy)

        from strategy.strategies.factor_strategy import (
            FactorCompositeStrategy, TopNStrategy, SectorRotationStrategy, FactorTimingStrategy
        )
        register_strategy("factor_composite", FactorCompositeStrategy)
        register_strategy("top_n", TopNStrategy)
        register_strategy("sector_rotation", SectorRotationStrategy)
        register_strategy("factor_timing", FactorTimingStrategy)
    except ImportError:
        pass  # Vissa strategier kanske inte är tillgängliga


_register_defaults()


# ── YAML-liknande parser (ingen extern dependency) ─────────────────────────────

class _YamlLikeParser:
    """
    Enkel YAML-liknande parser som hanterar grundläggande struktur.
    Använder indrag för hierarki, stödjer strängar, siffror, boolean, listor.
    """

    @staticmethod
    def parse(text: str) -> dict:
        """Parse:a YAML-liknande text till en dict."""
        result = {}
        lines = text.strip().split("\n")
        # Ta bort första och sista raden om de är trippel-citat
        if lines and lines[0].strip().startswith('"""') or lines[0].strip().startswith("'''"):
            lines = lines[1:]
        if lines and (lines[-1].strip().endswith('"""') or lines[-1].strip().endswith("'''")):
            lines[-1] = lines[-1].strip()[:-3]
            if not lines[-1].strip():
                lines = lines[:-1]

        stack = [(result, -1)]  # (current_dict, indent_level)

        for line in lines:
            stripped = line.rstrip()
            if not stripped.strip() or stripped.strip().startswith("#"):
                continue

            indent = len(line) - len(line.lstrip())
            content = stripped.strip()

            # Ta bort citattecken
            if len(content) >= 2 and content[0] in ('"', "'") and content[-1] in ('"', "'"):
                content = content[1:-1]

            # Pop stack till rätt indent-level
            while len(stack) > 1 and indent <= stack[-1][1]:
                stack.pop()

            # Nyckel-värde eller nyckel-lista
            if ":" in content and not content.startswith("-"):
                key, _, value = content.partition(":")
                key = key.strip()
                value = value.strip()

                # Navigera till rätt dict
                current = stack[-1][0]

                # Om värdet är tomt, starta en ny sub-dict
                if not value:
                    new_dict = {}
                    if isinstance(current, dict):
                        current[key] = new_dict
                    stack.append((new_dict, indent))
                else:
                    parsed_value = _YamlLikeParser._parse_value(value)
                    if isinstance(current, dict):
                        current[key] = parsed_value
                    elif isinstance(current, list):
                        current.append({key: parsed_value})

            elif content.startswith("- "):
                # List-element
                item_text = content[2:].strip()
                current = stack[-1][0]
                if isinstance(current, dict):
                    # Hitta eller skapa en lista
                    list_key = None
                    for k in current:
                        if isinstance(current[k], list):
                            list_key = k
                            break
                    if list_key is None:
                        list_key = "items"
                        current[list_key] = []
                    current[list_key].append(_YamlLikeParser._parse_value(item_text))
                elif isinstance(current, list):
                    current.append(_YamlLikeParser._parse_value(item_text))

        return result

    @staticmethod
    def _parse_value(value: str) -> Any:
        """Parse:a ett YAML-värde till rätt Python-typ."""
        value = value.strip()

        if value.lower() == "true":
            return True
        if value.lower() == "false":
            return False
        if value.lower() == "none" or value.lower() == "null":
            return None

        # Försök som heltal
        try:
            return int(value)
        except ValueError:
            pass

        # Försök som flyttal
        try:
            return float(value)
        except ValueError:
            pass

        # Sträng (ta bort citattecken)
        if len(value) >= 2 and value[0] in ('"', "'") and value[-1] in ('"', "'"):
            return value[1:-1]

        return value


# ── Filter-utvärdering ────────────────────────────────────────────────────────

def _evaluate_filters(filters: list, data_row: pd.Series) -> bool:
    """
    Utvärdera filter mot en datarad.

    filters:  Lista med filtersträngar som "adx > 25", "volume > 1000000"
    data_row: En rad med data

    Return: True om alla filter passeras
    """
    if not filters:
        return True

    for filter_str in filters:
        # Parse:a filter: "kolumn operator värde"
        match = re.match(r"(\w+)\s*([><!=]+)\s*([\w.]+)", filter_str)
        if not match:
            continue

        col, op, val_str = match.groups()
        val = float(val_str) if "." in val_str or val_str.isdigit() else val_str

        if col not in data_row.index:
            continue

        row_val = data_row[col]
        if pd.isna(row_val):
            return False

        try:
            row_val = float(row_val)
            val = float(val)
        except (ValueError, TypeError):
            pass

        if op == ">" and not (row_val > val):
            return False
        elif op == "<" and not (row_val < val):
            return False
        elif op == ">=" and not (row_val >= val):
            return False
        elif op == "<=" and not (row_val <= val):
            return False
        elif op == "==" and not (row_val == val):
            return False
        elif op == "!=" and not (row_val != val):
            return False

    return True


# ── Huvudfunktioner ────────────────────────────────────────────────────────────

def parse_strategy(yaml_str: str) -> Strategy:
    """
    Parse:a en YAML-strategidefinition till ett Strategy-objekt.

    yaml_str: YAML-formatterad strategidefinition

    Return: Strategy-instans
    """
    parsed = _YamlLikeParser.parse(yaml_str)

    name = parsed.get("name", "DSL-strategi")
    strategy_type = parsed.get("type", "")
    params = parsed.get("params", {})

    # Hitta strategiklass
    strategy_class = get_strategy_class(strategy_type)
    if strategy_class is None:
        raise ValueError(f"Okänd strategityp: '{strategy_type}'. "
                         f"Tillgängliga: {list(_STRATEGY_REGISTRY.keys())}")

    # Skapa strategi-instans
    strategy = strategy_class(name=name, params=params)

    # Lägg till extra metadata
    strategy._dsl_meta = {
        "filters": parsed.get("filters", []),
        "risk": parsed.get("risk", {}),
        "costs": parsed.get("costs", {}),
    }

    return strategy


def run_dsl_strategy(yaml_str: str, data: pd.DataFrame,
                     initial_capital: float = 100000.0) -> dict:
    """
    Kör en hel strategi från DSL-definition.

    yaml_str:        YAML-strategidefinition
    data:            Prisdata
    initial_capital: Startkapital

    Return: dict med backtestresultat
    """
    strategy = parse_strategy(yaml_str)
    meta = getattr(strategy, "_dsl_meta", {})

    # Applicera filter på data
    filters = meta.get("filters", [])
    if filters and "Close" in data.columns:
        filtered_data = data.copy()
        # För multi-asset: applicera filter radvis
        for idx in filtered_data.index:
            row = filtered_data.loc[idx]
            if isinstance(row, pd.DataFrame):
                row = row.iloc[-1]
            if not _evaluate_filters(filters, row):
                filtered_data.loc[idx, "Close"] = np.nan
        data = filtered_data.dropna(subset=["Close"])

    # Kör backtest
    result = run_backtest(strategy, data, initial_capital)

    # Lägg till metadata
    output = {
        "strategy": strategy.name,
        "type": yaml_str.split("\n")[1] if len(yaml_str.split("\n")) > 1 else "",
        "result": result,
        "meta": meta,
    }

    return output


def validate_strategy(yaml_str: str) -> dict:
    """
    Validera en DSL-strategidefinition.

    yaml_str: YAML-formatterad strategidefinition

    Return: dict med valid (bool), errors (list), warnings (list)
    """
    errors = []
    warnings = []

    try:
        parsed = _YamlLikeParser.parse(yaml_str)
    except Exception as e:
        return {"valid": False, "errors": [f"YAML-parsning misslyckades: {e}"], "warnings": []}

    # Krävda fält
    required_fields = ["name", "type"]
    for field in required_fields:
        if field not in parsed:
            errors.append(f"Saknat obligatoriskt fält: '{field}'")

    # Validera typ
    strategy_type = parsed.get("type", "")
    if strategy_type and strategy_type not in _STRATEGY_REGISTRY:
        warnings.append(
            f"Okänd strategityp: '{strategy_type}'. "
            f"Tillgängliga: {list(_STRATEGY_REGISTRY.keys())}"
        )

    # Validera params
    params = parsed.get("params", {})
    if not isinstance(params, dict):
        errors.append("'params' måste vara en dictionary")

    # Validera filters
    filters = parsed.get("filters", [])
    if isinstance(filters, list):
        for f in filters:
            if not re.match(r"\w+\s*[><!=]+\s*[\w.]+", str(f)):
                warnings.append(f"Filter kan ha fel format: '{f}'")
    elif filters:
        warnings.append("'filters' bör vara en lista av filtersträngar")

    # Validera risk
    risk = parsed.get("risk", {})
    if isinstance(risk, dict):
        if risk.get("stop_loss") is not None:
            try:
                sl = float(risk["stop_loss"])
                if sl <= 0 or sl >= 1:
                    warnings.append(f"stop_loss ({sl}) är ovanlig. Förväntas 0-1 (t.ex. 0.05 = 5%)")
            except (ValueError, TypeError):
                errors.append("stop_loss måste vara ett tal")
        if risk.get("max_position") is not None:
            try:
                mp = float(risk["max_position"])
                if mp <= 0 or mp > 1:
                    warnings.append(f"max_position ({mp}) bör vara 0-1")
            except (ValueError, TypeError):
                errors.append("max_position måste vara ett tal")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
    }


def dsl_to_yaml(strategy_obj: Strategy) -> str:
    """
    Exportera en Strategy-instans till DSL YAML-format.

    strategy_obj: Strategy-instans

    Return: YAML-sträng
    """
    lines = []
    lines.append(f'name: "{strategy_obj.name}"')
    lines.append(f"type: \"{strategy_obj.__class__.__name__}\"")

    # Parametrar
    if strategy_obj.params:
        lines.append("params:")
        for key, value in strategy_obj.params.items():
            if isinstance(value, str):
                lines.append(f"    {key}: \"{value}\"")
            elif isinstance(value, bool):
                lines.append(f"    {key}: {str(value).lower()}")
            else:
                lines.append(f"    {key}: {value}")

    # DSL-metadata om det finns
    meta = getattr(strategy_obj, "_dsl_meta", {})
    filters = meta.get("filters", [])
    if filters:
        lines.append("filters:")
        for f in filters:
            lines.append(f"    - {f}")

    risk = meta.get("risk", {})
    if risk:
        lines.append("risk:")
        for key, value in risk.items():
            if isinstance(value, bool):
                lines.append(f"    {key}: {str(value).lower()}")
            elif isinstance(value, str):
                lines.append(f"    {key}: \"{value}\"")
            else:
                lines.append(f"    {key}: {value}")

    costs = meta.get("costs", {})
    if costs:
        lines.append("costs:")
        for key, value in costs.items():
            lines.append(f"    {key}: {value}")

    return "\n".join(lines)
