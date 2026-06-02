"""
Enricher for mini-parlant.

When the sufficiency checker returns INSUFFICIENT, the enricher tries to
gather missing information through one of two built-in mechanisms:

1. **Tool lookup** – calls a registered tool function by name.
2. **Knowledge refocus** – broadens the query and re-scores existing
   knowledge snippets (no external call; pure in-memory).

Custom enrichers can be registered via :meth:`Enricher.register_tool`.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional, Tuple

from mini_parlant.models import ContextBundle, SufficiencyVerdict


class Enricher:
    """
    Performs one internal enrichment loop to fill knowledge gaps.

    Parameters
    ----------
    tools:
        A dict mapping tool name → callable ``(query: str) -> str``.
        Each tool is expected to return a text snippet relevant to the query.
    """

    def __init__(
        self,
        tools: Optional[Dict[str, Callable[[str], str]]] = None,
    ) -> None:
        self._tools: Dict[str, Callable[[str], str]] = tools or {}

    def register_tool(self, name: str, fn: Callable[[str], str]) -> "Enricher":
        """Register a tool function (fluent interface)."""
        self._tools[name] = fn
        return self

    def enrich(
        self,
        context: ContextBundle,
        verdict: SufficiencyVerdict,
    ) -> Tuple[ContextBundle, str]:
        """
        Attempt to enrich *context* and return ``(enriched_context, notes)``.

        Strategy
        --------
        1. If any tools are registered, call each one with the current query
           and append results as new knowledge snippets.
        2. Otherwise, perform knowledge refocus: re-rank existing snippets
           using keywords extracted from *verdict.missing_info*.

        Returns
        -------
        enriched_context:
            A new ContextBundle with additional / re-ranked knowledge.
        notes:
            Human-readable description of what was done.
        """
        if self._tools:
            return self._tool_lookup(context, verdict)
        return self._knowledge_refocus(context, verdict)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _tool_lookup(
        self,
        context: ContextBundle,
        verdict: SufficiencyVerdict,
    ) -> Tuple[ContextBundle, str]:
        new_snippets: List[str] = []
        notes_parts: List[str] = []

        for tool_name, fn in self._tools.items():
            try:
                result = fn(context.query)
                if result and result.strip():
                    new_snippets.append(f"[{tool_name}]: {result.strip()}")
                    notes_parts.append(f"called tool '{tool_name}'")
            except Exception as exc:
                notes_parts.append(f"tool '{tool_name}' failed: {exc}")

        enriched = ContextBundle(
            query=context.query,
            history=context.history,
            knowledge=context.knowledge + new_snippets,
            metadata=context.metadata,
            raw_input=context.raw_input,
        )
        notes = "Enrichment via tool lookup: " + "; ".join(notes_parts or ["no tools returned data"])
        return enriched, notes

    def _knowledge_refocus(
        self,
        context: ContextBundle,
        verdict: SufficiencyVerdict,
    ) -> Tuple[ContextBundle, str]:
        """Re-rank existing knowledge snippets using missing-info keywords."""
        focus_words = set()
        for item in verdict.missing_info:
            focus_words.update(w.lower() for w in item.split() if len(w) > 3)
        # Also add query words
        focus_words.update(w.lower() for w in context.query.split() if len(w) > 3)

        snippets = list(context.knowledge)
        if focus_words and snippets:
            scored = [
                (sum(1 for w in focus_words if w in s.lower()), i, s)
                for i, s in enumerate(snippets)
            ]
            scored.sort(key=lambda x: (-x[0], x[1]))
            snippets = [s for _, _, s in scored]

        enriched = ContextBundle(
            query=context.query,
            history=context.history,
            knowledge=snippets,
            metadata=context.metadata,
            raw_input=context.raw_input,
        )
        notes = (
            f"Enrichment via knowledge refocus "
            f"(focus keywords: {', '.join(sorted(focus_words)) or 'none'})"
        )
        return enriched, notes
