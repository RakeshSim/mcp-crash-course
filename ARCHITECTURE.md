# Architecture

## What this is

A learning project for MCP (Model Context Protocol) that grew into a real personal
assistant: one LangChain agent, backed by an LLM (OpenAI), with tool access to
GitHub, Gmail, Google Maps, Google Calendar, Slack, live web search (two providers),
crypto prices, tech news, job listings, weather, local files, and basic math —
each exposed as its own MCP server, some hand-written, some official/vendor-published.

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
| Used by | everything except weather | weather (the one deliberate example of the other transport) |

`weather_server.py` is the only SSE server. `langchain_client.py` now **auto-starts
it as a background subprocess on launch** (and stops it on exit) if nothing's
already listening on port 8000 — see "Auto-starting the weather server" below. You
no longer need a second terminal for it.

## Two ways to add a tool: build your own, or use an official one

Every capability in this project got added one of two ways — worth knowing both,
since they have different tradeoffs.

**Build your own** (`math_server.py`, `weather_server.py`, `gmail_server.py`,
`calendar_server.py`, `maps_server.py`, `search_server.py`, `finance_server.py`,
`news_server.py`, `jobs_server.py`, `slack_server.py`, `github_server.py`,
`teams_server.py`): write a Python file, `FastMCP("Name")`, wrap each capability in
`@mcp.tool()` with type hints + a docstring, call the real external API yourself
(via `httpx`). Full control over exactly what's exposed and how output is
formatted — but you own maintaining it.

**Use an official one** (filesystem, Brave Search, GitHub — see table below): a
vendor already published and maintains an MCP server for their product. You just
point `MultiServerMCPClient` at their published package/image instead of writing
code — the vendor keeps it updated, and it's usually far more capable than a
hand-rolled version. Tradeoffs: you don't control its output format, its toolset
can be much larger than you need (real problem — see "Lessons learned" below), and
each one packages/distributes itself differently (npm package run via `npx` for
Node-based servers like filesystem/Brave, a Docker image for GitHub's Go-based one
— see its comment in `langchain_client.py` for why).

**When both exist for the same thing** (this happened twice — GitHub and web
search): don't run both in the live agent. Two overlapping tool sets compete for
the LLM's tool-selection attention and just add confusion for no benefit.
- **GitHub**: `github_server.py` (hand-built) is kept in the repo as a reference,
  but retired from the active config — GitHub's official server does everything it
  did and much more.
- **Web search**: kept **both** `search_server.py` (Tavily) and the official Brave
  Search server active on purpose, since they're genuinely different products
  worth comparing, not a strict superset situation like GitHub was.

## Servers

| File / package | Tool(s) | External API | Credential needed | Built by |
|---|---|---|---|---|
| `math_server.py` | `add`, `multiply` | none | none | us |
| `weather_server.py` (SSE) | `get_weather` | Open-Meteo (geocoding + forecast) | none | us |
| **GitHub official** (`ghcr.io/github/github-mcp-server`, Docker) | issues, PRs, repos, code search, and more (`--toolsets=issues,pull_requests` — narrowed, see below) | GitHub REST API | `GITHUB_PERSONAL_ACCESS_TOKEN` (aliased from our own `GITHUB_TOKEN`, see below) | GitHub |
| `github_server.py` *(retired, kept as reference — not in active config)* | `list_open_issues`, `list_open_pull_requests` | GitHub REST API | `GITHUB_TOKEN` | us |
| `gmail_server.py` | `search_emails` | Gmail API | OAuth: `credentials.json` + `token.json` | us |
| `calendar_server.py` | `list_upcoming_events` | Google Calendar API | OAuth: `credentials.json` (shared with Gmail) + `calendar_token.json` (separate scope, separate token) | us |
| `maps_server.py` | `get_directions`, `find_stopovers` | Google Maps (Directions + Places) | `GOOGLE_MAPS_API_KEY` | us |
| `search_server.py` | `web_search` | Tavily | `TAVILY_API_KEY` | us |
| **Brave Search official** (`@brave/brave-search-mcp-server`, npx) | web/image/video/news search | Brave Search API | `BRAVE_API_KEY` | Brave |
| `finance_server.py` | `get_crypto_price` | CoinGecko | none | us |
| `news_server.py` | `top_tech_stories` | Hacker News (Algolia API) | none | us |
| `jobs_server.py` | `search_jobs` | Arbeitnow | none | us |
| **Filesystem official** (`@modelcontextprotocol/server-filesystem`, npx) | `read_file`, `write_file`, `edit_file`, `create_directory`, `move_file`, `list_directory`, `search_files`, etc. | none — local disk only, scoped to this project directory | none | Anthropic/MCP reference |
| `slack_server.py` | `send_slack_message`, `list_recent_slack_messages` | Slack Web API | `SLACK_BOT_TOKEN` | us |
| `teams_server.py` *(written, paused — not in active config)* | `send_teams_message`, `list_recent_teams_messages` | Microsoft Graph API | `TEAMS_TENANT_ID`/`TEAMS_CLIENT_ID`/`TEAMS_CLIENT_SECRET` | us |

