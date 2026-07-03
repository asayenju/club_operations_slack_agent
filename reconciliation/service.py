from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from reconciliation.models import ProposalStatus, ReconciliationProposal
from reconciliation.repository import (
    ProposalTransitionConflict,
    ReconciliationProposalRepository,
)


class ProposalNotFound(RuntimeError):
    pass


class InvalidProposalTransition(RuntimeError):
    pass


DEFAULT_PROPOSAL_EXPIRY = timedelta(hours=72)


class ReconciliationProposalService:
    def __init__(self, repository: ReconciliationProposalRepository):
        self.repository = repository

    def create_pending(
        self,
        *,
        workspace_id: str,
        source_evidence: list[dict[str, Any]],
        proposed_action: dict[str, Any],
        expires_at: datetime | None = None,
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
        expiry = expires_at or timestamp + DEFAULT_PROPOSAL_EXPIRY
        proposal = ReconciliationProposal(
            id=_proposal_id(proposal_id),
            workspace_id=workspace_id,
            status=ProposalStatus.PENDING,
            source_evidence=source_evidence,
            proposed_action=proposed_action,
            slack_channel_id=slack_channel_id,
            slack_message_ts=slack_message_ts,
            created_at=timestamp,
            expires_at=expiry,
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
        try:
            return self.repository.confirm(confirmed)
        except ProposalTransitionConflict as exc:
            raise InvalidProposalTransition(
                "proposal is no longer pending or actionable"
            ) from exc

    def reject(
        self,
        *,
        workspace_id: str,
        proposal_id: str,
        rejecting_user_id: str | None = None,
        rejected_at: datetime | None = None,
    ) -> ReconciliationProposal:
        proposal = self._require_proposal(workspace_id, proposal_id)
        timestamp = rejected_at or datetime.now(UTC)
        self._require_actionable_pending(proposal, timestamp)

        metadata = (
            {"rejected_by_user_id": rejecting_user_id}
            if rejecting_user_id
            else None
        )
        rejected = replace(
            proposal,
            status=ProposalStatus.REJECTED,
        ).with_audit_event("rejected", timestamp, metadata)
        try:
            return self.repository.reject(rejected)
        except ProposalTransitionConflict as exc:
            raise InvalidProposalTransition(
                "proposal is no longer pending or actionable"
            ) from exc

    def supersede(
        self,
        *,
        workspace_id: str,
        proposal_id: str,
        superseded_by_proposal_id: str | None = None,
        superseded_at: datetime | None = None,
    ) -> ReconciliationProposal:
        proposal = self._require_proposal(workspace_id, proposal_id)
        timestamp = superseded_at or datetime.now(UTC)
        self._require_actionable_pending(proposal, timestamp)

        metadata = (
            {"superseded_by_proposal_id": _proposal_id(superseded_by_proposal_id)}
            if superseded_by_proposal_id
            else None
        )
        superseded = replace(
            proposal,
            status=ProposalStatus.SUPERSEDED,
        ).with_audit_event("superseded", timestamp, metadata)
        try:
            return self.repository.supersede(superseded)
        except ProposalTransitionConflict as exc:
            raise InvalidProposalTransition(
                "proposal is no longer pending or actionable"
            ) from exc

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
            try:
                expired.append(
                    self.repository.expire(
                        expired_proposal,
                        expired_at=timestamp,
                    )
                )
            except ProposalTransitionConflict:
                continue
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

    def _require_actionable_pending(
        self,
        proposal: ReconciliationProposal,
        timestamp: datetime,
    ) -> None:
        self._require_pending(proposal)
        if proposal.expires_at <= timestamp:
            raise InvalidProposalTransition("expired proposals cannot be changed")


def _proposal_id(proposal_id: str | None) -> str:
    if proposal_id is None:
        return str(uuid4())
    try:
        return str(UUID(proposal_id))
    except ValueError as exc:
        raise ValueError("proposal_id must be a valid UUID") from exc
