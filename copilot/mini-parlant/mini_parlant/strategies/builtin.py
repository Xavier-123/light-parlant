"""
Built-in strategies for mini-parlant.

Three strategies are provided out of the box:

``DirectAnswerStrategy``   (priority 10)
    Fastest path: answer the query directly using available context.
    Matches when the dominant signal is QUESTION or GENERAL.

``ClarifyOrEnrichStrategy``   (priority 20)
    Triggered when the query is ambiguous or knowledge is missing.
    Instructs the LLM to either ask for clarification or surface what it
    knows and highlight gaps.

``TaskPlanningStrategy``   (priority 30)
    Triggered when the query contains an actionable task.
    Instructs the LLM to produce a structured step-by-step plan.
"""

from __future__ import annotations

from typing import Sequence

from mini_parlant.models import ContextBundle, Signal, SignalType, StrategyResult
from mini_parlant.registry import BaseStrategy


class DirectAnswerStrategy(BaseStrategy):
    """Answer the query directly and concisely."""

    priority = 10

    def matches(self, context: ContextBundle, signals: Sequence[Signal]) -> bool:
        types = {s.type for s in signals}
        return SignalType.QUESTION in types or SignalType.GENERAL in types

    def execute(self, context: ContextBundle, signals: Sequence[Signal]) -> StrategyResult:
        return StrategyResult(
            goal=(
                f"Provide an accurate and concise answer to the user's query: "
                f'"{context.query}"'
            ),
            constraints=[
                "Base your answer only on the provided knowledge and history.",
                "Do not fabricate facts.",
                "Be concise; avoid unnecessary elaboration.",
            ],
            output_format=(
                "A clear, plain-text answer in 1–3 paragraphs. "
                "If the answer requires a list, use a bullet list."
            ),
            strategy_name=self.name,
        )


class ClarifyOrEnrichStrategy(BaseStrategy):
    """Handle ambiguous queries or knowledge gaps."""

    priority = 20

    def matches(self, context: ContextBundle, signals: Sequence[Signal]) -> bool:
        types = {s.type for s in signals}
        return (
            SignalType.CLARIFICATION_NEEDED in types
            or SignalType.KNOWLEDGE_GAP in types
        )

    def execute(self, context: ContextBundle, signals: Sequence[Signal]) -> StrategyResult:
        has_gap = any(s.type == SignalType.KNOWLEDGE_GAP for s in signals)
        has_clarification = any(s.type == SignalType.CLARIFICATION_NEEDED for s in signals)

        if has_clarification and not context.history:
            goal = (
                f'The user query "{context.query}" is ambiguous or incomplete. '
                "Ask one targeted clarifying question to gather the missing information."
            )
        else:
            goal = (
                f'Answer "{context.query}" to the best of your ability. '
                "If critical information is missing, clearly state what you do not know "
                "and suggest how the user could provide it."
            )

        return StrategyResult(
            goal=goal,
            constraints=[
                "Ask at most ONE clarifying question.",
                "Do not invent information to fill knowledge gaps.",
                "Clearly label any uncertainty.",
            ],
            output_format=(
                "Plain text. "
                "If asking a clarifying question, lead with it. "
                "If answering partially, summarise what you know first."
            ),
            strategy_name=self.name,
        )


class TaskPlanningStrategy(BaseStrategy):
    """Decompose and plan a multi-step task."""

    priority = 30

    def matches(self, context: ContextBundle, signals: Sequence[Signal]) -> bool:
        types = {s.type for s in signals}
        return SignalType.TASK in types or SignalType.TOOL_USE in types

    def execute(self, context: ContextBundle, signals: Sequence[Signal]) -> StrategyResult:
        has_tool = any(s.type == SignalType.TOOL_USE for s in signals)
        tool_note = (
            " Reference any relevant tools or APIs where appropriate."
            if has_tool
            else ""
        )

        return StrategyResult(
            goal=(
                f"Create a clear, actionable plan to accomplish: "
                f'"{context.query}".{tool_note}'
            ),
            constraints=[
                "Break the task into numbered steps.",
                "Each step should be concrete and actionable.",
                "Highlight any prerequisites or dependencies between steps.",
                "Do not skip important steps even if they seem obvious.",
            ],
            output_format=(
                "A numbered step-by-step plan. "
                "Each step: **Step N: <title>** followed by a brief description. "
                "End with a short summary of the expected outcome."
            ),
            strategy_name=self.name,
        )
