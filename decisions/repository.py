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

    def find_by_chunk_key(self, chunk_key: str) -> dict[str, Any] | None:
        response = (
            self.client.table("documents")
            .select("id,content_hash,chunk_key")
            .eq("chunk_key", chunk_key)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        return rows[0] if rows else None

    def insert_many(self, payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
        response = self.client.table("documents").insert(payloads).execute()
        rows = response.data or []
        return rows if rows else payloads
