from dataclasses import dataclass
from typing import Literal

from tools.models import Evidence


@dataclass(frozen=True)
class ConfidenceResult:
    level: Literal["High", "Medium", "Low"]
    reason: str
    conflict: bool = False


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
        return ConfidenceResult(
            level="High",
            reason=f"Corroborated by multiple independent sources: {names}.",
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
