"""Knowledge capability — private durable knowledge across molts.

Filesystem-backed catalog. Each agent has its own ``<agent>/knowledge/``
directory; every immediate subdirectory with a ``KNOWLEDGE.md`` file is a
knowledge entry. The capability is pure presentation: it scans the directory,
parses each ``KNOWLEDGE.md``'s YAML frontmatter for ``name`` + ``description``,
and injects a compact YAML catalog into the system prompt's
``knowledge`` section. Bodies, supporting files, scripts, and assets live next
to ``KNOWLEDGE.md`` and are loaded on demand through the regular ``read`` tool.

Knowledge is structurally isomorphic to skills but physically separate:

- Skills live under ``<agent>/.library/{intrinsic,custom}/<name>/SKILL.md`` and
  are portable / shareable across agents.
- Knowledge lives under ``<agent>/knowledge/<name>/KNOWLEDGE.md`` and is
  private, agent-owned, and may reference agent-local paths, mail ids, and
  logs that skills must not depend on.

Tool surface (LTP v2 family; see ``src/lingtai/tools/CONTRACT.md``): the public
tool stays ``knowledge`` with the same two action values. ``info`` returns a
runtime health snapshot (catalog size, problems) without the manual body;
``manual`` returns the knowledge-manual body on demand. Both take a strict empty
``input``. Knowledge entry bodies are read via the ``read`` tool, the same way
the agent opens a ``SKILL.md``.

Usage: ``Agent(capabilities={"knowledge": {}})`` or via init.json.
"""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Mapping

from .._catalog import build_catalog_yaml, scan_markdown_catalog
from ..tool_family import ChildTool, ToolFamily
from lingtai.kernel.i18n import t

if TYPE_CHECKING:
    from lingtai.kernel.base_agent import BaseAgent

log = logging.getLogger(__name__)

PROVIDERS = {"providers": [], "default": "builtin"}


# ---------------------------------------------------------------------------
# Legacy JSON migration
# ---------------------------------------------------------------------------

_SLUG_RE = re.compile(r"[^a-z0-9._-]+")


def _slugify(value: str, fallback: str) -> str:
    """Return a filesystem-safe knowledge entry name."""
    base = value.strip().lower() or fallback
    base = _SLUG_RE.sub("-", base)
    base = base.strip(".-_") or fallback
    return base[:64].strip(".-_") or fallback


def _yaml_quote(value: str) -> str:
    """Render a small frontmatter scalar safely as JSON/YAML-compatible text."""
    return json.dumps(value, ensure_ascii=False)


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp", prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _unique_entry_dir(root: Path, preferred: str, legacy_id: str) -> tuple[Path, str]:
    slug = _slugify(preferred, fallback=_slugify(legacy_id, "entry"))
    candidate = root / slug
    if not candidate.exists():
        return candidate, slug

    suffix_base = _slugify(legacy_id, "entry")
    candidate = root / f"{slug}-{suffix_base}"
    if not candidate.exists():
        return candidate, candidate.name

    i = 2
    while True:
        candidate = root / f"{slug}-{suffix_base}-{i}"
        if not candidate.exists():
            return candidate, candidate.name
        i += 1


def _format_knowledge_md(*, name: str, title: str, description: str, content: str, supplementary: str, legacy_id: str, created_at: str, origin: str) -> str:
    frontmatter = [
        "---",
        f"name: {_yaml_quote(name)}",
        f"description: {_yaml_quote(description)}",
        "version: \"1.0.0\"",
        f"origin: {_yaml_quote(origin)}",
    ]
    if legacy_id:
        frontmatter.append(f"legacy_id: {_yaml_quote(legacy_id)}")
    if title:
        frontmatter.append(f"title: {_yaml_quote(title)}")
    if created_at:
        frontmatter.append(f"created_at: {_yaml_quote(created_at)}")
    frontmatter.append("---")

    body_parts = ["\n".join(frontmatter), ""]
    if title:
        body_parts.append(f"# {title}")
        body_parts.append("")
    if content:
        body_parts.append(content.rstrip())
        body_parts.append("")
    else:
        body_parts.append(description)
        body_parts.append("")
    if supplementary:
        body_parts.append("## References")
        body_parts.append("")
        body_parts.append("- [Migrated supplementary material](references/supplementary.md)")
        body_parts.append("")
    return "\n".join(body_parts).rstrip() + "\n"


