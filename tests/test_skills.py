"""Tests for the renamed skills capability."""
from __future__ import annotations

import importlib.util
from datetime import date, datetime
import json
import re
import sqlite3
import time
from pathlib import Path
from lingtai.agent import Agent
from tests._service_helpers import make_gemini_mock_service as make_mock_service




def _parse_skill_frontmatter(skill_md: Path) -> dict:
    content = skill_md.read_text(encoding="utf-8")
    assert content.startswith("---\n"), f"missing frontmatter: {skill_md}"
    end = content.find("\n---\n", 4)
    assert end != -1, f"missing closing frontmatter delimiter: {skill_md}"
    import yaml

    data = yaml.safe_load(content[4:end])
    assert isinstance(data, dict), f"frontmatter is not a mapping: {skill_md}"
    return data


def _timestamp_text(value) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return "" if value is None else str(value).strip().strip('"\'')


def _assert_iso_timestamp(value, path: Path):
    text = _timestamp_text(value)
    assert text, f"missing last_changed_at: {path}"
    datetime.fromisoformat(text.replace("Z", "+00:00"))
    assert "T" in text, f"last_changed_at must include time: {path}"
    assert text.endswith("Z") or "+" in text[10:] or "-" in text[10:], (
        f"last_changed_at must include timezone: {path}"
    )


def _mk_agent(tmp_path: Path, skills_cfg: dict | None = None):
    """Create an agent with the skills capability, optionally passing kwargs."""
    caps = {"skills": skills_cfg or {}}
    workdir = tmp_path / "agent"
    agent = Agent(
        service=make_mock_service(),
        agent_name="test",
        working_dir=workdir,
        capabilities=caps,
    )
    return agent, workdir


def _write_skill(folder: Path, name: str, desc: str = "test skill"):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {desc}\n---\n\nBody of {name}.\n"
    )


_UNKNOWN_ACTION = {
    "status": "failed",
    "error_code": "ACTION_REQUIRED",
    "message": "action must be one of info, manual",
}


def test_unknown_action_returns_error(tmp_path):
    """Only `info` and `manual` are supported; the failure is model-visible.

    After the LTP v2 ToolFamily migration the unknown-action envelope is the
    generic family failure (`status: "failed"` + typed `error_code`), not the
    pre-migration `{status: "error", message: "unknown action: ..."}` router
    envelope. Skills has no per-result diagnostic block of its own to preserve
    (unlike `web`'s `action`/`current_setting`), so it keeps the canonical
    family shape verbatim rather than renormalizing it.
    """
    agent, _ = _mk_agent(tmp_path)
    try:
        handler = agent._tool_handlers["skills"]
        assert handler({"action": "list", "input": {}, "reasoning": "r"}) == _UNKNOWN_ACTION
        # Missing action key fails the same way, before any handler I/O.
        assert handler({}) == _UNKNOWN_ACTION
        # Invalid JSON can make `action` unhashable (issue #513 blocker): the
        # dispatcher must render the typed failure, not raise TypeError.
        assert handler({"action": []}) == _UNKNOWN_ACTION
        assert handler({"action": {}}) == _UNKNOWN_ACTION
    finally:
        agent.stop(timeout=1.0)


def test_unknown_action_fails_before_any_handler_io(tmp_path, monkeypatch):
    """An unknown action must not scan the catalogue or read the manual."""
    agent, workdir = _mk_agent(tmp_path)
    try:
        from lingtai.tools import skills as skills_tool

        def _boom(*_args, **_kwargs):
            raise AssertionError("handler I/O ran for an unknown action")

        monkeypatch.setattr(skills_tool, "_reconcile", _boom)
        monkeypatch.setattr(skills_tool, "_skills_info", _boom)
        before = agent._prompt_manager.read_section("skills")
        assert agent._tool_handlers["skills"](
            {"action": "publish", "input": {}, "reasoning": "r"}
        ) == _UNKNOWN_ACTION
        assert agent._prompt_manager.read_section("skills") == before
    finally:
        agent.stop(timeout=1.0)


def test_family_schema_is_the_canonical_ltp_v2_root(tmp_path):
    """Public name/actions are unchanged; only the envelope is canonical now."""
    from lingtai.tools import skills as skills_tool

    schema = skills_tool.get_schema()
    assert schema["type"] == "object"
    assert set(schema["properties"]) == {"action", "input", "reasoning", "summarize"}
    assert schema["required"] == ["action", "input", "reasoning"]
    assert schema["additionalProperties"] is False
    # Public action values are unchanged and equal the dispatch keys.
    assert schema["properties"]["action"]["enum"] == ["info", "manual"]
    assert schema["properties"]["reasoning"]["type"] == "string"
    assert schema["properties"]["summarize"]["type"] == "boolean"

    branches = schema["properties"]["input"]["oneOf"]
    assert [b["title"] for b in branches] == ["info input", "manual input"]
    for branch in branches:
        # Canonical strict-empty input for both actions.
        assert branch["type"] == "object"
        assert branch["properties"] == {}
        assert branch["additionalProperties"] is False
        assert "reasoning" not in branch["properties"]
        assert "_reasoning" not in branch["properties"]
        assert "summarize" not in branch["properties"]

    # Root correlates each action const with that exact child's input schema.
    conditions = schema["allOf"]
    assert len(conditions) == 2
    for condition, name, branch in zip(conditions, ["info", "manual"], branches):
        assert condition["if"]["properties"]["action"]["const"] == name
        assert condition["if"]["required"] == ["action"]
        assert condition["then"]["properties"]["input"]["additionalProperties"] is False
        # Both surfaces derive from the one child registry, so the correlated
        # schema is exactly the disclosed branch (minus its display title).
        assert condition["then"]["properties"]["input"] == {
            k: v for k, v in branch.items() if k != "title"
        }


def test_schema_children_are_the_same_registry_dispatch_uses():
    """One canonical child-spec source backs both schema and dispatch.

    The advertised input schema for each action must be the exact object the
    dispatched child declares — not a parallel literal that can drift from it.
    """
    from lingtai.tools import skills as skills_tool

    schema_family = skills_tool._build_family(None, [])
    runtime_family = skills_tool._build_family(object(), ["/some/path"])
    assert schema_family.child_names == runtime_family.child_names == ("info", "manual")
    for name in ("info", "manual"):
        assert (
            schema_family._children[name].input_schema
            == runtime_family._children[name].input_schema
        )
        assert schema_family._children[name].title == runtime_family._children[name].title
    # And the composed schema is identical regardless of which one built it.
    assert schema_family.build_schema() == runtime_family.build_schema()


