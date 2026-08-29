"""Structural provider-call admission tests for the Puffo ACP profile."""
from __future__ import annotations

import ast
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from lingtai.adapters.acp.puffo_v0 import RUNTIME_POLICY
from lingtai.kernel.provider_admission import (
    DerivedLaunchAdmissionError,
    DerivedLaunchCapability,
    DerivedLaunchDecision,
    ProviderAdmittedLLMService,
    ProviderAdmissionError,
    ProviderAdmissionState,
    ProviderCallClass,
    ProviderCallDecision,
    RootProviderAdmission,
    begin_derived_provider_admission,
    bind_provider_admission,
    clear_provider_admission,
    current_provider_call_audit_id,
    require_derived_launch_admission,
)
from lingtai.kernel.llm_utils import send_with_timeout, send_with_timeout_stream
from lingtai.llm.api_gate import APICallGate
from lingtai.llm.base import _GatedSession
from lingtai.tools.soul.consultation import _send_with_timeout as soul_send_with_timeout


class _InnerSession:
    def __init__(self):
        self.calls = []
        self.audit_ids = []
        self.interface = object()
        self.pre_request_hook = None

    def send(self, message):
        self.calls.append(("send", message))
        self.audit_ids.append(current_provider_call_audit_id())
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
    def __init__(self, *, state=ProviderAdmissionState.GRANTED):
        self.state = state
        self.calls = []

    def authorize_provider_call(self, parent, call_class):
        self.calls.append((parent, call_class))
        return ProviderCallDecision(
            state=self.state,
            reason_code=(
                "allowed"
                if self.state is ProviderAdmissionState.GRANTED
                else "denied_by_test"
            ),
        )


class _AuditRecordingAdmissionPort:
    """A Driver-shaped port whose audit log is the E2E adjudication oracle."""

    def __init__(self):
        self.adjudications = []

    def authorize_provider_call(self, _parent, _call_class):
        audit_id = f"audit-{len(self.adjudications) + 1}"
        self.adjudications.append(audit_id)
        return ProviderCallDecision(
            ProviderAdmissionState.GRANTED,
            "allowed",
            audit_id=audit_id,
        )


class _AuditRecordingInnerService:
    """A recording transport that observes only the scoped audit trace."""

    def __init__(self, *, fan_out: bool = False):
        self.provider_calls = []
        self._fan_out = fan_out

    def generate(self, _prompt, **_kwargs):
        audit_id = current_provider_call_audit_id()
        self.provider_calls.append(audit_id)
        if self._fan_out:
            self.provider_calls.append(audit_id)
        return "generated"


class _MalformedAdmissionPort:
    def authorize_provider_call(self, _parent, _call_class):
        return ProviderCallDecision(state="granted", reason_code="malformed")


class _RaisingAdmissionPort:
    def authorize_provider_call(self, _parent, _call_class):
        raise RuntimeError("authority unavailable")


class _RecordingDerivedLaunchPort:
    def __init__(self, *, state=ProviderAdmissionState.GRANTED):
        self.state = state
        self.calls = []

    def authorize_derived_launch(self, parent, capability):
        self.calls.append((parent, capability))
        return DerivedLaunchDecision(
            state=self.state,
            reason_code=(
                "derived_launch_allowed"
                if self.state is ProviderAdmissionState.GRANTED
                else "derived_launch_denied_by_test"
            ),
            audit_id="audit-derived-test",
            child_endpoint_lease=object() if self.state is ProviderAdmissionState.GRANTED else None,
        )


class _CloseTrackingLease:
    """Opaque lease stand-in used to prove Core disposes rejected grants."""

    def __init__(self):
        self.close_calls = 0

    def close(self):
        self.close_calls += 1


