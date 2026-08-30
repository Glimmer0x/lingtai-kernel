"""Psyche intrinsic — the one public root for the four durable domains.

``psyche`` is a mandatory, model-visible LTP v2 family whose public inventory
is manual loading plus read-only settings discovery. The name states the human
contract exactly: ``pad + lingtai + knowledge + skills = psyche``. Its exact
action set is ``pad | lingtai | knowledge | skills | settings | manual``:

- ``pad``, ``lingtai``, ``knowledge``, and ``skills`` each return that domain's
  own installed manual;
- ``settings`` returns the two fully redacted Psyche-owned Pad configuration
  rows;
- ``manual`` returns the psyche routing-table manual, which explains the four
  durable domains, which action loads which manual, and the generic
  mutation/rebuild model shared by all of them.

Every child takes the canonical strict-empty ``input``, so *every* ``input`` key
is an unknown key and is rejected before any handler runs. No child mutates
disk, prompt state, configuration, or a catalog: the family is read-only by
construction, not by convention.

This root replaces the four former public roots ``pad``, ``lingtai``,
``knowledge``, and ``skills``. That was a clean break: those roots, the
``pad.append`` action, and the ``skills.info`` / ``knowledge.info`` actions have
no alias, wrapper, or compatibility path and now fail as unknown tools/actions.

The name ``psyche`` was previously used by a different, long-dissolved family
whose actions were ``lingtai_update``, ``pad_edit``, ``context_molt``,
``name_set``, and similar. **Reusing the root name grants those actions
nothing.** They were dissolved into ``context`` (molt/summarize/rebuild) and
``system`` (name actions) and are not aliases here: every one of those spellings
fails as an unknown action before any I/O.

One name is deliberately reused rather than rejected: ``manual`` is a current,
accepted action, so a ``manual`` call succeeds — but it returns only the new
durable-self routing table (``psyche-manual``), never the dissolved family's
manual or body. Accepting that one name is not compatibility with any other old
action. Root reuse is not action compatibility.
The capabilities themselves did not disappear — they moved entirely to private
lifecycle ownership:

- durable text mutation is ``file.write`` (full create/overwrite) and
  ``file.edit`` (exact replacement), neither of which hot-loads the prompt;
- the pinned Pad reference list stays composed by the private ``_pad_load``
  from ``system/pad_append.json``;
- Skills/Knowledge catalog composition, configured Skills paths, and the
  one-time Knowledge legacy migration stay in those capabilities' own
  ``setup()``/refresh path;
- everything durable becomes prompt-visible through one explicit
  ``context.rebuild`` or passive refresh/molt reconstruction.

The kernel-owned ``substrate`` *prompt section*
(``lingtai/prompts/substrate/substrate.md`` → ``system/substrate.md``) is a
separate, unchanged concept: a resident prompt layer describing the agent's
architecture to itself. This family was briefly named ``substrate`` too; that
public root is gone, while the prompt section keeps its name, content,
ownership, and render order untouched.
"""
from __future__ import annotations

from typing import Any, Mapping

from ..tool_family import ChildTool, ToolFamily
from ..tool_family.manual import MANUAL_INPUT_SCHEMA, build_manual_child
from .settings import build_settings_provider

__all__ = [
    "ACTION_ORDER",
    "DOMAIN_MANUALS",
    "get_description",
    "get_schema",
    "handle",
]

#: The one canonical child registry, as ``(action, installed manual name)``.
#: Each domain action loads exactly the manual that already teaches that domain,
#: so the router itself carries no copy of their bodies — the manuals stay
#: progressively disclosed references rather than inlined prose. ``manual`` is
#: appended separately below via the shared reserved-child builder.
#:
#: The right-hand names are the installed destinations under
#: ``.library/intrinsic/capabilities/<name>/SKILL.md`` that
#: ``Agent._install_intrinsic_manuals`` writes: ``pad-manual`` and
#: ``lingtai-manual`` ship as ``intrinsic_skills`` bundles, while ``knowledge``
#: and ``skills`` ship as their tool packages' own ``manual/`` directories.
DOMAIN_MANUALS: tuple[tuple[str, str], ...] = (
    ("pad", "pad-manual"),
    ("lingtai", "lingtai-manual"),
    ("knowledge", "knowledge"),
    ("skills", "skills"),
)

#: The psyche routing-table manual: its own installed skill bundle, loaded by
#: the reserved ``manual`` child exactly like every domain child loads its own.
_ROUTER_MANUAL = "psyche-manual"

_DROPPED_ENVELOPE_KEYS = ("_tc_id",)


def _build_children(agent) -> list[ChildTool]:
    """Build the one fixed child registry.

    Every manual child — the four domain loaders and reserved router
    ``manual`` — is a :func:`build_manual_child`, so all five share one loader,
    one strict-empty input schema, and one canonical result adapter. The generic
    settings child is injected later by :class:`ToolFamily`.

    ``agent=None`` yields the schema-only family backing :func:`get_schema`.
    That is safe because :meth:`ToolFamily.build_schema` reads only each child's
    ``input_schema`` and never a handler; constructing it at import time also
    proves the registry has no duplicate or reserved-name collision.
    """
    children = [
        ChildTool(
            name=action,
            input_schema=dict(MANUAL_INPUT_SCHEMA),
            handler=build_manual_child(agent, manual_name).handler,
            title=f"{action} input",
        )
        for action, manual_name in DOMAIN_MANUALS
    ]
    return children + [build_manual_child(agent, _ROUTER_MANUAL)]


