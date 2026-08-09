"""Agent Plugins registry infrastructure — discovery, validation, prompt XML.

This is the non-tool Agent Plugins machinery — a *service*, not an agent-callable
tool. The agent-facing ``plugin`` flagpost tool (which renders this data into the
system prompt) lives at ``lingtai/tools/plugin/`` and imports these helpers
lazily, exactly as ``lingtai/tools/mcp/`` imports ``mcp_registry``.

The standard is **Agent Plugins v1.0.0** (https://agent-plugins.org): a plugin is
a directory carrying a required ``plugin.json`` manifest (``$schema`` + ``name``),
optionally a ``skills/`` directory (one Agent Skill per immediate subdirectory
containing ``SKILL.md``), optionally an ``mcp.json`` MCP server configuration, and
optionally reverse-domain client-extension namespaces.

Contents: the canonical schema identifiers and filenames, the manifest name
grammar (``validate_manifest``), the §4.1 plugin-relative path containment rule
(``resolve_contained``), per-plugin discovery/validation (``read_plugin``),
multi-path scanning (``read_plugins``), boot-time **registration** of declared
plugins (``register_plugins``, ``prune_plugin_records``), and the system-prompt
XML renderer (``_build_registry_xml``).

**Two tiers, and the difference is the whole design.**

*Declared* plugins — the ones named in ``init.json`` ``manifest.plugins`` (the
canonical key) or its alias ``manifest.capabilities.plugin.paths`` — are
**registered** at boot by ``register_plugins``: each of their validated skill
directories is composed into the skills-catalog scan so their skills appear as
ordinary skills, and their ``mcp.json`` servers are translated into ``mcp_registry.jsonl``
records stamped ``source="plugin:<name>"`` through the *same* validator the
curated-addon decompression path uses. Registration is registry-level only: it
makes a plugin's server registrable and visible, exactly as ``addons:[]`` does.
Nothing is executed and no subprocess is spawned — activation still requires an
explicit ``init.json`` top-level ``mcp`` entry.

*Discovered* plugins — the ones merely found on an inherited
``manifest.capabilities.skills.paths`` directory — remain the original flagpost:
listed in the prompt, nothing mounted. Dropping a directory somewhere must never
silently mount an MCP server; only an explicit declaration does that.

Uninstall is the inverse of registration and needs no separate action: remove the
plugin from ``manifest.plugins`` and the next boot/refresh prunes every
``source="plugin:<name>"`` record whose owner is no longer declared. Pruning also
covers a server deleted from a still-declared plugin's ``mcp.json`` and a server
whose spec changed (dropped, then re-appended from the fresh spec), so the
registry converges on the declaration rather than accumulating.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)

#: Canonical Agent Plugins v1.0.0 schema identifiers. Per the specification a
#: client MUST NOT fetch these URLs while loading a plugin — they are compared
#: as opaque version identifiers against the versions this kernel understands.
PLUGIN_SCHEMA_URL = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
MCP_SCHEMA_URL = "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"

MANIFEST_FILENAME = "plugin.json"
MCP_CONFIG_FILENAME = "mcp.json"
SKILLS_DIRNAME = "skills"
SKILL_FILENAME = "SKILL.md"

#: Agent Plugins v1.0.0 ``name`` grammar, transcribed from plugin.schema.json:
#: lowercase alphanumerics plus ``.``/``-``, first and last characters
#: alphanumeric, no consecutive ``--`` or ``..``, 1–64 characters.
_NAME_RE = re.compile(r"^(?!.*(?:--|\.\.))[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")
_MAX_NAME_LEN = 64

#: Summary text rendered into the always-on prompt section is bounded so one
#: verbose manifest cannot dominate the catalog.
_MAX_SUMMARY_LEN = 200

#: MCP transports Agent Plugins v1.0.0 defines for ``mcp.json``.
_VALID_MCP_TYPES = {"stdio", "streamable-http", "sse"}

#: Agent Plugins v1.0.0 placeholder for the filesystem-resolved plugin root. A
#: value beginning with it is a plugin-relative path in disguise and is held to
#: the same §4.1 containment rule as the ``./`` form.
PLUGIN_ROOT_PLACEHOLDER = "${PLUGIN_ROOT}"

#: Every ``mcp_registry.jsonl`` record this module writes carries
#: ``source="plugin:<plugin name>"``. That stamp is what makes uninstall
#: mechanical: it identifies exactly which records a given plugin owns, so they
#: can be pruned without touching hand-written or addon-decompressed records.
PLUGIN_SOURCE_PREFIX = "plugin:"

#: Agent Plugins transports mapped onto the two the kernel registry models.
#: ``streamable-http`` and ``sse`` are both URL-addressed, so both land on the
#: registry's ``http``; the plugin's original ``type`` stays in ``mcp.json`` and
#: is reported in the plugin snapshot, never invented into the record.
_REGISTRY_TRANSPORTS = {
    "stdio": "stdio",
    "streamable-http": "http",
    "sse": "http",
}


def plugin_source(name: str) -> str:
    """The ``source`` stamp every registry record owned by ``name`` carries."""
    return f"{PLUGIN_SOURCE_PREFIX}{name}"


# ---------------------------------------------------------------------------
# §4.1 Path containment
# ---------------------------------------------------------------------------

def resolve_contained(root: Path, raw: object) -> tuple[Path | None, str | None]:
    """Resolve one plugin-relative path under §4.1, or explain the rejection.

    Agent Plugins v1.0.0 §4.1: "A configuration field defined by this
    specification as a plugin-relative path MUST begin with ``./``, be resolved
    against the plugin root, and remain within the filesystem-resolved plugin
    root after resolution."

    Both halves are enforced here. The ``./`` prefix is a syntactic gate (``data``
    and ``/abs/path`` are rejected as written); containment is checked *after*
    ``Path.resolve()``, which normalizes ``..`` segments **and** follows symlinks —
    so a ``./link`` whose target lives outside the plugin is rejected exactly like
    a literal ``./../escape``. Returns ``(resolved_path, None)`` on success and
    ``(None, error)`` on rejection.
    """
    if not isinstance(raw, str) or not raw:
        return None, "plugin-relative path must be a non-empty string"
    if not raw.startswith("./"):
        return None, f"plugin-relative path must start with './': {raw!r}"

    try:
        root_resolved = root.resolve()
        resolved = (root / raw[2:]).resolve()
    except OSError as e:  # pragma: no cover - platform/filesystem dependent
        return None, f"cannot resolve plugin-relative path {raw!r}: {e}"

    if resolved != root_resolved and root_resolved not in resolved.parents:
        return None, f"plugin-relative path escapes plugin root: {raw!r}"
    return resolved, None


# ---------------------------------------------------------------------------
# Manifest validation
# ---------------------------------------------------------------------------

def validate_manifest(payload: object) -> tuple[bool, str | None]:
    """Validate one parsed ``plugin.json`` against Agent Plugins v1.0.0.

    Only the two required fields are load-bearing (``$schema`` and ``name``);
    every optional field is type-checked but never invented. Returns
    ``(is_valid, error_message)``; ``error_message`` is None on success.
    """
    if not isinstance(payload, dict):
        return False, f"{MANIFEST_FILENAME} must be a JSON object"

    schema = payload.get("$schema")
    if not isinstance(schema, str) or not schema:
        return False, f"missing or non-string required field: $schema"
    if schema != PLUGIN_SCHEMA_URL:
        return False, (
            f"unsupported $schema {schema!r}: this kernel understands "
            f"{PLUGIN_SCHEMA_URL!r} (Agent Plugins v1.0.0)"
        )

    name = payload.get("name")
    if not isinstance(name, str) or not name:
        return False, "missing or non-string required field: name"
    if len(name) > _MAX_NAME_LEN:
        return False, f"name too long ({len(name)} > {_MAX_NAME_LEN} chars)"
    if not _NAME_RE.match(name):
        return False, f"invalid name {name!r}: must match {_NAME_RE.pattern}"

    for field in ("version", "description", "homepage", "repository", "license"):
        value = payload.get(field)
        if value is not None and not isinstance(value, str):
            return False, f"{field} must be a string when present"

    keywords = payload.get("keywords")
    if keywords is not None and (
        not isinstance(keywords, list) or not all(isinstance(k, str) for k in keywords)
    ):
        return False, "keywords must be a list of strings when present"

    for field in ("author", "extensions"):
        value = payload.get(field)
        if value is not None and not isinstance(value, dict):
            return False, f"{field} must be an object when present"

    return True, None


# ---------------------------------------------------------------------------
# Component discovery (skills/, mcp.json) — counted, never installed
# ---------------------------------------------------------------------------

def _walk_skills(
    root: Path,
    directory: Path,
    rel: str,
    prefix: str,
    label: str,
    names: list[str],
    paths: list[str],
    problems: list[dict],
) -> None:
    """Enumerate the skill directories under ``directory`` that actually mount.

    Traversal deliberately mirrors ``tools._catalog._scan_recursive``, the scanner
    that will do the mounting: sorted ``iterdir()``, dot-prefixed directories
    skipped, a directory carrying ``SKILL.md`` is a skill, a directory with only
    subdirectories is a grouping directory and is descended into, and a directory
    with loose files but no ``SKILL.md`` is corrupt. Matching that walk is what
    makes the reported skill list identical to the mounted one — the snapshot an
    operator audits cannot under- or over-report a nested skill.

    Every directory is put through §4.1 containment *before* it is descended into
    or accepted, so a symlink escape at any depth is rejected rather than merely
    noted, and its resolved path never reaches ``paths``.
    """
    try:
        entries = sorted(directory.iterdir())
    except OSError as e:
        problems.append({
            "plugin": label,
            "path": str(directory),
            "error": f"cannot read {rel}: {e}",
        })
        return

    for entry in entries:
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        child_rel = f"{rel}/{entry.name}"
        child_label = f"{prefix}{entry.name}"
        resolved, err = resolve_contained(root, child_rel)
        if err:
            problems.append({
                "plugin": label,
                "path": str(entry),
                "error": f"skill {child_label!r} skipped: {err}",
            })
            continue
        assert resolved is not None
        if (resolved / SKILL_FILENAME).is_file():
            names.append(child_label)
            paths.append(str(resolved))
            continue

        try:
            grandchildren = list(resolved.iterdir())
        except OSError as e:
            problems.append({
                "plugin": label,
                "path": str(entry),
                "error": f"cannot read {child_rel}: {e}",
            })
            continue
        if any(not c.is_dir() and not c.name.startswith(".") for c in grandchildren):
            problems.append({
                "plugin": label,
                "path": str(entry),
                "error": (
                    f"skill {child_label!r} skipped: no {SKILL_FILENAME} and has "
                    f"loose files — corrupted"
                ),
            })
            continue
        _walk_skills(
            root, resolved, child_rel, f"{child_label}/", label,
            names, paths, problems,
        )


def _scan_skills(root: Path, label: str) -> tuple[list[str], list[str], list[dict]]:
    """List the Agent Skills under ``./skills``. Never copies or installs.

    Returns ``(names, paths, problems)``. ``names`` are catalog labels relative to
    ``skills/`` (a nested skill reads ``group/nested``); ``paths`` are the
    absolute, containment-validated directory of each skill — the unit of trust
    registration composes into the skills catalog. An invalid or escaping skill is
    skipped without rejecting the plugin (the per-component failure boundary of
    §4.1) *and* contributes no path, so a rejected skill cannot be mounted by way
    of its parent directory.
    """
    problems: list[dict] = []
    skills_dir, err = resolve_contained(root, f"./{SKILLS_DIRNAME}")
    if err:
        return [], [], [{"plugin": label, "path": str(root), "error": f"skills/: {err}"}]
    assert skills_dir is not None
    if not skills_dir.is_dir():
        return [], [], []

    names: list[str] = []
    paths: list[str] = []
    _walk_skills(
        root, skills_dir, f"./{SKILLS_DIRNAME}", "", label, names, paths, problems,
    )
    return names, paths, problems


def _expand_plugin_path(root: Path, raw: str) -> tuple[str | None, str | None]:
    """Expand one ``mcp.json`` value that may be a plugin-relative path.

    §4.1 governs *plugin-relative* paths, which in ``mcp.json`` are the ``./``
    form and the spec's ``${PLUGIN_ROOT}`` expansion of it. Both are resolved
    against the plugin root and containment-checked.

    Writing ``../../bin/sh`` instead of ``./../../bin/sh`` must not be a way past
    that gate, so **any** relative value carrying a ``..`` segment is normalized
    through the same check and rejected when it escapes. That closes the only
    difference the ``./`` prefix used to make to reachability.

    What still passes through untouched is what is genuinely not a plugin-relative
    path: an absolute path, an ``${ENV_VAR}`` placeholder the client is not asked
    to expand, and a bare token with no ``..`` segment — an executable name
    (``node``), a flag (``-c``), a literal argument. §4.1 has nothing to say about
    those, and the kernel cannot tell an executable name from a relative file
    name; see the containment section of the plugin manual, which states this
    rule rather than implying every value is checked.

    Returns ``(value, None)`` or ``(None, error)``.
    """
    if raw.startswith(PLUGIN_ROOT_PLACEHOLDER):
        rest = raw[len(PLUGIN_ROOT_PLACEHOLDER):].lstrip("/")
        candidate = f"./{rest}" if rest else "./"
    elif raw.startswith("./"):
        candidate = raw
    elif not Path(raw).is_absolute() and ".." in Path(raw).parts:
        # A relative value with a `..` segment is a plugin-relative path however
        # it is spelled. Route it through the identical gate; a `a/../b` that
        # stays inside resolves and is rewritten absolute, an escape is rejected.
        candidate = f"./{raw}"
    else:
        return raw, None

    resolved, err = resolve_contained(root, candidate)
    if err:
        # ``candidate`` is a normalized spelling; name the declared value too so
        # the reason points at the line the author actually wrote.
        return None, err if candidate == raw else f"{err} (declared as {raw!r})"
    assert resolved is not None
    return str(resolved), None


def resolve_server_spec(root: Path, spec: object) -> tuple[dict | None, str | None]:
    """Validate one ``mcp.json`` server and resolve its plugin-relative paths.

    Returns ``(resolved_spec, None)`` — a copy of the declared spec with every
    plugin-relative ``command`` / ``cwd`` / ``args`` entry rewritten to its
    absolute resolved path — or ``(None, error)`` when the server must be
    skipped. Used by both halves of this module: the discovery scan (which keeps
    only the names) and registration (which needs the resolved spec to build a
    registry record), so a server can never be counted as valid by one and
    rejected by the other.
    """
    if not isinstance(spec, dict):
        return None, "configuration must be an object"

    transport = spec.get("type")
    if transport not in _VALID_MCP_TYPES:
        return None, (
            f"invalid type {transport!r}, must be one of {sorted(_VALID_MCP_TYPES)}"
        )

    resolved = dict(spec)
    for field in ("command", "cwd"):
        value = spec.get(field)
        if value is None:
            continue
        if not isinstance(value, str):
            return None, f"{field} must be a string when present"
        expanded, err = _expand_plugin_path(root, value)
        if err:
            return None, f"{field}: {err}"
        resolved[field] = expanded

    args = spec.get("args")
    if args is not None:
        if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
            return None, "args must be a list of strings when present"
        expanded_args: list[str] = []
        for i, arg in enumerate(args):
            value, err = _expand_plugin_path(root, arg)
            if err:
                return None, f"args[{i}]: {err}"
            assert value is not None
            expanded_args.append(value)
        resolved["args"] = expanded_args

    for field in ("env", "headers"):
        value = spec.get(field)
        if value is None:
            continue
        if not isinstance(value, dict):
            return None, f"{field} must be an object when present"
        if not all(
            isinstance(k, str) and isinstance(v, str) for k, v in value.items()
        ):
            return None, f"{field} must map strings to strings"

    if transport == "stdio":
        command = spec.get("command")
        if not isinstance(command, str) or not command:
            return None, "stdio transport requires a non-empty 'command'"
    else:
        url = spec.get("url")
        if not isinstance(url, str) or not url:
            return None, f"{transport} transport requires a non-empty 'url'"

    return resolved, None


def _scan_mcp_servers(root: Path, label: str) -> tuple[list[dict], list[dict]]:
    """Read ``mcp.json`` into validated ``{name, spec}`` entries.

    Reading is not registering: this function resolves and validates, it never
    writes to ``mcp_registry.jsonl`` and never spawns a subprocess. Whether the
    entries it returns are actually mounted is decided by ``register_plugins``,
    and only for plugins the operator explicitly declared. A malformed server
    entry is skipped individually; a malformed ``mcp.json`` yields one problem
    and no servers, without rejecting the plugin itself.
    """
    config = root / MCP_CONFIG_FILENAME
    if not config.is_file():
        return [], []

    try:
        payload = json.loads(config.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return [], [{"plugin": label, "path": str(config), "error": f"cannot read {MCP_CONFIG_FILENAME}: {e}"}]

    if not isinstance(payload, dict):
        return [], [{"plugin": label, "path": str(config), "error": f"{MCP_CONFIG_FILENAME} must be a JSON object"}]

    schema = payload.get("$schema")
    if schema != MCP_SCHEMA_URL:
        return [], [{
            "plugin": label,
            "path": str(config),
            "error": (
                f"unsupported {MCP_CONFIG_FILENAME} $schema {schema!r}: this kernel "
                f"understands {MCP_SCHEMA_URL!r} (Agent Plugins v1.0.0)"
            ),
        }]

    servers = payload.get("mcpServers")
    if not isinstance(servers, dict):
        return [], [{"plugin": label, "path": str(config), "error": "mcpServers must be an object"}]

    entries: list[dict] = []
    problems: list[dict] = []
    for server_name in sorted(servers):
        # §4.1 applies to every plugin-relative path a server declares —
        # `command`, `cwd`, and every entry of `args` alike. `resolve_server_spec`
        # is the single gate, so discovery and registration cannot disagree about
        # which servers are acceptable.
        resolved, err = resolve_server_spec(root, servers[server_name])
        if err:
            problems.append({
                "plugin": label,
                "path": str(config),
                "error": f"server {server_name!r} skipped: {err}",
            })
            continue
        assert resolved is not None
        entries.append({"name": server_name, "spec": resolved})
    return entries, problems


# ---------------------------------------------------------------------------
# Per-plugin read
# ---------------------------------------------------------------------------

def read_plugin(root: Path) -> tuple[dict | None, list[dict]]:
    """Read and validate one plugin directory.

    Returns ``(record, problems)``. ``record`` is None when the plugin is
    rejected outright (unreadable/invalid ``plugin.json``) — the whole-plugin
    failure boundary. Component-level failures (a skill or MCP server whose path
    escapes the root) leave the record intact and are reported in ``problems``,
    the per-component failure boundary.
    """
    label = root.name
    manifest_path = root / MANIFEST_FILENAME

    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return None, [{"plugin": label, "path": str(manifest_path), "error": f"cannot read {MANIFEST_FILENAME}: {e}"}]

    ok, err = validate_manifest(payload)
    if not ok:
        return None, [{"plugin": label, "path": str(manifest_path), "error": err or "unknown"}]

    problems: list[dict] = []
    skills, skill_paths, skill_problems = _scan_skills(root, payload["name"])
    problems.extend(skill_problems)
    servers, server_problems = _scan_mcp_servers(root, payload["name"])
    problems.extend(server_problems)

    summary = payload.get("description") or ""
    if len(summary) > _MAX_SUMMARY_LEN:
        summary = summary[: _MAX_SUMMARY_LEN - 1] + "…"

    record = {
        "name": payload["name"],
        "version": payload.get("version") or "",
        "summary": summary,
        "skills": skills,
        "skill_count": len(skills),
        # ``skill_paths`` are the individual, containment-validated skill
        # directories registration composes into the skills catalog scan — never
        # their parent ``skills/``. Composing the parent would re-admit whatever
        # ``_scan_skills`` just rejected, because the catalog scanner walks the
        # directory itself and follows symlinks; the validated list is the only
        # thing that makes "skipped" and "not mounted" the same statement. A
        # skill-less plugin contributes nothing.
        "skill_paths": skill_paths,
        "mcp_servers": [e["name"] for e in servers],
        "mcp_server_count": len(servers),
        # Resolved specs, keyed by server name. Registration needs them to build
        # registry records; the catalog and the prompt XML never render them.
        "mcp_specs": {e["name"]: e["spec"] for e in servers},
        "source": str(root),
    }
    homepage = payload.get("homepage")
    if homepage:
        record["homepage"] = homepage
    return record, problems


# ---------------------------------------------------------------------------
# Path resolution + multi-path scan
# ---------------------------------------------------------------------------

def resolve_path(raw: str, working_dir: Path) -> Path:
    """Resolve a configured plugin search path, mirroring the skills capability.

    Tilde expansion, absolute paths as-is, relative paths against the agent
    working dir.
    """
    expanded = Path(raw).expanduser()
    if expanded.is_absolute():
        return expanded
    return (Path(working_dir) / expanded).resolve(strict=False)


def scan_plugin_root(directory: Path) -> tuple[list[dict], list[dict]]:
    """Scan one configured search path for plugins.

    A search path is normally a *collection* directory whose immediate children
    are plugin roots. A directory that carries ``plugin.json`` itself is treated
    as a single plugin, so a lone plugin can be configured directly without a
    wrapper directory.
    """
    if not directory.is_dir():
        return [], []
    if (directory / MANIFEST_FILENAME).is_file():
        record, problems = read_plugin(directory)
        return ([record] if record else []), problems

    records: list[dict] = []
    problems: list[dict] = []
    try:
        entries = sorted(directory.iterdir())
    except OSError as e:
        return [], [{"plugin": "", "path": str(directory), "error": f"cannot read plugin path: {e}"}]

    for entry in entries:
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        if not (entry / MANIFEST_FILENAME).is_file():
            continue
        record, entry_problems = read_plugin(entry)
        problems.extend(entry_problems)
        if record:
            records.append(record)
    return records, problems


def read_plugins(
    working_dir: Path, paths: list[str]
) -> tuple[list[dict], list[dict], dict[str, dict]]:
    """Scan every configured search path. Returns (records, problems, report).

    ``report`` maps each raw configured path to ``{resolved, exists, plugins}``,
    mirroring the skills capability's per-path health report. Duplicate plugin
    names across paths are reported as problems and the first occurrence wins,
    mirroring the mcp registry's duplicate handling.
    """
    records: list[dict] = []
    problems: list[dict] = []
    report: dict[str, dict] = {}
    seen: set[str] = set()

    for raw in paths:
        resolved = resolve_path(raw, working_dir)
        exists = resolved.is_dir()
        found: list[dict] = []
        if exists:
            found, path_problems = scan_plugin_root(resolved)
            problems.extend(path_problems)
        else:
            log.warning("plugin: path does not exist: %s (resolved=%s)", raw, resolved)
        kept: list[dict] = []
        for record in found:
            if record["name"] in seen:
                problems.append({
                    "plugin": record["name"],
                    "path": record["source"],
                    "error": f"duplicate plugin name {record['name']!r}",
                })
                continue
            seen.add(record["name"])
            kept.append(record)
        records.extend(kept)
        report[raw] = {
            "resolved": str(resolved),
            "exists": exists,
            "plugins": len(kept),
        }

    return records, problems, report


# ---------------------------------------------------------------------------
# Declaration parsing
# ---------------------------------------------------------------------------

def declared_plugin_paths(
    manifest_plugins: object, capabilities: object = None
) -> list[str]:
    """Resolve the declared-plugin list from its canonical key and its alias.

    The **canonical** key is ``init.json`` ``manifest.plugins`` — a flat list of
    plugin package directories (absolute, tilde-prefixed, or relative to the
    agent working dir). The **alias** is ``manifest.capabilities.plugin.paths``,
    the key PR #1232 shipped; it is honored unchanged so an existing config keeps
    working, and it means exactly the same thing. Canonical entries come first,
    duplicates are dropped, so declaring a directory under both is harmless.

    ``manifest.capabilities.skills.paths`` is deliberately NOT a declaration
    channel. It is inherited for *discovery* only (see the plugin capability's
    ``_collect_paths``): dropping a directory into a skills path must never
    silently mount a third party's MCP server.
    """
    ordered: list[str] = []
    if isinstance(manifest_plugins, (list, tuple)):
        ordered.extend(p for p in manifest_plugins if isinstance(p, str) and p)

    if isinstance(capabilities, dict):
        cap = capabilities.get("plugin")
        if isinstance(cap, dict):
            raw = cap.get("paths")
            if isinstance(raw, (list, tuple)):
                ordered.extend(p for p in raw if isinstance(p, str) and p)

    seen: set[str] = set()
    return [p for p in ordered if not (p in seen or seen.add(p))]


# ---------------------------------------------------------------------------
# Registration: declared plugins -> skills catalog + mcp_registry.jsonl
# ---------------------------------------------------------------------------

def to_registry_record(
    plugin_name: str, server_name: str, spec: dict
) -> tuple[dict | None, str | None]:
    """Translate one resolved ``mcp.json`` server into a registry record.

    The record is validated by ``mcp_registry.validate_record`` — the exact
    validator the curated-addon decompression path uses — so a plugin cannot
    introduce a record shape the registry would otherwise reject. Notably, the
    registry's own name grammar applies: a server whose ``mcp.json`` key is not a
    legal registry name is skipped with that validator's message rather than
    silently renamed, because the name is what the agent will type.

    Every field the plugin declared and this module validated is carried into the
    record — including ``env``/``cwd`` for stdio and ``headers`` for the
    URL-addressed transports. The registry validator ignores keys it does not
    model, so carrying them costs nothing and means the record is a faithful
    account of the declaration rather than a lossy summary of it. Nothing here
    makes the record a launch spec: ``Agent._load_mcp_from_workdir`` matches a
    registry record by ``name`` and spawns from the ``init.json`` ``mcp`` entry's
    own config, so these fields are informational.

    Returns ``(record, None)`` or ``(None, error)``.
    """
    from lingtai.services.mcp_registry import validate_record

    transport = _REGISTRY_TRANSPORTS.get(spec.get("type"))
    if transport is None:  # unreachable via resolve_server_spec; defensive
        return None, f"unsupported transport {spec.get('type')!r}"

    summary = f"{server_name}: MCP server provided by Agent Plugin {plugin_name}"
    if len(summary) > _MAX_SUMMARY_LEN:
        summary = summary[: _MAX_SUMMARY_LEN - 1] + "…"

    record: dict = {
        "name": server_name,
        "summary": summary,
        "transport": transport,
        "source": plugin_source(plugin_name),
    }
    if transport == "stdio":
        record["command"] = spec.get("command") or ""
        record["args"] = list(spec.get("args") or [])
        cwd = spec.get("cwd")
        if cwd:
            record["cwd"] = cwd
        env = spec.get("env")
        if env:
            record["env"] = dict(env)
    else:
        record["url"] = spec.get("url") or ""
        headers = spec.get("headers")
        if headers:
            record["headers"] = dict(headers)

    ok, err = validate_record(record)
    if not ok:
        return None, err or "unknown"
    return record, None


def prune_plugin_records(working_dir: Path, desired: dict[str, dict]) -> list[str]:
    """Drop plugin-owned registry records that the declaration no longer implies.

    ``desired`` maps server name → the record registration wants that name to
    hold. A ``source="plugin:*"`` line is dropped when its name is absent from
    ``desired`` (its plugin was uninstalled, or the server left the plugin's
    ``mcp.json``) or when its content differs from the desired record (the spec
    changed — the stale line goes and the fresh one is appended after).

    Records the plugin system does not own are never touched, and neither are
    blank or unparseable lines: this is a targeted removal, not a rewrite of the
    file through a validator that would silently discard a human's broken line.
    The file is written only when something actually changed.

    Returns the names removed.
    """
    from lingtai.services.mcp_registry import _registry_path

    path = _registry_path(Path(working_dir))
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        log.warning("plugin: cannot read registry for pruning: %s", e)
        return []

    kept: list[str] = []
    removed: list[str] = []
    for raw in text.splitlines():
        if not raw.strip():
            kept.append(raw)
            continue
        try:
            record = json.loads(raw)
        except json.JSONDecodeError:
            kept.append(raw)
            continue
        source = record.get("source") if isinstance(record, dict) else None
        if not isinstance(source, str) or not source.startswith(PLUGIN_SOURCE_PREFIX):
            kept.append(raw)
            continue
        name = record.get("name")
        if isinstance(name, str) and record == desired.get(name):
            kept.append(raw)
            continue
        removed.append(name if isinstance(name, str) else "")

    if removed:
        body = "\n".join(kept)
        path.write_text(body + "\n" if body else "", encoding="utf-8")
    return removed


def register_plugins(working_dir: Path, declared: list[str]) -> dict:
    """Register every declared plugin. The one boot-time mutation point.

    Runs before capability setup on both boot paths, for the same reason addon
    decompression does: the ``skills`` and ``mcp`` capabilities must see the
    mounted result on their first reconcile.

    Per declared plugin (validated exactly as discovery validates it, so a bad
    ``plugin.json`` rejects the whole plugin and an escaping component skips just
    that component):

    - ``skills/`` — each *validated* skill directory is returned in
      ``skill_paths`` for the skills capability to compose into its catalog scan,
      so the plugin's skills appear as ordinary skills located inside the plugin.
      The parent ``skills/`` is never composed: a skill rejected under §4.1 must
      not be reachable through it, and the per-skill list is what makes the
      reported and the mounted set the same set.
    - ``mcp.json`` — each server becomes an ``mcp_registry.jsonl`` record stamped
      ``source="plugin:<name>"``, appended through the addon path's own
      validator. Registry-level only: nothing is launched, and activation still
      needs an ``init.json`` top-level ``mcp`` entry.

    Stale plugin-owned records are pruned first, so an uninstalled plugin's
    servers disappear on the next boot and a changed spec is replaced rather than
    duplicated. Idempotent: running twice leaves the same registry as once.

    Returns the snapshot the ``plugin`` tool's ``info`` action reports.
    """
    from lingtai.services.mcp_registry import _append_record, read_registry

    working_dir = Path(working_dir)
    declared = list(declared or [])
    # Default plugin root: <workdir>/plugin/ is scanned automatically when it
    # exists, so dropping a plugin directory there needs no init.json entry.
    # Explicit declarations still come first and win duplicate names.
    default_plugin_dir = working_dir / "plugin"
    if default_plugin_dir.is_dir() and str(default_plugin_dir) not in declared:
        declared = [str(default_plugin_dir)] + declared
    records, problems, paths_report = read_plugins(working_dir, declared)

    # Pass 1 — decide what the registry should hold, and why anything is skipped.
    desired: dict[str, dict] = {}
    owners: dict[str, str] = {}
    plugins: list[dict] = []
    skill_paths: list[str] = []

    for record in records:
        name = record["name"]
        skipped: list[dict] = [
            {"component": p.get("path", ""), "reason": p.get("error", "")}
            for p in problems
            if p.get("plugin") == name
        ]

        skill_paths.extend(record["skill_paths"])

        wanted: list[str] = []
        for server_name in record["mcp_servers"]:
            spec = record["mcp_specs"][server_name]
            reg, err = to_registry_record(name, server_name, spec)
            if err:
                skipped.append({
                    "component": f"mcp:{server_name}",
                    "reason": f"not registrable: {err}",
                })
                continue
            assert reg is not None
            if server_name in desired:
                skipped.append({
                    "component": f"mcp:{server_name}",
                    "reason": (
                        f"name already claimed by plugin {owners[server_name]!r}"
                    ),
                })
                continue
            desired[server_name] = reg
            owners[server_name] = name
            wanted.append(server_name)

        entry = {
            "name": name,
            "version": record["version"],
            "summary": record["summary"],
            "source": record["source"],
            "skills": list(record["skills"]),
            "skill_count": record["skill_count"],
            "skill_paths": list(record["skill_paths"]),
            "mcp_servers": list(record["mcp_servers"]),
            "mcp_server_count": record["mcp_server_count"],
            "mcp_registered": wanted,
            "skipped": skipped,
        }
        if record.get("homepage"):
            entry["homepage"] = record["homepage"]
        plugins.append(entry)

    by_name = {p["name"]: p for p in plugins}

    # Pass 2 — prune first so a changed spec is replaced, not duplicated, then
    # append whatever the (re-read) registry is still missing.
    pruned = prune_plugin_records(working_dir, desired)
    existing, _registry_problems = read_registry(working_dir)
    existing_by_name = {r["name"]: r for r in existing}

    appended: list[str] = []
    for server_name, reg in desired.items():
        prior = existing_by_name.get(server_name)
        if prior is not None:
            if prior.get("source") != reg["source"]:
                # A hand-written or addon-decompressed record owns this name.
                # Registration never overwrites what it does not own.
                owner = by_name[owners[server_name]]
                owner["mcp_registered"] = [
                    n for n in owner["mcp_registered"] if n != server_name
                ]
                owner["skipped"].append({
                    "component": f"mcp:{server_name}",
                    "reason": (
                        f"name already registered by {prior.get('source')!r} — "
                        f"rename the server in mcp.json or remove the conflict"
                    ),
                })
            continue
        try:
            _append_record(working_dir, reg)
        except OSError as e:
            owner = by_name[owners[server_name]]
            owner["mcp_registered"] = [
                n for n in owner["mcp_registered"] if n != server_name
            ]
            owner["skipped"].append({
                "component": f"mcp:{server_name}",
                "reason": f"cannot append to registry: {e}",
            })
            continue
        appended.append(server_name)

    return {
        "declared": declared,
        "plugins": plugins,
        "skill_paths": skill_paths,
        "mcp_appended": appended,
        "mcp_pruned": [n for n in pruned if n],
        "paths": paths_report,
        "problems": problems,
    }


# ---------------------------------------------------------------------------
# XML registry builder (rendered into system prompt)
# ---------------------------------------------------------------------------

def _escape_xml(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _plugin_xml(record: dict, mount: str, indent: str = "  ") -> list[str]:
    """Render one ``<plugin>`` element, stamped with how it is mounted."""
    lines = [f"{indent}<plugin>"]
    lines.append(f"{indent}  <name>{_escape_xml(record['name'])}</name>")
    lines.append(f"{indent}  <mount>{mount}</mount>")
    if record.get("version"):
        lines.append(f"{indent}  <version>{_escape_xml(record['version'])}</version>")
    if record.get("summary"):
        lines.append(f"{indent}  <summary>{_escape_xml(record['summary'])}</summary>")
    lines.append(f"{indent}  <skills>{record['skill_count']}</skills>")
    skill_names = record.get("skills") or []
    if skill_names:
        lines.append(
            f"{indent}  <skill_names>{_escape_xml(', '.join(skill_names))}</skill_names>"
        )
    lines.append(f"{indent}  <mcp_servers>{record['mcp_server_count']}</mcp_servers>")
    mcp_names = record.get("mcp_servers") or []
    if mcp_names:
        lines.append(
            f"{indent}  <mcp_names>{_escape_xml(', '.join(mcp_names))}</mcp_names>"
        )
    if mount == "registered":
        registered = record.get("mcp_registered") or []
        lines.append(
            f"{indent}  <mcp_registered>{_escape_xml(', '.join(registered))}"
            f"</mcp_registered>"
        )
        skipped = record.get("skipped") or []
        if skipped:
            lines.append(f"{indent}  <skipped>{len(skipped)}</skipped>")
    lines.append(f"{indent}  <source>{_escape_xml(record['source'])}</source>")
    homepage = record.get("homepage")
    if homepage:
        lines.append(f"{indent}  <homepage>{_escape_xml(homepage)}</homepage>")
    lines.append(f"{indent}</plugin>")
    return lines


def _build_registry_xml(
    registered: list[dict], discovered: list[dict] | None = None
) -> str:
    """Render the ``<registered_plugin>`` prompt section for both mount tiers.

    ``registered`` plugins were declared in ``manifest.plugins`` (or its alias)
    and mounted at boot: their skills are in the skills catalog and their
    ``mcp.json`` servers hold ``mcp_registry.jsonl`` records. ``discovered``
    plugins were merely found on an inherited skills path — the original
    flagpost, listed and nothing more. The preamble states which is which,
    because the difference is the difference between "you can use this" and "you
    would have to wire this up yourself".
    """
    discovered = discovered or []
    if not registered and not discovered:
        return (
            "No Agent Plugins (agent-plugins.org, v1.0.0) are registered or "
            "discovered for this agent. Drop a plugin directory under "
            "<workdir>/plugin/<name>/plugin.json (or declare it in init.json "
            "manifest.plugins) and refresh to mount it. See "
            "plugin(action=\"manual\") for the plugin-manual."
        )

    preamble = (
        "The following Agent Plugins (agent-plugins.org, v1.0.0) are visible to "
        "this agent. <mount>registered</mount> means the plugin was declared in "
        "init.json manifest.plugins and mounted at boot: its skills stay inside "
        "the plugin (readable via file/read from <source>, not composed into the "
        "vanilla skills catalog) and each name in <mcp_registered> holds an "
        "mcp_registry.jsonl record with source=\"plugin:<name>\" — registered, "
        "but NOT running, so activation still needs an init.json top-level mcp "
        "entry. "
        "<mount>discovered</mount> means the plugin was only found on an "
        "inherited skills path: nothing is mounted, its skills are NOT in your "
        "catalog and its MCP servers are NOT registered. Call "
        "plugin(action=\"manual\") for the plugin-manual, and "
        "plugin(action=\"info\") for the full registration snapshot including "
        "every skipped component and why."
    )

    lines = [preamble, "", "<registered_plugin>"]
    for record in registered:
        lines.extend(_plugin_xml(record, "registered"))
    for record in discovered:
        lines.extend(_plugin_xml(record, "discovered"))
    lines.append("</registered_plugin>")
    return "\n".join(lines)