def test_both_actions_reject_extra_input_before_dispatch(tmp_path):
    """Strict-empty means any input key fails, on either action."""
    agent, _ = _mk_agent(tmp_path)
    try:
        handler = agent._tool_handlers["skills"]
        for action in ("info", "manual"):
            assert handler(
                {"action": action, "input": {"paths": ["/tmp"]}, "reasoning": "r"}
            ) == {
                "status": "failed",
                "error_code": "INVALID_ARGUMENT",
                "message": "unsupported skills input field",
            }
        # A missing/non-object input is rejected too.
        assert handler({"action": "info", "reasoning": "r"}) == {
            "status": "failed",
            "error_code": "INVALID_ARGUMENT",
            "message": "input must be an object",
        }
        # Unknown root fields and non-boolean summarize fail at the envelope.
        assert handler(
            {"action": "info", "input": {}, "reasoning": "r", "engine": "x"}
        ) == {
            "status": "failed",
            "error_code": "INVALID_ARGUMENT",
            "message": "unsupported skills argument",
        }
        assert handler(
            {"action": "info", "input": {}, "reasoning": "r", "summarize": "yes"}
        ) == {
            "status": "failed",
            "error_code": "INVALID_ARGUMENT",
            "message": "summarize must be a boolean",
        }
    finally:
        agent.stop(timeout=1.0)


def test_envelope_metadata_never_reaches_either_handler(tmp_path):
    """`reasoning`/`_reasoning`/`summarize` are root-only, never action input."""
    agent, _ = _mk_agent(tmp_path)
    try:
        handler = agent._tool_handlers["skills"]
        for action in ("info", "manual"):
            result = handler(
                {
                    "action": action,
                    "input": {},
                    "reasoning": "why",
                    "_reasoning": "internal",
                    "summarize": True,
                }
            )
            # Dispatch succeeded (the envelope fields were stripped, not
            # forwarded into the strict-empty child input).
            assert result["status"] == "ok"
            for leaked in ("reasoning", "_reasoning", "summarize"):
                assert leaked not in result
    finally:
        agent.stop(timeout=1.0)


def test_lingtai_owned_skill_frontmatter_has_last_changed_at():
    root = Path(__file__).resolve().parents[1]
    skill_files = sorted((root / "src" / "lingtai").rglob("SKILL.md"))
    assert skill_files, "expected LingTai-owned source skills"
    for skill_md in skill_files:
        fm = _parse_skill_frontmatter(skill_md)
        _assert_iso_timestamp(fm.get("last_changed_at"), skill_md)


