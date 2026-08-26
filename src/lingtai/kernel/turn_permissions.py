"""Protocol-neutral, turn-scoped tool permission brokerage."""
from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from .tool_call_guard import GuardDecision, ToolProposal


@dataclass(frozen=True, slots=True)
class ToolPermissionRequest:
    """Safe tool identity presented for a one-shot permission decision."""

    tool_call_id: str
    tool_name: str


class PermissionDecision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"


class TurnPermissionBroker(Protocol):
    """Optional outbound Port deciding whether one proposed tool may dispatch."""

    def request_permission(
        self, request: ToolPermissionRequest
    ) -> PermissionDecision: ...


_CURRENT: ContextVar[TurnPermissionBroker | None] = ContextVar(
    "lingtai_turn_permission_broker", default=None
)


def current_turn_permission_broker() -> TurnPermissionBroker | None:
    return _CURRENT.get()


def bind_turn_permission_broker(
    broker: TurnPermissionBroker | None,
) -> Token[TurnPermissionBroker | None]:
    return _CURRENT.set(broker)


def reset_turn_permission_broker(token: Token[TurnPermissionBroker | None]) -> None:
    _CURRENT.reset(token)


def clear_turn_permission_broker() -> None:
    _CURRENT.set(None)


def broker_permission_check(proposal: ToolProposal) -> GuardDecision:
    """Require the current broker's exact ALLOW decision, failing closed."""

    broker = _CURRENT.get()
    if broker is None:
        return GuardDecision.allow()
    try:
        result = broker.request_permission(
            ToolPermissionRequest(
                tool_call_id=proposal.tool_trace_id or proposal.tool_call_id or "",
                tool_name=proposal.tool_name,
            )
        )
    except Exception:
        result = PermissionDecision.DENY
    if result is PermissionDecision.ALLOW:
        return GuardDecision.allow(check_name="turn_permission_broker")
    return GuardDecision.deny(
        check_name="turn_permission_broker",
        reason="tool permission was not granted",
    )


__all__ = [
    "PermissionDecision",
    "ToolPermissionRequest",
    "TurnPermissionBroker",
    "bind_turn_permission_broker",
    "broker_permission_check",
    "clear_turn_permission_broker",
    "current_turn_permission_broker",
    "reset_turn_permission_broker",
]
