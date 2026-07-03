import dataclasses

import anthropic

from tools.confidence import Agreement, ConfidenceResult
from tools.models import Evidence

_MODEL = "claude-haiku-4-5-20251001"

_CONFLICT_SYSTEM = (
    "You are reviewing evidence chunks retrieved from a club knowledge base. "
    "Determine whether the pieces agree or conflict with each other on the topic. "
    "Reply with exactly one word: 'agreeing' or 'conflicting'."
)

_COMPOSE_SYSTEM = (
    "You are a helpful assistant answering questions for club members via Slack.\n"
    "Rules:\n"
    "1. Answer ONLY using the provided evidence — do not add outside knowledge.\n"
    "2. Cite each factual claim with its source label in brackets, "
    "e.g. [#general — 2026-06-21].\n"
    "3. Do NOT evaluate confidence yourself. Use exactly the confidence tier "
    "and reason provided.\n"
    "4. Format using Slack mrkdwn. Keep your answer concise (under 200 words).\n"
    "5. If the evidence is insufficient to answer the question, say so clearly "
    "without guessing."
)

_NO_EVIDENCE_REPLY = (
    "I couldn't find relevant information in the club's records to answer that question."
)


def _get_client(client: anthropic.Anthropic | None) -> anthropic.Anthropic:
    return client if client is not None else anthropic.Anthropic()


def _format_evidence(evidence: list[Evidence]) -> str:
    parts = []
    for i, ev in enumerate(evidence, 1):
        parts.append(f"[{i}] Source: {ev.citation.label}\n{ev.text}")
    return "\n\n".join(parts)


def evaluate_conflict(
    evidence: list[Evidence],
    *,
    client: anthropic.Anthropic | None = None,
) -> Agreement:
    """Ask Claude whether the provided evidence pieces agree or conflict.

    Returns 'agreeing', 'conflicting', or 'unknown' (when undetermined or
    when all evidence comes from a single source type).
    """
    if len({ev.source for ev in evidence}) < 2:
        return "unknown"

    c = _get_client(client)
    message = c.messages.create(
        model=_MODEL,
        max_tokens=10,
        system=_CONFLICT_SYSTEM,
        messages=[{"role": "user", "content": _format_evidence(evidence)}],
    )

    reply = message.content[0].text.strip().lower()
    if "agreeing" in reply:
        return "agreeing"
    if "conflicting" in reply:
        return "conflicting"
    return "unknown"


def compose_answer(
    question: str,
    evidence: list[Evidence],
    confidence: ConfidenceResult,
    *,
    client: anthropic.Anthropic | None = None,
) -> tuple[str, ConfidenceResult]:
    """Compose a Slack-ready answer from retrieved evidence and a confidence score.

    When confidence.conflict is 'unclear', calls evaluate_conflict to resolve it
    and returns an updated ConfidenceResult alongside the answer text.
    """
    if not evidence:
        return _NO_EVIDENCE_REPLY, confidence

    c = _get_client(client)
    updated_confidence = confidence

    if confidence.conflict == "unclear":
        agreement = evaluate_conflict(evidence, client=c)
        if agreement in ("agreeing", "conflicting"):
            source_names = ", ".join(sorted({ev.source for ev in evidence}))
            if agreement == "agreeing":
                new_conflict: bool = False
                new_reason = f"Corroborated by multiple independent sources: {source_names}."
            else:
                new_conflict = True
                new_reason = f"Found conflicting evidence across multiple sources: {source_names}."
            updated_confidence = dataclasses.replace(
                confidence,
                conflict=new_conflict,
                reason=new_reason,
            )

    user_content = (
        f"Evidence:\n{_format_evidence(evidence)}\n\n"
        f"Confidence: {updated_confidence.level} — {updated_confidence.reason}\n\n"
        f"Question: {question}"
    )

    message = c.messages.create(
        model=_MODEL,
        max_tokens=512,
        system=_COMPOSE_SYSTEM,
        messages=[{"role": "user", "content": user_content}],
    )

    return message.content[0].text.strip(), updated_confidence
