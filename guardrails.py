# guardrails.py
import os
import re

from dotenv import load_dotenv
from langchain.agents.middleware import AgentMiddleware

# Load .env ourselves rather than relying on the importer having already
# called load_dotenv() first — if this module read os.environ before .env
# was loaded, _REAL_SECRET_VALUES below would end up empty and silently
# redact nothing. python-dotenv's load_dotenv() is safe to call more than
# once (idempotent), same pattern every server file in this project uses.
load_dotenv()

# Primary defense: exact-match on the REAL secret values already loaded into
# this process's environment (from .env). This catches every credential
# regardless of its format/prefix — unlike guessing regex patterns, it
# doesn't need to know what an OpenAI key vs. a Pinecone key looks like.
# Only env vars whose NAME suggests a secret are included, and only values
# long enough that matching them can't false-positive on ordinary text.
_SECRET_NAME_HINTS = ("KEY", "TOKEN", "SECRET", "PASSWORD")
_REAL_SECRET_VALUES = [
    v for k, v in os.environ.items()
    if any(hint in k.upper() for hint in _SECRET_NAME_HINTS) and len(v) >= 12
]

# Regex patterns for common secret/API-key formats used by THIS project's own
# credentials (OpenAI, GitHub, Slack, Google) — not an exhaustive secret
# scanner, just covers what could realistically leak if a tool (like the
# filesystem server) reads .env / credentials.json / token.json.
_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),          # OpenAI
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),      # GitHub tokens (ghp_, gho_, ghu_, ghs_, ghr_)
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),    # GitHub fine-grained PAT
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),    # Slack tokens
    re.compile(r"AIza[A-Za-z0-9_-]{30,}"),          # Google API key
    re.compile(r"GOCSPX-[A-Za-z0-9_-]{20,}"),       # Google OAuth client secret
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
]

_REDACTED = "[REDACTED — looked like an API key/secret]"

# Safety net against any tool (buggy or not) returning runaway-sized output.
# Real incident that motivated this: Brave's brave_place_search tool returned
# a response that failed its own schema validation, ToolRetryMiddleware
# retried it 3 times, and each ~880,000-CHARACTER failure message got stored
# in conversation history — one turn alone hit ~665,000 tokens and blew past
# OpenAI's 200,000 TPM rate limit outright. This caps any single tool result
# well before it could ever get close to that.
_MAX_TOOL_OUTPUT_CHARS = 8000


class OutputGuardrailMiddleware(AgentMiddleware):
    """Output guardrails: scans every tool result BEFORE the LLM (and
    therefore the user) ever sees it, and applies two independent checks:

    1. Secret redaction — the filesystem server can read ANY file in the
       project, including .env/credentials.json/token.json. Without this, a
       question like "what's in my .env file?" would leak real API keys back
       through the agent's answer.
    2. Size cap — a misbehaving tool (third-party or our own) can return
       enormous output. Without a cap, one bad tool result can single-handedly
       blow past the model's rate limit in a single turn (see above).

    Both run via wrap_tool_call/awrap_tool_call, which intercepts every tool's
    raw result before it becomes part of the conversation the LLM reasons over.
    """

    async def awrap_tool_call(self, request, handler):
        result = await handler(request)
        return self._process(result)

    def wrap_tool_call(self, request, handler):
        result = handler(request)
        return self._process(result)

    def _scrub(self, text: str) -> str:
        # 1. Exact-match against this process's own real secret values —
        #    catches anything from .env regardless of its format.
        for value in _REAL_SECRET_VALUES:
            if value in text:
                text = text.replace(value, _REDACTED)
        # 2. Pattern-based fallback — catches secret-*shaped* strings that
        #    AREN'T in this process's own .env (e.g. a key belonging to
        #    someone else that shows up in a file/email/search result).
        for pattern in _SECRET_PATTERNS:
            text = pattern.sub(_REDACTED, text)
        # 3. Cap the size, after redaction (so we don't cut a secret in half
        #    and leave a partial one dangling in the truncated output).
        if len(text) > _MAX_TOOL_OUTPUT_CHARS:
            original_len = len(text)
            text = (
                text[:_MAX_TOOL_OUTPUT_CHARS]
                + f"\n...[TRUNCATED — tool output was {original_len:,} chars, capped at {_MAX_TOOL_OUTPUT_CHARS:,}]"
            )
        return text

    def _process(self, result):
        content = getattr(result, "content", None)

        if isinstance(content, str):
            result.content = self._scrub(content)

        elif isinstance(content, list):
            # MCP tool results commonly come through as a list of content
            # blocks (e.g. [{"type": "text", "text": "..."}]) rather than a
            # plain string — scrub the "text" field of each block.
            for block in content:
                if isinstance(block, dict) and isinstance(block.get("text"), str):
                    block["text"] = self._scrub(block["text"])

        return result
