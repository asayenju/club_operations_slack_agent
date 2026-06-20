from common.config import SlackSettings


def test_slack_settings_accepts_supabase_service_key_alias(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-test")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "service-key")
    monkeypatch.setenv("VOYAGE_API_KEY", "voyage-key")

    settings = SlackSettings(_env_file=None)

    assert settings.supabase_service_role_key == "service-key"
    assert settings.voyage_embed_model == "voyage-4-lite"
