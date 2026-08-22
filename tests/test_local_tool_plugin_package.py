"""Local-tool plugin packaging invariants, proven on the Vision reference slice.

A built-in model-facing tool is a plugin-style package: the same folder ships
the implementation, the ``manual/`` skill bundle the kernel installs into the
agent's library, and the capability declaration the built-in registry
publishes. ``lingtai.tools._plugin.LocalToolPlugin`` binds those three and owns
the two promises a package must not be able to break — the reserved ``manual``
action, appended from the package's own skill rather than declared or handed in
by the package, and the mount, which refuses to publish a family that is not
this plugin's or that has lost that action.

These tests pin the packaging promises, the packaged-skill → installed-skill →
``manual`` result chain, and the *unchanged* public Vision surface around them.
They construct no provider, read no credential, and make no network call: the
manual is provider-independent, and the family's dispatch boundary rejects
every invalid envelope before any provider I/O.
"""
from __future__ import annotations

import importlib
import inspect
import shutil
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from lingtai.services.vision import VisionService
from lingtai.tools import _plugin
from lingtai.tools import registry
from lingtai.tools import vision as vision_tool
from lingtai.tools._plugin import LocalToolPlugin, LocalToolPluginError
from lingtai.tools.tool_family import ChildTool, ToolFamily
from lingtai.tools.tool_family.manual import MANUAL_INPUT_SCHEMA
from lingtai.tools.vision import VisionManager, get_schema, setup
from lingtai.tools.vision.plugin import (
    VISION_ACTIONS,
    VISION_DECLARED_ACTIONS,
    VISION_PLUGIN,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]

_IDENTITY = {
    "name": "vision",
    "package": "lingtai.tools.vision",
    "summary": "s",
    "homepage": "h",
    "skill_name": "vision-manual",
}


class _StubAgent:
    """Minimal agent surface: a working dir plus one recorded ``add_tool``."""

    def __init__(self, working_dir: Path) -> None:
        self._working_dir = working_dir
        self.tools: dict[str, dict] = {}

    def add_tool(self, name: str, **kwargs) -> None:
        self.tools[name] = kwargs


def _install_packaged_manual(working_dir: Path) -> Path:
    """Do what ``Agent._install_intrinsic_manuals`` does, for this plugin only."""
    destination = VISION_PLUGIN.installed_manual_path(working_dir).parent
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(VISION_PLUGIN.manual_dir, destination)
    return destination


def _never_called_service() -> MagicMock:
    """A vision service that fails the test if any provider I/O is attempted."""
    svc = MagicMock(spec=VisionService)
    svc.analyze_image.side_effect = AssertionError(
        "provider I/O must not run for this call"
    )
    return svc


# ---------------------------------------------------------------------------
# The package ships its own capability declaration
# ---------------------------------------------------------------------------

def test_vision_package_declaration_matches_the_shipped_builtin_registry():
    """The package owns its mount facts; registry.py publishes exactly them."""
    declaration = VISION_PLUGIN.capability_declaration()

    assert registry.BUILTIN_TOOLS[declaration["name"]] == declaration["module"]
    assert (declaration["name"] in registry.CORE_DEFAULTS) is declaration["default_on"]
    assert registry.CORE_DEFAULTS[declaration["name"]] == declaration["default_kwargs"]
    assert declaration["source"] == _plugin.BUILTIN_SOURCE


def test_declaration_module_is_the_declaring_package_and_is_bootable():
    declaration = VISION_PLUGIN.capability_declaration()
    assert declaration["module"] == vision_tool.__name__

    module = importlib.import_module(declaration["module"])
    assert module is vision_tool
    # The host's own boot contract — unchanged — still accepts this module.
    assert callable(getattr(module, "setup", None))


def test_registry_composition_is_unchanged_and_still_the_runtime_source():
    """The descriptor documents the entry; it does not replace registry I/O."""
    declaration = VISION_PLUGIN.capability_declaration()
    composed = registry.apply_core_defaults(None)
    assert composed[declaration["name"]] == declaration["default_kwargs"]
    assert registry.canonical_capability_name(declaration["name"]) == declaration["name"]


def test_declared_manual_destination_is_the_directory_the_installer_produces():
    """``manual/`` installs under the public name, which is what ``manual`` reads."""
    declaration = VISION_PLUGIN.capability_declaration()
    assert declaration["manual_destination"] == declaration["name"]

    packaged = VISION_PLUGIN.manual_dir
    assert packaged.name == _plugin.MANUAL_DIRNAME
    assert packaged.parent.name == declaration["module"].rpartition(".")[2]
    assert (packaged / _plugin.SKILL_FILENAME).is_file()

    installed = VISION_PLUGIN.installed_manual_path(Path("/tmp/agent"))
    assert installed == Path(
        "/tmp/agent", *_plugin.LIBRARY_CAPABILITIES_SEGMENTS,
        declaration["manual_destination"], _plugin.SKILL_FILENAME,
    )


# ---------------------------------------------------------------------------
# `manual` is mandatory, reserved, and sourced from the package's own skill
# ---------------------------------------------------------------------------