def test_skills_validator_can_require_last_changed_at(tmp_path):
    root = Path(__file__).resolve().parents[1]
    validator_path = root / "src" / "lingtai" / "tools" / "skills" / "manual" / "scripts" / "validate.py"
    spec = importlib.util.spec_from_file_location("skill_validate", validator_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    skill = tmp_path / "skill"
    _write_skill(skill, "demo-skill", "demo skill for validator")
    passed, messages = module.validate_frontmatter(skill, require_last_changed_at=True)
    assert not passed
    assert any("last_changed_at" in msg for msg in messages)

    (skill / "SKILL.md").write_text(
        "---\n"
        "name: demo-skill\n"
        "description: demo skill for validator\n"
        "last_changed_at: \"2026-06-29T08:00:00Z\"\n"
        "---\n\n"
        "Body.\n",
        encoding="utf-8",
    )
    passed, messages = module.validate_frontmatter(skill, require_last_changed_at=True)
    assert passed, messages


# ---------------------------------------------------------------------------
# Structure & setup
# ---------------------------------------------------------------------------


def test_skills_setup_creates_per_agent_directories(tmp_path):
    agent, workdir = _mk_agent(tmp_path)
    try:
        assert (workdir / ".library").is_dir()
        assert (workdir / ".library" / "intrinsic").is_dir()
        assert (workdir / ".library" / "intrinsic" / "capabilities").is_dir()
        # Note: intrinsic/addons/ is not a skills-library concern; curated
        # addon implementations ship as MCP servers and are decompressed into
        # mcp_registry.jsonl by the `mcp` capability.
        assert (workdir / ".library" / "custom").is_dir()
    finally:
        agent.stop(timeout=1.0)


def test_skills_setup_hard_copies_intrinsics(tmp_path):
    # The Agent initializer installs each loaded capability's manual/ bundle
    # into intrinsic/capabilities/<cap>/. The skills capability documents
    # itself like every other capability.
    agent, workdir = _mk_agent(tmp_path)
    try:
        skill_md = (
            workdir / ".library" / "intrinsic" / "capabilities" / "skills" / "SKILL.md"
        )
        assert skill_md.is_file()
        body = skill_md.read_text(encoding="utf-8")
        assert "name: skills-manual" in body
        assert "Nested skill/reference pattern for umbrella manuals" in body
        assert "Nested reference catalog" in body
        assert "## Routing table" in body
        assert "children's routing metadata explicitly" in body
        assert "machine-readable routing table" in body
        assert "Do not leave the parent as only a prose list of links" in body
        assert "reference/substrate-manual/SKILL.md" in body
        assert "The catalog scanner treats a directory that already" in body
        assert "validate.py reference/topic-a/" in body

        bash_md = (
            workdir / ".library" / "intrinsic" / "capabilities" / "shell" / "SKILL.md"
        )
        assert bash_md.is_file()
        bash_body = bash_md.read_text(encoding="utf-8")
        assert "name: shell-manual" in bash_body
        assert "Nested reference catalog" in bash_body
        assert "reference/scheduled-work/SKILL.md" in bash_body
        assert "reference/notification-reminders/SKILL.md" in bash_body
        assert "reference/debugging-cleanup/SKILL.md" in bash_body

        web_root = (
            workdir / ".library" / "intrinsic" / "capabilities" / "web"
        )
        assert "name: web-manual" in (web_root / "SKILL.md").read_text(encoding="utf-8")
        assert (web_root / "scripts" / "extract_page.py").is_file()
        assert (web_root / "reference" / "tier-quick-refs" / "SKILL.md").is_file()
        for moved_reference in (
            "reference/bash-claude-code/SKILL.md",
            "reference/bash-openai-codex/SKILL.md",
            "reference/bash-opencode/SKILL.md",
            "reference/bash-cursor-agent/SKILL.md",
            "reference/bash-mimocode/SKILL.md",
            "reference/bash-qwen-code/SKILL.md",
            "reference/bash-oh-my-pi/SKILL.md",
            "reference/bash-gemini-cli/SKILL.md",
            "reference/bash-aider/SKILL.md",
            "reference/bash-goose/SKILL.md",
            "reference/bash-openhands/SKILL.md",
            "reference/bash-crush/SKILL.md",
            "reference/bash-zed-acp/SKILL.md",
        ):
            assert moved_reference in bash_body

        bash_reference_dir = bash_md.parent / "reference"
        for reference_name in (
            "scheduled-work",
            "notification-reminders",
            "debugging-cleanup",
            "bash-claude-code",
            "bash-openai-codex",
            "bash-opencode",
            "bash-cursor-agent",
            "bash-mimocode",
            "bash-qwen-code",
            "bash-oh-my-pi",
            "bash-gemini-cli",
            "bash-aider",
            "bash-goose",
            "bash-openhands",
            "bash-crush",
            "bash-zed-acp",
        ):
            bash_reference = bash_reference_dir / reference_name / "SKILL.md"
            assert bash_reference.is_file()
        assert "Nested shell-manual reference" in (
            bash_reference_dir / "scheduled-work" / "SKILL.md"
        ).read_text(encoding="utf-8")

        daemon_md = (
            workdir / ".library" / "intrinsic" / "capabilities" / "daemon" / "SKILL.md"
        )
        assert daemon_md.is_file()
        daemon_body = daemon_md.read_text(encoding="utf-8")
        assert "name: daemon-manual" in daemon_body
        assert "Nested reference catalog" in daemon_body
        assert "reference/forensics/SKILL.md" in daemon_body
        assert "reference/inspection/SKILL.md" in daemon_body
        assert "reference/cli-backends/SKILL.md" in daemon_body
        assert "reference/cleanup/SKILL.md" in daemon_body

        nokv_md = (
            workdir / ".library" / "intrinsic" / "capabilities" / "nokv-workbench" / "SKILL.md"
        )
        assert nokv_md.is_file()
        nokv_body = nokv_md.read_text(encoding="utf-8")
        assert "name: nokv-workbench" in nokv_body
        assert "workbench_find" in nokv_body
        assert "workbench_commit" in nokv_body
        assert "version: 0.5.0" in nokv_body
        assert "workbench_restore" in nokv_body
        assert "restore-to-fork" in nokv_body
        assert "same numeric `snapshot_id`" in nokv_body
        assert "metadata/restore_manifest.json" in nokv_body
        assert "nokv.workbench.restore_manifest.v1" in nokv_body
        assert "RestoreInProgress" in nokv_body
        assert "RestoreDestinationConflict" in nokv_body
        assert "CapabilityMismatch" in nokv_body
        assert "metadata/run_manifest.json" in nokv_body
        assert "nokv.workbench.run_manifest.v1" in nokv_body
        assert "content_digest_uri" in nokv_body
        assert "workbench_snapshot_retire" in nokv_body
        assert "application/x-ndjson" in nokv_body
        assert (
            nokv_md.parent / "assets" / "mcp_registry.example.jsonl"
        ).is_file()

        daemon_reference_dir = daemon_md.parent / "reference"
        for reference_name in ("forensics", "inspection", "cli-backends", "cleanup"):
            daemon_reference = daemon_reference_dir / reference_name / "SKILL.md"
            assert daemon_reference.is_file()
        for backend_name in (
            "codex",
            "opencode",
            "claude-p",
            "mimocode",
            "qwen-code",
            "kimicode",
            "cursor",
            "oh-my-pi",
            "lingtai",
        ):
            backend_reference = (
                daemon_reference_dir
                / "cli-backends"
                / "reference"
                / "backends"
                / backend_name
                / "SKILL.md"
            )
            assert backend_reference.is_file()
        assert "Nested daemon-manual reference" in (
            daemon_reference_dir / "forensics" / "SKILL.md"
        ).read_text(encoding="utf-8")
    finally:
        agent.stop(timeout=1.0)


def test_skills_setup_hard_copies_standalone_intrinsic_skills(tmp_path):
    # Standalone always-included skills live in lingtai.intrinsic_skills and are
    # copied next to capability manuals under .library/intrinsic/capabilities/.
    agent, workdir = _mk_agent(tmp_path)
    try:
        skill_md = (
            workdir
            / ".library"
            / "intrinsic"
            / "capabilities"
            / "file-manual"
            / "SKILL.md"
        )
        assert skill_md.is_file()
        body = skill_md.read_text(encoding="utf-8")
        assert "name: file-manual" in body
        assert "encoding='gbk'" in body
        assert "iconv -f gbk -t utf-8" in body

        system_manual_md = (
            workdir
            / ".library"
            / "intrinsic"
            / "capabilities"
            / "system-manual"
            / "SKILL.md"
        )
        assert system_manual_md.is_file()
        system_manual_body = system_manual_md.read_text(encoding="utf-8")
        assert "name: system-manual" in system_manual_body
        assert "Progressive Disclosure Router" in system_manual_body
        assert "reference/substrate-manual/SKILL.md" in system_manual_body
        assert "reference/procedures-manual/SKILL.md" in system_manual_body
        assert "reference/sqlite-log-query/SKILL.md" in system_manual_body
        assert "reference/runtime-update-checks/SKILL.md" in system_manual_body
        assert "lingtai-agent log doctor" in system_manual_body
        assert "lingtai-agent log query" in system_manual_body
        assert "lingtai-agent log rebuild" in system_manual_body
        assert "name: substrate-manual" in system_manual_body
        assert "name: procedures-manual" in system_manual_body
        assert "name: sqlite-log-query" in system_manual_body
        assert "name: runtime-update-checks" in system_manual_body
        assert "Nested reference catalog" in system_manual_body
        assert "location: reference/notification-manual/SKILL.md" not in system_manual_body

        notification_manual_md = (
            workdir
            / ".library"
            / "intrinsic"
            / "capabilities"
            / "notification-manual"
            / "SKILL.md"
        )
        assert notification_manual_md.is_file()
        notification_manual_body = notification_manual_md.read_text(encoding="utf-8")
        assert "name: notification-manual" in notification_manual_body
        assert "# Notification Manual" in notification_manual_body
        assert "<agent>/.library/intrinsic/capabilities/notification-manual/SKILL.md" in notification_manual_body
        assert "location: reference/channel-model/SKILL.md" in notification_manual_body
        assert "location: reference/dismissal-safety/SKILL.md" in notification_manual_body
        assert (
            notification_manual_md.parent / "reference" / "channel-model" / "SKILL.md"
        ).is_file()
        assert (
            notification_manual_md.parent / "reference" / "dismissal-safety" / "SKILL.md"
        ).is_file()
        assert not (
            system_manual_md.parent / "reference" / "notification-manual"
        ).exists()

        substrate_ref = system_manual_md.parent / "reference" / "substrate-manual" / "SKILL.md"
        assert substrate_ref.is_file()
        substrate_body = substrate_ref.read_text(encoding="utf-8")
        assert "name: substrate-manual" in substrate_body
        assert "Nested system-manual reference" in substrate_body
        assert "# Substrate Manual" in substrate_body
        assert "**ACTIVE**" in substrate_body
        assert "**ASLEEP**" in substrate_body
        assert "**SUSPENDED**" in substrate_body
        assert "MCP and addon ownership" in substrate_body
        assert "notification" in substrate_body
        assert "dismiss" in substrate_body

        procedures_ref = system_manual_md.parent / "reference" / "procedures-manual" / "SKILL.md"
        assert procedures_ref.is_file()
        procedures_body = procedures_ref.read_text(encoding="utf-8")
        assert "name: procedures-manual" in procedures_body
        assert "Nested system-manual reference" in procedures_body
        assert "# Procedures Manual" in procedures_body
        assert "Human-facing deliverables" in procedures_body
        assert "external side effects" in procedures_body
        assert "Resident procedures maintenance" in procedures_body

        runtime_update_ref = (
            system_manual_md.parent / "reference" / "runtime-update-checks" / "SKILL.md"
        )
        assert runtime_update_ref.is_file()
        runtime_update_body = runtime_update_ref.read_text(encoding="utf-8")
        assert "name: runtime-update-checks" in runtime_update_body
        assert "Nested system-manual reference" in runtime_update_body
        assert "# Runtime Update Checks" in runtime_update_body
        assert "kind: kernel_version" in runtime_update_body
        assert ".notification/nudge.json" in runtime_update_body
        assert "roughly 60-second in-memory probe gate" in runtime_update_body
        assert "editable/source/dev" in runtime_update_body
        assert "receiving explicit confirmation" in runtime_update_body

        context_manual_md = (
            workdir
            / ".library"
            / "intrinsic"
            / "capabilities"
            / "context-manual"
            / "SKILL.md"
        )
        assert context_manual_md.is_file()
        context_manual_body = context_manual_md.read_text(encoding="utf-8")
        assert "name: context-manual" in context_manual_body
        assert "## Asset catalog" in context_manual_body
        assert "assets/molt-template.md" in context_manual_body
        assert "9-section summary scaffold" in context_manual_body
        assert "9. **Context Status**" not in context_manual_body

        molt_template_asset = context_manual_md.parent / "assets" / "molt-template.md"
        assert molt_template_asset.is_file()
        molt_template_body = molt_template_asset.read_text(encoding="utf-8")
        assert "# Consequential Molt Summary Template" in molt_template_body
        assert "## Summary scaffold" in molt_template_body
        for section in (
            "1. **Who I Am**",
            "2. **Accomplishments**",
            "3. **Outstanding Tasks**",
            "4. **Action Checklist**",
            "5. **Collaborators**",
            "6. **Durable Memory and Execution Notes**",
            "7. **Key Paths and Artifacts**",
            "8. **Lessons and Gotchas**",
            "9. **Context Status**",
        ):
            assert section in molt_template_body
        assert "## Pre-molt verification checklist" in molt_template_body

        sqlite_log_query_ref = system_manual_md.parent / "reference" / "sqlite-log-query" / "SKILL.md"
        assert sqlite_log_query_ref.is_file()
        sqlite_log_query_body = sqlite_log_query_ref.read_text(encoding="utf-8")
        assert "name: sqlite-log-query" in sqlite_log_query_body
        assert "Nested system-manual reference" in sqlite_log_query_body
        assert "# SQLite Log Query" in sqlite_log_query_body
        assert "lingtai-agent log query" in sqlite_log_query_body
        # Trajectory mining content is now in the sqlite-log-query reference
        assert "Trajectory Mining" in sqlite_log_query_body
        assert "trajectory mining" in sqlite_log_query_body.lower()
        assert "Finding schema" in sqlite_log_query_body or "finding schema" in sqlite_log_query_body.lower()
        assert "cheap model" in sqlite_log_query_body.lower() or "cheap-model" in sqlite_log_query_body.lower()
        assert "scripts/event_summary.py" in sqlite_log_query_body

        # event_summary.py script exists, is referenced, and can summarize
        # a minimal SQLite sidecar using the actual events schema columns.
        sqlite_scripts = sqlite_log_query_ref.parent / "scripts" / "event_summary.py"
        assert sqlite_scripts.is_file(), "event_summary.py script must exist"
        spec = importlib.util.spec_from_file_location("event_summary_for_test", sqlite_scripts)
        assert spec and spec.loader
        event_summary = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(event_summary)

        db_path = tmp_path / "log.sqlite"
        conn = sqlite3.connect(db_path)
        conn.executescript(
            """
            CREATE TABLE events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              ts REAL NOT NULL,
              type TEXT NOT NULL,
              agent_address TEXT,
              agent_name_snapshot TEXT,
              fields_json TEXT NOT NULL,
              source_file TEXT,
              source_offset INTEGER,
              source_line INTEGER,
              source_kind TEXT,
              scope TEXT,
              run_id TEXT,
              inserted_at TEXT
            );
            """
        )
        now = time.time()
        conn.executemany(
            "INSERT INTO events(ts, type, fields_json, source_kind, scope, run_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                (now - 60, "tool_call", json.dumps({"name": "bash"}), "agent_events", "agent", None),
                (now, "tool_result", json.dumps({"error": "token abcdefghijklmnop"}), "agent_events", "agent", None),
            ],
        )
        conn.commit()
        conn.close()
        summary = event_summary.summarize(str(db_path), source_kind="agent_events", hours=1)
        assert summary["total_events"] == 2
        assert summary["event_type_counts"]
        assert summary["schema_keys"]
        assert summary["error_clusters"][0]["error"] == "token=[REDACTED]"

        # No standalone top-level trajectory-mining skill: the capability is
        # intentionally exposed only through system-manual's SQLite reference.
        trajectory_md = (
            workdir
            / ".library"
            / "intrinsic"
            / "capabilities"
            / "lingtai-trajectory-mining"
            / "SKILL.md"
        )
        assert not trajectory_md.exists()
        assert "trajectory/anomaly mining" in system_manual_body
        assert "sqlite-log-query" in system_manual_body

        doctor_md = (
            workdir
            / ".library"
            / "intrinsic"
            / "capabilities"
            / "lingtai-doctor"
            / "SKILL.md"
        )
        doctor_script = doctor_md.parent / "scripts" / "doctor.py"
        assert doctor_md.is_file()
        assert doctor_script.is_file()
        assert "name: lingtai-doctor" in doctor_md.read_text(encoding="utf-8")
    finally:
        agent.stop(timeout=1.0)


