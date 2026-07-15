# jobs_server.py
import logging

import httpx
from mcp.server.fastmcp import FastMCP

logging.basicConfig(level=logging.WARNING)

mcp = FastMCP("Jobs")


@mcp.tool()
async def search_jobs(keyword: str, limit: int = 5) -> str:
    """Search remote-friendly job listings by keyword (e.g. 'python', 'aws architect')."""
    async with httpx.AsyncClient() as client:
        resp = await client.get("https://www.arbeitnow.com/api/job-board-api")
        resp.raise_for_status()
        jobs = resp.json().get("data", [])

    keyword_lower = keyword.lower()
    matches = [j for j in jobs if keyword_lower in j.get("title", "").lower()][:limit]

    if not matches:
        return f"No jobs found matching '{keyword}'."

    lines = [
        f"{j['title']} at {j['company_name']} ({j.get('location', 'remote')}) - {j['url']}"
        for j in matches
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run(transport="stdio")
