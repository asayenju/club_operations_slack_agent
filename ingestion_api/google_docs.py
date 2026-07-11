from collections.abc import Iterator
from typing import Any, TypedDict

from googleapiclient.discovery import build

from common.google_credentials_store import get_google_credentials


HEADING_STYLES = {f"HEADING_{level}" for level in range(1, 7)}
GOOGLE_READ_SCOPES = [
    "https://www.googleapis.com/auth/documents.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
]


class DocumentSection(TypedDict):
    heading_path: str
    heading: str
    text: str


def get_docs_service(workspace_id: str) -> Any:
    credentials = get_google_credentials(workspace_id, GOOGLE_READ_SCOPES)
    return build("docs", "v1", credentials=credentials, cache_discovery=False)


def fetch_doc(doc_id: str, workspace_id: str) -> dict[str, Any]:
    normalized_doc_id = doc_id.strip()
    if not normalized_doc_id:
        raise ValueError("doc_id must not be empty")

    return (
        get_docs_service(workspace_id)
        .documents()
        .get(documentId=normalized_doc_id)
        .execute()
    )


def _paragraph_text(paragraph: dict[str, Any]) -> str:
    return "".join(
        element["textRun"]["content"]
        for element in paragraph.get("elements", [])
        if element.get("textRun", {}).get("content")
    )


def _iter_paragraphs(elements: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    for element in elements:
        paragraph = element.get("paragraph")
        if paragraph:
            yield paragraph

        table = element.get("table")
        if table:
            for row in table.get("tableRows", []):
                for cell in row.get("tableCells", []):
                    yield from _iter_paragraphs(cell.get("content", []))

        table_of_contents = element.get("tableOfContents")
        if table_of_contents:
            yield from _iter_paragraphs(table_of_contents.get("content", []))


def extract_sections(doc: dict[str, Any]) -> tuple[str, list[DocumentSection]]:
    """Split a Google Doc into full-text sections following heading hierarchy."""
    title = str(doc.get("title") or "untitled").strip()
    sections: list[DocumentSection] = []
    heading_path: list[str] = []
    current_heading = title
    buffer: list[str] = []

    def flush() -> None:
        text = "".join(buffer).strip()
        if not text:
            return

        sections.append(
            {
                "heading_path": " > ".join(heading_path) if heading_path else title,
                "heading": current_heading,
                "text": text,
            }
        )

    body_elements = doc.get("body", {}).get("content", [])
    for paragraph in _iter_paragraphs(body_elements):
        style = paragraph.get("paragraphStyle", {}).get(
            "namedStyleType",
            "NORMAL_TEXT",
        )
        text = _paragraph_text(paragraph)

        if style in HEADING_STYLES and text.strip():
            flush()
            buffer = []
            level = int(style.rsplit("_", maxsplit=1)[1])
            heading_path = heading_path[: level - 1]
            heading_path.append(text.strip())
            current_heading = text.strip()
        else:
            buffer.append(text)

    flush()
    return title, sections
