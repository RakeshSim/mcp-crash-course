# github_server.py
import os

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

mcp = FastMCP("GitHub")

GITHUB_API = "https://api.github.com"


def _headers() -> dict:
    headers = {"Accept": "application/vnd.github+json"}
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


@mcp.tool()
async def list_open_issues(repo: str, limit: int = 5) -> str:
    """List open issues for a GitHub repo. repo format: 'owner/name', e.g. 'anthropics/claude-code'."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GITHUB_API}/repos/{repo}/issues",
            params={"state": "open", "per_page": limit},
            headers=_headers(),
        )
        resp.raise_for_status()
        issues = [i for i in resp.json() if "pull_request" not in i]

    if not issues:
        return f"No open issues found for {repo}."

    lines = [f"#{i['number']} {i['title']} ({i['html_url']})" for i in issues]
    return "\n".join(lines)


@mcp.tool()
async def list_open_pull_requests(repo: str, limit: int = 5) -> str:
    """List open pull requests for a GitHub repo. repo format: 'owner/name', e.g. 'anthropics/claude-code'."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GITHUB_API}/repos/{repo}/pulls",
            params={"state": "open", "per_page": limit},
            headers=_headers(),
        )
        resp.raise_for_status()
        prs = resp.json()

    if not prs:
        return f"No open pull requests found for {repo}."

    lines = [f"#{pr['number']} {pr['title']} ({pr['html_url']})" for pr in prs]
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run(transport="stdio")
