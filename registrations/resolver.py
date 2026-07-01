from common.config import get_ingestion_settings
from registrations.repository import SupabaseRegistrationRepository
from registrations.service import RegistrationService


def resolve_google_email(
    workspace_id: str,
    slack_user_id: str,
    service: RegistrationService | None = None,
) -> str | None:
    registration_service = service or _build_registration_service()
    return registration_service.resolve_google_email(
        workspace_id,
        slack_user_id,
    )


def _build_registration_service() -> RegistrationService:
    settings = get_ingestion_settings()
    return RegistrationService(
        SupabaseRegistrationRepository.from_settings(
            settings.required_supabase_url,
            settings.required_supabase_service_key,
        )
    )