def test_raw_provider_service_construction_inventory_is_explicit():
    """A new raw service constructor must be classified before it can land.

    Root composition and refresh create an LLMService before BaseAgent wraps it
    at the provider boundary. The historical daemon constructor is deliberately
    listed as an uncovered derived route until the driver-mediated adapter is
    wired. This recognizes direct names, imported aliases, and attribute calls;
    it is not a whole-program proof over dynamic factories or subclasses. It is
    an inventory tripwire: a newly introduced direct constructor fails review
    until it is classified and its profile semantics are made explicit.
    """
    root = Path(__file__).resolve().parents[1]
    counts: dict[str, int] = {}
    for source in (root / "src" / "lingtai").rglob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        aliases = {"LLMService"}
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            for imported in node.names:
                if imported.name == "LLMService":
                    aliases.add(imported.asname or imported.name)
        count = sum(
            isinstance(node, ast.Call)
            and (
                isinstance(node.func, ast.Name) and node.func.id in aliases
                or isinstance(node.func, ast.Attribute) and node.func.attr == "LLMService"
            )
            for node in ast.walk(tree)
        )
        if count:
            counts[str(source.relative_to(root))] = count

    assert counts == {
        "src/lingtai/cli.py": 1,
        "src/lingtai/agent.py": 1,
        "src/lingtai/tools/daemon/__init__.py": 1,
    }


def _direct_constructor_calls(source: str, targets: set[str]) -> set[tuple[str, str]]:
    """Return statically visible direct request-constructor call sites.

    The helper is intentionally not a resolver: dynamic factories, registry
    lookup, and subclass/wrapper overrides are reviewed outside this narrow
    source inventory.  It does cover the direct forms promised by the
    Contract, including aliases introduced through package re-exports.
    """
    tree = ast.parse(source)
    aliases = set(targets)
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        for imported in node.names:
            if imported.name in targets:
                aliases.add(imported.asname or imported.name)

    calls: set[tuple[str, str]] = set()

    class _InventoryVisitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self._scope: list[str] = []

        def _visit_scoped(self, node: ast.AST, name: str) -> None:
            self._scope.append(name)
            self.generic_visit(node)
            self._scope.pop()

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            self._visit_scoped(node, node.name)

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._visit_scoped(node, node.name)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self._visit_scoped(node, node.name)

        def visit_Call(self, node: ast.Call) -> None:
            if isinstance(node.func, ast.Name) and node.func.id in aliases:
                constructor = node.func.id
            elif (
                isinstance(node.func, ast.Attribute)
                and node.func.attr in targets
            ):
                constructor = node.func.attr
            else:
                self.generic_visit(node)
                return
            calls.add((".".join(self._scope) or "<module>", constructor))
            self.generic_visit(node)

    _InventoryVisitor().visit(tree)
    return calls


def test_derived_launch_constructor_inventory_matches_promised_static_forms():
    """Direct names, aliases/re-exports, and attribute calls remain covered."""
    source = """\
from package import DaemonSupervisorRequest as Request
import package as pkg

def direct():
    DaemonSupervisorRequest()
    Request()

class Launcher:
    def by_attribute(self):
        pkg.AvatarLaunchRequest()
"""

    assert _direct_constructor_calls(
        source, {"DaemonSupervisorRequest", "AvatarLaunchRequest"}
    ) == {
        ("direct", "DaemonSupervisorRequest"),
        ("direct", "Request"),
        ("Launcher.by_attribute", "AvatarLaunchRequest"),
    }


def test_derived_launch_constructor_inventory_is_explicit():
    """Every direct derived-launch request constructor needs classification.

    This is step 1 of the v0 derived-admission transition.  It intentionally
    inventories the request constructors, rather than claiming that a green
    static scan proves every possible launch route: dynamic factories,
    registry lookup, and subclass/wrapper overrides remain Contract-declared
    blind spots for focused review and production-path E2E.

    Direct names, ``from … import … as`` aliases (including package
    re-exports), and attribute calls are all matched.  A new direct request
    constructor must be explicitly classified before it can land.
    """
    root = Path(__file__).resolve().parents[1]
    targets = {"DaemonSupervisorRequest", "AvatarLaunchRequest"}
    inventory: set[tuple[str, str, str]] = set()

    for source in (root / "src" / "lingtai").rglob("*.py"):
        for scope, constructor in _direct_constructor_calls(
            source.read_text(encoding="utf-8"), targets
        ):
            inventory.add((str(source.relative_to(root)), scope, constructor))

    assert inventory == {
        # Decode is not a launch, but it is the one wire re-construction point
        # and therefore must stay visible beside the production constructors.
        ("src/lingtai/kernel/daemon_supervisor/__init__.py", "decode_request",
         "DaemonSupervisorRequest"),
        # LingTai-backend daemon launch and external-CLI daemon launch.
        ("src/lingtai/tools/daemon/__init__.py", "DaemonManager._spawn_detached_lingtai_run",
         "DaemonSupervisorRequest"),
        ("src/lingtai/tools/daemon/__init__.py", "DaemonManager._handle_emanate_cli",
         "DaemonSupervisorRequest"),
        # Avatar detached-child launch.
        ("src/lingtai/tools/avatar/__init__.py", "AvatarManager._launch",
         "AvatarLaunchRequest"),
    }


