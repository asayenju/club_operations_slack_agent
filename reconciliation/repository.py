from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Callable, Protocol

from supabase import Client, create_client

from reconciliation.models import (
    ProposalStatus,
    ReconciliationProposal,
    format_datetime,
    parse_datetime,
)

PAGE_SIZE = 1000


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

    def list_due(
        self,
        workspace_id: str,
        due_at: datetime,
    ) -> list[ReconciliationProposal]:
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
        row = proposal.to_row()
        row["updated_at"] = format_datetime(proposal.created_at)
        response = (
            self.client.table("reconciliation_proposals")
            .insert(row)
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
        rows = self._fetch_paginated(
            lambda: (
                self.client.table("reconciliation_proposals")
                .select("*")
                .eq("workspace_id", workspace_id)
                .eq("status", ProposalStatus.PENDING.value)
                .order("expires_at")
                .order("id")
            )
        )
        return [
            ReconciliationProposal.from_row(row)
            for row in rows
        ]

    def list_due(
        self,
        workspace_id: str,
        due_at: datetime,
    ) -> list[ReconciliationProposal]:
        rows = self._fetch_paginated(
            lambda: (
                self.client.table("reconciliation_proposals")
                .select("*")
                .eq("workspace_id", workspace_id)
                .eq("status", ProposalStatus.PENDING.value)
                .lte("expires_at", format_datetime(due_at))
                .order("expires_at")
                .order("id")
            )
        )
        return [
            ReconciliationProposal.from_row(row)
            for row in rows
        ]

    def confirm(self, proposal: ReconciliationProposal) -> ReconciliationProposal:
        if proposal.confirmed_at is None:
            raise ProposalStorageError("confirmed proposals require confirmed_at")
        return self._save_pending_transition(
            proposal,
            expires_after=proposal.confirmed_at,
            updated_at=proposal.confirmed_at,
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
            updated_at=expired_at,
        )

    def reject(self, proposal: ReconciliationProposal) -> ReconciliationProposal:
        return self._save_pending_transition(
            proposal,
            updated_at=_last_audit_timestamp(proposal),
        )

    def supersede(self, proposal: ReconciliationProposal) -> ReconciliationProposal:
        return self._save_pending_transition(
            proposal,
            updated_at=_last_audit_timestamp(proposal),
        )

    def _save_pending_transition(
        self,
        proposal: ReconciliationProposal,
        *,
        expires_after: datetime | None = None,
        expires_at_or_before: datetime | None = None,
        updated_at: datetime,
    ) -> ReconciliationProposal:
        row = proposal.to_update_row()
        row["updated_at"] = format_datetime(updated_at)
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

    def _fetch_paginated(
        self,
        build_query: Callable[[], Any],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        start = 0
        while True:
            page = (
                build_query()
                .range(start, start + PAGE_SIZE - 1)
                .execute()
                .data
                or []
            )
            rows.extend(page)
            if len(page) < PAGE_SIZE:
                return rows
            start += PAGE_SIZE


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


def _last_audit_timestamp(proposal: ReconciliationProposal) -> datetime:
    if proposal.audit_log:
        occurred_at = proposal.audit_log[-1].get("occurred_at")
        if occurred_at:
            return parse_datetime(str(occurred_at))
    return datetime.now(UTC)
