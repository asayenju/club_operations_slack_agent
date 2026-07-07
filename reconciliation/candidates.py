from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from tools.models import Evidence
from tools.vector_search import DEFAULT_MIN_SIMILARITY, list_decisions, search_decisions, search_knowledge


@dataclass(frozen=True)
class SourceResult:
    """Evidence found (or not found) for one source when building a candidate.

    `searched=True` with empty `evidence` is itself a signal (e.g. "no /decide
    record found for this topic") — distinct from a source never having been
    queried at all.
    """

    source: str
    evidence: list[Evidence]
    searched: bool = True


@dataclass(frozen=True)
class ReconciliationCandidate:
    """Grouped cross-source evidence for one reconciliation topic.

    Deliberately generic — missing-decision, budget/cost mismatch, and
    conflicting-fact scenarios all differ only in which `results` are empty
    and what their evidence text says, not in structure. Judging whether a
    candidate actually represents a real inconsistency is left to later
    stages (deterministic scoring via tools.confidence.score_confidence, or
    Claude's evaluate_conflict) — this type only assembles inputs for them.
    """

    workspace_id: str
    topic: str
    results: list[SourceResult] = field(default_factory=list)
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def all_evidence(self) -> list[Evidence]:
        return [ev for result in self.results for ev in result.evidence]

    def has_any_evidence(self) -> bool:
        return any(result.evidence for result in self.results)

    def empty_sources(self) -> list[str]:
        return [result.source for result in self.results if result.searched and not result.evidence]


def build_reconciliation_candidate(
    topic: str,
    workspace_id: str,
    *,
    limit: int = 5,
    min_similarity: float = DEFAULT_MIN_SIMILARITY,
) -> ReconciliationCandidate:
    """Assemble grouped cross-source evidence for one reconciliation topic.

    Reuses the shared /ask retrieval tools (search_decisions, search_knowledge)
    rather than introducing a parallel search stack. Falls back to a
    non-semantic decision listing only when search_decisions finds nothing,
    since a real but low-similarity decision would otherwise look "missing".
    """
    normalized_topic = topic.strip()
    if not normalized_topic:
        raise ValueError("topic must not be empty")
    if not workspace_id.strip():
        raise ValueError("workspace_id must not be empty")

    decide_evidence = search_decisions(
        normalized_topic, workspace_id, limit=limit, min_similarity=min_similarity
    )
    if not decide_evidence:
        # Unfiltered fallback: lets a later summarization step confirm "no
        # decision addresses this topic" against the full decision list
        # rather than trusting an absence it can't verify. Deliberately not
        # topic-filtered here (that requires the judgment this module is
        # scoped to avoid) — acceptable at club-scale decision volumes;
        # revisit if a workspace's decision count grows large.
        decide_evidence = list_decisions(workspace_id)

    knowledge_evidence = search_knowledge(
        normalized_topic, workspace_id, limit=limit, min_similarity=min_similarity
    )
    gdoc_evidence = [ev for ev in knowledge_evidence if ev.source == "gdoc"]
    gsheet_evidence = [ev for ev in knowledge_evidence if ev.source == "gsheet"]

    results = [
        SourceResult(source="slack_decide", evidence=decide_evidence, searched=True),
        SourceResult(source="gdoc", evidence=gdoc_evidence, searched=True),
        SourceResult(source="gsheet", evidence=gsheet_evidence, searched=True),
    ]

    return ReconciliationCandidate(
        workspace_id=workspace_id,
        topic=normalized_topic,
        results=results,
    )


def build_reconciliation_candidates(
    topics: list[str],
    workspace_id: str,
    *,
    limit: int = 5,
    min_similarity: float = DEFAULT_MIN_SIMILARITY,
) -> list[ReconciliationCandidate]:
    """Build one ReconciliationCandidate per topic, in order.

    Does not decide what topics to check — that's the caller's job (e.g. a
    future scheduler). A bad topic fails the whole batch rather than being
    silently skipped, since callers are expected to supply pre-validated
    topics from a controlled source.
    """
    return [
        build_reconciliation_candidate(topic, workspace_id, limit=limit, min_similarity=min_similarity)
        for topic in topics
    ]
