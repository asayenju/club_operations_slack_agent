from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from reconciliation.models import ProposalStatus, ReconciliationProposal


DEFAULT_APPROVAL_REACTION = "white_check_mark"


class ReconciliationApprovalRejected(RuntimeError):
    pass


class ReconciliationApprovalNotConfigured(ReconciliationApprovalRejected):
    pass


@dataclass(frozen=True)
class ReconciliationApprovalPolicy:
    lead_user_ids: frozenset[str]
    approval_reaction: str = DEFAULT_APPROVAL_REACTION

    @classmethod
    def from_settings(cls, settings) -> "ReconciliationApprovalPolicy":
        return cls(
            lead_user_ids=_parse_user_ids(
                getattr(settings, "reconciliation_approval_user_ids", None)
            ),
            approval_reaction=_normalize_reaction(
                getattr(
                    settings,
                    "reconciliation_approval_reaction",
                    DEFAULT_APPROVAL_REACTION,
                )
            ),
        )


def validate_reconciliation_approval(
    *,
    proposal: ReconciliationProposal,
    policy: ReconciliationApprovalPolicy,
    approving_user_id: str,
    reaction: str,
    now: datetime | None = None,
) -> None:
    if not policy.lead_user_ids:
        raise ReconciliationApprovalNotConfigured(
            "reconciliation approval users are not configured"
        )

    approving_user_id = approving_user_id.strip()
    if approving_user_id not in policy.lead_user_ids:
        raise ReconciliationApprovalRejected(
            "user is not allowed to approve reconciliation proposals"
        )

    if _normalize_reaction(reaction) != policy.approval_reaction:
        raise ReconciliationApprovalRejected(
            "reaction is not configured for reconciliation approval"
        )

    if proposal.status != ProposalStatus.PENDING:
        raise ReconciliationApprovalRejected(
            f"cannot approve {proposal.status.value} reconciliation proposal"
        )

    timestamp = _utc_datetime(now or datetime.now(UTC))
    if proposal.expires_at <= timestamp:
        raise ReconciliationApprovalRejected(
            "expired reconciliation proposals cannot be approved"
        )


def _parse_user_ids(value: str | None) -> frozenset[str]:
    if not value:
        return frozenset()
    return frozenset(user_id.strip() for user_id in value.split(",") if user_id.strip())


def _normalize_reaction(value: str | None) -> str:
    value = (value or DEFAULT_APPROVAL_REACTION).strip()
    value = value.removeprefix(":").removesuffix(":")
    return value or DEFAULT_APPROVAL_REACTION


def _utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
