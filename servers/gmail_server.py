# gmail_server.py
import base64
import logging
import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from mcp.server.fastmcp import FastMCP

logging.basicConfig(level=logging.WARNING)  # silence MCP/googleapiclient's "file_cache" and per-request INFO logs

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
CREDENTIALS_FILE = "credentials.json"
TOKEN_FILE = "token.json"

mcp = FastMCP("Gmail")


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
    return build("gmail", "v1", credentials=creds)


@mcp.tool()
def search_emails(query: str, limit: int = 5) -> str:
    """Search Gmail using Gmail search syntax, e.g. 'from:linkedin newer_than:7d' or 'subject:job'."""
    service = _get_service()
    resp = service.users().messages().list(userId="me", q=query, maxResults=limit).execute()
    msg_refs = resp.get("messages", [])

    if not msg_refs:
        return f"No emails found for query: {query}"

    lines = []
    for ref in msg_refs:
        msg = service.users().messages().get(
            userId="me", id=ref["id"], format="metadata",
            metadataHeaders=["From", "Subject", "Date"],
        ).execute()
        headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
        snippet = msg.get("snippet", "")
        lines.append(
            f"From: {headers.get('From', '?')} | Subject: {headers.get('Subject', '?')} | {headers.get('Date', '?')}\n  {snippet}"
        )

    return "\n\n".join(lines)


if __name__ == "__main__":
    mcp.run(transport="stdio")
