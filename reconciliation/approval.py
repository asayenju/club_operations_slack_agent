from __future__ import annotations

from dataclasses import dataclass


DEFAULT_APPROVAL_REACTION = "white_check_mark"


class ReconciliationApprovalRejected(RuntimeError):
    pass


class ReconciliationApprovalNotConfigured(ReconciliationApprovalRejected):
    pass


@dataclass(frozen=True)
class ReconciliationApprovalPolicy:
    lead_user_ids: frozenset[str]
    approval_reaction: str = DEFAULT_APPROVAL_REACTION
    allow_any_user: bool = False

    @classmethod
    def from_settings(cls, settings) -> "ReconciliationApprovalPolicy":
        lead_user_ids = _parse_user_ids(
            getattr(settings, "reconciliation_approval_user_ids", None)
        )
        return cls(
            lead_user_ids=lead_user_ids,
            approval_reaction=_normalize_reaction(
                getattr(
                    settings,
                    "reconciliation_approval_reaction",
                    DEFAULT_APPROVAL_REACTION,
                )
            ),
            allow_any_user=(
                not lead_user_ids
                and getattr(settings, "app_env", "development") == "development"
            ),
        )


def validate_reconciliation_approval(
    *,
    policy: ReconciliationApprovalPolicy,
    approving_user_id: str,
    reaction: str,
) -> None:
    if not policy.lead_user_ids and not policy.allow_any_user:
        raise ReconciliationApprovalNotConfigured(
            "reconciliation approval users are not configured"
        )

    approving_user_id = approving_user_id.strip()
    if not approving_user_id:
        raise ReconciliationApprovalRejected(
            "approving user is required"
        )
    if policy.lead_user_ids and approving_user_id not in policy.lead_user_ids:
        raise ReconciliationApprovalRejected(
            "user is not allowed to approve reconciliation proposals"
        )

    if _normalize_reaction(reaction) != policy.approval_reaction:
        raise ReconciliationApprovalRejected(
            "reaction is not configured for reconciliation approval"
        )


def _parse_user_ids(value: str | None) -> frozenset[str]:
    if not value:
        return frozenset()
    return frozenset(user_id.strip() for user_id in value.split(",") if user_id.strip())


def _normalize_reaction(value: str | None) -> str:
    value = (value or DEFAULT_APPROVAL_REACTION).strip()
    value = value.removeprefix(":").removesuffix(":")
    if ":skin-tone-" in value:
        value = value.split(":skin-tone-", 1)[0].removesuffix(":")
    return value or DEFAULT_APPROVAL_REACTION
