"""Mini Parlant-style lightweight context optimization framework.

This single-file implementation provides:
- Strategy registry (Journey-like)
- Two decision modes: Markov and LLM-like scoring
- Lightweight guideline matching
- Prompt planning with goal / constraints / output schema
- Self-reflection loop with tool calling when data is insufficient
- Structured JSON output

Design goals:
- Keep dependencies to the Python standard library only
- Make each component replaceable with a real embedding model / LLM / tool backend later
- Preserve the core Parlant loop: select strategy -> match rules -> generate -> judge -> optionally tool loop -> finalize
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Callable, Dict, Iterable, List, Optional, Protocol, Sequence, Tuple


# =========================
# Data models
# =========================


@dataclass
class KnowledgeChunk:
    """A retrieved knowledge chunk."""

    id: str
    text: str
    source: str = ""
    score: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ParsedContext:
    """Structured view of the raw input context."""

    query: str
    history: str = ""
    knowledge: List[KnowledgeChunk] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    raw_text: str = ""


@dataclass
class Strategy:
    """Lightweight journey / strategy definition."""

    id: str
    name: str
    description: str
    trigger_keywords: List[str] = field(default_factory=list)
    goal: str = ""
    constraints: List[str] = field(default_factory=list)
    output_schema: Dict[str, Any] = field(default_factory=dict)
    tool_candidates: List[str] = field(default_factory=list)
    priority: int = 0
    transitions: Dict[str, float] = field(default_factory=dict)
    examples: List[str] = field(default_factory=list)


@dataclass
class DecisionResult:
    strategy_id: str
    confidence: float
    reason: str = ""
    mode: str = "markov"
    candidates: List[Tuple[str, float]] = field(default_factory=list)


@dataclass
class Guideline:
    """A lightweight rule used for matching and response shaping."""

    id: str
    condition_keywords: List[str]
    action: str
    priority: int = 0
    required_fields: List[str] = field(default_factory=list)
    optional_fields: List[str] = field(default_factory=list)
    output_hints: List[str] = field(default_factory=list)


@dataclass
class GuidelineMatch:
    guideline: Guideline
    score: float
    matched_keywords: List[str] = field(default_factory=list)


@dataclass
class GenerationPlan:
    """What the response generator should do."""

    goal: str
    constraints: List[str]
    output_schema: Dict[str, Any]
    selected_strategy: Strategy
    matched_guidelines: List[GuidelineMatch]
    context_summary: str
    tool_candidates: List[str] = field(default_factory=list)


@dataclass
class ReflectionResult:
    enough: bool
    missing: List[str] = field(default_factory=list)
    confidence: float = 0.0
    reason: str = ""


@dataclass
class ToolCall:
    name: str
    arguments: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    name: str
    ok: bool
    content: str
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FinalResponse:
    """Structured output returned by the engine."""

    answer: str
    strategy_id: str
    confidence: float
    used_tools: List[str] = field(default_factory=list)
    matched_guidelines: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)


# =========================
# Utilities
# =========================


_WORD_RE = re.compile(r"[\u4e00-\u9fff]+|[A-Za-z0-9_]+")


def tokenize(text: str) -> List[str]:
    return [t.lower() for t in _WORD_RE.findall(text or "")]


def cosine_sim(a: Dict[str, float], b: Dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for k, v in a.items():
        na += v * v
        dot += v * b.get(k, 0.0)
    for v in b.values():
        nb += v * v
    if na == 0 or nb == 0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def bow_vector(text: str) -> Dict[str, float]:
    counts: Dict[str, float] = {}
    for tok in tokenize(text):
        counts[tok] = counts.get(tok, 0.0) + 1.0
    return counts


def truncate_text(text: str, max_chars: int = 600) -> str:
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def safe_json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)


# =========================
# Context parsing
# =========================


class ContextParser:
    """Parse a long text into query / history / knowledge.

    Supported input forms:
    1) A structured dict-like input already split into fields.
    2) Raw text containing markers such as:
       Query:
       History:
       Knowledge:

    The parser is intentionally forgiving to keep it lightweight.
    """

    QUERY_PATTERNS = [r"(?:^|\n)\s*Query\s*[:：]\s*", r"(?:^|\n)\s*问题\s*[:：]\s*"]
    HISTORY_PATTERNS = [r"(?:^|\n)\s*History\s*[:：]\s*", r"(?:^|\n)\s*历史(?:对话)?\s*[:：]\s*"]
    KNOWLEDGE_PATTERNS = [r"(?:^|\n)\s*Knowledge\s*[:：]\s*", r"(?:^|\n)\s*检索知识\s*[:：]\s*"]

    def parse(self, raw_input: Any) -> ParsedContext:
        if isinstance(raw_input, ParsedContext):
            return raw_input

        if isinstance(raw_input, dict):
            knowledge_items = raw_input.get("knowledge", []) or []
            knowledge = [
                k if isinstance(k, KnowledgeChunk) else KnowledgeChunk(**k)
                for k in knowledge_items
            ]
            return ParsedContext(
                query=str(raw_input.get("query", "")).strip(),
                history=str(raw_input.get("history", "")).strip(),
                knowledge=knowledge,
                metadata=dict(raw_input.get("metadata", {}) or {}),
                raw_text=str(raw_input.get("raw_text", "")).strip(),
            )

        text = str(raw_input or "")
        if not text.strip():
            return ParsedContext(query="", raw_text="")

        query = self._extract_section(text, self.QUERY_PATTERNS)
        history = self._extract_section(text, self.HISTORY_PATTERNS)
        knowledge_text = self._extract_section(text, self.KNOWLEDGE_PATTERNS)

        # If not tagged, use a heuristic fallback.
        if not query:
            query = self._heuristic_first_line(text)
        knowledge = self._split_knowledge_chunks(knowledge_text)

        return ParsedContext(
            query=query.strip(),
            history=history.strip(),
            knowledge=knowledge,
            metadata={},
            raw_text=text,
        )

    def _extract_section(self, text: str, patterns: Sequence[str]) -> str:
        starts: List[Tuple[int, int]] = []
        for pat in patterns:
            m = re.search(pat, text, flags=re.IGNORECASE | re.MULTILINE)
            if m:
                starts.append((m.start(), m.end()))
        if not starts:
            return ""
        _, start = min(starts, key=lambda x: x[0])
        tail = text[start:]
        # Stop at the next known section marker if present.
        markers = ["Query:", "History:", "Knowledge:", "问题：", "历史：", "检索知识："]
        ends = []
        for marker in markers:
            idx = tail.find(marker)
            if idx > 0:
                ends.append(idx)
        return tail[: min(ends)] if ends else tail

    def _heuristic_first_line(self, text: str) -> str:
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        return lines[0] if lines else text[:200]

    def _split_knowledge_chunks(self, text: str) -> List[KnowledgeChunk]:
        text = text.strip()
        if not text:
            return []

        # Split on common separators or blank lines.
        raw_chunks = [c.strip() for c in re.split(r"\n\s*\n|\n[-=*]{3,}\n|\n\s*\d+[.)]\s*", text) if c.strip()]
        if not raw_chunks:
            raw_chunks = [text]

        chunks: List[KnowledgeChunk] = []
        for i, chunk in enumerate(raw_chunks[:20]):
            chunks.append(
                KnowledgeChunk(
                    id=f"k{i+1}",
                    text=chunk,
                    source="input",
                    score=0.0,
                )
            )
        return chunks


# =========================
# Strategy registry
# =========================


class StrategyRegistry:
    def __init__(self) -> None:
        self._strategies: Dict[str, Strategy] = {}

    def register(self, strategy: Strategy) -> None:
        self._strategies[strategy.id] = strategy

    def get(self, strategy_id: str) -> Strategy:
        if strategy_id not in self._strategies:
            raise KeyError(f"Strategy not found: {strategy_id}")
        return self._strategies[strategy_id]

    def list(self) -> List[Strategy]:
        return sorted(self._strategies.values(), key=lambda s: (-s.priority, s.id))

    def __len__(self) -> int:
        return len(self._strategies)


# =========================
# Guideline matching
# =========================


class GuidelineMatcher:
    """Lightweight matching using keyword overlap + optional embeddings placeholder.

    This intentionally avoids heavy LLM usage.
    """

    def __init__(self, guidelines: Optional[List[Guideline]] = None) -> None:
        self.guidelines = guidelines or []

    def match(self, context: ParsedContext, top_k: int = 5) -> List[GuidelineMatch]:
        query_tokens = set(tokenize(context.query))
        history_tokens = set(tokenize(context.history))
        knowledge_text = "\n".join(k.text for k in context.knowledge)
        knowledge_tokens = set(tokenize(knowledge_text))
        full_tokens = query_tokens | history_tokens | knowledge_tokens

        matches: List[GuidelineMatch] = []
        for guideline in self.guidelines:
            matched = [kw for kw in guideline.condition_keywords if kw.lower() in full_tokens]
            # Weighted overlap: query > history > knowledge (implemented simply via token presence)
            score = len(matched)
            if matched:
                score += guideline.priority / 100.0
                matches.append(
                    GuidelineMatch(
                        guideline=guideline,
                        score=float(score),
                        matched_keywords=matched,
                    )
                )

        matches.sort(key=lambda m: (-m.score, -m.guideline.priority, m.guideline.id))
        return matches[:top_k]


# =========================
# Decision engines
# =========================


class DecisionEngine(Protocol):
    def select(self, context: ParsedContext, strategies: Sequence[Strategy], history_strategy_id: str = "") -> DecisionResult:
        ...


class MarkovDecisionEngine:
    """Select the next strategy using a small transition matrix + heuristic features."""

    def __init__(self, default_strategy_id: str = "general") -> None:
        self.default_strategy_id = default_strategy_id

    def select(self, context: ParsedContext, strategies: Sequence[Strategy], history_strategy_id: str = "") -> DecisionResult:
        if not strategies:
            return DecisionResult(
                strategy_id=self.default_strategy_id,
                confidence=0.0,
                reason="No strategies registered.",
                mode="markov",
                candidates=[],
            )

        query_vec = bow_vector(context.query)
        history_vec = bow_vector(context.history)
        knowledge_vec = bow_vector("\n".join(k.text for k in context.knowledge))

        scored: List[Tuple[str, float]] = []
        for s in strategies:
            # Base score from keyword overlap against trigger keywords.
            trigger_text = " ".join(s.trigger_keywords + [s.name, s.description] + s.examples)
            trigger_vec = bow_vector(trigger_text)
            sim_q = cosine_sim(query_vec, trigger_vec)
            sim_h = cosine_sim(history_vec, trigger_vec)
            sim_k = cosine_sim(knowledge_vec, trigger_vec)
            base = 0.65 * sim_q + 0.2 * sim_h + 0.15 * sim_k

            # Transition adjustment from previous selected strategy.
            trans_bonus = 0.0
            if history_strategy_id and history_strategy_id in s.transitions:
                trans_bonus = s.transitions[history_strategy_id]
            elif history_strategy_id and s.id == history_strategy_id:
                trans_bonus = 0.05

            # Prefer higher priority if scores are similar.
            priority_bonus = s.priority / 1000.0
            total = base + trans_bonus + priority_bonus
            scored.append((s.id, total))

        scored.sort(key=lambda x: (-x[1], x[0]))
        best_id, best_score = scored[0]
        confidence = max(0.0, min(1.0, best_score))
        reason = f"Selected by Markov-style score; best={best_score:.4f}."
        return DecisionResult(
            strategy_id=best_id,
            confidence=confidence,
            reason=reason,
            mode="markov",
            candidates=scored[:5],
        )


class LLMLikeDecisionEngine:
    """A lightweight LLM-style selector.

    This is not a real model call; it is a deterministic scorer that mimics the
    output shape of an LLM decision step. Later you can replace _score_strategy
    with an actual small model call.
    """

    def __init__(self, min_confidence: float = 0.25) -> None:
        self.min_confidence = min_confidence

    def select(self, context: ParsedContext, strategies: Sequence[Strategy], history_strategy_id: str = "") -> DecisionResult:
        if not strategies:
            return DecisionResult(
                strategy_id="general",
                confidence=0.0,
                reason="No strategies registered.",
                mode="llm",
                candidates=[],
            )

        scored = []
        for s in strategies:
            score, reason = self._score_strategy(context, s, history_strategy_id)
            scored.append((s.id, score, reason))

        scored.sort(key=lambda x: (-x[1], x[0]))
        best_id, best_score, best_reason = scored[0]
        confidence = max(0.0, min(1.0, best_score))
        reason = best_reason if confidence >= self.min_confidence else f"Low-confidence fallback; {best_reason}"
        return DecisionResult(
            strategy_id=best_id,
            confidence=confidence,
            reason=reason,
            mode="llm",
            candidates=[(sid, score) for sid, score, _ in scored[:5]],
        )

    def _score_strategy(self, context: ParsedContext, strategy: Strategy, history_strategy_id: str) -> Tuple[float, str]:
        text = f"{context.query}\n{context.history}\n" + "\n".join(k.text for k in context.knowledge)
        text_tokens = set(tokenize(text))

        matched = [kw for kw in strategy.trigger_keywords if kw.lower() in text_tokens]
        matched_count = len(matched)
        density = matched_count / max(1, len(strategy.trigger_keywords))
        priority = strategy.priority / 100.0
        transition = 0.0
        if history_strategy_id and history_strategy_id in strategy.transitions:
            transition = strategy.transitions[history_strategy_id]

        # Simulate a small-model likelihood score.
        raw = 0.55 * density + 0.25 * min(1.0, matched_count / 3.0) + 0.15 * priority + 0.05 * transition
        raw = max(0.0, min(1.0, raw))
        reason = (
            f"Matched {matched_count} trigger keywords: {matched[:5]}"
            if matched
            else "No direct trigger keywords matched; using semantic fallback."
        )
        return raw, reason


# =========================
# Tool registry and execution
# =========================


class Tool(Protocol):
    name: str

    def run(self, arguments: Dict[str, Any]) -> ToolResult:
        ...


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise KeyError(f"Tool not found: {name}")
        return self._tools[name]

    def has(self, name: str) -> bool:
        return name in self._tools

    def list(self) -> List[str]:
        return sorted(self._tools.keys())


class KnowledgeSearchTool:
    """Example function tool for searching extra knowledge.

    By default it works over an in-memory corpus; replace it with your retrieval backend.
    """

    name = "knowledge_search"

    def __init__(self, corpus: Optional[List[KnowledgeChunk]] = None) -> None:
        self.corpus = corpus or []

    def run(self, arguments: Dict[str, Any]) -> ToolResult:
        query = str(arguments.get("query", "")).strip()
        if not query:
            return ToolResult(name=self.name, ok=False, content="Missing query.")

        q_tokens = set(tokenize(query))
        ranked: List[Tuple[float, KnowledgeChunk]] = []
        for chunk in self.corpus:
            c_tokens = set(tokenize(chunk.text))
            overlap = len(q_tokens & c_tokens)
            if overlap == 0:
                continue
            score = overlap / max(1, len(q_tokens))
            ranked.append((score, chunk))

        ranked.sort(key=lambda x: (-x[0], x[1].id))
        top = ranked[:5]
        content = "\n\n".join(f"[{c.id}] {c.text}" for _, c in top)
        data = {
            "results": [
                {"id": c.id, "text": c.text, "source": c.source, "score": s}
                for s, c in top
            ]
        }
        return ToolResult(name=self.name, ok=True, content=content, data=data)


class SimpleExtractorTool:
    """A toy tool that extracts a few facts from the current context."""

    name = "extract_facts"

    def run(self, arguments: Dict[str, Any]) -> ToolResult:
        text = str(arguments.get("text", ""))
        facts: List[str] = []
        for line in re.split(r"[\n。！？.!?]", text):
            line = line.strip()
            if not line:
                continue
            if len(line) > 12:
                facts.append(line)
        facts = facts[:8]
        content = "\n".join(f"- {f}" for f in facts) if facts else "No extractable facts."
        return ToolResult(name=self.name, ok=True, content=content, data={"facts": facts})


# =========================
# Reflection / sufficiency judgment
# =========================


class SelfJudge:
    """Decide whether the current context is sufficient to answer.

    This can be replaced by a real small model.
    """

    def judge(self, context: ParsedContext, plan: GenerationPlan, draft: str) -> ReflectionResult:
        query = context.query.lower()
        draft_text = (draft or "").lower()
        knowledge_text = "\n".join(k.text for k in context.knowledge).lower()

        missing: List[str] = []

        # Heuristic 1: empty or too short output.
        if len(draft.strip()) < 20:
            missing.append("answer_too_short")

        # Heuristic 2: if query asks for step/process but draft has no enumerated structure.
        process_keywords = ["how", "steps", "流程", "办理", "怎么", "如何", "过程"]
        if any(k in query for k in process_keywords):
            if not re.search(r"(^|\n)\s*(\d+[.)]|[-*])\s+", draft):
                missing.append("process_steps")

        # Heuristic 3: query terms should appear somewhere in answer or knowledge.
        q_terms = [t for t in tokenize(context.query) if len(t) > 1][:8]
        if q_terms:
            hit = sum(1 for t in q_terms if t in draft_text or t in knowledge_text)
            if hit < max(1, len(q_terms) // 4):
                missing.append("query_alignment")

        # Heuristic 4: if selected strategy requires tools and none used, be cautious.
        if plan.tool_candidates and not any(tool in draft_text for tool in plan.tool_candidates):
            # This is only a soft warning.
            if "knowledge" in plan.tool_candidates or "search" in plan.tool_candidates:
                missing.append("needs_external_knowledge")

        enough = len(missing) == 0
        confidence = 0.85 if enough else max(0.1, 0.75 - 0.15 * len(missing))
        reason = "Sufficient." if enough else f"Missing signals: {missing}"
        return ReflectionResult(enough=enough, missing=missing, confidence=confidence, reason=reason)


# =========================
# Prompt / plan builder
# =========================


class PromptBuilder:
    def build_plan(
        self,
        context: ParsedContext,
        strategy: Strategy,
        guideline_matches: List[GuidelineMatch],
    ) -> GenerationPlan:
        matched_actions = [m.guideline.action for m in guideline_matches]
        constraints = list(strategy.constraints)
        for m in guideline_matches:
            if m.guideline.output_hints:
                constraints.extend(m.guideline.output_hints)
        constraints = self._deduplicate_keep_order(constraints)

        summary = self._build_context_summary(context)
        tool_candidates = list(strategy.tool_candidates)
        for m in guideline_matches:
            for f in m.guideline.optional_fields + m.guideline.required_fields:
                if f not in tool_candidates and f in {"knowledge_search", "extract_facts", "search", "tool"}:
                    tool_candidates.append(f)

        goal = strategy.goal or (matched_actions[0] if matched_actions else "Answer the user accurately.")
        return GenerationPlan(
            goal=goal,
            constraints=constraints,
            output_schema=strategy.output_schema or {
                "answer": "string",
                "confidence": "number",
                "references": "array",
            },
            selected_strategy=strategy,
            matched_guidelines=guideline_matches,
            context_summary=summary,
            tool_candidates=tool_candidates,
        )

    def build_prompt(self, context: ParsedContext, plan: GenerationPlan, tool_notes: str = "") -> str:
        guidelines_block = []
        for m in plan.matched_guidelines:
            g = m.guideline
            guidelines_block.append(
                f"- [{g.id}] priority={g.priority} score={m.score:.3f} action={g.action} matched={m.matched_keywords}"
            )
        guidelines_str = "\n".join(guidelines_block) if guidelines_block else "- None"

        knowledge_str = "\n\n".join(
            f"[{k.id}]({k.source}) score={k.score:.3f}\n{truncate_text(k.text, 700)}"
            for k in context.knowledge
        ) or "None"

        return f"""# Goal
{plan.goal}