def test_provider_dispatch_concurrency_inventory_is_explicit():
    """Concurrency creation points must be classified before they can land.

    Provider admission is ambient state at the Core boundary.  A new thread or
    executor can therefore become a previously-unseen propagation boundary.
    This source inventory is deliberately broad: each entry is classified in
    the provider-admission Contract as either a propagation boundary or a
    non-provider worker.  Adding a creation point without updating that
    classification must fail review.
    """
    root = Path(__file__).resolve().parents[1]
    constructors = {
        "Thread",
        "ThreadPoolExecutor",
        "ProcessPoolExecutor",
        "to_thread",
        "run_in_executor",
    }
    inventory: set[tuple[str, int, str]] = set()
    for source in (root / "src" / "lingtai").rglob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name) and node.func.id in constructors:
                constructor = node.func.id
            elif (
                isinstance(node.func, ast.Attribute)
                and node.func.attr in constructors
            ):
                constructor = node.func.attr
            else:
                continue
            inventory.add((str(source.relative_to(root)), node.lineno, constructor))

    provider_context_propagation = {
        ("src/lingtai/kernel/session.py", 289, "ThreadPoolExecutor"),
        ("src/lingtai/tools/soul/consultation.py", 67, "Thread"),
    }
    post_admission_provider_dispatch = {
        ("src/lingtai/llm/api_gate.py", 44, "ThreadPoolExecutor"),
        ("src/lingtai/llm/api_gate.py", 45, "Thread"),
    }
    outside_root_provider_dispatch = {
        ("src/lingtai/adapters/acp/server.py", 277, "Thread"),
        ("src/lingtai/adapters/acp/server.py", 304, "Thread"),
        ("src/lingtai/adapters/acp/server.py", 726, "Thread"),
        ("src/lingtai/adapters/browser_transport.py", 56, "Thread"),
        ("src/lingtai/adapters/posix/daemon_manager.py", 283, "Thread"),
        ("src/lingtai/adapters/posix/daemon_manager.py", 506, "Thread"),
        ("src/lingtai/adapters/posix/mail.py", 282, "Thread"),
        ("src/lingtai/kernel/base_agent/lifecycle.py", 444, "Thread"),
        ("src/lingtai/kernel/base_agent/lifecycle.py", 623, "Thread"),
        ("src/lingtai/kernel/base_agent/lifecycle.py", 799, "Thread"),
        ("src/lingtai/kernel/llm_utils.py", 302, "ThreadPoolExecutor"),
        ("src/lingtai/kernel/nudge/__init__.py", 230, "Thread"),
        ("src/lingtai/kernel/nudge/kernel_version.py", 137, "Thread"),
        ("src/lingtai/kernel/preset_connectivity.py", 211, "ThreadPoolExecutor"),
        ("src/lingtai/kernel/session_stats/__init__.py", 461, "Thread"),
        ("src/lingtai/kernel/tool_executor.py", 1625, "ThreadPoolExecutor"),
        ("src/lingtai/llm/openai/codex_quota.py", 153, "Thread"),
        ("src/lingtai/mcp_servers/cloud_mail/manager.py", 391, "Thread"),
        ("src/lingtai/mcp_servers/cloud_mail/server.py", 173, "to_thread"),
        ("src/lingtai/mcp_servers/feishu/account.py", 475, "Thread"),
        ("src/lingtai/mcp_servers/feishu/server.py", 711, "to_thread"),
        ("src/lingtai/mcp_servers/feishu/task_card.py", 323, "Thread"),
        ("src/lingtai/mcp_servers/feishu/task_card.py", 404, "Thread"),
        ("src/lingtai/mcp_servers/imap/account.py", 880, "Thread"),
        ("src/lingtai/mcp_servers/imap/bridge.py", 62, "Thread"),
        ("src/lingtai/mcp_servers/imap/server.py", 639, "to_thread"),
        ("src/lingtai/mcp_servers/telegram/account.py", 285, "Thread"),
        ("src/lingtai/mcp_servers/telegram/manager.py", 451, "Thread"),
        ("src/lingtai/mcp_servers/telegram/manager.py", 2587, "Thread"),
        ("src/lingtai/mcp_servers/telegram/manager.py", 3633, "Thread"),
        ("src/lingtai/mcp_servers/telegram/manager.py", 3663, "Thread"),
        ("src/lingtai/mcp_servers/telegram/server.py", 755, "to_thread"),
        ("src/lingtai/mcp_servers/telegram/task_card/controller.py", 429, "Thread"),
        ("src/lingtai/mcp_servers/wechat/manager.py", 223, "Thread"),
        ("src/lingtai/mcp_servers/wechat/server.py", 937, "to_thread"),
        ("src/lingtai/mcp_servers/whatsapp/client.py", 104, "Thread"),
        ("src/lingtai/mcp_servers/whatsapp/client.py", 111, "Thread"),
        ("src/lingtai/mcp_servers/whatsapp/server.py", 218, "to_thread"),
        ("src/lingtai/services/mcp.py", 574, "Thread"),
        ("src/lingtai/services/mcp.py", 967, "Thread"),
        ("src/lingtai/services/mcp_inbox.py", 606, "Thread"),
        ("src/lingtai/tools/bash/__init__.py", 1306, "Thread"),
        ("src/lingtai/tools/bash/__init__.py", 1467, "Thread"),
        ("src/lingtai/tools/bash/__init__.py", 1714, "Thread"),
            ("src/lingtai/tools/daemon/__init__.py", 1786, "ThreadPoolExecutor"),
            ("src/lingtai/tools/daemon/__init__.py", 6575, "Thread"),
            ("src/lingtai/tools/daemon/__init__.py", 9179, "ThreadPoolExecutor"),
        ("src/lingtai/tools/daemon/claude_interactive.py", 611, "Thread"),
            ("src/lingtai/tools/daemon/execution_host.py", 687, "ThreadPoolExecutor"),
        ("src/lingtai/tools/daemon/posix_process.py", 112, "Thread"),
        ("src/lingtai/tools/daemon/runtime.py", 133, "Thread"),
        ("src/lingtai/tools/daemon/runtime.py", 220, "Thread"),
        ("src/lingtai/tools/daemon/supervisor_runtime.py", 284, "Thread"),
        ("src/lingtai/tools/daemon/windows_process.py", 353, "Thread"),
        ("src/lingtai/tools/email/manager.py", 321, "Thread"),
        ("src/lingtai/tools/soul/__init__.py", 244, "Thread"),
        ("src/lingtai/tools/soul/consultation.py", 594, "Thread"),
        ("src/lingtai/tools/task_card/__init__.py", 652, "Thread"),
    }
    assert inventory == (
        provider_context_propagation
        | post_admission_provider_dispatch
        | outside_root_provider_dispatch
    )


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


