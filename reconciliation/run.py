from __future__ import annotations

from dataclasses import asdict

from reconciliation.candidates import build_reconciliation_candidate
from reconciliation.composer import compose_reconciliation_proposal
from reconciliation.models import ReconciliationProposal
from reconciliation.service import ReconciliationProposalService
from tools.confidence import score_confidence


def run_reconciliation(
    *,
    workspace_id: str,
    topic: str,
    slack_client,
    slack_channel_id: str,
    proposal_service: ReconciliationProposalService,
) -> ReconciliationProposal | None:
    """Run one manual/dev reconciliation check for a topic.

    Posts a Slack message either way. Only persists a confirmable proposal
    (via `proposal_service`) when a real conflict was found — an informational
    post has nothing for a lead to confirm.
    """
    candidate = build_reconciliation_candidate(topic, workspace_id)
    evidence = candidate.all_evidence()
    confidence = score_confidence(evidence)
    result = compose_reconciliation_proposal(evidence, confidence)

    response = slack_client.chat_postMessage(
        channel=slack_channel_id,
        blocks=result.blocks,
        text=f"Reconciliation proposal: {topic}",
    )

    if not result.is_actionable:
        return None

    return proposal_service.create_pending(
        workspace_id=workspace_id,
        source_evidence=[asdict(ev) for ev in evidence],
        proposed_action={"description": result.proposed_action},
        slack_channel_id=slack_channel_id,
        slack_message_ts=response["ts"],
    )
