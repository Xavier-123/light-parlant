"""
Context selector for mini-parlant.

Responsibility: trim / prioritise the raw content inside a
:class:`~mini_parlant.models.ContextBundle` so that the composer only sees
the most relevant information.

This keeps prompts short and reduces hallucination risk, while remaining
entirely rule-based (no LLM call).
"""

from __future__ import annotations

from typing import Dict, List

from mini_parlant.models import ContextBundle, Signal, SignalType


class ContextSelector:
    """
    Lightweight relevance filter.

    Applies heuristics to reduce the number of knowledge snippets and history
    turns that are forwarded to the LLM:

    - Keeps at most *max_knowledge* snippets (most relevant = appear later in
      the list, on the assumption that the retrieval system returns them in
      relevance order).
    - Keeps at most *max_history_turns* history messages (most recent first).
    - Promotes snippets that contain query keywords.
    """

    def __init__(
        self,
        max_knowledge: int = 5,
        max_history_turns: int = 6,
    ) -> None:
        self.max_knowledge = max_knowledge
        self.max_history_turns = max_history_turns

    def select(
        self,
        context: ContextBundle,
        signals: List[Signal],
    ) -> ContextBundle:
        """Return a new ContextBundle with trimmed / prioritised content."""
        knowledge = self._select_knowledge(context)
        history = self._select_history(context)
        return ContextBundle(
            query=context.query,
            history=history,
            knowledge=knowledge,
            metadata=context.metadata,
            raw_input=context.raw_input,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _select_knowledge(self, context: ContextBundle) -> List[str]:
        if not context.knowledge:
            return []
        snippets = context.knowledge

        # Promote snippets that contain query words
        query_words = {w.lower() for w in context.query.split() if len(w) > 3}
        if query_words:
            scored = [
                (sum(1 for w in query_words if w in s.lower()), i, s)
                for i, s in enumerate(snippets)
            ]
            scored.sort(key=lambda x: (-x[0], x[1]))
            snippets = [s for _, _, s in scored]

        return snippets[: self.max_knowledge]

    def _select_history(self, context: ContextBundle) -> List[Dict[str, str]]:
        """Keep the most recent *max_history_turns* pairs."""
        turns = context.history
        if len(turns) <= self.max_history_turns:
            return turns
        if self.max_history_turns <= 1:
            return turns[-1:] if turns else []
        # Keep the very first message (often a system/context-setting message)
        # plus the most recent turns
        kept = [turns[0]] + turns[-(self.max_history_turns - 1):]
        return kept