def _assert_single_audited_provider_operation(
    adjudications: list[str], provider_calls: list[str | None]
) -> None:
    """D6's two independent exact-count checks, joined by one audit id."""

    assert len(adjudications) == 1
    audit_id = adjudications[0]
    assert provider_calls == [audit_id]


def test_provider_trace_carries_only_audited_string_to_the_recording_transport():
    """D6 happy path: one Driver decision maps to one recorded provider I/O."""

    port = _AuditRecordingAdmissionPort()
    inner = _AuditRecordingInnerService()
    service = ProviderAdmittedLLMService(inner, port)
    token = bind_provider_admission(RootProviderAdmission("turn-d6", "test"))
    try:
        assert service.generate("legal-operation") == "generated"
    finally:
        clear_provider_admission(token)

    _assert_single_audited_provider_operation(port.adjudications, inner.provider_calls)


def test_d6_replay_mutation_must_make_the_adjudication_count_red():
    """A repeated legal operation is visible to D6; this is not CAS protection."""

    port = _AuditRecordingAdmissionPort()
    inner = _AuditRecordingInnerService()
    service = ProviderAdmittedLLMService(inner, port)
    token = bind_provider_admission(RootProviderAdmission("turn-d6-replay", "test"))
    try:
        service.generate("legal-operation")
        service.generate("replayed-legal-operation")
    finally:
        clear_provider_admission(token)

    with pytest.raises(AssertionError):
        _assert_single_audited_provider_operation(port.adjudications, inner.provider_calls)


