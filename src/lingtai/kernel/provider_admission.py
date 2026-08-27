"""Provider-call admission port for profiles that restrict model initiation.

The port protects *structural* provider-call paths.  It deliberately does not
claim to sandbox code that already runs in the same OS trust domain as a
full-tool agent.  A driving adapter supplies the policy/transport; Core owns
the typed parent context and makes every concrete ``send``/``generate`` call
cross this one boundary.
"""
from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol


class ProviderCallClass(str, Enum):
    """The execution shape requesting one actual model-provider call."""

    ROOT = "root"
    DAEMON = "daemon"
    AVATAR_CHILD = "avatar_child"


@dataclass(frozen=True, slots=True)
class RootProviderAdmission:
    """Core-private context for one admitted root turn.

    ``correlation_id`` is audit/routing material only.  It is never a bearer
    credential: production driver adapters must bind it to their own protected
    in-memory admission state before granting a call.
    """

    correlation_id: str
    policy_version: str


@dataclass(frozen=True, slots=True)
class DerivedProviderAdmission:
    """Core-private parent for a daemon/avatar provider call.

    ``execution_ref`` is intentionally opaque.  It must not contain a path,
    agent directory, workspace, argv, environment, or a reusable grant.
    """

    root: RootProviderAdmission
    call_class: ProviderCallClass
    execution_ref: str


ProviderAdmissionParent = RootProviderAdmission | DerivedProviderAdmission


@dataclass(frozen=True, slots=True)
class ProviderCallDecision:
    """A safe result of attempting one provider-call admission."""

    allowed: bool
    reason_code: str


class ProviderCallAdmissionPort(Protocol):
    """Driver-facing Core port, invoked once per actual provider call.

    Returning ``allowed=True`` is the adapter's linearization point for that
    one call.  Implementations must not cache a long-lived permit; Core calls
    this method again for the next ``send`` or ``generate``.
    """

    def authorize_provider_call(
        self,
        parent: ProviderAdmissionParent,
        call_class: ProviderCallClass,
    ) -> ProviderCallDecision: ...


class ProviderAdmissionError(PermissionError):
    """Raised before a provider request when admission is absent or denied."""

    def __init__(self, reason_code: str):
        self.reason_code = reason_code
        super().__init__(f"provider call was not admitted: {reason_code}")


_current_parent: ContextVar[ProviderAdmissionParent | None] = ContextVar(
    "lingtai_current_provider_admission", default=None
)


def bind_provider_admission(parent: ProviderAdmissionParent) -> Token:
    """Install one Core-private parent for the current execution context."""

    if not isinstance(parent, (RootProviderAdmission, DerivedProviderAdmission)):
        raise TypeError("parent must be a provider-admission context")
    return _current_parent.set(parent)


def clear_provider_admission(token: Token) -> None:
    """Restore the previous execution context after a turn/call completes."""

    _current_parent.reset(token)


def clear_current_provider_admission() -> None:
    """Fail closed when an exceptional path ends a Core execution context.

    Normal completion restores the exact prior context through the ``Token``
    returned by :func:`bind_provider_admission`.  The agent run-loop also
    calls this defensive cleanup in its outer ``finally`` so an exception
    cannot leave a root admission installed in a reused worker context.
    """

    _current_parent.set(None)


def current_provider_admission() -> ProviderAdmissionParent | None:
    """Return the current Core-private parent, if provider work is admitted."""

    return _current_parent.get()


def current_provider_call_class() -> ProviderCallClass:
    """Classify the current request without trusting caller-provided strings."""

    parent = current_provider_admission()
    if isinstance(parent, DerivedProviderAdmission):
        return parent.call_class
    return ProviderCallClass.ROOT


def require_provider_admission(port: ProviderCallAdmissionPort | None) -> None:
    """Cross the one structural provider boundary or fail before provider I/O.

    ``None`` retains generic LingTai behavior.  A constrained profile injects a
    real port and therefore fails closed for calls without a bound parent,
    malformed adapter decisions, or explicit denial.
    """

    if port is None:
        return
    parent = current_provider_admission()
    if parent is None:
        raise ProviderAdmissionError("missing_provider_admission")
    call_class = current_provider_call_class()
    try:
        decision = port.authorize_provider_call(parent, call_class)
    except Exception:
        decision = ProviderCallDecision(False, "provider_admission_port_error")
    if (
        not isinstance(decision, ProviderCallDecision)
        or not isinstance(decision.allowed, bool)
        or not isinstance(decision.reason_code, str)
        or not decision.reason_code
        or decision.allowed is not True
    ):
        reason = (
            decision.reason_code
            if isinstance(decision, ProviderCallDecision)
            and isinstance(decision.reason_code, str)
            and decision.reason_code
            else "provider_call_not_admitted"
        )
        raise ProviderAdmissionError(reason)


class ProviderAdmittedChatSession:
    """Transparent session proxy that checks admission for every send path."""

    __slots__ = ("_inner", "_port")

    def __init__(self, inner: Any, port: ProviderCallAdmissionPort):
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "_port", port)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self._inner, name, value)

    @property
    def interface(self):
        return self._inner.interface

    @property
    def pre_request_hook(self):
        return self._inner.pre_request_hook

    @pre_request_hook.setter
    def pre_request_hook(self, value) -> None:
        self._inner.pre_request_hook = value

    @staticmethod
    def reset_provider_turn_state(session) -> None:
        inner = getattr(session, "_inner", session)
        reset = getattr(type(inner), "reset_provider_turn_state", None)
        if callable(reset):
            reset(inner)

    def send(self, message):
        require_provider_admission(self._port)
        return self._inner.send(message)

    def send_stream(self, message, on_chunk=None):
        require_provider_admission(self._port)
        return self._inner.send_stream(message, on_chunk=on_chunk)


class ProviderAdmittedLLMService:
    """Service proxy ensuring every session and direct generation is gated."""

    __slots__ = ("_inner", "_port")

    def __init__(self, inner: Any, port: ProviderCallAdmissionPort):
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "_port", port)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def create_session(self, *args, **kwargs) -> ProviderAdmittedChatSession:
        return ProviderAdmittedChatSession(
            self._inner.create_session(*args, **kwargs), self._port
        )

    def get_session(self, session_id: str):
        session = self._inner.get_session(session_id)
        return (
            None
            if session is None
            else ProviderAdmittedChatSession(session, self._port)
        )

    def generate(self, *args, **kwargs):
        require_provider_admission(self._port)
        return self._inner.generate(*args, **kwargs)


__all__ = [
    "DerivedProviderAdmission",
    "ProviderAdmittedChatSession",
    "ProviderAdmittedLLMService",
    "ProviderAdmissionError",
    "ProviderAdmissionParent",
    "ProviderCallAdmissionPort",
    "ProviderCallClass",
    "ProviderCallDecision",
    "RootProviderAdmission",
    "bind_provider_admission",
    "clear_provider_admission",
    "clear_current_provider_admission",
    "current_provider_admission",
    "require_provider_admission",
]
