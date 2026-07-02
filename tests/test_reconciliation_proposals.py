from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from reconciliation.models import (
    ProposalStatus,
    ReconciliationProposal,
    format_datetime,
)
from reconciliation.repository import (
    ProposalTransitionConflict,
    SupabaseReconciliationProposalRepository,
)
from reconciliation.service import (
    InvalidProposalTransition,
    ProposalNotFound,
    ReconciliationProposalService,
)


PROPOSAL_ID = "00000000-0000-0000-0000-000000000001"
DUE_PROPOSAL_ID = "00000000-0000-0000-0000-000000000002"
FUTURE_PROPOSAL_ID = "00000000-0000-0000-0000-000000000003"
OTHER_PROPOSAL_ID = "00000000-0000-0000-0000-000000000004"
SUPERSEDING_PROPOSAL_ID = "00000000-0000-0000-0000-000000000005"


class RecordingSupabaseQuery:
    def __init__(self, *, return_rows=True):
        self.return_rows = return_rows
        self.filters = []
        self.updated_row = None

    def update(self, row):
        self.updated_row = row
        return self

    def eq(self, column, value):
        self.filters.append(("eq", column, value))
        return self

    def gt(self, column, value):
        self.filters.append(("gt", column, value))
        return self

    def lte(self, column, value):
        self.filters.append(("lte", column, value))
        return self

    def execute(self):
        rows = [self.updated_row] if self.return_rows else []
        return SimpleNamespace(data=rows)


class RecordingSupabaseClient:
    def __init__(self, *, return_rows=True):
        self.query = RecordingSupabaseQuery(return_rows=return_rows)
        self.table_name = None

    def table(self, table_name):
        self.table_name = table_name
        return self.query


class InMemoryProposalRepository:
    def __init__(self):
        self.proposals: dict[tuple[str, str], ReconciliationProposal] = {}

    def create_pending(self, proposal):
        self.proposals[(proposal.workspace_id, proposal.id)] = proposal
        return proposal

    def get_by_id(self, workspace_id, proposal_id):
        return self.proposals.get((workspace_id, proposal_id))

    def find_by_slack_message(
        self,
        workspace_id,
        slack_channel_id,
        slack_message_ts,
    ):
        return next(
            (
                proposal
                for proposal in self.proposals.values()
                if proposal.workspace_id == workspace_id
                and proposal.slack_channel_id == slack_channel_id
                and proposal.slack_message_ts == slack_message_ts
            ),
            None,
        )

    def list_pending(self, workspace_id):
        return [
            proposal
            for proposal in self.proposals.values()
            if proposal.workspace_id == workspace_id
            and proposal.status == ProposalStatus.PENDING
        ]

    def confirm(self, proposal):
        return self._save_pending_transition(
            proposal,
            expires_after=proposal.confirmed_at,
        )

    def expire(self, proposal, *, expired_at):
        return self._save_pending_transition(
            proposal,
            expires_at_or_before=expired_at,
        )

    def reject(self, proposal):
        return self._save_pending_transition(proposal)

    def supersede(self, proposal):
        return self._save_pending_transition(proposal)

    def _save_pending_transition(
        self,
        proposal,
        *,
        expires_after=None,
        expires_at_or_before=None,
    ):
        current = self.proposals.get((proposal.workspace_id, proposal.id))
        if current is None or current.status != ProposalStatus.PENDING:
            raise ProposalTransitionConflict(
                "proposal was no longer pending or actionable"
            )
        if expires_after is not None and current.expires_at <= expires_after:
            raise ProposalTransitionConflict(
                "proposal was no longer pending or actionable"
            )
        if (
            expires_at_or_before is not None
            and current.expires_at > expires_at_or_before
        ):
            raise ProposalTransitionConflict(
                "proposal was no longer pending or actionable"
            )
        self.proposals[(proposal.workspace_id, proposal.id)] = proposal
        return proposal


class ExpireBeforeConfirmRepository(InMemoryProposalRepository):
    def confirm(self, proposal):
        key = (proposal.workspace_id, proposal.id)
        current = self.proposals[key]
        self.proposals[key] = replace(current, status=ProposalStatus.EXPIRED)
        return super().confirm(proposal)


