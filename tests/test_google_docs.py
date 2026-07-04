from ingestion_api.google_docs import extract_sections


def paragraph(text: str, style: str = "NORMAL_TEXT") -> dict:
    return {
        "paragraph": {
            "paragraphStyle": {"namedStyleType": style},
            "elements": [{"textRun": {"content": text}}],
        }
    }


def test_extract_sections_tracks_heading_hierarchy_and_preamble():
    document = {
        "title": "Committee Notes",
        "body": {
            "content": [
                paragraph("Opening context.\n"),
                paragraph("Budget\n", "HEADING_1"),
                paragraph("The approved budget is $500.\n"),
                paragraph("Venue\n", "HEADING_2"),
                paragraph("The hall costs $250.\n"),
                paragraph("Next steps\n", "HEADING_1"),
                paragraph("Book it by Friday.\n"),
            ]
        },
    }

    title, sections = extract_sections(document)

    assert title == "Committee Notes"
    assert sections == [
        {
            "heading_path": "Committee Notes",
            "heading": "Committee Notes",
            "text": "Opening context.",
        },
        {
            "heading_path": "Budget",
            "heading": "Budget",
            "text": "The approved budget is $500.",
        },
        {
            "heading_path": "Budget > Venue",
            "heading": "Venue",
            "text": "The hall costs $250.",
        },
        {
            "heading_path": "Next steps",
            "heading": "Next steps",
            "text": "Book it by Friday.",
        },
    ]


def test_extract_sections_includes_text_from_tables():
    document = {
        "title": "Budget",
        "body": {
            "content": [
                {
                    "table": {
                        "tableRows": [
                            {
                                "tableCells": [
                                    {"content": [paragraph("Venue: $250\n")]},
                                    {"content": [paragraph("Food: $100\n")]},
                                ]
                            }
                        ]
                    }
                }
            ]
        },
    }

    _, sections = extract_sections(document)

    assert sections[0]["text"] == "Venue: $250\nFood: $100"
