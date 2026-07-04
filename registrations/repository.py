from datetime import datetime, timezone

from supabase import Client, create_client


class SupabaseRegistrationRepository:
    def __init__(self, client: Client):
        self.client = client

    @classmethod
    def from_settings(
        cls,
        supabase_url: str,
        supabase_service_key: str,
    ) -> "SupabaseRegistrationRepository":
        return cls(create_client(supabase_url, supabase_service_key))

    def upsert(
        self,
        workspace_id: str,
        slack_user_id: str,
        email: str,
        display_name: str | None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        (
            self.client.table("user_google_accounts")
            .upsert(
                {
                    "workspace_id": workspace_id,
                    "slack_user_id": slack_user_id,
                    "google_email": email,
                    "display_name": display_name,
                    "source": "register",
                    "updated_at": now,
                },
                on_conflict="workspace_id,slack_user_id",
            )
            .execute()
        )

    def find_by_email(
        self,
        workspace_id: str,
        email: str,
    ) -> dict | None:
        response = (
            self.client.table("user_google_accounts")
            .select("workspace_id,slack_user_id,google_email")
            .eq("workspace_id", workspace_id)
            .eq("google_email", email)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        if not rows:
            return None
        return {
            "workspace_id": rows[0]["workspace_id"],
            "slack_user_id": rows[0]["slack_user_id"],
            "email": rows[0]["google_email"],
        }

    def find_by_user(
        self,
        workspace_id: str,
        slack_user_id: str,
    ) -> dict | None:
        response = (
            self.client.table("user_google_accounts")
            .select(
                "workspace_id,slack_user_id,google_email,display_name,source"
            )
            .eq("workspace_id", workspace_id)
            .eq("slack_user_id", slack_user_id)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        if not rows:
            return None
        return {
            "workspace_id": rows[0]["workspace_id"],
            "slack_user_id": rows[0]["slack_user_id"],
            "email": rows[0]["google_email"],
            "display_name": rows[0].get("display_name"),
            "source": rows[0]["source"],
        }

    def delete(self, workspace_id: str, slack_user_id: str) -> bool:
        existing = (
            self.client.table("user_google_accounts")
            .select("slack_user_id")
            .eq("workspace_id", workspace_id)
            .eq("slack_user_id", slack_user_id)
            .limit(1)
            .execute()
            .data
            or []
        )
        if not existing:
            return False
        (
            self.client.table("user_google_accounts")
            .delete()
            .eq("workspace_id", workspace_id)
            .eq("slack_user_id", slack_user_id)
            .execute()
        )
        return True
