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


def test_ingestion_settings_slack_backfill_defaults(monkeypatch):
    monkeypatch.delenv("SLACK_BACKFILL_LIMIT", raising=False)
    monkeypatch.delenv("SLACK_RECONCILE_CRON_HOUR", raising=False)

    settings = IngestionSettings(_env_file=None)

    assert settings.slack_backfill_limit == 200
    assert settings.slack_reconcile_cron_hour == 6


def test_ingestion_settings_slack_backfill_limit_overridable(monkeypatch):
    monkeypatch.setenv("SLACK_BACKFILL_LIMIT", "50")

    settings = IngestionSettings(_env_file=None)

    assert settings.slack_backfill_limit == 50


def test_ingestion_settings_slack_reconcile_cron_hour_overridable(monkeypatch):
    monkeypatch.setenv("SLACK_RECONCILE_CRON_HOUR", "3")

    settings = IngestionSettings(_env_file=None)

    assert settings.slack_reconcile_cron_hour == 3
