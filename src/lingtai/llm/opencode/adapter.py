"""OpenCode adapter — OpenAI-compatible client for a local ``opencode serve`` endpoint.

OpenCode (github.com/sst/opencode) is an open-source, Go-based coding agent CLI
that runs locally and supports 75+ LLM providers through Models.dev. Its
headless server (``opencode serve``) exposes an OpenAI-compatible API on
``http://127.0.0.1:4050`` by default:

    POST /v1/chat/completions   (OpenAI-compatible)
    POST /v1/responses          (Responses API)
    GET  /v1/models

Models are addressed as ``provider/model`` (e.g. ``anthropic/claude-sonnet-4-5``
or ``openai/gpt-5.5``); the server resolves the provider prefix and
authenticates through the CLI's own credential store
(``~/.local/share/opencode/auth.json``, environment variables, or a project
``.env``) — LingTai never handles an OpenCode API key.

This adapter is a thin subclass of OpenAIAdapter pinned to the local serve
endpoint:

* default ``base_url`` is ``http://127.0.0.1:4050/v1``;
* a non-empty placeholder ``api_key`` satisfies the OpenAI SDK (the serve
  endpoint is localhost and ignores it unless ``OPENCODE_SERVER_PASSWORD``
  auth is configured);
* the Chat Completions wire is the default (the broadest-compat surface of the
  opencode server); ``wire_api`` / legacy ``use_responses`` still opt into the
  Responses wire like the rest of the OpenAI-compatible family;
* ``prompt_cache_key`` is disabled by default — opencode proxies to arbitrary
  upstream providers and has no shared prompt cache of its own, so sending the
  extra field is pointless; an explicit value re-enables it.

Everything else (session management, tool calls, thinking-block replay,
context-overflow auto-recovery) inherits from OpenAIAdapter unchanged.
"""

from __future__ import annotations

from ..openai.adapter import OpenAIAdapter

# Default ``opencode serve`` endpoint. The server listens on 127.0.0.1:4050 by
# default; the OpenAI-compatible routes live under /v1.
_OPENCODE_SERVE_DEFAULT_URL = "http://127.0.0.1:4050/v1"

# OpenCode authenticates providers inside its own CLI. The OpenAI SDK still
# requires a non-empty api_key value, so we send a localhost placeholder that
# the serve endpoint ignores. Never forwarded off-machine.
_OPENCODE_PLACEHOLDER_API_KEY = "opencode-local"


class OpenCodeAdapter(OpenAIAdapter):
    """OpenAI-compat adapter pinned to a local ``opencode serve`` endpoint."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        timeout_ms: int = 300_000,
        max_rpm: int = 0,
        default_headers: dict | None = None,
        wire_api: str | None = "chat_completions",
        use_responses: bool | None = None,
        force_responses: bool | None = None,
        compact_threshold: int | None = None,
        responses_stateless_replay: bool = True,
        prompt_cache_key: str | bool = False,
    ):
        kwargs: dict = {}
        if wire_api is not None:
            kwargs["wire_api"] = wire_api
        if use_responses is not None:
            kwargs["use_responses"] = use_responses
        if force_responses is not None:
            kwargs["force_responses"] = force_responses
        kwargs["compact_threshold"] = compact_threshold
        kwargs["responses_stateless_replay"] = responses_stateless_replay
        super().__init__(
            api_key=api_key or _OPENCODE_PLACEHOLDER_API_KEY,
            base_url=base_url or _OPENCODE_SERVE_DEFAULT_URL,
            timeout_ms=timeout_ms,
            max_rpm=max_rpm,
            default_headers=default_headers,
            prompt_cache_key=prompt_cache_key,
            **kwargs,
        )

    def _default_prompt_cache_key(self, model: str) -> str:
        # Fixed provider identity — clean ``lingtai-opencode`` namespace instead
        # of the localhost base_url host. Only used when a caller explicitly
        # enables prompt_cache_key (the constructor default disables it).
        return f"lingtai-opencode:{model}:v1"
