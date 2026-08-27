"""Structural provider-call admission tests for the Puffo ACP profile."""
from __future__ import annotations

import pytest

from lingtai.adapters.acp.puffo_v0 import RUNTIME_POLICY
from lingtai.kernel.provider_admission import (
    DerivedProviderAdmission,
    ProviderAdmittedLLMService,
    ProviderAdmissionError,
    ProviderCallClass,
    ProviderCallDecision,
    RootProviderAdmission,
    bind_provider_admission,
    clear_provider_admission,
)


class _InnerSession:
    def __init__(self):
        self.calls = []
        self.interface = object()
        self.pre_request_hook = None

    def send(self, message):
        self.calls.append(("send", message))
        return message

    def send_stream(self, message, on_chunk=None):
        self.calls.append(("stream", message))
        return message


class _InnerService:
    def __init__(self):
        self.session = _InnerSession()
        self.generations = []

    def create_session(self, *_args, **_kwargs):
        return self.session

    def get_session(self, _session_id):
        return self.session

    def generate(self, prompt, **_kwargs):
        self.generations.append(prompt)
        return prompt


class _RecordingAdmissionPort:
    def __init__(self, *, allow=True):
        self.allow = allow
        self.calls = []

    def authorize_provider_call(self, parent, call_class):
        self.calls.append((parent, call_class))
        return ProviderCallDecision(
            allowed=self.allow,
            reason_code="allowed" if self.allow else "denied_by_test",
        )


class _MalformedAdmissionPort:
    def authorize_provider_call(self, _parent, _call_class):
        return ProviderCallDecision(allowed="yes", reason_code="malformed")


def test_every_session_send_and_generate_crosses_the_same_admission_port():
    inner = _InnerService()
    port = _RecordingAdmissionPort()
    service = ProviderAdmittedLLMService(inner, port)

    with pytest.raises(ProviderAdmissionError, match="missing_provider_admission"):
        service.create_session("system").send("untrusted")

    root = RootProviderAdmission("turn-a", "puffo-v0.test")
    token = bind_provider_admission(root)
    try:
        session = service.create_session("system")
        assert session.send("first") == "first"
        assert session.send_stream("second") == "second"
        assert service.generate("third") == "third"
    finally:
        clear_provider_admission(token)

    assert inner.session.calls == [("send", "first"), ("stream", "second")]
    assert inner.generations == ["third"]
    assert port.calls == [
        (root, ProviderCallClass.ROOT),
        (root, ProviderCallClass.ROOT),
        (root, ProviderCallClass.ROOT),
    ]


def test_derived_call_class_is_not_inferred_from_user_controlled_text():
    inner = _InnerService()
    port = _RecordingAdmissionPort()
    service = ProviderAdmittedLLMService(inner, port)
    root = RootProviderAdmission("turn-a", "puffo-v0.test")
    derived = DerivedProviderAdmission(root, ProviderCallClass.DAEMON, "opaque-run-a")

    token = bind_provider_admission(derived)
    try:
        service.create_session("system").send("work")
    finally:
        clear_provider_admission(token)

    assert port.calls == [(derived, ProviderCallClass.DAEMON)]


def test_denied_provider_admission_never_reaches_the_inner_service():
    """Attack oracle: a valid-looking root context cannot bypass a denial."""

    inner = _InnerService()
    service = ProviderAdmittedLLMService(inner, _RecordingAdmissionPort(allow=False))
    token = bind_provider_admission(RootProviderAdmission("turn-a", "test"))
    try:
        with pytest.raises(ProviderAdmissionError, match="denied_by_test"):
            service.create_session("system").send("attempt provider call")
    finally:
        clear_provider_admission(token)

    assert inner.session.calls == []


def test_malformed_admission_decision_fails_closed_before_provider_io():
    inner = _InnerService()
    service = ProviderAdmittedLLMService(inner, _MalformedAdmissionPort())
    token = bind_provider_admission(RootProviderAdmission("turn-a", "test"))
    try:
        with pytest.raises(ProviderAdmissionError, match="malformed"):
            service.create_session("system").send("attempt provider call")
    finally:
        clear_provider_admission(token)

    assert inner.session.calls == []


def test_puffo_root_only_policy_fails_closed_for_derived_model_calls():
    root = RootProviderAdmission("turn-a", RUNTIME_POLICY.policy_version)
    daemon = DerivedProviderAdmission(root, ProviderCallClass.DAEMON, "opaque-run-a")

    assert RUNTIME_POLICY.authorize_provider_call(
        root, ProviderCallClass.ROOT
    ).allowed is True
    denied = RUNTIME_POLICY.authorize_provider_call(daemon, ProviderCallClass.DAEMON)
    assert denied.allowed is False
    assert denied.reason_code == "host_mediated_derived_admission_required"
