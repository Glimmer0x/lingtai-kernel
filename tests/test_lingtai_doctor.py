"""Tests for the intrinsic lingtai-doctor script."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import typing
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCTOR = ROOT / "src" / "lingtai" / "intrinsic_skills" / "lingtai-doctor" / "scripts" / "doctor.py"


def load_doctor_module():
    spec = importlib.util.spec_from_file_location("lingtai_doctor", DOCTOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _valid_tombstone(*, cleared=None, pending=None) -> dict:
    return {
        "version": 1, "epoch": 0, "cleared": cleared or {},
        "batch_state": {"count": 0, "alarm_fired": False}, "pending": pending,
    }


def test_lingtai_doctor_self_test_passes():
    proc = subprocess.run(
        [sys.executable, str(DOCTOR), "--self-test"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "self-test OK" in proc.stdout


def test_lingtai_doctor_json_redacts_env_secrets(tmp_path):
    agent = tmp_path / "project" / ".lingtai" / "mimo"
    agent.mkdir(parents=True)
    (agent / ".agent.json").write_text(
        json.dumps({"name": "mimo", "state": "idle"}), encoding="utf-8"
    )
    (agent / ".agent.heartbeat").write_text("ok", encoding="utf-8")
    (agent / "init.json").write_text(
        json.dumps(
            {
                "mcp": {
                    "telegram": {
                        "type": "stdio",
                        "command": "/definitely/missing/python",
                        "env": {"BOT_TOKEN": "secret-value", "CONFIG_PATH": ".secrets/tg.json"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    proc = subprocess.run(
        [sys.executable, str(DOCTOR), "--agent-dir", str(agent), "--json"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert proc.returncode == 1
    assert "secret-value" not in proc.stdout
    data = json.loads(proc.stdout)
    assert data["severity"] == "FAIL"
    assert any(section["name"] == "mcp/addons" for section in data["sections"])


def test_lingtai_doctor_reports_non_object_lifecycle_json(tmp_path):
    agent = tmp_path / "agent"
    agent.mkdir()
    (agent / ".agent.json").write_text("[]", encoding="utf-8")
    (agent / ".status.json").write_text('"idle"', encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, "-O", str(DOCTOR), "--agent-dir", str(agent), "--json"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert proc.returncode == 1
    assert not proc.stderr
    lifecycle = next(
        section for section in json.loads(proc.stdout)["sections"]
        if section["name"] == "lifecycle"
    )
    findings = {finding["title"]: finding for finding in lifecycle["findings"]}
    assert "list" in findings[".agent.json malformed"]["detail"]
    assert "str" in findings[".status.json malformed"]["detail"]


def test_lingtai_doctor_addon_timeout_becomes_warning(monkeypatch):
    doctor = load_doctor_module()
    section = doctor.Section("mcp/addons")

    def time_out(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs["timeout"])

    monkeypatch.setattr(doctor.subprocess, "run", time_out)

    assert doctor.try_addon_imports(section, [], {"example.addon"}) == ["example.addon"]
    assert section.severity == "WARN"
    assert section.findings[0].data["imports"][0]["error"] == [
        "import probe timed out after 10s"
    ]


def test_lingtai_doctor_probes_every_curated_addon():
    """``ADDON_MODULES`` must track ``mcp_catalog.json``.

    An addon missing here is a diagnostic blind spot: a configured entry whose
    args do not literally carry ``-m lingtai.mcp_servers.<name>`` is never
    import-probed, so a broken install passes doctor clean.
    """
    doctor = load_doctor_module()
    catalog = json.loads(
        (ROOT / "src" / "lingtai" / "mcp_catalog.json").read_text(encoding="utf-8")
    )

    expected = {
        name: entry["args"][entry["args"].index("-m") + 1]
        for name, entry in catalog.items()
        if not name.startswith("_") and "-m" in entry.get("args", [])
    }

    assert expected, "expected curated stdio addons in mcp_catalog.json"
    assert doctor.ADDON_MODULES == expected


def test_lingtai_doctor_addon_modules_are_importable_packages():
    doctor = load_doctor_module()

    for name, module in doctor.ADDON_MODULES.items():
        package = ROOT / "src" / Path(*module.split("."))
        assert package.is_dir(), f"{name} -> {module} is not a shipped package"


def test_lingtai_doctor_skill_doc_lists_every_probed_addon():
    skill = (
        ROOT / "src" / "lingtai" / "intrinsic_skills" / "lingtai-doctor" / "SKILL.md"
    ).read_text(encoding="utf-8")
    doctor = load_doctor_module()

    section = skill.split("**First-party MCP server imports**", 1)
    assert len(section) == 2, "SKILL.md no longer documents the import probe"
    probe_text = section[1].split("\n\n", 1)[0]

    for name in doctor.ADDON_MODULES:
        assert f"`{name}`" in probe_text, f"SKILL.md omits probed addon {name}"


def test_lingtai_doctor_reports_invalid_daemon_tombstone_without_contents(tmp_path):
    doctor = load_doctor_module()
    path = tmp_path / ".notification" / "daemon" / ".tombstone"
    path.parent.mkdir(parents=True)
    path.write_text('{"secret":"never-report-me"}', encoding="utf-8")

    valid, detail = doctor._daemon_tombstone_health(path)

    assert valid is False
    assert detail == {"error": "ValueError"}
    assert "never-report-me" not in repr(detail)


def test_lingtai_doctor_rejects_store_fatal_daemon_tombstones(tmp_path):
    doctor = load_doctor_module()
    path = tmp_path / ".notification" / "daemon" / ".tombstone"
    path.parent.mkdir(parents=True)
    cases = (
        _valid_tombstone(cleared={
            "bad.txt": {"raw_sha256": "0" * 64, "event_keys": []}
        }),
        _valid_tombstone(pending={
            "daemon_id": "!!bad", "event_id": "event-1",
            "prior_batch_state": {"count": 0, "alarm_fired": False},
            "batch_state": {"count": 1, "alarm_fired": False},
        }),
    )

    for value in cases:
        path.write_text(json.dumps(value), encoding="utf-8")
        valid, detail = doctor._daemon_tombstone_health(path)
        assert valid is False
        assert detail == {"error": "ValueError"}


def test_lingtai_doctor_type_hints_resolve():
    doctor = load_doctor_module()

    hints = typing.get_type_hints(doctor.newest_mtime)

    assert hints["paths"] == doctor.Iterable[Path]
