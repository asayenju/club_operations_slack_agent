from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from reconciliation.models import (
    ProposalStatus,
    ReconciliationProposal,
    format_datetime,
)
from reconciliation.approval import (
    ReconciliationApprovalNotConfigured,
    ReconciliationApprovalPolicy,
    ReconciliationApprovalRejected,
    validate_reconciliation_approval,
)
from reconciliation.repository import (
    PAGE_SIZE,
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
UNKNOWN_PROPOSAL_ID = "00000000-0000-0000-0000-000000000099"


class RecordingSupabaseQuery:
    def __init__(self, *, return_rows=True, rows=None):
        self.return_rows = return_rows
        self.rows = rows or []
        self.filters = []
        self.inserted_row = None
        self.updated_row = None
        self.order_columns = []
        self.range_start = None
        self.range_end = None

    def insert(self, row):
        self.inserted_row = row
        return self

    def select(self, _columns):
        return self

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

    def order(self, column):
        self.order_columns.append(column)
        return self

    def range(self, start, end):
        self.range_start = start
        self.range_end = end
        return self

    def execute(self):
        if not self.return_rows:
            rows = []
        elif self.updated_row is not None:
            eq_filters = {
                column: value
                for operator, column, value in self.filters
                if operator == "eq"
            }
            rows = [
                {
                    "id": eq_filters.get("id", PROPOSAL_ID),
                    "workspace_id": eq_filters.get("workspace_id", "T123"),
                    "created_at": self.updated_row.get(
                        "created_at",
                        self.updated_row["expires_at"],
                    ),
                    **self.updated_row,
                }
            ]
        elif self.inserted_row is not None:
            rows = [self.inserted_row]
        else:
            rows = self.rows
            if self.range_start is not None and self.range_end is not None:
                rows = rows[self.range_start : self.range_end + 1]
        return SimpleNamespace(data=rows)


class RecordingSupabaseClient:
    def __init__(self, *, return_rows=True, rows=None):
        self.return_rows = return_rows
        self.rows = rows
        self.queries = []
        self.table_name = None

    @property
    def query(self):
        return self.queries[-1]

    def table(self, table_name):
        self.table_name = table_name
        query = RecordingSupabaseQuery(
            return_rows=self.return_rows,
            rows=self.rows,
        )
        self.queries.append(query)
        return query


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

    def list_due(self, workspace_id, due_at):
        return [
            proposal
            for proposal in self.list_pending(workspace_id)
            if proposal.expires_at <= due_at
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


def build_policy(*, users="UAPPROVER", reaction="white_check_mark"):
    return ReconciliationApprovalPolicy(
        lead_user_ids=frozenset(users.split(",") if users else []),
        approval_reaction=reaction,
    )


def build_proposal(
    *,
    status=ProposalStatus.PENDING,
    expires_at=None,
    confirmed_at=None,
    confirmed_by_user_id=None,
):
    created_at = datetime(2026, 7, 1, 10, tzinfo=UTC)
    return ReconciliationProposal(
        id=PROPOSAL_ID,
        workspace_id="T123",
        status=status,
        source_evidence=[],
        proposed_action={"kind": "notify"},
        slack_channel_id="C123",
        slack_message_ts="1710000000.000100",
        created_at=created_at,
        expires_at=expires_at or created_at + timedelta(hours=1),
        confirmed_at=confirmed_at,
        confirmed_by_user_id=confirmed_by_user_id,
    )


def test_approval_policy_reads_configured_users_and_reaction():
    settings = SimpleNamespace(
        reconciliation_approval_user_ids=" UAPPROVER, UBACKUP ,, ",
        reconciliation_approval_reaction=":heavy_check_mark:",
    )

    policy = ReconciliationApprovalPolicy.from_settings(settings)

    assert policy.lead_user_ids == frozenset({"UAPPROVER", "UBACKUP"})
    assert policy.approval_reaction == "heavy_check_mark"
    assert policy.allow_any_user is False


def test_approval_policy_defaults_to_checkmark_reaction():
    settings = SimpleNamespace(reconciliation_approval_user_ids="UAPPROVER")

    policy = ReconciliationApprovalPolicy.from_settings(settings)

    assert policy.approval_reaction == "white_check_mark"


def test_approval_policy_allows_any_user_only_in_unconfigured_development():
    settings = SimpleNamespace(
        app_env="development",
        reconciliation_approval_user_ids=None,
    )

    policy = ReconciliationApprovalPolicy.from_settings(settings)

    assert policy.lead_user_ids == frozenset()
    assert policy.allow_any_user is True


def test_approval_policy_stays_closed_when_unconfigured_in_production():
    settings = SimpleNamespace(
        app_env="production",
        reconciliation_approval_user_ids=None,
    )

    policy = ReconciliationApprovalPolicy.from_settings(settings)

    assert policy.lead_user_ids == frozenset()
    assert policy.allow_any_user is False


def test_approval_validation_accepts_authorized_user_and_reaction():
    validate_reconciliation_approval(
        policy=build_policy(),
        approving_user_id="UAPPROVER",
        reaction=":white_check_mark:",
    )


def test_approval_validation_accepts_skin_tone_variant_of_configured_reaction():
    validate_reconciliation_approval(
        policy=build_policy(reaction="+1"),
        approving_user_id="UAPPROVER",
        reaction="+1::skin-tone-2",
    )


def test_approval_validation_accepts_any_user_when_development_policy_allows_it():
    validate_reconciliation_approval(
        policy=ReconciliationApprovalPolicy(
            lead_user_ids=frozenset(),
            approval_reaction="white_check_mark",
            allow_any_user=True,
        ),
        approving_user_id="ULOCAL",
        reaction="white_check_mark",
    )


def test_approval_validation_rejects_missing_user_config():
    with pytest.raises(ReconciliationApprovalNotConfigured):
        validate_reconciliation_approval(
            policy=build_policy(users=""),
            approving_user_id="UAPPROVER",
            reaction="white_check_mark",
        )


def test_approval_validation_rejects_unconfigured_user():
    with pytest.raises(ReconciliationApprovalRejected):
        validate_reconciliation_approval(
            policy=build_policy(),
            approving_user_id="UOTHER",
            reaction="white_check_mark",
        )


def test_approval_validation_rejects_wrong_reaction():
    with pytest.raises(ReconciliationApprovalRejected):
        validate_reconciliation_approval(
            policy=build_policy(),
            approving_user_id="UAPPROVER",
            reaction="eyes",
        )


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


def test_proposal_update_row_omits_immutable_columns():
    created_at = datetime(2026, 7, 1, 10, tzinfo=UTC)
    proposal = ReconciliationProposal(
        id="00000000-0000-0000-0000-000000000001",
        workspace_id="T123",
        status=ProposalStatus.REJECTED,
        source_evidence=[],
        proposed_action={"kind": "notify"},
        slack_channel_id=None,
        slack_message_ts=None,
        created_at=created_at,
        expires_at=created_at + timedelta(hours=1),
    )

    row = proposal.to_update_row()

    assert "id" not in row
    assert "workspace_id" not in row
    assert "created_at" not in row
    assert row["status"] == ProposalStatus.REJECTED.value


def test_format_datetime_treats_naive_datetimes_as_utc():
    assert format_datetime(datetime(2026, 7, 1, 10)) == "2026-07-01T10:00:00+00:00"


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
    assert client.query.updated_row["updated_at"] == format_datetime(confirmed_at)
    assert "created_at" not in client.query.updated_row


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
    assert client.query.updated_row["updated_at"] == format_datetime(expired_at)
    assert "created_at" not in client.query.updated_row


def test_supabase_create_pending_sets_updated_at_from_created_at():
    created_at = datetime(2026, 7, 1, 10, tzinfo=UTC)
    proposal = ReconciliationProposal(
        id=PROPOSAL_ID,
        workspace_id="T123",
        status=ProposalStatus.PENDING,
        source_evidence=[],
        proposed_action={"kind": "notify"},
        slack_channel_id="C123",
        slack_message_ts="1710000000.000100",
        created_at=created_at,
        expires_at=created_at + timedelta(hours=1),
    )
    client = RecordingSupabaseClient()
    repository = SupabaseReconciliationProposalRepository(client)

    repository.create_pending(proposal)

    assert client.query.inserted_row["updated_at"] == format_datetime(created_at)


def test_supabase_list_pending_orders_by_expiry_for_due_scan():
    created_at = datetime(2026, 7, 1, 10, tzinfo=UTC)
    client = RecordingSupabaseClient(
        rows=[
            ReconciliationProposal(
                id=PROPOSAL_ID,
                workspace_id="T123",
                status=ProposalStatus.PENDING,
                source_evidence=[],
                proposed_action={"kind": "notify"},
                slack_channel_id=None,
                slack_message_ts=None,
                created_at=created_at,
                expires_at=created_at + timedelta(hours=1),
            ).to_row()
        ]
    )
    repository = SupabaseReconciliationProposalRepository(client)

    repository.list_pending("T123")

    assert client.query.order_columns == ["expires_at", "id"]
    assert client.query.range_start == 0
    assert client.query.range_end == PAGE_SIZE - 1


def test_supabase_list_pending_paginates_all_rows():
    created_at = datetime(2026, 7, 1, 10, tzinfo=UTC)
    rows = [
        ReconciliationProposal(
            id=f"00000000-0000-0000-0000-{index + 1:012d}",
            workspace_id="T123",
            status=ProposalStatus.PENDING,
            source_evidence=[],
            proposed_action={"kind": "notify"},
            slack_channel_id=None,
            slack_message_ts=None,
            created_at=created_at,
            expires_at=created_at + timedelta(minutes=index + 1),
        ).to_row()
        for index in range(PAGE_SIZE + 1)
    ]
    client = RecordingSupabaseClient(rows=rows)
    repository = SupabaseReconciliationProposalRepository(client)

    proposals = repository.list_pending("T123")

    assert len(proposals) == PAGE_SIZE + 1
    assert len(client.queries) == 2
    assert (client.queries[0].range_start, client.queries[0].range_end) == (
        0,
        PAGE_SIZE - 1,
    )
    assert (client.queries[1].range_start, client.queries[1].range_end) == (
        PAGE_SIZE,
        (PAGE_SIZE * 2) - 1,
    )


def test_supabase_list_due_filters_by_expiry_before_pagination():
    now = datetime(2026, 7, 1, 10, tzinfo=UTC)
    client = RecordingSupabaseClient(rows=[])
    repository = SupabaseReconciliationProposalRepository(client)

    repository.list_due("T123", now)

    assert ("eq", "workspace_id", "T123") in client.query.filters
    assert ("eq", "status", ProposalStatus.PENDING.value) in client.query.filters
    assert ("lte", "expires_at", format_datetime(now)) in client.query.filters
    assert client.query.order_columns == ["expires_at", "id"]
    assert client.query.range_start == 0
    assert client.query.range_end == PAGE_SIZE - 1


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


def test_create_pending_proposal_normalizes_naive_datetimes_to_utc():
    service, _ = build_service()
    created_at = datetime(2026, 7, 1, 10)
    expires_at = datetime(2026, 7, 4, 10)

    proposal = service.create_pending(
        workspace_id="T123",
        source_evidence=[],
        proposed_action={"kind": "notify"},
        created_at=created_at,
        expires_at=expires_at,
        proposal_id=PROPOSAL_ID,
    )

    assert proposal.created_at == datetime(2026, 7, 1, 10, tzinfo=UTC)
    assert proposal.expires_at == datetime(2026, 7, 4, 10, tzinfo=UTC)


def test_create_pending_proposal_defaults_expiry_to_72_hours():
    service, _ = build_service()
    created_at = datetime(2026, 7, 1, 10, tzinfo=UTC)

    proposal = service.create_pending(
        workspace_id="T123",
        source_evidence=[],
        proposed_action={"kind": "notify"},
        created_at=created_at,
        proposal_id=PROPOSAL_ID,
    )

    assert proposal.expires_at == created_at + timedelta(hours=72)


def test_create_pending_proposal_defaults_expiry_after_normalized_creation_time():
    service, _ = build_service()
    created_at = datetime(2026, 7, 1, 10)

    proposal = service.create_pending(
        workspace_id="T123",
        source_evidence=[],
        proposed_action={"kind": "notify"},
        created_at=created_at,
        proposal_id=PROPOSAL_ID,
    )

    assert proposal.created_at == datetime(2026, 7, 1, 10, tzinfo=UTC)
    assert proposal.expires_at == datetime(2026, 7, 4, 10, tzinfo=UTC)


def test_create_pending_proposal_rejects_past_expiry():
    service, _ = build_service()
    created_at = datetime(2026, 7, 1, 10, tzinfo=UTC)

    with pytest.raises(ValueError, match="expires_at must be in the future"):
        service.create_pending(
            workspace_id="T123",
            source_evidence=[],
            proposed_action={"kind": "notify"},
            created_at=created_at,
            expires_at=created_at,
            proposal_id=PROPOSAL_ID,
        )


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


def test_create_pending_rejects_incomplete_slack_message_reference():
    service, _ = build_service()
    created_at = datetime(2026, 7, 1, 10, tzinfo=UTC)

    with pytest.raises(
        ValueError,
        match="slack_channel_id and slack_message_ts must be provided together",
    ):
        service.create_pending(
            workspace_id="T123",
            source_evidence=[],
            proposed_action={"kind": "notify"},
            slack_channel_id="C123",
            created_at=created_at,
            expires_at=created_at + timedelta(hours=1),
            proposal_id=PROPOSAL_ID,
        )


def test_create_pending_normalizes_blank_slack_message_reference_to_none():
    service, _ = build_service()
    created_at = datetime(2026, 7, 1, 10, tzinfo=UTC)

    proposal = service.create_pending(
        workspace_id="T123",
        source_evidence=[],
        proposed_action={"kind": "notify"},
        slack_channel_id=" ",
        slack_message_ts="",
        created_at=created_at,
        expires_at=created_at + timedelta(hours=1),
        proposal_id=PROPOSAL_ID,
    )

    assert proposal.slack_channel_id is None
    assert proposal.slack_message_ts is None


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
    assert confirmed.audit_log[-1]["occurred_at"] == format_datetime(confirmed_at)
    assert confirmed.audit_log[-1]["approved_by_user_id"] == "UAPPROVER"


def test_confirm_pending_proposal_normalizes_approval_time_to_utc():
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

    confirmed = service.confirm(
        workspace_id="T123",
        proposal_id=PROPOSAL_ID,
        approving_user_id="UAPPROVER",
        confirmed_at=datetime(
            2026,
            7,
            1,
            20,
            30,
            tzinfo=timezone(timedelta(hours=10)),
        ),
    )

    assert confirmed.confirmed_at == datetime(2026, 7, 1, 10, 30, tzinfo=UTC)
    assert confirmed.confirmed_at.tzinfo == UTC
    assert confirmed.audit_log[-1]["occurred_at"] == "2026-07-01T10:30:00+00:00"


def test_confirm_pending_proposal_requires_approving_user():
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

    with pytest.raises(ValueError, match="approving_user_id must not be empty"):
        service.confirm(
            workspace_id="T123",
            proposal_id=PROPOSAL_ID,
            approving_user_id=" ",
            confirmed_at=created_at + timedelta(minutes=10),
        )


def test_confirm_missing_proposal_raises_not_found():
    service, _ = build_service()

    with pytest.raises(ProposalNotFound):
        service.confirm(
            workspace_id="T123",
            proposal_id=UNKNOWN_PROPOSAL_ID,
            approving_user_id="UAPPROVER",
        )


def test_confirm_rejects_non_uuid_proposal_id():
    service, _ = build_service()

    with pytest.raises(ValueError, match="proposal_id must be a valid UUID"):
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
    assert (
        repository.get_by_id("T123", DUE_PROPOSAL_ID).audit_log[-1]["occurred_at"]
        == format_datetime(now)
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
