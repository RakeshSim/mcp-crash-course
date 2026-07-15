import asyncio

from dotenv import load_dotenv
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
#from langgraph.prebuilt import create_react_agent
from langchain.agents import create_agent
# AsyncSqliteSaver: same idea as MemorySaver (persists conversation state per
# thread_id) but writes to a real file on disk instead of a Python dict, so
# history survives restarts. "Async" because our whole script is async/await
# (ainvoke etc.) — the sync SqliteSaver would block the event loop on disk I/O.
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver


load_dotenv()  # reads OPENAI_API_KEY (and other secrets) from .env into the environment

llm = ChatOpenAI()  # the model that will decide which tool(s) to call, if any


async def main():
    # MultiServerMCPClient describes WHERE each MCP server lives and HOW to reach it.
    # "stdio" servers get launched as subprocesses by this client automatically.
    # "sse" servers must already be running elsewhere; this client just connects to the URL.
    client = MultiServerMCPClient(
        {
            "math": {
                "command": "python",
                "args": [
                    "/Users/rakeshyadav/TCS-AI-Training/Langchain-MCP/mcp-crash-course/servers/math_server.py"
                ],
                "transport": "stdio", # <-- Added this missing key
            },
            "weather": {
                "url": "http://localhost:8000/sse",  # must be started manually: uv run python servers/weather_server.py
                "transport": "sse",
            },
            "github": {
                "command": "python",
                "args": [
                    "/Users/rakeshyadav/TCS-AI-Training/Langchain-MCP/mcp-crash-course/servers/github_server.py"
                ],
                "transport": "stdio",
            },
            "gmail": {
                "command": "python",
                "args": [
                    "/Users/rakeshyadav/TCS-AI-Training/Langchain-MCP/mcp-crash-course/servers/gmail_server.py"
                ],
                "transport": "stdio",
            },
            "maps": {
                "command": "python",
                "args": [
                    "/Users/rakeshyadav/TCS-AI-Training/Langchain-MCP/mcp-crash-course/servers/maps_server.py"
                ],
                "transport": "stdio",
            },
            "search": {
                "command": "python",
                "args": [
                    "/Users/rakeshyadav/TCS-AI-Training/Langchain-MCP/mcp-crash-course/servers/search_server.py"
                ],
                "transport": "stdio",
            },
            "finance": {
                "command": "python",
                "args": [
                    "/Users/rakeshyadav/TCS-AI-Training/Langchain-MCP/mcp-crash-course/servers/finance_server.py"
                ],
                "transport": "stdio",
            },
            "news": {
                "command": "python",
                "args": [
                    "/Users/rakeshyadav/TCS-AI-Training/Langchain-MCP/mcp-crash-course/servers/news_server.py"
                ],
                "transport": "stdio",
            },
            "jobs": {
                "command": "python",
                "args": [
                    "/Users/rakeshyadav/TCS-AI-Training/Langchain-MCP/mcp-crash-course/servers/jobs_server.py"
                ],
                "transport": "stdio",
            },
            "calendar": {
                "command": "python",
                "args": [
                    "/Users/rakeshyadav/TCS-AI-Training/Langchain-MCP/mcp-crash-course/servers/calendar_server.py"
                ],
                "transport": "stdio",
            },
            "slack": {
                "command": "python",
                "args": [
                    "/Users/rakeshyadav/TCS-AI-Training/Langchain-MCP/mcp-crash-course/servers/slack_server.py"
                ],
                "transport": "stdio",
            },
        }
    )

    # Connects to every server above, asks each "what tools do you have?", and
    # returns them all merged into one flat list of LangChain-compatible tools.
    tools = await client.get_tools()

    # AsyncSqliteSaver.from_conn_string opens (or creates, if missing) a local
    # file "checkpoints.db" and manages that connection for as long as we're
    # inside this `async with` block. Everything that needs persistence
    # (agent creation + the whole chat loop) has to live inside this block —
    # once we exit it, the connection closes.
    async with AsyncSqliteSaver.from_conn_string("checkpoints.db") as checkpointer:
        # create_agent wires the LLM + tool list into a ReAct-style loop:
        # the model reads the user's message, decides whether a tool is needed,
        # calls it if so, reads the tool's result, and repeats until it has a final answer.
        agent = create_agent(llm, tools, checkpointer=checkpointer)

        # thread_id is the key the checkpointer uses to look up "which conversation is this?"
        # Same thread_id across calls (even across separate script runs, now that
        # it's on disk) = same remembered history. A different thread_id
        # (e.g. per user, per chat window) would start a completely separate memory.
        config = {"configurable": {"thread_id": "cli-session-1"}}

        print("MCP agent ready (math, weather, github, gmail, maps, search, finance, news, jobs, calendar, slack). Type 'exit' to quit.\n")
        print("Conversation history now persists in checkpoints.db across restarts.\n")

        # We never manually build up a messages list ourselves — the checkpointer
        # does that internally. We only ever send the NEW question; the agent
        # automatically loads prior turns for this thread_id before responding.
        while True:
            question = input("You: ").strip()
            if question.lower() in ("exit", "quit"):
                break
            if not question:
                continue

            result = await agent.ainvoke({"messages": question}, config=config)
            print("Agent:", result["messages"][-1].content, "\n")


if __name__ == "__main__":
    asyncio.run(main())