"""Focused LTP v2 evidence for the one public ``substrate`` root.

Covers the exact public inventory, the strict-empty input on every child,
pre-I/O rejection, that each action returns its own intended manual, that no
action mutates disk or prompt, and that the four former public roots and their
retired actions are gone without an alias.
"""
from __future__ import annotations

import hashlib
import importlib

import pytest

from lingtai.agent import Agent
from lingtai.tools import substrate as substrate_tool
from tests._service_helpers import make_gemini_mock_service as make_mock_service


EXPECTED_ACTIONS = ["pad", "lingtai", "knowledge", "skills", "manual"]

#: Which installed manual each action must return, by its `.library` directory.
EXPECTED_MANUAL_DIR = {
    "pad": "pad-manual",
    "lingtai": "lingtai-manual",
    "knowledge": "knowledge",
    "skills": "skills",
    "manual": "substrate-manual",
}


def _agent(tmp_path, **kwargs):
    return Agent(
        service=make_mock_service(), agent_name="test",
        working_dir=tmp_path / "test", **kwargs,
    )


def _call(agent, action, action_input=None, **root):
    args = {"action": action, "input": {} if action_input is None else action_input}
    args.setdefault("reasoning", "why")
    args.update(root)
    return agent._intrinsics["substrate"](args)


def _fs_digest(root):
    h = hashlib.sha256()
    for f in sorted(p for p in root.rglob("*") if p.is_file()):
        h.update(str(f.relative_to(root)).encode())
        h.update(f.read_bytes())
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Public inventory and schema
# ---------------------------------------------------------------------------

def test_exact_public_action_inventory():
    assert substrate_tool.ACTION_ORDER == tuple(EXPECTED_ACTIONS)
    assert substrate_tool.get_schema()["properties"]["action"]["enum"] == EXPECTED_ACTIONS


def test_root_is_the_closed_strict_ltp_v2_envelope():
    schema = substrate_tool.get_schema()
    assert schema["type"] == "object"
    assert sorted(schema["properties"]) == ["action", "input", "reasoning", "summarize"]
    assert schema["required"] == ["action", "input", "reasoning"]
    assert schema["additionalProperties"] is False


def test_every_child_input_is_the_canonical_strict_empty_object():
    schema = substrate_tool.get_schema()
    branches = schema["properties"]["input"]["oneOf"]
    assert [b["title"] for b in branches] == [f"{a} input" for a in EXPECTED_ACTIONS]
    for branch in branches:
        assert branch["type"] == "object"
        assert branch["properties"] == {}
        assert branch["additionalProperties"] is False


def test_root_allof_correlates_each_action_const_with_its_input_schema():
    conditions = substrate_tool.get_schema()["allOf"]
    assert len(conditions) == len(EXPECTED_ACTIONS)
    for action, cond in zip(EXPECTED_ACTIONS, conditions):
        assert cond["if"]["properties"]["action"]["const"] == action
        assert cond["if"]["required"] == ["action"]
        assert cond["then"]["properties"]["input"]["additionalProperties"] is False


def test_registered_exactly_once_as_an_intrinsic(tmp_path):
    from lingtai.tools.registry import BUILTIN_TOOLS, INTRINSICS

    assert INTRINSICS["substrate"]["module"] is substrate_tool
    assert "substrate" not in BUILTIN_TOOLS

    agent = _agent(tmp_path)
    try:
        schema_names = [s.name for s in agent._build_tool_schemas()]
        assert schema_names.count("substrate") == 1
    finally:
        agent.stop(timeout=1.0)


def test_substrate_family_reaches_both_provider_wires(tmp_path):
    """The composed schema survives Chat and Responses adapter scrubbing."""
    from lingtai.llm.openai.adapter import _scrub_responses_schema

    schema = substrate_tool.get_schema()
    scrubbed = _scrub_responses_schema(schema)
    assert scrubbed["properties"]["action"]["enum"] == EXPECTED_ACTIONS
    assert scrubbed["additionalProperties"] is False


def test_substrate_is_a_migrated_ltp_v2_family_for_summarize():
    from lingtai.kernel.tool_result_summary import (
        _LTP_V2_MIGRATED_FAMILIES,
        summary_requested,
    )

    assert "substrate" in _LTP_V2_MIGRATED_FAMILIES
    assert summary_requested({"summarize": True}, "substrate") is True
    assert summary_requested({"summarize": False}, "substrate") is False


def test_substrate_is_blacklisted_for_emanations():
    from lingtai.tools.daemon import EMANATION_BLACKLIST

    assert "substrate" in EMANATION_BLACKLIST


