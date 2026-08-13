"""Provider-local live reasoning-effort descriptor for Claude Code.

Claude Code is a local CLI route rather than an HTTP wire.  The descriptor
therefore owns the installed CLI vocabulary and the exact model/CLI route
identity; the kernel only stores the resulting opaque capability and revision.
An omitted baseline is intentionally represented by ``None``: clearing a live
override must remove ``--effort`` rather than invent a provider value.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from lingtai.kernel.llm.reasoning_effort import ReasoningEffortCapability

from .adapter import CLAUDE_EFFORT_LEVELS


CLAUDE_EFFORT_INTEGRATION = "lingtai_main_agent_native"
CLAUDE_EFFORT_PROVIDER_ROUTE = "claude-code"
CLAUDE_EFFORT_WIRE = "claude_cli"
CLAUDE_EFFORT_PROVIDER_DEFAULT = None
CLAUDE_EFFORT_EVIDENCE_REVISION = 1


@dataclass(frozen=True)
class ClaudeEffortDescriptor:
    """The exact active Claude Code route used by one chat session."""

    integration: str
    provider_route: str
    model: str
    cli_path: str
    wire: str
    values: tuple[str, ...]
    provider_default: str | None
    construction_baseline: str | None
    evidence_revision: int

    @property
    def fingerprint(self) -> str:
        parts = "\0".join(
            (
                self.integration,
                self.provider_route,
                self.model,
                self.cli_path,
                self.wire,
                ",".join(self.values),
                self.provider_default or "provider-controlled",
                self.construction_baseline or "omitted",
                str(self.evidence_revision),
            )
        )
        return hashlib.sha256(parts.encode("utf-8")).hexdigest()[:16]

    def to_capability(self) -> ReasoningEffortCapability:
        return ReasoningEffortCapability(
            available=True,
            route=f"{self.provider_route}:{self.model}",
            values=self.values,
            provider_default=self.provider_default,
            baseline=self.construction_baseline,
            settable=True,
            fingerprint=self.fingerprint,
            evidence_revision=self.evidence_revision,
            reason=None,
        )


def resolve_claude_effort_descriptor(
    *,
    model: str | None,
    cli_path: str | None,
    construction_baseline: str | None,
) -> ClaudeEffortDescriptor | None:
    """Describe a supported Claude Code route, or fail closed.

    The installed CLI contract is provider-scoped and does not claim that
    model-specific upstream support has been independently verified.  Unknown
    or empty model/CLI identities and invalid configured effort remain
    unavailable instead of advertising a control that could be ignored.
    """
    if not isinstance(model, str) or not model.strip():
        return None
    if not isinstance(cli_path, str) or not cli_path.strip():
        return None
    if construction_baseline is not None and construction_baseline not in CLAUDE_EFFORT_LEVELS:
        return None
    return ClaudeEffortDescriptor(
        integration=CLAUDE_EFFORT_INTEGRATION,
        provider_route=CLAUDE_EFFORT_PROVIDER_ROUTE,
        model=model.strip(),
        cli_path=cli_path.strip(),
        wire=CLAUDE_EFFORT_WIRE,
        values=tuple(CLAUDE_EFFORT_LEVELS),
        provider_default=CLAUDE_EFFORT_PROVIDER_DEFAULT,
        construction_baseline=construction_baseline,
        evidence_revision=CLAUDE_EFFORT_EVIDENCE_REVISION,
    )
