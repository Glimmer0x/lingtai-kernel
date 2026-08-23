"""Vision capability — image understanding via VisionService.

Adds the ability to analyze images. Requires a VisionService instance,
created either explicitly or via the ``provider``/``api_key`` factory.

Usage:
    agent.add_capability("vision", vision_service=my_svc)
    agent.add_capability("vision", provider="anthropic", api_key="sk-...")

The native mlx pseudo-provider (Apple MLX, on-device) remains available
through explicit ``add_capability(..., provider="mlx")`` opt-in, but it is
intentionally not advertised in ``PROVIDERS`` or first-run/check-caps
surfaces: it is macOS-only and requires an on-device model.

``local`` is a first-class generic local OpenAI-compatible provider: it
points at any OpenAI-compatible vision server on your machine (Ollama, LM
Studio, vLLM, llama.cpp, …) via ``base_url`` (default
``http://localhost:11434/v1``) and requires an explicit ``model``. The
operator-owned endpoint configuration lives in ``settings/vision.json``
(``base_url``, ``model``, optional ``api_key``/``max_tokens``); capability
kwargs override the file. No API key is required — local servers ignore the
value, so a placeholder is synthesized. Configure it with
``add_capability("vision", provider="local", model="<pulled-model>")``, via
``manifest.capabilities.vision``, or via ``settings/vision.json``.

``vision`` is migrated to the LingTai Tool Protocol v2 action-separated shape
(``src/lingtai/tools/CONTRACT.md``): one public ``vision`` tool whose canonical
children are ``analyze``/``check``/``list`` plus the family-owned reserved
``manual``, composed and dispatched by the generic
``lingtai.tools.tool_family`` infrastructure. The public tool name and action
values are unchanged; only the call envelope moved from flat arguments to
``action``/``input``/``reasoning``/``summarize``.
Provider routing, credential/identity resolution, and every analyze/manual
result shape are untouched by that migration.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping

from lingtai.kernel.tool_plugin import BoundToolPlugin, ToolPluginDeclaration, ToolPluginDeclarationError

from ..tool_family import ChildTool, ToolFamily
from ..tool_family.manual import MANUAL_INPUT_SCHEMA, build_manual_child


if TYPE_CHECKING:
    from lingtai.kernel.base_agent import BaseAgent
    from lingtai.kernel.tool_plugin import ActiveProviderPort, ToolPluginHost, WorkdirPort
    from lingtai.services.vision import VisionService


def _setup_failure(provider: str, exc: BaseException) -> str:
    """Build explicit manual guidance without exposing exception contents."""
    return (
        f"Direct vision setup failed for provider {provider!r} "
        f"({type(exc).__name__}); use vision(action='manual', input={{}}, "
        f"reasoning='direct vision setup failed, load the manual route')."
    )


def _consent_guidance() -> str:
    """Build the setup-with-human-consent guidance for a vision failure.

    Installing a local vision server, pulling a model, or editing
    settings/vision.json / the capability manifest are external side effects:
    the agent must obtain explicit human consent before performing them. The
    full steps live in the vision manual skill.
    """
    return (
        "To enable vision, load the vision manual skill for the setup steps: "
        "vision(action='manual', input={}, reasoning='vision is not set up, "
        "load the setup steps'); then ask the human for consent before "
        "installing a local vision server, pulling a model, or editing "
        "settings/vision.json / the capability manifest."
    )


_CODEX_POOL_ALIASES = {"codex-pool", "codex_pool"}
_CODEX_FAMILY = {"codex"} | _CODEX_POOL_ALIASES

# Claude Code CLI vision: all three spellings identify the claude backend
# whose vision route is the operator-installed Claude Code CLI (``claude -p``).
# LingTai does not proxy the CLI's auth, so these providers return explicit
# guidance instead of constructing a service. ``claude-p`` is the explicit
# vision-route alias alongside the LLM registry's two canonical adapter
# spellings (``claude-code``/``claude_code``).
_CLAUDE_CLI_FAMILY = {"claude-p", "claude-code", "claude_code"}


def _same_codex_family(requested: str, active: str) -> bool:
    """Return whether both names are Codex-family spellings.

    Provider spelling is only a Codex-family *compatibility gate*: ``codex``,
    ``codex-pool``, and ``codex_pool`` all resolve to the one native Codex
    factory (see ``lingtai/llm/_register.py``). Spelling never selects the
    fixed/direct vs weighted/pool route; that choice is made solely from the
    active provider-default bucket (``_codex_bucket_route``).
    """
    return requested in _CODEX_FAMILY and active in _CODEX_FAMILY


def _vision_endpoint(provider: str | None) -> str:
    """Classify a provider's vision endpoint for the mechanical ``list`` action.

    Pure string classification — never constructs a service, reads a
    credential, or touches the network.
    """
    key = (provider or "").lower()
    if key in _CODEX_FAMILY:
        return "responses"
    if key in _CLAUDE_CLI_FAMILY:
        return "claude-cli"
    if key == "local":
        return "openai-compatible-local"
    if key == "mlx":
        return "mlx-on-device"
    if key in PROVIDERS.get("providers", ()):
        return "provider-service"
    return "unknown"


def _responses_vision(provider: str | None) -> bool:
    """Return whether a provider routes vision through the Responses API."""
    return bool(provider and provider.lower() in _CODEX_FAMILY)


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
    if {requested, active} <= _CLAUDE_CLI_FAMILY:
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
        "codex", "codex-pool", "codex_pool", "claude-p", "claude-code", "claude_code",
        "local",
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
        "preset": {
            "type": ["string", "null"],
            "description": (
                "Optional preset name/path whose vision service should be "
                "borrowed for this call (e.g. \"codex-pool\" for gpt-5.6 "
                "vision). Must be a path listed in manifest.preset.allowed. "
                "Null/absent uses the default route (active provider or the "
                "configured vision capability)."
            ),
        },
    },
    "required": ["image_path", "question"],
    "additionalProperties": False,
}

def _unused(_input: Mapping[str, Any]) -> dict[str, Any]:
    raise AssertionError("the module-level schema-only ToolFamily never dispatches")


_CHECK_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "preset": {
            "type": ["string", "null"],
            "description": (
                "Optional preset name/path whose vision service should be "
                "checked (e.g. \"codex-pool\" for gpt-5.6 vision). Must be a "
                "path listed in manifest.preset.allowed. Null/absent checks "
                "the default route (active provider or the configured vision "
                "capability). The check resolves the service identity without "
                "sending an image request."
            ),
        },
    },
    "required": ["preset"],
    "additionalProperties": False,
}

_LIST_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "required": [],
    "additionalProperties": False,
}


@dataclass(frozen=True, slots=True)
class VisionConfiguration:
    """The capability setup input supplied through the configuration port.

    It contains exactly the public ``setup()`` arguments, never an Agent. The
    static declaration owns its validation and interpretation at bind time;
    keeping the value immutable makes a refresh bind from one coherent snapshot.
    """

    vision_service: Any | None
    provider: str | None
    api_key: str | None
    api_key_env: str | None
    kwargs: Mapping[str, Any]


_DESCRIPTION = (
    "Analyze an image with the active preset. Use vision(action='analyze', "
    "input={'image_path': '...', 'question': null}, reasoning='read the "
    "image') for the direct request; the optional input preset field "
    "borrows another allowed preset's vision service (e.g. 'codex-pool'). "
    "Use vision(action='check', input={'preset': null}, reasoning='verify "
    "the vision route') to resolve which preset's vision service actually "
    "works without sending an image. A real request failure returns a "
    "sanitized error and points to vision(action='manual', input={}, "
    "reasoning='load vision guidance') for read-only alternatives. No "
    "provider, model, credential, or MCP fallback is automatic."
)


def _build_family(
    analyze_handler: Any = _unused,
    check_handler: Any = _unused,
    list_handler: Any = _unused,
    manual_child: ChildTool | None = None,
) -> ToolFamily:
    """Build Vision's declared family from its one static declaration.

    The module-level schema-only family and each host-bound dispatcher derive
    their public name, operational schemas, and reserved manual slot from
    :data:`DECLARATION`. This prevents the advertised action inventory from
    drifting away from the declaration the kernel reserves.
    """
    return ToolFamily(
        DECLARATION.name,
        [
            ChildTool(
                action,
                DECLARATION.input_schemas[action],
                handler,
                title=f"{action} input",
            )
            for action, handler in (
                ("analyze", analyze_handler),
                ("check", check_handler),
                ("list", list_handler),
            )
        ]
        + [
            manual_child
            or ChildTool("manual", DECLARATION.manual_input_schema, _unused, title="manual input")
        ],
    )


def get_description(lang: str = "en") -> str:
    return _DESCRIPTION


def get_schema(lang: str = "en") -> dict:
    # Composed by generic ToolFamily infrastructure from the declaration-derived
    # schema-only family, never hand-assembled.
    return _FAMILY.build_schema()


class VisionManager:
    """Host-bound Vision dispatcher with no reference to the live Agent."""

    def __init__(
        self,
        workdir: "WorkdirPort",
        active_provider: "ActiveProviderPort",
        vision_service: "VisionService | None",
        manual_reason: str = "",
    ) -> None:
        self._workdir = workdir
        self._active_provider = active_provider
        self._vision_service = vision_service
        self._manual_reason = manual_reason
        # The declaration-derived child registry gets only this dispatcher's
        # handlers and the workdir-bound packaged manual child.
        self._family = _build_family(
            self._dispatch_analyze,
            self._dispatch_check,
            self._dispatch_list,
            build_manual_child(workdir, DECLARATION.manual),
        )

    def __call__(self, args: dict | None) -> dict:
        """Make the manager itself the registrar-published handler."""
        return self.handle(args)

    def _build_service_from_preset(self, preset_ref: str) -> tuple[Any, str]:
        """Borrow another preset's vision service for one call.

        The preset must appear in ``manifest.preset.allowed`` (same
        authorization surface as preset swapping). Its ``manifest.llm`` plus
        ``manifest.capabilities.vision`` provide the provider/model/credential
        identity; ``_resolve_direct_service`` is invoked with an identity shim
        built from that preset so the borrowed provider resolves its own route
        and credentials (e.g. a ``codex-pool`` preset selects its own OAuth
        pool identity) instead of inheriting the active provider's.

        Returns ``(VisionService | None, manual_reason, identity)`` where
        ``identity`` is a dict of the resolved provider/model identity (empty
        on failure).
        """
        import json as _json

        from lingtai.kernel.presets import load_preset, resolve_allowed_presets

        init_path = Path(self._workdir.path) / "init.json"
        if not init_path.is_file():
            return None, "No init.json is available to resolve manifest.preset.allowed.", {}
        try:
            init_data = _json.loads(init_path.read_text(encoding="utf-8"))
        except Exception:
            return None, "init.json could not be parsed while resolving preset.allowed.", {}
        manifest = init_data.get("manifest") or {}
        allowed_paths = {str(p) for p in resolve_allowed_presets(manifest, self._workdir.path)}
        raw_allowed = set(manifest.get("preset", {}).get("allowed") or [])
        resolved_ref = str(Path(preset_ref).expanduser())
        if preset_ref not in raw_allowed and resolved_ref not in allowed_paths:
            return None, (
                f"Preset {preset_ref!r} is not in manifest.preset.allowed; "
                "only authorized presets may be borrowed for vision."
            ), {}
        try:
            preset = load_preset(
                preset_ref,
                working_dir=self._workdir.path,
                # Read-only preset loading: no migration surface for a borrow.
                run_migrations=lambda _path: None,
            )
        except Exception as exc:
            return None, f"Failed to load preset {preset_ref!r}: {type(exc).__name__}.", {}
        pm = preset.get("manifest") or {}
        llm = pm.get("llm") or {}
        vision_cap = (pm.get("capabilities") or {}).get("vision") or {}
        provider = vision_cap.get("provider") or llm.get("provider")
        if not provider:
            return None, f"Preset {preset_ref!r} declares no vision provider.", {}
        identity = {
            "provider": llm.get("provider") or provider,
            "model": llm.get("model"),
            "base_url": llm.get("base_url"),
        }

        class _PresetIdentity:
            provider = llm.get("provider") or provider
            _model = llm.get("model")
            _base_url = llm.get("base_url")
            api_key = None
            _provider_defaults: dict = {}

        kwargs = dict(vision_cap)
        for key in ("model", "base_url", "api_key_env", "api_compat", "wire_api"):
            if key in llm and key not in kwargs:
                kwargs[key] = llm[key]
        api_key = kwargs.pop("api_key", None)
        api_key_env = kwargs.pop("api_key_env", None)
        # ``provider`` is passed positionally below; drop the capability copy so
        # ``_resolve_direct_service`` never receives it twice (TypeError).
        kwargs.pop("provider", None)
        service, service_reason = _resolve_direct_service(
            self._workdir,
            self._active_provider,
            provider,
            api_key=api_key,
            api_key_env=api_key_env,
            identity_service=_PresetIdentity(),
            **kwargs,
        )
        return service, service_reason, identity

    def _dispatch_analyze(self, action_input: Mapping[str, Any]) -> dict[str, Any]:
        """Run the one direct analyze operation on already-validated input.

        The body is the pre-migration ``handle()`` analyze path unchanged:
        same missing-service guard, relative-path resolution, existence check,
        default prompt, and success/failure result shapes. When the call
        carries the optional ``preset`` option, a borrowed service is built for
        this call from that preset's vision configuration instead of the
        default route.
        """
        preset_ref = action_input.get("preset") if isinstance(action_input, Mapping) else None
        if preset_ref:
            borrowed, borrow_reason, _identity = self._build_service_from_preset(preset_ref)
            if borrowed is None:
                return {
                    "status": "error",
                    "message": (
                        f"{borrow_reason} Load the vision manual skill for the "
                        "borrowing steps: vision(action='manual', input={}, "
                        "reasoning='preset vision unavailable, load the setup "
                        "steps'); then ask the human for consent before "
                        "changing preset authorization."
                    ),
                }
            service = borrowed
        else:
            service = self._vision_service
        if service is None:
            reason = self._manual_reason or (
                "Direct vision is unavailable; call vision(action='manual', "
                "input={}, reasoning='no direct vision route, load the "
                "manual alternatives')."
            )
            return {
                "status": "error",
                "message": f"{reason} {_consent_guidance()}",
            }
        image_path = action_input.get("image_path") or ""
        question = action_input.get("question")
        if question is None:
            question = "Describe what you see in this image."

        if not image_path:
            return {"status": "error", "message": "Provide image_path"}

        path = Path(image_path)
        if not path.is_absolute():
            path = self._workdir.path / path

        if not path.is_file():
            return {"status": "error", "message": f"Image file not found: {path}"}

        try:
            analysis = service.analyze_image(str(path), prompt=question)
            if not analysis:
                return {
                    "status": "error",
                    "message": "Vision analysis returned no response.",
                }
            return {"status": "ok", "analysis": analysis}
        except Exception as e:
            if preset_ref:
                route = "borrowed preset vision route"
                hint = (
                    "The borrowed preset's vision service failed for this "
                    "image; verify the preset is authorized and its provider "
                    "supports images."
                )
            else:
                route = "default vision route"
                hint = (
                    "The default route is the current provider's "
                    "Responses-API vision, which may not support images."
                )
            return {
                "status": "error",
                "message": (
                    f"Vision analysis failed on the {route} ({type(e).__name__}). "
                    f"{hint} Alternative vision may be available: the current "
                    "provider's MCP, a borrowed preset via the analyze "
                    "preset option, or a local OpenAI-compatible vision "
                    "server via provider='local'. Load the vision manual skill "
                    "for the setup alternatives: vision(action='manual', "
                    "input={}, reasoning='vision failed, load the setup "
                    "alternatives'); then ask the human for consent "
                    "before setting one up."
                ),
            }

    def _dispatch_check(self, action_input: Mapping[str, Any]) -> dict[str, Any]:
        """Resolve which vision route actually works without sending an image.

        With the optional ``preset`` field, this borrows that preset's vision
        service the same way ``analyze`` would (authorization check, preset
        load, provider identity) and reports the resolved provider/model; the
        service is constructed but no image request is made, so it never costs
        a provider call. Without ``preset``, it reports whether the default
        route (configured service or the active LLM's own Responses API) is
        available. A failure returns a sanitized error pointing at the manual.
        """
        preset_ref = action_input.get("preset") if isinstance(action_input, Mapping) else None
        if preset_ref:
            borrowed, borrow_reason, identity = self._build_service_from_preset(preset_ref)
            if borrowed is None:
                return {
                    "status": "error",
                    "message": (
                        f"{borrow_reason} Load the vision manual skill for the "
                        "borrowing steps: vision(action='manual', input={}, "
                        "reasoning='preset vision unavailable, load the setup "
                        "steps'); then ask the human for consent before "
                        "changing preset authorization."
                    ),
                }
            return {
                "status": "ok",
                "route": f"preset:{preset_ref}",
                "provider": identity.get("provider"),
                "model": identity.get("model"),
            }
        if self._vision_service is None:
            reason = self._manual_reason or (
                "Direct vision is unavailable; call vision(action='manual', "
                "input={}, reasoning='no direct vision route, load the "
                "manual alternatives')."
            )
            return {
                "status": "error",
                "message": f"{reason} {_consent_guidance()}",
            }
        active_service = self._active_provider.service
        return {
            "status": "ok",
            "route": "default",
            "provider": getattr(active_service, "provider", None),
            "model": getattr(active_service, "model", None),
        }

    def _dispatch_list(self, action_input: Mapping[str, Any]) -> dict[str, Any]:
        # mechanical enumeration; never constructs a service or makes a provider call
        import json as _json
        from lingtai.kernel.presets import load_preset, resolve_allowed_presets

        active_service = self._active_provider.service
        active_provider = getattr(active_service, "provider", None)
        active_model = getattr(active_service, "_model", None)
        default_endpoint = _vision_endpoint(active_provider)
        default = {
            "provider": active_provider,
            "model": active_model,
            "configured": self._vision_service is not None,
            "supports_vision": bool(self._vision_service is not None or default_endpoint != "unknown"),
            "endpoint": default_endpoint,
            "responses_vision": _responses_vision(active_provider),
        }
        allowed: list[str] = []
        init_path = Path(self._workdir.path) / "init.json"
        if init_path.is_file():
            try:
                init_data = _json.loads(init_path.read_text(encoding="utf-8"))
                manifest = init_data.get("manifest") or {}
                allowed = sorted(
                    {str(p) for p in resolve_allowed_presets(manifest, self._workdir.path)}
                    | {str(p) for p in (manifest.get("preset", {}).get("allowed") or [])}
                )
            except Exception:
                allowed = []
        presets: list[dict[str, Any]] = []
        for ref in allowed:
            try:
                preset = load_preset(ref, working_dir=self._workdir.path, run_migrations=lambda _path: None)
            except Exception:
                continue
            pm = preset.get("manifest") or {}
            llm = pm.get("llm") or {}
            vision_cap = (pm.get("capabilities") or {}).get("vision") or {}
            provider = vision_cap.get("provider") or llm.get("provider")
            if not provider:
                continue
            presets.append({
                "preset": ref,
                "provider": provider,
                "model": vision_cap.get("model") or llm.get("model"),
                "endpoint": _vision_endpoint(provider),
                "responses_vision": _responses_vision(provider),
            })
        return {"status": "ok", "default": default, "presets": presets, "count": len(presets)}

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



def _bind(host: "ToolPluginHost") -> BoundToolPlugin:
    """Compose Vision against only its granted ports; mount nothing.

    Provider resolution retains the previous active-provider behavior, but all
    Agent reads flow through ``workdir`` and ``active_provider``. Explicit
    capability kwargs arrive as one opaque configuration port rather than by
    reaching through the Agent. Construction creates no transport, process, or
    prompt side effect; the kernel registrar alone activates and mounts.
    """
    configuration = host.configuration.value
    if not isinstance(configuration, VisionConfiguration):
        raise ToolPluginDeclarationError(
            "vision requires a VisionConfiguration supplied by capability setup"
        )
    vision_service = configuration.vision_service
    provider = configuration.provider
    manual_reason = ""
    if vision_service is None and provider is None:
        active_service = host.active_provider.service
        active_name = getattr(active_service, "provider", "")
        if isinstance(active_name, str) and active_name.strip():
            provider = active_name
    if vision_service is None and provider is not None:
        vision_service, manual_reason = _resolve_direct_service(
            host.workdir,
            host.active_provider,
            provider,
            api_key=configuration.api_key,
            api_key_env=configuration.api_key_env,
            **dict(configuration.kwargs),
        )
    elif vision_service is None:
        manual_reason = (
            "No direct vision provider was configured; use vision(action='manual', "
            "input={}, reasoning='no direct vision provider is configured')."
        )
    manager = VisionManager(
        host.workdir,
        host.active_provider,
        vision_service=vision_service,
        manual_reason=manual_reason,
    )
    return BoundToolPlugin(
        name=DECLARATION.name,
        schema=get_schema(),
        handler=manager,
        description=DECLARATION.description,
        glossary_package=DECLARATION.glossary_package,
    )


#: Static official declaration. The schema-only family below and every bound
#: manager derive identity, action schemas, and installed manual destination
#: from this one object; the kernel verifies their advertised actions at bind.
DECLARATION = ToolPluginDeclaration(
    name="vision",
    actions=("analyze", "check", "list"),
    input_schemas={
        "analyze": _ANALYZE_INPUT_SCHEMA,
        "check": _CHECK_INPUT_SCHEMA,
        "list": _LIST_INPUT_SCHEMA,
    },
    manual_input_schema=MANUAL_INPUT_SCHEMA,
    manual="vision",
    description=_DESCRIPTION,
    binder=_bind,
    requires=("workdir", "active_provider", "configuration"),
    glossary_package=__package__,
)


#: Import-time schema-only composition catches a malformed fixed child registry
#: before an Agent exists. Runtime binding builds the same declaration-derived
#: family with real handlers and its installed manual child.
_FAMILY = _build_family()


def _resolve_direct_service(
    workdir: "WorkdirPort",
    active_provider: "ActiveProviderPort",
    provider: str,
    api_key: str | None = None,
    api_key_env: str | None = None,
    *,
    identity_service: Any = None,
    **kwargs: Any,
) -> tuple["VisionService | None", str]:
    """Resolve a direct VisionService from provider + kwargs.

    ``identity_service`` overrides the active-provider port's service used for
    provider identity, model/base_url inheritance, and the Codex pool bucket.
    Preset borrowing passes a lightweight identity shim built from the borrowed
    preset's ``manifest.llm`` so the borrowed provider (e.g. ``codex-pool``)
    resolves its own route and credentials instead of the active provider's.
    """
    vision_service: "VisionService | None" = None
    manual_reason = ""
    if api_key_env:
        from lingtai.kernel.config_resolve import resolve_env
        api_key = resolve_env(api_key, api_key_env)
    provider_key = provider.lower()
    active_service = identity_service if identity_service is not None else active_provider.service
    active_provider = getattr(active_service, "provider", "")
    active_provider_key = active_provider.lower() if isinstance(active_provider, str) else ""
    same_provider = _same_provider_identity(provider_key, active_provider_key)
    active_model = getattr(active_service, "_model", None) if same_provider else None
    active_base_url = getattr(active_service, "_base_url", None) if same_provider else None
    active_api_key = getattr(active_service, "api_key", None) if same_provider else None
    if provider_key == "mlx":
        # Native Apple-MLX on-device vision is an explicit pseudo-provider:
        # keep it out of PROVIDERS/check-caps, but preserve the documented
        # opt-in route. Its constructor accepts only model/max_tokens and
        # needs no key.
        mlx_kwargs = {
            key: kwargs[key]
            for key in ("model", "max_tokens")
            if key in kwargs and kwargs[key] is not None
        }
        from lingtai.services.vision import create_vision_service
        try:
            vision_service = create_vision_service(
                "mlx",
                api_key=None,
                **mlx_kwargs,
            )
        except Exception as exc:
            manual_reason = _setup_failure(provider, exc)
    elif provider_key == "local":
        # Local is a generic OpenAI-compatible vision server on this
        # machine (Ollama, LM Studio, vLLM, llama.cpp, ...). The endpoint
        # is operator-owned and configured in settings/vision.json
        # (base_url/model/api_key/max_tokens); capability kwargs override
        # the file. base_url defaults to the standard local port. model is
        # REQUIRED — no hardcoded default, because a silently assumed
        # model masks misconfiguration; when it is missing we surface
        # guided setup steps instead. api_key is optional: local servers
        # ignore it, so a placeholder satisfies the OpenAI SDK.
        from lingtai.services.vision.openai import OpenAIVisionService
        from .settings import (
            DEFAULT_LOCAL_BASE_URL,
            SettingsError,
            read_local_settings,
        )
        try:
            local_settings = read_local_settings(workdir)
        except SettingsError as exc:
            manual_reason = (
                f"Local vision settings are invalid: {exc}; fix "
                "settings/vision.json or pass provider='local' with "
                "base_url/model kwargs; see vision(action='manual', input={}, "
                "reasoning='local vision settings are invalid')."
            )
        else:
            local_base_url = (
                kwargs.get("base_url")
                or local_settings.base_url
                or DEFAULT_LOCAL_BASE_URL
            )
            local_model = kwargs.get("model") or local_settings.model
            if not local_model:
                manual_reason = (
                    "Local vision needs an explicit model. Load the vision "
                    "manual skill: vision(action='manual', input={}, "
                    "reasoning='local vision setup'); then ask the human "
                    "for consent before setting it up."
                )
            else:
                local_key = api_key or local_settings.api_key or "local"
                local_wire = _effective_openai_wire(
                    kwargs.get("wire_api"),
                    use_responses_api=False,
                    base_url=local_base_url,
                )
                svc_kwargs: dict = {
                    "api_key": local_key,
                    "model": local_model,
                    "base_url": local_base_url,
                }
                if local_wire and local_wire != "auto":
                    svc_kwargs["wire_api"] = local_wire
                cap_max_tokens = kwargs.get("max_tokens")
                if cap_max_tokens is None:
                    cap_max_tokens = local_settings.max_tokens
                if cap_max_tokens is not None:
                    svc_kwargs["max_tokens"] = cap_max_tokens
                try:
                    vision_service = OpenAIVisionService(**svc_kwargs)
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
        if provider_key in _CLAUDE_CLI_FAMILY:
            # The claude backend uses the Claude Code CLI for vision. LingTai
            # does not proxy the CLI's own authentication (claude.ai
            # subscription, API key, configured provider), so there is no
            # direct service to construct: the agent is told to run
            # ``claude -p`` and read the vision manual for the exact steps.
            manual_reason = (
                "You are using claude as backend, therefore to use vision run "
                "`claude -p`; see the vision manual for more details: "
                "vision(action='manual', input={}, reasoning='claude vision "
                "details')."
            )
        elif provider_key in _CODEX_FAMILY:
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
    return vision_service, manual_reason


def setup(
    agent: "BaseAgent",
    vision_service: "VisionService | None" = None,
    provider: str | None = None,
    api_key: str | None = None,
    api_key_env: str | None = None,
    **kwargs: Any,
) -> VisionManager:
    """Register Vision through its declared host-plugin route.

    ``vision`` remains always registered. Its public capability kwargs are
    carried as a configuration port; the binder resolves the default active
    provider through its one narrow read port, then the registrar mounts the
    resulting handler under the kernel-reserved ``vision`` name. No generic
    ``Agent.add_tool`` path is available to this official family.
    """
    from lingtai.adapters.tool_plugin_host import register_agent_tool_plugins

    (bound,) = register_agent_tool_plugins(
        agent,
        [DECLARATION],
        configurations={
            "vision": VisionConfiguration(
                vision_service=vision_service,
                provider=provider,
                api_key=api_key,
                api_key_env=api_key_env,
                kwargs=dict(kwargs),
            )
        },
    )
    if not isinstance(bound.handler, VisionManager):  # pragma: no cover - declaration invariant
        raise ToolPluginDeclarationError("vision declaration bound a non-Vision handler")
    return bound.handler
