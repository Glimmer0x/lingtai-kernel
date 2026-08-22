"""Email is a *real* Agent Plugin, proven through the kernel's own plugin service.

The claim under test is not "Email has a descriptor". It is that
``src/lingtai/tools/email/agent_plugin/`` is an Agent Plugins v1.0.0 package
which the kernel's real machinery — ``lingtai.services.plugin_registry``, the
same code path a third-party directory named in ``manifest.plugins`` travels —
validates, discovers, and mounts; that the plugin *owns* the Email manual as its
Agent Skill; and that the ``email`` family the model calls is composed from that
plugin, with the reserved ``manual`` action appended by the plugin rather than
declared by the package.

The host boundary is tested as explicitly as the plugin is. Email executes
in-process, so its plugin declares no MCP server: registering it composes one
skill and writes **zero** ``mcp_registry.jsonl`` records, which is what makes
shipping a first-party plugin inside the wheel a documentation mount rather than
a launcher. Nothing here sends mail or stands up a service — the manual is
account-independent and the dispatch boundary rejects a bad envelope before any
mailbox I/O.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from lingtai.services import plugin_registry
from lingtai.tools import _plugin as tool_plugin
from lingtai.tools import email as email_tool
from lingtai.tools._plugin import IntrinsicToolPlugin, IntrinsicToolPluginError
from lingtai.tools.email._family_schema import ACTION_ORDER, INPUT_SCHEMAS
from lingtai.tools.email.plugin import (
    EMAIL_ACTIONS,
    EMAIL_DECLARED_ACTIONS,
    EMAIL_PLUGIN,
)
from lingtai.tools.registry import INTRINSICS
from lingtai.tools.tool_family import ChildTool
from lingtai.tools.tool_family.manual import MANUAL_INPUT_SCHEMA

_TOOL_ROOT = Path(email_tool.__file__).resolve().parent

# The exact pre-plugin public action list, restated as a literal so composing it
# through the plugin cannot quietly redefine what the model may call.
_PUBLIC_ACTIONS = (
    "send", "check", "read", "dismiss", "reply", "reply_all",
    "search", "archive", "delete",
    "contacts", "add_contact", "remove_contact", "edit_contact",
    "manual",
)


class _RecordingManager:
    """Stands in for EmailManager; records every flat call, performs no I/O."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def handle(self, args: dict) -> dict:
        self.calls.append(dict(args))
        return {"status": "ok", "action": args.get("action")}


class _StubAgent:
    """The two attributes Email's family boundary actually reads."""

    def __init__(self, working_dir: Path, manager: object | None = None) -> None:
        self._working_dir = working_dir
        self._email_manager = manager


def _install_owned_manual(workdir: Path) -> Path:
    """Install the plugin-owned skill exactly where the host installs it."""
    destination = workdir / ".library" / "intrinsic" / "capabilities" / "email"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(EMAIL_PLUGIN.skill_dir, destination)
    return destination


# ---------------------------------------------------------------------------
# The package really is an Agent Plugins v1.0.0 plugin
# ---------------------------------------------------------------------------

def test_email_ships_a_plugin_directory_the_kernel_registry_accepts():
    """``read_plugin`` — the real one — validates the shipped package cleanly."""
    root = _TOOL_ROOT / "agent_plugin"
    assert root.is_dir()
    assert (root / plugin_registry.MANIFEST_FILENAME).is_file()

    record, problems = plugin_registry.read_plugin(root)
    assert problems == []
    assert record is not None
    assert record["name"] == "lingtai-email"
    assert record["skills"] == ["email-manual"]
    assert record["skill_count"] == 1
    assert Path(record["skill_paths"][0]) == EMAIL_PLUGIN.skill_dir


def test_the_registry_backed_record_is_read_lazily_and_cached():
    """The descriptor's registry half: real ``read_plugin``, on demand, once."""
    record = EMAIL_PLUGIN.plugin_record
    assert record["name"] == "lingtai-email"
    assert record["skills"] == ["email-manual"]
    assert record["mcp_servers"] == []
    # A copy per call, so a caller cannot mutate the cached record.
    record["skills"].append("smuggled")
    assert EMAIL_PLUGIN.plugin_record["skills"] == ["email-manual"]


