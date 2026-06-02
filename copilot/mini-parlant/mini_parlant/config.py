"""
Configuration objects for mini-parlant.

:class:`RuntimeConfig` is the single knob users turn to change behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class DecisionMode(str, Enum):
    """
    Controls how the decision engine picks a strategy.

    MARKOV
        Probabilistic selection driven by per-strategy weights and simple
        transition heuristics — fast, O(1), no LLM call required.

    LOGIC
        Rule/signal-driven selection that mirrors Parlant's guideline
        matching logic — deterministic, interpretable.
    """

    MARKOV = "markov"
    LOGIC = "logic"


@dataclass
class RuntimeConfig:
    """
    Top-level configuration for a :class:`~mini_parlant.runtime.MiniParlantRuntime`.

    Parameters
    ----------
    decision_mode:
        Which decision engine to use (``MARKOV`` or ``LOGIC``).
    max_enrichment_loops:
        How many internal enrichment cycles are allowed before the runtime
        gives up and responds with available information (minimum 0, default 1).
    llm_caller:
        An optional callable ``(prompt: str) -> str`` that wraps an actual LLM
        API.  When *None*, a simple echo stub is used so the framework can be
        exercised without any API keys.
    markov_seed:
        Optional random seed for the Markov engine (for reproducibility in
        tests).
    extra:
        Open-ended dict for user-defined extension parameters.
    """

    decision_mode: DecisionMode = DecisionMode.LOGIC
    max_enrichment_loops: int = 1
    llm_caller: Optional[Any] = None   # Callable[[str], str]
    markov_seed: Optional[int] = None
    extra: Dict[str, Any] = field(default_factory=dict)
