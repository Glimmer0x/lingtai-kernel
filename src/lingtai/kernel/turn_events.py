"""Protocol-neutral, turn-scoped tool lifecycle observation."""
from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class ToolLifecycleState(str, Enum):
    """A bounded lifecycle fact emitted by Core tool dispatch."""

    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    DENIED = "denied"


@dataclass(frozen=True, slots=True)
class ToolLifecycleEvent:
    """Safe tool identity and state; arguments and results are intentionally absent."""

    tool_call_id: str
    tool_name: str
    state: ToolLifecycleState


class TurnToolObserver(Protocol):
    """Optional outbound Port for observing one turn's tool lifecycle."""

    def on_tool_lifecycle(self, event: ToolLifecycleEvent) -> None: ...


_CURRENT: ContextVar[TurnToolObserver | None] = ContextVar(
    "lingtai_turn_tool_observer", default=None
)


def current_turn_tool_observer() -> TurnToolObserver | None:
    return _CURRENT.get()


def bind_turn_tool_observer(
    observer: TurnToolObserver | None,
) -> Token[TurnToolObserver | None]:
    return _CURRENT.set(observer)


def reset_turn_tool_observer(token: Token[TurnToolObserver | None]) -> None:
    _CURRENT.reset(token)


def clear_turn_tool_observer() -> None:
    """Clear observer scope at a terminal run-loop boundary."""

    _CURRENT.set(None)


def notify_tool_lifecycle(event: ToolLifecycleEvent) -> None:
    """Notify the active observer without allowing it to affect tool execution."""

    observer = _CURRENT.get()
    if observer is None:
        return
    try:
        observer.on_tool_lifecycle(event)
    except Exception:
        pass


__all__ = [
    "ToolLifecycleEvent",
    "ToolLifecycleState",
    "TurnToolObserver",
    "bind_turn_tool_observer",
    "clear_turn_tool_observer",
    "current_turn_tool_observer",
    "notify_tool_lifecycle",
    "reset_turn_tool_observer",
]
