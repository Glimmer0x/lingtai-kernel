"""Unified ``file`` capability: read, write, edit, grep, glob, and its manual.

This package is the single owner of the one public ``file`` tool: the composed
model-facing schema, the envelope dispatch, and all five operation
implementations (``_read``, ``_write``, ``_edit``, ``_glob``, ``_grep``). The
five pre-migration model-facing roots are gone, and so are their packages —
their behavior lives here unchanged: UTF-8 boundary, absolute-path/workdir
resolution, numbered-line read output, continuation metadata, ``max_chars``
cap, ``line_truncated``, edit ambiguity/missing handling, the full-write
receipt, glob sorting, and grep regex/line/path results and caps.

The package is plugin-packaged (``plugin.py``, ``.._plugin``): ``FILE_PLUGIN``
is the one declaration of the capability's identity — its registry module, boot
defaults, provider metadata, packaged ``manual/SKILL.md``, and the five actions
this package owns. The public schema, the dispatching family, ``PROVIDERS``, and
the ``setup()`` mount are all composed from it, and the reserved ``manual`` child
is appended by the plugin rather than registered by :class:`FileManager`.

Per ``../CONTRACT.md`` "Implementation independence", the six children share
nothing but the family name and the wire envelope: each operation module is
self-contained and none imports another. Each child's canonical raw result is
returned verbatim by ``ToolFamily.handle``; this module adds no result envelope
and no second summarizer.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Mapping, Sequence

from .._plugin import ToolPluginError
from ..tool_family import ChildTool, ToolFamily
from . import _edit, _glob, _grep, _read, _write
from .plugin import FILE_ACTIONS, FILE_DECLARED_ACTIONS, FILE_PLUGIN

if TYPE_CHECKING:
    from lingtai.kernel.base_agent import BaseAgent

# Provider metadata for ``registry.get_all_providers``, sourced from the one
# declaration rather than restated here.
PROVIDERS = FILE_PLUGIN.providers_declaration()

# The one family-owned manual, packaged in this plugin as ``manual/SKILL.md``
# (frontmatter name ``file-manual``) and installed by the host into
# ``.library/intrinsic/capabilities/file/``. ``read-manual`` remains a nested
# parent-owned reference it points at for read pagination/truncation depth, not
# a competing second top-level manual action.
FAMILY_MANUAL_SKILL = FILE_PLUGIN.manual_destination

_READ_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "file_path": {
            "type": "string",
            "description": "Absolute path to the file to read; a relative path resolves under the agent working directory.",
        },
        "offset": {
            "type": ["integer", "null"],
            "description": "Line number to start from (1-based), or null for the default 1.",
        },
        "limit": {
            "type": ["integer", "null"],
            "description": "Max lines to read, or null for the default 2000.",
        },
        "max_chars": {
            "type": ["integer", "null"],
            "description": "Per-call character budget for read content, or null for the default 100 000. Values above the non-configurable runtime hard cap are clamped to 200 000.",
        },
    },
    "required": ["file_path", "offset", "limit", "max_chars"],
    "additionalProperties": False,
}

_WRITE_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "file_path": {
            "type": "string",
            "description": "Absolute path to the file to write; parent directories are created automatically.",
        },
        "content": {"type": "string", "description": "Full content to write."},
    },
    "required": ["file_path", "content"],
    "additionalProperties": False,
}

_EDIT_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "file_path": {"type": "string", "description": "Absolute path to the file to edit."},
        "old_string": {"type": "string", "description": "The exact text to find and replace."},
        "new_string": {"type": "string", "description": "The replacement text."},
        "replace_all": {
            "type": ["boolean", "null"],
            "description": "Replace all occurrences, or null for the default false.",
        },
    },
    "required": ["file_path", "old_string", "new_string", "replace_all"],
    "additionalProperties": False,
}

_GREP_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "pattern": {"type": "string", "description": "Regex pattern to search for."},
        "path": {
            "type": ["string", "null"],
            "description": "File or directory to search in, or null for the agent working directory.",
        },
        "glob": {
            "type": ["string", "null"],
            "description": "File glob filter (e.g. '*.py'), or null for the default '*' (no filter).",
        },
        "max_matches": {
            "type": ["integer", "null"],
            "description": "Maximum matches to return, or null for the default 200.",
        },
    },
    "required": ["pattern", "path", "glob", "max_matches"],
    "additionalProperties": False,
}

_GLOB_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "pattern": {"type": "string", "description": "Glob pattern (e.g. '**/*.py'); use '**/' for recursive search."},
        "path": {
            "type": ["string", "null"],
            "description": "Directory to search in, or null for the agent working directory.",
        },
    },
    "required": ["pattern", "path"],
    "additionalProperties": False,
}

# This package's own five actions, keyed by public action name. ``manual`` is
# deliberately absent: the plugin appends the reserved action from the packaged
# ``manual/SKILL.md`` and rejects any attempt to declare it here.
_DECLARED_SCHEMAS_BY_ACTION: dict[str, dict[str, Any]] = {
    "read": _READ_INPUT_SCHEMA,
    "write": _WRITE_INPUT_SCHEMA,
    "edit": _EDIT_INPUT_SCHEMA,
    "glob": _GLOB_INPUT_SCHEMA,
    "grep": _GREP_INPUT_SCHEMA,
}
if set(_DECLARED_SCHEMAS_BY_ACTION) != set(FILE_DECLARED_ACTIONS):
    raise ToolPluginError(
        "file declares an action without an input schema (or the reverse): "
        f"{sorted(FILE_DECLARED_ACTIONS)} vs {sorted(_DECLARED_SCHEMAS_BY_ACTION)}"
    )

# Canonical child order comes from the plugin's declared action list, so the
# schema branch order and the dispatch registry order are the same one fact.
_DECLARED_SCHEMAS: dict[str, dict[str, Any]] = {
    action: _DECLARED_SCHEMAS_BY_ACTION[action] for action in FILE_DECLARED_ACTIONS
}

# Every public action's own strict ``input`` schema — the five declared above
# plus the plugin-appended reserved ``manual``.
ACTION_INPUT_SCHEMAS: dict[str, dict[str, Any]] = FILE_PLUGIN.action_input_schemas(
    _DECLARED_SCHEMAS
)

#: The complete public action list. Aliases the plugin's composed list so this
#: module never restates the action set the schema is built from.
ACTIONS: tuple[str, ...] = FILE_ACTIONS

# The five operation modules, in the plugin's declared action order.
_OPERATION_MODULES = (_read, _write, _edit, _glob, _grep)


def _unused(_input: Mapping[str, Any]) -> dict[str, Any]:
    raise AssertionError("the module-level schema-only ToolFamily never dispatches")


def _build_family(
    agent: "BaseAgent | None" = None,
    handlers: Sequence[Callable[[Mapping[str, Any]], dict[str, Any]]] | None = None,
) -> ToolFamily:
    """Build the six-child ``file`` family through the plugin descriptor.

    This builder declares only this package's five operations; the reserved
    ``manual`` child is appended by :data:`~.plugin.FILE_PLUGIN`, bound to the
    manual destination the plugin declares. One builder serves both uses, so
    the schema the model sees and the registry that actually dispatches can
    never drift apart. With *handlers* omitted the result is schema-only: every
    declared child gets a handler that raises, which is what module-level
    :data:`_FAMILY` uses to compose :func:`get_schema` and to prove at import
    time that the fixed registry has no duplicate or reserved-name collision
    (``ToolPluginError``/``ToolFamilyError`` would raise here rather than
    shipping silently). :class:`FileManager` passes real agent-bound handlers
    plus the agent the plugin binds ``manual`` to.
    """
    children = []
    for index, name in enumerate(FILE_DECLARED_ACTIONS):
        handler = handlers[index] if handlers is not None else _unused
        children.append(
            ChildTool(name, ACTION_INPUT_SCHEMAS[name], handler, title=f"{name} input")
        )
    return FILE_PLUGIN.build_family(children, agent)


_FAMILY = _build_family()


def get_description(lang: str = "en") -> str:
    return (
        "Unified file capability over one working tree. Use "
        "file(action='read', input={'file_path': '/abs/path', 'offset': null, "
        "'limit': null, 'max_chars': null}, reasoning='inspect the source') to "
        "read numbered lines of a text file; a successful read can still be "
        "truncated, so check truncated, next_offset, remaining_lines_estimate, "
        "and line_truncated and continue from next_offset until done. Use "
        "file(action='write', ...) to create or overwrite a whole file and "
        "file(action='edit', ...) for an exact string replacement in an "
        "existing file — both mutate the working tree and return a receipt, but "
        "neither reloads or mutates the current system prompt. After changing a "
        "durable prompt source, call context(action='rebuild', input={}, ...) "
        "only when it must take effect now. Use "
        "file(action='glob', ...) to find files by pattern and "
        "file(action='grep', ...) to search file contents by regex. Text files "
        "only — this tool cannot read binary, images, or audio. Use "
        "file(action='manual', input={}, reasoning='load file guidance') once "
        f"for the installed {FILE_PLUGIN.skill_name}. Read "
        f"{FILE_PLUGIN.skill_name} before non-UTF-8 files "
        "or a careful search/edit workflow; it also carries the nested "
        "read-manual reference for read pagination, truncation, and "
        "line_truncated depth, plus the bash/Python metadata workflow (file "
        "size, line count, longest line) for content read cannot page cleanly. "
        "After the manual result continue the original operation instead of "
        "repeating manual, because repeated identical manual calls are an "
        "error loop."
    )


def get_schema(lang: str = "en") -> dict[str, Any]:
    # Composed by the generic ToolFamily infra from each child's own canonical
    # ``input_schema`` above, rather than hand-assembled: the root ``allOf``
    # if/then conditions correlate each ``action`` const with that exact
    # child's ``input`` shape on both the Chat and Responses wires, and the
    # retained ``input.oneOf`` discloses every action's shape in one place.
    return _FAMILY.build_schema()


def _strip_nulls(action_input: Mapping[str, Any]) -> dict[str, Any]:
    # Strict OpenAI schemas express optional fields as required nullable
    # properties. Null means absent to the operation handlers, which then apply
    # their own historical defaults.
    return {key: value for key, value in action_input.items() if value is not None}


class FileManager:
    """One per-Agent dispatcher over the six file children.

    It binds this package's five declared operations; the sixth child,
    ``manual``, belongs to :data:`~.plugin.FILE_PLUGIN` and is appended by it.
    Holds no mutable state of its own: each operation is bound once here and
    reaches the working tree only through the injected ``agent._file_io``
    service.
    """

    def __init__(self, agent: "BaseAgent") -> None:
        self._agent = agent
        operations = [
            self._bind(module.build_operation(agent)) for module in _OPERATION_MODULES
        ]
        # Only the five declared operations are bound here. The reserved
        # ``manual`` child is appended by ``FILE_PLUGIN`` from its packaged
        # skill's declared destination, so no change to this manager can drop
        # or rebind it. It is registered directly and unwrapped:
        # ``ToolFamily.handle()`` returns its own canonical MCP-compatible
        # result verbatim for ``action="manual"`` (no double wrap), and it
        # performs no target file operation.
        self._family = _build_family(agent, operations)

    @staticmethod
    def _bind(operation: Callable[[dict[str, Any]], dict[str, Any]]) -> Callable[[Mapping[str, Any]], dict[str, Any]]:
        """Adapt one operation to the child-handler signature.

        The only thing between dispatch and the operation is ``_strip_nulls``;
        nothing else is added to, removed from, or reshaped in either the input
        or the returned result.
        """
        def dispatch(action_input: Mapping[str, Any]) -> dict[str, Any]:
            return operation(_strip_nulls(action_input))

        return dispatch

    def handle(self, args: dict[str, Any] | None) -> dict[str, Any]:
        """Validate the envelope, dispatch, and return the child's raw result.

        The generic ``ToolFamily`` dispatcher validates ``action``, type-checks
        and strips root ``summarize``, rejects unknown root fields, and rejects
        ``input`` keys outside the selected action's own declared schema —
        before any handler I/O — then calls the selected operation with only
        that action's own ``input``. Each child's canonical result (including
        the ``manual`` child's ``content``/``structuredContent`` shape and every
        operation's own ``{"status": "error", ...}`` dict) is returned verbatim:
        this family adds no outer envelope, so a ``write``/``edit`` receipt is
        never restructured or hidden on its way back to the Host.
        """
        return self._family.handle(args)


def setup(agent: "BaseAgent") -> FileManager:
    """Compose the one public ``file`` tool on *agent*.

    The mounted tool name and glossary package come from
    :data:`~.plugin.FILE_PLUGIN`, so the capability the registry resolves, the
    family the schema advertises, and the tool actually registered on the agent
    are the same declared identity. Mounting itself stays the host's: this runs
    only because ``registry.setup_capability`` called it.
    """
    manager = FileManager(agent)
    agent.add_tool(
        FILE_PLUGIN.name,
        schema=get_schema(),
        handler=manager.handle,
        description=get_description(),
        glossary_package=FILE_PLUGIN.package,
    )
    return manager
