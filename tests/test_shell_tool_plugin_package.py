"""Shell's built-in tool plugin packaging invariants.

Shell is a plugin-style package: ``src/lingtai/tools/bash/`` ships the execution
engine, the bundled ``manual/SKILL.md`` behind ``action='manual'``, and the
capability record the host mounts it by. ``lingtai.tools._plugin.KernelToolPlugin``
binds those three and owns the one promise a package must not be able to break —
the reserved ``manual`` action, appended from the packaged skill rather than
declared by the package.

These tests pin the packaging promise, the discovery/mount contract the host
consumes, and the *unchanged* public Shell surface around it. They run no shell
command: the manual is I/O-free and every packaging assertion is made on
descriptors and schemas.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from lingtai.tools import _plugin
from lingtai.tools._plugin import KernelToolPlugin, KernelToolPluginError
from lingtai.tools.bash import _tool_family
from lingtai.tools.bash.plugin import (
    SHELL_ACTIONS,
    SHELL_DECLARED_ACTIONS,
    SHELL_PLUGIN,
)
from lingtai.tools.registry import BUILTIN_TOOLS, CORE_DEFAULTS
from lingtai.tools.tool_family import ChildTool
from lingtai.tools.tool_family.manual import MANUAL_INPUT_SCHEMA as SHARED_MANUAL_SCHEMA

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PACKAGE_DIR = _REPO_ROOT / "src" / "lingtai" / "tools" / "bash"


def _agent(working_dir: Path) -> SimpleNamespace:
    return SimpleNamespace(_working_dir=working_dir)


def _install_manual(working_dir: Path, body: str) -> Path:
    """Install a shell manual exactly where the real initializer puts it."""
    manual_dir = working_dir / ".library" / "intrinsic" / "capabilities" / "shell"
    manual_dir.mkdir(parents=True, exist_ok=True)
    manual_path = manual_dir / "SKILL.md"
    manual_path.write_text(body, encoding="utf-8")
    return manual_path


# ---------------------------------------------------------------------------
# The package ships its own capability record
# ---------------------------------------------------------------------------

def test_package_declaration_matches_the_registry_the_host_actually_mounts():
    """The package owns its mount facts; the registry tables publish exactly them."""
    declaration = SHELL_PLUGIN.capability_declaration()
    assert BUILTIN_TOOLS[declaration["name"]] == declaration["module"]
    assert CORE_DEFAULTS[declaration["name"]] == declaration["default_kwargs"]
    assert declaration["source"] == _plugin.KERNEL_SOURCE
    assert declaration["kind"] == "capability"


def test_declaration_names_the_declaring_package_and_its_retained_directory():
    declaration = SHELL_PLUGIN.capability_declaration()
    assert declaration["module"] == "lingtai.tools.bash"
    assert SHELL_PLUGIN.implementation_dir == "bash"
    # The historical retained-implementation split is stated once, here — the
    # public name is never the directory name by accident.
    assert declaration["name"] == "shell" != SHELL_PLUGIN.implementation_dir
    assert declaration["manual_source"] == "bash/manual"
    assert declaration["manual_destination"] == "shell"


def test_registry_tables_stay_the_runtime_source_and_import_nothing_eagerly():
    """The descriptor documents the record; it does not replace registry I/O."""
    registry_source = (
        _REPO_ROOT / "src" / "lingtai" / "tools" / "registry.py"
    ).read_text(encoding="utf-8")
    assert "lingtai.tools.bash.plugin" not in registry_source
    assert '"shell": "lingtai.tools.bash"' in registry_source


# ---------------------------------------------------------------------------
# Runtime discovery / mount: the installer asks the package
# ---------------------------------------------------------------------------

def test_manual_destination_is_discovered_from_the_package_not_hard_coded():
    assert _plugin.tool_plugin_for("bash") is SHELL_PLUGIN
    assert _plugin.manual_destination_for("bash") == SHELL_PLUGIN.manual_destination


def test_the_installer_no_longer_spells_the_bash_to_shell_mapping_itself():
    """``Agent._install_intrinsic_manuals`` consumes the descriptor's answer."""
    agent_source = (_REPO_ROOT / "src" / "lingtai" / "agent.py").read_text(encoding="utf-8")
    assert "tool_plugins.manual_destination_for(entry.name)" in agent_source
    assert 'if entry.name == "bash"' not in agent_source


def test_packages_without_a_descriptor_keep_their_own_or_retained_destination():
    # Unconverted retained directory keeps its historical alias...
    assert _plugin.manual_destination_for("web_search") == "web"
    # ...and an ordinary package installs under its own name.
    assert _plugin.manual_destination_for("daemon") == "daemon"
    # A directory that ships no descriptor is answered without one, and the
    # miss is cached rather than re-imported on every library rewrite.
    assert _plugin.tool_plugin_for("daemon") is None
    assert _plugin.manual_destination_for("does-not-exist") == "does-not-exist"