def test_package_does_not_declare_manual_and_the_plugin_appends_it_last():
    assert _plugin.MANUAL_ACTION not in VISION_DECLARED_ACTIONS
    assert VISION_ACTIONS == (*VISION_DECLARED_ACTIONS, "manual")
    assert VISION_ACTIONS[-1] == "manual"


@pytest.mark.parametrize(
    "compose",
    [
        pytest.param(lambda: VISION_PLUGIN.actions(["analyze", "manual"]), id="actions"),
        pytest.param(
            lambda: VISION_PLUGIN.action_input_schemas({"analyze": {}, "manual": {}}),
            id="schemas",
        ),
        pytest.param(
            lambda: VISION_PLUGIN.build_family(
                [
                    ChildTool("analyze", {"type": "object"}, lambda _i: {}),
                    ChildTool("manual", {"type": "object"}, lambda _i: {"hijacked": True}),
                ]
            ),
            id="family",
        ),
    ],
)
def test_a_package_cannot_declare_re_schema_or_hand_in_the_reserved_manual(compose):
    with pytest.raises(LocalToolPluginError, match="reserved 'manual'"):
        compose()


def test_build_family_takes_an_agent_not_a_manual_child():
    """The only lever a package has over ``manual`` is *which agent*, not what."""
    parameters = list(inspect.signature(VISION_PLUGIN.build_family).parameters)
    assert parameters == ["declared", "agent"]


def test_composed_family_always_carries_a_manual_child_with_the_generic_input(tmp_path):
    family = VisionManager(_StubAgent(tmp_path), vision_service=None)._family
    assert family.has_manual()
    assert family.child_names == VISION_ACTIONS
    assert VISION_PLUGIN.action_input_schemas(
        {action: {} for action in VISION_DECLARED_ACTIONS}
    )["manual"] == MANUAL_INPUT_SCHEMA


def test_manual_answers_from_the_packages_own_installed_skill(tmp_path):
    """Packaged skill → installer destination → dispatched result, one chain."""
    _install_packaged_manual(tmp_path)
    agent = _StubAgent(tmp_path)
    manager = VisionManager(agent, vision_service=_never_called_service())

    result = manager.handle(
        {"action": "manual", "input": {}, "reasoning": "load vision guidance"}
    )

    assert result["status"] == "ok"
    assert result["action"] == "manual"
    assert result["manual_path"] == str(VISION_PLUGIN.installed_manual_path(tmp_path))
    # The body served is the package's own packaged skill, verbatim.
    assert VISION_PLUGIN.skill_body in result["manual"]
    assert f"name: {VISION_PLUGIN.skill_name}" in result["manual"]


def test_manual_is_degraded_and_truthful_when_the_package_skill_is_not_installed(tmp_path):
    """Fail-closed: no install means a reported degradation, never a silent empty."""
    manager = VisionManager(_StubAgent(tmp_path), vision_service=_never_called_service())

    result = manager.handle(
        {"action": "manual", "input": {}, "reasoning": "load vision guidance"}
    )

    assert result["status"] == "degraded"
    assert result["manual"] == ""
    assert result["manual_path"] == str(VISION_PLUGIN.installed_manual_path(tmp_path))
    assert "manual missing" in result["error"]


def test_manual_child_is_bound_to_this_plugins_own_capability_directory(tmp_path):
    """Not merely equal to it — built by the plugin, from the plugin's name."""
    _install_packaged_manual(tmp_path)
    child = VISION_PLUGIN.manual_child(_StubAgent(tmp_path))

    assert child.name == _plugin.MANUAL_ACTION
    assert child.input_schema == MANUAL_INPUT_SCHEMA
    dispatched = child.handler({})
    assert dispatched["structuredContent"]["manual_path"] == str(
        VISION_PLUGIN.installed_manual_path(tmp_path)
    )


def test_a_package_cannot_bind_manual_to_another_capabilitys_skill():
    """A descriptor whose module installs elsewhere is refused at construction."""
    with pytest.raises(LocalToolPluginError, match="another capability's installed skill"):
        LocalToolPlugin(**{**_IDENTITY, "package": "lingtai.tools.avatar"})


def test_manual_keeps_the_same_envelope_discipline_as_every_other_action(tmp_path):
    """Packaging the manual did not soften the envelope it is reached through."""
    _install_packaged_manual(tmp_path)
    manager = VisionManager(_StubAgent(tmp_path), vision_service=_never_called_service())

    # The pre-migration bare shorthand stays rejected: `input` is required.
    assert manager.handle({"action": "manual"})["status"] == "error"
    # ... its input stays strictly empty ...
    assert manager.handle(
        {"action": "manual", "input": {"topic": "analyze"}, "reasoning": "x"}
    )["status"] == "error"
    # ... and an unknown root field is rejected before the child ever runs.
    assert manager.handle(
        {"action": "manual", "input": {}, "reasoning": "x", "depth": 2}
    )["status"] == "error"


# ---------------------------------------------------------------------------
# The mount is the plugin's, and it refuses what it must not publish
# ---------------------------------------------------------------------------