def test_d6_fanout_mutation_must_make_the_provider_count_red():
    """Two provider I/O events after one decision cannot satisfy D6's call count."""

    port = _AuditRecordingAdmissionPort()
    inner = _AuditRecordingInnerService(fan_out=True)
    service = ProviderAdmittedLLMService(inner, port)
    token = bind_provider_admission(RootProviderAdmission("turn-d6-fanout", "test"))
    try:
        service.generate("legal-operation")
    finally:
        clear_provider_admission(token)

    assert port.adjudications == ["audit-1"]
    assert inner.provider_calls == ["audit-1", "audit-1"]
    with pytest.raises(AssertionError):
        _assert_single_audited_provider_operation(port.adjudications, inner.provider_calls)


def test_root_admission_reaches_the_real_provider_worker_thread():
    """The production timeout worker must retain an admitted root context."""

    inner = _InnerService()
    port = _RecordingAdmissionPort()
    session = ProviderAdmittedLLMService(inner, port).create_session("system")
    root = RootProviderAdmission("turn-worker", "puffo-v0.test")
    token = bind_provider_admission(root)
    try:
        with ThreadPoolExecutor(max_workers=1) as timeout_pool:
            result = send_with_timeout(
                session,
                "through-worker",
                timeout_pool,
                retry_timeout=1.0,
                agent_name="provider-admission-test",
                logger=None,
            )
    finally:
        clear_provider_admission(token)

    assert result == "through-worker"
    assert inner.session.calls == [("send", "through-worker")]
    assert port.calls == [(root, ProviderCallClass.ROOT)]


def test_root_admission_reaches_the_real_streaming_provider_worker_thread():
    """The production streaming timeout worker retains root admission too."""

    inner = _InnerService()
    port = _RecordingAdmissionPort()
    session = ProviderAdmittedLLMService(inner, port).create_session("system")
    root = RootProviderAdmission("turn-stream-worker", "puffo-v0.test")
    token = bind_provider_admission(root)
    try:
        with ThreadPoolExecutor(max_workers=1) as timeout_pool:
            result = send_with_timeout_stream(
                session,
                "stream-through-worker",
                timeout_pool,
                retry_timeout=1.0,
                agent_name="provider-admission-test",
                logger=None,
            )
    finally:
        clear_provider_admission(token)

    assert result == "stream-through-worker"
    assert inner.session.calls == [("stream", "stream-through-worker")]
    assert port.calls == [(root, ProviderCallClass.ROOT)]


def test_root_admission_reaches_rate_gated_provider_io_worker():
    """Nested timeout and rate-gate workers both retain root admission."""

    inner = _InnerService()
    gate = APICallGate(max_rpm=60, pool_size=1)
    inner.session = _GatedSession(inner.session, gate)
    port = _AuditRecordingAdmissionPort()
    session = ProviderAdmittedLLMService(inner, port).create_session("system")
    root = RootProviderAdmission("turn-rate-gated-worker", "puffo-v0.test")
    token = bind_provider_admission(root)
    try:
        with ThreadPoolExecutor(max_workers=1) as timeout_pool:
            result = send_with_timeout(
                session,
                "through-rate-gate",
                timeout_pool,
                retry_timeout=1.0,
                agent_name="provider-admission-test",
                logger=None,
            )
    finally:
        clear_provider_admission(token)
        gate.shutdown()

    assert result == "through-rate-gate"
    assert inner.session._inner.calls == [("send", "through-rate-gate")]
    assert inner.session._inner.audit_ids == ["audit-1"]
    assert port.adjudications == ["audit-1"]


