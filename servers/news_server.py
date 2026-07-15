# news_server.py
import logging

import httpx
from mcp.server.fastmcp import FastMCP

logging.basicConfig(level=logging.WARNING)

mcp = FastMCP("News")


@mcp.tool()
async def top_tech_stories(limit: int = 5) -> str:
    """Get today's top tech/programming news stories from Hacker News' front page."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://hn.algolia.com/api/v1/search",
            params={"tags": "front_page", "hitsPerPage": limit},
        )
        resp.raise_for_status()
        hits = resp.json().get("hits", [])

    if not hits:
        return "No stories found."

    lines = [
        f"{h['title']} ({h.get('points', 0)} points, {h.get('num_comments', 0)} comments) - {h.get('url', 'https://news.ycombinator.com/item?id=' + h['objectID'])}"
        for h in hits
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run(transport="stdio")
