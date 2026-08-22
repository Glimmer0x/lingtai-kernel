"""Built-in tool packaging: a tool package that *is* an Agent Plugin.

The curated MCP servers went first (``lingtai/mcp_servers/_plugin.py``): one
folder owns its server code, its bundled ``SKILL.md``, and the declaration the
runtime reads for it. This module is the same idea one layer up, for the
model-facing tools in ``lingtai/tools/`` — and it goes the whole way, because up
here the kernel already *has* a plugin standard and a plugin reader.

A built-in tool plugin is a real **Agent Plugins v1.0.0** package
(https://agent-plugins.org), the same shape ``lingtai/services/plugin_registry.py``
reads for a third-party plugin dropped on a configured path:

    lingtai/tools/<tool>/
        plugin.json                      # required manifest ($schema + name)
        skills/<manual skill>/SKILL.md   # the tool's manual, as an owned skill
        ...                              # the tool's Python module, as before

Three things follow from that, and all three are the point:

- **The manifest is the identity.** ``plugin.json`` states the model-facing
  name; the ``ai.lingtai.tool`` client-extension namespace (the reverse-domain
  namespace §3 reserves for exactly this) states which Python package ships it
  and which of its skills is the capability manual. A descriptor that disagrees
  with the manifest raises at import, so a package cannot say one thing in code
  and another in the file the runtime reads.
- **The manual is an owned skill, not a convention.** It lives under the
  plugin's ``skills/``, is discovered as a skill by the very same
  ``read_plugin`` scan a third-party plugin gets, and is what the reserved
  ``manual`` action serves. The pre-plugin ``manual/`` directory convention was
  invisible to that scan; this one is not.
- **Discovery is validation.** :func:`discover_tool_plugin` does not re-implement
  the specification — it calls ``plugin_registry.read_plugin``, so a built-in
  tool plugin is held to the same manifest grammar and the same §4.1 path
  containment as anything an operator installs. A packaging defect surfaces as a
  problem record rather than a silently missing manual.

What this module deliberately is **not** is a second plugin runtime. It
discovers nothing by itself (a package hands it its own root), registers
nothing, spawns nothing, and reads no configuration. In particular a built-in
tool plugin is expected to ship **no** ``mcp.json``: pluginizing a tool must
never become a way to put an MCP server into ``mcp_registry.jsonl``, and
registration/activation stays exactly where it was — ``register_plugins`` for
declared external plugins, an explicit ``init.json`` top-level ``mcp`` entry for
activation. Mounting the discovered skills into the agent's intrinsic library
remains the host's job (``Agent._install_intrinsic_manuals``); this module only
tells it what a manifest declares.

The one hard promise, inherited from the curated layer, is the reserved
``manual`` action (``tools/CONTRACT.md``): a package declares only its *own*
actions and this module appends ``manual``, bound to the manifest-declared owned
skill. A package that tries to declare, re-schema, or re-handle ``manual``
raises :class:`BuiltinToolPluginError` at import rather than shipping a family
whose manual is missing or points somewhere other than its packaged skill.
"""
from __future__ import annotations

import copy
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

from lingtai.kernel._frontmatter import split_frontmatter

from .tool_family import RESERVED_MANUAL_NAME, ChildTool, ToolFamily
from .tool_family.manual import MANUAL_INPUT_SCHEMA, build_manual_child

__all__ = [
    "MANIFEST_FILENAME",
    "MANUAL_ACTION",
    "MCP_CONFIG_FILENAME",
    "SKILLS_DIRNAME",
    "SKILL_FILENAME",
    "TOOL_EXTENSION_NAMESPACE",
    "BuiltinToolPlugin",
    "BuiltinToolPluginError",
    "discover_tool_plugin",
    "strict_empty_input_schema",
]

#: Agent Plugins v1.0.0 filenames. Spelled here so a tool package never writes
#: the literals itself; ``tests/test_builtin_tool_plugin_package.py`` pins them
#: equal to ``lingtai.services.plugin_registry``'s, which stays the one owner of
#: the specification (this layer must not fork it).
MANIFEST_FILENAME = "plugin.json"
MCP_CONFIG_FILENAME = "mcp.json"
SKILLS_DIRNAME = "skills"
SKILL_FILENAME = "SKILL.md"

