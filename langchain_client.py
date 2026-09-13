import asyncio
import os
import sys
import warnings

import httpx
from dotenv import load_dotenv

# LLMToolSelectorMiddleware makes its own small model call before every
# question to pick relevant tools, requesting structured output (json_schema).
# gpt-3.5-turbo doesn't support OpenAI's native Structured Outputs API, so
# LangChain harmlessly falls back to method='function_calling' each time —
# but prints this warning on every single turn. Silencing just this specific
# warning (not all warnings) since the fallback works correctly.
warnings.filterwarnings("ignore", message="Cannot use method='json_schema'.*")
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
#from langgraph.prebuilt import create_react_agent
from langchain.agents import create_agent
# SummarizationMiddleware: without this, every new message on the same thread_id
# re-sends the ENTIRE past conversation to the LLM (cost grows the longer a
# session runs). This middleware watches the running token count and, once it
# crosses `trigger`, replaces the older messages with a short LLM-written summary
# — keeping the most recent messages verbatim so short-term context stays sharp.
# LLMToolSelectorMiddleware: with 14 servers now wired in (including GitHub's
# official server, whose schemas alone are huge), sending EVERY tool's schema
# on every call blew past gpt-3.5-turbo's 16,385-token limit outright — not
# just a cost problem anymore, a hard failure. This runs a small pre-step that
# picks only the most relevant tools for the current question before the main
# model call, so the model only ever sees a manageable subset of schemas.
# HumanInTheLoopMiddleware: pauses the agent BEFORE running specific tools and
# waits for your approval — for anything that takes a real-world action (sends
# a message, writes/moves a file) rather than just reading data. Read-only
# tools (weather, search, GitHub reads, etc.) are left fully autonomous.
# ToolRetryMiddleware: the closer match for "adaptation" — if a tool call
# fails with a transient error (network timeout, connection drop), this
# automatically retries with exponential backoff instead of the agent just
# giving up on the first failure. Note: only catches actual raised exceptions
# — it won't retry our own tools' "return an error string" pattern (e.g.
# github_server.py returning "Failed to send message: ..." as a normal
# string), since that's a successful return, not an exception.
from langchain.agents.middleware import (
    HumanInTheLoopMiddleware,
    LLMToolSelectorMiddleware,
    SummarizationMiddleware,
    ToolRetryMiddleware,
)
# Command(resume=...) is how you tell LangGraph "here's the human's decision,
# continue the paused run" — it's what the chat loop sends back after the
# agent pauses partway through a turn waiting for approval.
from langgraph.types import Command
# AsyncSqliteSaver: same idea as MemorySaver (persists conversation state per
# thread_id) but writes to a real file on disk instead of a Python dict, so
# history survives restarts. "Async" because our whole script is async/await
# (ainvoke etc.) — the sync SqliteSaver would block the event loop on disk I/O.
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
# Output guardrails: (1) the filesystem server can read ANY file in this
# project, including .env/credentials.json/token.json — strips anything that
# looks like a real API key/secret out of tool results before the LLM sees
# them; (2) caps any single tool result's size, so a misbehaving tool can't
# blow past the model's rate limit in one turn (see comment at its use below).
from guardrails import OutputGuardrailMiddleware


load_dotenv()  # reads OPENAI_API_KEY (and other secrets) from .env into the environment

# The official GitHub MCP server (run via Docker below) expects its token under
# a different env var name than our own github_server.py used. Rather than
# duplicating the secret value as a second line in .env, alias it here in
# Python — .env stays the single source of truth. setdefault() means if you
# ever DO set GITHUB_PERSONAL_ACCESS_TOKEN explicitly in .env, that wins.
os.environ.setdefault("GITHUB_PERSONAL_ACCESS_TOKEN", os.environ.get("GITHUB_TOKEN", ""))

llm = ChatOpenAI()  # the model that will decide which tool(s) to call, if any

WEATHER_SERVER_PATH = "/Users/rakeshyadav/TCS-AI-Training/Langchain-MCP/mcp-crash-course/servers/weather_server.py"
WEATHER_SERVER_LOG = "/Users/rakeshyadav/TCS-AI-Training/Langchain-MCP/mcp-crash-course/weather_server.log"


async def _weather_server_reachable() -> bool:
    try:
        _, writer = await asyncio.open_connection("127.0.0.1", 8000)
        writer.close()
        await writer.wait_closed()
        return True
    except OSError:
        return False