def _migrate_one_legacy_json(knowledge_dir: Path, legacy: Path, *, label: str, origin: str) -> list[dict]:
    if not legacy.is_file():
        return []

    problems: list[dict] = []
    try:
        data = json.loads(legacy.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return [{"folder": label, "reason": f"cannot migrate legacy {label}: {e}"}]

    raw_entries = data.get("entries", []) if isinstance(data, dict) else []
    if not isinstance(raw_entries, list):
        return [{"folder": label, "reason": f"cannot migrate legacy {label}: entries is not a list"}]

    migrated = 0
    for idx, raw in enumerate(raw_entries, 1):
        if not isinstance(raw, dict):
            problems.append({"folder": f"{label}[{idx}]", "reason": "legacy entry is not an object"})
            continue
        legacy_id = str(raw.get("id") or idx)
        title = str(raw.get("title") or raw.get("content") or f"Entry {idx}").strip()
        summary = str(raw.get("summary") or title or raw.get("content") or "Migrated knowledge entry").strip()
        content = str(raw.get("content") or "").strip()
        supplementary = str(raw.get("supplementary") or "").strip()
        created_at = str(raw.get("created_at") or "").strip()

        entry_dir, name = _unique_entry_dir(knowledge_dir, title, legacy_id)
        try:
            md = _format_knowledge_md(
                name=name,
                title=title,
                description=summary,
                content=content,
                supplementary=supplementary,
                legacy_id=legacy_id,
                created_at=created_at,
                origin=origin,
            )
            _atomic_write_text(entry_dir / "KNOWLEDGE.md", md)
            if supplementary:
                _atomic_write_text(entry_dir / "references" / "supplementary.md", supplementary.rstrip() + "\n")
            migrated += 1
        except OSError as e:
            problems.append({"folder": f"{label}[{idx}]", "reason": f"migration write failed: {e}"})

    if migrated:
        backup = legacy.with_name(legacy.name + ".migrated")
        if backup.exists():
            n = 2
            while legacy.with_name(legacy.name + f".migrated.{n}").exists():
                n += 1
            backup = legacy.with_name(legacy.name + f".migrated.{n}")
        try:
            legacy.rename(backup)
        except OSError as e:
            problems.append({"folder": label, "reason": f"migrated entries but could not rename legacy file: {e}"})

    return problems


def _migrate_legacy_json(working_dir: Path, knowledge_dir: Path) -> list[dict]:
    """One-time migration from legacy JSON stores into folders.

    Old entries become ``knowledge/<slug>/KNOWLEDGE.md``. The old
    ``supplementary`` field is written to ``references/supplementary.md`` and
    linked from the main document. Source JSON files are renamed after a
    successful migration so the operation is not repeated on the next scan.
    """
    problems: list[dict] = []
    problems.extend(_migrate_one_legacy_json(
        knowledge_dir,
        knowledge_dir / "knowledge.json",
        label="knowledge/knowledge.json",
        origin="migrated-knowledge-json",
    ))
    problems.extend(_migrate_one_legacy_json(
        knowledge_dir,
        working_dir / "codex" / "codex.json",
        label="codex/codex.json",
        origin="migrated-codex-json",
    ))
    return problems


# ---------------------------------------------------------------------------
# YAML catalog builder
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Core reconciliation (shared by setup and `info`)
# ---------------------------------------------------------------------------

def _reconcile(agent: "BaseAgent") -> dict:
    """Scan ``<agent>/knowledge/``, inject catalog, report status.

    Pure presentation: never writes inside ``knowledge/``. The agent is the
    sole author of its knowledge entries; the capability only renders them.
    """
    working_dir = agent._working_dir
    knowledge_dir = working_dir / "knowledge"

    migration_problems = _migrate_legacy_json(working_dir, knowledge_dir)
    entries, problems = scan_markdown_catalog(
        knowledge_dir, filename="KNOWLEDGE.md", kind="knowledge entry",
    )
    problems = migration_problems + problems

    lang = agent._config.language
    catalog_yaml = build_catalog_yaml(entries, t(lang, "knowledge.preamble"))
    if catalog_yaml:
        agent.update_system_prompt("knowledge", catalog_yaml, protected=True)
    else:
        agent.update_system_prompt("knowledge", "", protected=True)

    return {
        "status": "ok",
        "knowledge_dir": str(knowledge_dir),
        "catalog_size": len(entries),
        "problems": problems,
    }


# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------

def _knowledge_manual(agent: "BaseAgent") -> dict:
    """Return the knowledge manual body without refreshing catalog health."""
    manual_path = agent._working_dir / ".library" / "intrinsic" / "capabilities" / "knowledge" / "SKILL.md"
    if not manual_path.is_file():
        return {
            "status": "degraded",
            "knowledge_manual": "",
            "manual_path": str(manual_path),
            "error": "knowledge manual missing — initializer may have failed or capability not installed correctly",
        }
    return {
        "status": "ok",
        "knowledge_manual": manual_path.read_text(encoding="utf-8"),
        "manual_path": str(manual_path),
    }


# ---------------------------------------------------------------------------
# LTP v2 family composition
# ---------------------------------------------------------------------------

# Neither action ever took an argument, so both children share the canonical
# strict-empty input. That is what mechanically enforces the signpost contract:
# with no declared property, *every* ``input`` key is an unknown key and is
# rejected before the handler runs.
_EMPTY_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "required": [],
    "additionalProperties": False,
}

