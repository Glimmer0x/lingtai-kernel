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

One more path source is composed in, not declared here: every Agent Plugin
declared in ``manifest.plugins`` contributes each of its containment-validated
skill directories, which ``Agent`` records on the agent at boot registration.
See ``_compose_paths``.

This capability is pure presentation: it scans whatever is on disk and builds
the catalog. It never writes to ``.library/``. File installation is the
initializer's job.

Tool surface: **none**. This capability registers no model-facing tool. The
former public ``skills`` root and its ``info`` action were removed as a clean
break — the one public root for this domain is now ``psyche``, whose
read-only ``psyche(action='skills')`` returns this package's manual. There is
no alias or compatibility wrapper for the old root or for ``skills.info``.

What remains is this capability's private lifecycle ownership, unchanged:
``setup()`` reconciles the catalog and injects the YAML ``skills`` prompt
section, honoring the configured ``paths``; ``_reconcile`` is re-run by
``Agent._install_intrinsic_manuals`` once manuals are on disk and by the one
full-context reconstruction path. Catalog scanning is never reachable from a
model-facing action.

Usage: ``Agent(capabilities={"skills": {"paths": [...]}})`` or via init.json.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from .._catalog import (
    build_catalog_yaml,
    parse_markdown_catalog_file,
    scan_markdown_catalog,
)
from lingtai.kernel.i18n import t

if TYPE_CHECKING:
    from lingtai.kernel.base_agent import BaseAgent

log = logging.getLogger(__name__)

PROVIDERS = {"providers": [], "default": "builtin"}


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


def _scan_one_skill(directory: Path) -> tuple[list[dict], list[dict]]:
    """Scan a path that *is* a skill directory rather than a collection of them.

    ``_scan`` looks for ``<child>/SKILL.md`` under the path it is given. A
    registered Agent Plugin contributes the individual skill directories that
    passed §4.1 containment, not their parent, so each of those paths carries its
    own ``SKILL.md`` one level up from where ``_scan`` would look. This parses it
    directly, which keeps the mounted set exactly the validated set — composing
    the parent instead would re-admit a skill the plugin registry rejected,
    because the recursive scanner follows symlinks.
    """
    entry, problem = parse_markdown_catalog_file(
        directory / "SKILL.md", directory.name, filename="SKILL.md",
    )
    return ([entry] if entry else []), ([problem] if problem else [])


def _compose_paths(agent: "BaseAgent", paths: list[str]) -> list[str]:
    """Union the declared Tier-1 paths with the registered plugins' skills.

    An Agent Plugin declared in ``init.json`` ``manifest.plugins`` is registered
    before capability setup (see ``services.plugin_registry.register_plugins``),
    and one thing registration produces is the absolute path of every *validated*
    skill directory inside each declared plugin. Composing those here — rather
    than copying the skill files anywhere — is what makes a plugin's skills
    appear in this catalog as ordinary skills, with their ``location`` pointing
    inside the plugin, so the plugin remains their visible source and
    uninstalling it removes them by simply not being declared any more.

    They are per-skill paths and not the plugin's ``skills/`` parent on purpose:
    a skill directory whose resolved path escapes the plugin root is rejected at
    registration, and handing this scan the parent would mount it anyway.

    Declared paths come first, plugin paths after, duplicates dropped: an
    operator who also lists a plugin's skill directory explicitly gets one scan,
    not two entries per skill.
    """
    ordered = list(paths)
    ordered.extend(
        p for p in getattr(agent, "_plugin_skill_paths", []) or [] if isinstance(p, str)
    )
    seen: set[str] = set()
    return [p for p in ordered if not (p in seen or seen.add(p))]


# ---------------------------------------------------------------------------
# Core reconciliation (setup/refresh lifecycle and full-context recompose)
# ---------------------------------------------------------------------------

def _reconcile(
    agent: "BaseAgent",
    paths: list[str],
    *,
    publish: bool = True,
) -> dict:
    """Scan ``.library/`` + Tier-1 paths, inject catalog, report status.

    The skills capability is pure presentation: it reads whatever the Agent
    initializer wrote to ``.library/intrinsic/`` and the agent wrote to
    ``.library/custom/``. It does NOT create directories or copy files, and it
    performs no migration.

    ``publish=False`` mirrors the Pad/LingTai composers: it writes the section
    without flushing, so full-context reconstruction composes every section
    before the one final prompt publication.
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

    # Scan each Tier 1 path, plus every registered plugin's validated skill dirs.
    paths_report: dict[str, dict] = {}
    for raw in _compose_paths(agent, paths):
        resolved = _resolve_path(raw, working_dir)
        exists = resolved.is_dir()
        p_valid: list[dict] = []
        p_problems: list[dict] = []
        if exists:
            # A path that carries SKILL.md is itself one skill (how a plugin
            # contributes); anything else is a collection to walk.
            if (resolved / "SKILL.md").is_file():
                p_valid, p_problems = _scan_one_skill(resolved)
            else:
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
    if publish:
        agent.update_system_prompt("skills", catalog_yaml or "", protected=True)
    else:
        agent._prompt_manager.write_section(
            "skills", catalog_yaml or "", protected=True,
        )
        agent._token_decomp_dirty = True

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


def setup(agent: "BaseAgent", paths: list[str] | None = None, **_ignored) -> None:
    """Set up the skills capability.

    ``paths`` is the Tier 1 list from ``init.json``
    ``manifest.capabilities.skills.paths``. When omitted (e.g. direct
    ``Agent(capabilities=["skills"])`` use without kwargs), no additional paths
    are scanned — only the per-agent ``.library/``.

    The capability itself does not create or populate ``.library/``; the Agent
    initializer's ``_install_intrinsic_manuals`` step handles that. Setup just
    scans whatever is on disk and injects the YAML catalog so the first turn
    sees a ready catalog.

    It registers **no** tool. Catalog reconciliation is private lifecycle: it
    runs here at setup/refresh and from the one full-context reconstruction
    path, never from a model-facing action. The public surface for this domain
    is the read-only ``psyche(action='skills')`` manual loader.
    """
    _reconcile(agent, list(paths) if paths else [])