async def _ensure_weather_server():
    """weather_server.py uses SSE (a standalone service the client connects
    to), unlike every other server here which the client launches itself as a
    subprocess — so historically you had to remember to start it yourself in
    a second terminal first, and forgetting caused a recurring
    httpx.ConnectError. This starts it automatically if nothing's already
    listening on port 8000, and waits until it's actually accepting
    connections before returning. Its own stdout/stderr go to a log file so
    the chat interface stays clean. Returns the subprocess handle so main()
    can shut it down on exit — or None if a server was already running
    externally, in which case we don't own its lifecycle and won't stop it.
    """
    if await _weather_server_reachable():
        print("Weather server already running — using the existing one.\n")
        return None

    print("Starting weather server in the background...")
    log_file = open(WEATHER_SERVER_LOG, "w")
    proc = await asyncio.create_subprocess_exec(
        sys.executable, WEATHER_SERVER_PATH, stdout=log_file, stderr=log_file,
    )
    for _ in range(25):  # up to ~5s for uvicorn to come up
        if await _weather_server_reachable():
            print("Weather server ready.\n")
            return proc
        await asyncio.sleep(0.2)

    raise RuntimeError(f"Weather server did not start in time — check {WEATHER_SERVER_LOG}")


async def main():
    weather_proc = await _ensure_weather_server()

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
            # Official pre-built MCP server, published and maintained by GitHub
            # itself (Docker image, not npx — see ARCHITECTURE.md for why the
            # packaging differs per vendor). Replaces our own github_server.py
            # in the active agent — that file stays in the repo as a reference
            # for how we built one from scratch, just no longer wired in here,
            # to avoid two overlapping GitHub tool sets confusing the LLM.
            "github": {
                "command": "docker",
                "args": [
                    "run", "--rm", "-i",
                    "-e", "GITHUB_PERSONAL_ACCESS_TOKEN",
                    "ghcr.io/github/github-mcp-server",
                    "stdio",
                    # The default toolset (context, copilot, issues, pull_requests,
                    # repos, users) alone costs ~19k tokens of schema — blew past
                    # gpt-3.5-turbo's 16,385-token limit combined with our other
                    # 13 servers. Narrowed to just what we actually use.
                    "--toolsets=issues,pull_requests",
                ],
                "transport": "stdio",
                # IMPORTANT: MCP's stdio_client does NOT inherit the full parent
                # environment by default (a deliberate security default — only a
                # safe allowlist like PATH/HOME is passed through). Our own Python
                # servers worked without this because they call load_dotenv()
                # themselves; this Docker-based one has no such fallback, so we
                # must explicitly hand it the one variable it needs.
                "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": os.environ["GITHUB_PERSONAL_ACCESS_TOKEN"]},
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
            # Official pre-built MCP server (npx package), not one we wrote —
            # gives the agent read/write access to files in this project directory only.
            "filesystem": {
                "command": "npx",
                "args": [
                    "-y",
                    "@modelcontextprotocol/server-filesystem",
                    "/Users/rakeshyadav/TCS-AI-Training/Langchain-MCP/mcp-crash-course",
                ],
                "transport": "stdio",
            },
            # Official pre-built MCP server, published and maintained by Brave
            # itself (not the older @modelcontextprotocol one, which is
            # deprecated) — reads BRAVE_API_KEY from the environment automatically.
            "brave_search": {
                "command": "npx",
                "args": ["-y", "@brave/brave-search-mcp-server"],
                "transport": "stdio",
            },
            "slack": {
                "command": "python",
                "args": [
                    "/Users/rakeshyadav/TCS-AI-Training/Langchain-MCP/mcp-crash-course/servers/slack_server.py"
                ],
                "transport": "stdio",
            },
            # "teams" is PAUSED, not deleted — teams_server.py is fully written
            # and its OAuth token exchange is verified working, but the Azure AD
            # tenant it was registered against has no Microsoft 365/Teams
            # license provisioned, so there's nothing to actually test against
            # yet. Re-add this entry once real Teams access exists.
            # "teams": {
            #     "command": "python",
            #     "args": [
            #         "/Users/rakeshyadav/TCS-AI-Training/Langchain-MCP/mcp-crash-course/servers/teams_server.py"
            #     ],
            #     "transport": "stdio",
            # },
        }
    )

    try:
        await _run_agent(client)
    finally:
        # Only stop the weather server if WE started it — if one was already
        # running externally (someone else's terminal, or a leftover from a
        # prior run), we don't own its lifecycle and leave it alone.
        if weather_proc:
            weather_proc.terminate()
            await weather_proc.wait()
            print("Weather server stopped.")


