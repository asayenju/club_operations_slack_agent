from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SearchRequest:
    query: str
    limit: int = 10


@dataclass(frozen=True)
class RetrievedChunk:
    source: str
    text: str
    permalink: str | None = None
    channel_id: str | None = None
    channel_name: str | None = None
    author_user_id: str | None = None
    author_name: str | None = None
    timestamp: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