def test_the_installed_manual_actually_lands_where_the_declaration_says(tmp_path):
    destination = SHELL_PLUGIN.capability_declaration()["manual_destination"]
    installed = SHELL_PLUGIN.installed_manual_path(_agent(tmp_path))
    assert Path(installed).parent.name == destination
    assert Path(installed).name == _plugin.SKILL_FILENAME


def test_registering_a_conflicting_descriptor_for_one_package_fails_loudly():
    # Re-registering the identical descriptor is a no-op (module reimport).
    assert _plugin.register_tool_plugin(SHELL_PLUGIN) is SHELL_PLUGIN
    with pytest.raises(KernelToolPluginError, match="conflicting"):
        _plugin.register_tool_plugin(
            KernelToolPlugin(
                name="not-shell",
                package="lingtai.tools.bash",
                summary="impostor",
                skill_name="shell-manual",
            )
        )
    # The registry is unchanged by the rejected attempt.
    assert _plugin.registered_tool_plugins()["bash"] is SHELL_PLUGIN


# ---------------------------------------------------------------------------
# `manual` is mandatory, reserved, and sourced from the packaged skill
# ---------------------------------------------------------------------------

def test_package_does_not_declare_manual_and_the_plugin_appends_it_last():
    assert _plugin.MANUAL_ACTION not in SHELL_DECLARED_ACTIONS
    assert SHELL_DECLARED_ACTIONS == ("run", "poll", "cancel")
    assert SHELL_ACTIONS == (*SHELL_DECLARED_ACTIONS, "manual")
    assert SHELL_ACTIONS[-1] == "manual"


@pytest.mark.parametrize(
    "compose",
    [
        pytest.param(lambda: SHELL_PLUGIN.actions(["run", "manual"]), id="actions"),
        pytest.param(
            lambda: SHELL_PLUGIN.action_input_schemas({"run": {}, "manual": {}}),
            id="schemas",
        ),
        pytest.param(
            lambda: SHELL_PLUGIN.build_family(
                [
                    ChildTool("run", {"type": "object"}, lambda _i: {}),
                    ChildTool("manual", {"type": "object"}, lambda _i: {"hijacked": True}),
                ]
            ),
            id="family",
        ),
    ],
)
def test_the_package_cannot_declare_re_schema_or_rebind_the_reserved_manual(compose):
    with pytest.raises(KernelToolPluginError, match="reserved 'manual'"):
        compose()


def test_composed_family_always_carries_a_manual_child_with_the_shared_schema():
    family = SHELL_PLUGIN.build_family(
        [ChildTool("run", {"type": "object"}, lambda _i: {})]
    )
    assert family.has_manual()
    assert family.child_names == ("run", "manual")
    # The plugin deep-copies the one shared reserved-manual literal rather than
    # minting a second spelling, so Shell's advertised manual input stays
    # byte-identical to every other LingTai family's.
    schema = SHELL_PLUGIN.manual_input_schema()
    assert schema == SHARED_MANUAL_SCHEMA
    assert schema is not SHARED_MANUAL_SCHEMA
    schema["properties"]["injected"] = {"type": "string"}
    assert "injected" not in SHARED_MANUAL_SCHEMA["properties"]
    assert "injected" not in SHELL_PLUGIN.manual_input_schema()["properties"]


def test_a_descriptor_whose_packaged_skill_is_missing_or_misnamed_fails_at_import():
    with pytest.raises(KernelToolPluginError, match="expected 'wrong-name'"):
        KernelToolPlugin(
            name="shell", package="lingtai.tools.bash",
            summary="s", skill_name="wrong-name",
        )
    with pytest.raises(KernelToolPluginError, match="no bundled manual/SKILL.md"):
        KernelToolPlugin(
            name="file", package="lingtai.tools.file",
            summary="s", skill_name="file-manual",
        )
    with pytest.raises(KernelToolPluginError, match="must be a lingtai.tools"):
        KernelToolPlugin(
            name="shell", package="lingtai.mcp_servers.telegram",
            summary="s", skill_name="shell-manual",
        )


