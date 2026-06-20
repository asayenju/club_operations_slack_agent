from typing import Any

from supabase import Client, create_client


class SupabaseDocumentsRepository:
    def __init__(self, client: Client):
        self.client = client

    @classmethod
    def from_settings(
        cls,
        supabase_url: str,
        supabase_service_role_key: str,
    ) -> "SupabaseDocumentsRepository":
        return cls(create_client(supabase_url, supabase_service_role_key))

    def find_by_content_hash(self, content_hash: str) -> dict[str, Any] | None:
        response = (
            self.client.table("documents")
            .select("id,content_hash,chunk_key")
            .eq("content_hash", content_hash)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        return rows[0] if rows else None

    def insert(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self.client.table("documents").insert(payload).execute()
        rows = response.data or []
        return rows[0] if rows else payload
