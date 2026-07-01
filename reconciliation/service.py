from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from reconciliation.models import ProposalStatus, ReconciliationProposal
from reconciliation.repository import ReconciliationProposalRepository


class ProposalNotFound(RuntimeError):
    pass


class InvalidProposalTransition(RuntimeError):
    pass


class ReconciliationProposalService:
    def __init__(self, repository: ReconciliationProposalRepository):
        self.repository = repository

    def create_pending(
        self,
        *,
        workspace_id: str,
        source_evidence: list[dict[str, Any]],
        proposed_action: dict[str, Any],
        expires_at: datetime,
        slack_channel_id: str | None = None,
        slack_message_ts: str | None = None,
        created_at: datetime | None = None,
        proposal_id: str | None = None,
    ) -> ReconciliationProposal:
        if not workspace_id.strip():
            raise ValueError("workspace_id must not be empty")
        if not proposed_action:
            raise ValueError("proposed_action must not be empty")

        timestamp = created_at or datetime.now(UTC)
        proposal = ReconciliationProposal(
            id=proposal_id or str(uuid4()),
            workspace_id=workspace_id,
            status=ProposalStatus.PENDING,
            source_evidence=source_evidence,
            proposed_action=proposed_action,
            slack_channel_id=slack_channel_id,
            slack_message_ts=slack_message_ts,
            created_at=timestamp,
            expires_at=expires_at,
        ).with_audit_event("created", timestamp)
        return self.repository.create_pending(proposal)

    def find_by_slack_message(
        self,
        workspace_id: str,
        slack_channel_id: str,
        slack_message_ts: str,
    ) -> ReconciliationProposal | None:
        return self.repository.find_by_slack_message(
            workspace_id,
            slack_channel_id,
            slack_message_ts,
        )

    def confirm(
        self,
        *,
        workspace_id: str,
        proposal_id: str,
        approving_user_id: str,
        confirmed_at: datetime | None = None,
    ) -> ReconciliationProposal:
        proposal = self._require_proposal(workspace_id, proposal_id)
        timestamp = confirmed_at or datetime.now(UTC)
        self._require_pending(proposal)
        if proposal.expires_at <= timestamp:
            raise InvalidProposalTransition("expired proposals cannot be confirmed")

        confirmed = replace(
            proposal,
            status=ProposalStatus.CONFIRMED,
            confirmed_by_user_id=approving_user_id,
            confirmed_at=timestamp,
        ).with_audit_event(
            "confirmed",
            timestamp,
            {"approved_by_user_id": approving_user_id},
        )
        return self.repository.confirm(confirmed)

    def expire_due(
        self,
        workspace_id: str,
        now: datetime | None = None,
    ) -> list[ReconciliationProposal]:
        timestamp = now or datetime.now(UTC)
        expired: list[ReconciliationProposal] = []
        for proposal in self.repository.list_pending(workspace_id):
            if proposal.expires_at > timestamp:
                continue
            expired_proposal = replace(
                proposal,
                status=ProposalStatus.EXPIRED,
            ).with_audit_event("expired", timestamp)
            expired.append(self.repository.expire(expired_proposal))
        return expired

    def _require_proposal(
        self,
        workspace_id: str,
        proposal_id: str,
    ) -> ReconciliationProposal:
        proposal = self.repository.get_by_id(workspace_id, proposal_id)
        if proposal is None:
            raise ProposalNotFound("reconciliation proposal was not found")
        return proposal

    def _require_pending(self, proposal: ReconciliationProposal) -> None:
        if proposal.status != ProposalStatus.PENDING:
            raise InvalidProposalTransition(
                f"cannot transition {proposal.status.value} proposal"
            )