# ---------------------------------------------------------------------------
# Each action returns its own intended manual
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("action", EXPECTED_ACTIONS)
def test_each_action_returns_its_intended_manual(tmp_path, action):
    agent = _agent(tmp_path)
    try:
        result = _call(agent, action)
        assert result["status"] == "ok"
        assert result["manual"].strip()
        path = result["manual_path"]
        assert path.endswith(
            f".library/intrinsic/capabilities/{EXPECTED_MANUAL_DIR[action]}/SKILL.md"
        ), path
    finally:
        agent.stop(timeout=1.0)


def test_the_five_manuals_are_all_distinct(tmp_path):
    agent = _agent(tmp_path)
    try:
        bodies = {a: _call(agent, a)["manual"] for a in EXPECTED_ACTIONS}
        assert len(set(bodies.values())) == len(EXPECTED_ACTIONS)
    finally:
        agent.stop(timeout=1.0)


def test_router_manual_is_a_routing_table_naming_all_four_domains(tmp_path):
    agent = _agent(tmp_path)
    try:
        body = _call(agent, "manual")["manual"]
        for domain in ("pad", "lingtai", "knowledge", "skills"):
            assert f'action="{domain}"' in body
        # It teaches the shared mutation/rebuild model rather than duplicating
        # the domain manuals it points at.
        assert "file.write" in body and "file.edit" in body
        assert 'context(action="rebuild"' in body
    finally:
        agent.stop(timeout=1.0)


# ---------------------------------------------------------------------------
# Returned-body accuracy (live-Agent lesson, head f575ec6a)
# ---------------------------------------------------------------------------
#
# A live agent called substrate(action='knowledge'|'skills') and got manuals
# that still taught retired public roots, a retired two-action surface, and
# pre-#1073/#1078 call shapes. Schema-level tests cannot catch that: the wire is
# correct while the *returned text* is wrong. These pin the returned bodies.

#: Substrings that must never reappear in a returned manual body, with the
#: reason each one is wrong. Keyed by the substrate action that returns it.
STALE_BODY_CLAIMS = {
    "knowledge": [
        # A. the retired public root, claimed in the present tense
        ("registers exactly one", "claims knowledge still registers a public tool"),
        ("tool, also named `knowledge`", "names a retired public knowledge root"),
        # A. remnants of the retired info|manual two-action surface
        ("both actions", "assumes the retired two-action surface"),
        ("settings/knowledge.", "names a retired per-domain settings address"),
    ],
    "skills": [
        # B. pre-current call shapes that would fail if a model copied them
        ("system({", "teaches the pre-LTP-v2 flat system call shape"),
        ("shell({", "teaches the pre-LTP-v2 flat shell call shape"),
        # B. an intrinsic bundle that no longer exists
        ("psyche/", "names the dissolved psyche intrinsic"),
        # B. refresh-only apply path, superseded by active context.rebuild
        ("ends with a refresh.", "teaches refresh as the only apply path"),
        ("settings/skills.json", "names a retired per-domain settings address"),
    ],
}

#: Substrings that must be present, proving the corrected current route.
REQUIRED_BODY_ROUTES = {
    "knowledge": [
        'substrate(action="knowledge"',
        'file(action="write"',
        'file(action="read"',
        'context(action="rebuild"',
    ],
    "skills": [
        'substrate(action="skills"',
        'context(action="rebuild"',
        'shell(action="run"',
        'file(action="read"',
        # The config-owner path keeps the exact refresh envelope.
        'system(action="refresh"',
        '"revert_preset": null',
    ],
}


#: Every ``file`` child's exact required input fields, read from the live schema
#: rather than hardcoded, so a schema change breaks this test instead of silently
#: letting an undispatchable snippet ship.
def _file_required_fields():
    from lingtai.tools.file import get_schema

    branches = get_schema()["properties"]["input"]["oneOf"]
    return {b["title"].split()[0]: list(b.get("required", [])) for b in branches}


def _file_snippets(body):
    """Yield ``(action, snippet)`` for every inline ``file(action="...")`` call.

    A snippet runs to the closing ``reasoning="..."`` so a call wrapped across
    source lines is still captured whole.
    """
    import re

    for match in re.finditer(
        r'file\(action="(\w+)",\s*(.*?)reasoning=', body, flags=re.S
    ):
        yield match.group(1), match.group(0)


