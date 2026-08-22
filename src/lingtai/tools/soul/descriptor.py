"""Package-local model-facing descriptor for the ``soul`` root.

This descriptor intentionally owns only stable presentation and installed-manual
identity.  The existing soul module consumes it for its model-facing prose, its
one public root name, and the reserved manual child's installed skill name; the
strict action schemas and all lifecycle behavior remain in ``__init__.py`` and
its sibling owners.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SoulModelDescriptor:
    """Stable model-facing identity for the soul family, local to this package."""

    root_name: str
    description: str
    manual_skill_name: str


SOUL_MODEL_DESCRIPTOR = SoulModelDescriptor(
    root_name="soul",
    description=(
        "Your inner voice. One tool, six actions, each with its own strict input "
        "object: soul(action=..., input={...}, reasoning='why'). flow is OPT-IN "
        "and DISABLED by default: it runs only when the operator sets env "
        "LINGTAI_SOUL_FLOW_ENABLED=1 (then refreshes). While disabled, "
        "soul(action='flow', input={}) returns status='disabled' (not an error — "
        "do not retry); inquiry/config/voice/dismiss still work. When enabled, "
        "flow fires periodic past-self consultation every soul_delay seconds "
        "while IDLE — M=1+K parallel LLM calls (1 stepped-back read of current "
        "chat + K past-snapshot voices) arrive as an involuntary "
        "soul(action='flow') pair. delay_seconds is only the cadence after "
        "opt-in, NOT an off switch, and no action in this family can enable flow. "
        "inquiry: ask a deep copy of yourself a question; answer returns in the "
        "tool result. config: tune flow knobs at runtime (delay_seconds, "
        "consultation_past_count) — does not enable flow. voice: read or choose "
        "how your own soul-flow voice sounds. dismiss: clear the current flow "
        "notification. manual: return the installed soul-manual skill without "
        "performing any soul operation. Results are small, so leave root summarize "
        "false (short-result profile); call manual with summarize=false so the "
        "exact procedure is not summarized away. See soul-manual for details."
    ),
    manual_skill_name="soul-manual",
)
