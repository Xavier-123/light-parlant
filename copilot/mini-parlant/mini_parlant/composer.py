"""
Prompt composer for mini-parlant.

Takes a :class:`~mini_parlant.models.StrategyResult` + a trimmed
:class:`~mini_parlant.models.ContextBundle` and builds the final LLM prompt,
then calls the LLM (or stub) and returns the raw response string.
"""

from __future__ import annotations

from typing import Callable, Optional

from mini_parlant.models import ContextBundle, StrategyResult


_PROMPT_TEMPLATE = """\
## Goal
{goal}

## Constraints
{constraints}

## Context
Query: {query}

{knowledge_section}
{history_section}
{extra_context_section}
## Output format
{output_format}

---
Please respond now.
"""


class Composer:
    """
    Builds LLM prompts and calls the LLM.

    Parameters
    ----------
    llm_caller:
        ``(prompt: str) -> str``.  When *None*, an echo stub is used.
    """

    def __init__(self, llm_caller: Optional[Callable[[str], str]] = None) -> None:
        self._llm = llm_caller or self._stub_llm

    @staticmethod
    def _stub_llm(prompt: str) -> str:
        """Echo stub — returns a placeholder when no real LLM is configured."""
        return (
            "[mini-parlant stub response]\n\n"
            "No LLM caller was configured.  The composed prompt was:\n\n"
            + prompt
        )

    def compose(
        self,
        context: ContextBundle,
        strategy_result: StrategyResult,
    ) -> str:
        """Build the prompt and return the LLM response."""
        prompt = self._build_prompt(context, strategy_result)
        return self._llm(prompt)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_prompt(
        self,
        context: ContextBundle,
        sr: StrategyResult,
    ) -> str:
        constraints_text = (
            "\n".join(f"- {c}" for c in sr.constraints)
            if sr.constraints
            else "- None"
        )

        knowledge_section = ""
        if context.knowledge:
            snippets = "\n".join(f"  [{i+1}] {s}" for i, s in enumerate(context.knowledge))
            knowledge_section = f"Retrieved knowledge:\n{snippets}\n"

        history_section = ""
        if context.history:
            turns = "\n".join(
                f"  {t['role'].capitalize()}: {t['content']}"
                for t in context.history
            )
            history_section = f"Conversation history:\n{turns}\n"

        extra_context_section = ""
        if sr.extra_context:
            extra_context_section = f"Additional context:\n{sr.extra_context}\n"

        return _PROMPT_TEMPLATE.format(
            goal=sr.goal,
            constraints=constraints_text,
            query=context.query,
            knowledge_section=knowledge_section,
            history_section=history_section,
            extra_context_section=extra_context_section,
            output_format=sr.output_format,
        )