class RejectBeforeExpireRepository(InMemoryProposalRepository):
    def expire(self, proposal, *, expired_at):
        key = (proposal.workspace_id, proposal.id)
        current = self.proposals[key]
        self.proposals[key] = replace(current, status=ProposalStatus.REJECTED)
        return super().expire(proposal, expired_at=expired_at)


def build_service():
    repository = InMemoryProposalRepository()
    return ReconciliationProposalService(repository), repository


def test_proposal_round_trips_to_storage_row():
    created_at = datetime(2026, 7, 1, 10, tzinfo=UTC)
    proposal = ReconciliationProposal(
        id="00000000-0000-0000-0000-000000000001",
        workspace_id="T123",
        status=ProposalStatus.PENDING,
        source_evidence=[{"source": "gdoc", "label": "Handover"}],
        proposed_action={"kind": "notify"},
        slack_channel_id="C123",
        slack_message_ts="1710000000.000100",
        created_at=created_at,
        expires_at=created_at + timedelta(hours=1),
    ).with_audit_event("created", created_at)

    restored = ReconciliationProposal.from_row(proposal.to_row())

    assert restored == proposal


def test_supabase_confirm_update_requires_pending_unexpired_row():
    created_at = datetime(2026, 7, 1, 10, tzinfo=UTC)
    confirmed_at = created_at + timedelta(minutes=10)
    proposal = ReconciliationProposal(
        id=PROPOSAL_ID,
        workspace_id="T123",
        status=ProposalStatus.CONFIRMED,
        source_evidence=[],
        proposed_action={"kind": "notify"},
        slack_channel_id="C123",
        slack_message_ts="1710000000.000100",
        created_at=created_at,
        expires_at=created_at + timedelta(hours=1),
        confirmed_by_user_id="UAPPROVER",
        confirmed_at=confirmed_at,
    )
    client = RecordingSupabaseClient()
    repository = SupabaseReconciliationProposalRepository(client)

    repository.confirm(proposal)

    assert client.table_name == "reconciliation_proposals"
    assert ("eq", "workspace_id", "T123") in client.query.filters
    assert ("eq", "id", PROPOSAL_ID) in client.query.filters
    assert ("eq", "status", ProposalStatus.PENDING.value) in client.query.filters
    assert ("gt", "expires_at", format_datetime(confirmed_at)) in client.query.filters


def test_supabase_expire_update_requires_pending_due_row():
    created_at = datetime(2026, 7, 1, 10, tzinfo=UTC)
    expired_at = created_at + timedelta(hours=2)
    proposal = ReconciliationProposal(
        id=PROPOSAL_ID,
        workspace_id="T123",
        status=ProposalStatus.EXPIRED,
        source_evidence=[],
        proposed_action={"kind": "notify"},
        slack_channel_id="C123",
        slack_message_ts="1710000000.000100",
        created_at=created_at,
        expires_at=created_at + timedelta(hours=1),
    )
    client = RecordingSupabaseClient()
    repository = SupabaseReconciliationProposalRepository(client)

    repository.expire(proposal, expired_at=expired_at)

    assert ("eq", "status", ProposalStatus.PENDING.value) in client.query.filters
    assert ("lte", "expires_at", format_datetime(expired_at)) in client.query.filters


def test_supabase_transition_raises_when_guard_matches_no_rows():
    created_at = datetime(2026, 7, 1, 10, tzinfo=UTC)
    proposal = ReconciliationProposal(
        id=PROPOSAL_ID,
        workspace_id="T123",
        status=ProposalStatus.REJECTED,
        source_evidence=[],
        proposed_action={"kind": "notify"},
        slack_channel_id="C123",
        slack_message_ts="1710000000.000100",
        created_at=created_at,
        expires_at=created_at + timedelta(hours=1),
    )
    client = RecordingSupabaseClient(return_rows=False)
    repository = SupabaseReconciliationProposalRepository(client)

    with pytest.raises(ProposalTransitionConflict):
        repository.reject(proposal)


