"""
Strategy registry for mini_parlant.

Inspired by Parlant's Journey/Guideline registration pattern.
Strategies are lightweight objects that translate a context + signals into a
:class:`~mini_parlant.models.StrategyResult` (goal, constraints, output format)
that the composer then turns into an LLM prompt.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Sequence

from mini_parlant.models import ContextBundle, Signal, StrategyResult, SignalType


# ---------------------------------------------------------------------------
# Abstract base strategy
# ---------------------------------------------------------------------------


class BaseStrategy(ABC):
    """
    Abstract strategy — analogous to a Parlant Journey node.

    Each concrete strategy encodes *when* it applies (``matches``) and *what*
    prompt recipe to produce (``execute``).
    """

    #: Lower values = higher priority when multiple strategies match
    priority: int = 100

    @property
    def name(self) -> str:
        return type(self).__name__

    @abstractmethod
    def matches(self, context: ContextBundle, signals: Sequence[Signal]) -> bool:
        """Return True if this strategy is applicable given *context* and *signals*."""

    @abstractmethod
    def execute(self, context: ContextBundle, signals: Sequence[Signal]) -> StrategyResult:
        """Produce a :class:`StrategyResult` for the composer."""


# ---------------------------------------------------------------------------
# Strategy registry
# ---------------------------------------------------------------------------


class StrategyRegistry:
    """
    Holds all registered strategies.

    Usage::

        registry = StrategyRegistry()
        registry.register(DirectAnswerStrategy())
        registry.register(TaskPlanningStrategy())

    Strategies are stored in insertion order; the decision engine picks among
    them according to its own logic.
    """

    def __init__(self) -> None:
        self._strategies: Dict[str, BaseStrategy] = {}

    def register(self, strategy: BaseStrategy) -> "StrategyRegistry":
        """Register *strategy* (fluent interface)."""
        self._strategies[strategy.name] = strategy
        return self

    def unregister(self, name: str) -> None:
        self._strategies.pop(name, None)

    def get(self, name: str) -> Optional[BaseStrategy]:
        return self._strategies.get(name)

    def all(self) -> List[BaseStrategy]:
        """Return all registered strategies in insertion order."""
        return list(self._strategies.values())

    def matching(
        self, context: ContextBundle, signals: Sequence[Signal]
    ) -> List[BaseStrategy]:
        """Return strategies that claim to match the current context."""
        return [s for s in self.all() if s.matches(context, signals)]

    def __len__(self) -> int:
        return len(self._strategies)

    def __repr__(self) -> str:
        names = list(self._strategies.keys())
        return f"StrategyRegistry({names})"
