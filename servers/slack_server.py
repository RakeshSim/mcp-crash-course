# slack_server.py
import logging
import os

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()
logging.basicConfig(level=logging.WARNING)

mcp = FastMCP("Slack")

SLACK_API = "https://slack.com/api"


def _headers() -> dict:
    return {"Authorization": f"Bearer {os.getenv('SLACK_BOT_TOKEN')}"}


@mcp.tool()
async def send_slack_message(channel: str, text: str) -> str:
    """Send a message to a Slack channel. channel is a channel ID (e.g. 'C01234ABCDE') or name (e.g. '#general')."""
    async with httpx.AsyncClient() as client:
        # The bot can only post to channels it has joined. Join first (public
        # channels only) so any new channel works without a manual /invite step.
        join_resp = await client.post(
            f"{SLACK_API}/conversations.join", headers=_headers(), json={"channel": channel}
        )
        join_data = join_resp.json()
        if not join_data.get("ok") and join_data.get("error") != "already_in_channel":
            return f"Failed to join channel: {join_data.get('error')}"

        resp = await client.post(
            f"{SLACK_API}/chat.postMessage",
            headers=_headers(),
            json={"channel": channel, "text": text},
        )
        data = resp.json()

    if not data.get("ok"):
        return f"Failed to send message: {data.get('error')}"
    return f"Message sent to {channel}."


@mcp.tool()
async def list_recent_slack_messages(channel: str, limit: int = 5) -> str:
    """List the most recent messages in a Slack channel. channel is a channel ID (bot must be a member of it)."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{SLACK_API}/conversations.history",
            headers=_headers(),
            params={"channel": channel, "limit": limit},
        )
        data = resp.json()

    if not data.get("ok"):
        return f"Failed to fetch messages: {data.get('error')}"

    messages = data.get("messages", [])
    if not messages:
        return f"No recent messages in {channel}."

    lines = [f"{m.get('user', 'unknown')}: {m.get('text', '')}" for m in messages]
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run(transport="stdio")