def test_the_packaged_skill_is_the_one_the_descriptor_names():
    packaged = _PACKAGE_DIR / "manual" / "SKILL.md"
    assert Path(SHELL_PLUGIN.skill_path) == packaged
    assert SHELL_PLUGIN.skill_frontmatter["name"] == SHELL_PLUGIN.skill_name == "shell-manual"
    assert SHELL_PLUGIN.skill_body.strip()
    # ``skill_text`` is the file verbatim (what the installer copies); the body
    # is the same file with frontmatter stripped.
    assert SHELL_PLUGIN.skill_text == packaged.read_text(encoding="utf-8")
    assert SHELL_PLUGIN.skill_body in SHELL_PLUGIN.skill_text
    assert SHELL_PLUGIN.skill_text.startswith("---")
    assert not SHELL_PLUGIN.skill_body.startswith("---")
    # Frontmatter is handed out as a copy — a caller cannot mutate the loaded skill.
    SHELL_PLUGIN.skill_frontmatter["name"] = "tampered"
    assert SHELL_PLUGIN.skill_frontmatter["name"] == "shell-manual"


# ---------------------------------------------------------------------------
# `manual` keeps the host boundary and gains a packaged floor
# ---------------------------------------------------------------------------

def test_manual_serves_the_host_installed_copy_and_its_host_local_path(tmp_path):
    body = "# shell manual\n\nasync hygiene and advanced usage.\n"
    manual_path = _install_manual(tmp_path, body)

    result = SHELL_PLUGIN.manual_payload(_agent(tmp_path))

    assert result["status"] == "ok"
    assert result["content"][0]["text"] == body
    assert result["structuredContent"]["manual_path"] == str(manual_path)
    assert result["structuredContent"]["manual_source"] == _plugin.MANUAL_SOURCE_INSTALLED
    assert result["structuredContent"]["skill"] == "shell-manual"
    assert "error" not in result and "warning" not in result


def test_manual_falls_back_to_the_packaged_skill_when_the_library_is_missing(tmp_path):
    """Package ownership's payoff: `manual` can no longer answer with nothing."""
    result = SHELL_PLUGIN.manual_payload(_agent(tmp_path))

    assert result["status"] == "ok"
    assert result["content"][0]["text"] == SHELL_PLUGIN.skill_text
    assert result["structuredContent"]["manual_path"] == SHELL_PLUGIN.skill_path
    assert result["structuredContent"]["manual_source"] == _plugin.MANUAL_SOURCE_PACKAGED
    # The host fact stays visible: the model is told which library path was empty.
    missing = result["structuredContent"]["installed_manual_path"]
    assert missing == SHELL_PLUGIN.installed_manual_path(_agent(tmp_path))
    assert not Path(missing).exists()
    assert "shell-manual" in result["warning"] and missing in result["warning"]


def test_manual_answers_the_packaged_skill_for_the_agentless_schema_only_family():
    """The module-level schema-only family has no library to read."""
    result = SHELL_PLUGIN.manual_payload(None)
    assert result["content"][0]["text"] == SHELL_PLUGIN.skill_text
    assert result["structuredContent"]["manual_source"] == _plugin.MANUAL_SOURCE_PACKAGED


def test_manual_child_is_plugin_owned_and_never_reaches_the_shell_engine(tmp_path):
    _install_manual(tmp_path, "# shell manual\n")

    class _ExplodingManager:
        def handle(self, args):  # pragma: no cover - must never be called
            raise AssertionError("manual must not reach the execution engine")

    from lingtai.tools.bash._tool_family import ShellFamilyDispatcher

    dispatcher = ShellFamilyDispatcher(_ExplodingManager(), _agent(tmp_path))
    result = dispatcher.handle({"action": "manual", "input": {}, "reasoning": "read"})

    assert result["content"][0]["text"] == "# shell manual\n"
    assert result["structuredContent"]["skill"] == "shell-manual"


# ---------------------------------------------------------------------------
# The public Shell surface is unchanged by the conversion
# ---------------------------------------------------------------------------

def test_the_public_schema_is_still_composed_from_the_plugin_action_list():
    schema = _tool_family.get_schema()
    assert tuple(schema["properties"]["action"]["enum"]) == SHELL_ACTIONS
    branches = {
        branch["if"]["properties"]["action"]["const"]
        for branch in schema["allOf"]
    }
    assert branches == set(SHELL_ACTIONS)
    assert set(schema["properties"]["input"]["oneOf"][0]["properties"]) <= set(
        _tool_family.RUN_INPUT_SCHEMA["properties"]
    )


def test_declared_branches_and_the_plugin_action_list_cannot_drift():
    assert tuple(_tool_family._DECLARED_INPUT_SCHEMAS) == SHELL_DECLARED_ACTIONS
    composed = SHELL_PLUGIN.action_input_schemas(_tool_family._DECLARED_INPUT_SCHEMAS)
    assert tuple(composed) == SHELL_ACTIONS
    assert composed["manual"] == _tool_family.MANUAL_INPUT_SCHEMA


