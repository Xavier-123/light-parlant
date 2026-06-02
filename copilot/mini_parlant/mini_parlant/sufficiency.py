"""
Sufficiency checker for mini_parlant.

Asks the LLM (or uses a heuristic fallback) whether the current context is
sufficient to answer the user's query.  Returns a
:class:`~mini_parlant.models.SufficiencyVerdict`.

When no LLM caller is available, a rule-based heuristic is used:
- If knowledge snippets are empty and the query is non-trivial → INSUFFICIENT.
- Otherwise → SUFFICIENT.
"""

from __future__ import annotations

from typing import Callable, List, Optional

from mini_parlant.models import (
    ContextBundle,
    Signal,
    SignalType,
    SufficiencyStatus,
    SufficiencyVerdict,
)


_SUFFICIENCY_PROMPT_TEMPLATE = """\
You are a sufficiency evaluator.

User query: {query}

Available knowledge snippets ({n_snippets}):
{snippets}

Conversation history turns: {n_history}

Task: Decide whether the available information is SUFFICIENT to answer the
user's query accurately and completely.

Respond with exactly one JSON object:
{{
  "status": "sufficient" or "insufficient",
  "reason": "<one sentence>",
  "missing_info": ["<item 1>", "<item 2>"]
}}

Do NOT include any other text.
"""


class SufficiencyChecker:
    """
    Evaluates whether the context is sufficient to answer the query.

    Parameters
    ----------
    llm_caller:
        Optional ``(prompt: str) -> str`` callable.  When provided, a brief
        LLM call is made to judge sufficiency.  When *None*, a fast heuristic
        is used instead.
    """

    def __init__(self, llm_caller: Optional[Callable[[str], str]] = None) -> None:
        self._llm = llm_caller

    def check(
        self,
        context: ContextBundle,
        signals: List[Signal],
    ) -> SufficiencyVerdict:
        if self._llm:
            return self._llm_check(context)
        return self._heuristic_check(context, signals)

    # ------------------------------------------------------------------
    # LLM-based check
    # ------------------------------------------------------------------

    def _llm_check(self, context: ContextBundle) -> SufficiencyVerdict:
        assert self._llm is not None
        snippets_text = (
            "\n".join(f"  - {s}" for s in context.knowledge)
            if context.knowledge
            else "  (none)"
        )
        prompt = _SUFFICIENCY_PROMPT_TEMPLATE.format(
            query=context.query,
            n_snippets=len(context.knowledge),
            snippets=snippets_text,
            n_history=len(context.history),
        )
        raw = self._llm(prompt)
        return self._parse_llm_response(raw)

    @staticmethod
    def _parse_llm_response(raw: str) -> SufficiencyVerdict:
        import json
        import re

        try:
            # Extract JSON even if there is surrounding prose
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if not m:
                raise ValueError("No JSON object found in LLM response")
            data = json.loads(m.group())
            status = (
                SufficiencyStatus.SUFFICIENT
                if data.get("status", "").lower() == "sufficient"
                else SufficiencyStatus.INSUFFICIENT
            )
            return SufficiencyVerdict(
                status=status,
                reason=data.get("reason", ""),
                missing_info=data.get("missing_info", []),
            )
        except Exception:
            # Conservative fallback: treat as sufficient to avoid infinite loops
            return SufficiencyVerdict(
                status=SufficiencyStatus.SUFFICIENT,
                reason="Could not parse LLM sufficiency response; assuming sufficient.",
            )

    # ------------------------------------------------------------------
    # Heuristic check (no LLM)
    # ------------------------------------------------------------------

    @staticmethod
    def _heuristic_check(
        context: ContextBundle, signals: List[Signal]
    ) -> SufficiencyVerdict:
        has_knowledge_gap = any(
            s.type == SignalType.KNOWLEDGE_GAP for s in signals
        )
        # A very short query (< 10 chars) is unlikely to require deep knowledge
        trivial_query = len(context.query.strip()) < 10

        if has_knowledge_gap and not trivial_query and not context.knowledge:
            return SufficiencyVerdict(
                status=SufficiencyStatus.INSUFFICIENT,
                reason="No retrieved knowledge available and knowledge-gap signal detected.",
                missing_info=["relevant knowledge snippets"],
            )
        return SufficiencyVerdict(
            status=SufficiencyStatus.SUFFICIENT,
            reason="Heuristic check passed.",
        )