def test_root_admission_reaches_soul_consultation_worker_thread():
    """Soul's production daemon-thread dispatch retains the admitted root."""

    class _SoulRuntime:
        config = SimpleNamespace(retry_timeout=1.0)

        def log(self, *_args, **_kwargs):
            return None

    inner = _InnerService()
    port = _RecordingAdmissionPort()
    session = ProviderAdmittedLLMService(inner, port).create_session("system")
    root = RootProviderAdmission("turn-soul-worker", "puffo-v0.test")
    token = bind_provider_admission(root)
    try:
        result = soul_send_with_timeout(_SoulRuntime(), session, "soul-worker")
    finally:
        clear_provider_admission(token)

    assert result == "soul-worker"
    assert inner.session.calls == [("send", "soul-worker")]
    assert port.calls == [(root, ProviderCallClass.ROOT)]


def test_provider_worker_does_not_retain_admission_between_reused_tasks():
    """A copied context must end with its task, even when the worker is reused."""

    inner = _InnerService()
    port = _RecordingAdmissionPort()
    session = ProviderAdmittedLLMService(inner, port).create_session("system")
    root = RootProviderAdmission("turn-reused-worker", "puffo-v0.test")
    with ThreadPoolExecutor(max_workers=1) as timeout_pool:
        token = bind_provider_admission(root)
        try:
            assert send_with_timeout(
                session,
                "admitted",
                timeout_pool,
                retry_timeout=1.0,
                agent_name="provider-admission-test",
                logger=None,
            ) == "admitted"
        finally:
            clear_provider_admission(token)

        with pytest.raises(ProviderAdmissionError, match="missing_provider_admission"):
            send_with_timeout(
                session,
                "must-not-inherit",
                timeout_pool,
                retry_timeout=1.0,
                agent_name="provider-admission-test",
                logger=None,
            )

    assert inner.session.calls == [("send", "admitted")]


def test_provider_worker_fails_closed_when_admission_authority_errors():
    """Worker context propagation cannot turn an authority failure into I/O."""

    inner = _InnerService()
    session = ProviderAdmittedLLMService(
        inner, _RaisingAdmissionPort()
    ).create_session("system")
    token = bind_provider_admission(RootProviderAdmission("turn-error", "test"))
    try:
        with ThreadPoolExecutor(max_workers=1) as timeout_pool:
            with pytest.raises(
                ProviderAdmissionError, match="provider_admission_port_error"
            ) as raised:
                send_with_timeout(
                    session,
                    "authority-error",
                    timeout_pool,
                    retry_timeout=1.0,
                    agent_name="provider-admission-test",
                    logger=None,
                )
    finally:
        clear_provider_admission(token)

    assert raised.value.state is ProviderAdmissionState.INDETERMINATE
    assert inner.session.calls == []


def test_provider_worker_rechecks_admission_for_each_call():
    """A worker may not reuse its first root decision for a later provider call."""

    class _FreshnessPort:
        def __init__(self):
            self.calls = 0

        def authorize_provider_call(self, _parent, _call_class):
            self.calls += 1
            if self.calls == 1:
                return ProviderCallDecision(ProviderAdmissionState.GRANTED, "allowed")
            return ProviderCallDecision(
                ProviderAdmissionState.INDETERMINATE,
                "admission_no_longer_current",
            )

    inner = _InnerService()
    port = _FreshnessPort()
    session = ProviderAdmittedLLMService(inner, port).create_session("system")
    token = bind_provider_admission(RootProviderAdmission("turn-fresh", "test"))
    try:
        with ThreadPoolExecutor(max_workers=1) as timeout_pool:
            assert send_with_timeout(
                session,
                "first",
                timeout_pool,
                retry_timeout=1.0,
                agent_name="provider-admission-test",
                logger=None,
            ) == "first"
            with pytest.raises(
                ProviderAdmissionError, match="admission_no_longer_current"
            ):
                send_with_timeout(
                    session,
                    "second",
                    timeout_pool,
                    retry_timeout=1.0,
                    agent_name="provider-admission-test",
                    logger=None,
                )
    finally:
        clear_provider_admission(token)

    assert port.calls == 2
    assert inner.session.calls == [("send", "first")]


