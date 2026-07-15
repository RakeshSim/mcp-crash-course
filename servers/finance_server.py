# finance_server.py
import logging

import httpx
from mcp.server.fastmcp import FastMCP

logging.basicConfig(level=logging.WARNING)

mcp = FastMCP("Finance")


@mcp.tool()
async def get_crypto_price(coin_ids: str, vs_currency: str = "usd") -> str:
    """Get current crypto prices. coin_ids is comma-separated CoinGecko ids, e.g. 'bitcoin,ethereum,solana'."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": coin_ids, "vs_currencies": vs_currency},
        )
        resp.raise_for_status()
        prices = resp.json()

    if not prices:
        return f"No prices found for: {coin_ids}"

    lines = [f"{coin}: {data.get(vs_currency)} {vs_currency.upper()}" for coin, data in prices.items()]
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run(transport="stdio")
