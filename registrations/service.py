from typing import Protocol


class RegistrationRepository(Protocol):
    def find_by_user(
        self,
        workspace_id: str,
        slack_user_id: str,
    ) -> dict | None:
        ...

    def find_by_email(
        self,
        workspace_id: str,
        email: str,
    ) -> dict | None:
        ...

    def upsert(
        self,
        workspace_id: str,
        slack_user_id: str,
        email: str,
        display_name: str | None,
    ) -> None:
        ...

    def delete(self, workspace_id: str, slack_user_id: str) -> bool:
        ...


class EmailAlreadyRegistered(RuntimeError):
    pass


class RegistrationService:
    def __init__(self, repository: RegistrationRepository):
        self.repository = repository

    def register(
        self,
        workspace_id: str,
        slack_user_id: str,
        email: str,
        display_name: str | None = None,
    ) -> str:
        normalized_email = email.strip().lower()
        existing = self.repository.find_by_email(
            workspace_id,
            normalized_email,
        )
        if existing and existing["slack_user_id"] != slack_user_id:
            raise EmailAlreadyRegistered(
                "That Google account is already linked to another Slack user."
            )
        self.repository.upsert(
            workspace_id,
            slack_user_id,
            normalized_email,
            display_name,
        )
        return normalized_email

    def unregister(self, workspace_id: str, slack_user_id: str) -> bool:
        return self.repository.delete(workspace_id, slack_user_id)

    def resolve_google_email(
        self,
        workspace_id: str,
        slack_user_id: str,
    ) -> str | None:
        registration = self.repository.find_by_user(
            workspace_id,
            slack_user_id,
        )
        return registration["email"] if registration else None