**Why GitHub's official server needed extra handling** (both worth knowing if you
add another Docker-based official server later):
1. **Env var name mismatch** — it expects `GITHUB_PERSONAL_ACCESS_TOKEN`, not our
   `GITHUB_TOKEN`. Rather than duplicating the secret as a second line in `.env`,
   `langchain_client.py` aliases it in Python at startup
   (`os.environ.setdefault(...)`), keeping `.env` as the single source of truth.
2. **MCP's `stdio_client` doesn't inherit your full shell environment by default**
   — a deliberate security default (only a safe allowlist like `PATH`/`HOME` passes
   through), so a Docker-launched server can't see `.env` values the way our own
   Python servers can (they call `load_dotenv()` themselves). It has to be handed
   explicitly via the `"env"` key in that server's `MultiServerMCPClient` config.
3. **Toolset size** — the default toolset alone costs ~19k tokens of schema, which
   combined with every other server blew past `gpt-3.5-turbo`'s context limit
   outright. Narrowed via `--toolsets=issues,pull_requests` to just what's used.

**Teams is paused, not broken**: the OAuth client-credentials token exchange in
`teams_server.py` is verified working — the blocker is that the Azure AD tenant it
was registered against has no Microsoft 365/Teams license provisioned
(`Forbidden: Microsoft Teams hasn't been provisioned on the tenant`), and a Microsoft
365 Developer Program sandbox (the usual free fix) wasn't available due to
eligibility rules. Re-enable by uncommenting its block in `langchain_client.py`
once real Teams access exists.

Design note: tools that only differ by a parameter value (e.g. `find_stopovers`'s
`place_type` covering restaurants, hotels, gas stations) are kept as **one**
parameterized tool rather than several near-duplicate ones — the LLM fills in the
parameter from natural language on its own.

## The client: `langchain_client.py`

1. `_ensure_weather_server()` — auto-starts `weather_server.py` as a background
   subprocess if nothing's listening on port 8000 yet, polling until it's actually
   ready. Returns the process handle so it can be stopped again on exit (only if
   *we* started it — an externally-running one is left alone).
2. `MultiServerMCPClient({...})` — describes where every server lives (command+args
   for stdio, url for SSE).
3. `client.get_tools()` — connects to all of them, merges every tool into one flat
   list.
4. `create_agent(llm, tools, checkpointer=..., middleware=[...])` — wires the LLM +
   tools + a middleware stack (see below) into a ReAct-style loop: read the message
   → decide if/which tool(s) to call → call → read result → repeat until there's a
   final answer.
5. A `while True: input()` loop — each line typed is one `agent.ainvoke(...)` call,
   wrapped in `try/except` so one bad turn can't crash the whole session (see
   "Lessons learned"). Also handles the pause/resume cycle for
   `HumanInTheLoopMiddleware` (below).

## The middleware stack

`create_agent`'s `middleware=[...]` list, applied in this order:

1. **`OutputGuardrailMiddleware`** (`guardrails.py`, ours) — two jobs, both running
   on every tool result before the LLM ever sees it:
   - **Secret redaction**: the filesystem server can read *any* file in the
     project, including `.env`/`credentials.json`/`token.json`. Without this, "what's
     in my .env file?" would leak real API keys back through the agent's answer.
     Primary defense is exact-match against this process's own real loaded secret
     values (catches any format, not just ones we guessed a regex for); pattern
     matching is a secondary fallback for secrets *not* in our own `.env`.
   - **Size cap** (8,000 chars per tool result): a safety net against any tool
     returning runaway-sized output — see the `brave_place_search` incident below,
     which is exactly what motivated adding this.