@pytest.mark.parametrize("action", ["knowledge", "skills"])
def test_returned_manual_file_calls_are_dispatchable(tmp_path, action):
    """Every displayed ``file(...)`` call carries that child's full strict input.

    The `file` children declare every field as required — including the nullable
    `offset`/`limit`/`max_chars` on `read` — so an abbreviated snippet a model
    copies verbatim is rejected before dispatch. A manual that ships one is
    teaching a call that cannot work.
    """
    required = _file_required_fields()

    agent = _agent(tmp_path, capabilities={"knowledge": {}, "skills": {}})
    try:
        body = _call(agent, action)["manual"]
        snippets = list(_file_snippets(body))
        assert snippets, f"{action} manual shows no file(...) call to check"

        for file_action, snippet in snippets:
            assert file_action in required, (
                f"{action} manual shows unknown file action {file_action!r}"
            )
            for field in required[file_action]:
                assert f'"{field}"' in snippet, (
                    f"{action} manual's file(action={file_action!r}) snippet omits "
                    f"required input field {field!r}: {snippet.strip()!r}"
                )
    finally:
        agent.stop(timeout=1.0)


@pytest.mark.parametrize("action", ["knowledge", "skills"])
def test_returned_manual_has_no_abbreviated_file_calls(tmp_path, action):
    """Reject the ``file(action="grep", ...)`` elision that hid missing fields."""
    import re

    agent = _agent(tmp_path, capabilities={"knowledge": {}, "skills": {}})
    try:
        body = _call(agent, action)["manual"]
        elided = re.findall(r'file\(action="\w+",\s*\.\.\.', body)
        assert not elided, (
            f"{action} manual abbreviates a file call instead of showing its "
            f"full strict input: {elided}"
        )
    finally:
        agent.stop(timeout=1.0)


@pytest.mark.parametrize("action", sorted(STALE_BODY_CLAIMS))
def test_returned_manual_body_has_no_stale_claims(tmp_path, action):
    agent = _agent(tmp_path, capabilities={"knowledge": {}, "skills": {}})
    try:
        body = _call(agent, action)["manual"]
        for needle, why in STALE_BODY_CLAIMS[action]:
            assert needle not in body, f"{action} manual {why}: {needle!r}"
    finally:
        agent.stop(timeout=1.0)


@pytest.mark.parametrize("action", sorted(REQUIRED_BODY_ROUTES))
def test_returned_manual_body_teaches_the_current_routes(tmp_path, action):
    agent = _agent(tmp_path, capabilities={"knowledge": {}, "skills": {}})
    try:
        body = _call(agent, action)["manual"]
        for needle in REQUIRED_BODY_ROUTES[action]:
            assert needle in body, f"{action} manual lost the current route {needle!r}"
    finally:
        agent.stop(timeout=1.0)


def test_no_returned_manual_teaches_a_retired_public_root(tmp_path):
    """No body may show a retired root as an executable call."""
    agent = _agent(tmp_path, capabilities={"knowledge": {}, "skills": {}})
    try:
        for action in EXPECTED_ACTIONS:
            body = _call(agent, action)["manual"]
            for retired in ("pad", "lingtai", "knowledge", "skills"):
                assert f"{retired}(action=" not in body, (
                    f"{action} manual teaches the retired {retired}(action=...) root"
                )
            assert "pad.append" not in body
            assert "knowledge.info" not in body
            assert "skills.info" not in body
    finally:
        agent.stop(timeout=1.0)


def test_manual_result_has_no_double_wrap(tmp_path):
    agent = _agent(tmp_path)
    try:
        result = _call(agent, "manual")
        assert sorted(result) == ["manual", "manual_path", "status"]
        assert "content" not in result and "structuredContent" not in result
    finally:
        agent.stop(timeout=1.0)


def test_missing_manual_degrades_with_the_exact_loader_message(tmp_path):
    agent = _agent(tmp_path)
    try:
        installed = (
            agent._working_dir / ".library" / "intrinsic" / "capabilities"
            / "substrate-manual" / "SKILL.md"
        )
        installed.unlink()
        result = _call(agent, "manual")
        assert result["status"] == "degraded"
        assert result["manual"] == ""
        assert "substrate-manual manual missing" in result["error"]
    finally:
        agent.stop(timeout=1.0)


# ---------------------------------------------------------------------------
# Read-only: nothing mutates disk or prompt
# ---------------------------------------------------------------------------

def test_no_action_mutates_disk_or_prompt(tmp_path):
    agent = _agent(tmp_path)
    try:
        before_fs = _fs_digest(agent._working_dir)
        before_prompt = agent._build_system_prompt()
        before_sections = dict(agent._prompt_manager._sections)

        for action in EXPECTED_ACTIONS:
            _call(agent, action)

        assert _fs_digest(agent._working_dir) == before_fs
        assert agent._build_system_prompt() == before_prompt
        assert dict(agent._prompt_manager._sections) == before_sections
    finally:
        agent.stop(timeout=1.0)


