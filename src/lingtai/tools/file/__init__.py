"""The declared official ``file`` host plugin.

``file`` remains one public LTP-v2 family with the unchanged six actions
``read``, ``write``, ``edit``, ``glob``, ``grep``, and ``manual``. This module
now declares that surface statically and binds it only through the kernel's
least-privilege host facade: the current workdir, File's narrow I/O service
port, and no whole Agent. The operation modules retain their real behavior and
raw result shapes; this module only composes them and hands the bound plugin to
the host-owned official registrar.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Mapping

from lingtai.kernel.tool_plugin import BoundToolPlugin, ToolPluginDeclaration

from ..tool_family import ChildTool, ToolFamily
from ..tool_family.manual import MANUAL_INPUT_SCHEMA, build_manual_child
from . import _edit, _glob, _grep, _read, _write

if TYPE_CHECKING:
    from lingtai.kernel.base_agent import BaseAgent
    from lingtai.kernel.tool_plugin import ToolPluginHost


PROVIDERS = {"providers": [], "default": "builtin"}

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

# This family owns five operational actions. The kernel appends the reserved
# manual slot from ``DECLARATION.manual_input_schema`` exactly once and last.
_DECLARED_ACTIONS: tuple[str, ...] = ("read", "write", "edit", "glob", "grep")
_DECLARED_SCHEMAS_BY_ACTION: dict[str, dict[str, Any]] = {
    "read": _READ_INPUT_SCHEMA,
    "write": _WRITE_INPUT_SCHEMA,
    "edit": _EDIT_INPUT_SCHEMA,
    "glob": _GLOB_INPUT_SCHEMA,
    "grep": _GREP_INPUT_SCHEMA,
}
if tuple(_DECLARED_SCHEMAS_BY_ACTION) != _DECLARED_ACTIONS:
    raise AssertionError("File action order and input-schema inventory diverged")

_OPERATION_MODULES = (_read, _write, _edit, _glob, _grep)


def _unused(_input: Mapping[str, Any]) -> dict[str, Any]:
    raise AssertionError("the module-level schema-only ToolFamily never dispatches")


def _build_family(host: "ToolPluginHost | None") -> ToolFamily:
    """Compose File's declared children with or without a granted host.

    The import-time schema-only build and the per-agent dispatching build share
    this one ordered declaration, so public action names and strict input
    schemas cannot drift from the family that actually dispatches. A real host
    grants precisely the ports the operation modules consume; no operation
    receives the live Agent or a generic service object.
    """
    children: list[ChildTool] = []
    if host is None:
        handlers: tuple[Callable[[Mapping[str, Any]], dict[str, Any]], ...] = (
            _unused,
            _unused,
            _unused,
            _unused,
            _unused,
        )
    else:
        # ToolFamily validates the strict nullable shape first. Only the child
        # adapter translates its declared nulls to absent operation arguments,
        # preserving the historic per-operation defaults without weakening the
        # public schema.
        handlers = tuple(
            lambda action_input, operation=module.build_operation(
                host.workdir, host.file_io
            ): operation(_strip_nulls(action_input))
            for module in _OPERATION_MODULES
        )
    for action, handler in zip(_DECLARED_ACTIONS, handlers, strict=True):
        children.append(
            ChildTool(
                action,
                DECLARATION.input_schemas[action],
                handler,
                title=f"{action} input",
            )
        )
    if host is None:
        children.append(
            ChildTool(
                "manual",
                DECLARATION.manual_input_schema,
                _unused,
                title="manual input",
            )
        )
    else:
        children.append(build_manual_child(host.workdir, DECLARATION.manual))
    return ToolFamily(DECLARATION.name, children)


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
        "for the installed file-manual. Read file-manual before non-UTF-8 files "
        "or a careful search/edit workflow; it also carries the nested "
        "read-manual reference for read pagination, truncation, and "
        "line_truncated depth, plus the bash/Python metadata workflow (file "
        "size, line count, longest line) for content read cannot page cleanly. "
        "After the manual result continue the original operation instead of "
        "repeating manual, because repeated identical manual calls are an "
        "error loop."
    )


def get_schema(lang: str = "en") -> dict[str, Any]:
    # Generic ToolFamily composition owns the LTP envelope and action/input
    # correlation. ``_FAMILY`` is schema-only; the registrar binds the real
    # same declaration to a narrow host later.
    return _FAMILY.build_schema()


def _strip_nulls(action_input: Mapping[str, Any]) -> dict[str, Any]:
    """Translate strict-schema nulls back to absent operation arguments."""
    return {key: value for key, value in action_input.items() if value is not None}


def _bind(host: "ToolPluginHost") -> BoundToolPlugin:
    """Purely compose File against its granted ports; mount nothing."""
    family = _build_family(host)

    return BoundToolPlugin(
        name=DECLARATION.name,
        schema=get_schema(),
        handler=family.handle,
        description=get_description(),
        glossary_package=__package__,
    )


DECLARATION = ToolPluginDeclaration(
    name="file",
    actions=_DECLARED_ACTIONS,
    input_schemas=_DECLARED_SCHEMAS_BY_ACTION,
    manual_input_schema=MANUAL_INPUT_SCHEMA,
    # The packaged ``manual/SKILL.md`` is installed at capabilities/file. Its
    # frontmatter remains ``name: file-manual`` as the manual's user-facing
    # skill identity, but it is not a competing installed destination.
    manual="file",
    description=get_description(),
    binder=_bind,
    requires=("workdir", "file_io"),
    glossary_package=__package__,
)

# Compatibility aliases for internal callers; both are derived from the one
# static declaration rather than restated tool identity.
ACTIONS = DECLARATION.public_actions
FAMILY_MANUAL_SKILL = DECLARATION.manual

# Construct after DECLARATION because the builder derives every public fact from
# it. The kernel validates the matching advertised enum again on each bind.
_FAMILY = _build_family(None)


def setup(agent: "BaseAgent", **_ignored) -> None:
    """Register File through the official host-plugin route.

    The registrar reserves ``file``, grants only its workdir and file-I/O
    ports, binds this declaration, and mounts the resulting family. Re-running
    setup on refresh is idempotent for this exact declaration.
    """
    from lingtai.adapters.tool_plugin_host import register_agent_tool_plugins

    register_agent_tool_plugins(agent, [DECLARATION])
