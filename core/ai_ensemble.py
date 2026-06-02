"""
core/ai_ensemble.py - Multi-AI Ensemble System
Använder flera AI-modeller parallellt och konsoliderar svaren
för högre träffsäkerhet och konfidensbedömning.

Användning:
    ensemble = AiEnsemble()
    result = ensemble.ensemble_analysis("AAPL", stock_data)
    # result.confidence, result.consensus, result.responses
"""

import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from core.providers import get_provider, list_providers
from core.config import _get_secret

_logger = logging.getLogger(__name__)

# Sökväg för AI-trade journal
_MODULE_DIR = Path(__file__).resolve().parent.parent
AI_JOURNAL_FILE = _MODULE_DIR / "data" / "ai_trade_journal.json"


@dataclass
class EnsembleResponse:
    """Svar från AI-ensemblen."""
    ticker: str
    responses: dict = field(default_factory=dict)  # provider -> (text, confidence)
    consensus: str = ""          # BUY/SELL/HOLD
    consensus_confidence: float = 0.0  # 0.0-1.0
    agreement_level: str = ""    # "full", "partial", "conflict"
    provider_weights: dict = field(default_factory=dict)
    error: Optional[str] = None
    timestamp: str = ""


# Rekommendationskategorier (starkare får högre vikt i omröstning)
RECOMMENDATION_ORDER = [
    "STARKT SÄLJ", "SÄLJ", "UNDVIK",
    "BEVAKA", "VÄNTA", "NEUTRAL",
    "KÖP", "STARKT KÖP",
]

RECOMMENDATION_SCORE = {
    "STARKT SÄLJ": -2,
    "SÄLJ": -1,
    "UNDVIK": -1,
    "BEVAKA": 0,
    "VÄNTA": 0,
    "NEUTRAL": 0,
    "KÖP": 1,
    "STARKT KÖP": 2,
}