def test_create_pending_proposal_records_required_fields():
    service, repository = build_service()
    created_at = datetime(2026, 7, 1, 10, tzinfo=UTC)
    expires_at = created_at + timedelta(hours=72)

    proposal = service.create_pending(
        workspace_id="T123",
        source_evidence=[{"source": "slack_decide", "text": "Budget approved"}],
        proposed_action={"kind": "update_budget", "amount": 300},
        slack_channel_id="C123",
        slack_message_ts="1710000000.000100",
        created_at=created_at,
        expires_at=expires_at,
        proposal_id=PROPOSAL_ID,
    )

    assert proposal.status == ProposalStatus.PENDING
    assert proposal.workspace_id == "T123"
    assert proposal.source_evidence[0]["source"] == "slack_decide"
    assert proposal.proposed_action["kind"] == "update_budget"
    assert proposal.slack_channel_id == "C123"
    assert proposal.slack_message_ts == "1710000000.000100"
    assert proposal.created_at == created_at
    assert proposal.expires_at == expires_at
    assert proposal.audit_log[0]["event"] == "created"
    assert repository.get_by_id("T123", PROPOSAL_ID) == proposal


def test_create_pending_proposal_rejects_non_uuid_id():
    service, _ = build_service()
    created_at = datetime(2026, 7, 1, 10, tzinfo=UTC)

    with pytest.raises(ValueError, match="proposal_id must be a valid UUID"):
        service.create_pending(
            workspace_id="T123",
            source_evidence=[],
            proposed_action={"kind": "notify"},
            created_at=created_at,
            expires_at=created_at + timedelta(hours=1),
            proposal_id="proposal-1",
        )


def test_find_by_slack_message_returns_matching_proposal():
    service, _ = build_service()
    created_at = datetime(2026, 7, 1, 10, tzinfo=UTC)
    proposal = service.create_pending(
        workspace_id="T123",
        source_evidence=[],
        proposed_action={"kind": "notify"},
        slack_channel_id="C123",
        slack_message_ts="1710000000.000100",
        created_at=created_at,
        expires_at=created_at + timedelta(hours=1),
        proposal_id=PROPOSAL_ID,
    )

    assert service.find_by_slack_message(
        "T123",
        "C123",
        "1710000000.000100",
    ) == proposal
    assert service.find_by_slack_message("T123", "C999", "missing") is None


def test_confirm_pending_proposal_records_approval_metadata():
    service, _ = build_service()
    created_at = datetime(2026, 7, 1, 10, tzinfo=UTC)
    confirmed_at = created_at + timedelta(minutes=10)
    service.create_pending(
        workspace_id="T123",
        source_evidence=[],
        proposed_action={"kind": "notify"},
        created_at=created_at,
        expires_at=created_at + timedelta(hours=1),
        proposal_id=PROPOSAL_ID,
    )

    confirmed = service.confirm(
        workspace_id="T123",
        proposal_id=PROPOSAL_ID,
        approving_user_id="UAPPROVER",
        confirmed_at=confirmed_at,
    )

    assert confirmed.status == ProposalStatus.CONFIRMED
    assert confirmed.confirmed_by_user_id == "UAPPROVER"
    assert confirmed.confirmed_at == confirmed_at
    assert confirmed.audit_log[-1]["event"] == "confirmed"
    assert confirmed.audit_log[-1]["approved_by_user_id"] == "UAPPROVER"


def test_confirm_missing_proposal_raises_not_found():
    service, _ = build_service()

    with pytest.raises(ProposalNotFound):
        service.confirm(
            workspace_id="T123",
            proposal_id="missing",
            approving_user_id="UAPPROVER",
        )


def test_confirm_expired_proposal_is_rejected():
    service, _ = build_service()
    created_at = datetime(2026, 7, 1, 10, tzinfo=UTC)
    service.create_pending(
        workspace_id="T123",
        source_evidence=[],
        proposed_action={"kind": "notify"},
        created_at=created_at,
        expires_at=created_at + timedelta(minutes=5),
        proposal_id=PROPOSAL_ID,
    )

    with pytest.raises(InvalidProposalTransition):
        service.confirm(
            workspace_id="T123",
            proposal_id=PROPOSAL_ID,
            approving_user_id="UAPPROVER",
            confirmed_at=created_at + timedelta(minutes=6),
        )


