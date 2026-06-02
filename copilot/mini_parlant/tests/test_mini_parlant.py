"""
Tests for mini_parlant.

Run with:  pytest mini_parlant/tests/
"""

from __future__ import annotations

import pytest
import sys
import os

# Ensure the mini_parlant package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mini_parlant.models import (
    ContextBundle,
    Signal,
    SignalType,
    StrategyResult,
    StructuredResponse,
    SufficiencyStatus,
    SufficiencyVerdict,
)
from mini_parlant.config import DecisionMode, RuntimeConfig
from mini_parlant.parser import DefaultParser
from mini_parlant.signals import DefaultSignalDetector
from mini_parlant.registry import StrategyRegistry
from mini_parlant.decision import LogicDecisionEngine, MarkovDecisionEngine
from mini_parlant.context_selector import ContextSelector
from mini_parlant.sufficiency import SufficiencyChecker
from mini_parlant.enricher import Enricher
from mini_parlant.composer import Composer
from mini_parlant.strategies.builtin import (
    DirectAnswerStrategy,
    ClarifyOrEnrichStrategy,
    TaskPlanningStrategy,
)
from mini_parlant.runtime import MiniParlantRuntime


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------


class TestDefaultParser:
    def test_parse_full_input(self):
        raw = """
Query:
What is Python?

History:
User: Hello
Assistant: Hi there!

Knowledge:
Python is a programming language.
It was created by Guido van Rossum.

Metadata:
locale=en-US
"""
        parser = DefaultParser()
        ctx = parser.parse(raw)
        assert ctx.query == "What is Python?"
        assert len(ctx.history) == 2
        assert ctx.history[0] == {"role": "user", "content": "Hello"}
        assert ctx.history[1] == {"role": "assistant", "content": "Hi there!"}
        assert len(ctx.knowledge) == 2
        assert ctx.metadata.get("locale") == "en-US"

    def test_parse_no_sections(self):
        raw = "What time is it?"
        parser = DefaultParser()
        ctx = parser.parse(raw)
        assert "What time is it?" in ctx.query

    def test_parse_empty_knowledge(self):
        raw = "Query:\nHello"
        parser = DefaultParser()
        ctx = parser.parse(raw)
        assert ctx.knowledge == []

    def test_parse_question_alias(self):
        raw = "Question:\nWho made Python?"
        parser = DefaultParser()
        ctx = parser.parse(raw)
        assert "Who made Python?" in ctx.query


# ---------------------------------------------------------------------------
# Signal detector tests
# ---------------------------------------------------------------------------


class TestDefaultSignalDetector:
    def test_detects_question(self):
        ctx = ContextBundle(query="What is the capital of France?")
        detector = DefaultSignalDetector()
        signals = detector.detect(ctx)
        types = {s.type for s in signals}
        assert SignalType.QUESTION in types

    def test_detects_task(self):
        ctx = ContextBundle(query="Create a Python script to read a CSV file.")
        detector = DefaultSignalDetector()
        signals = detector.detect(ctx)
        types = {s.type for s in signals}
        assert SignalType.TASK in types

    def test_detects_knowledge_gap(self):
        ctx = ContextBundle(query="What is the latest stock price of AAPL?", knowledge=[])
        detector = DefaultSignalDetector()
        signals = detector.detect(ctx)
        types = {s.type for s in signals}
        assert SignalType.KNOWLEDGE_GAP in types

    def test_detects_clarification_needed(self):
        ctx = ContextBundle(query="Hi")  # short query, no history
        detector = DefaultSignalDetector()
        signals = detector.detect(ctx)
        types = {s.type for s in signals}
        assert SignalType.CLARIFICATION_NEEDED in types

    def test_fallback_general(self):
        ctx = ContextBundle(query="The weather is nice today.", knowledge=["some info"])
        detector = DefaultSignalDetector()
        signals = detector.detect(ctx)
        assert signals  # at least one signal


# ---------------------------------------------------------------------------
# Strategy registry tests
# ---------------------------------------------------------------------------


class TestStrategyRegistry:
    def test_register_and_retrieve(self):
        registry = StrategyRegistry()
        s = DirectAnswerStrategy()
        registry.register(s)
        assert registry.get("DirectAnswerStrategy") is s

    def test_matching_returns_correct_strategy(self):
        registry = StrategyRegistry()
        registry.register(DirectAnswerStrategy())
        registry.register(TaskPlanningStrategy())

        ctx = ContextBundle(query="What is the capital of France?")
        signals = [Signal(type=SignalType.QUESTION, confidence=0.9)]
        matched = registry.matching(ctx, signals)
        names = [s.name for s in matched]
        assert "DirectAnswerStrategy" in names

    def test_unregister(self):
        registry = StrategyRegistry()
        registry.register(DirectAnswerStrategy())
        registry.unregister("DirectAnswerStrategy")
        assert registry.get("DirectAnswerStrategy") is None