def test_skills_setup_overwrites_stale_intrinsic(tmp_path):
    # The Agent initializer wipes-and-rewrites intrinsic/ on construction.
    # A stale entry from a previous kernel version must be replaced.
    workdir = tmp_path / "agent"
    stale = (
        workdir / ".library" / "intrinsic" / "capabilities" / "skills" / "SKILL.md"
    )
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text("---\nname: skills-manual\ndescription: STALE\n---\n")

    # Also leave a stale top-level dir to confirm wipe-and-rewrite scrubs old layouts.
    old_layout = workdir / ".library" / "intrinsic" / "skill-for-skill" / "SKILL.md"
    old_layout.parent.mkdir(parents=True, exist_ok=True)
    old_layout.write_text("---\nname: skill-for-skill\ndescription: ANCIENT\n---\n")

    agent = Agent(
        service=make_mock_service(),
        agent_name="test",
        working_dir=workdir,
        capabilities={"skills": {}},
    )
    try:
        body = stale.read_text()
        assert "STALE" not in body
        assert "The Skills Capability" in body or "skills-manual" in body
        # Old layout scrubbed.
        assert not old_layout.exists()
    finally:
        agent.stop(timeout=1.0)


def test_skills_setup_leaves_custom_untouched(tmp_path):
    workdir = tmp_path / "agent"
    user_skill = workdir / ".library" / "custom" / "my-tool" / "SKILL.md"
    user_skill.parent.mkdir(parents=True, exist_ok=True)
    user_skill.write_text("---\nname: my-tool\ndescription: Mine\n---\nUser content.\n")

    agent = Agent(
        service=make_mock_service(),
        agent_name="test",
        working_dir=workdir,
        capabilities={"skills": {}},
    )
    try:
        assert user_skill.read_text() == "---\nname: my-tool\ndescription: Mine\n---\nUser content.\n"
    finally:
        agent.stop(timeout=1.0)


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


