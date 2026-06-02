"""
Example: mini-parlant basic usage.

Run from the mini-parlant directory:

    python examples/basic_usage.py

No API keys are required — the stub LLM is used so you can see the full
pipeline (including the composed prompt) without any network calls.
"""

import sys
import os

# Allow running from the repo root or from the mini-parlant directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mini_parlant import MiniParlantRuntime, RuntimeConfig, DecisionMode


# ---------------------------------------------------------------------------
# Example 1 – simple question, Logic mode (default)
# ---------------------------------------------------------------------------

SIMPLE_QUESTION_INPUT = """
Query:
What is the capital of France?

History:
User: Hi there!
Assistant: Hello! How can I help you?

Knowledge:
France is a country in Western Europe.
Paris is the capital and largest city of France, located in the north of the country.
The Eiffel Tower is located in Paris.

Metadata:
locale=en-US
"""


def example_simple_question() -> None:
    print("=" * 60)
    print("Example 1: Simple Question (Logic mode)")
    print("=" * 60)
    runtime = MiniParlantRuntime()
    response = runtime.run(SIMPLE_QUESTION_INPUT)
    print(f"Strategy used : {response.strategy_used}")
    print(f"Signals       : {[s.type.value for s in response.signals]}")
    print(f"Enriched      : {response.enriched}")
    print(f"Answer        :\n{response.answer}")
    print()


# ---------------------------------------------------------------------------
# Example 2 – task request, Markov mode
# ---------------------------------------------------------------------------

TASK_INPUT = """
Query:
Create a step-by-step plan to build a simple REST API in Python.

Knowledge:
Python is a popular programming language.
FastAPI is a modern, fast web framework for building APIs with Python.
Flask is a micro web framework for Python.
"""


def example_task_planning() -> None:
    print("=" * 60)
    print("Example 2: Task Planning (Markov mode)")
    print("=" * 60)
    runtime = MiniParlantRuntime(
        config=RuntimeConfig(
            decision_mode=DecisionMode.MARKOV,
            markov_seed=42,
        )
    )
    response = runtime.run(TASK_INPUT)
    print(f"Strategy used : {response.strategy_used}")
    print(f"Signals       : {[s.type.value for s in response.signals]}")
    print(f"Answer        :\n{response.answer}")
    print()


# ---------------------------------------------------------------------------
# Example 3 – insufficient knowledge triggers enrichment loop
# ---------------------------------------------------------------------------

KNOWLEDGE_GAP_INPUT = """
Query:
What is the latest interest rate set by the European Central Bank?
"""


def example_knowledge_gap() -> None:
    print("=" * 60)
    print("Example 3: Knowledge Gap + Enrichment Loop")
    print("=" * 60)

    # Register a stub tool that simulates an API lookup
    def fake_ecb_tool(query: str) -> str:
        return "As of the latest update, the ECB deposit facility rate is 3.75%."

    from mini_parlant.enricher import Enricher

    enricher = Enricher(tools={"ecb_api": fake_ecb_tool})
    runtime = MiniParlantRuntime(
        config=RuntimeConfig(max_enrichment_loops=1),
        enricher=enricher,
    )
    response = runtime.run(KNOWLEDGE_GAP_INPUT)
    print(f"Strategy used     : {response.strategy_used}")
    print(f"Enriched          : {response.enriched}")
    print(f"Enrichment notes  : {response.enrichment_notes}")
    print(f"Answer            :\n{response.answer}")
    print()


# ---------------------------------------------------------------------------
# Example 4 – custom strategy
# ---------------------------------------------------------------------------

def example_custom_strategy() -> None:
    print("=" * 60)
    print("Example 4: Custom Strategy")
    print("=" * 60)

    from typing import Sequence
    from mini_parlant.registry import BaseStrategy
    from mini_parlant.models import ContextBundle, Signal, SignalType, StrategyResult

    class SentimentStrategy(BaseStrategy):
        """Analyses the sentiment of the user's query."""
        priority = 5  # Higher priority than DirectAnswerStrategy

        def matches(self, context: ContextBundle, signals: Sequence[Signal]) -> bool:
            keywords = {"feel", "feeling", "emotion", "happy", "sad", "angry"}
            return any(kw in context.query.lower() for kw in keywords)

        def execute(self, context: ContextBundle, signals: Sequence[Signal]) -> StrategyResult:
            return StrategyResult(
                goal=f'Analyse the emotional tone of: "{context.query}"',
                constraints=["Be empathetic.", "Keep the response brief."],
                output_format="One sentence describing the detected sentiment, followed by a supportive response.",
                strategy_name=self.name,
            )

    runtime = MiniParlantRuntime()
    runtime.registry.register(SentimentStrategy())

    response = runtime.run("I feel really sad today.")
    print(f"Strategy used : {response.strategy_used}")
    print(f"Answer        :\n{response.answer}")
    print()


if __name__ == "__main__":
    example_simple_question()
    example_task_planning()
    example_knowledge_gap()
    example_custom_strategy()
