from dataclasses import dataclass
from typing import Literal

from tools.models import Evidence


@dataclass(frozen=True)
class ConfidenceResult:
    level: Literal["High", "Medium", "Low"]
    reason: str
    conflict: bool | Literal["unclear"] = False


def score_confidence(evidence: list[Evidence]) -> ConfidenceResult:
    if not evidence:
        return ConfidenceResult(level="Low", reason="No relevant evidence found.")

    source_types = {ev.source for ev in evidence}
    has_decide = "slack_decide" in source_types
    others = source_types - {"slack_decide"}

    if has_decide:
        if others:
            other_names = ", ".join(sorted(others))
            return ConfidenceResult(
                level="High",
                reason=(
                    f"Supported by a /decide statement (also found in: {other_names}); "
                    "/decide takes priority."
                ),
                conflict=True,
            )
        return ConfidenceResult(
            level="High",
            reason="Supported by a formal /decide statement.",
        )

    if len(source_types) >= 2:
        names = ", ".join(sorted(source_types))
        doc_types = source_types & {"gdoc", "gsheet"}
        has_slack = "slack" in source_types

        if has_slack and doc_types:
            authoritative = _most_recent(evidence, doc_types)
            if authoritative and authoritative.timestamp:
                date = authoritative.timestamp[:10]
                note = (
                    f" {authoritative.source} takes priority over Slack"
                    f" (last modified {date})."
                )
            else:
                note = " Doc/Sheet evidence takes priority over Slack."
            return ConfidenceResult(
                level="High",
                reason=f"Found in multiple sources: {names}.{note}",
                conflict="unclear",
            )

        if len(doc_types) > 1:
            authoritative = _most_recent(evidence, doc_types)
            if authoritative and authoritative.timestamp:
                date = authoritative.timestamp[:10]
                note = f" Most recently modified: {authoritative.source} ({date})."
                return ConfidenceResult(
                    level="High",
                    reason=f"Found in multiple sources: {names}.{note} Agreement unverified.",
                    conflict="unclear",
                )

        return ConfidenceResult(
            level="High",
            reason=f"Found in multiple sources: {names}. Agreement unverified.",
            conflict="unclear",
        )

    [only_source] = source_types
    if only_source == "gdoc":
        return ConfidenceResult(level="Medium", reason="Found in a single Google Doc.")
    if only_source == "gsheet":
        return ConfidenceResult(level="Medium", reason="Found in a single Google Sheet.")

    return ConfidenceResult(
        level="Low",
        reason=f"Only found in {only_source}, which provides lower confidence.",
    )


def _most_recent(evidence: list[Evidence], sources: set[str]) -> Evidence | None:
    candidates = [ev for ev in evidence if ev.source in sources and ev.timestamp]
    return max(candidates, key=lambda ev: ev.timestamp) if candidates else None
