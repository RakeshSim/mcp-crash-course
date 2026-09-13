 uv init
 uv venv
 uv sync
 uv add langchain-mcp-adapters langgraph langchain-openai
  uv python-dotenv
  uv run main.py
  (mcp-crash-course) (base) rakeshyadav@Rakeshs-MacBook-Pro mcp-crash-course % git add .
(mcp-crash-course) (base) rakeshyadav@Rakeshs-MacBook-Pro mcp-crash-course % git status
(mcp-crash-course) (base) rakeshyadav@Rakeshs-MacBook-Pro mcp-crash-course % git remote set-url origin https://github.com/RakeshSim/mcp-crash-course.git
(mcp-crash-course) (base) rakeshyadav@Rakeshs-MacBook-Pro mcp-crash-course % git remote -v
origin  https://github.com/RakeshSim/mcp-crash-course.git (fetch)
origin  https://github.com/RakeshSim/mcp-crash-course.git (push)
(mcp-crash-course) (base) rakeshyadav@Rakeshs-MacBook-Pro mcp-crash-course % git branch -M main
(mcp-crash-course) (base) rakeshyadav@Rakeshs-MacBook-Pro mcp-crash-course % git add .
(mcp-crash-course) (base) rakeshyadav@Rakeshs-MacBook-Pro mcp-crash-course % git status
(mcp-crash-course) (base) rakeshyadav@Rakeshs-MacBook-Pro mcp-crash-course % git push -u origin main

Running the agent:

uv run python langchain_client.py
Then type at the You: prompt — exit to quit.

That's now the only command needed — langchain_client.py auto-starts the weather
server itself in the background (and stops it again on exit) if nothing's already
listening on port 8000. No second terminal required anymore.

If you want the weather server running independently (e.g. for direct testing via
MCP Inspector or curl), you can still start it yourself in a separate terminal —
the client detects it's already running and reuses it instead of starting a
duplicate:

uv run python servers/weather_server.py — runs the actual server, exactly as written (mcp.run(transport="sse")).

uv run mcp dev servers/weather_server.py — wraps the server in the MCP Inspector, a browser-based debugging UI (opens a local web page) where you manually pick a tool, type in arguments, and see the raw request/response — no LLM involved at all. Use this only while building/debugging a new tool, to sanity-check its schema and output before wiring it into the agent.

See ARCHITECTURE.md for the full picture — all servers, the middleware/guardrail stack, and real bugs found and fixed along the way.