2. **`ToolRetryMiddleware`** — retries a tool call automatically on failure, but
   `retry_on` is **deliberately narrowed** to real network-transient errors
   (`httpx.TimeoutException`, `ConnectError`, `ConnectionError`, `TimeoutError`)
   instead of the default `(Exception,)`. See "Lessons learned" for why a broad
   retry policy is actively dangerous.
3. **`HumanInTheLoopMiddleware`** — pauses the agent before any tool that *does*
   something real (`write_file`, `edit_file`, `create_directory`, `move_file`,
   `send_slack_message`, `send_teams_message`), and waits for your approval.
   Read-only tools stay fully autonomous. Mechanically: the agent graph pauses via
   LangGraph's `interrupt()`, `agent.ainvoke()` returns `result["__interrupt__"]`
   instead of a final answer, and the chat loop shows you the pending action, asks
   `y`/`n`, then resumes with `agent.ainvoke(Command(resume={"decisions": [...]}), ...)`.
4. **`LLMToolSelectorMiddleware`** (`max_tools=8`) — runs a small model call
   *before* the main one, picking only the ~8 most relevant tools (of 20+ across
   all servers) for the current question. Needed once GitHub's official server was
   added — sending every tool's schema on every call blew past the context limit
   outright, not just a cost concern.
5. **`SummarizationMiddleware`** (`trigger=("tokens", 3000)`, `keep=("messages", 10)`)
   — once a thread's history crosses ~3000 tokens, compresses older messages into a
   summary while leaving the last 10 verbatim, so a long-running session's cost
   doesn't grow unbounded.

## Conversation memory: `AsyncSqliteSaver` + `checkpoints.db`

`create_agent`'s `checkpointer` argument persists conversation state so multi-turn
context ("what did I just ask?") works. Started with `MemorySaver` (a Python dict —
lost on restart); now `AsyncSqliteSaver`, writing to a local `checkpoints.db` file,
so history survives restarts. `AsyncSqliteSaver` (not the sync `SqliteSaver`)
because the whole script is `async`/`await`; a sync DB call would block the event
loop.

The checkpointer looks up history by `thread_id` (currently hardcoded to
`"cli-session-1"`) — same `thread_id` across runs = same remembered conversation. A
different `thread_id` would start a completely separate memory (the mechanism a
future multi-user/multi-session frontend would key off of, one `thread_id` per
user/tab).

If this ever needs to run across multiple server processes/replicas, the natural
next swap is `PostgresSaver`/`RedisSaver` — same `checkpointer=` argument, only the
backend changes.

## Lessons learned (real bugs found and fixed, not hypothetical)

**1. Tool-selector hallucination can crash the whole session.**
`LLMToolSelectorMiddleware` uses `gpt-3.5-turbo` (a weak model for this) to pick
relevant tools across 20+ similarly-named options. It occasionally invents a tool
name that doesn't exist (observed: `brave_weather_search`, blending two real tool
names) — the middleware raises an uncaught `ValueError` on that, which used to kill
the entire script. **Fix**: wrapped the per-turn logic in `try/except` in the chat
loop — a bad turn now prints a friendly error and the session keeps running. This
didn't reduce *how often* the model hallucinates (that's inherent to using a weak
model over many tools) — it just stops one bad turn from taking down everything else.

**2. A blind retry policy amplifies permanent failures instead of fixing them.**
Brave's `brave_place_search` tool returned output that failed its own schema
validation — a **permanent** bug, not a transient blip. `ToolRetryMiddleware`'s
default `retry_on=(Exception,)` retried it 3 times anyway (it fails identically
every time), and each ~880,000-character failure message got stored in
conversation history. The next request tried to resend ~665,000 tokens of it and
got rejected by OpenAI's 200,000/min rate limit outright. **Fix**: narrowed
`retry_on` to only real transient exceptions, and added the `OutputGuardrailMiddleware`
size cap as a second, independent safety net so *any* future misbehaving tool
(this one or a new one) can't repeat this regardless of retry policy. Also had to
manually clear the already-poisoned `cli-session-1` thread from `checkpoints.db`
(443 checkpoints, 35MB) since the new guardrails only prevent *future* bloat, not
fix already-stored history.