def test_manual_actions_never_scan_a_catalog(tmp_path, monkeypatch):
    """No substrate action may reach a catalog scan or the legacy migration."""
    from lingtai.tools import knowledge as knowledge_tool
    from lingtai.tools import skills as skills_tool

    agent = _agent(tmp_path)
    try:
        def _boom(*_a, **_k):  # pragma: no cover - must never run
            raise AssertionError("a substrate manual action scanned a catalog")

        monkeypatch.setattr(knowledge_tool, "_compose_catalog", _boom)
        monkeypatch.setattr(knowledge_tool, "_reconcile", _boom)
        monkeypatch.setattr(knowledge_tool, "_migrate_legacy_json", _boom)
        monkeypatch.setattr(skills_tool, "_reconcile", _boom)

        for action in EXPECTED_ACTIONS:
            assert _call(agent, action)["status"] == "ok"
    finally:
        agent.stop(timeout=1.0)


# ---------------------------------------------------------------------------
# Fail-closed dispatch
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "action", ["append", "info", "edit", "load", "update", "", None, [], {}]
)
def test_unknown_or_retired_action_is_rejected(tmp_path, action):
    agent = _agent(tmp_path)
    try:
        result = _call(agent, action)
        assert "Unknown substrate action" in result["error"]
        assert "pad, lingtai, knowledge, skills, manual" in result["error"]
    finally:
        agent.stop(timeout=1.0)


@pytest.mark.parametrize("action", EXPECTED_ACTIONS)
def test_any_input_key_is_rejected_before_the_manual_is_read(tmp_path, action, monkeypatch):
    from lingtai.tools import _manual as manual_loader

    agent = _agent(tmp_path)
    try:
        def _boom(*_a, **_k):  # pragma: no cover - must never run
            raise AssertionError("manual was loaded despite an invalid input key")

        monkeypatch.setattr(manual_loader, "load_installed_manual", _boom)
        result = _call(agent, action, {"files": ["x"]})
        assert result["error_code"] == "INVALID_ARGUMENT"
        assert result["message"] == "unsupported substrate input field"
    finally:
        agent.stop(timeout=1.0)


def test_non_object_input_and_bad_summarize_are_rejected(tmp_path):
    agent = _agent(tmp_path)
    try:
        assert _call(agent, "manual", "nope")["error_code"] == "INVALID_ARGUMENT"
        bad = _call(agent, "manual", summarize="yes")
        assert bad["error_code"] == "INVALID_ARGUMENT"
        assert bad["message"] == "summarize must be a boolean"
    finally:
        agent.stop(timeout=1.0)


def test_unknown_root_field_is_rejected(tmp_path):
    agent = _agent(tmp_path)
    try:
        result = _call(agent, "manual", parameters={"x": 1})
        assert result["error_code"] == "INVALID_ARGUMENT"
        assert result["message"] == "unsupported substrate argument"
    finally:
        agent.stop(timeout=1.0)


def test_envelope_metadata_never_reaches_a_child(tmp_path):
    """``reasoning``/``_reasoning``/``summarize``/``_tc_id`` are not child input."""
    agent = _agent(tmp_path)
    try:
        result = _call(
            agent, "manual",
            reasoning="r", _reasoning="ir", summarize=False, _tc_id="tc-1",
        )
        assert result["status"] == "ok"
        assert result["manual"].strip()
    finally:
        agent.stop(timeout=1.0)


# ---------------------------------------------------------------------------
# The four former public roots are gone, with no alias
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("root", ["pad", "lingtai", "knowledge", "skills"])
def test_retired_public_roots_are_not_registered(tmp_path, root):
    from lingtai.tools.registry import INTRINSICS

    assert root not in INTRINSICS
    agent = _agent(tmp_path)
    try:
        assert root not in agent._intrinsics
        assert root not in agent._tool_handlers
        assert root not in [s.name for s in agent._build_tool_schemas()]
    finally:
        agent.stop(timeout=1.0)


@pytest.mark.parametrize("pkg", ["pad", "lingtai", "knowledge", "skills"])
def test_retired_domain_packages_expose_no_public_tool_surface(pkg):
    """They survive as private domain owners only — no schema, no dispatch."""
    module = importlib.import_module(f"lingtai.tools.{pkg}")
    for attribute in ("get_schema", "get_description", "handle", "ACTION_ORDER"):
        assert not hasattr(module, attribute), f"{pkg}.{attribute}"


