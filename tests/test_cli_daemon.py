"""``lingtai-agent daemon`` CLI surface.

The engine itself is covered by ``test_daemon*.py``; these tests pin the CLI's
own guardrails — what it refuses, what it will not spawn, and what it must not
write — plus the fact that a dispatch reaches the unmodified engine.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _write_preset(tmp_path: Path, name: str, *, provider: str = "anthropic",
                  model: str = "preset-model",
                  capabilities: dict | None = None) -> str:
    """Write a loadable preset file and return its path as a string."""
    library = tmp_path / "presets"
    library.mkdir(parents=True, exist_ok=True)
    path = library / f"{name}.json"
    path.write_text(json.dumps({
        "name": name,
        "description": {"summary": f"{name} preset"},
        "manifest": {
            "llm": {
                "provider": provider,
                "model": model,
                "api_key": "preset-key",
                "base_url": None,
            },
            "capabilities": {"file": {}} if capabilities is None else capabilities,
        },
    }), encoding="utf-8")
    return str(path)


def _write_agent_dir(tmp_path: Path, *, allowed: list[str] | None = None,
                     preset_block: object | None = None,
                     capabilities: dict | None = None,
                     disable: list[str] | None = None,
                     env_file: str | None = None,
                     extra_manifest: dict | None = None) -> Path:
    """Create an agent working directory with a schema-valid init.json.

    Schema-valid matters now that the CLI reads init.json through the canonical
    reader: `manifest.preset`, when present, must carry `active`/`default`/
    non-empty `allowed`, and `active` must point at a loadable preset. Callers
    that only want an allowlist get one built around a real preset file.
    """
    agent_dir = tmp_path / "agent"
    agent_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict = {
        "agent_name": "cli-daemon-agent",
        "language": "en",
        "llm": {
            "provider": "anthropic",
            "model": "test-model",
            "api_key": "test-key",
            "base_url": None,
        },
        "capabilities": {} if capabilities is None else capabilities,
    }
    if disable is not None:
        manifest["disable"] = disable
    if preset_block is not None:
        manifest["preset"] = preset_block
    elif allowed is not None:
        home = _write_preset(tmp_path, "home")
        manifest["preset"] = {
            "active": home,
            "default": home,
            "allowed": [home, *allowed],
        }
    if extra_manifest:
        manifest.update(extra_manifest)
    data: dict = {"manifest": manifest, "covenant": "", "pad": "", "lingtai": ""}
    if env_file is not None:
        data["env_file"] = env_file
    (agent_dir / "init.json").write_text(json.dumps(data), encoding="utf-8")
    return agent_dir


def _write_tasks(tmp_path: Path, payload: object, name: str = "tasks.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _run_cli(monkeypatch, argv: list[str]) -> int:
    """Invoke ``lingtai.cli.main`` and return the process exit code (0 = ok)."""
    from lingtai.cli import main

    monkeypatch.setattr(sys, "argv", ["lingtai-agent", *argv])
    try:
        main()
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


@pytest.fixture
def no_spawn(monkeypatch):
    """Record every detached spawn the engine attempts instead of performing it.

    Patching at ``_spawn_detached_lingtai_run`` keeps the whole CLI → envelope
    → ``_handle_emanate`` path (validation, preset gate, run-dir creation,
    prompt build) live, and stops exactly at the process boundary.
    """
    from lingtai.tools.daemon import DaemonManager

    spawns: list[dict] = []

    def _record(self, run_dir, **kwargs):
        spawns.append({"run_dir": run_dir, **kwargs})

    monkeypatch.setattr(DaemonManager, "_spawn_detached_lingtai_run", _record)
    return spawns


# ---------------------------------------------------------------------------
# Tasks-file validation
# ---------------------------------------------------------------------------


def test_emanate_refuses_missing_tasks_file(tmp_path, monkeypatch, capsys, no_spawn):
    agent_dir = _write_agent_dir(tmp_path)
    code = _run_cli(monkeypatch, [
        "daemon", "emanate",
        "--tasks", str(tmp_path / "absent.json"),
        "--agent-dir", str(agent_dir), "--yes",
    ])
    assert code == 1
    assert "does not exist" in capsys.readouterr().err
    assert no_spawn == []


def test_emanate_refuses_empty_tasks_file(tmp_path, monkeypatch, capsys, no_spawn):
    agent_dir = _write_agent_dir(tmp_path)
    empty = tmp_path / "empty.json"
    empty.write_text("", encoding="utf-8")
    code = _run_cli(monkeypatch, [
        "daemon", "emanate", "--tasks", str(empty),
        "--agent-dir", str(agent_dir), "--yes",
    ])
    assert code == 1
    assert "is empty" in capsys.readouterr().err
    assert no_spawn == []


def test_emanate_refuses_tasks_file_with_no_tasks(tmp_path, monkeypatch, capsys, no_spawn):
    agent_dir = _write_agent_dir(tmp_path)
    tasks = _write_tasks(tmp_path, {"tasks": []})
    code = _run_cli(monkeypatch, [
        "daemon", "emanate", "--tasks", str(tasks),
        "--agent-dir", str(agent_dir), "--yes",
    ])
    assert code == 1
    assert "no tasks" in capsys.readouterr().err
    assert no_spawn == []


@pytest.mark.parametrize("payload,fragment", [
    ({"tasks": [{"task": "x", "tools": ["file"]}], "nope": 1}, "unsupported field"),
    ({"tasks": [{"task": "x", "tools": ["file"], "bogus": 1}]}, "unsupported field"),
    ({"tasks": [{"tools": ["file"]}]}, "tasks[0].task is required"),
    ({"tasks": [{"task": "x"}]}, "tasks[0].tools is required"),
    ({"tasks": ["not-an-object"]}, "tasks[0] must be object"),
])
def test_emanate_refuses_off_schema_payloads(tmp_path, monkeypatch, capsys, no_spawn,
                                             payload, fragment):
    """Structural checks read the daemon tool's own emanate schema."""
    agent_dir = _write_agent_dir(tmp_path)
    tasks = _write_tasks(tmp_path, payload)
    code = _run_cli(monkeypatch, [
        "daemon", "emanate", "--tasks", str(tasks),
        "--agent-dir", str(agent_dir), "--yes",
    ])
    assert code == 1
    assert fragment in capsys.readouterr().err
    assert no_spawn == []


def test_emanate_accepts_bare_task_array(tmp_path, monkeypatch, capsys, no_spawn):
    agent_dir = _write_agent_dir(tmp_path)
    tasks = _write_tasks(tmp_path, [{"task": "bare array form", "tools": ["file"]}])
    assert _run_cli(monkeypatch, [
        "daemon", "emanate", "--tasks", str(tasks), "--agent-dir", str(agent_dir),
    ]) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["count"] == 1
    assert no_spawn == []


# ---------------------------------------------------------------------------
# --agent-dir
# ---------------------------------------------------------------------------


def test_emanate_requires_agent_dir(tmp_path, monkeypatch, capsys, no_spawn):
    tasks = _write_tasks(tmp_path, {"tasks": [{"task": "x", "tools": ["file"]}]})
    code = _run_cli(monkeypatch, ["daemon", "emanate", "--tasks", str(tasks)])
    assert code == 2  # argparse usage error
    assert "--agent-dir" in capsys.readouterr().err
    assert no_spawn == []


def test_emanate_refuses_agent_dir_without_init_json(tmp_path, monkeypatch, capsys, no_spawn):
    bare = tmp_path / "not-an-agent"
    bare.mkdir()
    tasks = _write_tasks(tmp_path, {"tasks": [{"task": "x", "tools": ["file"]}]})
    code = _run_cli(monkeypatch, [
        "daemon", "emanate", "--tasks", str(tasks),
        "--agent-dir", str(bare), "--yes",
    ])
    assert code == 1
    assert "init.json" in capsys.readouterr().err
    assert no_spawn == []


# ---------------------------------------------------------------------------
# --yes gate
# ---------------------------------------------------------------------------


def test_emanate_without_yes_previews_and_spawns_nothing(tmp_path, monkeypatch,
                                                        capsys, no_spawn):
    agent_dir = _write_agent_dir(tmp_path)
    tasks = _write_tasks(tmp_path, {"tasks": [
        {"task": "Summarize docs into notes.md", "tools": ["file"]},
        {"task": "Second task", "tools": ["file", "shell"]},
    ]})
    assert _run_cli(monkeypatch, [
        "daemon", "emanate", "--tasks", str(tasks), "--agent-dir", str(agent_dir),
    ]) == 0

    captured = capsys.readouterr()
    preview = json.loads(captured.out)
    assert preview["status"] == "preview"
    assert preview["dispatched"] is False
    assert preview["count"] == 2
    assert preview["backend"] == "lingtai"
    assert [t["tools"] for t in preview["tasks"]] == [["file"], ["file", "shell"]]
    assert "--yes" in captured.err

    assert no_spawn == []
    assert not (agent_dir / "daemons").exists()