**3. A weak model resolving ambiguous identity guesses instead of asking.**
"Check the latest code check-in in my repo" — with no explicit owner given — led
the model to invent a GitHub username (`apoorva-sharma`) instead of using GitHub's
own identity-resolution tool or asking for clarification. **Mitigation**: be
explicit (`RakeshSim/mcp-crash-course`) rather than "my repo." No code fix applied
for this one — it's flagged as a concrete case for why a stronger model (e.g.
Claude) would likely handle multi-tool ambiguity more reliably, if reliability
here becomes a priority.

**Common thread across all three**: every one of these traces back to using
`gpt-3.5-turbo` — a cheap, weak model — to do genuinely hard reasoning (pick 1 of
20+ tools, resolve ambiguous identity, retry-or-not judgment) across an
increasingly large tool surface. The fixes made failures *survivable*; they didn't
make the model more reliable. That tradeoff (cost vs. reliability) is a live,
open decision for this project, not a solved one.

## Auto-starting the weather server

Previously required a second terminal running `weather_server.py` before
`langchain_client.py` would work — forgetting this was a repeated, real source of
`httpx.ConnectError` crashes. `_ensure_weather_server()` in `langchain_client.py`
now handles this automatically:
- Checks if something's already listening on `127.0.0.1:8000` — if so, uses it
  (and won't try to stop it later, since it doesn't own that process).
- If not, spawns `weather_server.py` as a background subprocess (its own
  stdout/stderr redirected to `weather_server.log`, keeping the chat interface
  clean), and polls until it's actually accepting connections before proceeding.
- On exit (including normal `exit`/`quit`), stops the subprocess it started.

## Setup

**`.env`** (repo root, git-ignored):
```
OPENAI_API_KEY=...
GITHUB_TOKEN=...          # optional — used by the retired github_server.py; aliased for the official server too
GOOGLE_MAPS_API_KEY=...
TAVILY_API_KEY=...
BRAVE_API_KEY=...
SLACK_BOT_TOKEN=...
# TEAMS_TENANT_ID / TEAMS_CLIENT_ID / TEAMS_CLIENT_SECRET — written but paused, see above
```

**OAuth files** (repo root, git-ignored): `credentials.json` (Google Cloud OAuth
client, shared by Gmail + Calendar), `token.json` (Gmail, created on first login),
`calendar_token.json` (Calendar, created on first login — separate from Gmail's
because it's a different OAuth scope).

Before either Gmail or Calendar will work, the matching API must be enabled in the
same Google Cloud project: **"Gmail API"** and **"Google Calendar API"** specifically
— not "CalDAV API", which is a different, unrelated API that's easy to pick by
mistake in the API Library search.

**Slack bot**: needs `channels:read` + `chat:write` scopes, and must be reinstalled
to the workspace after adding scopes. `send_slack_message` auto-joins the target
public channel before posting, so no manual `/invite` is needed per channel.

**Docker**: needed for GitHub's official server (`docker pull ghcr.io/github/github-mcp-server`).
An old Docker version (tested against 20.10.5, a 2021 build) still worked fine.

**Node/npx**: needed for the filesystem, Brave Search official servers — no
separate install step, `npx -y <package>` fetches and runs them on demand.

**Running it**:
```bash
uv run python langchain_client.py
```
One command — the weather server starts itself automatically now. (If you want it
running independently for direct testing, `uv run python servers/weather_server.py`
in a separate terminal still works exactly as before; the client will detect and
reuse it instead of starting a second one.)

## Not yet built (next direction)

A "product" version — FastAPI backend (wrapping this same agent-building logic
behind a `/chat` endpoint, one `thread_id` per browser session instead of the
hardcoded one), an Angular chat frontend, and a scheduled daily digest (GitHub
issues + job listings, posted to Slack via `launchd`, independent of whether the
web app is running). Scoped as a separate plan when picked back up.