def test_the_action_required_message_is_derived_from_the_plugin_action_list(tmp_path):
    class _ExplodingManager:
        def handle(self, args):  # pragma: no cover - never reached
            raise AssertionError("dispatch must not happen without an action")

    from lingtai.tools.bash._tool_family import ShellFamilyDispatcher

    dispatcher = ShellFamilyDispatcher(_ExplodingManager(), _agent(tmp_path))
    result = dispatcher.handle({"input": {}, "reasoning": "no action"})
    assert result["message"] == "action must be one of run, poll, cancel, or manual"
    assert _tool_family._ACTIONS_PROSE == "run, poll, cancel, or manual"


def test_the_conversion_touches_no_containment_dialect_or_async_surface():
    """The descriptor is declarative — it holds no execution machinery.

    Checked on the parsed modules, not on their prose: the descriptor module
    binds nothing but its own constants and the packaging primitives, and the
    shared module calls no process/filesystem-mutating API.
    """
    import ast

    from lingtai.tools.bash import plugin as shell_plugin_module

    bound = {
        name for name, value in vars(shell_plugin_module).items()
        if not name.startswith("__")
    }
    assert bound == {
        "annotations", "KernelToolPlugin", "register_tool_plugin",
        "SHELL_PLUGIN", "SHELL_DECLARED_ACTIONS", "SHELL_ACTIONS",
    }

    forbidden_calls = {"Popen", "run", "system", "rmtree", "copytree", "spawn"}
    shared = ast.parse(
        (_REPO_ROOT / "src" / "lingtai" / "tools" / "_plugin.py").read_text(encoding="utf-8")
    )
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(shared)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert not imported & {"subprocess", "os", "shutil", "signal", "threading"}
    called = {
        node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
        for node in ast.walk(shared)
        if isinstance(node, ast.Call)
    }
    assert not called & forbidden_calls


def test_the_descriptor_is_frozen_and_its_default_kwargs_cannot_be_mutated():
    with pytest.raises(Exception):
        SHELL_PLUGIN.name = "not-shell"  # type: ignore[misc]
    with pytest.raises(TypeError):
        SHELL_PLUGIN.default_kwargs["yolo"] = False  # type: ignore[index]
    # The declaration hands out a copy, so a caller cannot edit the core default.
    declaration = SHELL_PLUGIN.capability_declaration()
    declaration["default_kwargs"]["yolo"] = False
    assert SHELL_PLUGIN.capability_declaration()["default_kwargs"] == {"yolo": True}
    assert CORE_DEFAULTS["shell"] == {"yolo": True}


def test_the_real_installer_writes_this_package_skill_to_this_declared_destination(tmp_path):
    """End-to-end: the host's library rewrite and the descriptor agree exactly.

    Runs the actual ``Agent._install_intrinsic_manuals`` — the wipe-and-rewrite
    that owns ``.library/intrinsic/`` — against a bare working directory, and
    proves the packaged Shell skill lands under the declared destination with
    its ``reference/`` submanuals, byte-identical to what the plugin owns. This
    is what makes the packaged fallback a true floor rather than a second,
    quietly different manual: whichever source answers, the model reads the
    same bytes.
    """
    from lingtai.agent import Agent

    class _Stub:
        _capabilities: list = []
        _working_dir = tmp_path

        def _log(self, *args, **kwargs):  # pragma: no cover - never expected
            raise AssertionError("installing manuals must not log a failure")

    Agent._install_intrinsic_manuals(_Stub())

    capabilities = tmp_path / ".library" / "intrinsic" / "capabilities"
    installed = capabilities / SHELL_PLUGIN.manual_destination / "SKILL.md"
    assert installed.is_file()
    assert installed.read_text(encoding="utf-8") == SHELL_PLUGIN.skill_text
    assert str(installed) == SHELL_PLUGIN.installed_manual_path(_agent(tmp_path))
    # The retained implementation directory never leaks into the flat
    # model-facing namespace, and neither does the unconverted `web_search` one.
    names = {entry.name for entry in capabilities.iterdir()}
    assert {"shell", "web"} <= names
    assert not names & {"bash", "web_search"}
    # Sidecar references travel with the manual the descriptor names.
    assert (installed.parent / "reference").is_dir()

    # Installed and packaged sources answer with the same bytes.
    served = SHELL_PLUGIN.manual_payload(_agent(tmp_path))
    assert served["structuredContent"]["manual_source"] == _plugin.MANUAL_SOURCE_INSTALLED
    installed.unlink()
    fallback = SHELL_PLUGIN.manual_payload(_agent(tmp_path))
    assert fallback["structuredContent"]["manual_source"] == _plugin.MANUAL_SOURCE_PACKAGED
    assert fallback["content"][0]["text"] == served["content"][0]["text"]