def test_emanate_with_yes_dispatches_through_the_engine(tmp_path, monkeypatch,
                                                        capsys, no_spawn):
    agent_dir = _write_agent_dir(tmp_path)
    tasks = _write_tasks(tmp_path, {"tasks": [
        {"task": "Summarize docs into notes.md", "tools": ["file"]},
    ]})
    assert _run_cli(monkeypatch, [
        "daemon", "emanate", "--tasks", str(tasks),
        "--agent-dir", str(agent_dir), "--yes",
    ]) == 0

    result = json.loads(capsys.readouterr().out)
    # The daemon tool's own emanate result shape, verbatim.
    assert result["status"] == "dispatched"
    assert result["count"] == 1
    assert len(result["ids"]) == 1
    assert result["group_id"]
    assert "handoff" in result

    assert len(no_spawn) == 1
    assert no_spawn[0]["task"] == "Summarize docs into notes.md"
    assert (agent_dir / "daemons").is_dir()


def test_emanate_env_file_budget_overrides_daemon_json(tmp_path, monkeypatch,
                                                       capsys, no_spawn):
    """A budget override in the agent's env_file reaches manager construction.

    Regression: dispatch used to build the ``DaemonManager`` before the lazy
    ``service`` read loaded the configured ``env_file``, so a valid
    ``LINGTAI_DAEMON_SYSTEM_PROMPT_BUDGET_CHARS`` configured there lost to
    ``daemon/daemon.json`` on the CLI path only.
    """
    # setenv-then-delenv records the key with monkeypatch so the mid-run
    # load_env_file write is removed at teardown; the run itself starts with
    # no inherited process value masking the env_file source.
    monkeypatch.setenv("LINGTAI_DAEMON_SYSTEM_PROMPT_BUDGET_CHARS", "sentinel")
    monkeypatch.delenv("LINGTAI_DAEMON_SYSTEM_PROMPT_BUDGET_CHARS")

    env_file = tmp_path / "runtime.env"
    env_file.write_text(
        "LINGTAI_DAEMON_SYSTEM_PROMPT_BUDGET_CHARS=26000\n", encoding="utf-8",
    )
    agent_dir = _write_agent_dir(tmp_path, env_file=str(env_file))
    (agent_dir / "daemon").mkdir()
    (agent_dir / "daemon" / "daemon.json").write_text(
        json.dumps({"system_prompt_budget_chars": 25_000}), encoding="utf-8",
    )

    import lingtai.tools.daemon as daemon_tool

    budgets: list[int] = []
    real_setup = daemon_tool.setup

    def _recording_setup(agent, **kwargs):
        mgr = real_setup(agent, **kwargs)
        budgets.append(mgr._system_prompt_budget_chars)
        return mgr

    monkeypatch.setattr(daemon_tool, "setup", _recording_setup)

    tasks = _write_tasks(tmp_path, {"tasks": [
        {"task": "Summarize docs into notes.md", "tools": ["file"]},
    ]})
    assert _run_cli(monkeypatch, [
        "daemon", "emanate", "--tasks", str(tasks),
        "--agent-dir", str(agent_dir), "--yes",
    ]) == 0

    assert json.loads(capsys.readouterr().out)["status"] == "dispatched"
    assert len(no_spawn) == 1
    assert budgets == [26_000]


def test_emanate_backend_flag_overrides_the_file(tmp_path, monkeypatch, capsys, no_spawn):
    agent_dir = _write_agent_dir(tmp_path)
    tasks = _write_tasks(tmp_path, {
        "tasks": [{"task": "x", "tools": ["file"]}],
        "backend": "lingtai",
    })
    assert _run_cli(monkeypatch, [
        "daemon", "emanate", "--tasks", str(tasks),
        "--agent-dir", str(agent_dir), "--backend", "codex",
    ]) == 0
    assert json.loads(capsys.readouterr().out)["backend"] == "codex"
    assert no_spawn == []


# ---------------------------------------------------------------------------
# P1-3 regression: the preview validates against the canonical emanate schema
#
# These all used to print a clean preview and exit 0, because every bound below
# lived in the family dispatcher, which only runs under --yes.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("payload,fragment", [
    ({"tasks": [{"task": "x", "tools": ["file"]}], "backend": "not-a-backend"},
     "is not one of"),
    ({"tasks": [{"task": "x", "tools": ["file"]}], "max_turns": 0},
     "max_turns must be >= 1"),
    ({"tasks": [{"task": "x", "tools": ["file"]}], "max_turns": 999999},
     "max_turns must be <= "),
    ({"tasks": [{"task": "x", "tools": ["file"]}], "timeout": 1},
     "timeout must be >= 5"),
    ({"tasks": [{"task": "x", "tools": ["file"], "context_token_limit": 0}]},
     "context_token_limit must be >= 1"),
    ({"tasks": [{"task": "x", "tools": ["file"]}], "max_turns": "many"},
     "max_turns must be integer or null"),
    ({"tasks": [{"task": "x", "tools": [7]}]},
     "tasks[0].tools[0] must be string"),
    ({"tasks": [{"task": "x", "tools": ["file"], "preset": 7}]},
     "tasks[0].preset must be string"),
    ({"tasks": [{"task": "x", "tools": ["file"], "skills": "not-a-list"}]},
     "tasks[0].skills must be array"),
])
def test_preview_refuses_schema_violations_without_yes(tmp_path, monkeypatch, capsys,
                                                       no_spawn, payload, fragment):
    """Every bound the tool enforces at dispatch is enforced at preview too."""
    agent_dir = _write_agent_dir(tmp_path)
    tasks = _write_tasks(tmp_path, payload)
    code = _run_cli(monkeypatch, [
        "daemon", "emanate", "--tasks", str(tasks), "--agent-dir", str(agent_dir),
    ])
    assert code == 1
    err = capsys.readouterr().err
    assert "does not match the daemon emanate schema" in err
    assert fragment in err
    assert no_spawn == []
    assert not (agent_dir / "daemons").exists()


def test_preview_refuses_the_reviewers_exact_payload(tmp_path, monkeypatch, capsys, no_spawn):
    """The reported reproducer: four violations at once, previously exit 0."""
    agent_dir = _write_agent_dir(tmp_path)
    tasks = _write_tasks(tmp_path, {
        "tasks": [{"task": "x", "tools": ["file"], "context_token_limit": 0}],
        "backend": "not-a-backend",
        "max_turns": 0,
        "timeout": 1,
    })
    code = _run_cli(monkeypatch, [
        "daemon", "emanate", "--tasks", str(tasks), "--agent-dir", str(agent_dir),
    ])
    assert code == 1
    err = capsys.readouterr().err
    # All four are reported together rather than one per run.
    assert "is not one of" in err
    assert "max_turns must be >= 1" in err
    assert "timeout must be >= 5" in err
    assert "context_token_limit must be >= 1" in err
    assert no_spawn == []


def test_backend_flag_is_held_to_the_same_enum(tmp_path, monkeypatch, capsys, no_spawn):
    """--backend overrides the file, so it needs the same enum check."""
    agent_dir = _write_agent_dir(tmp_path)
    tasks = _write_tasks(tmp_path, {"tasks": [{"task": "x", "tools": ["file"]}]})
    code = _run_cli(monkeypatch, [
        "daemon", "emanate", "--tasks", str(tasks),
        "--agent-dir", str(agent_dir), "--backend", "not-a-backend",
    ])
    assert code == 1
    assert "--backend 'not-a-backend' is not one of" in capsys.readouterr().err
    assert no_spawn == []


def test_schema_bounds_are_read_from_the_tool_not_restated():
    """The validator's numbers come from ``_tool_family``, so they cannot drift."""
    from lingtai.tools.daemon import _BACKEND_SCHEMA_ENUM
    from lingtai.tools.daemon._tool_family import _emanate_input_schema
    from lingtai.cli_daemon import CliDaemonError, _validate_emanate_input

    schema = _emanate_input_schema(list(_BACKEND_SCHEMA_ENUM))
    ceiling = schema["properties"]["max_turns"]["maximum"]
    floor = schema["properties"]["timeout"]["minimum"]

    ok = {"tasks": [{"task": "x", "tools": []}], "max_turns": ceiling, "timeout": floor}
    assert _validate_emanate_input(dict(ok))

    with pytest.raises(CliDaemonError, match=f"must be <= {ceiling}"):
        _validate_emanate_input({**ok, "max_turns": ceiling + 1})
    with pytest.raises(CliDaemonError, match=f"must be >= {floor}"):
        _validate_emanate_input({**ok, "timeout": floor - 1})


def test_validator_fails_loudly_on_an_unknown_schema_keyword():
    """A new schema keyword must break the interpreter, not be ignored."""
    from lingtai.cli_daemon import CliDaemonError, _check_schema

    with pytest.raises(CliDaemonError, match="unsupported keyword"):
        _check_schema({}, {"type": "object", "dependentRequired": {}}, "", [])


# ---------------------------------------------------------------------------
# P1-1 regression: the tool surface respects effective capability policy
# ---------------------------------------------------------------------------


