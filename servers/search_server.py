# search_server.py
import logging
import os

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()
logging.basicConfig(level=logging.WARNING)

mcp = FastMCP("Search")


@mcp.tool()
async def web_search(query: str, max_results: int = 5) -> str:
    """Search the live web for current information (news, facts, prices, anything beyond the model's training data)."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.tavily.com/search",
            json={
                "api_key": os.getenv("TAVILY_API_KEY"),
                "query": query,
                "max_results": max_results,
            },
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])

    if not results:
        return f"No web results found for: {query}"

    lines = [f"{r['title']} ({r['url']})\n  {r['content'][:200]}" for r in results]
    return "\n\n".join(lines)


if __name__ == "__main__":
    mcp.run(transport="stdio")