def test_skills_scans_absolute_path(tmp_path):
    extra = tmp_path / "extra"
    _write_skill(extra / "shared-skill", "shared-skill")

    agent, _ = _mk_agent(tmp_path, {"paths": [str(extra)]})
    try:
        result = agent._tool_handlers["skills"]({"action": "info", "input": {}, "reasoning": "test"})
        assert result["status"] == "ok"
        assert result["paths"][str(extra)]["skills"] == 1
        assert result["catalog_size"] >= 2  # skills-manual + shared-skill
    finally:
        agent.stop(timeout=1.0)


def test_skills_resolves_relative_path_from_working_dir(tmp_path):
    # Build a network-root layout: tmp_path is the network root.
    # The agent lives at tmp_path/agent, and .library_shared sits at tmp_path/.library_shared.
    shared = tmp_path / ".library_shared"
    _write_skill(shared / "net-skill", "net-skill")

    agent, _ = _mk_agent(tmp_path, {"paths": ["../.library_shared"]})
    try:
        result = agent._tool_handlers["skills"]({"action": "info", "input": {}, "reasoning": "test"})
        assert result["status"] == "ok"
        assert result["paths"]["../.library_shared"]["exists"] is True
        assert result["paths"]["../.library_shared"]["skills"] == 1
    finally:
        agent.stop(timeout=1.0)


