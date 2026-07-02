from __future__ import annotations

from datetime import datetime
from typing import Protocol

from supabase import Client, create_client

from reconciliation.models import (
    ProposalStatus,
    ReconciliationProposal,
    format_datetime,
)


class ProposalTransitionConflict(RuntimeError):
    pass


class ProposalStorageError(RuntimeError):
    pass


class ReconciliationProposalRepository(Protocol):
    def create_pending(
        self,
        proposal: ReconciliationProposal,
    ) -> ReconciliationProposal:
        ...

    def get_by_id(
        self,
        workspace_id: str,
        proposal_id: str,
    ) -> ReconciliationProposal | None:
        ...

    def find_by_slack_message(
        self,
        workspace_id: str,
        slack_channel_id: str,
        slack_message_ts: str,
    ) -> ReconciliationProposal | None:
        ...

    def list_pending(self, workspace_id: str) -> list[ReconciliationProposal]:
        ...

    def confirm(self, proposal: ReconciliationProposal) -> ReconciliationProposal:
        ...

    def expire(
        self,
        proposal: ReconciliationProposal,
        *,
        expired_at: datetime,
    ) -> ReconciliationProposal:
        ...

    def reject(self, proposal: ReconciliationProposal) -> ReconciliationProposal:
        ...

    def supersede(self, proposal: ReconciliationProposal) -> ReconciliationProposal:
        ...


class SupabaseReconciliationProposalRepository:
    def __init__(self, client: Client):
        self.client = client

    @classmethod
    def from_settings(
        cls,
        supabase_url: str,
        supabase_service_key: str,
    ) -> "SupabaseReconciliationProposalRepository":
        return cls(create_client(supabase_url, supabase_service_key))

    def create_pending(
        self,
        proposal: ReconciliationProposal,
    ) -> ReconciliationProposal:
        response = (
            self.client.table("reconciliation_proposals")
            .insert(proposal.to_row())
            .execute()
        )
        return _required_proposal(response.data)

    def get_by_id(
        self,
        workspace_id: str,
        proposal_id: str,
    ) -> ReconciliationProposal | None:
        response = (
            self.client.table("reconciliation_proposals")
            .select("*")
            .eq("workspace_id", workspace_id)
            .eq("id", proposal_id)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        return ReconciliationProposal.from_row(rows[0]) if rows else None

    def find_by_slack_message(
        self,
        workspace_id: str,
        slack_channel_id: str,
        slack_message_ts: str,
    ) -> ReconciliationProposal | None:
        response = (
            self.client.table("reconciliation_proposals")
            .select("*")
            .eq("workspace_id", workspace_id)
            .eq("slack_channel_id", slack_channel_id)
            .eq("slack_message_ts", slack_message_ts)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        return ReconciliationProposal.from_row(rows[0]) if rows else None

    def list_pending(self, workspace_id: str) -> list[ReconciliationProposal]:
        response = (
            self.client.table("reconciliation_proposals")
            .select("*")
            .eq("workspace_id", workspace_id)
            .eq("status", ProposalStatus.PENDING.value)
            .order("created_at")
            .execute()
        )
        return [
            ReconciliationProposal.from_row(row)
            for row in response.data or []
        ]

    def confirm(self, proposal: ReconciliationProposal) -> ReconciliationProposal:
        if proposal.confirmed_at is None:
            raise ProposalStorageError("confirmed proposals require confirmed_at")
        return self._save_pending_transition(
            proposal,
            expires_after=proposal.confirmed_at,
        )

    def expire(
        self,
        proposal: ReconciliationProposal,
        *,
        expired_at: datetime,
    ) -> ReconciliationProposal:
        return self._save_pending_transition(
            proposal,
            expires_at_or_before=expired_at,
        )

    def reject(self, proposal: ReconciliationProposal) -> ReconciliationProposal:
        return self._save_pending_transition(proposal)

    def supersede(self, proposal: ReconciliationProposal) -> ReconciliationProposal:
        return self._save_pending_transition(proposal)

    def _save_pending_transition(
        self,
        proposal: ReconciliationProposal,
        *,
        expires_after: datetime | None = None,
        expires_at_or_before: datetime | None = None,
    ) -> ReconciliationProposal:
        row = proposal.to_row()
        query = (
            self.client.table("reconciliation_proposals")
            .update(row)
            .eq("workspace_id", proposal.workspace_id)
            .eq("id", proposal.id)
            .eq("status", ProposalStatus.PENDING.value)
        )
        if expires_after is not None:
            query = query.gt("expires_at", format_datetime(expires_after))
        if expires_at_or_before is not None:
            query = query.lte("expires_at", format_datetime(expires_at_or_before))
        response = query.execute()
        return _required_transition_proposal(response.data)


def _required_proposal(rows: list[dict] | None) -> ReconciliationProposal:
    if not rows:
        raise ProposalStorageError("proposal write did not return a row")
    return ReconciliationProposal.from_row(rows[0])


def _required_transition_proposal(
    rows: list[dict] | None,
) -> ReconciliationProposal:
    if not rows:
        raise ProposalTransitionConflict(
            "proposal was no longer pending or actionable"
        )
    return ReconciliationProposal.from_row(rows[0])
