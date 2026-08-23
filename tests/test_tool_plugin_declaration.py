"""Contract tests for the kernel-owned declared host-plugin primitive.

These pin the four mechanisms `src/lingtai/kernel/tool_plugin/CONTRACT.md`
promises, plus the one real vertical slice (`mcp`) that earns them:

- a declaration is **static** — constructible and validated at import, with no
  Agent in existence;
- the official name list is **kernel-owned and fail-fast** — an unreserved name
  and a second, different declaration of a reserved name are both refused
  *before* any bind, activate, or mount, so there is no last-registration-wins
  path and no partially mounted batch;
- the host facade is **least privilege** — a declaration receives exactly the
  ports it named in `requires`, never the Agent, and never the mount port;
- **binding is not activation or mounting** — `bind()` composes and nothing else.
"""
from __future__ import annotations

import ast
import dataclasses
import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from lingtai.adapters.tool_plugin_host import (
    agent_host_ports,
    register_agent_tool_plugins,
)
from lingtai.kernel.base_agent import BaseAgent
from lingtai.kernel import tool_plugin as tool_plugin_module
from lingtai.kernel.tool_plugin import (
    GRANTABLE_HOST_PORTS,
    OFFICIAL_TOOL_PLUGIN_NAMES,
    BoundToolPlugin,
    DuplicateToolPluginNameError,
    HostPortError,
    ToolPluginDeclaration,
    ToolPluginDeclarationError,
    ToolPluginHost,
    UnreservedToolPluginNameError,
    register_official_tool_plugins,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

_STRICT_EMPTY = {"type": "object", "properties": {}, "additionalProperties": False}


# ---------------------------------------------------------------------------
# Test doubles — a recording host, in the spirit of tests/test_curated_mcp_plugin_package.py
# ---------------------------------------------------------------------------

class _RecordingMount:
    """A `ToolMountPort` that records instead of touching a tool surface."""

    def __init__(self) -> None:
        self.mounted: list[str] = []

    def mount_tool(self, transaction) -> None:
        self.mounted.append(transaction.plugin.name)


class _FakeWorkdir:
    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path


class _FakePromptSection:
    def __init__(self) -> None:
        self.bodies: list[str] = []

    def write_protected_section(self, body: str) -> None:
        self.bodies.append(body)


def _ports(tmp_path: Path) -> dict:
    return {
        "workdir": _FakeWorkdir(tmp_path),
        "prompt_section": _FakePromptSection(),
    }


def _advertising(*actions: str) -> dict:
    """The one structural fact `bind()` reads back out of a composed schema.

    Real families compose this through `ToolFamily.build_schema()`; a double
    only has to advertise the same action enum the declaration promises, since
    that is what the kernel compares.
    """
    return {
        "type": "object",
        "properties": {"action": {"type": "string", "enum": list(actions)}},
    }


def _declaration(name: str = "mcp", **overrides) -> ToolPluginDeclaration:
    """A minimal valid declaration; `overrides` mutate one field at a time."""
    binds: list[ToolPluginHost] = []
    actions = overrides.get("actions", ("info",))
    schema = _advertising(*actions, "manual")
    kwargs = dict(
        name=name,
        actions=("info",),
        input_schemas={"info": _STRICT_EMPTY},
        manual_input_schema=_STRICT_EMPTY,
        manual=name,
        description=f"{name} test declaration",
        binder=lambda host: (
            binds.append(host)
            or BoundToolPlugin(name=name, schema=schema, handler=lambda args: {})
        ),
        requires=(),
    )
    kwargs.update(overrides)
    declaration = ToolPluginDeclaration(**kwargs)
    declaration.__dict__.setdefault("_test_binds", binds)
    return declaration


# ---------------------------------------------------------------------------
# The declaration is static
# ---------------------------------------------------------------------------

def test_mcp_declaration_is_static_and_needs_no_agent():
    """`mcp`'s declaration exists at import, with its exact public surface."""
    from lingtai.tools.mcp import DECLARATION, get_schema

    assert DECLARATION.name == "mcp"
    # Operational actions only; the reserved `manual` is appended, never declared.
    assert DECLARATION.actions == ("info",)
    assert DECLARATION.public_actions == ("info", "manual")
    # The declared identity and the real composed model-facing schema agree.
    assert get_schema()["properties"]["action"]["enum"] == list(
        DECLARATION.public_actions
    )
    for schema in DECLARATION.public_input_schemas().values():
        assert schema["type"] == "object"
        assert schema["properties"] == {}
        assert schema["additionalProperties"] is False


def test_mcp_is_reserved_and_declares_only_the_ports_it_consumes():
    from lingtai.tools.mcp import DECLARATION

    assert "mcp" in OFFICIAL_TOOL_PLUGIN_NAMES
    assert DECLARATION.requires == ("workdir", "prompt_section")
    assert set(DECLARATION.requires) <= set(GRANTABLE_HOST_PORTS)


# ---------------------------------------------------------------------------
# Construction-time validation
# ---------------------------------------------------------------------------

def test_declaration_rejects_declaring_the_reserved_manual_action():
    with pytest.raises(ToolPluginDeclarationError, match="reserved 'manual'"):
        _declaration(
            actions=("info", "manual"),
            input_schemas={"info": _STRICT_EMPTY, "manual": _STRICT_EMPTY},
        )


def test_declaration_rejects_duplicate_and_empty_actions():
    with pytest.raises(ToolPluginDeclarationError, match="at least one"):
        _declaration(actions=(), input_schemas={})
    with pytest.raises(ToolPluginDeclarationError, match="duplicate action"):
        _declaration(actions=("info", "info"), input_schemas={"info": _STRICT_EMPTY})


def test_declaration_requires_one_input_schema_per_action():
    with pytest.raises(ToolPluginDeclarationError, match="exactly one"):
        _declaration(actions=("info", "probe"), input_schemas={"info": _STRICT_EMPTY})


def test_declaration_rejects_a_non_grantable_port():
    """`tool_mount` is host-only: a plugin that could mount could self-register."""
    assert "tool_mount" not in GRANTABLE_HOST_PORTS
    with pytest.raises(ToolPluginDeclarationError, match="non-grantable"):
        _declaration(requires=("tool_mount",))


def test_the_declaration_carries_no_field_nothing_consumes():
    """Ports and fields are earned by a real slice, never enumerated ahead of one.

    `skills` was carried here speculatively, read by nothing in `src/` or
    `tests/` and validated by nothing in `__post_init__`. A declaration field
    arrives with the family that consumes it (root `CONTRACT.md` rules 10-11).
    """
    fields = {field.name for field in dataclasses.fields(ToolPluginDeclaration)}
    assert "skills" not in fields
    assert fields == {
        "name",
        "actions",
        "input_schemas",
        "manual_input_schema",
        "manual",
        "description",
        "binder",
        "requires",
        "glossary_package",
    }


# ---------------------------------------------------------------------------
# Declared-versus-shipped agreement
# ---------------------------------------------------------------------------

def test_bind_refuses_a_plugin_advertising_actions_it_did_not_declare(tmp_path):
    """The declared identity and the shipped surface must agree, at every boot.

    `src/lingtai/tools/CONTRACT.md` requires declared identity, action list,
    and manual to agree and to fail loudly when they do not. The registrar
    holds both objects, so it checks rather than trusting a test to notice.
    """
    declaration = _declaration(
        binder=lambda host: BoundToolPlugin(
            name="mcp",
            schema=_advertising("info", "probe", "manual"),
            handler=lambda args: {},
        ),
    )
    with pytest.raises(ToolPluginDeclarationError, match="advertising"):
        declaration.bind(ToolPluginHost.grant(declaration, _ports(tmp_path)))


def test_bind_refuses_a_plugin_that_advertises_no_actions_at_all(tmp_path):
    """A missing enum is a defect, not permission to skip the agreement check."""
    declaration = _declaration(
        binder=lambda host: BoundToolPlugin(
            name="mcp", schema={}, handler=lambda args: {}
        ),
    )
    with pytest.raises(ToolPluginDeclarationError, match="advertises no action enum"):
        declaration.bind(ToolPluginHost.grant(declaration, _ports(tmp_path)))


def test_a_disagreeing_family_is_refused_with_nothing_mounted_or_claimed(tmp_path):
    """The refusal happens inside the registrar, before mount and before claim."""
    declaration = _declaration(
        binder=lambda host: BoundToolPlugin(
            name="mcp",
            schema=_advertising("info"),  # the reserved `manual` never shipped
            handler=lambda args: {},
        ),
    )
    mount = _RecordingMount()
    claimed: dict = {}

    with pytest.raises(ToolPluginDeclarationError, match="advertising"):
        register_official_tool_plugins(
            [declaration],
            ports_for=lambda _decl: _ports(tmp_path),
            mount=mount,
            claimed=claimed,
        )
    assert mount.mounted == []
    assert claimed == {}


def test_the_mcp_manual_route_is_derived_from_the_declaration(tmp_path, monkeypatch):
    """One literal: change `DECLARATION.manual` and the child follows it.

    The family used to name its installed manual a second time in
    `_build_family`, so a declaration reading `mcp-manual` and a child reading
    `mcp` would both validate and both boot.
    """
    from lingtai.tools import mcp as mcp_tool

    monkeypatch.setattr(
        mcp_tool,
        "DECLARATION",
        dataclasses.replace(mcp_tool.DECLARATION, manual="mcp-manual"),
    )
    host = ToolPluginHost.grant(mcp_tool.DECLARATION, _ports(tmp_path))
    result = mcp_tool._build_family(host).handle({"action": "manual", "input": {}})

    assert result["structuredContent"]["manual_path"].endswith(
        "capabilities/mcp-manual/SKILL.md"
    )


def test_the_mcp_input_schemas_are_derived_from_the_declaration(monkeypatch):
    """The composed per-action `input` shape comes from the declaration itself."""
    from lingtai.tools import mcp as mcp_tool

    declared = {
        "type": "object",
        "properties": {"probe": {"type": "string"}},
        "additionalProperties": False,
    }
    monkeypatch.setattr(
        mcp_tool,
        "DECLARATION",
        dataclasses.replace(mcp_tool.DECLARATION, input_schemas={"info": declared}),
    )
    schema = mcp_tool._build_family(None).build_schema()
    branch = next(
        b for b in schema["properties"]["input"]["oneOf"] if b["title"] == "info input"
    )

    assert branch["properties"] == {"probe": {"type": "string"}}


def test_the_shipped_mcp_family_agrees_with_its_own_declaration():
    """The real slice, not a double: name, actions, and per-action inputs agree."""
    from lingtai.tools import mcp as mcp_tool

    declaration = mcp_tool.DECLARATION
    family = mcp_tool._FAMILY

    assert family.name == declaration.name
    assert family.child_names == declaration.public_actions
    declared_inputs = declaration.public_input_schemas()
    for action in family.child_names:
        assert family._children[action].input_schema == declared_inputs[action]


# ---------------------------------------------------------------------------
# Least-privilege host facade
# ---------------------------------------------------------------------------

def test_bind_receives_only_the_required_ports(tmp_path):
    declaration = _declaration(requires=("workdir",))
    host = ToolPluginHost.grant(declaration, _ports(tmp_path))

    assert host.granted == ("workdir",)
    assert host.workdir.path == tmp_path
    with pytest.raises(AttributeError, match="did not require host port"):
        host.prompt_section


def test_grant_fails_loudly_when_a_required_port_is_missing(tmp_path):
    declaration = _declaration(requires=("workdir", "prompt_section"))
    with pytest.raises(HostPortError, match="prompt_section"):
        ToolPluginHost.grant(declaration, {"workdir": _FakeWorkdir(tmp_path)})


def test_host_facade_and_bound_plugin_never_expose_the_agent(tmp_path, mcp_agent):
    """No public attribute of the facade or the bound plugin is the Agent."""
    from lingtai.tools.mcp import DECLARATION

    agent = mcp_agent
    host = ToolPluginHost.grant(DECLARATION, agent_host_ports(agent, "mcp"))
    bound = DECLARATION.bind(host)

    surfaces = [host, bound, *(getattr(host, name) for name in host.granted)]
    for surface in surfaces:
        for attribute in dir(surface):
            if attribute.startswith("_"):
                continue
            assert getattr(surface, attribute, None) is not agent


def test_a_declaration_cannot_bind_to_another_plugins_host(tmp_path):
    declaration = _declaration(requires=("workdir",))
    foreign = ToolPluginHost("other", {"workdir": _FakeWorkdir(tmp_path)})
    with pytest.raises(HostPortError, match="granted to 'other'"):
        declaration.bind(foreign)


def test_bind_alone_activates_nothing_and_mounts_nothing(tmp_path):
    """Binding composes. Activation and mounting are the registrar's steps."""
    from lingtai.tools.mcp import DECLARATION

    ports = _ports(tmp_path)
    bound = DECLARATION.bind(ToolPluginHost.grant(DECLARATION, ports))

    assert ports["prompt_section"].bodies == []
    assert callable(bound.activate)  # declared, but not yet run
    assert bound.name == "mcp"


# ---------------------------------------------------------------------------
# Fail-fast official names
# ---------------------------------------------------------------------------

def test_unreserved_name_is_refused_before_any_bind_or_mount(tmp_path):
    declaration = _declaration(name="not_official")
    mount = _RecordingMount()

    with pytest.raises(UnreservedToolPluginNameError, match="not_official"):
        register_official_tool_plugins(
            [declaration],
            ports_for=lambda _decl: _ports(tmp_path),
            mount=mount,
            claimed={},
        )
    assert mount.mounted == []
    assert declaration.__dict__["_test_binds"] == []


def test_duplicate_name_in_one_batch_is_refused_before_any_mount(tmp_path):
    """The whole batch is refused: nothing binds, nothing mounts, nothing claims."""
    first = _declaration()
    second = _declaration()
    mount = _RecordingMount()
    claimed: dict = {}

    with pytest.raises(DuplicateToolPluginNameError, match="declared twice"):
        register_official_tool_plugins(
            [first, second],
            ports_for=lambda _decl: _ports(tmp_path),
            mount=mount,
            claimed=claimed,
        )
    assert mount.mounted == []
    assert claimed == {}
    assert first.__dict__["_test_binds"] == []
    assert second.__dict__["_test_binds"] == []


def test_a_second_different_declaration_cannot_take_a_claimed_name(tmp_path):
    """No last-registration-wins: the live claim is not overwritable."""
    first = _declaration()
    second = _declaration()
    mount = _RecordingMount()
    claimed: dict = {}

    register_official_tool_plugins(
        [first],
        ports_for=lambda _decl: _ports(tmp_path),
        mount=mount,
        claimed=claimed,
    )
    assert mount.mounted == ["mcp"]

    with pytest.raises(DuplicateToolPluginNameError, match="not overwritable"):
        register_official_tool_plugins(
            [second],
            ports_for=lambda _decl: _ports(tmp_path),
            mount=mount,
            claimed=claimed,
        )
    # The first declaration still owns the name, and nothing else was mounted.
    assert claimed["mcp"] is first
    assert mount.mounted == ["mcp"]
    assert second.__dict__["_test_binds"] == []


def test_repeat_registration_of_the_same_declaration_is_idempotent(tmp_path):
    """`_setup_from_init` re-runs the whole boot on every refresh."""
    declaration = _declaration()
    mount = _RecordingMount()
    claimed: dict = {}

    for _ in range(3):
        register_official_tool_plugins(
            [declaration],
            ports_for=lambda _decl: _ports(tmp_path),
            mount=mount,
            claimed=claimed,
        )
    assert mount.mounted == ["mcp", "mcp", "mcp"]
    assert claimed == {"mcp": declaration}


def test_activation_runs_before_mount_and_only_after_the_name_checks(tmp_path):
    order: list[str] = []
    mount = _RecordingMount()

    def _mount_tool(transaction) -> None:
        order.append("mount")
        mount.mount_tool(transaction)

    declaration = _declaration(
        binder=lambda host: BoundToolPlugin(
            name="mcp",
            schema=_advertising("info", "manual"),
            handler=lambda args: {},
            activate=lambda: order.append("activate"),
        ),
    )
    register_official_tool_plugins(
        [declaration],
        ports_for=lambda _decl: _ports(tmp_path),
        mount=type("_M", (), {"mount_tool": staticmethod(_mount_tool)})(),
        claimed={},
    )
    assert order == ["activate", "mount"]


# ---------------------------------------------------------------------------
# The live Agent slice
# ---------------------------------------------------------------------------

@pytest.fixture
def mcp_agent(tmp_path):
    from lingtai.agent import Agent
    from tests._service_helpers import make_gemini_mock_service

    agent = Agent(
        service=make_gemini_mock_service(),
        agent_name="tool-plugin-declaration",
        working_dir=tmp_path / "agent",
        capabilities={"mcp": {}},
    )
    try:
        yield agent
    finally:
        agent.stop(timeout=1.0)


def test_boot_claims_the_official_name_and_mounts_exactly_one_mcp_tool(mcp_agent):
    from lingtai.tools.mcp import DECLARATION

    agent = mcp_agent
    assert agent._official_tool_plugins["mcp"] is DECLARATION
    assert [s.name for s in agent._tool_schemas].count("mcp") == 1
    assert "mcp" in agent._tool_handlers


def test_registration_after_the_tool_surface_is_sealed_raises(mcp_agent):
    """`add_tool` is sealed by `start()`; a post-seal registrar mount fails loudly."""
    from lingtai.tools.mcp import DECLARATION

    agent = mcp_agent
    agent._sealed = True
    with pytest.raises(RuntimeError, match="after start"):
        register_agent_tool_plugins(agent, [DECLARATION])


def test_public_mount_bypass_cannot_publish_a_foreign_bound_plugin(mcp_agent):
    """No exported adapter/factory can turn an arbitrary bound plugin official."""
    from lingtai.adapters import tool_plugin_host

    agent = mcp_agent
    before_handler = agent._tool_handlers["mcp"]
    before_schemas = list(agent._tool_schemas)
    before_claim = agent.official_tool_plugins["mcp"]
    foreign = BoundToolPlugin(
        name="mcp",
        schema=_advertising("info", "manual"),
        handler=lambda args: {"foreign": True},
    )

    assert not hasattr(tool_plugin_host, "AgentToolMountAdapter")
    assert not hasattr(tool_plugin_host, "agent_tool_mount")
    with pytest.raises(PermissionError, match="registrar transaction"):
        agent._mount_official_tool(foreign)

    assert agent._tool_handlers["mcp"] is before_handler
    assert agent._tool_schemas == before_schemas
    assert agent.official_tool_plugins["mcp"] is before_claim


def test_a_foreign_declaration_cannot_take_the_live_mcp_name(mcp_agent):
    agent = mcp_agent
    before = list(agent._tool_schemas)

    with pytest.raises(DuplicateToolPluginNameError, match="not overwritable"):
        register_agent_tool_plugins(agent, [_declaration()])

    assert agent._tool_schemas == before


def test_a_constructed_transaction_cannot_replace_the_canonical_mcp_binding(mcp_agent):
    """The review's forged ``(live declaration, foreign plugin)`` bypass is closed."""
    agent = mcp_agent
    from lingtai.kernel.tool_plugin import _OfficialMountTransaction

    before_handler = agent._tool_handlers["mcp"]
    before_schemas = list(agent._tool_schemas)
    before_claim = agent.official_tool_plugins["mcp"]
    foreign = BoundToolPlugin(
        name="mcp",
        schema=_advertising("info", "manual"),
        handler=lambda args: {"foreign": True},
    )

    with pytest.raises(PermissionError, match="issued only by the kernel registrar"):
        agent._mount_official_tool(
            _OfficialMountTransaction(agent.official_tool_plugins["mcp"], foreign)
        )

    assert agent._tool_handlers["mcp"] is before_handler
    assert agent._tool_schemas == before_schemas
    assert agent.official_tool_plugins["mcp"] is before_claim


def test_clearing_the_backing_claim_cannot_admit_a_foreign_declaration(mcp_agent):
    """Live declaration anchors survive backing-map tampering."""
    agent = mcp_agent
    before_handler = agent._tool_handlers["mcp"]
    before_schemas = list(agent._tool_schemas)
    agent._official_tool_plugins.clear()

    with pytest.raises(PermissionError, match="registrar transaction"):
        agent._claim_official_tool(_declaration())
    with pytest.raises(DuplicateToolPluginNameError, match="anchored"):
        register_agent_tool_plugins(agent, [_declaration()])

    assert agent._tool_handlers["mcp"] is before_handler
    assert agent._tool_schemas == before_schemas
    assert agent._official_tool_declarations["mcp"].name == "mcp"


def test_the_prompt_section_port_writes_only_this_plugins_section(mcp_agent):
    """`info` re-renders the protected `mcp` section through the bound port."""
    agent = mcp_agent
    written: list[tuple] = []
    agent.update_system_prompt = lambda *a, **kw: written.append((a, kw))

    ports = agent_host_ports(agent, "mcp")
    ports["prompt_section"].write_protected_section("<registered_mcp/>")

    assert written == [(("mcp", "<registered_mcp/>"), {"protected": True})]


# ---------------------------------------------------------------------------
# The boot path: a refused official plugin must be observable
# ---------------------------------------------------------------------------

def _init_document(capabilities: dict, disable: list | None = None) -> dict:
    """A minimal valid `init.json`, the shape `_setup_from_init` reads."""
    manifest = {
        "agent_name": "tool-plugin-declaration",
        "language": "en",
        "llm": {
            "provider": "openai",
            "model": "gpt-4o",
            "api_key": "test-key",
            "base_url": None,
        },
        "capabilities": capabilities,
        "soul": {"delay": 60},
        "stamina": 3600,
        "context_limit": None,
        "molt_pressure": 0.8,
        "molt_prompt": "",
        "max_turns": 100,
        "admin": {"karma": True},
        "streaming": False,
    }
    if disable is not None:
        manifest["disable"] = disable
    return {
        "manifest": manifest,
        "principle": "",
        "covenant": "",
        "pad": "",
        "lingtai": "",
        "soul": "",
    }


def _agent_on_init(working_dir: Path, document: dict):
    """An Agent whose capabilities come from `init.json`, as the CLI boot does."""
    from lingtai.agent import Agent
    from lingtai.kernel.config import AgentConfig

    working_dir.mkdir(parents=True, exist_ok=True)
    (working_dir / "init.json").write_text(json.dumps(document), encoding="utf-8")

    service = MagicMock()
    service.provider = "openai"
    service.model = "gpt-4o"
    service._base_url = None
    return Agent(
        service, agent_name="tool-plugin-declaration", working_dir=working_dir,
        config=AgentConfig(),
    )


def test_an_official_name_conflict_is_not_swallowed_as_capability_skipped(
    mcp_agent, monkeypatch
):
    """The registrar's refusal must survive the Composition Root's skip-guard.

    `Agent.__init__` and `Agent._setup_from_init` both wrap `_setup_capability`
    in `except (ValueError, ImportError, TypeError)` and downgrade what they
    catch to one `capability_skipped` log line. While every declared-plugin
    error was a `ValueError` subclass, a violated official-name reservation
    produced an agent that booted *successfully* with no `mcp` tool at all —
    the failure mode this component exists to prevent, reported as a skip.
    """
    from lingtai.tools import mcp as mcp_tool

    agent = mcp_agent
    live = agent.official_tool_plugins["mcp"]
    monkeypatch.setattr(mcp_tool, "DECLARATION", _declaration())

    with pytest.raises(DuplicateToolPluginNameError) as excinfo:
        agent._setup_capability("mcp")

    # The exact predicate of the boot guard, asserted directly.
    assert not isinstance(excinfo.value, (ValueError, ImportError, TypeError))
    # The live tool kept its claim and its mount; nothing was replaced.
    assert agent.official_tool_plugins["mcp"] is live
    assert "mcp" in agent._tool_handlers


def test_an_unreserved_official_name_fails_the_boot_rather_than_skipping_mcp(
    tmp_path, monkeypatch
):
    """End to end through the real capability loop, with no test double."""
    from lingtai.agent import Agent
    from lingtai.tools import mcp as mcp_tool
    from tests._service_helpers import make_gemini_mock_service

    monkeypatch.setattr(
        mcp_tool,
        "DECLARATION",
        dataclasses.replace(mcp_tool.DECLARATION, name="not_official"),
    )
    with pytest.raises(UnreservedToolPluginNameError, match="not_official"):
        Agent(
            service=make_gemini_mock_service(),
            agent_name="tool-plugin-declaration",
            working_dir=tmp_path / "agent",
            capabilities={"mcp": {}},
        )


def test_a_missing_host_port_fails_the_boot_rather_than_skipping_mcp(
    tmp_path, monkeypatch
):
    """The same guard would have absorbed a wiring defect in the port table."""
    from lingtai.agent import Agent
    from lingtai.adapters import tool_plugin_host
    from tests._service_helpers import make_gemini_mock_service

    monkeypatch.setattr(
        tool_plugin_host, "agent_host_ports", lambda agent, plugin_name: {}
    )
    with pytest.raises(HostPortError, match="workdir"):
        Agent(
            service=make_gemini_mock_service(),
            agent_name="tool-plugin-declaration",
            working_dir=tmp_path / "agent",
            capabilities={"mcp": {}},
        )


# ---------------------------------------------------------------------------
# The claim map is the *live* official namespace
# ---------------------------------------------------------------------------

def test_the_claim_map_is_reachable_through_the_public_agent_surface(mcp_agent):
    """The adapter observes claims through the read-only Agent property."""
    from lingtai.tools.mcp import DECLARATION

    agent = mcp_agent
    assert agent.official_tool_plugins["mcp"] is DECLARATION
    assert "official_tool_plugins" in dir(type(agent))


def test_public_claim_view_cannot_clear_the_live_claim_or_admit_a_foreign_declaration(
    mcp_agent,
):
    """Claim observation is public, but clearing it cannot unlock registration."""
    agent = mcp_agent
    before_handler = agent._tool_handlers["mcp"]
    before_schemas = list(agent._tool_schemas)
    before_claim = agent.official_tool_plugins["mcp"]
    claims = agent.official_tool_plugins

    with pytest.raises((AttributeError, TypeError)):
        claims.clear()
    with pytest.raises(TypeError):
        claims["mcp"] = _declaration()

    with pytest.raises(DuplicateToolPluginNameError, match="not overwritable"):
        register_agent_tool_plugins(agent, [_declaration()])

    assert agent._tool_handlers["mcp"] is before_handler
    assert agent._tool_schemas == before_schemas
    assert agent.official_tool_plugins["mcp"] is before_claim


def test_a_refresh_that_disables_the_capability_drops_its_official_claim(tmp_path):
    """A claim must not outlive the tool it claims.

    `_setup_from_init` clears `_tool_handlers` / `_tool_schemas` and re-runs the
    whole boot. The claim map is cleared with them, so an agent refreshed with
    `mcp` in `manifest.disable` does not keep a claim on a name nothing mounts.
    """
    working_dir = tmp_path / "agent"
    agent = _agent_on_init(working_dir, _init_document({"mcp": {}}))
    agent._setup_from_init()
    assert "mcp" in agent.official_tool_plugins
    assert "mcp" in agent._tool_handlers

    (working_dir / "init.json").write_text(
        json.dumps(_init_document({}, disable=["mcp"])), encoding="utf-8"
    )
    agent._setup_from_init()

    assert "mcp" not in agent._tool_handlers
    assert "mcp" not in agent.official_tool_plugins


def test_a_refresh_that_keeps_the_capability_re_claims_the_official_name(tmp_path):
    """Clearing the map must not weaken the reservation across a refresh."""
    from lingtai.tools.mcp import DECLARATION

    working_dir = tmp_path / "agent"
    agent = _agent_on_init(working_dir, _init_document({"mcp": {}}))
    agent._setup_from_init()
    agent._setup_from_init()

    assert agent.official_tool_plugins["mcp"] is DECLARATION
    assert [s.name for s in agent._tool_schemas].count("mcp") == 1
    with pytest.raises(DuplicateToolPluginNameError, match="not overwritable"):
        register_agent_tool_plugins(agent, [_declaration()])


# ---------------------------------------------------------------------------
# Atomicity, stated exactly
# ---------------------------------------------------------------------------

def test_only_name_conflicts_are_all_or_nothing_across_a_batch(tmp_path, monkeypatch):
    """A binder or port failure mid-batch is *not* rolled back, and says so.

    The registrar's second loop mounts and claims each member as it goes, so a
    failure on member N leaves members 1..N-1 mounted and claimed. The
    all-or-nothing promise is scoped to the name checks in the first loop; this
    pins the truthful behavior of everything after them.
    """
    monkeypatch.setattr(
        tool_plugin_module, "OFFICIAL_TOOL_PLUGIN_NAMES", ("mcp", "second")
    )
    first = _declaration()
    second = _declaration(name="second", requires=("workdir",))
    mount = _RecordingMount()
    claimed: dict = {}

    with pytest.raises(HostPortError, match="workdir"):
        register_official_tool_plugins(
            [first, second],
            # The second member's port table is empty: a host wiring defect
            # that the name loop cannot see.
            ports_for=lambda decl: _ports(tmp_path) if decl.name == "mcp" else {},
            mount=mount,
            claimed=claimed,
        )

    assert mount.mounted == ["mcp"]
    assert list(claimed) == ["mcp"]
    assert second.__dict__["_test_binds"] == []


# ---------------------------------------------------------------------------
# The shared manual loader
# ---------------------------------------------------------------------------

def test_the_manual_loader_names_a_source_it_cannot_resolve():
    """Neither an Agent's `_working_dir` nor a port's `path`: say which.

    An `Agent` whose `_working_dir` is unset used to fall through to the port
    branch and raise `AttributeError: 'Agent' object has no attribute 'path'`,
    which names the wrong problem.
    """
    from lingtai.tools._manual import load_installed_manual

    class _AgentWithUnsetWorkingDir:
        _working_dir = None

    with pytest.raises(AttributeError, match="neither a live Agent"):
        load_installed_manual(_AgentWithUnsetWorkingDir(), "mcp")


# ---------------------------------------------------------------------------
# Kernel isolation
# ---------------------------------------------------------------------------

def _kernel_python_files() -> list[str]:
    proc = subprocess.run(
        ["git", "ls-files", "--", "src/lingtai/kernel/*.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in proc.stdout.splitlines() if line]


def _imported_modules(relative: str) -> list[str]:
    """Absolute module names one kernel file imports, relative imports resolved."""
    path = REPO_ROOT / relative
    parts = Path(relative).with_suffix("").parts[1:]  # drop the leading "src"
    # The importing module's own package: `a/b/__init__.py` and `a/b/c.py`
    # both sit in package `a.b`.
    package = list(parts[:-1])

    modules: list[str] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if not node.level:
                modules.append(node.module or "")
                continue
            base = package[: len(package) - (node.level - 1)] if node.level > 1 else package
            modules.append(".".join([*base, node.module] if node.module else base))
    return modules


def test_the_kernel_still_imports_nothing_from_lingtai_tools():
    """The declared primitive must not invert the kernel's strongest edge.

    `lingtai.kernel` owns the plugin *shape*; `lingtai.tools` owns the
    declarations; `src/lingtai/agent.py` and each capability `setup()` wire the
    two. A concrete family import under `src/lingtai/kernel/` would collapse
    that direction, so this is checked over the whole kernel source tree — with
    relative imports resolved, since `lingtai.kernel.base_agent.tools` is the
    kernel's own module of that name and must not be confused for the tools
    package.
    """
    kernel_files = _kernel_python_files()
    assert len(kernel_files) > 50, kernel_files  # guard against an empty sweep

    offenders = [
        f"{relative}: {module}"
        for relative in kernel_files
        for module in _imported_modules(relative)
        if module == "lingtai.tools" or module.startswith("lingtai.tools.")
    ]
    assert offenders == [], offenders
