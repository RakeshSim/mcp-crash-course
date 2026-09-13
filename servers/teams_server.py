# teams_server.py
import logging
import os
import time

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()
logging.basicConfig(level=logging.WARNING)

mcp = FastMCP("Teams")

GRAPH_API = "https://graph.microsoft.com/v1.0"
TENANT_ID = os.getenv("TEAMS_TENANT_ID")
CLIENT_ID = os.getenv("TEAMS_CLIENT_ID")
CLIENT_SECRET = os.getenv("TEAMS_CLIENT_SECRET")

# Unlike Slack's static bot token, Graph API access needs a short-lived OAuth
# token (app-only client-credentials flow). Cached in-memory and refreshed
# once it's within 60s of expiry, so we're not re-authenticating on every call.
_token_cache: dict = {"access_token": None, "expires_at": 0}


async def _get_token() -> str:
    if _token_cache["access_token"] and time.time() < _token_cache["expires_at"] - 60:
        return _token_cache["access_token"]

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token",
            data={
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "scope": "https://graph.microsoft.com/.default",
                "grant_type": "client_credentials",
            },
        )
        data = resp.json()

    if "access_token" not in data:
        raise RuntimeError(f"Failed to get Teams access token: {data}")

    _token_cache["access_token"] = data["access_token"]
    _token_cache["expires_at"] = time.time() + data["expires_in"]
    return _token_cache["access_token"]


async def _headers() -> dict:
    token = await _get_token()
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@mcp.tool()
async def send_teams_message(team_id: str, channel_id: str, text: str) -> str:
    """Send a message to a Microsoft Teams channel. team_id and channel_id come from the channel's 'Get link to channel' URL (see README)."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{GRAPH_API}/teams/{team_id}/channels/{channel_id}/messages",
            headers=await _headers(),
            json={"body": {"content": text}},
        )
        data = resp.json()

    if resp.status_code >= 400:
        return f"Failed to send message: {data.get('error', {}).get('message', data)}"
    return f"Message sent to channel {channel_id}."


@mcp.tool()
async def list_recent_teams_messages(team_id: str, channel_id: str, limit: int = 5) -> str:
    """List the most recent messages in a Microsoft Teams channel."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GRAPH_API}/teams/{team_id}/channels/{channel_id}/messages",
            headers=await _headers(),
            params={"$top": limit},
        )
        data = resp.json()

    if resp.status_code >= 400:
        return f"Failed to fetch messages: {data.get('error', {}).get('message', data)}"

    messages = [m for m in data.get("value", []) if m.get("body", {}).get("content")]
    if not messages:
        return f"No recent messages in channel {channel_id}."

    lines = []
    for m in messages[:limit]:
        sender = m.get("from", {}).get("user", {}).get("displayName", "unknown")
        body = m["body"]["content"]
        lines.append(f"{sender}: {body}")
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run(transport="stdio")