# Constraints
{chr(10).join(f'- {c}' for c in plan.constraints) if plan.constraints else '- None'}

# Output Schema
{safe_json_dumps(plan.output_schema)}

# Selected Strategy
ID: {plan.selected_strategy.id}
Name: {plan.selected_strategy.name}
Description: {plan.selected_strategy.description}

# Context Summary
{plan.context_summary}

# Query
{context.query}

# History
{context.history or 'None'}

# Retrieved Knowledge
{knowledge_str}

# Matched Guidelines
{guidelines_str}

# Tool Notes
{tool_notes or 'None'}

# Instruction
Return a structured JSON answer strictly following the schema. Do not fabricate missing facts; ask for clarification or state uncertainty if needed.
"""

    def _build_context_summary(self, context: ParsedContext) -> str:
        pieces = [f"Query: {truncate_text(context.query, 180)}"]
        if context.history:
            pieces.append(f"History: {truncate_text(context.history, 240)}")
        if context.knowledge:
            top = " | ".join(truncate_text(k.text, 120) for k in context.knowledge[:3])
            pieces.append(f"Knowledge: {top}")
        return "\n".join(pieces)

    def _deduplicate_keep_order(self, items: Iterable[str]) -> List[str]:
        seen = set()
        out = []
        for item in items:
            if item and item not in seen:
                seen.add(item)
                out.append(item)
        return out


# =========================
# Lightweight answer synthesis
# =========================


class LightweightAnswerSynthesizer:
    """Deterministic answer generator.

    In production, replace this with a true LLM call. Here we focus on framework logic.
    """

    def synthesize(
        self,
        context: ParsedContext,
        plan: GenerationPlan,
        tool_results: List[ToolResult],
    ) -> FinalResponse:
        citations = []
        for k in context.knowledge[:5]:
            if k.id:
                citations.append(k.id)
        used_tools = [t.name for t in tool_results if t.ok]

        answer_parts: List[str] = []
        answer_parts.append(f"已根据策略 {plan.selected_strategy.name} 处理你的请求。")

        if context.query:
            answer_parts.append(f"问题摘要：{truncate_text(context.query, 120)}")

        # Merge knowledge and tool content into a concise structured response.
        if tool_results:
            answer_parts.append("补充检索结果：")
            for tr in tool_results:
                if tr.ok and tr.content:
                    answer_parts.append(tr.content)

        if plan.matched_guidelines:
            answer_parts.append("匹配到的规则：")
            for m in plan.matched_guidelines[:5]:
                answer_parts.append(f"- {m.guideline.action} (rule={m.guideline.id}, score={m.score:.2f})")

        # Produce a structured final answer body.
        body = {
            "answer": self._compose_final_text(context, plan, tool_results),
            "confidence": round(self._estimate_confidence(context, plan, tool_results), 3),
            "references": citations,
            "strategy": plan.selected_strategy.id,
            "used_tools": used_tools,
        }
        return FinalResponse(
            answer=json.dumps(body, ensure_ascii=False, indent=2),
            strategy_id=plan.selected_strategy.id,
            confidence=body["confidence"],
            used_tools=used_tools,
            matched_guidelines=[m.guideline.id for m in plan.matched_guidelines],
            metadata={
                "goal": plan.goal,
                "constraints": plan.constraints,
            },
        )

    def _compose_final_text(self, context: ParsedContext, plan: GenerationPlan, tool_results: List[ToolResult]) -> str:
        # Minimal yet useful structure.
        query = context.query.strip()
        knowledge_text = "\n".join(k.text for k in context.knowledge)
        tool_text = "\n".join(tr.content for tr in tool_results if tr.ok)

        # Attempt a simple extractive summary.
        candidates = [query, knowledge_text, tool_text]
        merged = "\n".join(c for c in candidates if c)
        if not merged:
            return "当前缺少足够信息，建议补充更多上下文。"

        lines = [ln.strip() for ln in re.split(r"[\n。！？.!?]", merged) if ln.strip()]
        lines = list(dict.fromkeys(lines))
        lines = lines[:6]
        if not lines:
            return "当前缺少足够信息，建议补充更多上下文。"

        text = "；".join(lines)
        return text if len(text) < 800 else text[:797] + "..."

    def _estimate_confidence(self, context: ParsedContext, plan: GenerationPlan, tool_results: List[ToolResult]) -> float:
        base = 0.55
        if context.knowledge:
            base += min(0.2, 0.04 * len(context.knowledge))
        if tool_results:
            base += min(0.15, 0.05 * sum(1 for t in tool_results if t.ok))
        if plan.matched_guidelines:
            base += min(0.1, 0.03 * len(plan.matched_guidelines))
        return max(0.0, min(0.98, base))


# =========================
# Core engine
# =========================


class MiniParlantEngine:
    """The full lightweight pipeline."""

    def __init__(
        self,
        strategy_registry: StrategyRegistry,
        guideline_matcher: GuidelineMatcher,
        tool_registry: Optional[ToolRegistry] = None,
        decision_mode: str = "markov",
        max_internal_loops: int = 2,
        top_k_guidelines: int = 5,
    ) -> None:
        self.strategy_registry = strategy_registry
        self.guideline_matcher = guideline_matcher
        self.tool_registry = tool_registry or ToolRegistry()
        self.decision_mode = decision_mode
        self.max_internal_loops = max_internal_loops
        self.top_k_guidelines = top_k_guidelines

        self.parser = ContextParser()
        self.markov_decider = MarkovDecisionEngine(default_strategy_id="general")
        self.llm_decider = LLMLikeDecisionEngine()
        self.prompt_builder = PromptBuilder()
        self.judge = SelfJudge()
        self.synthesizer = LightweightAnswerSynthesizer()

        self._strategy_history_id = ""

    def process(self, raw_input: Any) -> FinalResponse:
        context = self.parser.parse(raw_input)
        strategies = self.strategy_registry.list()

        # 1) strategy selection
        decision = self._select_strategy(context, strategies)
        selected_strategy = self.strategy_registry.get(decision.strategy_id)

        # 2) guideline matching
        guideline_matches = self.guideline_matcher.match(context, top_k=self.top_k_guidelines)

        # 3) plan & prompt
        plan = self.prompt_builder.build_plan(context, selected_strategy, guideline_matches)

        # 4) generate + self-judge + optional tool loop
        tool_results: List[ToolResult] = []
        draft = self._draft_answer(context, plan, tool_results)
        reflection = self.judge.judge(context, plan, draft)

        internal_loop = 0
        while not reflection.enough and internal_loop < self.max_internal_loops:
            internal_loop += 1
            calls = self._plan_tool_calls(context, plan, reflection)
            if not calls:
                break
            tool_results.extend(self._execute_tools(calls, context, plan))
            draft = self._draft_answer(context, plan, tool_results)
            reflection = self.judge.judge(context, plan, draft)

        final_response = self.synthesizer.synthesize(context, plan, tool_results)
        final_response.metadata.update(
            {
                "decision_mode": decision.mode,
                "decision_reason": decision.reason,
                "decision_confidence": decision.confidence,
                "reflection": asdict(reflection),
                "internal_loops": internal_loop,
                "tool_results": [asdict(t) for t in tool_results],
                "selected_candidates": decision.candidates,
            }
        )
        self._strategy_history_id = selected_strategy.id
        return final_response

    def _select_strategy(self, context: ParsedContext, strategies: Sequence[Strategy]) -> DecisionResult:
        if self.decision_mode == "llm":
            return self.llm_decider.select(context, strategies, history_strategy_id=self._strategy_history_id)
        return self.markov_decider.select(context, strategies, history_strategy_id=self._strategy_history_id)

    def _draft_answer(self, context: ParsedContext, plan: GenerationPlan, tool_results: List[ToolResult]) -> str:
        tool_notes = "\n".join(f"{t.name}: {t.content}" for t in tool_results if t.ok)
        prompt = self.prompt_builder.build_prompt(context, plan, tool_notes=tool_notes)
        # In a real implementation, send `prompt` to a model.
        # Here we only use it as a transparent intermediate artifact.
        return self._extractive_draft(context, plan, tool_results, prompt)

    def _extractive_draft(self, context: ParsedContext, plan: GenerationPlan, tool_results: List[ToolResult], prompt: str) -> str:
        # Heuristic draft: pull the most relevant sentences from the query, knowledge, and tools.
        sentences: List[str] = []
        for src in [context.query, context.history, "\n".join(k.text for k in context.knowledge), "\n".join(t.content for t in tool_results if t.ok)]:
            for part in re.split(r"[\n。！？.!?]", src):
                p = part.strip()
                if len(p) >= 8:
                    sentences.append(p)
        unique = []
        seen = set()
        for s in sentences:
            if s not in seen:
                seen.add(s)
                unique.append(s)
        unique = unique[:8]
        if not unique:
            return "信息不足，无法生成可靠答案。"

        structured = {
            "goal": plan.goal,
            "answer": "；".join(unique[:5]),
            "constraints": plan.constraints[:6],
            "format": plan.output_schema,
            "note": "This is a lightweight draft; real model generation can replace this step.",
        }
        return json.dumps(structured, ensure_ascii=False, indent=2)

    def _plan_tool_calls(self, context: ParsedContext, plan: GenerationPlan, reflection: ReflectionResult) -> List[ToolCall]:
        # Small internal tool planner.
        calls: List[ToolCall] = []
        query = context.query
        query_l = query.lower()

        # Prefer explicit tool candidates from the selected strategy.
        candidates = plan.tool_candidates or ["knowledge_search"]

        if "knowledge_search" in candidates or "search" in candidates:
            if context.knowledge:
                # Search using the user's query, with a fallback to missing terms.
                search_query = query
                if reflection.missing:
                    search_query = f"{query} {' '.join(reflection.missing)}"
                calls.append(ToolCall(name="knowledge_search", arguments={"query": search_query}))

        if "extract_facts" in candidates:
            calls.append(ToolCall(name="extract_facts", arguments={"text": context.history + "\n" + query}))

        # Extra heuristics: when the query indicates process or steps and we still lack data, search.
        if not calls and any(k in query_l for k in ["how", "步骤", "流程", "如何", "怎么"]):
            calls.append(ToolCall(name="knowledge_search", arguments={"query": query}))

        # Avoid over-calling tools.
        return calls[:2]

    def _execute_tools(self, calls: List[ToolCall], context: ParsedContext, plan: GenerationPlan) -> List[ToolResult]:
        results: List[ToolResult] = []
        for call in calls:
            if not self.tool_registry.has(call.name):
                results.append(ToolResult(name=call.name, ok=False, content=f"Tool not registered: {call.name}"))
                continue
            tool = self.tool_registry.get(call.name)
            try:
                result = tool.run(call.arguments)
            except Exception as exc:  # pragma: no cover - defensive
                result = ToolResult(name=call.name, ok=False, content=f"Tool execution error: {exc}")
            results.append(result)
        return results


# =========================
# Default bootstrap helpers
# =========================


def build_default_engine(decision_mode: str = "markov") -> MiniParlantEngine:
    """Create a ready-to-use engine with sample strategies/guidelines/tools."""

    registry = StrategyRegistry()

    registry.register(
        Strategy(
            id="general",
            name="General Answering",
            description="Handle general conversational or mixed-context questions.",
            trigger_keywords=["general", "chat", "other", "misc", "问答"],
            goal="Provide a concise, correct answer.",
            constraints=["Do not invent facts.", "Prefer structured output."],
            output_schema={
                "answer": "string",
                "confidence": "number",
                "references": "array[string]",
            },
            tool_candidates=["knowledge_search"],
            priority=10,
            transitions={"faq": 0.15, "workflow": 0.10, "multi_hop": 0.05},
        )
    )

    registry.register(
        Strategy(
            id="faq",
            name="FAQ Answering",
            description="Answer direct questions from available knowledge.",
            trigger_keywords=["what", "which", "when", "where", "how", "是什么", "多少", "是否", "能否", "吗"],
            goal="Answer the user's question directly using the best available evidence.",
            constraints=["Use only retrieved knowledge and explicit facts.", "If uncertain, say so."],
            output_schema={"answer": "string", "references": "array[string]", "confidence": "number"},
            tool_candidates=["knowledge_search"],
            priority=90,
            transitions={"general": 0.05, "workflow": 0.10, "multi_hop": 0.08},
        )
    )

    registry.register(
        Strategy(
            id="workflow",
            name="Workflow / SOP",
            description="Provide steps, procedure, or operational guidance.",
            trigger_keywords=["step", "steps", "procedure", "workflow", "process", "流程", "步骤", "办理", "操作"],
            goal="Produce ordered steps and notes.",
            constraints=["Preserve step order.", "Highlight prerequisites and warnings."],
            output_schema={
                "title": "string",
                "steps": "array[string]",
                "warnings": "array[string]",
                "references": "array[string]",
            },
            tool_candidates=["knowledge_search", "extract_facts"],
            priority=80,
            transitions={"faq": 0.10, "general": 0.05, "multi_hop": 0.12},
        )
    )

    registry.register(
        Strategy(
            id="multi_hop",
            name="Multi-hop Reasoning",
            description="Combine multiple chunks and infer the final answer.",
            trigger_keywords=["compare", "combine", "infer", "reason", "multi", "多个", "综合", "推理"],
            goal="Synthesize information from multiple sources.",
            constraints=["Show concise reasoning.", "Mark assumptions explicitly."],
            output_schema={
                "summary": "string",
                "reasoning": "array[string]",
                "answer": "string",
                "references": "array[string]",
            },
            tool_candidates=["knowledge_search", "extract_facts"],
            priority=70,
            transitions={"faq": 0.10, "workflow": 0.08, "general": 0.03},
        )
    )

    registry.register(
        Strategy(
            id="policy",
            name="Policy / Constraint Handling",
            description="Handle policy-heavy, rule-bound, or compliance-heavy requests.",
            trigger_keywords=["policy", "rule", "compliance", "limit", "restriction", "规则", "政策", "约束", "限制"],
            goal="Answer with careful constraints and explicit uncertainty.",
            constraints=["Never fabricate policy details.", "Prefer conservative wording."],
            output_schema={
                "answer": "string",
                "constraints": "array[string]",
                "references": "array[string]",
            },
            tool_candidates=["knowledge_search"],
            priority=85,
            transitions={"faq": 0.06, "workflow": 0.06, "general": 0.02},
        )
    )

    guidelines = [
        Guideline(
            id="g_open_fact",
            condition_keywords=["what", "when", "where", "how", "是什么", "多少", "是否"],
            action="Answer directly and cite available evidence.",
            priority=60,
            required_fields=["answer"],
            output_hints=["Keep answer concise."],
        ),
        Guideline(
            id="g_steps",
            condition_keywords=["step", "步骤", "流程", "办理", "procedure"],
            action="Return ordered steps with prerequisites and warnings.",
            priority=70,
            required_fields=["steps"],
            output_hints=["Use numbered steps."],
        ),
        Guideline(
            id="g_uncertain",
            condition_keywords=["maybe", "uncertain", "不确定", "可能"],
            action="Express uncertainty and propose a way to verify.",
            priority=50,
            required_fields=["answer"],
            output_hints=["State uncertainty clearly."],
        ),
    ]

    tool_registry = ToolRegistry()
    # An empty corpus is fine; you can inject RAG chunks later.
    tool_registry.register(KnowledgeSearchTool(corpus=[]))
    tool_registry.register(SimpleExtractorTool())

    return MiniParlantEngine(
        strategy_registry=registry,
        guideline_matcher=GuidelineMatcher(guidelines=guidelines),
        tool_registry=tool_registry,
        decision_mode=decision_mode,
        max_internal_loops=2,
        top_k_guidelines=5,
    )


# =========================
# Demo
# =========================


def demo() -> None:
    engine = build_default_engine(decision_mode="markov")

    raw_input = {
        "query": "如何设计一个轻量化的上下文优化框架？",
        "history": "用户之前问过：怎样把长文本压缩成结构化上下文。",
        "knowledge": [
            {
                "id": "kb1",
                "text": "框架应包含策略注册、决策引擎、自检循环、工具补充和结构化输出。",
                "source": "kb",
                "score": 0.93,
            },
            {
                "id": "kb2",
                "text": "当信息不足时，可以通过工具检索补充知识，再重新生成。",
                "source": "kb",
                "score": 0.88,
            },
        ],
        "metadata": {"request_id": "demo-001"},
    }

    result = engine.process(raw_input)
    print(result.to_json())


if __name__ == "__main__":
    demo()
