"""Protocol-neutral, turn-scoped permission brokerage tests."""
from __future__ import annotations

from types import SimpleNamespace

from lingtai.kernel.tool_call_guard import ToolProposal
from lingtai.kernel.turn_permissions import (
    PermissionDecision,
    ToolPermissionRequest,
    bind_turn_permission_broker,
    broker_permission_check,
    clear_turn_permission_broker,
    current_turn_permission_broker,
    reset_turn_permission_broker,
)


class _Broker:
    def __init__(self, result=PermissionDecision.ALLOW, *, raises=False):
        self.result = result
        self.raises = raises
        self.requests = []

    def request_permission(self, request):
        self.requests.append(request)
        if self.raises:
            raise RuntimeError("private adapter error")
        return self.result


def _proposal():
    return ToolProposal(
        tool_name="shell",
        tool_args={"command": "never expose"},
        tool_call_id="provider-id",
        tool_trace_id="safe-trace",
        context={"path": "/private/path"},
    )


def test_unbound_broker_passes_through():
    clear_turn_permission_broker()
    assert broker_permission_check(_proposal()).allowed


def test_bound_broker_receives_only_safe_identity_and_reset_clears_scope():
    broker = _Broker()
    token = bind_turn_permission_broker(broker)
    try:
        assert current_turn_permission_broker() is broker
        decision = broker_permission_check(_proposal())
    finally:
        reset_turn_permission_broker(token)

    assert decision.allowed
    assert broker.requests == [ToolPermissionRequest("safe-trace", "shell")]
    assert current_turn_permission_broker() is None


def test_denial_exception_and_invalid_result_fail_closed_without_private_detail():
    for broker in (
        _Broker(PermissionDecision.DENY),
        _Broker(raises=True),
        _Broker(SimpleNamespace(value="allow")),
    ):
        token = bind_turn_permission_broker(broker)
        try:
            decision = broker_permission_check(_proposal())
        finally:
            reset_turn_permission_broker(token)
        assert not decision.allowed
        assert decision.check_name == "turn_permission_broker"
        assert "private adapter error" not in decision.reason