def test_derived_call_class_is_not_inferred_from_user_controlled_text():
    inner = _InnerService()
    port = _RecordingAdmissionPort()
    service = ProviderAdmittedLLMService(inner, port)
    root = RootProviderAdmission("turn-a", "puffo-v0.test")
    derived = begin_derived_provider_admission(root, ProviderCallClass.DAEMON)

    token = bind_provider_admission(derived)
    try:
        service.create_session("system").send("work")
    finally:
        clear_provider_admission(token)

    assert port.calls == [(derived, ProviderCallClass.DAEMON)]


def test_v0_derived_admission_rejects_nested_derived_execution():
    """v0 is deliberately one hop: a child cannot mint another parent."""

    root = RootProviderAdmission("turn-a", RUNTIME_POLICY.policy_version)
    child = begin_derived_provider_admission(root, ProviderCallClass.DAEMON)

    with pytest.raises(TypeError, match="derived admission requires a root admission"):
        begin_derived_provider_admission(child, ProviderCallClass.AVATAR_CHILD)  # type: ignore[arg-type]


def test_derived_launch_reports_a_child_request_to_the_port_then_denies_it():
    """Core remains a backstop, but Driver sees and audits a nested request."""

    root = RootProviderAdmission("turn-a", RUNTIME_POLICY.policy_version)
    child = begin_derived_provider_admission(root, ProviderCallClass.DAEMON)
    port = _RecordingDerivedLaunchPort()
    token = bind_provider_admission(child)
    try:
        with pytest.raises(
            DerivedLaunchAdmissionError, match="nested_derived_launch_denied"
        ) as raised:
            require_derived_launch_admission(port, DerivedLaunchCapability.AVATAR)
    finally:
        clear_provider_admission(token)

    assert raised.value.decision.state is ProviderAdmissionState.DENIED
    assert port.calls == [(child, DerivedLaunchCapability.AVATAR)]


def test_nested_driver_grant_is_denied_and_its_opaque_lease_is_closed():
    """A buggy Driver grant cannot create a child or strand its endpoint."""

    root = RootProviderAdmission("turn-a", RUNTIME_POLICY.policy_version)
    child = begin_derived_provider_admission(root, ProviderCallClass.DAEMON)
    lease = _CloseTrackingLease()

    class IncorrectlyGrantingPort:
        def authorize_derived_launch(self, parent, capability):
            assert parent is child
            assert capability is DerivedLaunchCapability.AVATAR
            return DerivedLaunchDecision(
                ProviderAdmissionState.GRANTED,
                "incorrect_driver_grant",
                audit_id="audit-incorrect-grant",
                child_endpoint_lease=lease,
            )

    token = bind_provider_admission(child)
    try:
        with pytest.raises(
            DerivedLaunchAdmissionError, match="nested_derived_launch_denied"
        ) as raised:
            require_derived_launch_admission(
                IncorrectlyGrantingPort(), DerivedLaunchCapability.AVATAR
            )
    finally:
        clear_provider_admission(token)

    assert raised.value.decision.audit_id == "audit-incorrect-grant"
    assert lease.close_calls == 1


def test_derived_launch_port_is_fail_closed_when_unconnected_or_indeterminate():
    """A constrained profile cannot mistake an unavailable Driver for a grant."""

    root = RootProviderAdmission("turn-a", RUNTIME_POLICY.policy_version)
    token = bind_provider_admission(root)
    try:
        with pytest.raises(
            DerivedLaunchAdmissionError,
            match="derived_launch_admission_port_unconnected",
        ) as raised:
            require_derived_launch_admission(
                RUNTIME_POLICY, DerivedLaunchCapability.DAEMON
            )
    finally:
        clear_provider_admission(token)

    assert raised.value.decision.state is ProviderAdmissionState.INDETERMINATE


