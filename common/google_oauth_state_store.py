"""Server-side, single-use, expiring state tokens for the Google OAuth
"Connect Google Drive" flow (issue #74 review, Aman).

Previously the `state` param carried "{team_id}|{user_id}" directly, and
/google/oauth_redirect trusted that content verbatim -- Slack team IDs
aren't secret, so anyone who knew a workspace's team_id could forge that
state and complete Google's consent screen themselves, causing their own
refresh token to overwrite that workspace's stored Drive credentials. The
fix: issue an unguessable random token, record server-side which
workspace/user it was issued for, and require the callback to redeem it
exactly once before it expires.
"""

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

DEFAULT_TTL_SECONDS = 600  # 10 minutes -- enough to complete Google's consent screen


class GoogleOAuthStateStore:
    def __init__(self, supabase_client: Any):
        self._supabase = supabase_client

    def create(
        self,
        workspace_id: str,
        user_id: Optional[str],
        *,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> str:
        """Issue a new single-use state token for this workspace/user."""
        token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        row = {
            "state": token,
            "workspace_id": workspace_id,
            "user_id": user_id,
            "expires_at": (now + timedelta(seconds=ttl_seconds)).isoformat(),
        }
        self._supabase.table("google_oauth_states").insert(row).execute()
        return token

    def consume(self, state: str) -> Optional[tuple[str, Optional[str]]]:
        """Redeem a state token exactly once. Returns (workspace_id, user_id)
        if `state` is a real, unexpired, not-yet-consumed token, else None --
        covering unknown, forged, expired, and replayed tokens alike (the
        caller doesn't need to distinguish them; all are simply invalid)."""
        if not state:
            return None
        now_iso = datetime.now(timezone.utc).isoformat()
        rows = (
            self._supabase.table("google_oauth_states")
            .update({"consumed_at": now_iso})
            .eq("state", state)
            .is_("consumed_at", "null")
            .gt("expires_at", now_iso)
            .execute()
            .data
        )
        if not rows:
            return None
        row = rows[0]
        return row["workspace_id"], row.get("user_id")