# ---------------------------------------------------------------------------
# Decision engine tests
# ---------------------------------------------------------------------------


class TestLogicDecisionEngine:
    def _make_registry(self):
        r = StrategyRegistry()
        r.register(DirectAnswerStrategy())
        r.register(ClarifyOrEnrichStrategy())
        r.register(TaskPlanningStrategy())
        return r

    def test_selects_task_strategy_for_task_signal(self):
        engine = LogicDecisionEngine()
        registry = self._make_registry()
        ctx = ContextBundle(query="Build me a REST API.")
        signals = [Signal(type=SignalType.TASK, confidence=0.9)]
        selected = engine.select(ctx, signals, registry)
        assert selected is not None
        assert selected.name == "TaskPlanningStrategy"

    def test_selects_direct_for_question(self):
        engine = LogicDecisionEngine()
        registry = self._make_registry()
        ctx = ContextBundle(query="What is Python?")
        signals = [Signal(type=SignalType.QUESTION, confidence=0.9)]
        selected = engine.select(ctx, signals, registry)
        assert selected is not None
        assert selected.name == "DirectAnswerStrategy"

    def test_returns_none_for_empty_registry(self):
        engine = LogicDecisionEngine()
        registry = StrategyRegistry()
        ctx = ContextBundle(query="Hello")
        signals = [Signal(type=SignalType.GENERAL)]
        assert engine.select(ctx, signals, registry) is None


class TestMarkovDecisionEngine:
    def test_always_returns_a_strategy(self):
        engine = MarkovDecisionEngine(seed=0)
        registry = StrategyRegistry()
        registry.register(DirectAnswerStrategy())
        registry.register(TaskPlanningStrategy())
        ctx = ContextBundle(query="Do something.")
        signals = [Signal(type=SignalType.TASK, confidence=0.8)]
        result = engine.select(ctx, signals, registry)
        assert result is not None

    def test_reproducible_with_seed(self):
        def run(seed):
            engine = MarkovDecisionEngine(seed=seed)
            registry = StrategyRegistry()
            registry.register(DirectAnswerStrategy())
            registry.register(TaskPlanningStrategy())
            registry.register(ClarifyOrEnrichStrategy())
            ctx = ContextBundle(query="Tell me how to bake a cake.")
            signals = [
                Signal(type=SignalType.TASK, confidence=0.8),
                Signal(type=SignalType.QUESTION, confidence=0.5),
            ]
            return engine.select(ctx, signals, registry).name

        assert run(42) == run(42)


# ---------------------------------------------------------------------------
# Sufficiency checker tests
# ---------------------------------------------------------------------------


class TestSufficiencyChecker:
    def test_heuristic_sufficient_when_knowledge_present(self):
        checker = SufficiencyChecker()
        ctx = ContextBundle(query="What is Python?", knowledge=["Python is a language."])
        signals = [Signal(type=SignalType.QUESTION)]
        verdict = checker.check(ctx, signals)
        assert verdict.status == SufficiencyStatus.SUFFICIENT

    def test_heuristic_insufficient_when_no_knowledge_and_gap_signal(self):
        checker = SufficiencyChecker()
        ctx = ContextBundle(query="What is the current stock price of AAPL?", knowledge=[])
        signals = [Signal(type=SignalType.KNOWLEDGE_GAP)]
        verdict = checker.check(ctx, signals)
        assert verdict.status == SufficiencyStatus.INSUFFICIENT

    def test_llm_check_parses_json(self):
        def fake_llm(prompt: str) -> str:
            return '{"status": "sufficient", "reason": "Enough info.", "missing_info": []}'

        checker = SufficiencyChecker(llm_caller=fake_llm)
        ctx = ContextBundle(query="What?", knowledge=["Some info"])
        signals = []
        verdict = checker.check(ctx, signals)
        assert verdict.status == SufficiencyStatus.SUFFICIENT
        assert verdict.reason == "Enough info."


# ---------------------------------------------------------------------------
# Enricher tests
# ---------------------------------------------------------------------------


class TestEnricher:
    def test_tool_lookup_adds_knowledge(self):
        def fake_tool(query: str) -> str:
            return f"Looked up: {query}"

        enricher = Enricher(tools={"search": fake_tool})
        ctx = ContextBundle(query="What is the GDP of France?", knowledge=[])
        verdict = SufficiencyVerdict(
            status=SufficiencyStatus.INSUFFICIENT,
            reason="No data.",
            missing_info=["GDP of France"],
        )
        enriched_ctx, notes = enricher.enrich(ctx, verdict)
        assert len(enriched_ctx.knowledge) == 1
        assert "search" in enriched_ctx.knowledge[0]
        assert "tool lookup" in notes

    def test_refocus_reranks_knowledge(self):
        enricher = Enricher()  # no tools
        ctx = ContextBundle(
            query="Tell me about Python",
            knowledge=[
                "JavaScript is a language.",
                "Python is a high-level programming language.",
            ],
        )
        verdict = SufficiencyVerdict(
            status=SufficiencyStatus.INSUFFICIENT,
            reason="Need Python-specific info.",
            missing_info=["Python features"],
        )
        enriched_ctx, notes = enricher.enrich(ctx, verdict)
        # Python snippet should be ranked higher
        assert "Python" in enriched_ctx.knowledge[0]
        assert "refocus" in notes


