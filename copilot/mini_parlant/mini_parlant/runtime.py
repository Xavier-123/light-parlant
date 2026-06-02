"""
Runtime orchestrator for mini_parlant.

:class:`MiniParlantRuntime` is the single entry-point that wires all
sub-components together and executes the full pipeline:

    raw_input
        → parse → detect signals → select context
        → select strategy → check sufficiency
        → [enrich → re-select context → re-execute strategy]? (0-N loops)
        → compose LLM prompt → call LLM
        → return StructuredResponse

Usage::

    from mini_parlant import MiniParlantRuntime, RuntimeConfig, DecisionMode
    from mini_parlant.strategies import DirectAnswerStrategy, TaskPlanningStrategy

    runtime = MiniParlantRuntime(
        config=RuntimeConfig(decision_mode=DecisionMode.LOGIC),
    )
    runtime.registry.register(DirectAnswerStrategy())
    runtime.registry.register(TaskPlanningStrategy())

    response = runtime.run(raw_input)
    print(response.answer)
"""

from __future__ import annotations

import logging
from typing import Callable, List, Optional

from mini_parlant.composer import Composer
from mini_parlant.config import DecisionMode, RuntimeConfig
from mini_parlant.context_selector import ContextSelector
from mini_parlant.decision import LogicDecisionEngine, MarkovDecisionEngine
from mini_parlant.enricher import Enricher
from mini_parlant.models import (
    ContextBundle,
    Signal,
    StructuredResponse,
    SufficiencyStatus,
)
from mini_parlant.parser import BaseParser, DefaultParser
from mini_parlant.registry import BaseStrategy, StrategyRegistry
from mini_parlant.signals import BaseSignalDetector, DefaultSignalDetector
from mini_parlant.strategies.builtin import (
    ClarifyOrEnrichStrategy,
    DirectAnswerStrategy,
    TaskPlanningStrategy,
)
from mini_parlant.sufficiency import SufficiencyChecker

logger = logging.getLogger(__name__)


class MiniParlantRuntime:
    """
    Lightweight runtime that orchestrates the full mini_parlant pipeline.

    Parameters
    ----------
    config:
        :class:`~mini_parlant.config.RuntimeConfig` controlling decision
        mode, loop budget, and optional LLM caller.
    parser:
        Custom :class:`~mini_parlant.parser.BaseParser` (default:
        :class:`~mini_parlant.parser.DefaultParser`).
    signal_detector:
        Custom signal detector (default:
        :class:`~mini_parlant.signals.DefaultSignalDetector`).
    context_selector:
        Custom context selector (default:
        :class:`~mini_parlant.context_selector.ContextSelector`).
    enricher:
        Custom :class:`~mini_parlant.enricher.Enricher` (default: no tools).

    Attributes
    ----------
    registry:
        The :class:`~mini_parlant.registry.StrategyRegistry` for this
        runtime.  Use ``runtime.registry.register(...)`` to add strategies.
    """

    def __init__(
            self,
            config: Optional[RuntimeConfig] = None,
            parser: Optional[BaseParser] = None,
            signal_detector: Optional[BaseSignalDetector] = None,
            context_selector: Optional[ContextSelector] = None,
            enricher: Optional[Enricher] = None,
    ) -> None:
        self.config = config or RuntimeConfig()
        self.registry = StrategyRegistry()

        # Register built-in strategies by default
        self.registry.register(DirectAnswerStrategy())
        self.registry.register(ClarifyOrEnrichStrategy())
        self.registry.register(TaskPlanningStrategy())

        # Sub-components
        self._parser = parser or DefaultParser()
        self._signal_detector = signal_detector or DefaultSignalDetector()
        self._context_selector = context_selector or ContextSelector()
        self._sufficiency_checker = SufficiencyChecker(
            llm_caller=self.config.llm_caller
        )
        self._enricher = enricher or Enricher()
        self._composer = Composer(llm_caller=self.config.llm_caller)

        # Decision engine
        if self.config.decision_mode == DecisionMode.MARKOV:
            self._engine = MarkovDecisionEngine(seed=self.config.markov_seed)
        else:
            self._engine = LogicDecisionEngine()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, raw_input: str) -> StructuredResponse:
        """
        Execute the full pipeline on *raw_input* and return a
        :class:`~mini_parlant.models.StructuredResponse`.
        """
        logger.debug("mini_parlant: parsing input")
        context = self._parser.parse(raw_input)

        logger.debug("mini_parlant: detecting signals")
        signals = self._signal_detector.detect(context)

        logger.debug("mini_parlant: selecting context")
        trimmed_context = self._context_selector.select(context, signals)

        enriched = False
        enrichment_notes = ""

        # --- Sufficiency check + optional enrichment loop ---
        max_loops = max(0, self.config.max_enrichment_loops)
        for loop_idx in range(max_loops + 1):  # first iteration = pre-enrichment
            verdict = self._sufficiency_checker.check(trimmed_context, signals)

            if verdict.status == SufficiencyStatus.SUFFICIENT:
                break

            if loop_idx >= max_loops:
                logger.debug(
                    "mini_parlant: still insufficient after %d enrichment loop(s); proceeding anyway",
                    loop_idx,
                )
                break

            logger.debug(
                "mini_parlant: context insufficient (%s); enriching (loop %d/%d)",
                verdict.reason,
                loop_idx + 1,
                max_loops,
            )
            trimmed_context, notes = self._enricher.enrich(trimmed_context, verdict)
            enrichment_notes = notes
            enriched = True
            # Re-detect signals on enriched context (signals may change)
            signals = self._signal_detector.detect(trimmed_context)

        # --- Strategy selection ---
        logger.debug("mini_parlant: selecting strategy (%s mode)", self.config.decision_mode)
        strategy = self._engine.select(trimmed_context, signals, self.registry)
        if strategy is None:
            return StructuredResponse(
                answer="[mini_parlant] No strategy available to handle this request.",
                signals=signals,
                enriched=enriched,
                enrichment_notes=enrichment_notes,
            )

        logger.debug("mini_parlant: executing strategy '%s'", strategy.name)
        strategy_result = strategy.execute(trimmed_context, signals)
        strategy_result.strategy_name = strategy.name

        # --- LLM generation ---
        logger.debug("mini_parlant: composing and calling LLM")
        answer = self._composer.compose(trimmed_context, strategy_result)

        return StructuredResponse(
            answer=answer,
            strategy_used=strategy.name,
            signals=signals,
            enriched=enriched,
            enrichment_notes=enrichment_notes,
            metadata={
                "decision_mode": self.config.decision_mode.value,
                "query": context.query,
                "knowledge_count": len(trimmed_context.knowledge),
                "history_turns": len(trimmed_context.history),
            },
        )
