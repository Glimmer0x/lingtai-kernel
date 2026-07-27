"""Vision capability — image understanding via VisionService.

Adds the ability to analyze images. Requires a VisionService instance,
created either explicitly or via the ``provider``/``api_key`` factory.

Usage:
    agent.add_capability("vision", vision_service=my_svc)
    agent.add_capability("vision", provider="anthropic", api_key="sk-...")

The local mlx-vlm pseudo-provider remains available through explicit
``add_capability(..., provider="local")`` opt-in, but it is intentionally not
advertised in ``PROVIDERS`` or first-run/check-caps surfaces yet.

``vision`` is migrated to the LingTai Tool Protocol v2 action-separated shape
(``src/lingtai/tools/CONTRACT.md``): one public ``vision`` tool whose canonical
children are ``analyze`` and the family-owned reserved ``manual``, composed and
dispatched by the generic ``lingtai.tools.tool_family`` infrastructure. The
public tool name and both action values are unchanged; only the call envelope
moved from flat arguments to ``action``/``input``/``reasoning``/``summarize``.
Provider routing, credential/identity resolution, and every analyze/manual
result shape are untouched by that migration.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping

from ..tool_family import ChildTool, ToolFamily
from ..tool_family.manual import MANUAL_INPUT_SCHEMA, build_manual_child


if TYPE_CHECKING:
    from lingtai.kernel.base_agent import BaseAgent
    from lingtai.services.vision import VisionService


def _setup_failure(provider: str, exc: BaseException) -> str:
    """Build explicit manual guidance without exposing exception contents."""
    return (
        f"Direct vision setup failed for provider {provider!r} "
        f"({type(exc).__name__}); use vision(action='manual', input={{}}, "
        f"reasoning='direct vision setup failed, load the manual route')."
    )


_CODEX_POOL_ALIASES = {"codex-pool", "codex_pool"}
_CODEX_FAMILY = {"codex"} | _CODEX_POOL_ALIASES


def _same_codex_family(requested: str, active: str) -> bool:
    """Return whether both names are Codex-family spellings.

    Provider spelling is only a Codex-family *compatibility gate*: ``codex``,
    ``codex-pool``, and ``codex_pool`` all resolve to the one native Codex
    factory (see ``lingtai/llm/_register.py``). Spelling never selects the
    fixed/direct vs weighted/pool route; that choice is made solely from the
    active provider-default bucket (``_codex_bucket_route``).
    """
    return requested in _CODEX_FAMILY and active in _CODEX_FAMILY


def _normalize_codex_auth_path(raw: object) -> str | None:
    """Return a trimmed nonblank Codex auth path, or ``None``.

    Mirrors the canonical Codex factory (``lingtai/llm/_register.py`` ``_codex``),
    which strips ``codex_auth_path`` before constructing ``FixedAccountSource``.
    The single trimmed value is used both to decide the direct route and as the
    propagated ``token_path``, so a space-padded path never routes direct while
    forwarding an invalid, un-normalized value.
    """
    if isinstance(raw, str):
        trimmed = raw.strip()
        if trimmed:
            return trimmed
    return None


def _codex_bucket_route(bucket: dict | None) -> str:
    """Resolve the active Codex route from the provider-default bucket.

    Mirrors the canonical Codex factory: the route is ``"direct"`` iff the
    active bucket carries a nonblank ``codex_auth_path`` (trimmed; Fixed
    account); otherwise it is ``"pool"`` (Weighted account selection). The
    request spelling is irrelevant — an active ``codex-pool`` service that
    configures a ``codex_auth_path`` is a direct/Fixed route, exactly as the
    factory treats it.
    """
    if isinstance(bucket, dict) and _normalize_codex_auth_path(bucket.get("codex_auth_path")):
        return "direct"
    return "pool"


def _same_provider_identity(requested: str, active: str) -> bool:
    """Return whether two provider names identify the same current route."""
    if requested == active:
        return True
    if {requested, active} <= {"glm", "zhipu"}:
        return True
    return _same_codex_family(requested, active)


def _effective_openai_wire(
    wire_api: str | None,
    *,
    use_responses_api: bool,
    base_url: str | None,
) -> str | None:
    """Resolve a supported canonical wire; reject unknown protocols."""
    normalized = wire_api.strip().lower() if isinstance(wire_api, str) else wire_api
    if isinstance(normalized, str):
        if normalized in {"chat_completions", "responses"}:
            return normalized
        if normalized in {"", "auto"}:
            return "responses" if use_responses_api and not base_url else "chat_completions"
    elif normalized is None:
        return "responses" if use_responses_api and not base_url else "chat_completions"
    return None


PROVIDERS = {
    "providers": [
        "gemini", "anthropic", "openai", "openrouter", "custom", "deepseek",
        "minimax", "mimo", "glm", "zhipu", "grok", "qwen", "kimi",
        "codex", "codex-pool", "codex_pool", "claude-code", "claude_code",
    ],
    "default": None,
    "fallback_on_inherit": None,  # no agnostic fallback for vision
}

_ANALYZE_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "image_path": {
            "type": "string",
            "description": "Path to the image file",
        },
        "question": {
            # Strict OpenAI object branches express an optional field as a
            # required nullable property. Null means absent, and the analyze
            # handler then applies the same default prompt it always has.
            "type": ["string", "null"],
            "description": (
                "Question about the image, or null for the default "
                "\"Describe what you see in this image.\""
            ),
        },
    },
    "required": ["image_path", "question"],
    "additionalProperties": False,
}

def _unused(_input: Mapping[str, Any]) -> dict[str, Any]:
    raise AssertionError("the module-level schema-only ToolFamily never dispatches")


def _build_family(
    analyze_handler: Any = _unused,
    manual_child: ChildTool | None = None,
) -> ToolFamily:
    """Build vision's family from the one canonical child declaration.

    The single source of truth for vision's children: both the module-level
    schema-only family (which composes the model-facing schema and proves at
    import time that the registry has no duplicate or reserved-name collision)
    and each ``VisionManager``'s dispatching family come from here, so child
    names, schemas, titles, and order cannot drift between the wire surface
    and the dispatcher. Defaults build the non-dispatching variant; the
    manager passes its bound ``analyze`` handler and the real reserved
    ``manual`` child from ``build_manual_child``.
    """
    return ToolFamily(
        "vision",
        [
            ChildTool("analyze", _ANALYZE_INPUT_SCHEMA, analyze_handler, title="analyze input"),
            manual_child
            or ChildTool("manual", MANUAL_INPUT_SCHEMA, _unused, title="manual input"),
        ],
    )


_FAMILY = _build_family()


def get_description(lang: str = "en") -> str:
    return (
        "Analyze an image with the active preset. Use vision(action='analyze', "
        "input={'image_path': '...', 'question': null}, reasoning='read the "
        "image') for the direct request; OpenRouter/custom first try the "
        "current OpenAI-compatible route. A real request failure returns a "
        "sanitized error and points to vision(action='manual', input={}, "
        "reasoning='load vision guidance') for read-only alternatives. "
        "No provider, model, credential, or MCP fallback is automatic."
    )


def get_schema(lang: str = "en") -> dict:
    # Composed by the generic ToolFamily infra from ``_build_family``'s child
    # declaration, never hand-assembled.
    return _FAMILY.build_schema()


class VisionManager:
    """Handles vision tool calls via a VisionService."""

    def __init__(
        self,
        agent: "BaseAgent",
        vision_service: VisionService | None,
        manual_reason: str = "",
    ) -> None:
        self._agent = agent
        self._vision_service = vision_service
        self._manual_reason = manual_reason
        # Same canonical child declaration the module-level schema-only family
        # uses, with this instance's bound analyze handler and the real
        # reserved ``manual`` child registered directly (unwrapped).
        self._family = _build_family(
            self._dispatch_analyze, build_manual_child(agent, "vision")
        )

    def _dispatch_analyze(self, action_input: Mapping[str, Any]) -> dict[str, Any]:
        """Run the one direct analyze operation on already-validated input.

        The body is the pre-migration ``handle()`` analyze path unchanged:
        same missing-service guard, relative-path resolution, existence check,
        default prompt, and success/failure result shapes.
        """
        if self._vision_service is None:
            return {
                "status": "error",
                "message": self._manual_reason or (
                    "Direct vision is unavailable; call vision(action='manual', "
                    "input={}, reasoning='no direct vision route, load the "
                    "manual alternatives')."
                ),
            }
        image_path = action_input.get("image_path") or ""
        question = action_input.get("question")
        if question is None:
            question = "Describe what you see in this image."

        if not image_path:
            return {"status": "error", "message": "Provide image_path"}

        path = Path(image_path)
        if not path.is_absolute():
            path = self._agent._working_dir / path

        if not path.is_file():
            return {"status": "error", "message": f"Image file not found: {path}"}

        try:
            analysis = self._vision_service.analyze_image(str(path), prompt=question)
            if not analysis:
                return {
                    "status": "error",
                    "message": "Vision analysis returned no response.",
                }
            return {"status": "ok", "analysis": analysis}
        except Exception as e:
            return {
                "status": "error",
                "message": (
                    f"Vision analysis failed ({type(e).__name__}). Call "
                    "vision(action='manual', input={}, reasoning='the direct "
                    "vision request failed, load the explicit manual route') "
                    "for the explicit manual route."
                ),
            }

    def _adapt_manual_result(self, mcp_result: dict[str, Any]) -> dict[str, Any]:
        # Host-owned flattening of the manual child's canonical result into
        # vision's pre-migration ``status``/``action``/``manual`` shape (plus
        # the loader's ``manual_path``). See ``handle()`` for the ordering rule.
        flat: dict[str, Any] = {
            "status": mcp_result.get("status", "ok"),
            "action": "manual",
            "manual": mcp_result["content"][0]["text"],
            "manual_path": mcp_result["structuredContent"]["manual_path"],
        }
        if "error" in mcp_result:
            flat["error"] = mcp_result["error"]
        return flat

    def manual(self) -> dict:
        """Return only installed guidance; never inspect config or invoke a backend.

        Retained as the family's own public manual entry point (callers and
        tests use it directly). Performs no provider construction, no
        credential read, and no analyze operation.
        """
        return self._adapt_manual_result(self._family.handle({"action": "manual", "input": {}}))

    def handle(self, args: dict | None) -> dict:
        # Canonical statement of this family's dispatch/presentation ordering.
        # The generic ``ToolFamily`` dispatcher validates ``action``,
        # type-checks and strips root ``summarize``, rejects unknown root
        # fields, and rejects ``input`` keys outside the selected action's own
        # declared schema (schema conformance alone is not the dispatch-time
        # authorization boundary — see ``tools/CONTRACT.md`` "Dispatch and
        # actions") before ``_dispatch_analyze`` or the registered ``manual``
        # child's handler ever runs, so every envelope failure lands before any
        # provider I/O. ``self._family.handle`` returns the ``manual`` child's
        # canonical ``content``/``structuredContent`` result verbatim (no double
        # wrap); flattening it to vision's public shape is this method's own
        # Host job, done strictly after dispatch, never inside a registered
        # child. Envelope failures are normalized to vision's long-standing
        # ``{"status": "error", "message": ...}`` shape here, rather than by
        # changing the generic dispatcher's canonical error result.
        action = args.get("action") if isinstance(args, Mapping) else None
        result = self._family.handle(args)
        if action == "manual" and "content" in result:
            return self._adapt_manual_result(result)
        if result.get("status") == "failed" and "error_code" in result:
            return {"status": "error", "message": result["message"]}
        return result


def setup(
    agent: "BaseAgent",
    vision_service: VisionService | None = None,
    provider: str | None = None,
    api_key: str | None = None,
    api_key_env: str | None = None,
    **kwargs: Any,
) -> VisionManager:
    """Set up the vision capability on an agent.

    Requires either ``vision_service`` or ``provider`` + ``api_key`` for a
    direct route. Without one, the tool is still registered for manual guidance.
    """
    manual_reason = ""
    if vision_service is None and provider is not None:
        if api_key_env:
            from lingtai.kernel.config_resolve import resolve_env
            api_key = resolve_env(api_key, api_key_env)
        provider_key = provider.lower()
        active_service = getattr(agent, "service", None)
        active_provider = getattr(active_service, "provider", "")
        active_provider_key = active_provider.lower() if isinstance(active_provider, str) else ""
        same_provider = _same_provider_identity(provider_key, active_provider_key)
        active_model = getattr(active_service, "_model", None) if same_provider else None
        active_base_url = getattr(active_service, "_base_url", None) if same_provider else None
        active_api_key = getattr(active_service, "api_key", None) if same_provider else None
        if provider_key == "local":
            # Local vision is an explicit pseudo-provider: keep it out of
            # PROVIDERS/check-caps, but preserve the documented opt-in route.
            # Its constructor accepts only model/max_tokens and needs no key.
            local_kwargs = {
                key: kwargs[key]
                for key in ("model", "max_tokens")
                if key in kwargs and kwargs[key] is not None
            }
            from lingtai.services.vision import create_vision_service
            try:
                vision_service = create_vision_service(
                    "local",
                    api_key=None,
                    **local_kwargs,
                )
            except Exception as exc:
                manual_reason = _setup_failure(provider, exc)
        elif provider_key not in PROVIDERS["providers"]:
            # No dedicated VisionService for this provider (custom relay,
            # OpenRouter, an anthropic-compat local proxy, ...). Route vision
            # through the OpenAI- or Anthropic-compatible service, picking the
            # wire protocol and endpoint from, in order:
            #   1. capability kwargs — explicit init.json override. This lets a
            #      user point vision at a *different*, vision-capable model
            #      (e.g. Kimi-K2.6 on a multi-model proxy) while the main LLM
            #      stays on a text-only model (e.g. GLM-5.1).
            #   2. the main LLM: api_compat from service._provider_defaults
            #      (shaped {provider_name: defaults_dict}), base_url/model from
            #      service._base_url / service._model.
            # If the relay or model can't actually do vision, the call fails at
            # runtime — capability registration never pre-checks.
            bucket = {}
            api_compat = (kwargs.get("api_compat") or "").lower()
            if not api_compat:
                defaults = getattr(active_service, "_provider_defaults", None) if same_provider else None
                if isinstance(defaults, dict):
                    # _provider_defaults is dict[provider_name, defaults_dict];
                    # read only the active provider's bucket, never another
                    # provider's credential/transport configuration.
                    bucket = defaults.get(active_provider_key)
                    if isinstance(bucket, dict):
                        api_compat = (bucket.get("api_compat") or "").lower()

            cap_model = kwargs.get("model")
            cap_base_url = kwargs.get("base_url")
            cap_max_tokens = kwargs.get("max_tokens")
            bucket = bucket if isinstance(bucket, dict) else {}
            llm_base_url = cap_base_url or active_base_url or bucket.get("base_url")
            llm_model = cap_model or active_model or bucket.get("model")
            api_key = api_key or active_api_key
            headers = kwargs.get("default_headers") or bucket.get("default_headers")
            wire_api = _effective_openai_wire(
                kwargs.get("wire_api") or bucket.get("wire_api"),
                use_responses_api=bucket.get("use_responses_api") is True,
                base_url=llm_base_url,
            )

            if api_compat == "openai":
                from lingtai.services.vision.openai import OpenAIVisionService
                svc_kwargs: dict = {
                    "api_key": api_key,
                    "model": llm_model,
                    "base_url": llm_base_url,
                }
                if headers:
                    svc_kwargs["default_headers"] = headers
                if wire_api and wire_api != "auto":
                    svc_kwargs["wire_api"] = wire_api
                if cap_max_tokens is not None:
                    svc_kwargs["max_tokens"] = cap_max_tokens
                if wire_api is None:
                    manual_reason = "The active OpenAI-compatible wire is not implemented by the direct vision service; use vision(action='manual', input={}, reasoning='the active OpenAI-compatible wire has no direct vision route')."
                elif not llm_model:
                    manual_reason = f"Provider {provider!r} has no resolved current model for direct vision; use vision(action='manual', input={{}}, reasoning='no resolved current model for direct vision')."
                elif not api_key:
                    manual_reason = f"Provider {provider!r} has no resolved current credential for direct vision; use vision(action='manual', input={{}}, reasoning='no resolved current credential for direct vision')."
                else:
                    try:
                        vision_service = OpenAIVisionService(**svc_kwargs)
                    except Exception as exc:
                        manual_reason = _setup_failure(provider, exc)
            elif api_compat == "anthropic":
                from lingtai.services.vision.anthropic import AnthropicVisionService
                svc_kwargs = {
                    "api_key": api_key,
                    "model": llm_model,
                    "base_url": llm_base_url,
                }
                if headers:
                    svc_kwargs["default_headers"] = headers
                if cap_max_tokens is not None:
                    svc_kwargs["max_tokens"] = cap_max_tokens
                if not llm_model:
                    manual_reason = f"Provider {provider!r} has no resolved current model for direct vision; use vision(action='manual', input={{}}, reasoning='no resolved current model for direct vision')."
                elif not api_key:
                    manual_reason = f"Provider {provider!r} has no resolved current credential for direct vision; use vision(action='manual', input={{}}, reasoning='no resolved current credential for direct vision')."
                else:
                    try:
                        vision_service = AnthropicVisionService(**svc_kwargs)
                    except Exception as exc:
                        manual_reason = _setup_failure(provider, exc)
            else:
                manual_reason = f"No direct vision route is supported for provider {provider!r}; use vision(action='manual', input={{}}, reasoning='this provider has no supported direct vision route')."
        else:
            if provider_key in _CODEX_FAMILY:
                # Codex vision is a standalone Responses request. It may share
                # the active Codex family's model and endpoint, but never
                # inherits those from an unrelated main provider. The fixed/
                # direct vs weighted/pool credential route is *not* chosen from
                # provider spelling: it follows the active provider-default
                # bucket exactly as the canonical Codex factory does — direct
                # iff the bucket carries a nonblank trimmed ``codex_auth_path``,
                # otherwise pool (see ``lingtai/llm/_register.py``).
                if same_provider:
                    if active_model:
                        kwargs.setdefault("model", active_model)
                    if active_base_url:
                        kwargs.setdefault("base_url", active_base_url)
                codex_base_url = kwargs.get("base_url")

                defaults = getattr(active_service, "_provider_defaults", None) if same_provider else None
                bucket = defaults.get(active_provider_key) if isinstance(defaults, dict) else None
                if not isinstance(bucket, dict):
                    bucket = {}
                # Bucket-driven route: the active Codex service is direct iff its
                # bucket configures a nonblank ``codex_auth_path``, else pool. An
                # unrelated active provider carries an empty bucket → ``"pool"``,
                # and its pool branch stays gated by ``same_provider`` below, so it
                # never reads a default pool and still fails closed.
                codex_route = _codex_bucket_route(bucket)
                # Normalize an explicit capability identity on every route. This
                # preserves a valid independent token path while ensuring a
                # whitespace-only value cannot bypass either fail-closed branch.
                explicit_token_path = _normalize_codex_auth_path(kwargs.pop("token_path", None))
                if explicit_token_path:
                    kwargs["token_path"] = explicit_token_path
                if not kwargs.get("model"):
                    manual_reason = f"Provider {provider!r} has no resolved current model for direct vision; use vision(action='manual', input={{}}, reasoning='no resolved current model for direct vision')."
                elif codex_route == "direct":
                    # A whitespace-only explicit ``token_path`` is not an identity;
                    # normalize both it and the inherited bucket path once so the
                    # trimmed value drives ``token_path`` exactly like the factory.
                    token_path = (
                        explicit_token_path
                        or _normalize_codex_auth_path(bucket.get("codex_auth_path"))
                    )
                    if token_path:
                        kwargs["token_path"] = token_path
                    else:
                        manual_reason = "Codex vision has no explicit current OAuth identity; use vision(action='manual', input={}, reasoning='Codex vision has no explicit current OAuth identity')."
                else:
                    # Pool route (bucket has no nonblank ``codex_auth_path``).
                    # WeightedAccountSource selects an account from the pool file
                    # (thin-wrapper spec v3).  Reads only the non-secret pool;
                    # Codex core owns token refresh, quota, retry, and transport.
                    # Only an active Codex-family service (``same_provider``) may
                    # supply a pool identity; an unrelated active provider never
                    # runs the selector and falls through to fail-closed below,
                    # so no unrelated/default pool file is read on its behalf.
                    if same_provider:
                        from lingtai.auth.codex_pool import (
                            resolve_codex_pool_path,
                            resolve_codex_tui_dir,
                        )
                        from lingtai.auth.codex_account_source import (
                            WeightedAccountSource,
                            NoCandidateError,
                        )
                        tui_dir = resolve_codex_tui_dir()
                        pool_path = resolve_codex_pool_path(bucket)
                        source = WeightedAccountSource(
                            pool_path, tui_dir, model=kwargs.get("model"),
                        )
                        try:
                            candidate = source.select()
                            kwargs["token_path"] = candidate.auth_ref
                        except NoCandidateError:
                            pass
                    if not kwargs.get("token_path"):
                        manual_reason = "Codex pool vision has no selected current OAuth identity; use vision(action='manual', input={}, reasoning='Codex pool vision has no selected current OAuth identity')."
                kwargs.pop("api_compat", None)
                kwargs.pop("base_url", None)
                if codex_base_url:
                    kwargs["base_url"] = codex_base_url
                if not manual_reason:
                    from lingtai.services.vision import create_vision_service
                    try:
                        vision_service = create_vision_service("codex", api_key=None, **kwargs)
                    except Exception as exc:
                        manual_reason = _setup_failure(provider, exc)
            else:
                service_provider = provider_key
                defaults = getattr(active_service, "_provider_defaults", {}) if same_provider else {}
                bucket = defaults.get(active_provider_key, {}) if isinstance(defaults, dict) else {}
                active_base_url = active_base_url or (bucket.get("base_url") if isinstance(bucket, dict) else None)
                active_headers = bucket.get("default_headers") if isinstance(bucket, dict) else None
                active_compat = kwargs.get("api_compat") or (bucket.get("api_compat") if isinstance(bucket, dict) else "") or ""
                wire_api = _effective_openai_wire(
                    kwargs.get("wire_api") or (bucket.get("wire_api") if isinstance(bucket, dict) else None),
                    use_responses_api=isinstance(bucket, dict) and bucket.get("use_responses_api") is True,
                    base_url=kwargs.get("base_url") or active_base_url,
                )
                if service_provider in {"openrouter", "deepseek", "zhipu", "glm", "grok", "qwen", "kimi"}:
                    service_provider = "anthropic" if active_compat.lower() == "anthropic" else "openai"
                elif service_provider == "custom":
                    service_provider = "anthropic" if active_compat.lower() == "anthropic" else "openai"

                # Provider-specific kwarg injection. Each branch is opt-in because
                # vision services have heterogeneous constructor signatures.
                if service_provider == "minimax":
                    service_provider = "anthropic"
                if service_provider in {"openai", "anthropic", "gemini", "mimo"}:
                    if same_provider and active_model:
                        kwargs.setdefault("model", active_model)
                    if (
                        service_provider in {"openai", "anthropic"}
                        and same_provider
                        and active_base_url
                    ):
                        kwargs.setdefault("base_url", active_base_url)
                if service_provider == "mimo" and same_provider and active_base_url:
                    kwargs.setdefault("base_url", active_base_url)
                if service_provider in {"openai", "mimo"} and wire_api is None:
                    manual_reason = "The active OpenAI-compatible wire is not implemented by the direct vision service; use vision(action='manual', input={}, reasoning='the active OpenAI-compatible wire has no direct vision route')."
                elif service_provider == "mimo" and wire_api != "chat_completions":
                    manual_reason = "The active MiMo wire is not implemented by the direct vision service; use vision(action='manual', input={}, reasoning='the active MiMo wire has no direct vision route')."
                if service_provider in {"openai", "mimo"} and active_compat == "anthropic":
                    manual_reason = "The active preset uses an Anthropic wire that this vision route cannot safely adapt; use vision(action='manual', input={}, reasoning='the active Anthropic wire cannot be safely adapted for direct vision')."
                    vision_service = None
                if service_provider == "anthropic" and active_headers:
                    kwargs.setdefault("default_headers", active_headers)
                elif service_provider == "openai":
                    if active_headers:
                        kwargs.setdefault("default_headers", active_headers)
                    if wire_api not in (None, "auto"):
                        kwargs.setdefault("wire_api", wire_api)
                elif service_provider == "mimo":
                    # MiMo's standalone constructor intentionally accepts only
                    # api_key/model/base_url/max_tokens. Its current direct
                    # route is Chat Completions; other wires stay manual-only.
                    kwargs.pop("default_headers", None)
                    kwargs.pop("wire_api", None)
                resolved_api_key = api_key or active_api_key
                if service_provider not in {"codex", "local"} and not kwargs.get("model"):
                    manual_reason = f"Provider {provider!r} has no resolved current model for direct vision; use vision(action='manual', input={{}}, reasoning='no resolved current model for direct vision')."
                elif service_provider not in {"codex", "local"} and not resolved_api_key:
                    manual_reason = f"Provider {provider!r} has no resolved current credential for direct vision; use vision(action='manual', input={{}}, reasoning='no resolved current credential for direct vision')."
                # Dedicated vision services do not consume the LLM adapter's
                # transport selector.
                kwargs.pop("api_compat", None)
                if service_provider not in {"openai", "anthropic", "mimo"}:
                    kwargs.pop("base_url", None)
                # Lazy import: the provider service lives in ``lingtai.services``.
                from lingtai.services.vision import create_vision_service
                if vision_service is None and not manual_reason:
                    try:
                        vision_service = create_vision_service(
                            service_provider,
                            api_key=resolved_api_key,
                            **kwargs,
                        )
                    except Exception as exc:
                        manual_reason = _setup_failure(provider, exc)
    elif vision_service is None:
        manual_reason = "No direct vision provider was configured; use vision(action='manual', input={}, reasoning='no direct vision provider is configured')."

    mgr = VisionManager(agent, vision_service=vision_service, manual_reason=manual_reason)
    agent.add_tool("vision", schema=get_schema(), handler=mgr.handle, description=get_description(), glossary_package=__package__)
    return mgr
