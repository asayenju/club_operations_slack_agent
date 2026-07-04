import pytest

from registrations.service import (
    EmailAlreadyRegistered,
    RegistrationService,
)
from registrations.resolver import resolve_google_email


class InMemoryRegistrationRepository:
    def __init__(self):
        self.records = {}

    def find_by_email(self, workspace_id, email):
        return next(
            (
                record
                for record in self.records.values()
                if record["workspace_id"] == workspace_id
                and record["email"] == email
            ),
            None,
        )

    def find_by_user(self, workspace_id, slack_user_id):
        return self.records.get((workspace_id, slack_user_id))

    def upsert(
        self,
        workspace_id,
        slack_user_id,
        email,
        display_name,
    ):
        self.records[(workspace_id, slack_user_id)] = {
            "workspace_id": workspace_id,
            "slack_user_id": slack_user_id,
            "email": email,
            "display_name": display_name,
        }

    def delete(self, workspace_id, slack_user_id):
        return self.records.pop((workspace_id, slack_user_id), None) is not None


def test_reregistering_updates_the_same_slack_user():
    repository = InMemoryRegistrationRepository()
    service = RegistrationService(repository)

    service.register("T123", "U1", "first@example.com", "Aman")
    service.register("T123", "U1", "second@example.com", "Aman")

    assert repository.records[("T123", "U1")]["email"] == "second@example.com"
    assert len(repository.records) == 1


def test_email_cannot_be_registered_by_another_user_in_workspace():
    repository = InMemoryRegistrationRepository()
    service = RegistrationService(repository)
    service.register("T123", "U1", "shared@example.com", "Aman")

    with pytest.raises(EmailAlreadyRegistered):
        service.register("T123", "U2", "SHARED@example.com", "Hailee")

    assert ("T123", "U2") not in repository.records


def test_unregister_returns_whether_a_mapping_was_removed():
    repository = InMemoryRegistrationRepository()
    service = RegistrationService(repository)
    service.register("T123", "U1", "member@example.com")

    assert service.unregister("T123", "U1") is True
    assert service.unregister("T123", "U1") is False


def test_resolver_returns_registered_email_or_none():
    repository = InMemoryRegistrationRepository()
    service = RegistrationService(repository)
    service.register("T123", "U1", "Member@Example.com")

    assert resolve_google_email("T123", "U1", service) == "member@example.com"
    assert resolve_google_email("T123", "U2", service) is None
