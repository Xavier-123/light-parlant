"""
Signal detection for mini_parlant.

The :class:`SignalDetector` inspects a :class:`~mini_parlant.models.ContextBundle`
and emits a list of :class:`~mini_parlant.models.Signal` objects that the
decision engine uses to pick a strategy.

Design notes
------------
- Keeps all detection logic in pure Python (no LLM call) so signal detection
  is always fast and cheap.
- Uses keyword/pattern heuristics.  Production callers may subclass
  :class:`BaseSignalDetector` and replace individual ``_detect_*`` methods.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import List, Sequence

from mini_parlant.models import ContextBundle, Signal, SignalType


class BaseSignalDetector(ABC):
    @abstractmethod
    def detect(self, context: ContextBundle) -> List[Signal]:
        """Return a list of signals detected in *context*."""


class DefaultSignalDetector(BaseSignalDetector):
    """
    Keyword/pattern-based signal detector.

    Emits one or more signals per context bundle.  Confidence values are
    simple heuristics and should be treated as *relative* weights rather than
    calibrated probabilities.
    """

    # Task keywords – imperative verbs that suggest an action request
    _TASK_KEYWORDS = re.compile(
        r"\b(create|write|build|generate|implement|make|draft|plan|"
        r"develop|design|produce|summarize|translate|explain how to|"
        r"step[- ]by[- ]step|list|enumerate)\b",
        re.IGNORECASE,
    )

    # Question markers
    _QUESTION_KEYWORDS = re.compile(
        r"\b(what|who|where|when|why|how|which|is|are|was|were|"
        r"do|does|did|can|could|would|should|tell me|define)\b",
        re.IGNORECASE,
    )

    # Signals that the model may not have enough info
    _KNOWLEDGE_GAP_KEYWORDS = re.compile(
        r"\b(don'?t know|not sure|unable to|cannot find|missing|unclear|"
        r"need more|require|look up|search for|find out|check)\b",
        re.IGNORECASE,
    )

    # Hints that a tool should be invoked
    _TOOL_USE_KEYWORDS = re.compile(
        r"\b(calculate|compute|execute|run|call|invoke|fetch|retrieve|"
        r"query|lookup|look up|api|database|db|sql|code|script)\b",
        re.IGNORECASE,
    )

    def detect(self, context: ContextBundle) -> List[Signal]:
        text = context.query

        signals: List[Signal] = []

        # --- task signal ---
        if self._TASK_KEYWORDS.search(text):
            signals.append(Signal(type=SignalType.TASK, confidence=0.8))

        # --- question signal ---
        if self._QUESTION_KEYWORDS.search(text) or text.strip().endswith("?"):
            signals.append(Signal(type=SignalType.QUESTION, confidence=0.9))

        # --- knowledge-gap signal ---
        # Triggered when retrieved knowledge is empty OR gap keywords appear
        if not context.knowledge or self._KNOWLEDGE_GAP_KEYWORDS.search(text):
            signals.append(
                Signal(
                    type=SignalType.KNOWLEDGE_GAP,
                    confidence=0.7 if not context.knowledge else 0.5,
                    payload={"knowledge_count": len(context.knowledge)},
                )
            )

        # --- tool-use signal ---
        if self._TOOL_USE_KEYWORDS.search(text):
            signals.append(Signal(type=SignalType.TOOL_USE, confidence=0.6))

        # --- clarification-needed signal ---
        # Heuristic: very short query (<10 chars) with no history is ambiguous
        if len(text.strip()) < 10 and not context.history:
            signals.append(
                Signal(type=SignalType.CLARIFICATION_NEEDED, confidence=0.8)
            )

        # Fallback – always emit at least one general signal
        if not signals:
            signals.append(Signal(type=SignalType.GENERAL, confidence=1.0))

        return signals