async def _run_agent(client: MultiServerMCPClient):
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
        # trigger=("tokens", 3000): once the running conversation crosses ~3000 tokens,
        # summarize it. keep=("messages", 10): always leave the last 10 messages
        # untouched (verbatim), so recent back-and-forth doesn't get fuzzed by summarization.
        agent = create_agent(
            llm,
            tools,
            checkpointer=checkpointer,
            middleware=[
                OutputGuardrailMiddleware(),
                # max_retries=2, default backoff — retries transient failures
                # (network blips) up to twice before giving up and reporting
                # the failure to the LLM as normal.
                # retry_on is DELIBERATELY narrow: only real network-transient
                # errors. The default (retry_on=(Exception,)) will happily
                # retry PERMANENT failures too — e.g. a tool returning output
                # that fails its own schema validation (a real bug we hit with
                # Brave's brave_place_search) fails identically every time, so
                # retrying it 3x just multiplies a bad result by 3, not fixes it.
                ToolRetryMiddleware(
                    max_retries=2,
                    retry_on=(httpx.TimeoutException, httpx.ConnectError, ConnectionError, TimeoutError),
                ),
                # Gate every tool that DOES something (vs. just reads/reports)
                # behind approval. `True` = use the default review options
                # (approve/edit/reject/respond) for that tool name.
                HumanInTheLoopMiddleware(
                    interrupt_on={
                        "write_file": True,
                        "edit_file": True,
                        "create_directory": True,
                        "move_file": True,
                        "send_slack_message": True,
                        "send_teams_message": True,
                    }
                ),
                # max_tools=8: only the 8 most relevant tools (of ~20+ across all
                # servers) get sent to the main model per question. Runs its own
                # small LLM call first to pick them — a bit of extra latency,
                # traded for staying under the context limit at all.
                LLMToolSelectorMiddleware(model=llm, max_tools=8),
                SummarizationMiddleware(model=llm, trigger=("tokens", 3000), keep=("messages", 10)),
            ],
        )

        # thread_id is the key the checkpointer uses to look up "which conversation is this?"
        # Same thread_id across calls (even across separate script runs, now that
        # it's on disk) = same remembered history. A different thread_id
        # (e.g. per user, per chat window) would start a completely separate memory.
        config = {"configurable": {"thread_id": "cli-session-1"}}

        print("MCP agent ready (math, weather, github, gmail, maps, search, finance, news, jobs, calendar, filesystem, brave_search, slack). Type 'exit' to quit. [teams paused]\n")
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

            # A single turn failing (e.g. LLMToolSelectorMiddleware's selector
            # model picking a tool name that doesn't actually exist — a real,
            # reproducible failure with a model as weak as gpt-3.5-turbo when
            # choosing among 20+ similarly-named tools) must NOT kill the whole
            # session. Catch it, tell the user, and let them try again.
            try:
                result = await agent.ainvoke({"messages": question}, config=config)

                # If a gated tool (write_file, send_slack_message, etc.) was about
                # to run, the graph pauses here instead of finishing — result will
                # have "__interrupt__" instead of a final answer. Loop until every
                # pending approval is resolved (a turn can pause more than once,
                # e.g. if the agent wants to call two gated tools in sequence).
                while result.get("__interrupt__"):
                    request = result["__interrupt__"][0].value
                    decisions = []
                    for action in request["action_requests"]:
                        print(f"\n[Approval needed] {action['name']} with args: {action['args']}")
                        choice = input("Approve? (y/n): ").strip().lower()
                        if choice == "y":
                            decisions.append({"type": "approve"})
                        else:
                            decisions.append({"type": "reject", "message": "User declined this action."})
                    result = await agent.ainvoke(Command(resume={"decisions": decisions}), config=config)

                print("Agent:", result["messages"][-1].content, "\n")
            except Exception as exc:
                print(f"Agent: Sorry, that turn hit an internal error ({exc}). Try rephrasing the question.\n")


if __name__ == "__main__":
    asyncio.run(main())