def test_disabled_tool_refuses_the_batch(tmp_path, monkeypatch, capsys, no_spawn):
    """``manifest.disable`` is policy; a task cannot route around it."""
    agent_dir = _write_agent_dir(tmp_path, disable=["shell"])
    tasks = _write_tasks(tmp_path, {"tasks": [
        {"task": "run something", "tools": ["shell"]},
    ]})
    code = _run_cli(monkeypatch, [
        "daemon", "emanate", "--tasks", str(tasks),
        "--agent-dir", str(agent_dir), "--yes",
    ])
    assert code == 1
    err = capsys.readouterr().err
    assert "this agent does not grant" in err
    assert "whole batch is refused" in err
    assert no_spawn == []
    assert not (agent_dir / "daemons").exists()


def test_disabled_tool_refuses_the_whole_batch_including_allowed_siblings(
    tmp_path, monkeypatch, capsys, no_spawn,
):
    agent_dir = _write_agent_dir(tmp_path, disable=["shell"])
    tasks = _write_tasks(tmp_path, {"tasks": [
        {"task": "fine", "tools": ["file"]},
        {"task": "not fine", "tools": ["shell"]},
    ]})
    assert _run_cli(monkeypatch, [
        "daemon", "emanate", "--tasks", str(tasks),
        "--agent-dir", str(agent_dir), "--yes",
    ]) == 1
    assert "tasks[1] requests tool 'shell'" in capsys.readouterr().err
    assert no_spawn == []


def test_disabled_tool_is_refused_before_yes(tmp_path, monkeypatch, capsys, no_spawn):
    agent_dir = _write_agent_dir(tmp_path, disable=["shell"])
    tasks = _write_tasks(tmp_path, {"tasks": [{"task": "x", "tools": ["shell"]}]})
    assert _run_cli(monkeypatch, [
        "daemon", "emanate", "--tasks", str(tasks), "--agent-dir", str(agent_dir),
    ]) == 1
    assert "this agent does not grant" in capsys.readouterr().err
    assert no_spawn == []


def test_engine_also_refuses_a_disabled_tool_when_the_cli_gate_is_bypassed(tmp_path):
    """The CLI gate is defense in depth; the surface itself must fail closed.

    Even calling the dispatcher directly — no CLI gate — a disabled tool is
    never registered on the facade, so ``_build_tool_surface`` refuses.
    """
    from lingtai.cli_daemon import _CliDaemonAgent, _dispatch_through_tool_family

    agent_dir = _write_agent_dir(tmp_path, disable=["shell"])
    agent = _CliDaemonAgent.for_dispatch(agent_dir)
    agent.install_tool_surface({"shell", "file"})

    assert "shell" not in {s.name for s in agent._tool_schemas}
    result = _dispatch_through_tool_family(agent, "emanate", {
        "tasks": [{"task": "x", "tools": ["shell"]}],
        "backend": "lingtai", "max_turns": None, "timeout": None,
    })
    assert result["status"] == "error"
    assert "Unknown tools for emanation" in result["message"]


def test_effective_capabilities_apply_core_defaults_and_disable(tmp_path):
    """The effective set is ``apply_core_defaults``, not the raw manifest."""
    from lingtai.cli_daemon import _CliDaemonAgent

    agent_dir = _write_agent_dir(
        tmp_path, capabilities={"shell": {"yolo": False}}, disable=["vision"],
    )
    granted = _CliDaemonAgent.for_dispatch(agent_dir).effective_capabilities()

    assert "vision" not in granted           # dropped by manifest.disable
    assert "file" in granted                 # core floor, never named in init
    assert granted["shell"] == {"yolo": False}  # authored kwargs win over the floor


def test_authored_capability_kwargs_reach_setup(tmp_path, monkeypatch):
    """A capability is instantiated with the agent's configuration, not defaults."""
    from lingtai.cli_daemon import _CliDaemonAgent
    import lingtai.tools.registry as registry

    agent_dir = _write_agent_dir(tmp_path, capabilities={"shell": {"yolo": False}})
    seen: dict = {}
    real = registry.setup_capability

    def _spy(collector, name, **kwargs):
        seen[name] = kwargs
        return real(collector, name, **kwargs)

    monkeypatch.setattr(registry, "setup_capability", _spy)
    _CliDaemonAgent.for_dispatch(agent_dir).install_tool_surface({"shell"})

    assert seen["shell"] == {"yolo": False}


@pytest.mark.parametrize("tool", ["email", "compact"])
def test_engine_provided_tools_are_not_refused_by_the_capability_gate(
    tmp_path, monkeypatch, capsys, no_spawn, tool,
):
    """The gate must not over-refuse names the engine supplies itself.

    ``email`` is auto-mounted as MCP and ``compact`` comes from the daemon
    intrinsic surface; neither is a capability in ``BUILTIN_TOOLS``, so the
    capability set is not their authority.
    """
    agent_dir = _write_agent_dir(tmp_path)
    tasks = _write_tasks(tmp_path, {"tasks": [{"task": "x", "tools": [tool]}]})
    _run_cli(monkeypatch, [
        "daemon", "emanate", "--tasks", str(tasks), "--agent-dir", str(agent_dir),
    ])
    assert "this agent does not grant" not in capsys.readouterr().err


def test_a_preset_task_is_not_gated_on_the_parent_capability_set(tmp_path, monkeypatch,
                                                                 capsys, no_spawn):
    """A preset brings its own sandbox, so the parent set is not its authority."""
    preset = _write_preset(tmp_path, "cheap", capabilities={"file": {}})
    agent_dir = _write_agent_dir(tmp_path, allowed=[preset], disable=["shell"])
    tasks = _write_tasks(tmp_path, {"tasks": [
        {"task": "x", "tools": ["shell"], "preset": preset},
    ]})
    # Reaches the engine (which owns preset-surface resolution) rather than
    # being refused by the parent-capability gate.
    _run_cli(monkeypatch, [
        "daemon", "emanate", "--tasks", str(tasks), "--agent-dir", str(agent_dir),
    ])
    assert "this agent does not grant" not in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Preset allowlist — fail closed
# ---------------------------------------------------------------------------


def test_disallowed_preset_refuses_the_whole_batch(tmp_path, monkeypatch, capsys, no_spawn):
    """One unauthorized preset refuses every task in the file, not just its own."""
    agent_dir = _write_agent_dir(tmp_path, allowed=[str(tmp_path / "ok.json")])
    tasks = _write_tasks(tmp_path, {"tasks": [
        {"task": "allowed sibling", "tools": ["file"]},
        {"task": "unauthorized", "tools": ["file"], "preset": str(tmp_path / "evil.json")},
    ]})
    code = _run_cli(monkeypatch, [
        "daemon", "emanate", "--tasks", str(tasks),
        "--agent-dir", str(agent_dir), "--yes",
    ])
    assert code == 1
    err = capsys.readouterr().err
    assert "not in this agent's allowed list" in err
    assert "whole batch is refused" in err
    assert no_spawn == []
    assert not (agent_dir / "daemons").exists()


def test_absent_allowlist_fails_closed(tmp_path, monkeypatch, capsys, no_spawn):
    """An agent with no preset block grants no preset."""
    agent_dir = _write_agent_dir(tmp_path)
    tasks = _write_tasks(tmp_path, {"tasks": [
        {"task": "x", "tools": ["file"], "preset": str(tmp_path / "any.json")},
    ]})
    code = _run_cli(monkeypatch, [
        "daemon", "emanate", "--tasks", str(tasks),
        "--agent-dir", str(agent_dir), "--yes",
    ])
    assert code == 1
    assert "not in this agent's allowed list" in capsys.readouterr().err
    assert no_spawn == []


@pytest.mark.parametrize("preset_block", [{}, {"allowed": []}, {"allowed": "oops"}])
def test_malformed_preset_block_fails_closed(tmp_path, monkeypatch, capsys,
                                             no_spawn, preset_block):
    """A malformed preset block is refused by the canonical init reader.

    This used to reach the CLI's own allowlist gate because init.json was read
    with a bare ``json.loads``. Reading through ``read_init`` means the schema
    rejects the block first — an earlier and stricter fail-closed point, but
    still a refusal with no dispatch, which is what matters.
    """
    agent_dir = _write_agent_dir(tmp_path, preset_block=preset_block)
    tasks = _write_tasks(tmp_path, {"tasks": [
        {"task": "x", "tools": ["file"], "preset": str(tmp_path / "any.json")},
    ]})
    code = _run_cli(monkeypatch, [
        "daemon", "emanate", "--tasks", str(tasks),
        "--agent-dir", str(agent_dir), "--yes",
    ])
    assert code == 1
    assert "is not usable" in capsys.readouterr().err
    assert no_spawn == []
    assert not (agent_dir / "daemons").exists()


def test_disallowed_preset_is_refused_before_yes(tmp_path, monkeypatch, capsys, no_spawn):
    """The gate runs at preview time too — a bad batch never looks dispatchable."""
    agent_dir = _write_agent_dir(tmp_path, allowed=[str(tmp_path / "ok.json")])
    tasks = _write_tasks(tmp_path, {"tasks": [
        {"task": "x", "tools": ["file"], "preset": str(tmp_path / "evil.json")},
    ]})
    code = _run_cli(monkeypatch, [
        "daemon", "emanate", "--tasks", str(tasks), "--agent-dir", str(agent_dir),
    ])
    assert code == 1
    assert "not in this agent's allowed list" in capsys.readouterr().err
    assert no_spawn == []