def test_confirm_already_confirmed_proposal_is_rejected():
    service, _ = build_service()
    created_at = datetime(2026, 7, 1, 10, tzinfo=UTC)
    service.create_pending(
        workspace_id="T123",
        source_evidence=[],
        proposed_action={"kind": "notify"},
        created_at=created_at,
        expires_at=created_at + timedelta(hours=1),
        proposal_id=PROPOSAL_ID,
    )
    service.confirm(
        workspace_id="T123",
        proposal_id=PROPOSAL_ID,
        approving_user_id="UAPPROVER",
        confirmed_at=created_at + timedelta(minutes=1),
    )

    with pytest.raises(InvalidProposalTransition):
        service.confirm(
            workspace_id="T123",
            proposal_id=PROPOSAL_ID,
            approving_user_id="UAPPROVER",
            confirmed_at=created_at + timedelta(minutes=2),
        )


def test_reject_pending_proposal_records_audit_metadata():
    service, _ = build_service()
    created_at = datetime(2026, 7, 1, 10, tzinfo=UTC)
    rejected_at = created_at + timedelta(minutes=15)
    service.create_pending(
        workspace_id="T123",
        source_evidence=[],
        proposed_action={"kind": "notify"},
        created_at=created_at,
        expires_at=created_at + timedelta(hours=1),
        proposal_id=PROPOSAL_ID,
    )

    rejected = service.reject(
        workspace_id="T123",
        proposal_id=PROPOSAL_ID,
        rejecting_user_id="UREJECTOR",
        rejected_at=rejected_at,
    )

    assert rejected.status == ProposalStatus.REJECTED
    assert rejected.audit_log[-1]["event"] == "rejected"
    assert rejected.audit_log[-1]["rejected_by_user_id"] == "UREJECTOR"


def test_supersede_pending_proposal_records_audit_metadata():
    service, _ = build_service()
    created_at = datetime(2026, 7, 1, 10, tzinfo=UTC)
    superseded_at = created_at + timedelta(minutes=15)
    service.create_pending(
        workspace_id="T123",
        source_evidence=[],
        proposed_action={"kind": "notify"},
        created_at=created_at,
        expires_at=created_at + timedelta(hours=1),
        proposal_id=PROPOSAL_ID,
    )

    superseded = service.supersede(
        workspace_id="T123",
        proposal_id=PROPOSAL_ID,
        superseded_by_proposal_id=SUPERSEDING_PROPOSAL_ID,
        superseded_at=superseded_at,
    )

    assert superseded.status == ProposalStatus.SUPERSEDED
    assert superseded.audit_log[-1]["event"] == "superseded"
    assert (
        superseded.audit_log[-1]["superseded_by_proposal_id"]
        == SUPERSEDING_PROPOSAL_ID
    )


def test_confirm_rejected_proposal_is_rejected():
    service, _ = build_service()
    created_at = datetime(2026, 7, 1, 10, tzinfo=UTC)
    service.create_pending(
        workspace_id="T123",
        source_evidence=[],
        proposed_action={"kind": "notify"},
        created_at=created_at,
        expires_at=created_at + timedelta(hours=1),
        proposal_id=PROPOSAL_ID,
    )
    service.reject(
        workspace_id="T123",
        proposal_id=PROPOSAL_ID,
        rejected_at=created_at + timedelta(minutes=1),
    )

    with pytest.raises(InvalidProposalTransition):
        service.confirm(
            workspace_id="T123",
            proposal_id=PROPOSAL_ID,
            approving_user_id="UAPPROVER",
            confirmed_at=created_at + timedelta(minutes=2),
        )


