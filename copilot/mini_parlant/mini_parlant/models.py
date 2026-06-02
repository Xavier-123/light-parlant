"""
Data models for mini_parlant.

These are intentionally plain dataclasses / TypedDicts so that the package
carries zero mandatory third-party dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence


# ---------------------------------------------------------------------------
# Input / context
# ---------------------------------------------------------------------------


@dataclass
class ContextBundle:
    """
    The parsed, structured representation of the raw input text.

    Attributes
    ----------
    query:
        The current user question or instruction.
    history:
        Prior conversation turns as a list of ``{"role": ..., "content": ...}``
        dicts (compatible with standard chat APIs).
    knowledge:
        Retrieved knowledge snippets relevant to the query.
    metadata:
        Any additional key/value data extracted from the raw input
        (e.g. user locale, session ID, tool results from a previous turn).
    raw_input:
        The original unprocessed input string, kept for debugging.
    """

    query: str
    history: List[Dict[str, str]] = field(default_factory=list)
    knowledge: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    raw_input: str = ""


# ---------------------------------------------------------------------------
# Signals  (analogous to Parlant's event/guideline signals)
# ---------------------------------------------------------------------------


class SignalType(str, Enum):
    """Categorical type for a detected signal."""

    TASK = "task"
    QUESTION = "question"
    CLARIFICATION_NEEDED = "clarification_needed"
    KNOWLEDGE_GAP = "knowledge_gap"
    TOOL_USE = "tool_use"
    GENERAL = "general"


@dataclass
class Signal:
    """
    A lightweight signal derived from the context bundle.

    Signals are produced by the *parser* and consumed by the *decision engine*
    to select the most appropriate strategy.
    """

    type: SignalType
    confidence: float = 1.0          # 0-1; higher = stronger signal
    payload: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Strategy result
# ---------------------------------------------------------------------------


@dataclass
class StrategyResult:
    """
    What a strategy returns: a prompt recipe for the LLM composer.

    Attributes
    ----------
    goal:
        A concise statement of what the LLM should achieve.
    constraints:
        A list of hard rules the LLM must respect.
    output_format:
        A description of the desired response structure.
    extra_context:
        Any additional information the strategy wants to inject into the prompt.
    strategy_name:
        Name of the strategy that produced this result (set automatically).
    """

    goal: str
    constraints: List[str] = field(default_factory=list)
    output_format: str = "Provide a clear, concise plain-text answer."
    extra_context: str = ""
    strategy_name: str = ""


# ---------------------------------------------------------------------------
# Sufficiency verdict
# ---------------------------------------------------------------------------


class SufficiencyStatus(str, Enum):
    SUFFICIENT = "sufficient"
    INSUFFICIENT = "insufficient"


@dataclass
class SufficiencyVerdict:
    """Result of the self-sufficiency check."""

    status: SufficiencyStatus
    reason: str = ""
    missing_info: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Final structured output
# ---------------------------------------------------------------------------


@dataclass
class StructuredResponse:
    """
    The final output returned by :class:`~mini_parlant.runtime.MiniParlantRuntime`.

    Attributes
    ----------
    answer:
        The main response text.
    strategy_used:
        Name of the strategy that was selected.
    signals:
        Signals that were detected in the context.
    enriched:
        Whether an enrichment loop was triggered.
    enrichment_notes:
        Human-readable notes about what enrichment was performed.
    metadata:
        Any extra diagnostic information.
    """

    answer: str
    strategy_used: str = ""
    signals: List[Signal] = field(default_factory=list)
    enriched: bool = False
    enrichment_notes: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
