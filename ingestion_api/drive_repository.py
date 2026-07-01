from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from functools import lru_cache
from typing import Protocol

from supabase import Client, create_client

from common.config import get_ingestion_settings


@dataclass(frozen=True)
class ConnectedFolder:
    workspace_id: str
    folder_id: str
    folder_name: str
    connected_by: str | None = None
    last_scanned_at: str | None = None


@dataclass(frozen=True)
class ConnectedFile:
    workspace_id: str
    folder_id: str
    file_id: str
    file_name: str
    mime_type: str
    modified_time: str | None = None
    last_ingested_at: str | None = None


class DriveRegistry(Protocol):
    def upsert_folder(self, folder: ConnectedFolder) -> None:
        ...

    def list_folders(self, workspace_id: str) -> list[ConnectedFolder]:
        ...

    def get_folder(self, workspace_id: str, folder_id: str) -> ConnectedFolder | None:
        ...

    def mark_folder_scanned(self, workspace_id: str, folder_id: str) -> None:
        ...

    def delete_folder(self, workspace_id: str, folder_id: str) -> None:
        ...

    def list_folder_files(self, workspace_id: str, folder_id: str) -> list[ConnectedFile]:
        ...

    def upsert_file(self, file: ConnectedFile) -> None:
        ...

    def delete_file_mapping(
        self,
        workspace_id: str,
        folder_id: str,
        file_id: str,
    ) -> None:
        ...

    def roots_for_item(self, workspace_id: str, file_id: str) -> set[str]:
        ...

    def roots_for_parents(
        self,
        workspace_id: str,
        parent_ids: tuple[str, ...],
    ) -> set[str]:
        ...

    def file_reference_count(self, workspace_id: str, file_id: str) -> int:
        ...

    def get_page_token(self, workspace_id: str) -> str | None:
        ...

    def set_page_token(self, workspace_id: str, page_token: str) -> None:
        ...


@lru_cache
def get_drive_registry_client() -> Client:
    settings = get_ingestion_settings()
    return create_client(
        settings.required_supabase_url,
        settings.required_supabase_service_key,
    )


class SupabaseDriveRegistry:
    def __init__(self, client: Client | None = None):
        self.client = client or get_drive_registry_client()

    def upsert_folder(self, folder: ConnectedFolder) -> None:
        payload = {
            key: value
            for key, value in asdict(folder).items()
            if value is not None
        }
        (
            self.client.table("connected_folders")
            .upsert(payload, on_conflict="workspace_id,folder_id")
            .execute()
        )

    def list_folders(self, workspace_id: str) -> list[ConnectedFolder]:
        response = (
            self.client.table("connected_folders")
            .select("workspace_id,folder_id,folder_name,connected_by,last_scanned_at")
            .eq("workspace_id", workspace_id)
            .execute()
        )
        return [ConnectedFolder(**row) for row in response.data or []]

    def get_folder(self, workspace_id: str, folder_id: str) -> ConnectedFolder | None:
        response = (
            self.client.table("connected_folders")
            .select("workspace_id,folder_id,folder_name,connected_by,last_scanned_at")
            .eq("workspace_id", workspace_id)
            .eq("folder_id", folder_id)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        return ConnectedFolder(**rows[0]) if rows else None

    def mark_folder_scanned(self, workspace_id: str, folder_id: str) -> None:
        (
            self.client.table("connected_folders")
            .update({"last_scanned_at": _utc_now()})
            .eq("workspace_id", workspace_id)
            .eq("folder_id", folder_id)
            .execute()
        )

    def delete_folder(self, workspace_id: str, folder_id: str) -> None:
        (
            self.client.table("connected_folders")
            .delete()
            .eq("workspace_id", workspace_id)
            .eq("folder_id", folder_id)
            .execute()
        )

    def list_folder_files(self, workspace_id: str, folder_id: str) -> list[ConnectedFile]:
        response = (
            self.client.table("connected_files")
            .select(
                "workspace_id,folder_id,file_id,file_name,mime_type,"
                "modified_time,last_ingested_at"
            )
            .eq("workspace_id", workspace_id)
            .eq("folder_id", folder_id)
            .execute()
        )
        return [ConnectedFile(**row) for row in response.data or []]

    def upsert_file(self, file: ConnectedFile) -> None:
        payload = {
            key: value
            for key, value in asdict(file).items()
            if value is not None
        }
        (
            self.client.table("connected_files")
            .upsert(payload, on_conflict="workspace_id,folder_id,file_id")
            .execute()
        )

    def delete_file_mapping(
        self,
        workspace_id: str,
        folder_id: str,
        file_id: str,
    ) -> None:
        (
            self.client.table("connected_files")
            .delete()
            .eq("workspace_id", workspace_id)
            .eq("folder_id", folder_id)
            .eq("file_id", file_id)
            .execute()
        )

    def roots_for_item(self, workspace_id: str, file_id: str) -> set[str]:
        response = (
            self.client.table("connected_files")
            .select("folder_id")
            .eq("workspace_id", workspace_id)
            .eq("file_id", file_id)
            .execute()
        )
        return {str(row["folder_id"]) for row in response.data or []}

    def roots_for_parents(
        self,
        workspace_id: str,
        parent_ids: tuple[str, ...],
    ) -> set[str]:
        if not parent_ids:
            return set()

        roots = {
            folder.folder_id
            for folder in self.list_folders(workspace_id)
            if folder.folder_id in parent_ids
        }
        response = (
            self.client.table("connected_files")
            .select("folder_id")
            .eq("workspace_id", workspace_id)
            .in_("file_id", list(parent_ids))
            .execute()
        )
        roots.update(str(row["folder_id"]) for row in response.data or [])
        return roots

    def file_reference_count(self, workspace_id: str, file_id: str) -> int:
        response = (
            self.client.table("connected_files")
            .select("file_id", count="exact")
            .eq("workspace_id", workspace_id)
            .eq("file_id", file_id)
            .execute()
        )
        return int(response.count or 0)

    def get_page_token(self, workspace_id: str) -> str | None:
        response = (
            self.client.table("drive_sync_state")
            .select("page_token")
            .eq("workspace_id", workspace_id)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        if not rows or not rows[0].get("page_token"):
            return None
        return str(rows[0]["page_token"])

    def set_page_token(self, workspace_id: str, page_token: str) -> None:
        (
            self.client.table("drive_sync_state")
            .upsert(
                {
                    "workspace_id": workspace_id,
                    "page_token": page_token,
                    "updated_at": _utc_now(),
                },
                on_conflict="workspace_id",
            )
            .execute()
        )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
