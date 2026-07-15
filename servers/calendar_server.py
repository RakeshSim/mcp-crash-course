# calendar_server.py
import datetime
import logging
import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from mcp.server.fastmcp import FastMCP

logging.basicConfig(level=logging.WARNING)

# Separate scope from gmail_server.py, so it needs its own token file
# (a token is only valid for the scopes it was originally granted for).
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
CREDENTIALS_FILE = "credentials.json"  # same OAuth client as gmail_server.py
TOKEN_FILE = "calendar_token.json"

mcp = FastMCP("Calendar")


def _get_service():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    return build("calendar", "v3", credentials=creds)


@mcp.tool()
def list_upcoming_events(days: int = 7, limit: int = 10) -> str:
    """List upcoming events on the user's primary Google Calendar within the next `days` days."""
    service = _get_service()
    now = datetime.datetime.utcnow().isoformat() + "Z"
    time_max = (datetime.datetime.utcnow() + datetime.timedelta(days=days)).isoformat() + "Z"

    resp = service.events().list(
        calendarId="primary",
        timeMin=now,
        timeMax=time_max,
        maxResults=limit,
        singleEvents=True,
        orderBy="startTime",
    ).execute()
    events = resp.get("items", [])

    if not events:
        return f"No upcoming events in the next {days} days."

    lines = []
    for e in events:
        start = e["start"].get("dateTime", e["start"].get("date"))
        lines.append(f"{start}: {e.get('summary', '(no title)')}")
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run(transport="stdio")