def test_retired_actions_have_no_implementation_left():
    """``pad.append`` is gone as an action AND as a handler."""
    from lingtai.tools import pad as pad_tool

    assert not hasattr(pad_tool, "_pad_append")
    from lingtai.tools.pad import _pad

    assert not hasattr(_pad, "_pad_append")
    assert not hasattr(_pad, "_save_append_list")


@pytest.mark.parametrize("name", ["pad", "lingtai", "knowledge", "skills"])
def test_retired_roots_are_not_ltp_v2_summarize_families(name):
    from lingtai.kernel.tool_result_summary import _LTP_V2_MIGRATED_FAMILIES

    assert name not in _LTP_V2_MIGRATED_FAMILIES


# ---------------------------------------------------------------------------
# Fail-loud full reconstruction (tools/context/CONTRACT.md)
# ---------------------------------------------------------------------------
#
# The Skills and Knowledge catalogs are two of the four durable domains the one
# reconstruction contract must recompose. A composer failure must abort the whole
# rebuild: `context.rebuild` returns `context_reconstruction_failed` and applies
# no summaries and requests no provider replay. Catching and continuing would
# publish a prompt missing a durable section while reporting success.

@pytest.mark.parametrize(
    "module_name,attr",
    [("lingtai.tools.skills", "_reconcile"),
     ("lingtai.tools.knowledge", "_compose_catalog")],
)
def test_catalog_composer_failure_fails_the_whole_rebuild(
    tmp_path, monkeypatch, module_name, attr
):
    import importlib

    from lingtai.tools import context as context_tool

    agent = _agent(tmp_path, capabilities={"knowledge": {}, "skills": {}})
    try:
        agent._prompt_manager.write_section("comment", "CURRENT-COMMENT")
        module = importlib.import_module(module_name)

        def _boom(*_a, **_k):
            raise RuntimeError("catalog scan exploded")

        monkeypatch.setattr(module, attr, _boom)

        # Instrument the two stages that must NOT be reached. `_flush_system_prompt`
        # is the single final publish (contract step 3); `_summarize_engine` is the
        # entry point for recording/applying summaries and requesting provider
        # replay (contract steps 4-5). Neither may run when a composer raises.
        publishes: list[int] = []
        original_flush = agent._flush_system_prompt
        agent._flush_system_prompt = (
            lambda *a, **k: (publishes.append(1), original_flush(*a, **k))[1]
        )

        summarize_calls: list[dict] = []

        def _sentinel_engine(_agent, args):  # pragma: no cover - must never run
            summarize_calls.append(args)
            raise AssertionError(
                "summary processing/provider replay was reached despite a "
                "reconstruction failure"
            )

        monkeypatch.setattr(context_tool, "_summarize_engine", _sentinel_engine)

        # Nonempty `items` makes the skipped stage unambiguous: with pending
        # summaries supplied, reaching step 4 at all would call the engine.
        result = context_tool.handle(
            agent,
            {
                "action": "rebuild",
                "input": {"items": [{"tool_call_id": "tc-1", "summary": "s"}]},
                "reasoning": "r",
            },
        )
        agent._flush_system_prompt = original_flush

        # Fail loud: the typed reconstruction error and no success marker.
        assert result["status"] == "error"
        assert result["reason"] == "context_reconstruction_failed"
        assert "prompt_reconstructed" not in result
        # Ordering proof: no final publish, and the summary/replay stage never ran.
        assert publishes == []
        assert summarize_calls == []
        # And no partially composed prompt was left behind.
        assert agent._prompt_manager.read_section("comment") == "CURRENT-COMMENT"
    finally:
        agent.stop(timeout=1.0)


def test_successful_rebuild_still_publishes_exactly_once(tmp_path):
    """The fail-loud path must not disturb the single-publish invariant."""
    agent = _agent(tmp_path, capabilities={"knowledge": {}, "skills": {}})
    try:
        system = agent._working_dir / "system"
        system.mkdir(exist_ok=True)
        (system / "pad.md").write_text("PAD-BODY", encoding="utf-8")
        (system / "lingtai.md").write_text("I AM", encoding="utf-8")

        publishes = []
        original = agent._flush_system_prompt

        def _counting(*args, **kwargs):
            publishes.append(1)
            return original(*args, **kwargs)

        agent._flush_system_prompt = _counting
        agent._reconstruct_context()
        agent._flush_system_prompt = original

        assert publishes == [1]
        read = agent._prompt_manager.read_section
        assert "PAD-BODY" in read("pad")
        assert "I AM" in read("character")
        assert read("skills")
        assert "knowledge" in agent._prompt_manager._sections
    finally:
        agent.stop(timeout=1.0)
