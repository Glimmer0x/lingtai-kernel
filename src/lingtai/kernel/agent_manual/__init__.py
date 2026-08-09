"""Agent-directory MANUAL.md — kernel-owned generated operational guide.

Every agent working directory carries a generated ``MANUAL.md`` at its root:
the agent's own 说明书 — a progressive-disclosure operational-guide entry that
supplements the resident substrate section. The authoritative content lives in
the packaged template ``MANUAL.md.tpl``; there is deliberately **no** overlay
or local-append mechanism — humans change the manual for every agent by
changing the template via a kernel PR, never by leaving private overrides in
an agent directory (see ``CONTRACT.md`` next to this module).

Regeneration is a mechanical template-version check, not a heartbeat concern:
:func:`ensure_agent_manual` rewrites the file only when it is missing or its
head ``template_version`` differs from the packaged template's. The mount
points are the context-rebuild moments — ``_perform_refresh``, agent molt, and
``BaseAgent`` construction — each wrapped fail-soft so a manual problem can
never break lifecycle flow.

Secret discipline: the renderer never reads ``.secrets/`` and the facts dict
is scrubbed through the same secret-key redaction the resolved manifest uses,
so credential material cannot reach the rendered file even if a caller passes
it by mistake.
"""
from __future__ import annotations

import re
from importlib import resources as importlib_resources
from pathlib import Path

from .._fsutil import atomic_write_text
from ..workdir import WorkdirLayout, _redact_secrets, workdir_layout

__all__ = [
    "collect_agent_facts",
    "ensure_agent_manual",
    "render_manual",
    "template_version",
]

_TEMPLATE_RESOURCE = "MANUAL.md.tpl"

# Matches the `template_version:` field in the YAML-style head of both the
# packaged template and a rendered MANUAL.md. Only the head is scanned (the
# first _HEAD_SCAN_BYTES bytes) so a stray mention in body prose cannot
# masquerade as the version marker.
_TEMPLATE_VERSION_RE = re.compile(r"^template_version:\s*(\S+)\s*$", re.MULTILINE)
_HEAD_SCAN_BYTES = 2048

# `{{key}}` placeholders substituted from the facts dict at render time.
_PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")

#: Rendered in place of a fact the caller did not (or could not) provide.
_UNKNOWN = "unknown"


def _read_template() -> str:
    return (
        importlib_resources.files(__package__)
        .joinpath(_TEMPLATE_RESOURCE)
        .read_text(encoding="utf-8")
    )


def template_version(text: str) -> str | None:
    """Return the ``template_version`` declared in *text*'s head, or None."""
    match = _TEMPLATE_VERSION_RE.search(text[:_HEAD_SCAN_BYTES])
    return match.group(1) if match else None


def render_manual(facts: dict | None = None, *, template: str | None = None) -> str:
    """Render the manual template with *facts* substituted into ``{{key}}`` slots.

    Pure: no filesystem writes, no agent access — callers gather facts (see
    :func:`collect_agent_facts`) and pass them in, which is what makes the
    renderer directly testable. Secret-named keys are dropped from *facts*
    before substitution; missing or None facts render as ``unknown``.
    """
    tpl = template if template is not None else _read_template()
    safe_facts = _redact_secrets(dict(facts or {}))

    def _substitute(match: re.Match) -> str:
        value = safe_facts.get(match.group(1))
        if value is None or value == "":
            return _UNKNOWN
        return str(value)

    return _PLACEHOLDER_RE.sub(_substitute, tpl)


def ensure_agent_manual(
    layout_or_root: WorkdirLayout | Path | str,
    *,
    facts: dict | None = None,
) -> Path | None:
    """Generate ``MANUAL.md`` in the agent directory if missing or stale.

    The check is mechanical: compare the existing file's head
    ``template_version`` against the packaged template's; rewrite (atomically,
    tmp + rename via ``_fsutil.atomic_write_text``) only when the file is
    missing, unreadable, unversioned, or carries a different version. A
    version match is a strict no-op — the live-snapshot facts are *not*
    refreshed outside a template bump, by design (see CONTRACT.md).

    Returns the written path, or None when the existing file is current.
    Raises on I/O failure; mount call sites wrap fail-soft.
    """
    layout = (
        layout_or_root
        if isinstance(layout_or_root, WorkdirLayout)
        else workdir_layout(layout_or_root)
    )
    target = layout.manual
    tpl = _read_template()
    current_version = template_version(tpl)

    if target.is_file():
        try:
            existing_head = target.read_text(encoding="utf-8")[:_HEAD_SCAN_BYTES]
        except OSError:
            existing_head = ""
        if current_version is not None and template_version(existing_head) == current_version:
            return None

    atomic_write_text(target, render_manual(facts, template=tpl))
    return target


def collect_agent_facts(agent, manifest: dict | None = None) -> dict:
    """Gather the live-snapshot facts dict from a (Base)Agent, fail-soft.

    Every field is optional: any attribute that is absent or raises simply
    stays out of the dict and renders as ``unknown``. The LLM block comes from
    ``_build_manifest``'s safelisted ``llm`` extraction, so no credential
    fields can enter here; :func:`render_manual` re-scrubs regardless.

    *manifest* lets the construction mount pass the just-built manifest dict
    instead of re-invoking ``_build_manifest`` (whose subclass override may
    depend on attributes the subclass has not set yet mid-``__init__``).
    """
    facts: dict = {}
    if manifest is None:
        try:
            manifest = agent._build_manifest()
        except Exception:
            manifest = {}

    for key in ("agent_name", "agent_id", "created_at", "molt_count"):
        value = manifest.get(key)
        if value is not None:
            facts[key] = value

    llm = manifest.get("llm")
    if isinstance(llm, dict):
        for key in ("provider", "model", "context_limit"):
            if llm.get(key) is not None:
                facts[key] = llm[key]

    preset = manifest.get("preset")
    if isinstance(preset, dict) and preset.get("active"):
        facts["preset"] = preset["active"]

    thread = getattr(agent, "_heartbeat_thread", None)
    facts["heartbeat"] = (
        "publishing" if thread is not None and thread.is_alive() else "not started"
    )

    try:
        identity = getattr(agent, "_runtime_identity_event_fields", None) or {}
        stamp = identity.get("kernel_runtime_stamp")
        version = identity.get("kernel_version")
        if stamp or version:
            facts["source_revision"] = " ".join(
                str(part) for part in (version, stamp) if part
            )
    except Exception:
        pass

    handlers = getattr(agent, "_tool_handlers", None)
    if isinstance(handlers, dict):
        facts["mcp_status"] = f"{len(handlers)} non-intrinsic tool(s) registered"

    working_dir = getattr(agent, "_working_dir", None)
    if working_dir is not None:
        facts["workdir"] = str(working_dir)
        facts["pad_pointer"] = "system/pad.md"

    return facts
