from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SearchRequest:
    query: str
    limit: int = 10


@dataclass(frozen=True)
class Citation:
    source: str  # "slack_decide" | "gdoc" | "gsheet" | "slack"
    label: str   # human-readable: "#general — 2026-06-21" / "Doc › Section" / "Sheet Title"


@dataclass(frozen=True)
class Evidence:
    source: str
    text: str
    citation: Citation
    similarity: float | None          # raw pgvector score; None for Slack RTS (no vector search)
    score: float | None = None        # reserved for future post-retrieval confidence scoring
    timestamp: str | None = None      # ISO 8601 or None
    author: str | None = None         # display name or user ID; None when not available
    metadata: dict[str, Any] = field(default_factory=dict)