#: The reverse-domain client-extension namespace §3 reserves for a client's own
#: keys. LingTai's built-in tool packages carry exactly two: ``package`` (the
#: Python package that ships this plugin) and ``manual_skill`` (which of the
#: plugin's owned skills is the capability manual). Both are agreements the
#: descriptor checks; neither is read by ``plugin_registry``, which ignores
#: extension namespaces it does not own.
TOOL_EXTENSION_NAMESPACE = "ai.lingtai.tool"

#: The reserved action name. Owned by ``lingtai.tools.tool_family``; re-exported
#: here so a tool package never spells the literal itself.
MANUAL_ACTION = RESERVED_MANUAL_NAME


class BuiltinToolPluginError(ValueError):
    """Raised for a built-in tool packaging defect (bad manifest or shape)."""


def strict_empty_input_schema() -> dict[str, Any]:
    """The canonical closed, argument-free ``input`` schema for an action."""
    return copy.deepcopy(MANUAL_INPUT_SCHEMA)


def _manifest_extension(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Return the ``ai.lingtai.tool`` extension block, or ``{}``."""
    extensions = manifest.get("extensions")
    if not isinstance(extensions, Mapping):
        return {}
    block = extensions.get(TOOL_EXTENSION_NAMESPACE)
    return dict(block) if isinstance(block, Mapping) else {}


@dataclass(frozen=True)
class BuiltinToolPlugin:
    """One built-in tool package's manifest identity and owned manual skill.

    ``name`` is the model-facing tool name, the manifest ``name``, and the
    directory the manual mounts under in the agent's intrinsic library — one
    value, stated once. ``package`` is the Python package that ships the
    manifest, and ``manual_skill`` is the ``skills/`` subdirectory holding the
    manual. All three are re-stated by ``plugin.json`` and checked against it at
    construction, so a package that renames its manual, moves to another module,
    or edits the manifest alone fails at import instead of shipping a manual the
    ``manual`` action cannot find.

    Construction reads the manifest and the owned skill; it validates neither
    against the specification (``plugin_registry`` owns that, reached through
    :meth:`read_record`) nor against any agent, registry, or configuration. It
    mounts, registers, and launches nothing.
    """

    name: str
    package: str
    manual_skill: str

    # Loaded from the package's own files at construction. Excluded from
    # init/repr/eq: derived material, not part of the declared identity.
    _root: Path = field(init=False, repr=False, compare=False)
    _manifest: dict[str, Any] = field(init=False, repr=False, compare=False)
    _skill_frontmatter: dict[str, str] = field(init=False, repr=False, compare=False)
    _skill_body: str = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        for attribute in ("name", "package", "manual_skill"):
            value = getattr(self, attribute)
            if not isinstance(value, str) or not value.strip():
                raise BuiltinToolPluginError(
                    f"BuiltinToolPlugin {attribute!r} must be a non-empty string"
                )

        root = Path(str(resources.files(self.package)))
        manifest_path = root / MANIFEST_FILENAME
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise BuiltinToolPluginError(
                f"BuiltinToolPlugin {self.name!r} cannot read its "
                f"{MANIFEST_FILENAME}: {e}"
            ) from e
        if not isinstance(manifest, dict):
            raise BuiltinToolPluginError(
                f"BuiltinToolPlugin {self.name!r} {MANIFEST_FILENAME} must be a JSON object"
            )
        if manifest.get("name") != self.name:
            raise BuiltinToolPluginError(
                f"BuiltinToolPlugin {self.name!r} {MANIFEST_FILENAME} declares name "
                f"{manifest.get('name')!r}; the manifest names the tool"
            )

        extension = _manifest_extension(manifest)
        if extension.get("package") != self.package:
            raise BuiltinToolPluginError(
                f"BuiltinToolPlugin {self.name!r} {MANIFEST_FILENAME} "
                f"{TOOL_EXTENSION_NAMESPACE} declares package "
                f"{extension.get('package')!r}, expected {self.package!r}"
            )
        if extension.get("manual_skill") != self.manual_skill:
            raise BuiltinToolPluginError(
                f"BuiltinToolPlugin {self.name!r} {MANIFEST_FILENAME} "
                f"{TOOL_EXTENSION_NAMESPACE} declares manual_skill "
                f"{extension.get('manual_skill')!r}, expected {self.manual_skill!r}"
            )

        skill_file = root / SKILLS_DIRNAME / self.manual_skill / SKILL_FILENAME
        try:
            text = skill_file.read_text(encoding="utf-8")
        except OSError as e:
            raise BuiltinToolPluginError(
                f"BuiltinToolPlugin {self.name!r} cannot read its owned manual skill "
                f"{self.manual_skill!r} at {skill_file}: {e}"
            ) from e
        frontmatter, body = split_frontmatter(text)
        if frontmatter.get("name") != self.manual_skill:
            raise BuiltinToolPluginError(
                f"BuiltinToolPlugin {self.name!r} owned {SKILL_FILENAME} declares name "
                f"{frontmatter.get('name')!r}, expected {self.manual_skill!r}"
            )
        if not body.strip():
            raise BuiltinToolPluginError(
                f"BuiltinToolPlugin {self.name!r} owned {SKILL_FILENAME} has an empty body"
            )

        object.__setattr__(self, "_root", root)
        object.__setattr__(self, "_manifest", manifest)
        object.__setattr__(self, "_skill_frontmatter", frontmatter)
        object.__setattr__(self, "_skill_body", body)

    # -- manifest ----------------------------------------------------------

    @property
    def root(self) -> Path:
        """The plugin root — the directory carrying ``plugin.json``."""
        return self._root

    @property
    def manifest(self) -> dict[str, Any]:
        """The parsed ``plugin.json``, copied so callers cannot mutate it."""
        return copy.deepcopy(self._manifest)

    @property
    def manifest_path(self) -> Path:
        """Absolute resolved path of the packaged ``plugin.json``."""
        return self._root / MANIFEST_FILENAME

    @property
    def version(self) -> str:
        """The manifest ``version``, or ``""`` when the manifest omits it."""
        value = self._manifest.get("version")
        return value if isinstance(value, str) else ""

    def read_record(self) -> tuple[dict | None, list[dict]]:
        """Read this plugin through the host's Agent Plugins reader.

        Delegates to ``lingtai.services.plugin_registry.read_plugin`` — the same
        function that reads a third-party plugin — so specification validation
        has exactly one owner and a built-in package cannot grant itself a
        laxer manifest grammar or a laxer §4.1 containment rule. Reading is not
        registering: no registry line is written and nothing is launched.

        Imported lazily inside the method per the ``lingtai.tools → lingtai``
        lazy-back-edge rule (``lingtai/tools/__init__.py``).
        """
        from lingtai.services.plugin_registry import read_plugin

        return read_plugin(self._root)

    # -- owned manual skill -------------------------------------------------

    @property
    def skill_dir(self) -> Path:
        """Absolute directory of the owned manual skill."""
        return self._root / SKILLS_DIRNAME / self.manual_skill

    @property
    def skill_path(self) -> Path:
        """Absolute path of the owned manual skill's ``SKILL.md``."""
        return self.skill_dir / SKILL_FILENAME

    @property
    def skill_frontmatter(self) -> dict[str, str]:
        """Parsed owned-``SKILL.md`` frontmatter (the manual's catalog entry)."""
        return dict(self._skill_frontmatter)

    @property
    def skill_body(self) -> str:
        """The owned ``SKILL.md`` markdown body."""
        return self._skill_body

    @property
    def mount_name(self) -> str:
        """Where the host mounts the owned manual in the intrinsic library.

        ``.library/intrinsic/capabilities/<mount_name>/`` — the manifest name,
        so the model-facing tool name, the manifest name, and the installed
        manual directory are one value rather than three that can drift. The
        reserved ``manual`` action serves the mounted copy: the plugin owns the
        source, the host owns the agent-local mount it hands the model.
        """
        return self.name

    def manual_child(self, agent: Any | None) -> ChildTool:
        """Build this plugin's reserved ``manual`` child.

        With an ``agent``, the canonical generic child bound to this plugin's
        mount name. With ``None``, a schema-only stub whose handler raises if a
        module-level schema-only family ever dispatches it.
        """
        if agent is None:
            def _unused(_input: Mapping[str, Any]) -> dict[str, Any]:
                raise AssertionError(
                    "the module-level schema-only ToolFamily never dispatches"
                )

            return ChildTool(
                MANUAL_ACTION,
                strict_empty_input_schema(),
                _unused,
                title="manual input",
            )
        return build_manual_child(agent, self.mount_name)

    # -- family composition -------------------------------------------------

    def actions(self, declared: Sequence[str]) -> tuple[str, ...]:
        """Declared actions plus the reserved ``manual``, in that order."""
        self._check_declared_names(declared)
        return (*declared, MANUAL_ACTION)

    def action_input_schemas(
        self, declared: Mapping[str, Mapping[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        """Declared ``input`` schemas plus the reserved ``manual`` schema."""
        self._check_declared_names(tuple(declared))
        schemas: dict[str, dict[str, Any]] = {
            action: copy.deepcopy(dict(schema)) for action, schema in declared.items()
        }
        schemas[MANUAL_ACTION] = strict_empty_input_schema()
        return schemas

    def build_family(
        self, declared: Sequence[ChildTool], agent: Any | None = None
    ) -> ToolFamily:
        """Compose this plugin's one public family, ``manual`` always appended."""
        self._check_declared_names([child.name for child in declared])
        return ToolFamily(self.name, [*declared, self.manual_child(agent)])

    def _check_declared_names(self, declared: Sequence[str]) -> None:
        names = list(declared)
        if not names:
            raise BuiltinToolPluginError(
                f"BuiltinToolPlugin {self.name!r} must declare at least one action"
            )
        if MANUAL_ACTION in names:
            raise BuiltinToolPluginError(
                f"BuiltinToolPlugin {self.name!r} must not declare the reserved "
                f"{MANUAL_ACTION!r} action; it is appended from the owned "
                f"{self.manual_skill!r} skill"
            )
        if len(set(names)) != len(names):
            raise BuiltinToolPluginError(
                f"BuiltinToolPlugin {self.name!r} declared a duplicate action"
            )


# ---------------------------------------------------------------------------
# Runtime discovery / mount plan
# ---------------------------------------------------------------------------

def discover_tool_plugin(root: Path) -> tuple[dict | None, list[dict]]:
    """Discover the built-in tool plugin rooted at ``root``, if there is one.

    Returns ``(mount_plan, problems)``. ``mount_plan`` is ``None`` when ``root``
    carries no ``plugin.json`` (a pre-plugin tool package, which the host still
    installs by the legacy ``manual/`` convention) or when the manifest is
    rejected outright — the whole-plugin failure boundary ``read_plugin`` owns.
    Component-level failures leave the plan intact and are reported in
    ``problems``, the per-component boundary of §4.1.

    The plan is a list of ``(destination name, source directory)`` pairs and
    nothing more: this function copies no file, writes no registry line, and
    launches nothing. The manifest-declared manual skill mounts under the
    plugin's own name — that is what makes ``.library/intrinsic/capabilities/
    <tool>/SKILL.md``, the path the reserved ``manual`` action reads, the
    mounted copy of a skill the plugin owns. Any further owned skill mounts
    under its own catalog label.

    A built-in tool plugin that ships an ``mcp.json`` is a packaging error, not
    a feature: this layer is the model-facing tool surface, and mounting a tool
    must never become a path to registering an MCP server. Such a plugin is
    reported as a problem and its servers are named but never registered — this
    function has no registry write to reach in the first place.
    """
    root = Path(root)
    if not (root / MANIFEST_FILENAME).is_file():
        return None, []

    from lingtai.services.plugin_registry import read_plugin

    record, problems = read_plugin(root)
    problems = list(problems)
    if record is None:
        return None, problems

    manual_skill = ""
    try:
        manifest = json.loads((root / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):  # pragma: no cover - read_plugin just parsed it
        manifest = {}
    if isinstance(manifest, Mapping):
        # The extension namespace is client-specific by design, so the shared
        # record ``read_plugin`` builds does not carry it; re-reading the two
        # keys here keeps the specification's reader free of LingTai's own.
        manual_skill = str(_manifest_extension(manifest).get("manual_skill") or "")

    if record["mcp_servers"]:
        problems.append({
            "plugin": record["name"],
            "path": str(root / MCP_CONFIG_FILENAME),
            "error": (
                f"built-in tool plugin {record['name']!r} declares MCP servers "
                f"{record['mcp_servers']!r}; a tool package must not carry "
                f"{MCP_CONFIG_FILENAME} — they are not registered"
            ),
        })

    by_label = dict(zip(record["skills"], record["skill_paths"]))
    mounts: list[tuple[str, str]] = []
    if manual_skill and manual_skill in by_label:
        mounts.append((record["name"], by_label.pop(manual_skill)))
    elif manual_skill:
        problems.append({
            "plugin": record["name"],
            "path": str(root / SKILLS_DIRNAME / manual_skill),
            "error": (
                f"manifest declares manual_skill {manual_skill!r}, which is not "
                f"an owned skill of this plugin"
            ),
        })
    mounts.extend((label, path) for label, path in by_label.items())

    plan = {
        "name": record["name"],
        "version": record["version"],
        "manual_skill": manual_skill,
        "source": record["source"],
        "mounts": mounts,
    }
    return plan, problems