def test_engine_preset_gate_still_runs_when_the_cli_gate_is_bypassed(tmp_path, monkeypatch):
    """The CLI's own check is defense in depth, never the only gate."""
    from lingtai.cli_daemon import _CliDaemonAgent, _dispatch_through_tool_family

    agent_dir = _write_agent_dir(tmp_path, allowed=[str(tmp_path / "ok.json")])
    agent = _CliDaemonAgent.for_dispatch(agent_dir)
    agent.install_tool_surface({"file"})
    result = _dispatch_through_tool_family(agent, "emanate", {
        "tasks": [{"task": "x", "tools": ["file"], "preset": str(tmp_path / "evil.json")}],
        "backend": "lingtai",
        "max_turns": None,
        "timeout": None,
    })
    assert result["status"] == "error"
    assert "not in this agent's allowed list" in result["message"]
    assert not (agent_dir / "daemons").exists()


# ---------------------------------------------------------------------------
# P1-2 regression: dispatch uses the agent's effective config, not raw JSON
# ---------------------------------------------------------------------------


def test_active_preset_model_is_used_not_the_raw_init_llm(tmp_path, monkeypatch,
                                                          capsys, no_spawn):
    """A materialized preset decides the daemon's provider/model.

    Reading init.json with a bare ``json.loads`` skipped active-preset
    materialization, so the daemon launched on the *stale raw* llm block that
    the preset was supposed to replace.
    """
    from lingtai.cli_daemon import _CliDaemonAgent

    active = _write_preset(
        tmp_path, "minimax", provider="minimax", model="effective-model",
    )
    agent_dir = _write_agent_dir(tmp_path, preset_block={
        "active": active, "default": active, "allowed": [active],
    }, extra_manifest={
        "llm": {
            "provider": "anthropic",
            "model": "stale-raw-model",
            "api_key": "raw-key",
            "base_url": None,
        },
    })

    agent = _CliDaemonAgent.for_dispatch(agent_dir)
    assert agent._init_data["manifest"]["llm"]["model"] == "effective-model"
    assert agent._init_data["manifest"]["llm"]["provider"] == "minimax"
    assert agent.service.model == "effective-model"
    assert agent.service.provider == "minimax"

    # And it is the effective model that reaches the run directory.
    tasks = _write_tasks(tmp_path, {"tasks": [{"task": "x", "tools": ["file"]}]})
    assert _run_cli(monkeypatch, [
        "daemon", "emanate", "--tasks", str(tasks),
        "--agent-dir", str(agent_dir), "--yes",
    ]) == 0
    capsys.readouterr()
    state = json.loads(
        (no_spawn[0]["run_dir"].path / "daemon.json").read_text(encoding="utf-8")
    )
    assert state["model"] == "effective-model"


def test_relative_env_file_resolves_under_agent_dir_not_cwd(tmp_path, monkeypatch):
    """``--agent-dir`` is the base for every relative path in init.json.

    ``resolve_paths`` is part of the canonical reader; skipping it meant a
    relative ``env_file`` was loaded from wherever the CLI happened to be
    invoked, so a daemon could boot with another directory's credentials — or
    none at all.
    """
    from lingtai.cli_daemon import _CliDaemonAgent

    agent_dir = _write_agent_dir(tmp_path, env_file="secrets.env", extra_manifest={
        "llm": {
            "provider": "anthropic",
            "model": "m",
            "api_key_env": "CLI_DAEMON_ENV_FILE_PROBE",
            "base_url": None,
        },
    })
    (agent_dir / "secrets.env").write_text(
        "CLI_DAEMON_ENV_FILE_PROBE=from-agent-dir\n", encoding="utf-8",
    )
    # A decoy with the same relative name next to the caller's CWD.
    cwd = tmp_path / "elsewhere"
    cwd.mkdir()
    (cwd / "secrets.env").write_text(
        "CLI_DAEMON_ENV_FILE_PROBE=from-cwd\n", encoding="utf-8",
    )
    monkeypatch.chdir(cwd)
    monkeypatch.delenv("CLI_DAEMON_ENV_FILE_PROBE", raising=False)

    agent = _CliDaemonAgent.for_dispatch(agent_dir)
    assert agent._init_data["env_file"] == str(agent_dir / "secrets.env")
    assert agent.service.api_key == "from-agent-dir"


def test_jsonc_init_is_parsed(tmp_path):
    """The canonical reader accepts JSONC; ``json.loads`` did not."""
    from lingtai.cli_daemon import _CliDaemonAgent

    agent_dir = _write_agent_dir(tmp_path)
    raw = (agent_dir / "init.json").read_text(encoding="utf-8")
    (agent_dir / "init.json").write_text(
        "// the canonical reader tolerates comments\n" + raw, encoding="utf-8",
    )
    assert _CliDaemonAgent.for_dispatch(agent_dir)._config.language == "en"


def test_invalid_init_refuses_dispatch(tmp_path, monkeypatch, capsys, no_spawn):
    """Schema validation now runs; an unusable init.json refuses the batch."""
    agent_dir = _write_agent_dir(tmp_path)
    (agent_dir / "init.json").write_text(
        json.dumps({"manifest": {"agent_name": "x"}}), encoding="utf-8",
    )
    tasks = _write_tasks(tmp_path, {"tasks": [{"task": "x", "tools": ["file"]}]})
    assert _run_cli(monkeypatch, [
        "daemon", "emanate", "--tasks", str(tasks),
        "--agent-dir", str(agent_dir), "--yes",
    ]) == 1
    assert "is not usable" in capsys.readouterr().err
    assert no_spawn == []


def test_reading_effective_config_writes_nothing(tmp_path):
    """Unlike ``cli.load_init``, the CLI never publishes a resolved manifest."""
    from lingtai.cli_daemon import _CliDaemonAgent

    active = _write_preset(tmp_path, "p")
    agent_dir = _write_agent_dir(tmp_path, preset_block={
        "active": active, "default": active, "allowed": [active],
    })
    before = (agent_dir / "init.json").read_bytes()

    _CliDaemonAgent.for_dispatch(agent_dir)

    assert (agent_dir / "init.json").read_bytes() == before
    assert not (agent_dir / "system" / "manifest.resolved.json").exists()


def test_inspection_does_not_require_a_usable_init(tmp_path, monkeypatch, capsys):
    """A broken agent must still be inspectable — refusing to list is backwards."""
    agent_dir = _write_agent_dir(tmp_path)
    _seed_run_dir(agent_dir)
    (agent_dir / "init.json").write_text(
        json.dumps({"manifest": {"agent_name": "broken"}}), encoding="utf-8",
    )
    assert _run_cli(monkeypatch, ["daemon", "list", "--agent-dir", str(agent_dir)]) == 0
    assert "em-1" in capsys.readouterr().out


def test_reclaim_dispatches_through_the_daemon_family(tmp_path, monkeypatch, capsys):
    """CLI reclaim is the tool-family reclaim surface, not a second control path."""
    agent_dir = _write_agent_dir(tmp_path)
    calls: list[tuple[Path, str, dict]] = []

    def fake_dispatch(agent, action, action_input):
        calls.append((agent._working_dir, action, action_input))
        return {"status": "reclaimed", "cancelled": 2}

    monkeypatch.setattr("lingtai.cli_daemon._dispatch_through_tool_family", fake_dispatch)

    assert _run_cli(monkeypatch, [
        "daemon", "reclaim", "--agent-dir", str(agent_dir),
    ]) == 0
    assert calls == [(agent_dir, "reclaim", {})]
    assert json.loads(capsys.readouterr().out) == {"status": "reclaimed", "cancelled": 2}


# ---------------------------------------------------------------------------
# Read-only list / check
# ---------------------------------------------------------------------------


#: A PID that is not this process and is overwhelmingly unlikely to be alive —
#: what a run directory left behind by a since-exited agent looks like.
_DEAD_PARENT_PID = 999_999


def _seed_run_dir(agent_dir: Path, *, handle: str = "em-1",
                  task: str = "seeded task", state: str = "done") -> Path:
    """Create a well-formed daemon run directory through ``DaemonRunDir``.

    Written by the real writer rather than by hand, so ``list``'s legitimate
    lazy repair of malformed/legacy records never fires and a byte-comparison
    can isolate the writes this CLI must not perform.  The record is left
    owned by a dead parent PID with its terminal notification unpublished —
    exactly the two things ``DaemonManager.__init__`` reconciles.
    """
    from lingtai.tools.daemon.run_dir import DaemonRunDir

    run_dir = DaemonRunDir(
        parent_working_dir=agent_dir,
        handle=handle,
        run_id=f"{handle}-20260813-101010-abcdef",
        task=task,
        tools=["file"],
        model="test-model",
        max_turns=5,
        timeout_s=60.0,
        parent_addr=agent_dir.name,
        parent_pid=_DEAD_PARENT_PID,
        system_prompt="prompt",
        backend="lingtai",
    )
    if state != "running":
        run_dir.update_state(state=state, finished_at="2026-08-13T10:11:10Z")
    return run_dir.path


