"""
Decision engine for mini_parlant.

Two engines are provided:

``LogicDecisionEngine`` (default)
    Mirrors Parlant's guideline-matching logic: collect all strategies that
    claim to match the context, then return the one with the highest signal
    confidence × priority weight.  Fully deterministic.

``MarkovDecisionEngine``
    Probabilistic engine that uses per-strategy weights (derived from signal
    strengths) to perform a weighted-random draw — similar to Markov-chain
    successor selection.  Useful for exploratory / diverse behaviour.

Both engines expose the same interface: ``select(context, signals, registry)
-> BaseStrategy``.
"""

from __future__ import annotations

import random
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Sequence

from mini_parlant.models import ContextBundle, Signal, SignalType
from mini_parlant.registry import BaseStrategy, StrategyRegistry


class BaseDecisionEngine(ABC):
    @abstractmethod
    def select(
        self,
        context: ContextBundle,
        signals: Sequence[Signal],
        registry: StrategyRegistry,
    ) -> Optional[BaseStrategy]:
        """Select and return the best strategy, or *None* if registry is empty."""


# ---------------------------------------------------------------------------
# Logic engine
# ---------------------------------------------------------------------------


class LogicDecisionEngine(BaseDecisionEngine):
    """
    Deterministic, signal-driven selection.

    Scoring formula::

        score(s) = sum(signal.confidence for signal in signals) / s.priority

    The strategy with the highest score wins.  If multiple strategies tie,
    the one registered first is chosen (stable sort).
    """

    def select(
        self,
        context: ContextBundle,
        signals: Sequence[Signal],
        registry: StrategyRegistry,
    ) -> Optional[BaseStrategy]:
        candidates = registry.matching(context, signals)
        if not candidates:
            candidates = registry.all()   # fall back to all strategies
        if not candidates:
            return None

        total_confidence = sum(s.confidence for s in signals) or 1.0

        def score(strategy: BaseStrategy) -> float:
            return total_confidence / max(strategy.priority, 1)

        return max(candidates, key=score)


# ---------------------------------------------------------------------------
# Markov engine
# ---------------------------------------------------------------------------


class MarkovDecisionEngine(BaseDecisionEngine):
    """
    Probabilistic strategy selection.

    Each candidate strategy receives a weight proportional to the sum of
    confidences of signals it "resonates with" (based on signal type ↔
    strategy name heuristics).  A weighted random draw then selects the
    winner.

    This mimics a first-order Markov chain where the *current state* is the
    dominant signal type and the *transition probabilities* are the weights.
    """

    # Maps signal types to strategy name substrings that resonate with them
    _RESONANCE: Dict[SignalType, List[str]] = {
        SignalType.TASK: ["task", "plan", "direct"],
        SignalType.QUESTION: ["direct", "answer", "clarify"],
        SignalType.CLARIFICATION_NEEDED: ["clarify", "enrich"],
        SignalType.KNOWLEDGE_GAP: ["clarify", "enrich"],
        SignalType.TOOL_USE: ["task", "plan", "enrich"],
        SignalType.GENERAL: [],
    }

    def __init__(self, seed: Optional[int] = None) -> None:
        self._rng = random.Random(seed)

    def select(
        self,
        context: ContextBundle,
        signals: Sequence[Signal],
        registry: StrategyRegistry,
    ) -> Optional[BaseStrategy]:
        candidates = registry.matching(context, signals)
        if not candidates:
            candidates = registry.all()
        if not candidates:
            return None

        weights = [self._weight(s, signals) for s in candidates]

        # Ensure no zero-weight entries so every candidate has a chance
        weights = [max(w, 0.01) for w in weights]

        return self._rng.choices(candidates, weights=weights, k=1)[0]

    def _weight(
        self, strategy: BaseStrategy, signals: Sequence[Signal]
    ) -> float:
        name_lower = strategy.name.lower()
        weight = 0.0
        for signal in signals:
            resonating = self._RESONANCE.get(signal.type, [])
            if any(kw in name_lower for kw in resonating):
                weight += signal.confidence
            else:
                weight += signal.confidence * 0.1   # small baseline
        return weight / max(strategy.priority, 1)
