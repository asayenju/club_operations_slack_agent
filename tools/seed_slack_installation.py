"""One-off admin tool: seed slack_installations for a workspace that's
currently running on the old static SLACK_BOT_TOKEN model, so upgrading to
the OAuth install flow (issue #61) doesn't take the bot down with no remote
recovery path.

Without this, the moment SupabaseInstallationStore ships, both the Slack bot
and ingestion API lose their bot token entirely (the app no longer reads
SLACK_BOT_TOKEN at all), and the only fix is completing /slack/install again
-- which isn't reachable from outside the host until real public hosting
(issue #62) exists. Run this once, before or immediately during that deploy,
using the bot token you already have.

Usage:
    SLACK_BOT_TOKEN=xoxb-... python -m tools.seed_slack_installation
"""

import os
import time

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from slack_sdk.oauth.installation_store.models.bot import Bot

from common.config import get_slack_settings
from common.slack_installation_store import SupabaseInstallationStore


def main() -> None:
    bot_token = os.environ.get("SLACK_BOT_TOKEN")
    if not bot_token:
        print("Set SLACK_BOT_TOKEN to the existing bot token before running this.")
        raise SystemExit(1)

    client = WebClient(token=bot_token)
    try:
        response = client.auth_test()
    except SlackApiError as exc:
        print(f"auth.test failed: {exc.response.get('error', 'unknown_error')}")
        raise SystemExit(1) from exc

    team_id = response["team_id"]
    bot_user_id = response.get("user_id")
    bot_id = response.get("bot_id")
    scopes_header = (response.headers or {}).get("x-oauth-scopes", "")

    settings = get_slack_settings()
    from supabase import create_client
    supabase = create_client(settings.supabase_url, settings.supabase_service_role_key)

    store = SupabaseInstallationStore(supabase)
    store.save_bot(Bot(
        app_id=None,
        team_id=team_id,
        bot_token=bot_token,
        bot_id=bot_id,
        bot_user_id=bot_user_id,
        bot_scopes=scopes_header,
        installed_at=time.time(),
    ))
    print(f"Seeded slack_installations for team_id={team_id!r}. Bot token is encrypted at rest.")


if __name__ == "__main__":
    main()
