"""Skills capability — per-agent skill catalog (pure presentation).

Every agent has its own ``<agent>/.library/``:

- ``intrinsic/capabilities/<cap>/`` and ``intrinsic/addons/<addon>/`` — manual
  bundles installed by the Agent initializer (wipe-and-rewrite on every
  ``_setup_from_init``). The skills capability does NOT create or populate
  this directory.
- ``custom/`` — agent-authored skills. Never touched by any kernel code.

Additional paths come from ``init.json``:

``manifest.capabilities.skills.paths``: list[str] — each entry is scanned
recursively and contributes to the YAML skill catalog injected into the
system prompt's ``skills`` section. Paths may be absolute, relative to the
agent working dir, or tilde-prefixed.

This capability is pure presentation: it scans whatever is on disk and builds
the catalog. It never writes to ``.library/``. File installation is the
initializer's job.

Tool surface: ``info`` refreshes/reconciles the catalog and returns runtime
health without manual bodies; ``manual`` returns the skills manual body on demand.
Both are action children of one LTP v2 ``ToolFamily`` (``src/lingtai/tools/
CONTRACT.md``): the public tool name stays ``skills`` and the public action
values stay exactly ``info`` and ``manual``; only the envelope shape around
them changes to the canonical ``action`` + ``input`` + ``reasoning`` +
``summarize`` root.

Usage: ``Agent(capabilities={"skills": {"paths": [...]}})`` or via init.json.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping

from .._catalog import build_catalog_yaml, scan_markdown_catalog
from ..tool_family import ChildTool, ToolFamily
from ..tool_family.manual import build_manual_child
from lingtai.kernel.i18n import t

if TYPE_CHECKING:
    from lingtai.kernel.base_agent import BaseAgent

log = logging.getLogger(__name__)

PROVIDERS = {"providers": [], "default": "builtin"}

# Both skills actions are signposts that take no arguments at all, so both
# child input schemas are the canonical strict-empty object. Built per call so
# each child owns a distinct schema object: a future per-action field must not
# silently widen its sibling.
def _strict_empty_input() -> dict[str, Any]:
    return {"type": "object", "properties": {}, "required": [], "additionalProperties": False}


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

def _resolve_path(p: str, working_dir: Path) -> Path:
    """Resolve a user-declared skills path.

    - Tilde expansion (``~/foo`` → user home).
    - Absolute paths used as-is.
    - Relative paths resolved against the agent working dir.
    """
    expanded = Path(p).expanduser()
    if expanded.is_absolute():
        return expanded
    return (working_dir / expanded).resolve(strict=False)


# ---------------------------------------------------------------------------
# Skill scanner
# ---------------------------------------------------------------------------

def _scan(directory: Path) -> tuple[list[dict], list[dict]]:
    return scan_markdown_catalog(directory, filename="SKILL.md", kind="skill")


# ---------------------------------------------------------------------------
# Core reconciliation (shared by setup and `info` health check)
# ---------------------------------------------------------------------------

def _reconcile(
    agent: "BaseAgent",
    paths: list[str],
) -> dict:
    """Scan ``.library/`` + Tier-1 paths, inject catalog, report status.

    The skills capability is pure presentation: it reads whatever the Agent
    initializer wrote to ``.library/intrinsic/`` and the agent wrote to
    ``.library/custom/``. It does NOT create directories or copy files.

    Returns a dict suitable for the ``info`` response.
    """
    working_dir = agent._working_dir
    library_dir = working_dir / ".library"
    intrinsic_dir = library_dir / "intrinsic"
    custom_dir = library_dir / "custom"

    problems: list[dict] = []
    status = "ok"
    error: str | None = None

    # Scan intrinsic + custom. If they don't exist, _scan silently returns empty.
    all_skills: list[dict] = []
    int_valid, int_problems = _scan(intrinsic_dir)
    all_skills.extend(int_valid)
    problems.extend(int_problems)

    cus_valid, cus_problems = _scan(custom_dir)
    all_skills.extend(cus_valid)
    problems.extend(cus_problems)

    # Scan each Tier 1 path.
    paths_report: dict[str, dict] = {}
    for raw in paths:
        resolved = _resolve_path(raw, working_dir)
        exists = resolved.is_dir()
        p_valid: list[dict] = []
        p_problems: list[dict] = []
        if exists:
            p_valid, p_problems = _scan(resolved)
            all_skills.extend(p_valid)
            problems.extend(p_problems)
        else:
            log.warning("skills: path does not exist: %s (resolved=%s)", raw, resolved)
        paths_report[raw] = {
            "resolved": str(resolved),
            "exists": exists,
            "skills": len(p_valid),
        }

    # Build and inject catalog.
    lang = agent._config.language
    catalog_yaml = build_catalog_yaml(all_skills, t(lang, "skills.preamble"))
    if catalog_yaml:
        agent.update_system_prompt("skills", catalog_yaml, protected=True)
    else:
        agent.update_system_prompt("skills", "", protected=True)

    # Health signal: the skills capability's own manual must be present.
    skills_manual_path = intrinsic_dir / "capabilities" / "skills" / "SKILL.md"
    if not skills_manual_path.is_file():
        status = "degraded"
        error = error or (
            "skills manual missing — initializer may have failed or "
            "capability not installed correctly"
        )
        manual_body = ""
    else:
        manual_body = skills_manual_path.read_text(encoding="utf-8")

    result = {
        "status": status,
        "skills_manual": manual_body,
        # Back-compat key kept for callers that have not renamed yet.
        "library_manual": manual_body,
        "skills_dir": str(library_dir),
        # The on-disk directory remains .library for compatibility.
        "library_dir": str(library_dir),
        "catalog_size": len(all_skills),
        "paths": paths_report,
        "problems": problems,
    }
    if error:
        result["error"] = error
    return result


def _skills_info(agent: "BaseAgent", paths: list[str]) -> dict:
    """Refresh/reconcile the skills catalog and return health without the manual body."""
    result = dict(_reconcile(agent, paths))
    result.pop("skills_manual", None)
    result.pop("library_manual", None)
    return result


def _adapt_manual_result(mcp_result: dict) -> dict:
    """Flatten the dispatched ``manual`` child's canonical result to skills' shape.

    Skills' public manual shape predates the generic canonical
    ``content``/``structuredContent`` contract and must stay byte-identical, so
    this Host-owned adapter runs strictly *after* dispatch — never inside a
    registered child, and never touching ``info``. ``library_manual`` remains
    the back-compat mirror of ``skills_manual``.
    """
    manual_body = mcp_result["content"][0]["text"]
    flat: dict = {
        "status": mcp_result.get("status", "ok"),
        "skills_manual": manual_body,
        "library_manual": manual_body,
        "manual_path": mcp_result["structuredContent"]["manual_path"],
    }
    if "error" in mcp_result:
        flat["error"] = mcp_result["error"]
    return flat


# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------

def get_description(lang: str = "en") -> str:
    return 'SIGNPOST ONLY: this tool does not author, pin, publish, install, or execute skills; `info` only refreshes/reconciles the skills catalog and returns health without the manual body; `manual` returns the skills-manual body. Your per-agent skill catalog. The skills section of your system prompt is a YAML list — one `- name:` block per skill with `location:` and `description:` — covering every skill reachable right now. Both actions take an empty input object: skills(action=\'info\', input={}, reasoning=\'refresh the skill catalogue\') and skills(action=\'manual\', input={}, reasoning=\'load skills guidance\'). Before using this tool (authoring, pinning, publishing, or managing skills), read the `skills-manual` skill — call `manual` for its body and `info` for a runtime health snapshot; no exceptions.'


def _build_family(agent: "BaseAgent | None", paths: list[str]) -> ToolFamily:
    """Build the skills family — the one canonical child registry.

    Both the model-facing schema and runtime dispatch come from this single
    declaration, so action names, input schemas, titles, and order cannot drift
    apart. ``agent=None`` yields a schema-only family whose handlers are never
    reachable: ``get_schema()`` calls only ``build_schema()``, which reads each
    child's ``input_schema`` and never a handler. Constructing it at import time
    also proves the registry has no duplicate or reserved-name collision
    (``ToolFamilyError`` would raise here rather than shipping silently).

    The ``manual`` child is ``build_manual_child``'s, registered directly and
    unwrapped, so ``ToolFamily.handle()`` returns its canonical result verbatim
    (no double wrap); the flat public shape is rebuilt strictly after dispatch
    in ``handle_skills``. It reads the installed manual only — no catalog scan,
    no prompt injection, no other ``info``-side effect.
    """
    if agent is None:
        def _info(_input: Mapping[str, Any]) -> dict:
            raise AssertionError("the schema-only skills family never dispatches")
    else:
        def _info(_input: Mapping[str, Any]) -> dict:
            return _skills_info(agent, paths)

    # Always the shared builder's own child, so the advertised ``manual`` input
    # schema is exactly the one dispatch registers — schema and dispatch cannot
    # disagree even about a detail like a redundant empty ``required``.
    manual_child = build_manual_child(agent, "skills")

    return ToolFamily(
        "skills",
        [ChildTool("info", _strict_empty_input(), _info, title="info input"), manual_child],
    )


_SCHEMA_FAMILY = _build_family(None, [])


def get_schema(lang: str = "en") -> dict:
    # Composed from the same child registry runtime dispatch uses, so the
    # public action enum cannot drift from the dispatch keys.
    return _SCHEMA_FAMILY.build_schema()


def setup(agent: "BaseAgent", paths: list[str] | None = None, **_ignored) -> None:
    """Set up the skills capability.

    ``paths`` is the Tier 1 list from ``init.json`` ``manifest.capabilities.skills.paths``.
    When omitted (e.g., direct ``Agent(capabilities=["skills"])`` use without kwargs),
    no additional paths are scanned — only the per-agent ``.library/``.

    The capability itself does not create or populate ``.library/``; the Agent
    initializer's ``_install_intrinsic_manuals`` step handles that. Setup just
    scans whatever is on disk and injects the YAML catalog so the first turn
    sees a ready catalog.
    """
    path_list = list(paths) if paths else []

    # Run reconciliation once on setup so the catalog is ready before first turn.
    # This only READS from .library/ — the initializer has already written it.
    _reconcile(agent, path_list)

    family = _build_family(agent, path_list)

    def handle_skills(args: dict) -> dict:
        # ``ToolFamily.handle`` is the fail-closed authorization boundary:
        # schema conformance alone is not (``tools/CONTRACT.md`` "Dispatch and
        # actions"). Flattening the dispatched ``manual`` result is this Host
        # layer's own job, done strictly after dispatch.
        action = args.get("action") if isinstance(args, Mapping) else None
        result = family.handle(args)
        if action == "manual" and "content" in result:
            return _adapt_manual_result(result)
        return result

    agent.add_tool(
        "skills",
        schema=get_schema(),
        handler=handle_skills,
        description=get_description(),
        glossary_package=__package__,
    )
