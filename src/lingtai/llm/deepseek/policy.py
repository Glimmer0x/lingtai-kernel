"""DeepSeek reasoning-effort policy — the single owner of this route's semantics.

The shared ``OpenAIAdapter`` keeps owning transport, streaming, tool replay and
fallback. It calls :func:`apply_reasoning` as an opaque hook and carries the
result; it holds no DeepSeek model name, level, alias, or default of its own.

Official contract (api-docs.deepseek.com, current as of 2026-08-10):

  Chat Completions
    * ``thinking.type`` is ``enabled``/``disabled``; the default is enabled.
    * ``reasoning_effort`` is ``low``/``high``/``max``; the default is ``high``.
    * Only ``deepseek-v4-flash`` serves all three levels today;
      ``deepseek-v4-pro`` serves ``high`` and ``max``.
    * Documented compatibility mapping: ``medium`` -> ``high`` everywhere,
      ``xhigh`` -> ``high`` on Flash and ``xhigh`` -> ``max`` on Pro.

  Responses
    * Serves ``deepseek-v4-flash`` only; ``deepseek-v4-pro`` is not supported.
    * ``reasoning.effort`` is supported; no thinking-disable and no
      compatibility alias is documented for this wire.

Two deliberate fail-closed calls:

  1. ``low`` on Pro is rejected instead of silently rewritten to ``high``.
     Server-side leniency is not a documented alias, and offering ``low`` would
     advertise a tier the model does not have. When Pro gains real three-level
     support, move ``low`` into its canonical tuple — one line.
  2. Responses accepts nothing outside ``low|high|max``. That endpoint may
     silently ignore an unsupported parameter, so an undocumented value must
     fail here rather than be sent and quietly dropped.

Related files:
  - src/lingtai/llm/_register.py — installs this policy on the deepseek route
  - src/lingtai/llm/openai/adapter.py — invokes the hook, carries the result
  - src/lingtai/init_schema.py, src/lingtai/agent.py — configuration ingress
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


PROVIDER = "deepseek"

WIRE_CHAT = "chat_completions"
WIRE_RESPONSES = "responses"

#: Internal omission sentinel — never emitted on the wire. It means "send no
#: reasoning field and let DeepSeek's own default apply".
OMITTED = "default"

#: Explicit Chat-only level meaning ``thinking.type = disabled``. A real
#: requested value, NOT an omission.
DISABLED = "none"

FLASH = "deepseek-v4-flash"
PRO = "deepseek-v4-pro"

#: (model, wire) -> (canonical levels, documented compatibility aliases).
#: Canonical levels are the only values an effort control may advertise;
#: aliases are accepted on ingress and normalized, never advertised.
#: ``(PRO, WIRE_RESPONSES)`` is absent on purpose — DeepSeek does not serve it.
_ROUTES: dict[tuple[str, str], tuple[tuple[str, ...], dict[str, str]]] = {
    (FLASH, WIRE_CHAT): (("none", "low", "high", "max"), {"medium": "high", "xhigh": "high"}),
    (PRO, WIRE_CHAT): (("none", "high", "max"), {"medium": "high", "xhigh": "max"}),
    (FLASH, WIRE_RESPONSES): (("low", "high", "max"), {}),
}

#: Models DeepSeek publishes today. Membership makes a missing route entry a
#: KNOWN-unsupported route (rejected even when the effort is omitted) rather
#: than a merely unrecognized one (where omission still works). This is a
#: DeepSeek-local set, not a cross-provider registry.
_KNOWN_MODELS = frozenset({FLASH, PRO})


@dataclass(frozen=True)
class ReasoningApplication:
    """One resolved reasoning decision, captured at session construction.

    Every field is a bounded plain string. The request kwargs are rebuilt on
    demand from these fields, so the recorded decision and the bytes on the
    wire cannot drift apart, and no caller can mutate what was observed.
    """

    wire: str
    requested: str
    normalized: str
    emitted: str
    provenance: str
    provider: str = PROVIDER

    def request_kwargs(self) -> dict[str, Any]:
        """Return the exact request kwargs this decision contributes."""
        if self.emitted == "omitted":
            return {}
        if self.wire == WIRE_RESPONSES:
            return {"reasoning": {"effort": self.normalized}}
        if self.emitted == "disabled":
            # ``thinking`` is a DeepSeek body extension, not an OpenAI SDK
            # parameter, so it travels in ``extra_body`` (which the SDK merges
            # into the top level of the request JSON). Disabled carries no
            # effort at all.
            return {"extra_body": {"thinking": {"type": "disabled"}}}
        return {
            "reasoning_effort": self.normalized,
            "extra_body": {"thinking": {"type": "enabled"}},
        }

    def observation_fields(self) -> dict[str, str]:
        """Return bounded observation strings — never payloads or credentials."""
        return {
            "provider": self.provider,
            "wire": self.wire,
            "effort_requested": self.requested,
            "effort_normalized": self.normalized,
            "effort_emitted": self.emitted,
            "effort_provenance": self.provenance,
        }


def owns_provider(provider: Any) -> bool:
    """Return whether *provider* is the DeepSeek route this module owns."""
    return isinstance(provider, str) and provider.strip().lower() == PROVIDER


def wire_for(llm: Mapping[str, Any]) -> str:
    """Return the wire a manifest/preset ``llm`` block selects for DeepSeek.

    Mirrors ``OpenAIAdapter._should_use_responses()`` for this factory: the
    route always has a configured ``base_url``, so only an explicit
    ``wire_api: responses`` reaches the Responses wire.
    """
    if str(llm.get("wire_api") or "").strip().lower() == WIRE_RESPONSES:
        return WIRE_RESPONSES
    return WIRE_CHAT


def _unsupported_route(model: Any, wire: str) -> ValueError:
    served = sorted(m for (m, w) in _ROUTES if w == wire)
    return ValueError(
        f"provider deepseek does not serve model {model!r} on the {wire} wire; "
        f"models served on this wire: {', '.join(served) or 'none'}"
    )


def apply_reasoning(*, model: Any, wire: str, thinking: Any) -> ReasoningApplication:
    """Resolve one DeepSeek reasoning decision, or raise before dispatch."""
    if wire not in (WIRE_CHAT, WIRE_RESPONSES):
        raise ValueError(f"provider deepseek: unknown wire {wire!r}")

    # A known model on a route DeepSeek does not serve (today: Pro on
    # Responses) is impossible whether or not an effort was configured, so it
    # fails ahead of the omission short-circuit. An UNKNOWN future model is
    # deliberately treated differently below: omission keeps working there
    # without a release.
    if model in _KNOWN_MODELS and (model, wire) not in _ROUTES:
        raise _unsupported_route(model, wire)

    if thinking is None or thinking == OMITTED:
        return ReasoningApplication(
            wire=wire,
            requested=OMITTED,
            normalized=OMITTED,
            emitted="omitted",
            provenance="omitted",
        )

    if not isinstance(thinking, str):
        raise ValueError(
            f"provider deepseek: thinking must be a string, got "
            f"{type(thinking).__name__} ({thinking!r}) for model {model!r} "
            f"on the {wire} wire"
        )

    route = _ROUTES.get((model, wire))
    if route is None:
        raise ValueError(
            f"{_unsupported_route(model, wire)}; refusing explicit effort {thinking!r}"
        )
    canonical, aliases = route

    if thinking in canonical:
        normalized, provenance = thinking, "explicit_config"
    elif thinking in aliases:
        normalized, provenance = aliases[thinking], "compat_alias"
    else:
        raise ValueError(
            f"provider deepseek: {thinking!r} is not a supported reasoning "
            f"effort for model {model!r} on the {wire} wire; canonical levels: "
            f"{', '.join(canonical)}"
            + (f" (compatibility aliases: {', '.join(sorted(aliases))})" if aliases else "")
        )

    emitted = "disabled" if (wire == WIRE_CHAT and normalized == DISABLED) else normalized
    return ReasoningApplication(
        wire=wire,
        requested=thinking,
        normalized=normalized,
        emitted=emitted,
        provenance=provenance,
    )


def validate_configured_thinking(*, model: Any, wire: str, thinking: Any) -> None:
    """Validate a manifest/preset value against the exact selected route.

    Configuration ingress delegates here instead of testing a kernel-global
    level tuple, so a manifest can only carry what this route really accepts.
    """
    apply_reasoning(model=model, wire=wire, thinking=thinking)


def validate_llm_block(llm: Mapping[str, Any], *, wire: str | None = None) -> None:
    """Validate the DeepSeek-owned parts of one manifest/preset ``llm`` block."""
    if "thinking" not in llm:
        return
    validate_configured_thinking(
        model=llm.get("model"),
        wire=wire if wire is not None else wire_for(llm),
        thinking=llm["thinking"],
    )