def test_list_prints_a_status_table(tmp_path, monkeypatch, capsys):
    agent_dir = _write_agent_dir(tmp_path)
    _seed_run_dir(agent_dir)
    assert _run_cli(monkeypatch, ["daemon", "list", "--agent-dir", str(agent_dir)]) == 0
    out = capsys.readouterr().out
    assert "STATUS" in out and "TASK" in out
    assert "em-1" in out
    assert "seeded task" in out


def test_list_status_filter(tmp_path, monkeypatch, capsys):
    agent_dir = _write_agent_dir(tmp_path)
    _seed_run_dir(agent_dir)
    assert _run_cli(monkeypatch, [
        "daemon", "list", "--status", "running", "--agent-dir", str(agent_dir),
    ]) == 0
    assert "no daemon runs" in capsys.readouterr().out


@pytest.mark.parametrize("argv", [
    ["daemon", "list"],
    ["daemon", "check", "em-1"],
])
def test_list_and_check_write_nothing(tmp_path, monkeypatch, capsys, argv):
    """A stale, unnotified record must survive inspection byte-for-byte."""
    agent_dir = _write_agent_dir(tmp_path)
    run_path = _seed_run_dir(agent_dir, state="running")
    before = (run_path / "daemon.json").read_bytes()

    assert _run_cli(monkeypatch, [*argv, "--agent-dir", str(agent_dir)]) == 0
    capsys.readouterr()

    assert (run_path / "daemon.json").read_bytes() == before
    assert not (agent_dir / ".notification").exists()


def test_a_full_manager_would_have_rewritten_that_record(tmp_path):
    """Positive control: the reconciliation the read-only view skips is real.

    Without this, ``test_list_and_check_write_nothing`` could pass simply
    because nothing ever reconciles stale records.
    """
    from lingtai.tools.daemon import DaemonManager
    from lingtai.cli_daemon import _CliDaemonAgent

    agent_dir = _write_agent_dir(tmp_path)
    run_path = _seed_run_dir(agent_dir, state="running")
    before = (run_path / "daemon.json").read_bytes()

    DaemonManager(_CliDaemonAgent.for_dispatch(agent_dir))

    after = json.loads((run_path / "daemon.json").read_text(encoding="utf-8"))
    assert (run_path / "daemon.json").read_bytes() != before
    assert after["state"] == "failed"


def test_check_prints_a_snapshot(tmp_path, monkeypatch, capsys):
    agent_dir = _write_agent_dir(tmp_path)
    run_path = _seed_run_dir(agent_dir)
    assert _run_cli(monkeypatch, [
        "daemon", "check", "em-1", "--agent-dir", str(agent_dir),
    ]) == 0
    snapshot = json.loads(capsys.readouterr().out)
    assert snapshot["id"] == "em-1"
    assert snapshot["state"] == "done"
    assert snapshot["path"] == str(run_path)


def test_check_unknown_id_exits_nonzero(tmp_path, monkeypatch, capsys):
    agent_dir = _write_agent_dir(tmp_path)
    code = _run_cli(monkeypatch, [
        "daemon", "check", "em-404", "--agent-dir", str(agent_dir),
    ])
    assert code == 1
    assert json.loads(capsys.readouterr().out)["status"] == "error"


# ---------------------------------------------------------------------------
# P1-4 regression: inspection never rewrites durable state, whatever its shape
#
# The engine's ``_load_or_rebuild_daemon_state`` self-heals a daemon.json that
# is missing, unparseable, or stamped with an older data_version. That repair
# belongs to the owning agent; a CLI must observe without mutating.
# ---------------------------------------------------------------------------


def _damage(run_path: Path, kind: str) -> None:
    """Put a run directory into one of the three would-be-rebuild shapes."""
    daemon_json = run_path / "daemon.json"
    if kind == "missing":
        daemon_json.unlink()
    elif kind == "unparseable":
        daemon_json.write_text("{not json", encoding="utf-8")
    elif kind == "stale_version":
        state = json.loads(daemon_json.read_text(encoding="utf-8"))
        state["data_version"] = 0
        daemon_json.write_text(json.dumps(state), encoding="utf-8")
    else:  # pragma: no cover - guards the parametrization
        raise AssertionError(kind)


@pytest.mark.parametrize("kind", ["missing", "unparseable", "stale_version"])
@pytest.mark.parametrize("argv", [["daemon", "list"], ["daemon", "check", "em-1"]])
def test_inspection_never_repairs_damaged_durable_state(tmp_path, monkeypatch, capsys,
                                                        kind, argv):
    agent_dir = _write_agent_dir(tmp_path)
    run_path = _seed_run_dir(agent_dir)
    _damage(run_path, kind)
    daemon_json = run_path / "daemon.json"
    existed = daemon_json.exists()
    before = daemon_json.read_bytes() if existed else None

    _run_cli(monkeypatch, [*argv, "--agent-dir", str(agent_dir)])
    capsys.readouterr()

    assert daemon_json.exists() is existed, "inspection created daemon.json"
    if existed:
        assert daemon_json.read_bytes() == before, "inspection rewrote daemon.json"


@pytest.mark.parametrize("kind", ["missing", "unparseable", "stale_version"])
def test_list_still_shows_a_damaged_run_and_says_it_needs_rebuild(tmp_path, monkeypatch,
                                                                  capsys, kind):
    """Not repairing must not mean silently dropping the row, or lying about it."""
    agent_dir = _write_agent_dir(tmp_path)
    run_path = _seed_run_dir(agent_dir)
    _damage(run_path, kind)

    assert _run_cli(monkeypatch, ["daemon", "list", "--agent-dir", str(agent_dir)]) == 0
    captured = capsys.readouterr()

    assert run_path.name.split("-2026")[0] in captured.out  # the row is still listed
    assert "NOT repaired on disk" in captured.err
    assert "read-only" in captured.err


@pytest.mark.parametrize("kind", ["missing", "unparseable", "stale_version"])
def test_a_full_manager_would_have_repaired_the_damaged_record(tmp_path, kind):
    """Positive control for the lazy-repair path the read-only view overrides."""
    from lingtai.tools.daemon import DaemonManager
    from lingtai.cli_daemon import _CliDaemonAgent

    agent_dir = _write_agent_dir(tmp_path)
    run_path = _seed_run_dir(agent_dir)
    _damage(run_path, kind)

    manager = DaemonManager(_CliDaemonAgent.for_dispatch(agent_dir))
    manager._handle_list()

    from lingtai.tools.daemon.run_dir import DaemonRunDir

    repaired = json.loads((run_path / "daemon.json").read_text(encoding="utf-8"))
    assert repaired["data_version"] == DaemonRunDir.DATA_VERSION
    assert repaired["migration"]["source"] == "daemon_list_best_effort"


def test_read_only_view_records_which_runs_need_rebuild(tmp_path):
    """The needs-rebuild set is what the CLI reports instead of repairing."""
    from lingtai.cli_daemon import _CliDaemonAgent, _ReadOnlyDaemonView

    agent_dir = _write_agent_dir(tmp_path)
    healthy = _seed_run_dir(agent_dir, handle="em-1")
    damaged = _seed_run_dir(agent_dir, handle="em-2")
    _damage(damaged, "stale_version")

    view = _ReadOnlyDaemonView(_CliDaemonAgent.for_inspection(agent_dir))
    result = view._handle_list()

    assert view.needs_rebuild == [damaged.name]
    assert healthy.name not in view.needs_rebuild
    # Both runs are still reported, the damaged one from reconstruction.
    assert {e["run_id"] for e in result["emanations"]} == {healthy.name, damaged.name}


# ---------------------------------------------------------------------------
# Secret hygiene
# ---------------------------------------------------------------------------


def test_backend_options_env_values_are_redacted_from_output(tmp_path, monkeypatch,
                                                             capsys, no_spawn):
    agent_dir = _write_agent_dir(tmp_path)
    tasks = _write_tasks(tmp_path, {
        "tasks": [{
            "task": "x",
            "tools": ["file"],
            "backend_options": {"env": {"CLAUDE_CONFIG_DIR": "s3cr3t-value"}},
        }],
        "backend": "claude-p",
    })
    assert _run_cli(monkeypatch, [
        "daemon", "emanate", "--tasks", str(tasks), "--agent-dir", str(agent_dir),
    ]) == 0
    out = capsys.readouterr().out
    assert "s3cr3t-value" not in out


def test_redaction_keeps_explicit_nulls_in_the_printed_shape():
    """A script reading `check` output must see null, not a missing key."""
    from lingtai.cli_daemon import _redact_preserving_nulls

    assert _redact_preserving_nulls({
        "result_path": None,
        "current_tool": None,
        "state": "done",
        "env": {"TOKEN": "s3cr3t"},
        "events": [{"detail": None, "event": "daemon_done"}],
    }) == {
        "result_path": None,
        "current_tool": None,
        "state": "done",
        "env": {"TOKEN": "<redacted>"},
        "events": [{"detail": None, "event": "daemon_done"}],
    }


# ---------------------------------------------------------------------------
# Facade
# ---------------------------------------------------------------------------


