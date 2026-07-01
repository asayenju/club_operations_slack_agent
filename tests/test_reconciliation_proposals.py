from datetime import UTC, datetime, timedelta

import pytest

from reconciliation.models import ProposalStatus, ReconciliationProposal
from reconciliation.service import (
    InvalidProposalTransition,
    ProposalNotFound,
    ReconciliationProposalService,
)


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
        self.proposals[(proposal.workspace_id, proposal.id)] = proposal
        return proposal

    def expire(self, proposal):
        self.proposals[(proposal.workspace_id, proposal.id)] = proposal
        return proposal


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
        proposal_id="proposal-1",
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
    assert repository.get_by_id("T123", "proposal-1") == proposal


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
        proposal_id="proposal-1",
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
        proposal_id="proposal-1",
    )

    confirmed = service.confirm(
        workspace_id="T123",
        proposal_id="proposal-1",
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
        proposal_id="proposal-1",
    )

    with pytest.raises(InvalidProposalTransition):
        service.confirm(
            workspace_id="T123",
            proposal_id="proposal-1",
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
        proposal_id="proposal-1",
    )
    service.confirm(
        workspace_id="T123",
        proposal_id="proposal-1",
        approving_user_id="UAPPROVER",
        confirmed_at=created_at + timedelta(minutes=1),
    )

    with pytest.raises(InvalidProposalTransition):
        service.confirm(
            workspace_id="T123",
            proposal_id="proposal-1",
            approving_user_id="UAPPROVER",
            confirmed_at=created_at + timedelta(minutes=2),
        )


def test_expire_due_marks_only_due_pending_proposals():
    service, repository = build_service()
    now = datetime(2026, 7, 1, 10, tzinfo=UTC)
    service.create_pending(
        workspace_id="T123",
        source_evidence=[],
        proposed_action={"kind": "due"},
        created_at=now - timedelta(hours=2),
        expires_at=now - timedelta(minutes=1),
        proposal_id="due",
    )
    service.create_pending(
        workspace_id="T123",
        source_evidence=[],
        proposed_action={"kind": "future"},
        created_at=now,
        expires_at=now + timedelta(hours=1),
        proposal_id="future",
    )
    service.create_pending(
        workspace_id="T999",
        source_evidence=[],
        proposed_action={"kind": "other_workspace"},
        created_at=now - timedelta(hours=2),
        expires_at=now - timedelta(minutes=1),
        proposal_id="other",
    )

    expired = service.expire_due("T123", now=now)

    assert [proposal.id for proposal in expired] == ["due"]
    assert repository.get_by_id("T123", "due").status == ProposalStatus.EXPIRED
    assert repository.get_by_id("T123", "future").status == ProposalStatus.PENDING
    assert repository.get_by_id("T999", "other").status == ProposalStatus.PENDING
    assert repository.get_by_id("T123", "due").audit_log[-1]["event"] == "expired"


def test_expire_due_is_idempotent():
    service, _ = build_service()
    now = datetime(2026, 7, 1, 10, tzinfo=UTC)
    service.create_pending(
        workspace_id="T123",
        source_evidence=[],
        proposed_action={"kind": "due"},
        created_at=now - timedelta(hours=2),
        expires_at=now - timedelta(minutes=1),
        proposal_id="due",
    )

    assert len(service.expire_due("T123", now=now)) == 1
    assert service.expire_due("T123", now=now) == []
