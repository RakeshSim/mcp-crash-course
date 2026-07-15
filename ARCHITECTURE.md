# Architecture

## What this is

A learning project for MCP (Model Context Protocol) that grew into a real personal
assistant: one LangChain agent, backed by an LLM (OpenAI), with tool access to
GitHub, Gmail, Google Maps, Google Calendar, Slack, live web search, crypto prices,
tech news, job listings, weather, and basic math — each exposed as its own small
MCP server.

## Core idea: servers expose tools, one client/agent consumes all of them

```
Your function (typed, docstring)  →  @mcp.tool()  →  MCP server  →  transport (stdio/SSE)
                                                                            ↓
                                                     MultiServerMCPClient.get_tools()
                                                                            ↓
                                                       create_agent(llm, tools)  →  LLM decides when to call them
```

The LLM never sees your Python code — it sees a tool name, a description (from the
docstring), and a schema (from the type hints), and decides on its own whether/when
to call it based on the user's natural-language message.

## Transports: stdio vs SSE

Two ways a client can talk to an MCP server — this is about the **client↔server**
connection, not about what the server itself does internally (a stdio server can
still make HTTP calls to an external API, e.g. GitHub).

| | stdio | SSE (network) |
|---|---|---|
| Who starts the server | The client launches it as a subprocess | Runs standalone; client connects to a URL |
| Lifetime | Dies when the client exits | Keeps running independently |
| Shareable across clients | No — one subprocess per client | Yes — many clients can connect to the same running server |
| Used by | math, github, gmail, maps, search, finance, news, jobs, calendar, slack | weather (the one deliberate example of the other transport) |

Every server in this project is stdio **except** `weather_server.py`, which uses SSE
purely as the worked example of "a shared, independently-running service." Before
running `langchain_client.py`, `weather_server.py` must be started separately:

```bash
uv run python servers/weather_server.py
```

## Servers

| File | Tool(s) | External API | Credential needed |
|---|---|---|---|
| `math_server.py` | `add`, `multiply` | none | none |
| `weather_server.py` (SSE) | `get_weather` | Open-Meteo (geocoding + forecast) | none |
| `github_server.py` | `list_open_issues`, `list_open_pull_requests` | GitHub REST API | `GITHUB_TOKEN` (optional — works unauthenticated at a lower rate limit) |
| `gmail_server.py` | `search_emails` | Gmail API | OAuth: `credentials.json` + `token.json` |
| `calendar_server.py` | `list_upcoming_events` | Google Calendar API | OAuth: `credentials.json` (shared with Gmail) + `calendar_token.json` (separate scope, separate token) |
| `maps_server.py` | `get_directions`, `find_stopovers` | Google Maps (Directions + Places) | `GOOGLE_MAPS_API_KEY` |
| `search_server.py` | `web_search` | Tavily | `TAVILY_API_KEY` |
| `finance_server.py` | `get_crypto_price` | CoinGecko | none |
| `news_server.py` | `top_tech_stories` | Hacker News (Algolia API) | none |
| `jobs_server.py` | `search_jobs` | Arbeitnow | none |
| `slack_server.py` | `send_slack_message`, `list_recent_slack_messages` | Slack Web API | `SLACK_BOT_TOKEN` |

Design note: tools that only differ by a parameter value (e.g. `find_stopovers`'s
`place_type` covering restaurants, hotels, gas stations) are kept as **one**
parameterized tool rather than several near-duplicate ones — the LLM fills in the
parameter from natural language on its own.

## The client: `langchain_client.py`

1. `MultiServerMCPClient({...})` — describes where every server lives (command+args
   for stdio, url for SSE).
2. `client.get_tools()` — connects to all of them, merges every tool into one flat
   list.
3. `create_agent(llm, tools, checkpointer=...)` — wires the LLM + tools into a
   ReAct-style loop: read the message → decide if/which tool(s) to call → call →
   read result → repeat until there's a final answer.
4. A `while True: input()` loop — each line typed is one `agent.ainvoke(...)` call;
   the agent decides fresh, per message, which tool(s) (if any) it needs.

## Conversation memory: `AsyncSqliteSaver` + `checkpoints.db`

`create_agent`'s `checkpointer` argument persists conversation state so multi-turn
context ("what did I just ask?") works. Started with `MemorySaver` (a Python dict —
lost on restart); since this needs to survive across separate script runs (and this
is a single-user project, not yet a multi-server deployment), it's now
`AsyncSqliteSaver`, writing to a local `checkpoints.db` file. `AsyncSqliteSaver` was
used instead of the sync `SqliteSaver` because the whole script is `async`/`await`;
a sync DB call would block the event loop.

The checkpointer looks up history by `thread_id` (currently hardcoded to
`"cli-session-1"` in `langchain_client.py`) — same `thread_id` across runs = same
remembered conversation. A different `thread_id` would start a completely separate
memory (this is the mechanism a future multi-user/multi-session frontend would key
off of, one `thread_id` per user/tab).

If this ever needs to run across multiple server processes/replicas, the natural
next swap is `PostgresSaver`/`RedisSaver` — same `checkpointer=` argument, only the
backend changes.

## Setup

**`.env`** (repo root, git-ignored):
```
OPENAI_API_KEY=...
GITHUB_TOKEN=...          # optional
GOOGLE_MAPS_API_KEY=...
TAVILY_API_KEY=...
SLACK_BOT_TOKEN=...
```

**OAuth files** (repo root, git-ignored): `credentials.json` (Google Cloud OAuth
client, shared by Gmail + Calendar), `token.json` (Gmail, created on first login),
`calendar_token.json` (Calendar, created on first login — separate from Gmail's
because it's a different OAuth scope).

**Slack bot**: needs `channels:read` + `chat:write` scopes, and must be reinstalled
to the workspace after adding scopes. `send_slack_message` auto-joins the target
public channel before posting, so no manual `/invite` is needed per channel.

**Running it**:
```bash
# terminal 1 — the one SSE server, must be started first
uv run python servers/weather_server.py

# terminal 2 — the agent
uv run python langchain_client.py
```

## Not yet built (next direction)

A "product" version — FastAPI backend (wrapping this same agent-building logic
behind a `/chat` endpoint, one `thread_id` per browser session instead of the
hardcoded one), an Angular chat frontend, and a scheduled daily digest (GitHub
issues + job listings, posted to Slack via `launchd`, independent of whether the
web app is running). Scoped as a separate plan when picked back up.
