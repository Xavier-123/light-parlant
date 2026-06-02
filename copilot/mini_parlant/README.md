# mini-parlant

A **lightweight context optimization framework** inspired by [Parlant](https://github.com/emcie-co/parlant).

`mini-parlant` takes a long input text (query + dialogue history + retrieved knowledge + metadata)
and produces a **structured response** by routing through registered strategies, performing
self-sufficiency checks, and optionally enriching the context before calling an LLM.

---

## Architecture

```
raw_input (string)
     │
     ▼
┌─────────────┐
│   Parser    │  Splits raw text into ContextBundle
└──────┬──────┘  (query, history, knowledge, metadata)
       │
       ▼
┌──────────────────┐
│ SignalDetector   │  Detects TASK / QUESTION / KNOWLEDGE_GAP / TOOL_USE /
└──────┬───────────┘  CLARIFICATION_NEEDED / GENERAL signals
       │
       ▼
┌─────────────────┐
│ ContextSelector │  Trims & re-ranks knowledge snippets and history turns
└──────┬──────────┘
       │
       ▼
┌──────────────────────┐
│  SufficiencyChecker  │  Asks: "do we have enough info to answer?"
└──────┬───────────────┘  (heuristic or lightweight LLM call)
       │   insufficient?
       ▼
┌──────────────┐      ┌──────────────────────────────────┐
│   Enricher   │─────►│ Tool lookup OR knowledge refocus │
└──────┬───────┘      └──────────────────────────────────┘
       │  (at most max_enrichment_loops times)
       │  sufficient or loops exhausted
       ▼
┌─────────────────────────────────────────────────────────┐
│               Decision Engine                           │
│   LOGIC mode  → deterministic signal-weighted selection │
│   MARKOV mode → weighted-random draw (Markov chain)     │
└──────┬──────────────────────────────────────────────────┘
       │
       ▼
┌──────────────────┐
│ StrategyRegistry │  Holds all registered strategies
└──────┬───────────┘  (analogous to Parlant's Journeys)
       │
       ▼  strategy.execute(context, signals) → StrategyResult
┌──────────────┐      ┌──────────────────────────────────────┐
│   Composer   │─────►│  LLM prompt = goal + constraints     │
└──────┬───────┘      │             + output format          │
       │              └──────────────────────────────────────┘
       ▼
StructuredResponse
  .answer          – LLM-generated text
  .strategy_used   – which strategy was selected
  .signals         – detected signals
  .enriched        – whether enrichment ran
  .enrichment_notes
  .metadata
```

### Mapping to Parlant concepts

| Parlant concept      | mini-parlant equivalent              |
|----------------------|--------------------------------------|
| Journey / Guideline  | `BaseStrategy` + `StrategyRegistry`  |
| Event / Signal       | `Signal` (from `SignalDetector`)      |
| Engine               | `DecisionEngine` (Logic or Markov)   |
| Session context      | `ContextBundle`                      |
| NLP service          | `llm_caller` callable in `RuntimeConfig` |
| Tool service         | `Enricher.register_tool(name, fn)`   |

---

## Quickstart

```python
from mini_parlant import MiniParlantRuntime, RuntimeConfig, DecisionMode

runtime = MiniParlantRuntime()          # Logic mode by default
response = runtime.run("""
Query:
What is the capital of France?

Knowledge:
France is a country in Western Europe.
Paris is the capital and largest city of France.
""")

print(response.answer)
print("Strategy:", response.strategy_used)
```

### Using a real LLM

```python
import openai

def call_openai(prompt: str) -> str:
    resp = openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content

runtime = MiniParlantRuntime(config=RuntimeConfig(llm_caller=call_openai))
response = runtime.run(raw_input_text)
```

### Switching to Markov decision mode

```python
from mini_parlant import RuntimeConfig, DecisionMode

config = RuntimeConfig(
    decision_mode=DecisionMode.MARKOV,
    markov_seed=42,          # optional, for reproducibility
)
runtime = MiniParlantRuntime(config=config)
```

### Registering a custom strategy

```python
from typing import Sequence
from mini_parlant.registry import BaseStrategy
from mini_parlant.models import ContextBundle, Signal, StrategyResult

class SentimentStrategy(BaseStrategy):
    priority = 5   # lower = higher priority

    def matches(self, context: ContextBundle, signals: Sequence[Signal]) -> bool:
        return any(w in context.query.lower() for w in ("feel", "emotion", "sad", "happy"))

    def execute(self, context: ContextBundle, signals: Sequence[Signal]) -> StrategyResult:
        return StrategyResult(
            goal=f'Analyse sentiment of: "{context.query}"',
            constraints=["Be empathetic.", "Be brief."],
            output_format="One sentence describing the sentiment.",
            strategy_name=self.name,
        )

runtime.registry.register(SentimentStrategy())
```

### Adding a tool for enrichment

```python
from mini_parlant.enricher import Enricher

def lookup_stock_price(query: str) -> str:
    # ... call a real API ...
    return "AAPL: $175.23"

enricher = Enricher(tools={"stock_api": lookup_stock_price})
runtime = MiniParlantRuntime(
    config=RuntimeConfig(max_enrichment_loops=1),
    enricher=enricher,
)
```

---

## Input format

The default parser recognises the following **section headers** (case-insensitive):

| Section keyword(s)                     | Fills `ContextBundle` field |
|----------------------------------------|-----------------------------|
| `Query` / `Question`                   | `.query`                    |
| `History` / `Dialogue` / `Conversation`| `.history`                  |
| `Knowledge` / `Context` / `Retrieved` | `.knowledge`                |
| `Metadata` / `System`                  | `.metadata`                 |

Sections are separated by lines containing only the header keyword (optionally followed by `:`).

If no section headers are found, the entire input is treated as the query.

History lines should follow the format `Role: content` (e.g., `User: Hello`).
Metadata lines follow `key=value` format.

---

## Built-in strategies

| Strategy                  | Priority | Matches when…                                      |
|---------------------------|----------|----------------------------------------------------|
| `DirectAnswerStrategy`    | 10       | QUESTION or GENERAL signal detected               |
| `ClarifyOrEnrichStrategy` | 20       | CLARIFICATION_NEEDED or KNOWLEDGE_GAP signal      |
| `TaskPlanningStrategy`    | 30       | TASK or TOOL_USE signal detected                  |

Lower priority number = higher preference in the Logic engine.

---

## Configuration reference

```python
@dataclass
class RuntimeConfig:
    decision_mode: DecisionMode = DecisionMode.LOGIC
    # DecisionMode.LOGIC  – deterministic signal-driven selection
    # DecisionMode.MARKOV – probabilistic weighted-random selection

    max_enrichment_loops: int = 1
    # How many enrichment cycles are allowed (0 = disabled)

    llm_caller: Optional[Callable[[str], str]] = None
    # Your LLM wrapper.  When None, a stub is used.

    markov_seed: Optional[int] = None
    # Random seed for Markov engine reproducibility

    extra: Dict[str, Any] = field(default_factory=dict)
    # User-defined extension parameters
```

---

## Running the tests

```bash
cd mini_parlant
pip install pytest
pytest tests/
```

No API keys are required — all tests use the built-in stub LLM.

---

## Running the examples

```bash
cd mini_parlant
python examples/basic_usage.py
```

---

## Design principles

1. **Zero mandatory dependencies** — the package runs on the Python standard library alone.
2. **One enrichment loop maximum** — prevents runaway API costs and infinite recursion.
3. **Pluggable everything** — parser, signal detector, context selector, enricher, and
   decision engine can all be replaced by subclassing and injecting into `MiniParlantRuntime`.
4. **Parlant-inspired, not Parlant-copied** — the Journey/Guideline concept is mapped to
   lightweight `BaseStrategy` objects; the heavy persistence and async layers are omitted.
5. **Synchronous by default** — keeps the runtime trivially embeddable; async wrappers
   can be added by the caller.
