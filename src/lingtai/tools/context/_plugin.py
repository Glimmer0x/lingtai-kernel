"""Package-local model-facing surface for the ``context`` root.

``ContextToolPlugin`` is deliberately a small ownership seam, not an Agent
Plugin descriptor and not an activation mechanism.  The existing intrinsic
registration continues to import ``context.__init__`` under the same root name;
that module constructs the one surface below and delegates its public schema
and dispatch entry points to it.

The seam owns work that is genuinely model-facing and context-specific:

* composing the exact action registry into the ``context`` schema;
* binding validated action input to the existing molt/summarize/rebuild engines;
* threading intrinsic transport metadata only to ``molt``; and
* registering the real reserved manual child, then flattening its dispatched
  result at Context's own presentation boundary.

It deliberately does *not* own Agent registration, prompt reconstruction,
summary persistence, session-journal validation, provider lifecycle, or plugin
activation.  Those remain in their current owners and the handlers supplied by
``context.__init__`` are invoked unchanged.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

from ..tool_family import ChildTool, DiagnosticDescriptor, ToolFamily
from ..tool_family.manual import build_manual_child


ActionSpec = tuple[str, Mapping[str, Any], Callable[[Any, dict], dict]]


class ContextToolPlugin:
    """Own Context's one actual model-facing schema/dispatch/manual surface.

    The supplied action-spec getter deliberately remains live rather than taking
    a copied registry: Context's module-level schema-only family and every
    agent-bound dispatcher must keep deriving from the same source.  This object
    creates the import-time schema family only to preserve the existing
    duplicate/reserved-name collision check; each dispatch still binds the
    current Agent exactly once.
    """

    def __init__(
        self,
        *,
        root_name: str,
        action_specs: Callable[[], Sequence[ActionSpec]],
        child_diagnostics: Mapping[str, Mapping[str, DiagnosticDescriptor]],
        manual_skill_name: str,
        molt_envelope_keys: tuple[str, ...],
        action_enum_description: str,
        description: str,
    ) -> None:
        self.root_name = root_name
        self._action_specs = action_specs
        self._child_diagnostics = child_diagnostics
        self._manual_skill_name = manual_skill_name
        self._molt_envelope_keys = molt_envelope_keys
        self._action_enum_description = action_enum_description
        self._description = description
        # Construction retains Context's existing import-time registry collision
        # check.  It never dispatches: its children are schema-only bindings.
        self._schema_family = ToolFamily(root_name, self.build_children(None))

    @property
    def action_order(self) -> tuple[str, ...]:
        """The current public action order derived from the one child registry."""
        return tuple(name for name, _schema, _handler in self._action_specs()) + ("manual",)

    @property
    def schema_family(self) -> ToolFamily:
        """Return the import-time schema-only family used by ``get_schema``."""
        return self._schema_family

    @staticmethod
    def _strip_nulls(action_input: Mapping[str, Any]) -> dict[str, Any]:
        """Normalize explicit nullable provider values to absent handler input."""
        return {key: value for key, value in action_input.items() if value is not None}

    def build_children(
        self, agent: Any, envelope: Mapping[str, Any] | None = None
    ) -> list[ChildTool]:
        """Bind Context's one canonical registry to a schema or a live Agent.

        No envelope field reaches a child generically.  Context's molt is the
        narrow exception: it consumes the intrinsic ``_tc_id`` transport value
        in order to replay its own call, so only that handler receives the
        explicitly lifted metadata out-of-band.
        """
        extra = dict(envelope or {})
        children: list[ChildTool] = []
        for name, schema, handler in self._action_specs():

            def dispatch(action_input: Mapping[str, Any], *, _name=name, _handler=handler) -> dict:
                args = self._strip_nulls(action_input)
                if _name == "molt":
                    # Transport metadata never overwrites validated action input.
                    for key, value in extra.items():
                        args.setdefault(key, value)
                return _handler(agent, args)

            children.append(
                ChildTool(
                    name,
                    schema,
                    dispatch,
                    title=f"{name} input",
                    diagnostics=self._child_diagnostics.get(name),
                )
            )
        # Registered directly and unwrapped.  The family adapts the result only
        # after ToolFamily.handle() has returned this canonical child result.
        children.append(build_manual_child(agent, self._manual_skill_name))
        return children

    def get_description(self, lang: str = "en") -> str:
        """Return Context's established model-facing description unchanged."""
        del lang  # Canonical English prose is intentionally language-independent.
        return self._description

    def get_schema(self, lang: str = "en") -> dict[str, Any]:
        """Compose the Context root schema from the real child registry."""
        del lang  # Canonical English prose is intentionally language-independent.
        schema = self._schema_family.build_schema()
        schema["properties"]["action"]["description"] = self._action_enum_description
        return schema

    @staticmethod
    def _adapt_manual_result(mcp_result: dict) -> dict:
        """Flatten the dispatched ManualTool result to Context's public shape."""
        flat: dict[str, Any] = {
            "status": mcp_result.get("status", "ok"),
            "manual": mcp_result["content"][0]["text"],
            "manual_path": mcp_result["structuredContent"]["manual_path"],
        }
        if "error" in mcp_result:
            flat["error"] = mcp_result["error"]
        return flat

    def handle(self, agent: Any, args: Mapping[str, Any] | None) -> dict:
        """Validate one Context envelope and dispatch it to the selected action.

        The generic family remains the closed-root and cross-action validator.
        This Context-owned boundary performs only its established special cases:
        lift molt-only intrinsic metadata, restore root reasoning for generic
        validation, flatten the real manual-child result after dispatch, and
        preserve Context's public unknown-action wording.
        """
        raw = dict(args or {})
        envelope = {
            key: raw.pop(key) for key in self._molt_envelope_keys if key in raw
        }
        # ``reasoning``/``_reasoning`` are still generic root fields; only molt
        # sees their envelope copies for its post-molt reminder.
        for key in ("reasoning", "_reasoning"):
            if key in envelope:
                raw[key] = envelope[key]

        action = raw.get("action")
        result = ToolFamily(self.root_name, self.build_children(agent, envelope)).handle(raw)

        if action == "manual" and "content" in result:
            return self._adapt_manual_result(result)
        if result.get("error_code") == "ACTION_REQUIRED":
            return {
                "error": (
                    f"Unknown {self.root_name} action: "
                    f"{action if action is not None else ''}. Must be one of: "
                    f"{', '.join(self.action_order)}."
                )
            }
        return result