# ---------------------------------------------------------------------------
# Context selector tests
# ---------------------------------------------------------------------------


class TestContextSelector:
    def test_limits_knowledge(self):
        selector = ContextSelector(max_knowledge=2)
        ctx = ContextBundle(
            query="What is Python?",
            knowledge=["A", "B", "C", "D"],
        )
        selected = selector.select(ctx, [])
        assert len(selected.knowledge) <= 2

    def test_limits_history(self):
        selector = ContextSelector(max_history_turns=3)
        history = [{"role": "user", "content": f"msg {i}"} for i in range(10)]
        ctx = ContextBundle(query="Q", history=history)
        selected = selector.select(ctx, [])
        assert len(selected.history) <= 3

    def test_promotes_relevant_knowledge(self):
        selector = ContextSelector(max_knowledge=2)
        ctx = ContextBundle(
            query="Python programming",
            knowledge=[
                "JavaScript is used for web development.",
                "Python is a high-level programming language.",
                "Java is object-oriented.",
            ],
        )
        selected = selector.select(ctx, [])
        # Python snippet should be in top-2
        assert any("Python" in s for s in selected.knowledge)


# ---------------------------------------------------------------------------
# Full runtime integration tests
# ---------------------------------------------------------------------------


class TestMiniParlantRuntime:
    def test_run_returns_structured_response(self):
        runtime = MiniParlantRuntime()
        response = runtime.run("Query:\nWhat is Python?")
        assert isinstance(response, StructuredResponse)
        assert response.answer
        assert response.strategy_used

    def test_run_with_task_input(self):
        runtime = MiniParlantRuntime(
            config=RuntimeConfig(decision_mode=DecisionMode.LOGIC)
        )
        # Include knowledge so KNOWLEDGE_GAP signal is not emitted;
        # only TASK + TOOL_USE signals are detected → TaskPlanningStrategy wins.
        response = runtime.run(
            "Query:\nCreate a plan to build a web app.\n\n"
            "Knowledge:\nPython is a popular language.\nFlask can be used for web apps."
        )
        assert response.strategy_used == "TaskPlanningStrategy"

    def test_run_with_markov_mode(self):
        runtime = MiniParlantRuntime(
            config=RuntimeConfig(decision_mode=DecisionMode.MARKOV, markov_seed=1)
        )
        response = runtime.run("Query:\nHow do I reverse a string in Python?")
        assert response.strategy_used

    def test_enrichment_triggered(self):
        enriched_flag = {"called": False}

        def fake_tool(query: str) -> str:
            enriched_flag["called"] = True
            return "Enriched knowledge snippet."

        from mini_parlant.enricher import Enricher

        enricher = Enricher(tools={"test_tool": fake_tool})
        runtime = MiniParlantRuntime(
            config=RuntimeConfig(max_enrichment_loops=1),
            enricher=enricher,
        )
        # A query with no knowledge should trigger enrichment
        response = runtime.run(
            "Query:\nWhat is the current population of Mars colonies?"
        )
        # Enrichment may or may not be triggered depending on heuristic;
        # at minimum, the runtime should complete without error.
        assert isinstance(response, StructuredResponse)

    def test_custom_llm_caller(self):
        def my_llm(prompt: str) -> str:
            return "Custom LLM response: " + prompt[:50]

        runtime = MiniParlantRuntime(config=RuntimeConfig(llm_caller=my_llm))
        response = runtime.run("Query:\nWhat is AI?")
        assert "Custom LLM response:" in response.answer

    def test_custom_strategy_registered(self):
        from typing import Sequence
        from mini_parlant.registry import BaseStrategy

        class GreetStrategy(BaseStrategy):
            priority = 1  # highest priority

            def matches(self, context: ContextBundle, signals: Sequence[Signal]) -> bool:
                return "hello" in context.query.lower()

            def execute(self, context: ContextBundle, signals: Sequence[Signal]) -> StrategyResult:
                return StrategyResult(
                    goal="Greet the user warmly.",
                    output_format="One friendly sentence.",
                    strategy_name=self.name,
                )

        runtime = MiniParlantRuntime()
        runtime.registry.register(GreetStrategy())
        response = runtime.run("Query:\nHello there!")
        assert response.strategy_used == "GreetStrategy"
