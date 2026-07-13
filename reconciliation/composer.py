from dataclasses import dataclass

import anthropic

from memoryAnswer.composer import evaluate_conflict
from tools.confidence import ConfidenceResult, score_confidence
from tools.models import Evidence

_MODEL = "claude-haiku-4-5-20251001"

_SYSTEM = (
    "You are reviewing evidence of an inconsistency in club records for a committee reconciliation review.\n"
    "Rules:\n"
    "1. Summarize ONLY from the provided evidence — do not add outside knowledge.\n"
    "2. Cite each factual claim by copying that evidence's exact 'Source: ...' label into "
    "brackets, e.g. if you see 'Source: #finance — 2026-06-01', cite it as "
    "[#finance — 2026-06-01]. Never cite by a number or position in the list.\n"
    "3. Do NOT evaluate confidence or urgency yourself — use exactly what is provided.\n"
    "4. Format using Slack mrkdwn, NOT standard Markdown: bold is *single asterisks*, "
    "never **double asterisks**. Do not use '#' headers or any other standard Markdown "
    "syntax Slack doesn't render. Keep the summary concise (under 150 words)."
)

_ACTION_SYSTEM = (
    "You are recommending a corrective action for a committee reconciliation review, "
    "given evidence of a conflict between club record sources.\n"
    "Rules:\n"
    "1. Base your recommendation ONLY on the provided evidence — do not invent facts.\n"
    "2. Recommend ONE concrete action a committee lead could take to resolve the conflict.\n"
    "3. Respond with a single sentence. No preamble, no markdown."
)

_SUMMARY_FALLBACK = (
    "A conflict was detected, but a summary could not be generated automatically. "
    "See the cited evidence below."
)

_ACTION_FALLBACK = "Review the conflicting evidence and reconcile manually."


@dataclass(frozen=True)
class ComposedProposal:
    blocks: list[dict]
    is_actionable: bool
    confidence: ConfidenceResult
    proposed_action: str | None = None


def _derive_urgency(confidence: ConfidenceResult) -> str:
    if confidence.level == "Low":
        return "Low"
    if confidence.conflict is True:
        return "High" if confidence.level == "High" else "Medium"
    if confidence.conflict == "unclear":
        return "Medium"
    return "Low"


def _format_evidence(evidence: list[Evidence]) -> str:
    parts = []
    for ev in evidence:
        parts.append(f"Source: {ev.citation.label}\n{ev.text}")
    return "\n\n".join(parts)


def _extract_text(message: anthropic.types.Message) -> str | None:
    if not message.content:
        return None
    return message.content[0].text


def _build_info_blocks(confidence: ConfidenceResult) -> list[dict]:
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*No reconciliation needed for this topic.*\n"
                    f"*Confidence:* {confidence.level} — {confidence.reason}"
                ),
            },
        },
    ]


def _generate_proposed_action(
    evidence: list[Evidence],
    confidence: ConfidenceResult,
    *,
    client: anthropic.Anthropic,
) -> str:
    user_content = (
        f"Evidence:\n{_format_evidence(evidence)}\n\n"
        f"Confidence: {confidence.level} — {confidence.reason}"
    )
    message = client.messages.create(
        model=_MODEL,
        max_tokens=128,
        system=_ACTION_SYSTEM,
        messages=[{"role": "user", "content": user_content}],
    )
    text = _extract_text(message)
    return text.strip() if text else _ACTION_FALLBACK


def compose_reconciliation_proposal(
    evidence: list[Evidence],
    confidence: ConfidenceResult,
    *,
    client: anthropic.Anthropic | None = None,
) -> ComposedProposal:
    updated_confidence = confidence

    if confidence.conflict == "unclear":
        agreement = evaluate_conflict(evidence, client=client)
        if agreement in ("agreeing", "conflicting"):
            updated_confidence = score_confidence(evidence, agreement=agreement)

    if updated_confidence.conflict is not True:
        return ComposedProposal(
            blocks=_build_info_blocks(updated_confidence),
            is_actionable=False,
            confidence=updated_confidence,
        )

    c = client if client is not None else anthropic.Anthropic()
    proposed_action = _generate_proposed_action(evidence, updated_confidence, client=c)
    urgency = _derive_urgency(updated_confidence)

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
    answer_text = _extract_text(message)
    summary = answer_text.strip() if answer_text is not None else _SUMMARY_FALLBACK

    return ComposedProposal(
        blocks=_build_blocks(summary, proposed_action, updated_confidence, urgency),
        is_actionable=True,
        confidence=updated_confidence,
        proposed_action=proposed_action,
    )


def _build_blocks(
    summary: str,
    proposed_action: str,
    confidence: ConfidenceResult,
    urgency: str,
) -> list[dict]:
    urgency_text = f"*Urgency:* {urgency}"
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