def test_facade_takes_no_lease_and_writes_no_agent_identity(tmp_path):
    """The facade must never look like a second agent in the working dir."""
    from lingtai.cli_daemon import _CliDaemonAgent

    agent_dir = _write_agent_dir(tmp_path)
    agent = _CliDaemonAgent.for_dispatch(agent_dir)
    agent.install_tool_surface({"file"})

    assert {s.name for s in agent._tool_schemas} == {"file"}
    assert agent._config.language == "en"
    assert not (agent_dir / ".agent.heartbeat").exists()
    assert not (agent_dir / ".agent.lock").exists()
    assert not (agent_dir / ".agent.json").exists()


def test_facade_reads_the_sanitized_preset_allowlist(tmp_path):
    """``_read_preset_from_init`` is the live Agent's implementation, not a copy."""
    from lingtai.agent import Agent
    from lingtai.cli_daemon import _CliDaemonAgent

    home = _write_preset(tmp_path, "home")
    agent_dir = _write_agent_dir(tmp_path, preset_block={
        "allowed": [home, 7],
        "active": home,
        "default": home,
        "secret": "must-not-survive",
    })
    agent = _CliDaemonAgent.for_inspection(agent_dir)
    assert _CliDaemonAgent._read_preset_from_init is Agent._read_preset_from_init
    assert agent._read_preset_from_init() == {
        "allowed": [home], "active": home, "default": home,
    }


def test_facade_refuses_to_publish_terminal_notifications(tmp_path):
    """A CLI publish must fail so the pending receipt survives for the agent."""
    from lingtai.cli_daemon import _CliDaemonAgent, _ReadOnlyDaemonView

    agent_dir = _write_agent_dir(tmp_path)
    run_path = _seed_run_dir(agent_dir)
    agent = _CliDaemonAgent.for_dispatch(agent_dir)
    view = _ReadOnlyDaemonView(agent)

    published = view._publish_daemon_notification(
        "em-1", status="done", text="body", run_path=run_path,
        run_state=json.loads((run_path / "daemon.json").read_text(encoding="utf-8")),
        idempotency_key="k",
    )
    assert published is False


def test_facade_service_is_lazy(tmp_path):
    """`list`/`check` must work with no resolvable credential."""
    from lingtai.cli_daemon import _CliDaemonAgent

    env_file = tmp_path / "agent.env"
    env_file.write_text("OTHER=1\n", encoding="utf-8")
    agent_dir = _write_agent_dir(tmp_path, env_file=str(env_file), extra_manifest={
        "llm": {
            "provider": "anthropic",
            "model": "m",
            "api_key_env": "NOPE_MISSING_CLI_DAEMON_KEY",
            "base_url": None,
        },
    })

    agent = _CliDaemonAgent.for_dispatch(agent_dir)
    assert agent._working_dir == agent_dir  # construction touched no credential
    with pytest.raises(ValueError):
        _ = agent.service


# ---------------------------------------------------------------------------
# Docs / description hint
# ---------------------------------------------------------------------------


def test_daemon_tool_description_points_programmatic_callers_at_the_cli():
    from lingtai.tools.daemon import get_description

    assert "lingtai-agent daemon" in get_description()


def test_daemon_manual_documents_the_cli():
    manual = (
        Path(__file__).resolve().parents[1]
        / "src/lingtai/tools/daemon/manual/SKILL.md"
    ).read_text(encoding="utf-8")
    assert "## Programmatic use / CLI" in manual
    assert "lingtai-agent daemon emanate" in manual


# ---------------------------------------------------------------------------
# run-sync — one prompt in, one result out
#
# The engine is untouched by this action, so these pin the composition: that
# the request is held to the same schema/gates as a tasks file, that the wait
# is the read-only check binding, and what each terminal state prints and exits.
# ---------------------------------------------------------------------------


def _parse_daemon_args(argv: list[str]):
    """Parse an argv through the real ``daemon`` parser tree, without running it."""
    import argparse

    from lingtai.cli_daemon import add_daemon_parser

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    add_daemon_parser(sub)
    return parser.parse_args(argv)


@pytest.fixture
def stub_clock(monkeypatch):
    """Replace ``cli_daemon``'s ``time`` with a clock only its poll loop drives.

    Scoped to the module attribute rather than the ``time`` module so the
    engine's own timestamps stay real, and so a wall-clock-ceiling test costs
    no wall clock: ``sleep`` advances the same counter ``monotonic`` reads.
    """
    from lingtai import cli_daemon

    class _Clock:
        def __init__(self) -> None:
            self.now = 0.0
            self.slept: list[float] = []

        def monotonic(self) -> float:
            return self.now

        def sleep(self, seconds: float) -> None:
            self.slept.append(seconds)
            self.now += seconds

    clock = _Clock()
    monkeypatch.setattr(cli_daemon, "time", clock)
    return clock


@pytest.fixture
def finishing_spawn(monkeypatch):
    """Spawn replaced by an immediate terminal transition on the real run dir.

    Everything before the process boundary stays live (validation, gates, run
    directory, prompt build) exactly as ``no_spawn`` leaves it; this fixture
    additionally drives the run dir to a terminal state through ``DaemonRunDir``'s
    own writers, so ``run-sync``'s poll observes the same ``daemon.json`` /
    ``result.txt`` / ``events.jsonl`` a real detached run would have written.
    Set ``outcome["state"] = "running"`` to model a run that never finishes.
    """
    from lingtai.tools.daemon import DaemonManager

    outcome = {"state": "done", "text": "the daemon's answer"}
    spawns: list[dict] = []

    def _record(self, run_dir, **kwargs):
        spawns.append({"run_dir": run_dir, **kwargs})
        if outcome["state"] == "done":
            run_dir.mark_done(outcome["text"])
        elif outcome["state"] == "failed":
            run_dir.mark_failed(RuntimeError(outcome["text"]))
        elif outcome["state"] == "cancelled":
            run_dir.mark_cancelled()

    monkeypatch.setattr(DaemonManager, "_spawn_detached_lingtai_run", _record)
    outcome["spawns"] = spawns
    return outcome


def _run_sync(monkeypatch, agent_dir: Path, prompt: str = "answer me",
              *extra: str) -> int:
    return _run_cli(monkeypatch, [
        "daemon", "run-sync", prompt, "--agent-dir", str(agent_dir),
        "--tools", "file", "--poll-interval", "0.01", *extra,
    ])


# -- argparse wiring --------------------------------------------------------


def test_run_sync_argparse_defaults():
    args = _parse_daemon_args(["daemon", "run-sync", "do a thing",
                               "--agent-dir", "/tmp/agent"])
    assert args.daemon_command == "run-sync"
    assert args.prompt == "do a thing"
    assert args.agent_dir == Path("/tmp/agent")
    assert args.tools is None and args.preset is None
    assert args.max_turns is None and args.timeout is None
    assert args.poll_interval == 2.0
    assert args.output_format == "text"
    assert args.stream is False


def test_run_sync_argparse_flags():
    args = _parse_daemon_args([
        "daemon", "run-sync", "p", "--agent-dir", "/tmp/a",
        "--tools", "file,shell", "--preset", "/p.json", "--max-turns", "7",
        "--timeout", "30", "--poll-interval", "0.5",
        "--output-format", "json", "--stream",
    ])
    assert args.tools == "file,shell" and args.preset == "/p.json"
    assert args.max_turns == 7 and args.timeout == 30.0
    assert args.poll_interval == 0.5
    assert args.output_format == "json" and args.stream is True


def test_run_sync_requires_an_agent_dir():
    with pytest.raises(SystemExit):
        _parse_daemon_args(["daemon", "run-sync", "p"])


def test_run_sync_rejects_an_unknown_output_format():
    with pytest.raises(SystemExit):
        _parse_daemon_args(["daemon", "run-sync", "p", "--agent-dir", "/tmp/a",
                            "--output-format", "yaml"])


def test_run_sync_is_registered_as_a_handler():
    from lingtai.cli_daemon import _HANDLERS, _handle_run_sync

    assert _HANDLERS["run-sync"] is _handle_run_sync


# -- preset selection: flag beats env, env beats nothing --------------------


@pytest.mark.parametrize("flag,env,expected", [
    ("/flag.json", None, "/flag.json"),
    (None, "/env.json", "/env.json"),
    ("/flag.json", "/env.json", "/flag.json"),  # the flag wins
    (None, None, None),                          # neither: inherit
    (None, "   ", None),                         # a blank env var is not a preset
])
def test_run_sync_preset_priority(monkeypatch, flag, env, expected):
    import argparse

    from lingtai.cli_daemon import _RUN_SYNC_PRESET_ENV, _resolve_run_sync_preset

    if env is None:
        monkeypatch.delenv(_RUN_SYNC_PRESET_ENV, raising=False)
    else:
        monkeypatch.setenv(_RUN_SYNC_PRESET_ENV, env)
    assert _resolve_run_sync_preset(argparse.Namespace(preset=flag)) == expected