# The one source of truth for knowledge's children: name -> the operation that
# child performs on a bound agent. Both share ``_EMPTY_INPUT_SCHEMA`` and the
# ``"<name> input"`` title, so the spec carries only what differs. Each
# operation is a lambda rather than a direct function reference so the
# module-level global is resolved when the child runs, not when this tuple is
# built at import — the no-rescan/pre-I/O tests patch those globals to prove a
# handler never ran.
#
# ``manual`` is this package's own child rather than the generic
# ``build_manual_child`` because knowledge's public result is keyed
# ``knowledge_manual``, not the generic ``content``/``structuredContent`` shape.
# Using the generic builder would mean wrapping into a shape this family never
# exposes only to flatten it back in a Host adapter; registering our own child
# satisfies no-double-wrap without that round trip.
_CHILD_SPECS: tuple[tuple[str, Callable[["BaseAgent"], dict]], ...] = (
    ("info", lambda agent: _reconcile(agent)),
    ("manual", lambda agent: _knowledge_manual(agent)),
)


def _build_family(agent: "BaseAgent | None") -> ToolFamily:
    """Build one ``knowledge`` :class:`ToolFamily` from :data:`_CHILD_SPECS`.

    With an ``agent``, children dispatch that agent's real operations. With
    ``None`` — the module-level :data:`_FAMILY` backing ``get_schema()`` — they
    raise if invoked, since a schema-only family never dispatches. Either way
    construction validates the registry, so a duplicate or reserved-name
    collision raises :class:`ToolFamilyError` at import time.
    """

    def bind(operation: "Callable[[BaseAgent], dict]") -> Callable[[Mapping[str, Any]], dict]:
        if agent is None:
            def unused(_input: Mapping[str, Any]) -> dict:
                raise AssertionError("the module-level schema-only ToolFamily never dispatches")
            return unused
        return lambda _input: operation(agent)

    return ToolFamily(
        "knowledge",
        [
            ChildTool(name, _EMPTY_INPUT_SCHEMA, bind(operation), title=f"{name} input")
            for name, operation in _CHILD_SPECS
        ],
    )