def test_setup_mounts_exactly_one_public_tool_from_the_descriptor(tmp_path):
    agent = _StubAgent(tmp_path)
    manager = setup(agent, vision_service=MagicMock(spec=VisionService))

    declaration = VISION_PLUGIN.capability_declaration()
    assert list(agent.tools) == [declaration["name"]]
    mounted = agent.tools[declaration["name"]]
    assert mounted["glossary_package"] == declaration["module"]
    # What is advertised is exactly what dispatches.
    assert mounted["schema"] == manager._family.build_schema() == get_schema()
    assert mounted["handler"] == manager.handle
    # ... and it advertises the skill the plugin owns.
    assert VISION_PLUGIN.manual_action_description() in mounted["description"]
    assert VISION_PLUGIN.skill_name in mounted["description"]


@pytest.mark.parametrize(
    ("family", "handler", "description", "match"),
    [
        pytest.param(
            ToolFamily("other", [ChildTool("manual", dict(MANUAL_INPUT_SCHEMA), lambda _i: {})]),
            lambda _a: {},
            None,
            "cannot mount family 'other'",
            id="foreign-family",
        ),
        pytest.param(
            ToolFamily("vision", [ChildTool("analyze", {"type": "object"}, lambda _i: {})]),
            lambda _a: {},
            None,
            "without the reserved 'manual' action",
            id="manual-less-family",
        ),
        pytest.param(None, "not-callable", None, "handler must be callable", id="bad-handler"),
        pytest.param(None, lambda _a: {}, "Analyze an image.", "must advertise", id="unadvertised"),
    ],
)
def test_mount_refuses_what_it_must_not_publish(tmp_path, family, handler, description, match):
    agent = _StubAgent(tmp_path)
    resolved_family = family if family is not None else VISION_PLUGIN.build_family(
        [ChildTool("analyze", {"type": "object"}, lambda _i: {})]
    )
    resolved_description = (
        description if description is not None
        else VISION_PLUGIN.describe("Analyze an image.")
    )

    with pytest.raises(LocalToolPluginError, match=match):
        VISION_PLUGIN.mount(agent, resolved_family, handler, resolved_description)
    assert agent.tools == {}


# ---------------------------------------------------------------------------
# The public envelope shape is unchanged by the packaging
# ---------------------------------------------------------------------------

def test_public_schema_keeps_the_strict_action_family_shape():
    schema = get_schema()
    assert set(schema["properties"]) == {"action", "input", "reasoning", "summarize"}
    assert schema["required"] == ["action", "input", "reasoning"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["action"]["enum"] == list(VISION_ACTIONS)
    branch_titles = [b["title"] for b in schema["properties"]["input"]["oneOf"]]
    assert branch_titles == [f"{action} input" for action in VISION_ACTIONS]


def test_declared_actions_still_dispatch_into_the_package(tmp_path):
    """The plugin composes and mounts; vision still owns every declared result."""
    manager = VisionManager(_StubAgent(tmp_path), vision_service=None)
    result = manager.handle(
        {"action": "list", "input": {}, "reasoning": "enumerate vision routes"}
    )
    assert result["status"] == "ok"
    assert "presets" in result


def test_the_plugin_owns_no_provider_credential_or_security_decision():
    """Provider selection and credential resolution never entered the plugin."""
    for module in (_plugin, importlib.import_module("lingtai.tools.vision.plugin")):
        source = Path(module.__file__).read_text(encoding="utf-8")
        for forbidden in ("api_key", "token_path", "create_vision_service", "base_url"):
            assert forbidden not in source, f"{forbidden} leaked into {module.__name__}"


# ---------------------------------------------------------------------------
# Descriptor defects fail loudly at import time
# ---------------------------------------------------------------------------

def test_descriptor_rejects_a_manual_that_is_not_the_packaged_skill():
    with pytest.raises(LocalToolPluginError, match="declares name"):
        LocalToolPlugin(**{**_IDENTITY, "skill_name": "somebody-elses-manual"})


@pytest.mark.parametrize("blank_field", sorted(_IDENTITY))
def test_descriptor_rejects_blank_identity_fields(blank_field):
    with pytest.raises(LocalToolPluginError, match="non-empty string"):
        LocalToolPlugin(**{**_IDENTITY, blank_field: "  "})


def test_descriptor_rejects_a_package_with_no_manual_bundle():
    with pytest.raises(LocalToolPluginError):
        LocalToolPlugin(**{**_IDENTITY, "name": "i18n", "package": "lingtai.tools.i18n"})


def test_packaged_skill_is_shipped_and_reachable_from_the_repo():
    packaged = Path(VISION_PLUGIN.skill_path)
    assert packaged.is_file()
    assert packaged.resolve().is_relative_to(_REPO_ROOT.resolve())
    assert VISION_PLUGIN.skill_frontmatter["name"] == VISION_PLUGIN.skill_name
    assert VISION_PLUGIN.skill_frontmatter["description"]
    assert VISION_PLUGIN.skill_body.strip()
