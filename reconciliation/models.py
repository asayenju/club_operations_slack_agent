from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class ProposalStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    EXPIRED = "expired"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


TERMINAL_STATUSES = {
    ProposalStatus.CONFIRMED,
    ProposalStatus.EXPIRED,
    ProposalStatus.REJECTED,
    ProposalStatus.SUPERSEDED,
}


@dataclass(frozen=True)
class ReconciliationProposal:
    id: str
    workspace_id: str
    status: ProposalStatus
    source_evidence: list[dict[str, Any]]
    proposed_action: dict[str, Any]
    slack_channel_id: str | None
    slack_message_ts: str | None
    created_at: datetime
    expires_at: datetime
    confirmed_by_user_id: str | None = None
    confirmed_at: datetime | None = None
    audit_log: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "ReconciliationProposal":
        return cls(
            id=str(row["id"]),
            workspace_id=str(row["workspace_id"]),
            status=ProposalStatus(str(row["status"])),
            source_evidence=list(row.get("source_evidence") or []),
            proposed_action=dict(row.get("proposed_action") or {}),
            slack_channel_id=row.get("slack_channel_id"),
            slack_message_ts=row.get("slack_message_ts"),
            created_at=parse_datetime(row["created_at"]),
            expires_at=parse_datetime(row["expires_at"]),
            confirmed_by_user_id=row.get("confirmed_by_user_id"),
            confirmed_at=parse_datetime(row["confirmed_at"])
            if row.get("confirmed_at")
            else None,
            audit_log=list(row.get("audit_log") or []),
        )

    def to_row(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "workspace_id": self.workspace_id,
            "status": self.status.value,
            "source_evidence": self.source_evidence,
            "proposed_action": self.proposed_action,
            "slack_channel_id": self.slack_channel_id,
            "slack_message_ts": self.slack_message_ts,
            "created_at": format_datetime(self.created_at),
            "expires_at": format_datetime(self.expires_at),
            "confirmed_by_user_id": self.confirmed_by_user_id,
            "confirmed_at": format_datetime(self.confirmed_at)
            if self.confirmed_at
            else None,
            "audit_log": self.audit_log,
        }

    def with_audit_event(
        self,
        event: str,
        occurred_at: datetime,
        metadata: dict[str, Any] | None = None,
    ) -> "ReconciliationProposal":
        audit_event = {
            "event": event,
            "occurred_at": format_datetime(occurred_at),
            **(metadata or {}),
        }
        return replace(self, audit_log=[*self.audit_log, audit_event])


def parse_datetime(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def format_datetime(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()
