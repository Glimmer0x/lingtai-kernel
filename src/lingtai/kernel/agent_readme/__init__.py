"""Agent-directory README.md \u2014 kernel-owned static navigation entry point.

Every agent working directory carries a static ``README.md`` at its root: a
navigation entry point for humans and tools reaching the folder. It is **not**
an operating manual (that role belongs to ``substrate.md`` via the resident
substrate section and its manuals) and it deliberately does **not** carry the
agent's identity or any live/dynamic values (see ``CONTRACT.md`` next to this
module).

The authoritative content lives in the packaged template ``README.md.tpl``;
there is deliberately **no** overlay or local-append mechanism. Regeneration
is a mechanical template-version check, not a heartbeat concern:
:func:`ensure_agent_readme` rewrites the file only when it is missing or its
head ``template_version`` differs from the packaged template's. The mount
points are the lifecycle moments \u2014 ``_perform_refresh``, agent molt, and
``BaseAgent`` construction \u2014 each wrapped fail-soft so a README problem can
never break lifecycle flow.

Secret discipline: the template contains no secret values and the renderer
accepts no facts, so credential material cannot reach the rendered file.
"""
from __future__ import annotations

import re
from importlib import resources as importlib_resources
from pathlib import Path

from .._fsutil import atomic_write_text
from ..workdir import WorkdirLayout, workdir_layout

__all__ = [
    "ensure_agent_readme",
    "render_readme",
    "template_version",
]

_TEMPLATE_RESOURCE = "README.md.tpl"

# Matches the `template_version:` field in the YAML-style head of both the
# packaged template and a rendered README.md. Only the head is scanned (the
# first _HEAD_SCAN_BYTES bytes) so a stray mention in body prose cannot
# masquerade as the version marker.
_TEMPLATE_VERSION_RE = re.compile(r"^template_version:\s*(\S+)\s*$", re.MULTILINE)
_HEAD_SCAN_BYTES = 2048


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


def render_readme(*, template: str | None = None) -> str:
    """Render the README template verbatim.

    Pure: no filesystem writes, no agent access, no placeholders \u2014 the
    template is fully static, so rendering is identity. Kept as a function so
    callers/tests exercise the packaged template through one path.
    """
    return template if template is not None else _read_template()


def ensure_agent_readme(
    layout_or_root: WorkdirLayout | Path | str,
    *,
    template: str | None = None,
    _log: callable | None = None,
) -> Path | None:
    """Generate ``README.md`` in the agent directory if missing or stale.

    The check is mechanical: compare the existing file's head
    ``template_version`` against the packaged template's; rewrite (atomically,
    tmp + rename via ``_fsutil.atomic_write_text``) only when the file is
    missing, unreadable, unversioned, or carries a different version. A
    version match is a strict no-op.

    Migration safety (P1-1): a pre-existing file with **no** ``template_version``
    head is taken over, not clobbered silently \u2014 its content is preserved as
    ``README.md.bak`` first and the takeover is emitted through ``_log`` when
    provided, so an upgrade never loses a user-written README without a trace.

    A packaged template that itself lost its version head raises (``ValueError``)
    instead of silently degrading into a rewrite-every-mount loop; mount call
    sites wrap fail-soft, so the failure is visible via their logging.

    Returns the written path, or None when the existing file is current.
    Raises on I/O failure; mount call sites wrap fail-soft.
    """
    layout = (
        layout_or_root
        if isinstance(layout_or_root, WorkdirLayout)
        else workdir_layout(layout_or_root)
    )
    target = layout.readme
    tpl = render_readme(template=template)
    current_version = template_version(tpl)
    if current_version is None:
        raise ValueError("agent_readme packaged template lost its template_version head")

    if target.is_file():
        try:
            with target.open(encoding="utf-8") as fh:
                existing_head = fh.read(_HEAD_SCAN_BYTES)
        except (OSError, UnicodeDecodeError):
            existing_head = ""
        existing_version = template_version(existing_head)
        if existing_version == current_version:
            return None
        if existing_version is None:
            # Takeover of a user-authored, unversioned README: preserve a
            # backup and log the event so the migration is never silent.
            try:
                backup = target.with_name("README.md.bak")
                atomic_write_text(backup, target.read_text(encoding="utf-8"), encoding="utf-8")
            except Exception:
                # Backup best-effort; the takeover itself proceeds so the
                # agent root still gains the navigation entry.
                pass
            if _log is not None:
                try:
                    _log("agent_readme_takeover", backup=str(backup))
                except Exception:
                    pass

    atomic_write_text(target, tpl, encoding="utf-8")
    return target
