"""
Input parser for mini-parlant.

Responsibility: convert a raw (possibly very long) input string into a
:class:`~mini_parlant.models.ContextBundle`.

The default implementation uses simple section-header heuristics; callers
may subclass :class:`BaseParser` and inject a custom one into the runtime.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Dict, List, Optional

from mini_parlant.models import ContextBundle


class BaseParser(ABC):
    """Abstract base for input parsers."""

    @abstractmethod
    def parse(self, raw_input: str) -> ContextBundle:
        """Convert *raw_input* to a :class:`ContextBundle`."""


class DefaultParser(BaseParser):
    """
    Heuristic parser that recognises common section headings in the raw input.

    Supported section patterns (case-insensitive, with optional colon):
    - ``Query`` / ``Question``
    - ``History`` / ``Dialogue`` / ``Conversation``
    - ``Knowledge`` / ``Context`` / ``Retrieved``
    - ``Metadata`` / ``System``

    Any text before the first recognised heading is treated as the query if no
    explicit ``Query:`` section exists.

    Example raw input::

        Query: What is the capital of France?

        History:
        User: Hi
        Assistant: Hello!

        Knowledge:
        France is a country in Western Europe. Its capital is Paris.

        Metadata:
        locale=en-US
    """

    # Compiled section-header regex: captures ``<heading>:`` at start of line
    _SECTION_RE = re.compile(
        r"^\s*(?P<heading>query|question|history|dialogue|conversation|"
        r"knowledge|context|retrieved|metadata|system)\s*:?\s*$",
        re.IGNORECASE | re.MULTILINE,
    )

    def parse(self, raw_input: str) -> ContextBundle:
        sections = self._split_sections(raw_input)

        query = (
            sections.get("query")
            or sections.get("question")
            or raw_input.strip()
        )

        history_text = (
            sections.get("history")
            or sections.get("dialogue")
            or sections.get("conversation")
            or ""
        )
        history = self._parse_history(history_text)

        knowledge_text = (
            sections.get("knowledge")
            or sections.get("context")
            or sections.get("retrieved")
            or ""
        )
        knowledge = [k.strip() for k in knowledge_text.split("\n") if k.strip()]

        metadata_text = sections.get("metadata") or sections.get("system") or ""
        metadata = self._parse_metadata(metadata_text)

        return ContextBundle(
            query=query.strip(),
            history=history,
            knowledge=knowledge,
            metadata=metadata,
            raw_input=raw_input,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _split_sections(self, text: str) -> Dict[str, str]:
        """Return a dict mapping lower-case heading name -> section body."""
        parts: Dict[str, str] = {}
        current_heading: Optional[str] = None
        current_lines: List[str] = []

        for line in text.splitlines():
            m = self._SECTION_RE.match(line)
            if m:
                if current_heading is not None:
                    parts[current_heading] = "\n".join(current_lines).strip()
                current_heading = m.group("heading").lower()
                current_lines = []
            else:
                current_lines.append(line)

        if current_heading is not None:
            parts[current_heading] = "\n".join(current_lines).strip()
        elif current_lines:
            # No headings found at all – treat whole text as query
            parts["query"] = "\n".join(current_lines).strip()

        return parts

    def _parse_history(self, text: str) -> List[Dict[str, str]]:
        """
        Parse lines like ``User: …`` / ``Assistant: …`` into chat-API dicts.
        Lines that do not match the pattern are appended to the previous turn.
        """
        turns: List[Dict[str, str]] = []
        role_map = {
            "user": "user",
            "human": "user",
            "assistant": "assistant",
            "bot": "assistant",
            "system": "system",
        }
        line_re = re.compile(r"^(?P<role>\w+)\s*:\s*(?P<content>.+)$")

        for line in text.splitlines():
            m = line_re.match(line.strip())
            if m:
                role_key = m.group("role").lower()
                role = role_map.get(role_key, "user")
                turns.append({"role": role, "content": m.group("content").strip()})
            elif turns and line.strip():
                turns[-1]["content"] += " " + line.strip()

        return turns

    def _parse_metadata(self, text: str) -> Dict[str, str]:
        """Parse ``key=value`` pairs from metadata text."""
        meta: Dict[str, str] = {}
        for line in text.splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                meta[k.strip()] = v.strip()
        return meta