class AiEnsemble:
    """AI-ensemble som anropar flera providers och konsoliderar svaren.

    Använder historisk accuracy som viktning per provider.
    """

    # Provider-konfiguration med kostnadsinfo
    PROVIDERS = {
        "deepseek": {"model": "deepseek-chat", "cost_per_1m_input": 0.27, "cost_per_1m_output": 1.10},
        "gemini": {"model": "gemini-2.5-flash", "cost_per_1m_input": 0.0, "cost_per_1m_output": 0.0},
        "claude": {"model": "claude-sonnet-4-20250514", "cost_per_1m_input": 3.00, "cost_per_1m_output": 15.00},
    }

    def __init__(self, config: dict = None):
        """Initiera ensemblen.

        Args:
            config: Dict med inställningar:
                - providers: Lista med provider-namn att använda
                - confidence_threshold: Min konfidens för att ta beslut (default 0.5)
                - use_historical_weights: Viktning efter historisk accuracy (default True)
        """
        self.config = config or {}
        self.confidence_threshold = self.config.get("confidence_threshold", 0.5)
        self.use_historical_weights = self.config.get("use_historical_weights", True)
        self._accuracy_cache: dict = {}  # Provider accuracy cache

    def ensemble_analysis(self, ticker: str, stock_data: dict,
                          providers: list = None,
                          depth: str = "Normal") -> EnsembleResponse:
        """Analysera en aktie med flera AI-providers parallellt.

        Frågar N providers samtidigt (i trådar) och konsoliderar svaren.

        Args:
            ticker: Ticker-symbol
            stock_data: Dict med aktiedata (samma som analyze_stock får)
            providers: Lista med provider-namn (default: ["deepseek", "gemini"])
            depth: Analysdjup ("Snabb", "Normal", "Djup", "Extra djup")

        Returns:
            EnsembleResponse med konsoliderat svar
        """
        if providers is None:
            providers = ["deepseek", "gemini"]

        result = EnsembleResponse(
            ticker=ticker.upper(),
            timestamp=datetime.now().isoformat()[:19],
        )

        # Hämta historisk accuracy för viktning
        provider_weights = self._get_provider_weights(providers)
        result.provider_weights = provider_weights

        # Bygg prompt (samma för alla providers)
        from core.ai_prompts import SYSTEM_PROMPT_STOCK_ANALYSIS
        data_str = json.dumps(stock_data, indent=2, ensure_ascii=False) if stock_data else "Ingen data"
        system_prompt = SYSTEM_PROMPT_STOCK_ANALYSIS + (
            "\n\nAvsluta din analys med en tydlig rekommendation på en separat rad: "
            "**REKOMMENDATION:** [STARKT KÖP/KÖP/BEVAKA/UNDVIK/SÄLJ]"
        )
        user_message = f"Analysera aktien **{ticker}**.\n\nTillgänglig data:\n```json\n{data_str}\n```"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        # Anropa alla providers parallellt i trådar
        responses: dict = {}
        threads = []
        lock = threading.Lock()

        def _call_provider(p_name: str):
            """Anropa en provider och spara resultat."""
            try:
                provider = get_provider(p_name)
                if provider is None:
                    with lock:
                        responses[p_name] = ("", 0.0, f"Provider '{p_name}' ej tillgänglig")
                    return

                ai_resp = provider.generate(
                    messages,
                    max_tokens=4096 if depth == "Djup" else 2048,
                    temperature=0.3,
                )

                if ai_resp.success:
                    text = ai_resp.text
                    # Extrahera rekommendation och konfidens från texten
                    from .ai_analysis import extract_recommendation, extract_confidence
                    rec = extract_recommendation(text)
                    conf = extract_confidence(text)

                    # Viktad konfidens: om provider har historik, justera
                    weight = provider_weights.get(p_name, 1.0)
                    weighted_conf = conf * weight

                    with lock:
                        responses[p_name] = (text, weighted_conf, rec)
                else:
                    with lock:
                        responses[p_name] = ("", 0.0, ai_resp.error or "Okänt fel")
            except Exception as e:
                _logger.error("Fel vid anrop av %s: %s", p_name, e)
                with lock:
                    responses[p_name] = ("", 0.0, str(e))

        for p_name in providers:
            t = threading.Thread(target=_call_provider, args=(p_name,), daemon=True)
            threads.append(t)
            t.start()

        # Vänta på alla trådar (timeout 120s per provider)
        for t in threads:
            t.join(timeout=120)

        result.responses = responses

        # Konsolidera svaren
        result = self.resolve_conflicts(result)
        result.consensus_confidence = self._calculate_consensus_confidence(result)
        result.agreement_level = self._determine_agreement(result)

        return result

    def resolve_conflicts(self, result: EnsembleResponse) -> EnsembleResponse:
        """Analysera om providers håller med varandra eller är oense.

        Om alla håller med -> hög confidence.
        Om de säger olika -> flagga som "osäker".

        Returns:
            Uppdaterad EnsembleResponse med consensus
        """
        recommendations = []
        for p_name, (text, conf, rec) in result.responses.items():
            if text and conf > 0:
                recommendations.append((p_name, rec, conf))

        if not recommendations:
            result.consensus = "OSÄKER"
            result.error = "Inga providers svarade"
            return result

        # Om bara en provider svarade, använd dess rekommendation
        if len(recommendations) == 1:
            result.consensus = recommendations[0][1]
            return result

        # Omröstning: använd RECOMMENDATION_SCORE för viktad röstning
        score_sum = 0
        total_weight = 0
        for p_name, rec, conf in recommendations:
            score = RECOMMENDATION_SCORE.get(rec, 0)
            weight = result.provider_weights.get(p_name, 1.0)
            score_sum += score * weight
            total_weight += weight

        if total_weight > 0:
            avg_score = score_sum / total_weight
            if avg_score > 0.3:
                result.consensus = "KÖP"
            elif avg_score < -0.3:
                result.consensus = "SÄLJ"
            else:
                result.consensus = "BEVAKA"
        else:
            result.consensus = "OSÄKER"

        return result

    def consensus_vote(self, responses: dict) -> str:
        """Majoritetsbeslut för BUY/SELL/HOLD baserat på alla svar.

        Args:
            responses: Dict med provider -> (text, confidence, recommendation)

        Returns:
            "KÖP", "SÄLJ", eller "BEVAKA"
        """
        buys = 0
        sells = 0
        holds = 0

        for p_name, (text, conf, rec) in responses.items():
            if rec in ("STARKT KÖP", "KÖP"):
                buys += 1
            elif rec in ("STARKT SÄLJ", "SÄLJ", "UNDVIK"):
                sells += 1
            else:
                holds += 1

        if buys > sells and buys > holds:
            return "KÖP"
        elif sells > buys and sells > holds:
            return "SÄLJ"
        else:
            return "BEVAKA"

    def _calculate_consensus_confidence(self, result: EnsembleResponse) -> float:
        """Beräkna konfidens baserat på hur väl providers håller med.

        - 100% om alla håller med
        - 66% om 2/3
        - 50% om 1/2

        Returns:
            Float 0.0-1.0
        """
        recommendations = []
        for p_name, (text, conf, rec) in result.responses.items():
            if text and conf > 0:
                recommendations.append(rec)

        n = len(recommendations)
        if n == 0:
            return 0.0

        # Räkna förekomst av varje rekommendation
        counts = {}
        for rec in recommendations:
            # Normalisera till kategori
            if rec in ("STARKT KÖP", "KÖP"):
                cat = "KÖP"
            elif rec in ("STARKT SÄLJ", "SÄLJ", "UNDVIK"):
                cat = "SÄLJ"
            else:
                cat = "BEVAKA"
            counts[cat] = counts.get(cat, 0) + 1

        max_agree = max(counts.values()) if counts else 0

        # Beräkna konfidens
        if n == 1:
            return 0.5  # En provider -> max 50%

        if n == 2:
            return 1.0 if max_agree == 2 else 0.5

        if n >= 3:
            if max_agree == n:
                return 1.0  # Alla håller med
            elif max_agree >= n * 2 / 3:
                return 0.66  # 2/3 håller med
            else:
                return 0.5  # Delade meningar

        return 0.5

    def _determine_agreement(self, result: EnsembleResponse) -> str:
        """Bestäm överensstämmelsenivå.

        Returns:
            "full" = alla håller med
            "partial" = delade meningar
            "conflict" = motsatta åsikter (en säger köp, en säger sälj)
        """
        recs = []
        for p_name, (text, conf, rec) in result.responses.items():
            if text and conf > 0:
                recs.append(rec)

        if len(recs) <= 1:
            return "partial"

        # Kolla om det finns både köp- och säljrekommendationer
        has_buy = any(r in ("STARKT KÖP", "KÖP") for r in recs)
        has_sell = any(r in ("STARKT SÄLJ", "SÄLJ", "UNDVIK") for r in recs)

        if has_buy and has_sell:
            return "conflict"

        # Kolla om alla är samma kategori
        categories = set()
        for r in recs:
            if r in ("STARKT KÖP", "KÖP"):
                categories.add("BUY")
            elif r in ("STARKT SÄLJ", "SÄLJ", "UNDVIK"):
                categories.add("SELL")
            else:
                categories.add("HOLD")

        if len(categories) == 1:
            return "full"

        return "partial"

    def _get_provider_weights(self, providers: list) -> dict:
        """Hämta vikter för providers baserat på historisk accuracy.

        Returnerar dict med provider -> vikt (float).
        Default-vikt = 1.0 om ingen historik finns.
        """
        weights = {p: 1.0 for p in providers}

        if not self.use_historical_weights:
            return weights

        try:
            accuracy = self._load_provider_accuracy()
            for p in providers:
                if p in accuracy:
                    # Skala: 50% accuracy -> vikt 0.5, 100% -> vikt 1.5
                    acc = accuracy[p]
                    weights[p] = 0.5 + acc  # 0.5-1.5
        except Exception as e:
            _logger.warning("Kunde inte ladda provider-accuracy: %s", e)

        return weights

    def _load_provider_accuracy(self) -> dict:
        """Ladda historisk accuracy per provider från AI-journalen.

        Returns:
            Dict med provider -> accuracy (0.0-1.0)
        """
        if self._accuracy_cache:
            return self._accuracy_cache

        try:
            if not AI_JOURNAL_FILE.exists():
                return {}

            entries = json.loads(AI_JOURNAL_FILE.read_text(encoding="utf-8"))
            if not isinstance(entries, list):
                return {}

            # Räkna träffar per provider
            provider_stats: dict = {}

            for entry in entries:
                provider = entry.get("provider", "unknown")
                outcome = entry.get("outcome_1m")

                if outcome is None:
                    continue

                if provider not in provider_stats:
                    provider_stats[provider] = {"correct": 0, "total": 0}

                provider_stats[provider]["total"] += 1

                # Positivt utfall = korrekt rekommendation
                # (förenklat: en köprekommendation var rätt om priset gick upp)
                rec = entry.get("recommendation", "")
                if rec in ("STARKT KÖP", "KÖP") and outcome > 0:
                    provider_stats[provider]["correct"] += 1
                elif rec in ("STARKT SÄLJ", "SÄLJ", "UNDVIK") and outcome < 0:
                    provider_stats[provider]["correct"] += 1
                elif rec in ("BEVAKA", "VÄNTA", "NEUTRAL"):
                    # Håll-rekommendationer: rätt om pris ändrades < 3%
                    if abs(outcome) < 3:
                        provider_stats[provider]["correct"] += 1

            # Beräkna accuracy
            accuracy = {}
            for provider, stats in provider_stats.items():
                if stats["total"] > 0:
                    accuracy[provider] = stats["correct"] / stats["total"]

            self._accuracy_cache = accuracy
            return accuracy

        except Exception as e:
            _logger.warning("Kunde inte läsa AI-journal: %s", e)
            return {}

    def get_best_provider(self) -> str:
        """Hitta providern med bäst historisk accuracy.

        Returns:
            Providernamn (t.ex. "deepseek")
        """
        accuracy = self._load_provider_accuracy()
        if not accuracy:
            return "deepseek"  # Default

        return max(accuracy, key=accuracy.get)

    def get_best_provider_for_sector(self, sector: str) -> str:
        """Hitta vilken AI som är bäst på en specifik sektor.

        Args:
            sector: Sektornamn (t.ex. "Technology", "Healthcare")

        Returns:
            Providernamn med bäst träffsäkerhet i sektorn
        """
        try:
            if not AI_JOURNAL_FILE.exists():
                return self.get_best_provider()

            entries = json.loads(AI_JOURNAL_FILE.read_text(encoding="utf-8"))
            if not isinstance(entries, list):
                return self.get_best_provider()

            # Filtrera på sektor
            sector_stats: dict = {}
            for entry in entries:
                if entry.get("sector", "") != sector:
                    continue
                provider = entry.get("provider", "unknown")
                outcome = entry.get("outcome_1m")
                if outcome is None:
                    continue

                if provider not in sector_stats:
                    sector_stats[provider] = {"correct": 0, "total": 0}
                sector_stats[provider]["total"] += 1

                rec = entry.get("recommendation", "")
                if rec in ("STARKT KÖP", "KÖP") and outcome > 0:
                    sector_stats[provider]["correct"] += 1
                elif rec in ("STARKT SÄLJ", "SÄLJ", "UNDVIK") and outcome < 0:
                    sector_stats[provider]["correct"] += 1

            if not sector_stats:
                return self.get_best_provider()

            # Hitta bäst
            best_provider = max(
                sector_stats,
                key=lambda p: sector_stats[p]["correct"] / max(sector_stats[p]["total"], 1)
                if sector_stats[p]["total"] > 0 else 0
            )
            return best_provider

        except Exception as e:
            _logger.warning("Kunde inte beräkna sektor-accuracy: %s", e)
            return self.get_best_provider()
