import dataclasses

import anthropic

from memoryAnswer.composer import evaluate_conflict
from tools.confidence import ConfidenceResult
from tools.models import Evidence

_MODEL = "claude-haiku-4-5-20251001"

_SYSTEM = (
    "You are reviewing evidence of an inconsistency in club records for a committee reconciliation review.\n"
    "Rules:\n"
    "1. Summarize ONLY from the provided evidence — do not add outside knowledge.\n"
    "2. Cite each factual claim with its source label in brackets, e.g. [#finance — 2026-06-01].\n"
    "3. Do NOT evaluate confidence or urgency yourself — use exactly what is provided.\n"
    "4. Format using Slack mrkdwn. Keep the summary concise (under 150 words)."
)

_CAUTIOUS_SUMMARY = (
    "A potential inconsistency was detected, but the available evidence is insufficient "
    "to make a concrete recommendation. Human review is needed before any action is taken."
)


def _derive_urgency(confidence: ConfidenceResult) -> str | None:
    if confidence.level == "Low":
        return None
    if confidence.conflict is True:
        return "High" if confidence.level == "High" else "Medium"
    if confidence.conflict == "unclear":
        return "Medium"
    return None


def _format_evidence(evidence: list[Evidence]) -> str:
    parts = []
    for i, ev in enumerate(evidence, 1):
        parts.append(f"[{i}] Source: {ev.citation.label}\n{ev.text}")
    return "\n\n".join(parts)


def compose_reconciliation_proposal(
    evidence: list[Evidence],
    proposed_action: str,
    confidence: ConfidenceResult,
    *,
    client: anthropic.Anthropic | None = None,
) -> list[dict]:
    c = client if client is not None else anthropic.Anthropic()
    updated_confidence = confidence

    if confidence.conflict == "unclear":
        agreement = evaluate_conflict(evidence, client=c)
        if agreement in ("agreeing", "conflicting"):
            source_names = ", ".join(sorted({ev.source for ev in evidence}))
            if agreement == "agreeing":
                updated_confidence = dataclasses.replace(
                    confidence,
                    conflict=False,
                    reason=f"Corroborated by multiple independent sources: {source_names}.",
                )
            else:
                updated_confidence = dataclasses.replace(
                    confidence,
                    conflict=True,
                    reason=f"Found conflicting evidence across multiple sources: {source_names}.",
                )

    urgency = _derive_urgency(updated_confidence)

    if updated_confidence.level == "Low":
        summary = _CAUTIOUS_SUMMARY
    else:
        user_content = (
            f"Evidence:\n{_format_evidence(evidence)}\n\n"
            f"Proposed action: {proposed_action}\n\n"
            f"Urgency: {urgency}\n"
            f"Confidence: {updated_confidence.level} — {updated_confidence.reason}"
        )
        message = c.messages.create(
            model=_MODEL,
            max_tokens=512,
            system=_SYSTEM,
            messages=[{"role": "user", "content": user_content}],
        )
        summary = message.content[0].text.strip()

    return _build_blocks(summary, proposed_action, updated_confidence, urgency)


def _build_blocks(
    summary: str,
    proposed_action: str,
    confidence: ConfidenceResult,
    urgency: str | None,
) -> list[dict]:
    urgency_text = f"*Urgency:* {urgency}" if urgency else "*Urgency:* Low"
    confidence_text = f"*Confidence:* {confidence.level} — {confidence.reason}"

    return [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": ":mag: Reconciliation Proposal"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": summary},
        },
        {"type": "divider"},
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": urgency_text},
                {"type": "mrkdwn", "text": confidence_text},
            ],
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Proposed action:* {proposed_action}"},
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "React with :white_check_mark: to approve · Expires in 72 hours · Only committee leads may approve",
                }
            ],
        },
    ]
