# math_server.py
import logging

from mcp.server.fastmcp import FastMCP

logging.basicConfig(level=logging.WARNING)  # silence MCP's per-request INFO logs

mcp = FastMCP("Math")

@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two numbers"""
    return a + b

@mcp.tool()
def multiply(a: int, b: int) -> int:
    """Multiply two numbers"""
    return a * b

if __name__ == "__main__":
    mcp.run(transport="stdio")