def test_skills_expands_tilde(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    utils = fake_home / "my-utils"
    _write_skill(utils / "util-skill", "util-skill")

    agent, _ = _mk_agent(tmp_path, {"paths": ["~/my-utils"]})
    try:
        result = agent._tool_handlers["skills"]({"action": "info", "input": {}, "reasoning": "test"})
        assert result["paths"]["~/my-utils"]["exists"] is True
    finally:
        agent.stop(timeout=1.0)


def test_skills_reports_missing_path_as_not_existing(tmp_path):
    agent, _ = _mk_agent(tmp_path, {"paths": ["/does/not/exist"]})
    try:
        result = agent._tool_handlers["skills"]({"action": "info", "input": {}, "reasoning": "test"})
        assert result["paths"]["/does/not/exist"]["exists"] is False
        assert result["paths"]["/does/not/exist"]["skills"] == 0
    finally:
        agent.stop(timeout=1.0)


# ---------------------------------------------------------------------------
# info action
# ---------------------------------------------------------------------------


def test_info_omits_skills_manual_body(tmp_path):
    agent, _ = _mk_agent(tmp_path)
    try:
        result = agent._tool_handlers["skills"]({"action": "info", "input": {}, "reasoning": "test"})
        assert "skills_manual" not in result
        assert "library_manual" not in result
    finally:
        agent.stop(timeout=1.0)


def test_manual_returns_skills_manual_body(tmp_path):
    agent, _ = _mk_agent(tmp_path)
    try:
        result = agent._tool_handlers["skills"]({"action": "manual", "input": {}, "reasoning": "test"})
        assert "skills_manual" in result
        assert "library_manual" in result
        assert "name: skills-manual" in result["skills_manual"]
    finally:
        agent.stop(timeout=1.0)


def test_info_reports_ok_when_healthy(tmp_path):
    agent, _ = _mk_agent(tmp_path)
    try:
        result = agent._tool_handlers["skills"]({"action": "info", "input": {}, "reasoning": "test"})
        assert result["status"] == "ok"
        assert "error" not in result
    finally:
        agent.stop(timeout=1.0)


def test_info_reports_degraded_when_intrinsic_missing(tmp_path):
    # The skills capability is pure presentation — it does NOT reinstall
    # manuals when info is called. So if the initializer-installed manual is
    # deleted out-of-band after setup, info must report degraded.
    agent, workdir = _mk_agent(tmp_path)
    try:
        manual_path = (
            workdir / ".library" / "intrinsic" / "capabilities" / "skills" / "SKILL.md"
        )
        assert manual_path.is_file(), "precondition: initializer installed manual"
        manual_path.unlink()

        result = agent._tool_handlers["skills"]({"action": "info", "input": {}, "reasoning": "test"})
        assert result["status"] == "degraded"
        assert "error" in result
    finally:
        agent.stop(timeout=1.0)


def test_info_surfaces_problems(tmp_path):
    workdir = tmp_path / "agent"
    # Pre-create a broken custom skill (missing description frontmatter).
    bad = workdir / ".library" / "custom" / "broken" / "SKILL.md"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("---\nname: broken\n---\nno description!\n")

    agent = Agent(
        service=make_mock_service(),
        agent_name="test",
        working_dir=workdir,
        capabilities={"skills": {}},
    )
    try:
        result = agent._tool_handlers["skills"]({"action": "info", "input": {}, "reasoning": "test"})
        problem_folders = [p["folder"] for p in result["problems"]]
        assert any("broken" in f for f in problem_folders)
    finally:
        agent.stop(timeout=1.0)


# ---------------------------------------------------------------------------
# LTP v2 migration: exact semantic preservation of both children
# ---------------------------------------------------------------------------


def test_info_result_keys_and_health_are_exactly_preserved(tmp_path):
    """`info` still returns the exact pre-migration health/problem report.

    The envelope changed; the child's own canonical result did not. Keys, the
    resolved-path report, the problem list entries, and `catalog_size` are
    returned verbatim, with the manual body still omitted and no wrapper
    around the child result.
    """
    extra = tmp_path / "extra"
    _write_skill(extra / "good-skill", "good-skill")
    workdir = tmp_path / "agent"
    bad = workdir / ".library" / "custom" / "broken" / "SKILL.md"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("---\nname: broken\n---\nno description!\n")

    agent = Agent(
        service=make_mock_service(),
        agent_name="test",
        working_dir=workdir,
        capabilities={"skills": {"paths": [str(extra)]}},
    )
    try:
        result = agent._tool_handlers["skills"](
            {"action": "info", "input": {}, "reasoning": "health check"}
        )
        assert set(result) == {
            "status",
            "skills_dir",
            "library_dir",
            "catalog_size",
            "paths",
            "problems",
        }
        assert result["status"] == "ok"
        assert result["skills_dir"] == str(workdir / ".library")
        assert result["library_dir"] == result["skills_dir"]
        assert result["paths"] == {
            str(extra): {"resolved": str(extra), "exists": True, "skills": 1}
        }
        assert result["problems"] == [
            {
                "folder": "broken",
                "reason": "SKILL.md missing required frontmatter field: description",
            }
        ]
        assert result["catalog_size"] >= 2
        # No child-result envelope nested inside the action result.
        assert "content" not in result
        assert "structuredContent" not in result
    finally:
        agent.stop(timeout=1.0)


def test_manual_result_is_exact_body_and_path_without_double_wrap(tmp_path):
    """`manual` returns the exact installed bytes and host-local path."""
    agent, workdir = _mk_agent(tmp_path)
    try:
        manual_path = (
            workdir / ".library" / "intrinsic" / "capabilities" / "skills" / "SKILL.md"
        )
        expected = manual_path.read_text(encoding="utf-8")
        result = agent._tool_handlers["skills"](
            {"action": "manual", "input": {}, "reasoning": "load guidance"}
        )
        assert result == {
            "status": "ok",
            "skills_manual": expected,
            "library_manual": expected,
            "manual_path": str(manual_path),
        }
        # The canonical child result is adapted by the Host, never nested.
        assert "content" not in result
        assert "structuredContent" not in result
    finally:
        agent.stop(timeout=1.0)


def test_manual_has_no_info_side_effect(tmp_path):
    """`manual` must not scan, reconcile, or re-inject the catalogue.

    A skill added on disk after setup stays invisible until `info` runs: this
    proves `manual` performed no catalogue mutation, only a manual read.
    """
    extra = tmp_path / "extra"
    _write_skill(extra / "before-skill", "before-skill")
    agent, _ = _mk_agent(tmp_path, {"paths": [str(extra)]})
    try:
        handler = agent._tool_handlers["skills"]
        before = agent._prompt_manager.read_section("skills") or ""
        assert "- name: before-skill" in before

        # Add a new skill on disk, then call `manual` only.
        _write_skill(extra / "after-skill", "after-skill")
        manual_result = handler(
            {"action": "manual", "input": {}, "reasoning": "read manual"}
        )
        assert manual_result["status"] == "ok"
        unchanged = agent._prompt_manager.read_section("skills") or ""
        assert unchanged == before
        assert "- name: after-skill" not in unchanged
        # `manual` reports no health fields at all.
        for info_only in ("catalog_size", "paths", "problems", "skills_dir"):
            assert info_only not in manual_result

        # `info` is what reconciles — the new skill appears only now.
        info_result = handler({"action": "info", "input": {}, "reasoning": "refresh"})
        refreshed = agent._prompt_manager.read_section("skills") or ""
        assert "- name: after-skill" in refreshed
        assert info_result["paths"][str(extra)]["skills"] == 2
    finally:
        agent.stop(timeout=1.0)


def test_manual_degrades_with_exact_loader_message(tmp_path):
    """A missing manual degrades on `manual` exactly as before the migration."""
    agent, workdir = _mk_agent(tmp_path)
    try:
        manual_path = (
            workdir / ".library" / "intrinsic" / "capabilities" / "skills" / "SKILL.md"
        )
        assert manual_path.is_file(), "precondition: initializer installed manual"
        manual_path.unlink()

        assert agent._tool_handlers["skills"](
            {"action": "manual", "input": {}, "reasoning": "read manual"}
        ) == {
            "status": "degraded",
            "skills_manual": "",
            "library_manual": "",
            "manual_path": str(manual_path),
            "error": (
                "skills manual missing — initializer may have failed or "
                "capability not installed correctly"
            ),
        }
    finally:
        agent.stop(timeout=1.0)


def test_skills_family_reaches_both_provider_wires(tmp_path):
    """The composed schema survives Chat Completions and Responses unchanged."""
    from lingtai.kernel.base_agent.tools import _build_tool_schemas
    from lingtai.llm.openai.adapter import _build_responses_tools, _build_tools

    agent, _ = _mk_agent(tmp_path)
    try:
        schemas = _build_tool_schemas(agent)
        # Exactly one public model root for the family; no duplicate old roots.
        assert [s.name for s in schemas].count("skills") == 1
        skills_schema = next(s for s in schemas if s.name == "skills")
        chat = _build_tools([skills_schema])[0]["function"]["parameters"]
        responses = _build_responses_tools([skills_schema])[0]["parameters"]
        for wire, combinator in ((chat, "oneOf"), (responses, "anyOf")):
            assert set(wire["properties"]) == {
                "action",
                "input",
                "reasoning",
                "summarize",
            }
            assert wire["required"] == ["action", "input", "reasoning"]
            assert wire["additionalProperties"] is False
            assert wire["properties"]["action"]["enum"] == ["info", "manual"]
            branches = wire["properties"]["input"][combinator]
            assert [b["title"] for b in branches] == ["info input", "manual input"]
    finally:
        agent.stop(timeout=1.0)


def test_skills_is_a_migrated_ltp_v2_family_for_summarize(tmp_path):
    """Root `summarize` is the canonical control for this migrated family."""
    from lingtai.kernel.tool_result_summary import summary_requested

    assert summary_requested({"summarize": True}, tool_name="skills") is True
    assert summary_requested({"summarize": False}, tool_name="skills") is False
    # Still scoped by name: an unmigrated tool's own field is not this control.
    # ``bash`` is the legacy input alias for the migrated ``shell`` family and
    # is never itself on the allowlist, so it stands in for "unmigrated" here.
    assert summary_requested({"summarize": True}, tool_name="bash") is False


# ---------------------------------------------------------------------------
# Prompt injection
# ---------------------------------------------------------------------------


def test_catalog_injected_into_skills_section(tmp_path):
    extra = tmp_path / "extra"
    _write_skill(extra / "shared-thing", "shared-thing")

    agent, _ = _mk_agent(tmp_path, {"paths": [str(extra)]})
    try:
        prompt = agent._prompt_manager.read_section("skills") or ""
        assert "- name: skills-manual" in prompt
        assert "- name: file-manual" in prompt
        assert "- name: shared-thing" in prompt
    finally:
        agent.stop(timeout=1.0)


def test_web_manual_is_one_top_level_catalog_entry_matching_the_tool(tmp_path):
    # Ownership collapse contract: the generic skill catalogue must expose
    # exactly one top-level entry for the web tool's manual, named
    # `web-manual`, with no separate top-level `web-browsing` identity — and
    # `web(action="manual")` must return the same installed SKILL.md bytes
    # that catalogue entry was built from. Nested reference/<topic>/SKILL.md
    # files stay parent-owned drill-down references, never separate
    # top-level catalogue entries.
    workdir = tmp_path / "agent"
    agent = Agent(
        service=make_mock_service(),
        agent_name="test",
        working_dir=workdir,
        capabilities={"skills": {}, "web": {"provider": "duckduckgo"}},
    )
    try:
        prompt = agent._prompt_manager.read_section("skills") or ""
        top_level_names = re.findall(r"^- name: (\S+)$", prompt, flags=re.MULTILINE)

        web_entries = [n for n in top_level_names if n == "web-manual" or n.startswith("web-browsing")]
        assert web_entries == ["web-manual"], (
            f"expected exactly one top-level 'web-manual' entry and no 'web-browsing*' "
            f"entry, got: {web_entries}"
        )
        assert not any(n.startswith("web-browsing") for n in top_level_names)

        installed_manual_path = (
            workdir / ".library" / "intrinsic" / "capabilities" / "web" / "SKILL.md"
        )
        installed_bytes = installed_manual_path.read_bytes()
        assert b"name: web-manual" in installed_bytes

        tool_result = agent._tool_handlers["web"]({"action": "manual", "input": {}})
        assert tool_result["status"] == "ok"
        assert tool_result["manual"].encode("utf-8") == installed_bytes
        assert tool_result["manual_path"] == str(installed_manual_path)

        # Nested reference SKILL.md files exist and are parent-owned — they
        # must not surface as additional top-level catalogue names.
        nested = [
            "web-manual-tier-quick-refs",
            "web-manual-routing-and-sites",
            "web-manual-maintenance-bundles",
        ]
        for name in nested:
            assert name not in top_level_names
    finally:
        agent.stop(timeout=1.0)


def test_catalog_rendering_is_readable_without_xml_quote_noise(tmp_path):
    # The catalog goes straight into the system prompt; humans (and the model)
    # complained that the prior XML shape was escape soup. Pin the YAML shape:
    # per-skill block with a `description:` block scalar carrying raw quotes
    # and apostrophes, no `&quot;` / `&apos;` over-escaping noise.
    workdir = tmp_path / "agent"
    _write_skill(
        workdir / ".library" / "custom" / "fancy-tool",
        "fancy-tool",
        'Handles "quoted" args and \'apostrophes\' — keep them raw.',
    )

    agent = Agent(
        service=make_mock_service(),
        agent_name="test",
        working_dir=workdir,
        capabilities={"skills": {}},
    )
    try:
        prompt = agent._prompt_manager.read_section("skills") or ""
        # No spurious escape entities for `"` and `'` in element text.
        assert "&quot;" not in prompt
        assert "&apos;" not in prompt
        # YAML shape: `- name:` entry with a `description: |` block scalar.
        assert "- name: fancy-tool" in prompt
        assert "  description: |" in prompt
        # Body sits one level deeper than the `description:` field.
        assert "    Handles \"quoted\" args" in prompt
    finally:
        agent.stop(timeout=1.0)


def test_custom_skills_appear_in_catalog(tmp_path):
    workdir = tmp_path / "agent"
    _write_skill(workdir / ".library" / "custom" / "my-tool", "my-tool", "my desc")

    agent = Agent(
        service=make_mock_service(),
        agent_name="test",
        working_dir=workdir,
        capabilities={"skills": {}},
    )
    try:
        prompt = agent._prompt_manager.read_section("skills") or ""
        assert "my-tool" in prompt
        assert "my desc" in prompt
    finally:
        agent.stop(timeout=1.0)



# NOTE: `knowledge` and `skills` are now default-on (the always-on tool floor
# boots on every Agent). The tests below preserve the breaking-rename guarantee
# at its remaining surface: legacy `library` / `codex` capability NAMES must not
# themselves produce tool handlers. Whether `knowledge`/`skills` are present is
# governed by core defaults, not by alias normalization.


def test_former_library_config_does_not_register_library_tool(tmp_path):
    workdir = tmp_path / "agent"
    agent = Agent(
        service=make_mock_service(),
        agent_name="test",
        working_dir=workdir,
        capabilities={"library": {}},
    )
    try:
        assert "library" not in agent._tool_handlers
    finally:
        agent.stop(timeout=1.0)


def test_former_library_list_config_does_not_register_library_tool(tmp_path):
    workdir = tmp_path / "agent"
    agent = Agent(
        service=make_mock_service(),
        agent_name="test",
        working_dir=workdir,
        capabilities=["library"],
    )
    try:
        assert "library" not in agent._tool_handlers
    finally:
        agent.stop(timeout=1.0)


def test_former_library_paths_do_not_leak_into_skills_catalog(tmp_path):
    """Skills extra paths must come from the `skills` cap, not `library` alias."""
    extra = tmp_path / "extra"
    _write_skill(extra / "old-shared", "old-shared")
    workdir = tmp_path / "agent"

    agent = Agent(
        service=make_mock_service(),
        agent_name="test",
        working_dir=workdir,
        capabilities={"library": {"paths": [str(extra)]}},
    )
    try:
        # `skills` is default-on, but the legacy `library.paths` must not be
        # picked up as an extra skill path by alias normalization.
        assert "old-shared" not in (agent._prompt_manager.read_section("skills") or "")
    finally:
        agent.stop(timeout=1.0)


def test_former_codex_library_pair_does_not_register_legacy_tools(tmp_path):
    extra = tmp_path / "extra"
    _write_skill(extra / "paired-shared", "paired-shared")
    workdir = tmp_path / "agent"

    agent = Agent(
        service=make_mock_service(),
        agent_name="test",
        working_dir=workdir,
        capabilities={"codex": {}, "library": {"paths": [str(extra)]}},
    )
    try:
        assert "codex" not in agent._tool_handlers
        assert "library" not in agent._tool_handlers
    finally:
        agent.stop(timeout=1.0)


def test_new_knowledge_and_skills_config_registers_both(tmp_path):
    extra = tmp_path / "extra"
    _write_skill(extra / "new-shared", "new-shared")
    workdir = tmp_path / "agent"

    agent = Agent(
        service=make_mock_service(),
        agent_name="test",
        working_dir=workdir,
        capabilities={"knowledge": {}, "skills": {"paths": [str(extra)]}},
    )
    try:
        assert {"knowledge", "skills"}.issubset(agent._tool_handlers)
        assert "library" not in agent._tool_handlers
        assert "codex" not in agent._tool_handlers
        assert "new-shared" in (agent._prompt_manager.read_section("skills") or "")
        # Knowledge is now filesystem-backed and isomorphic to skills: author by
        # writing knowledge/<name>/KNOWLEDGE.md, then refresh via info.
        entry_dir = workdir / "knowledge" / "new-entry"
        entry_dir.mkdir(parents=True)
        (entry_dir / "KNOWLEDGE.md").write_text(
            "---\nname: new-entry\ndescription: A freshly authored knowledge entry.\n---\nBody.\n"
        )
        result = agent._tool_handlers["knowledge"](
            {"action": "info", "input": {}, "reasoning": "refresh after authoring"}
        )
        assert result["status"] == "ok"
        assert result["catalog_size"] == 1
        assert "new-entry" in (agent._prompt_manager.read_section("knowledge") or "")
    finally:
        agent.stop(timeout=1.0)


# ---------------------------------------------------------------------------
# No git operations
# ---------------------------------------------------------------------------


def test_skills_does_not_create_git_repo(tmp_path):
    agent, workdir = _mk_agent(tmp_path)
    try:
        assert not (workdir / ".library" / ".git").exists()
    finally:
        agent.stop(timeout=1.0)


def test_resident_prompts_route_to_system_manual_nested_references():
    root = Path(__file__).resolve().parents[1]

    substrate = (root / "src" / "lingtai" / "prompts" / "substrate" / "substrate.md").read_text(
        encoding="utf-8"
    )
    assert "expanded runtime/substrate\nrouter is `system-manual`" in substrate
    assert "reference/substrate-manual/SKILL.md" in substrate

    procedures = (root / "src" / "lingtai" / "prompts" / "procedures" / "procedures.md").read_text(
        encoding="utf-8"
    )
    assert "unified runtime/procedure router is\n`system-manual`" in procedures
    assert "reference/procedures-manual/SKILL.md" in procedures


def test_skills_manual_documents_external_skill_intake_default():
    manual = (
        Path(__file__).resolve().parents[1]
        / "src/lingtai/tools/skills/manual/SKILL.md"
    ).read_text(encoding="utf-8")
    required = [
        "## External skill intake (default flow)",
        "<agent>/.library/custom/<skill-name>/",
        "run the bundled validator",
        "call `system({\"action\": \"refresh\"})`",
        "the skill is only a file on disk",
        "Each receiving agent clones/copies it into",
        "Do not assume `.library_shared` is loaded by default",
        "add `../.library_shared` to each participating",
    ]
    for phrase in required:
        assert phrase in manual


def test_context_manual_routes_skill_sharing_through_custom_by_default():
    manual = (
        Path(__file__).resolve().parents[1]
        / "src/lingtai/intrinsic_skills/context-manual/SKILL.md"
    ).read_text(encoding="utf-8")
    assert "peers install it into their own `.library/custom/<name>/`" in manual
    assert "explicit opt-in local-network shared root" in manual
