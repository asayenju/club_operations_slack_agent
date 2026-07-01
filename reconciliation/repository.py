from __future__ import annotations

from typing import Protocol

from supabase import Client, create_client

from reconciliation.models import ProposalStatus, ReconciliationProposal


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

    def expire(self, proposal: ReconciliationProposal) -> ReconciliationProposal:
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
        return _first_proposal(response.data, proposal)

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
        return self._save(proposal)

    def expire(self, proposal: ReconciliationProposal) -> ReconciliationProposal:
        return self._save(proposal)

    def _save(self, proposal: ReconciliationProposal) -> ReconciliationProposal:
        row = proposal.to_row()
        response = (
            self.client.table("reconciliation_proposals")
            .update(row)
            .eq("workspace_id", proposal.workspace_id)
            .eq("id", proposal.id)
            .execute()
        )
        return _first_proposal(response.data, proposal)


def _first_proposal(
    rows: list[dict] | None,
    fallback: ReconciliationProposal,
) -> ReconciliationProposal:
    if not rows:
        return fallback
    return ReconciliationProposal.from_row(rows[0])
