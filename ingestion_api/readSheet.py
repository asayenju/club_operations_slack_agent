import json
import gspread

def get_sheet_rows(service_account_json, sheet_id):
    """
    connect with google sheet and get data back
    """
    creds_dict = json.loads(service_account_json)
    client = gspread.service_account_from_dict(creds_dict)
    sheet = client.open_by_key(sheet_id)
    worksheet = sheet.get_worksheet(0)
    return worksheet.get_all_records()


def row_to_text(row: dict) -> str:
    """
    Converts a row dict to a readable string for embedding.
    """
    return " | ".join(f"{key}: {value}" for key, value in row.items())


if __name__ == "__main__":

    import os
    from pathlib import Path
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).parent.parent / ".env")

    service_account_json = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
    sheet_id = "18qD3iUbKgasx5bFWZiuGqNJdJGhMLvpPBxxalaIanIU"

    rows = get_sheet_rows(service_account_json, sheet_id)
    print(f"Reading the {len(rows)} th row... ")

    for row in rows[:3]:
        print(row_to_text(row))
