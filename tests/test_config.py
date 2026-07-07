from common.config import IngestionSettings, SlackSettings


def test_slack_settings_accepts_supabase_service_key_alias(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-test")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "service-key")
    monkeypatch.setenv("VOYAGE_API_KEY", "voyage-key")

    settings = SlackSettings(_env_file=None)

    assert settings.supabase_service_role_key == "service-key"
    assert settings.voyage_embed_model == "voyage-3.5-lite"
    assert settings.voyage_embed_dimension == 1024


def test_ingestion_settings_accepts_supabase_service_role_key_alias(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role-key")

    settings = IngestionSettings(_env_file=None)

    assert settings.supabase_service_key == "service-role-key"


def test_settings_prefer_service_role_key_when_both_aliases_are_set(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-test")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "role-key")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "legacy-key")
    monkeypatch.setenv("VOYAGE_API_KEY", "voyage-key")

    slack_settings = SlackSettings(_env_file=None)
    ingestion_settings = IngestionSettings(_env_file=None)

    assert slack_settings.supabase_service_role_key == "role-key"
    assert ingestion_settings.supabase_service_key == "role-key"