def test_reject_expired_proposal_is_rejected():
    service, _ = build_service()
    created_at = datetime(2026, 7, 1, 10, tzinfo=UTC)
    service.create_pending(
        workspace_id="T123",
        source_evidence=[],
        proposed_action={"kind": "notify"},
        created_at=created_at,
        expires_at=created_at + timedelta(minutes=5),
        proposal_id=PROPOSAL_ID,
    )

    with pytest.raises(InvalidProposalTransition):
        service.reject(
            workspace_id="T123",
            proposal_id=PROPOSAL_ID,
            rejected_at=created_at + timedelta(minutes=6),
        )


def test_confirm_loses_storage_race_when_proposal_expires_after_read():
    repository = ExpireBeforeConfirmRepository()
    service = ReconciliationProposalService(repository)
    created_at = datetime(2026, 7, 1, 10, tzinfo=UTC)
    service.create_pending(
        workspace_id="T123",
        source_evidence=[],
        proposed_action={"kind": "notify"},
        created_at=created_at,
        expires_at=created_at + timedelta(hours=1),
        proposal_id=PROPOSAL_ID,
    )

    with pytest.raises(InvalidProposalTransition):
        service.confirm(
            workspace_id="T123",
            proposal_id=PROPOSAL_ID,
            approving_user_id="UAPPROVER",
            confirmed_at=created_at + timedelta(minutes=1),
        )

    assert repository.get_by_id("T123", PROPOSAL_ID).status == ProposalStatus.EXPIRED


def test_expire_due_marks_only_due_pending_proposals():
    service, repository = build_service()
    now = datetime(2026, 7, 1, 10, tzinfo=UTC)
    service.create_pending(
        workspace_id="T123",
        source_evidence=[],
        proposed_action={"kind": "due"},
        created_at=now - timedelta(hours=2),
        expires_at=now - timedelta(minutes=1),
        proposal_id=DUE_PROPOSAL_ID,
    )
    service.create_pending(
        workspace_id="T123",
        source_evidence=[],
        proposed_action={"kind": "future"},
        created_at=now,
        expires_at=now + timedelta(hours=1),
        proposal_id=FUTURE_PROPOSAL_ID,
    )
    service.create_pending(
        workspace_id="T999",
        source_evidence=[],
        proposed_action={"kind": "other_workspace"},
        created_at=now - timedelta(hours=2),
        expires_at=now - timedelta(minutes=1),
        proposal_id=OTHER_PROPOSAL_ID,
    )

    expired = service.expire_due("T123", now=now)

    assert [proposal.id for proposal in expired] == [DUE_PROPOSAL_ID]
    assert (
        repository.get_by_id("T123", DUE_PROPOSAL_ID).status
        == ProposalStatus.EXPIRED
    )
    assert (
        repository.get_by_id("T123", FUTURE_PROPOSAL_ID).status
        == ProposalStatus.PENDING
    )
    assert (
        repository.get_by_id("T999", OTHER_PROPOSAL_ID).status
        == ProposalStatus.PENDING
    )
    assert (
        repository.get_by_id("T123", DUE_PROPOSAL_ID).audit_log[-1]["event"]
        == "expired"
    )


def test_expire_due_is_idempotent():
    service, _ = build_service()
    now = datetime(2026, 7, 1, 10, tzinfo=UTC)
    service.create_pending(
        workspace_id="T123",
        source_evidence=[],
        proposed_action={"kind": "due"},
        created_at=now - timedelta(hours=2),
        expires_at=now - timedelta(minutes=1),
        proposal_id=DUE_PROPOSAL_ID,
    )

    assert len(service.expire_due("T123", now=now)) == 1
    assert service.expire_due("T123", now=now) == []


def test_expire_due_skips_storage_race_when_proposal_rejects_after_list():
    repository = RejectBeforeExpireRepository()
    service = ReconciliationProposalService(repository)
    now = datetime(2026, 7, 1, 10, tzinfo=UTC)
    service.create_pending(
        workspace_id="T123",
        source_evidence=[],
        proposed_action={"kind": "due"},
        created_at=now - timedelta(hours=2),
        expires_at=now - timedelta(minutes=1),
        proposal_id=DUE_PROPOSAL_ID,
    )

    assert service.expire_due("T123", now=now) == []
    assert (
        repository.get_by_id("T123", DUE_PROPOSAL_ID).status
        == ProposalStatus.REJECTED
    )