def test_importing_the_tool_registry_does_not_pull_the_plugin_service():
    """The lazy back-edge the packaging depends on, asserted where it is used.

    ``tests/test_kernel_isolation.py`` owns the general DAG rule; this pins the
    specific edge this descriptor introduces, so a future eager validation call
    fails in the plugin's own evidence file too.
    """
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable, "-c",
            "import sys; import lingtai.tools.registry; "
            "print('PULLED' if 'lingtai.services.plugin_registry' in sys.modules "
            "else 'LAZY')",
        ],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[1]),
        env={"PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
             "PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 0, result.stderr
    assert "LAZY" in result.stdout


def test_shipped_manifest_passes_the_canonical_v1_manifest_validator():
    payload = json.loads(
        (_TOOL_ROOT / "agent_plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    assert payload["$schema"] == plugin_registry.PLUGIN_SCHEMA_URL
    ok, err = plugin_registry.validate_manifest(payload)
    assert (ok, err) == (True, None)


def test_the_plugin_is_discoverable_through_the_ordinary_scan_paths(tmp_path):
    """Both discovery shapes find it: a lone plugin root and a collection dir."""
    root = EMAIL_PLUGIN.plugin_root

    direct, direct_problems = plugin_registry.scan_plugin_root(root)
    assert direct_problems == []
    assert [r["name"] for r in direct] == ["lingtai-email"]

    collection = tmp_path / "plugins"
    shutil.copytree(root, collection / "lingtai-email")
    records, problems, report = plugin_registry.read_plugins(
        tmp_path, [str(collection)]
    )
    assert problems == []
    assert [r["name"] for r in records] == ["lingtai-email"]
    assert report[str(collection)]["exists"] is True
    assert report[str(collection)]["plugins"] == 1


def test_declaring_the_plugin_mounts_its_skill_and_launches_nothing(tmp_path):
    """The real mount path: one skill composed, zero registry records written."""
    workdir = tmp_path / "agent"
    workdir.mkdir()
    declared = workdir / "declared" / "lingtai-email"
    shutil.copytree(EMAIL_PLUGIN.plugin_root, declared)

    snapshot = plugin_registry.register_plugins(workdir, [str(declared)])

    assert [p["name"] for p in snapshot["plugins"]] == ["lingtai-email"]
    entry = snapshot["plugins"][0]
    assert entry["skills"] == ["email-manual"]
    assert entry["skipped"] == []
    # Mounted: the validated skill directory is what the skills capability
    # composes into its catalog scan.
    assert [Path(p).name for p in entry["skill_paths"]] == ["email-manual"]
    assert [Path(p).name for p in snapshot["skill_paths"]] == ["email-manual"]

    # Host boundary: an in-process tool declares no launcher, so registration
    # cannot make anything spawnable.
    assert entry["mcp_servers"] == []
    assert entry["mcp_registered"] == []
    assert snapshot["mcp_appended"] == []
    assert not (workdir / "system" / "mcp_registry.jsonl").exists()


def test_registration_is_idempotent(tmp_path):
    workdir = tmp_path / "agent"
    workdir.mkdir()
    declared = workdir / "declared" / "lingtai-email"
    shutil.copytree(EMAIL_PLUGIN.plugin_root, declared)

    first = plugin_registry.register_plugins(workdir, [str(declared)])
    second = plugin_registry.register_plugins(workdir, [str(declared)])
    assert first["plugins"] == second["plugins"]
    assert second["mcp_appended"] == []


# ---------------------------------------------------------------------------
# The plugin owns the manual
# ---------------------------------------------------------------------------

def test_the_manual_is_the_plugins_own_skill_not_a_loose_bundle():
    """There is no ``manual/`` directory left — the plugin owns the document."""
    assert not (_TOOL_ROOT / "manual").exists()
    assert EMAIL_PLUGIN.skill_path == (
        _TOOL_ROOT / "agent_plugin" / "skills" / "email-manual" / "SKILL.md"
    )
    assert EMAIL_PLUGIN.skill_frontmatter["name"] == "email-manual"
    assert EMAIL_PLUGIN.skill_body.strip()


def test_the_real_host_installer_installs_the_plugin_owned_skill(tmp_path):
    """End-to-end through `Agent._install_intrinsic_manuals`, not a hand copy.

    Only `_working_dir`, `_capabilities`, and `_log` are read by that method, so
    the stub exercises the real installer without booting an agent (no LLM, no
    mailbox, no lease). The destination and bytes are what must not move.
    """
    from lingtai.agent import Agent

    class _InstallHost:
        _capabilities: list = []

        def __init__(self, working_dir):
            self._working_dir = working_dir

        def _log(self, *args, **kwargs):
            pass

    Agent._install_intrinsic_manuals(_InstallHost(tmp_path))

    installed = (
        tmp_path / ".library" / "intrinsic" / "capabilities" / "email" / "SKILL.md"
    )
    assert installed.is_file()
    assert installed.read_bytes() == EMAIL_PLUGIN.skill_path.read_bytes()
    # A tool that still ships `manual/` is unaffected by the plugin branch.
    assert (
        tmp_path / ".library" / "intrinsic" / "capabilities" / "shell" / "SKILL.md"
    ).is_file()


def test_the_host_installer_and_the_plugin_agree_on_which_skill_is_owned():
    """``owned_skill_dir`` is what ``_install_intrinsic_manuals`` walks to."""
    assert tool_plugin.owned_skill_dir(_TOOL_ROOT) == EMAIL_PLUGIN.skill_dir
    # A tool package that ships no plugin keeps the plain ``manual/`` bundle and
    # contributes nothing here, so the host's fallback stays a fallback.
    assert tool_plugin.owned_skill_dir(_TOOL_ROOT.parent / "system") is None


def test_manual_returns_the_plugin_owned_document_in_emails_pinned_shape(tmp_path):
    installed = _install_owned_manual(tmp_path)
    agent = _StubAgent(tmp_path, _RecordingManager())

    result = email_tool.handle(agent, {"action": "manual", "input": {}})

    assert set(result) == {"status", "manual", "manual_path"}
    assert result["status"] == "ok"
    assert result["manual_path"] == str(installed / "SKILL.md")
    assert result["manual_path"].endswith("capabilities/email/SKILL.md")
    # The document the model reads is the plugin's own skill, byte for byte.
    assert result["manual"] == EMAIL_PLUGIN.skill_path.read_text(encoding="utf-8")
    assert EMAIL_PLUGIN.skill_body in result["manual"]


def test_manual_never_enters_the_email_manager(tmp_path):
    _install_owned_manual(tmp_path)
    manager = _RecordingManager()

    email_tool.handle(_StubAgent(tmp_path, manager), {"action": "manual", "input": {}})

    assert manager.calls == []


def test_manual_still_reports_the_hosts_degraded_result_when_not_installed(tmp_path):
    """The plugin owns the document; the host still owns installation."""
    result = email_tool.handle(
        _StubAgent(tmp_path, _RecordingManager()), {"action": "manual", "input": {}}
    )
    assert result["status"] == "degraded"
    assert result["manual"] == ""
    assert "email manual missing" in result["error"]


# ---------------------------------------------------------------------------
# The reserved ``manual`` action belongs to the plugin
# ---------------------------------------------------------------------------

def test_the_package_declares_its_own_actions_and_the_plugin_appends_manual():
    assert "manual" not in EMAIL_DECLARED_ACTIONS
    assert EMAIL_ACTIONS == EMAIL_DECLARED_ACTIONS + ("manual",)
    assert EMAIL_ACTIONS == _PUBLIC_ACTIONS
    assert ACTION_ORDER == EMAIL_ACTIONS
    assert tuple(INPUT_SCHEMAS) == _PUBLIC_ACTIONS
    assert INPUT_SCHEMAS["manual"] == MANUAL_INPUT_SCHEMA


@pytest.mark.parametrize(
    "compose",
    [
        lambda declared: EMAIL_PLUGIN.actions(declared),
        lambda declared: EMAIL_PLUGIN.action_input_schemas({a: {} for a in declared}),
        lambda declared: EMAIL_PLUGIN.build_family(
            None, [ChildTool(a, {}, lambda _i: {}) for a in declared]
        ),
        lambda declared: EMAIL_PLUGIN.schema_family(
            [ChildTool(a, {}, lambda _i: {}) for a in declared]
        ),
    ],
)
@pytest.mark.parametrize("declared", [(), ("send", "manual")])
def test_a_package_can_neither_declare_nothing_nor_declare_the_reserved_manual(
    compose, declared
):
    with pytest.raises(IntrinsicToolPluginError):
        compose(declared)


@pytest.mark.parametrize(
    "compose",
    [
        lambda declared: EMAIL_PLUGIN.actions(declared),
        lambda declared: EMAIL_PLUGIN.build_family(
            None, [ChildTool(a, {}, lambda _i: {}) for a in declared]
        ),
        lambda declared: EMAIL_PLUGIN.schema_family(
            [ChildTool(a, {}, lambda _i: {}) for a in declared]
        ),
    ],
)
def test_a_package_cannot_declare_the_same_action_twice(compose):
    """The sequence-shaped composers; a schema mapping cannot express a dup."""
    with pytest.raises(IntrinsicToolPluginError):
        compose(("send", "send"))


def test_the_composed_family_always_carries_a_strict_empty_manual_child(tmp_path):
    family = EMAIL_PLUGIN.build_family(
        _StubAgent(tmp_path), [ChildTool("send", {"type": "object"}, lambda _i: {})]
    )
    branches = family.build_schema()["properties"]["action"]["enum"]
    assert branches == ["send", "manual"]

    schema_only = EMAIL_PLUGIN.schema_family(
        [ChildTool("send", {"type": "object"}, lambda _i: {})]
    )
    assert schema_only.build_schema()["properties"]["action"]["enum"] == [
        "send", "manual",
    ]


def test_manual_keeps_its_strict_empty_input(tmp_path):
    """A packaged plugin cannot widen the reserved action's arguments."""
    _install_owned_manual(tmp_path)
    agent = _StubAgent(tmp_path, _RecordingManager())

    rejected = email_tool.handle(agent, {"action": "manual", "input": {"x": 1}})

    assert "manual" not in rejected
    assert rejected.get("error_code") or rejected.get("error") or rejected.get("status") == "error"


# ---------------------------------------------------------------------------
# The tool the model calls is still exactly the tool it was
# ---------------------------------------------------------------------------

def test_the_host_registers_the_intrinsic_under_the_plugins_tool_name():
    assert EMAIL_PLUGIN.name == "email"
    assert INTRINSICS[EMAIL_PLUGIN.name]["module"] is email_tool


def test_public_schema_keeps_the_strict_action_family_shape():
    schema = email_tool.get_schema()
    assert schema["properties"]["action"]["enum"] == list(_PUBLIC_ACTIONS)
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"action", "input", "reasoning"}


def test_declared_actions_still_dispatch_flat_into_the_manager(tmp_path):
    manager = _RecordingManager()
    agent = _StubAgent(tmp_path, manager)

    result = email_tool.handle(
        agent,
        {
            "action": "check",
            "input": {"folder": "inbox"},
            "reasoning": "look at the inbox",
        },
    )

    assert result == {"status": "ok", "action": "check"}
    assert manager.calls == [{"action": "check", "folder": "inbox"}]


def test_the_reserved_unread_rejection_is_unchanged(tmp_path):
    manager = _RecordingManager()
    result = email_tool.handle(_StubAgent(tmp_path, manager), {"action": "unread"})
    assert result["status"] == "error"
    assert "reserved for kernel-" in result["message"]
    assert manager.calls == []


# ---------------------------------------------------------------------------
# Descriptor defects fail at import, not at the first call
# ---------------------------------------------------------------------------

def test_descriptor_rejects_a_package_that_is_not_its_own_module():
    with pytest.raises(IntrinsicToolPluginError, match="one package"):
        IntrinsicToolPlugin(
            name="email",
            package="lingtai.tools.system",
            plugin_name="lingtai-email",
            skill_name="email-manual",
            manual_skill="email",
            summary="wrong module",
        )


def test_descriptor_rejects_a_package_that_ships_no_plugin():
    with pytest.raises(IntrinsicToolPluginError, match="ships no Agent Plugin"):
        IntrinsicToolPlugin(
            name="system",
            package="lingtai.tools.system",
            plugin_name="lingtai-system",
            skill_name="system-manual",
            manual_skill="system-manual",
            summary="no plugin directory is shipped for system",
        )


def test_descriptor_rejects_a_manifest_name_it_did_not_declare():
    with pytest.raises(IntrinsicToolPluginError, match="plugin.json declares"):
        IntrinsicToolPlugin(
            name="email",
            package="lingtai.tools.email",
            plugin_name="something-else",
            skill_name="email-manual",
            manual_skill="email",
            summary="manifest name disagreement",
        )


def test_descriptor_rejects_a_skill_the_plugin_does_not_own():
    with pytest.raises(IntrinsicToolPluginError, match="exactly the skill"):
        IntrinsicToolPlugin(
            name="email",
            package="lingtai.tools.email",
            plugin_name="lingtai-email",
            skill_name="not-the-email-manual",
            manual_skill="email",
            summary="skill name disagreement",
        )


@pytest.mark.parametrize(
    "blank_field",
    ["name", "package", "plugin_name", "skill_name", "manual_skill", "summary"],
)
def test_descriptor_rejects_blank_identity_fields(blank_field):
    fields = {
        "name": "email",
        "package": "lingtai.tools.email",
        "plugin_name": "lingtai-email",
        "skill_name": "email-manual",
        "manual_skill": "email",
        "summary": "LingTai internal email.",
    }
    fields[blank_field] = "   "
    with pytest.raises(IntrinsicToolPluginError, match="non-empty string"):
        IntrinsicToolPlugin(**fields)