def test_run_sync_env_preset_reaches_the_dispatched_task(tmp_path, monkeypatch,
                                                         capsys, no_spawn):
    """``LINGTAI_P_PRESET`` is a real default, not just a resolved string."""
    from lingtai.cli_daemon import _RUN_SYNC_PRESET_ENV

    allowed = _write_preset(tmp_path, "cheap")
    agent_dir = _write_agent_dir(tmp_path, allowed=[allowed])
    monkeypatch.setenv(_RUN_SYNC_PRESET_ENV, allowed)

    captured: list[dict] = []

    def fake_dispatch(agent, action, action_input):
        captured.append({"action": action, "input": action_input})
        return {"status": "error", "message": "stopped after capture"}

    monkeypatch.setattr("lingtai.cli_daemon._dispatch_through_tool_family", fake_dispatch)

    assert _run_sync(monkeypatch, agent_dir) == 1
    capsys.readouterr()
    assert captured[0]["action"] == "emanate"
    assert captured[0]["input"]["tasks"][0]["preset"] == allowed


def test_run_sync_omits_preset_entirely_when_none_is_selected(tmp_path, monkeypatch,
                                                              capsys, no_spawn):
    """Omission — not ``null`` — is the engine's existing inherit-the-parent path."""
    from lingtai.cli_daemon import _RUN_SYNC_PRESET_ENV

    monkeypatch.delenv(_RUN_SYNC_PRESET_ENV, raising=False)
    agent_dir = _write_agent_dir(tmp_path)
    captured: list[dict] = []

    def fake_dispatch(agent, action, action_input):
        captured.append(action_input)
        return {"status": "error", "message": "stopped after capture"}

    monkeypatch.setattr("lingtai.cli_daemon._dispatch_through_tool_family", fake_dispatch)

    assert _run_sync(monkeypatch, agent_dir) == 1
    capsys.readouterr()
    assert "preset" not in captured[0]["tasks"][0]


# -- default tool surface ---------------------------------------------------


def test_run_sync_default_tools_are_the_granted_host_floor(tmp_path):
    """The default is the one surface reachable with *and* without a preset."""
    from lingtai.cli_daemon import _CliDaemonAgent, _default_run_sync_tools
    from lingtai.tools.daemon import _parent_host_tool_floor

    agent_dir = _write_agent_dir(tmp_path)
    agent = _CliDaemonAgent.for_dispatch(agent_dir)
    tools = _default_run_sync_tools(agent)

    assert set(tools) == set(agent.effective_capabilities()) & _parent_host_tool_floor()
    assert "file" in tools and "shell" in tools
    # Only what actually registered is requested, so a capability whose setup
    # was skipped cannot turn an implicit default into "Unknown tools".
    assert set(tools) == {s.name for s in agent._tool_schemas}


def test_run_sync_default_tools_respect_manifest_disable(tmp_path):
    """An implicit default must not hand back a capability the agent disabled."""
    from lingtai.cli_daemon import _CliDaemonAgent, _default_run_sync_tools

    agent_dir = _write_agent_dir(tmp_path, disable=["shell"])
    tools = _default_run_sync_tools(_CliDaemonAgent.for_dispatch(agent_dir))

    assert "shell" not in tools
    assert "file" in tools


def test_run_sync_default_tools_reach_the_dispatched_task(tmp_path, monkeypatch,
                                                          capsys, no_spawn):
    """Omitting ``--tools`` is a real default, not an empty ``tools`` list."""
    agent_dir = _write_agent_dir(tmp_path)
    captured: list[dict] = []

    def fake_dispatch(agent, action, action_input):
        captured.append(action_input)
        return {"status": "error", "message": "stopped after capture"}

    monkeypatch.setattr("lingtai.cli_daemon._dispatch_through_tool_family", fake_dispatch)

    assert _run_cli(monkeypatch, [
        "daemon", "run-sync", "x", "--agent-dir", str(agent_dir),
        "--poll-interval", "0.01",
    ]) == 1
    capsys.readouterr()
    assert "file" in captured[0]["tasks"][0]["tools"]


@pytest.mark.parametrize("raw,expected", [
    (None, None),
    ("", []),
    ("file", ["file"]),
    (" file , shell ,", ["file", "shell"]),
])
def test_run_sync_tools_flag_parsing(raw, expected):
    from lingtai.cli_daemon import _parse_tools_flag

    assert _parse_tools_flag(raw) == expected


# -- blocking poll to a terminal state --------------------------------------


def test_run_sync_blocks_until_done_and_prints_only_the_result(
        tmp_path, monkeypatch, capsys, finishing_spawn, stub_clock):
    agent_dir = _write_agent_dir(tmp_path)
    assert _run_sync(monkeypatch, agent_dir, "summarize the docs") == 0

    captured = capsys.readouterr()
    assert captured.out == "the daemon's answer\n"
    assert captured.err == ""
    assert finishing_spawn["spawns"], "the dispatch never reached the engine"


def test_run_sync_waits_for_a_run_that_is_not_terminal_yet(
        tmp_path, monkeypatch, capsys, finishing_spawn, stub_clock):
    """The loop must poll again rather than report the first non-terminal read."""
    from lingtai.tools.daemon import DaemonManager

    finishing_spawn["state"] = "running"
    agent_dir = _write_agent_dir(tmp_path)

    real_check = DaemonManager._handle_check
    calls: list[str] = []

    def finishing_check(self, em_id, *args, **kwargs):
        calls.append(em_id)
        if len(calls) == 3:  # the run finishes between the second and third poll
            finishing_spawn["spawns"][0]["run_dir"].mark_done("late answer")
        return real_check(self, em_id, *args, **kwargs)

    monkeypatch.setattr(DaemonManager, "_handle_check", finishing_check)

    assert _run_sync(monkeypatch, agent_dir) == 0
    assert capsys.readouterr().out == "late answer\n"
    assert len(calls) == 3
    assert stub_clock.slept == [0.01, 0.01]


def test_run_sync_polls_the_read_only_check_binding(
        tmp_path, monkeypatch, capsys, finishing_spawn, stub_clock):
    """Waiting must not reconcile, repair, or reap — it is the `check` surface.

    ``_ReadOnlyDaemonView`` binds the manager's own unmodified ``_handle_check``
    through ``__getattr__``, so spying on the manager unit is what proves *who*
    the poll loop called it as.
    """
    from lingtai.cli_daemon import _ReadOnlyDaemonView
    from lingtai.tools.daemon import DaemonManager

    agent_dir = _write_agent_dir(tmp_path)
    seen: list[object] = []
    real_check = DaemonManager._handle_check

    def spy(self, em_id, *args, **kwargs):
        seen.append(type(self))
        return real_check(self, em_id, *args, **kwargs)

    monkeypatch.setattr(DaemonManager, "_handle_check", spy)

    assert _run_sync(monkeypatch, agent_dir) == 0
    capsys.readouterr()
    assert seen and set(seen) == {_ReadOnlyDaemonView}
    assert not (agent_dir / ".notification").exists()


def test_run_sync_json_output_carries_the_whole_envelope(
        tmp_path, monkeypatch, capsys, finishing_spawn, stub_clock):
    agent_dir = _write_agent_dir(tmp_path)
    assert _run_sync(monkeypatch, agent_dir, "answer me",
                     "--output-format", "json") == 0

    payload = json.loads(capsys.readouterr().out)
    run_dir = finishing_spawn["spawns"][0]["run_dir"]
    assert payload["status"] == "done"
    assert payload["result"] == "the daemon's answer"
    assert payload["id"] == run_dir.path.name
    assert payload["agent_dir"] == str(agent_dir)
    assert payload["tools"] == ["file"]
    assert payload["preset"] is None
    assert payload["gave_up_waiting"] is False
    assert payload["path"] == str(run_dir.path)
    assert Path(payload["result_path"]).read_text(encoding="utf-8") == \
        "the daemon's answer"


def test_run_sync_reads_the_full_result_not_the_bounded_preview(
        tmp_path, monkeypatch, capsys, finishing_spawn, stub_clock):
    """``result_preview`` in daemon.json is capped; ``result.txt`` is the answer."""
    from lingtai.tools.daemon.run_dir import DaemonRunDir

    long_answer = "x" * (DaemonRunDir._RESULT_PREVIEW_MAX + 500)
    finishing_spawn["text"] = long_answer
    agent_dir = _write_agent_dir(tmp_path)

    assert _run_sync(monkeypatch, agent_dir) == 0
    assert capsys.readouterr().out == long_answer + "\n"


# -- non-zero exits ---------------------------------------------------------


@pytest.mark.parametrize("state", ["failed", "cancelled"])
def test_run_sync_exits_nonzero_on_a_non_done_terminal_state(
        tmp_path, monkeypatch, capsys, finishing_spawn, stub_clock, state):
    finishing_spawn["state"] = state
    finishing_spawn["text"] = "the daemon blew up"
    agent_dir = _write_agent_dir(tmp_path)

    assert _run_sync(monkeypatch, agent_dir) == 1
    captured = capsys.readouterr()
    assert f"finished {state}" in captured.err


def test_run_sync_gives_up_at_the_wall_clock_ceiling(
        tmp_path, monkeypatch, capsys, finishing_spawn, stub_clock):
    """``--timeout`` bounds the command; the daemon keeps its own watchdog."""
    finishing_spawn["state"] = "running"
    agent_dir = _write_agent_dir(tmp_path)

    code = _run_sync(monkeypatch, agent_dir, "answer me", "--timeout", "10")
    assert code == 1
    err = capsys.readouterr().err
    assert "gave up waiting after --timeout 10.0s" in err
    assert "daemon check" in err and "reclaim" in err
    assert stub_clock.now >= 10.0

    # The run itself was never marked terminal by the CLI.
    state = json.loads(
        (finishing_spawn["spawns"][0]["run_dir"].path / "daemon.json")
        .read_text(encoding="utf-8")
    )
    assert state["state"] == "running"