_FAMILY = _build_family(None)


def get_description(lang: str = "en") -> str:
    return "SIGNPOST ONLY: this tool does not create, edit, search, or load knowledge entries; `info` only re-scans the knowledge catalog and reports health; `manual` returns the knowledge-manual body. Your private durable knowledge catalog across molts — what you've learned, decided, and discovered. Each entry is a folder at knowledge/<name>/ containing KNOWLEDGE.md (YAML frontmatter with name + description) and any supporting files (scripts, assets, notes, raw logs). The knowledge catalog in your system prompt is a YAML list — each entry is a `- name:` block with `location:` and `description:` — bodies load on demand via the read tool, just like skills. Knowledge is private and agent-owned: entries may reference local paths, mail ids, and logs that skills must not depend on. Author new entries by writing knowledge/<name>/KNOWLEDGE.md with write/edit; revise the same way. Call knowledge(action='info', input={}, reasoning='refresh the knowledge catalog') to refresh the catalog and inspect health, and knowledge(action='manual', input={}, reasoning='load knowledge guidance') for the manual body. Before using this tool, read the `knowledge-manual` skill — no exceptions."


def get_schema(lang: str = "en") -> dict:
    # Composed by the generic ToolFamily infra from each child's own canonical
    # ``input_schema`` rather than hand-assembled. The public action values are
    # unchanged (``info``, ``manual``); what changes is the root envelope, which
    # is now the closed LTP v2 ``action``/``input``/``reasoning``/``summarize``
    # shape with per-action ``input`` correlation on both provider wires.
    return _FAMILY.build_schema()


def handle(family: ToolFamily, args: dict | None) -> dict:
    """Dispatch one ``knowledge`` family call and normalize its envelope error.

    ``family`` is the per-agent :class:`ToolFamily` ``setup()`` builds once at
    registration. Dispatch itself lives entirely in the generic
    ``ToolFamily.handle``; the only thing this Host layer adds is the
    unknown-action normalization below.

    Knowledge's pre-migration public unknown-action result was
    ``{"status": "error", "message": "unknown action: ..., only 'info' or
    'manual' is supported"}`` for any bad action value, including an unhashable
    one such as ``[]`` or ``{}``, and rendering a *missing* ``action`` as the
    empty-string default (``kernel/tool_dispatch.py``'s ``default=""``). That
    exact shape — including that default — is preserved here, after dispatch,
    rather than by changing the generic dispatcher's own canonical
    ``ACTION_REQUIRED`` envelope error.
    """
    action = args.get("action", "") if isinstance(args, Mapping) else ""
    result = family.handle(args)
    if result.get("error_code") == "ACTION_REQUIRED":
        return {
            "status": "error",
            "message": f"unknown action: {action!r}, only 'info' or 'manual' is supported",
        }
    return result


def setup(agent: "BaseAgent", **_ignored) -> None:
    """Set up the knowledge capability.

    Scans ``<agent>/knowledge/`` for ``<name>/KNOWLEDGE.md`` entries and
    injects the catalog into the system prompt. Registers the ``knowledge``
    family with ``info`` for runtime health and ``manual`` for the
    progressive-disclosure manual body.

    Unknown kwargs (e.g. the historical ``knowledge_limit``) are accepted and
    ignored — the file-backed catalog has no fixed-size limit.
    """
    _reconcile(agent)
    family = _build_family(agent)

    def handle_knowledge(args: dict) -> dict:
        return handle(family, args)

    agent.add_tool(
        "knowledge",
        schema=get_schema(),
        handler=handle_knowledge,
        description=get_description(),
        glossary_package=__package__,
    )