def test_required_derived_launch_port_cannot_fall_back_to_legacy_default():
    """A constrained composition must expose a missing Driver seam."""

    root = RootProviderAdmission("turn-a", RUNTIME_POLICY.policy_version)
    token = bind_provider_admission(root)
    try:
        with pytest.raises(
            DerivedLaunchAdmissionError,
            match="required_derived_launch_admission_port_missing",
        ) as raised:
            require_derived_launch_admission(
                None, DerivedLaunchCapability.DAEMON, required=True
            )
    finally:
        clear_provider_admission(token)

    assert raised.value.decision.state is ProviderAdmissionState.INDETERMINATE


def test_derived_launch_port_returns_auditable_grant_for_an_admitted_root():
    root = RootProviderAdmission("turn-a", RUNTIME_POLICY.policy_version)
    port = _RecordingDerivedLaunchPort()
    token = bind_provider_admission(root)
    try:
        decision = require_derived_launch_admission(
            port, DerivedLaunchCapability.DAEMON
        )
    finally:
        clear_provider_admission(token)

    assert decision.allowed is True
    assert decision.audit_id == "audit-derived-test"
    assert port.calls == [(root, DerivedLaunchCapability.DAEMON)]


def test_denied_provider_admission_never_reaches_the_inner_service():
    """Attack oracle: a valid-looking root context cannot bypass a denial."""

    inner = _InnerService()
    service = ProviderAdmittedLLMService(
        inner, _RecordingAdmissionPort(state=ProviderAdmissionState.DENIED)
    )
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
    daemon = begin_derived_provider_admission(root, ProviderCallClass.DAEMON)

    assert RUNTIME_POLICY.authorize_provider_call(
        root, ProviderCallClass.ROOT
    ).allowed is True
    denied = RUNTIME_POLICY.authorize_provider_call(daemon, ProviderCallClass.DAEMON)
    assert denied.allowed is False
    assert denied.state is ProviderAdmissionState.INDETERMINATE
    assert denied.reason_code == "derived_admission_port_unconnected"


def test_bound_unconnected_derived_admission_never_reaches_provider_io():
    """Attack oracle for the future derived adapter's unconnected state."""

    inner = _InnerService()
    service = ProviderAdmittedLLMService(inner, RUNTIME_POLICY)
    root = RootProviderAdmission("turn-a", RUNTIME_POLICY.policy_version)
    token = bind_provider_admission(
        begin_derived_provider_admission(root, ProviderCallClass.AVATAR_CHILD)
    )
    try:
        with pytest.raises(
            ProviderAdmissionError,
            match="derived_admission_port_unconnected",
        ) as raised:
            service.create_session("system").send("attempt derived provider call")
    finally:
        clear_provider_admission(token)

    assert inner.session.calls == []
    assert raised.value.state is ProviderAdmissionState.INDETERMINATE


def test_each_provider_call_requires_a_fresh_non_cached_decision():
    """A previous grant cannot be reused after the authority becomes unavailable."""

    class _FreshnessPort:
        def __init__(self):
            self.calls = 0

        def authorize_provider_call(self, _parent, _call_class):
            self.calls += 1
            if self.calls == 1:
                return ProviderCallDecision(
                    ProviderAdmissionState.GRANTED, "allowed"
                )
            return ProviderCallDecision(
                ProviderAdmissionState.INDETERMINATE,
                "revocation_state_unavailable",
            )

    inner = _InnerService()
    port = _FreshnessPort()
    service = ProviderAdmittedLLMService(inner, port)
    token = bind_provider_admission(RootProviderAdmission("turn-a", "test"))
    try:
        session = service.create_session("system")
        assert session.send("first") == "first"
        with pytest.raises(ProviderAdmissionError, match="revocation_state_unavailable"):
            session.send("second")
    finally:
        clear_provider_admission(token)

    assert port.calls == 2
    assert inner.session.calls == [("send", "first")]


def test_derived_admission_carries_no_path_or_string_execution_reference():
    root = RootProviderAdmission("turn-a", "test")
    derived = begin_derived_provider_admission(root, ProviderCallClass.DAEMON)

    assert not hasattr(derived, "execution_ref")
    assert "handle" not in repr(derived)