_FAMILY = ToolFamily("psyche", _build_children(None), settings_provider=tuple)

#: The exact public action inventory comes from the same composed family as the
#: schema, including its injected reserved settings child.
ACTION_ORDER: tuple[str, ...] = _FAMILY.child_names

_ACTION_ENUM_DESCRIPTION = (
    "Required Psyche operation. Every action takes an empty input object and "
    "is strictly read-only — none of them writes a file, "
    "reloads the prompt, or rescans a catalog.\n"
    "pad: return pad-manual (the sketchboard body at system/pad.md and its "
    "pinned read-only references).\n"
    "lingtai: return lingtai-manual (your 灵台 / character at system/lingtai.md).\n"
    "knowledge: return the knowledge manual (private durable entries under "
    "knowledge/<name>/KNOWLEDGE.md).\n"
    "skills: return the skills manual (your catalog under .library/ plus any "
    "configured skills paths).\n"
    "settings: return the redacted five-field inventory of Psyche-owned Pad "
    "configuration.\n"
    "manual: return the psyche routing table — which action loads which "
    "domain manual, and the shared mutation/rebuild model.\n"
    "To CHANGE any durable source, use file.write for a full rewrite or "
    "file.edit for exact replacement, then apply it with one explicit "
    "context.rebuild; file mutation never hot-loads the prompt."
)


def get_description(lang: str = "en") -> str:
    return (
        "SIGNPOST ONLY: your psyche is your four durable domains — pad, "
        "lingtai (灵台), knowledge, and skills. Domain actions return manuals; "
        "settings returns one compact redacted inventory. It never authors, "
        "edits, pins, installs, rescans, or loads anything. "
        "psyche(action='pad'|'lingtai'|'knowledge'|'skills', "
        "input={}, reasoning='why') returns that domain's manual; "
        "psyche(action='settings', input={}, reasoning='why') returns the two "
        "Psyche-owned Pad settings with both values redacted; "
        "psyche(action='manual', input={}, reasoning='why') returns the "
        "routing table that says which one you want and how the domains relate. "
        "Durable content is changed with file.write (full rewrite) or file.edit "
        "(exact replacement) on the domain's own source, and becomes visible "
        "only after an explicit context.rebuild or passive refresh/molt "
        "reconstruction. Read the relevant manual before acting on a domain you "
        "do not already know. Results are exact guidance — leave root summarize "
        "false."
    )


def get_schema(lang: str = "en") -> dict:
    # Composed from the same child registry runtime dispatch uses, so the public
    # action enum cannot drift from the dispatch keys.
    schema = _FAMILY.build_schema()
    schema["properties"]["action"]["description"] = _ACTION_ENUM_DESCRIPTION
    return schema


def _adapt_manual_result(mcp_result: dict) -> dict:
    """Flatten one dispatched child's canonical result to psyche's shape.

    This one adapter serves all five manual children; settings never returns a
    ``content`` block and bypasses it. It runs strictly after dispatch, in this
    Host layer, never inside a registered child, per the no-double-wrap rule
    (``../CONTRACT.md`` "Dispatch and actions").
    """
    flat: dict[str, Any] = {
        "status": mcp_result.get("status", "ok"),
        "manual": mcp_result["content"][0]["text"],
        "manual_path": mcp_result["structuredContent"]["manual_path"],
    }
    if "error" in mcp_result:
        flat["error"] = mcp_result["error"]
    return flat


def handle(agent, args: dict) -> dict:
    """Validate the strict LTP v2 envelope and dispatch one psyche action.

    ``ToolFamily.handle`` is the always-authoritative, fail-closed boundary: an
    unknown or missing action, and any ``input`` key at all (every child's input
    is strict-empty), is rejected before the selected provider/loader runs.
    """
    raw = dict(args or {})
    for key in _DROPPED_ENVELOPE_KEYS:
        raw.pop(key, None)

    action = raw.get("action")
    result = ToolFamily(
        "psyche",
        _build_children(agent),
        settings_provider=build_settings_provider(agent),
    ).handle(raw)
    if "content" in result:
        return _adapt_manual_result(result)
    if result.get("error_code") == "ACTION_REQUIRED":
        return {
            "error": (
                f"Unknown psyche action: {action if action is not None else ''}. "
                f"Must be one of: {', '.join(ACTION_ORDER)}."
            )
        }
    return result


def boot(agent) -> None:
    """Run the Pad and LingTai domains' initial internal composition.

    This is lifecycle, not a public action, and it is the reason this hook
    exists here at all: ``pad`` and ``lingtai`` are no longer registered
    intrinsics, so the kernel's ``boot(agent)`` loop no longer reaches their
    modules. Their private canonical composers still must run once at
    construction, exactly as before, so the ``pad`` and ``character`` prompt
    sections exist before the first turn.

    Ownership is unchanged: ``_pad_load`` and ``_lingtai_load`` remain the
    domains' own composers and remain the same functions
    ``Agent._reload_prompt_sections`` calls inside the one full reconstruction
    path. This hook only invokes them; it neither reimplements nor wraps them,
    and it registers no lifecycle hook of its own (Agent owns the single
    post-molt hook, ``_reconstruct_context``).

    ``knowledge`` and ``skills`` are deliberately absent here: they are
    *capabilities*, so their initial catalog composition still runs from their
    own ``setup()`` through the capability lifecycle.
    """
    from ..pad import _pad_load
    from ..lingtai import _lingtai_load

    _pad_load(agent, {})
    _lingtai_load(agent, {})