def test_run_sync_timeout_reports_status_timeout_in_json(
        tmp_path, monkeypatch, capsys, finishing_spawn, stub_clock):
    finishing_spawn["state"] = "running"
    agent_dir = _write_agent_dir(tmp_path)

    assert _run_sync(monkeypatch, agent_dir, "answer me",
                     "--timeout", "10", "--output-format", "json") == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "timeout"
    assert payload["gave_up_waiting"] is True


def test_run_sync_passes_timeout_through_as_the_daemon_watchdog(
        tmp_path, monkeypatch, capsys, no_spawn):
    """One flag, both roles: the engine gets it too, not just the poll loop."""
    agent_dir = _write_agent_dir(tmp_path)
    captured: list[dict] = []

    def fake_dispatch(agent, action, action_input):
        captured.append(action_input)
        return {"status": "error", "message": "stopped after capture"}

    monkeypatch.setattr("lingtai.cli_daemon._dispatch_through_tool_family", fake_dispatch)

    assert _run_sync(monkeypatch, agent_dir, "answer me",
                     "--timeout", "45", "--max-turns", "3") == 1
    capsys.readouterr()
    assert captured[0]["timeout"] == 45.0
    assert captured[0]["max_turns"] == 3
    assert captured[0]["backend"] is None


def test_run_sync_refuses_a_non_positive_poll_interval(tmp_path, monkeypatch,
                                                       capsys, no_spawn):
    agent_dir = _write_agent_dir(tmp_path)
    code = _run_cli(monkeypatch, [
        "daemon", "run-sync", "x", "--agent-dir", str(agent_dir),
        "--tools", "file", "--poll-interval", "0",
    ])
    assert code == 1
    assert "--poll-interval must be > 0" in capsys.readouterr().err
    assert no_spawn == []


# -- the same validation and gates as a tasks file --------------------------


@pytest.mark.parametrize("extra,fragment", [
    (["--max-turns", "0"], "max_turns must be >= 1"),
    (["--timeout", "1"], "timeout must be >= 5"),
])
def test_run_sync_is_held_to_the_emanate_schema(tmp_path, monkeypatch, capsys,
                                                no_spawn, extra, fragment):
    """The in-memory request meets the same schema a ``--tasks`` file meets."""
    agent_dir = _write_agent_dir(tmp_path)
    assert _run_sync(monkeypatch, agent_dir, "x", *extra) == 1
    err = capsys.readouterr().err
    assert fragment in err
    assert "run-sync does not match the daemon emanate schema" in err
    assert "--tasks file" not in err  # it was never given one
    assert no_spawn == []


def test_run_sync_refuses_an_empty_prompt(tmp_path, monkeypatch, capsys, no_spawn):
    agent_dir = _write_agent_dir(tmp_path)
    assert _run_sync(monkeypatch, agent_dir, "   ") == 1
    assert "must be a non-empty string" in capsys.readouterr().err
    assert no_spawn == []


def test_run_sync_refuses_a_preset_outside_the_allowlist(tmp_path, monkeypatch,
                                                         capsys, no_spawn):
    agent_dir = _write_agent_dir(tmp_path, allowed=[str(tmp_path / "ok.json")])
    code = _run_sync(monkeypatch, agent_dir, "x",
                     "--preset", str(tmp_path / "evil.json"))
    assert code == 1
    assert "not in this agent's allowed list" in capsys.readouterr().err
    assert no_spawn == []
    assert not (agent_dir / "daemons").exists()


def test_run_sync_refuses_a_capability_the_agent_disabled(tmp_path, monkeypatch,
                                                          capsys, no_spawn):
    agent_dir = _write_agent_dir(tmp_path, disable=["shell"])
    code = _run_cli(monkeypatch, [
        "daemon", "run-sync", "x", "--agent-dir", str(agent_dir),
        "--tools", "shell", "--poll-interval", "0.01",
    ])
    assert code == 1
    assert "does not grant" in capsys.readouterr().err
    assert no_spawn == []


def test_run_sync_refuses_an_unusable_init(tmp_path, monkeypatch, capsys, no_spawn):
    agent_dir = _write_agent_dir(tmp_path)
    (agent_dir / "init.json").write_text(
        json.dumps({"manifest": {"agent_name": "x"}}), encoding="utf-8",
    )
    assert _run_sync(monkeypatch, agent_dir) == 1
    assert "is not usable" in capsys.readouterr().err
    assert no_spawn == []


# -- --stream tail ----------------------------------------------------------


def test_event_tail_returns_only_new_complete_lines(tmp_path):
    """A line still mid-write is held back, and nothing is replayed."""
    from lingtai.cli_daemon import _EventTail

    events = tmp_path / "events.jsonl"
    events.write_text('{"event": "a"}\n{"event": "b"}\n', encoding="utf-8")
    tail = _EventTail(events)

    assert [e["event"] for e in tail.drain()] == ["a", "b"]
    assert tail.drain() == []

    # A partial line: not an event until its newline lands.
    with open(events, "a", encoding="utf-8") as handle:
        handle.write('{"event": "c"}')
    assert tail.drain() == []
    with open(events, "a", encoding="utf-8") as handle:
        handle.write('\n{"event": "d"}\n')
    assert [e["event"] for e in tail.drain()] == ["c", "d"]


def test_event_tail_survives_a_missing_file_and_bad_lines(tmp_path):
    from lingtai.cli_daemon import _EventTail

    events = tmp_path / "events.jsonl"
    tail = _EventTail(events)
    assert tail.drain() == []  # not created yet

    events.write_text('not json\n\n{"event": "ok"}\n"scalar"\n', encoding="utf-8")
    assert [e["event"] for e in tail.drain()] == ["ok"]


def test_event_tail_resumes_after_the_file_is_replaced(tmp_path):
    from lingtai.cli_daemon import _EventTail

    events = tmp_path / "events.jsonl"
    events.write_text('{"event": "old"}\n' * 3, encoding="utf-8")
    tail = _EventTail(events)
    tail.drain()

    events.write_text('{"event": "new"}\n', encoding="utf-8")  # shorter than before
    assert [e["event"] for e in tail.drain()] == ["new"]


def test_stream_event_lines_are_compact_and_redacted():
    from lingtai.cli_daemon import _format_stream_event

    line = _format_stream_event({
        "event": "tool_call", "name": "file", "turn": 2,
        "args_preview": '{"action": "read",\n  "path": "notes.md"}',
        "ts": "2026-08-20T00:00:00Z",
    })
    assert line.startswith("· tool_call name=file turn=2")
    assert "\n" not in line

    secret = _format_stream_event({
        "event": "mcp_start", "env": {"TOKEN": "s3cr3t-value"},
    })
    assert "s3cr3t-value" not in secret


def test_run_sync_stream_tails_events_to_stderr(
        tmp_path, monkeypatch, capsys, finishing_spawn, stub_clock):
    """The tail is over the run's own events.jsonl, and stdout stays the result."""
    agent_dir = _write_agent_dir(tmp_path)
    assert _run_sync(monkeypatch, agent_dir, "answer me", "--stream") == 0

    captured = capsys.readouterr()
    assert captured.out == "the daemon's answer\n"
    # Written by DaemonRunDir itself: construction, then the terminal transition.
    assert "· daemon_start" in captured.err
    assert "· daemon_done" in captured.err


def test_run_sync_without_stream_prints_no_events(
        tmp_path, monkeypatch, capsys, finishing_spawn, stub_clock):
    agent_dir = _write_agent_dir(tmp_path)
    assert _run_sync(monkeypatch, agent_dir) == 0
    assert "daemon_start" not in capsys.readouterr().err


def test_run_sync_stream_does_not_replay_events_across_polls(
        tmp_path, monkeypatch, capsys, finishing_spawn, stub_clock):
    """Each event is printed once, however many polls the wait takes."""
    from lingtai.tools.daemon import DaemonManager

    finishing_spawn["state"] = "running"
    agent_dir = _write_agent_dir(tmp_path)

    real_check = DaemonManager._handle_check
    polls: list[int] = []

    def finishing_check(self, em_id, *args, **kwargs):
        polls.append(1)
        if len(polls) == 4:
            finishing_spawn["spawns"][0]["run_dir"].mark_done("done at last")
        return real_check(self, em_id, *args, **kwargs)

    monkeypatch.setattr(DaemonManager, "_handle_check", finishing_check)

    assert _run_sync(monkeypatch, agent_dir, "answer me", "--stream") == 0
    err = capsys.readouterr().err
    assert err.count("· daemon_start") == 1
    assert err.count("· daemon_done") == 1


# -- documentation ----------------------------------------------------------


def test_daemon_manual_documents_run_sync():
    manual = (
        Path(__file__).resolve().parents[1]
        / "src/lingtai/tools/daemon/manual/SKILL.md"
    ).read_text(encoding="utf-8")
    assert "lingtai-agent daemon run-sync" in manual
