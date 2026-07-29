"""Focused contract regressions for the single public ``web`` capability."""
from __future__ import annotations

import gzip
import json
import os
from pathlib import Path

import pytest

from lingtai.tools.registry import BUILTIN_TOOLS, get_all_providers, normalize_capabilities
from lingtai.tools.web_search import setup
from lingtai.tools.web_search.settings import _bounded_error
from lingtai.tools.browser.port import TransportResponse


class _Agent:
    def __init__(self, root: Path) -> None:
        self._working_dir = root

    def add_tool(self, *args, **kwargs) -> None:
        self.tool_name = args[0]
        self.schema = kwargs["schema"]
        self.handler = kwargs["handler"]


class _Search:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def search(self, query: str):
        self.calls.append(query)
        return [type("Result", (), {"title": "title", "url": "https://example.test/r", "snippet": "snippet"})()]


class _Port:
    def __init__(self) -> None:
        self.requests: list[str] = []

    def resolve(self, hostname: str, *, timeout_s: float):
        return ["93.184.216.34"]

    def request(self, url: str, *, resolved, max_bytes: int, timeout_s: float):
        self.requests.append(url)
        return TransportResponse(200, {"content-type": "text/html"}, b"<p>page</p>", False, url)


def test_registry_has_one_web_surface_and_preserves_opaque_identity():
    assert BUILTIN_TOOLS["web"] == "lingtai.tools.web_search"
    assert "browser" not in BUILTIN_TOOLS
    assert "web_search" not in BUILTIN_TOOLS
    assert set(get_all_providers()) >= {"web"}
    assert "browser" not in get_all_providers()
    assert "web_search" not in get_all_providers()
    service = object()
    port = object()
    normalized = normalize_capabilities({"web_search": {"search_service": service, "browser_port": port}})
    assert normalized == {"web": {"search_service": service, "browser_port": port}}


def test_search_link_ref_browse_uses_same_agent_state(tmp_path):
    agent = _Agent(tmp_path)
    search = _Search()
    port = _Port()
    manager = setup(agent, search_service=search, browser_port=port)
    result = manager.handle({"action": "search", "input": {"query": "question"}})
    assert result["status"] == "ok"
    assert result["action"] == "search"
    assert result["count"] == 1
    assert result["results"][0]["link_ref"]
    assert not port.requests
    browsed = manager.handle({
        "action": "browse",
        "input": {
            "url": None,
            "link_ref": result["results"][0]["link_ref"],
            "cursor": None,
            "extract": None,
            "max_chars": None,
        },
    })
    assert browsed["status"] == "ok"
    assert browsed["action"] == "browse"
    assert len(port.requests) == 1
    assert search.calls == ["question"]


def test_settings_are_strict_reread_and_do_not_mutate_environment(tmp_path):
    agent = _Agent(tmp_path)
    search = _Search()
    manager = setup(agent, search_service=search, browser_port=_Port())
    settings = tmp_path / "settings" / "web.search.json"
    settings.parent.mkdir()
    settings.write_text(json.dumps({"schema_version": 1, "engine": "not-admitted"}))
    failure = manager.handle({"action": "search", "input": {"query": "x"}})
    assert failure["status"] == "failed"
    assert failure["current_setting"]["source"] == "settings_error"
    assert failure["current_setting"]["engine"] is None
    before = dict(os.environ)
    rejected = manager.handle({
        "action": "search",
        "input": {"query": "x", "engine": "duckduckgo"},
    })
    assert rejected["error_code"] == "INVALID_ARGUMENT"
    assert dict(os.environ) == before
    settings.write_text(json.dumps({"schema_version": 1, "engine": "duckduckgo"}))
    success = manager.handle({"action": "search", "input": {"query": "x"}})
    assert success["status"] == "ok"
    assert success["current_setting"]["source"] == "settings/web.search.json"
    assert success["current_setting"]["settings_revision"]


def test_missing_and_operator_defaults_report_the_computed_source(tmp_path, monkeypatch):
    missing_env = "MISSING_WEB_SENTINEL"
    monkeypatch.delenv(missing_env, raising=False)
    built_agent = _Agent(tmp_path / "built")
    built = setup(built_agent, browser_port=_Port())
    built_result = built.handle({"action": "search", "input": {"query": ""}})
    assert built_result["current_setting"]["source"] == "built_in_default"
    assert built_result["current_setting"]["engine"] == "duckduckgo"

    operator_agent = _Agent(tmp_path / "operator")
    operator = setup(
        operator_agent,
        provider="openai",
        api_key_env=missing_env,
        browser_port=_Port(),
    )
    result = operator.handle({"action": "search", "input": {"query": "question"}})
    assert result["error_code"] == "SEARCH_ENGINE_UNAVAILABLE"
    assert result["current_setting"]["source"] == "operator_default"
    statuses = result["current_setting"]["available_engines"]
    assert {item["api_key_env"] for item in statuses if item["status"] == "credential_missing"} == {"MISSING_WEB_SENTINEL"}
    assert "MISSING_WEB_SENTINEL_VALUE" not in json.dumps(result)


def test_settings_v1_rejects_boolean_and_float_schema_versions(tmp_path):
    agent = _Agent(tmp_path)
    manager = setup(agent, search_service=_Search(), browser_port=_Port())
    settings = tmp_path / "settings" / "web.search.json"
    settings.parent.mkdir()
    for version in (True, 1.0):
        settings.write_text(json.dumps({"schema_version": version, "engine": "duckduckgo"}))
        result = manager.handle({"action": "search", "input": {"query": "question"}})
        assert result["error_code"] == "WEB_SETTINGS_INVALID"
        assert result["current_setting"]["engine"] is None


def test_invalid_settings_keep_manual_and_browse_usable(tmp_path):
    agent = _Agent(tmp_path)
    port = _Port()
    manager = setup(agent, search_service=_Search(), browser_port=port)
    settings = tmp_path / "settings" / "web.search.json"
    settings.parent.mkdir()
    settings.write_text("{not-json")
    manual = manager.handle({"action": "manual", "input": {}})
    assert manual["action"] == "manual"
    browsed = manager.handle({
        "action": "browse",
        "input": {
            "url": "https://example.test",
            "link_ref": None,
            "cursor": None,
            "extract": None,
            "max_chars": None,
        },
    })
    assert browsed["action"] == "browse"
    # Browse does not own settings/web.search.json: it reports a truthful
    # no-read diagnostic, never the settings-file error observed by search.
    assert browsed["current_setting"]["source"] == "not_applicable"
    assert "settings_error" not in browsed["current_setting"]


@pytest.mark.parametrize(
    "payload,description",
    [
        ('{"schema_version": 1, "engine": "duckduckgo", "extra": "x"}', "unknown field"),
        ('{"schema_version": 1, "engine": "duckduckgo", "schema_version": 1}', "duplicate field (raw JSON)"),
        ('{"schema_version": 1}', "missing engine field"),
        ('{"engine": "duckduckgo"}', "missing schema_version field"),
    ],
)
def test_settings_rejects_unknown_missing_and_duplicate_fields(tmp_path, payload, description):
    agent = _Agent(tmp_path)
    manager = setup(agent, search_service=_Search(), browser_port=_Port())
    settings = tmp_path / "settings" / "web.search.json"
    settings.parent.mkdir()
    settings.write_text(payload)
    result = manager.handle({"action": "search", "input": {"query": "q"}})
    assert result["error_code"] == "WEB_SETTINGS_INVALID", description
    assert result["current_setting"]["engine"] is None


def test_settings_rejects_symlink_and_non_regular_file(tmp_path):
    agent = _Agent(tmp_path)
    manager = setup(agent, search_service=_Search(), browser_port=_Port())
    settings_dir = tmp_path / "settings"
    settings_dir.mkdir()
    real = tmp_path / "elsewhere.json"
    real.write_text(json.dumps({"schema_version": 1, "engine": "duckduckgo"}))
    (settings_dir / "web.search.json").symlink_to(real)
    result = manager.handle({"action": "search", "input": {"query": "q"}})
    assert result["error_code"] == "WEB_SETTINGS_INVALID"
    assert result["current_setting"]["engine"] is None


def test_settings_changed_file_is_observed_on_next_call(tmp_path):
    agent = _Agent(tmp_path)
    manager = setup(agent, search_service=_Search(), browser_port=_Port())
    settings = tmp_path / "settings" / "web.search.json"
    settings.parent.mkdir()
    settings.write_text(json.dumps({"schema_version": 1, "engine": "duckduckgo"}))
    first = manager.handle({"action": "search", "input": {"query": "q"}})
    first_revision = first["current_setting"]["settings_revision"]
    settings.write_text("{not-json")
    second = manager.handle({"action": "search", "input": {"query": "q"}})
    assert second["error_code"] == "WEB_SETTINGS_INVALID"
    settings.write_text(json.dumps({"schema_version": 1, "engine": "duckduckgo"}))
    third = manager.handle({"action": "search", "input": {"query": "q"}})
    assert third["status"] == "ok"
    assert third["current_setting"]["settings_revision"] == first_revision


def test_no_old_family_owned_web_json_cross_read(tmp_path):
    """A stale/legacy family-owned settings/web.json must never be consulted;
    only the action-owned settings/web.search.json is read."""
    agent = _Agent(tmp_path)
    manager = setup(agent, search_service=_Search(), browser_port=_Port())
    settings_dir = tmp_path / "settings"
    settings_dir.mkdir()
    (settings_dir / "web.json").write_text(
        json.dumps({"schema_version": 1, "search": {"engine": "not-admitted"}})
    )
    # The old-path file is present but must be ignored: no web.search.json
    # exists, so this call takes the built-in/operator default, not the
    # invalid selector recorded in the legacy family-owned file.
    result = manager.handle({"action": "search", "input": {"query": "q"}})
    assert result["status"] == "ok"
    assert result["current_setting"]["source"] != "settings/web.json"


def test_browse_and_manual_never_construct_a_provider_or_touch_search_settings(tmp_path, monkeypatch):
    agent = _Agent(tmp_path)
    port = _Port()
    manager = setup(agent, search_service=_Search(), browser_port=port)
    settings = tmp_path / "settings" / "web.search.json"
    settings.parent.mkdir()
    settings.write_text("{not-json")

    def fail_read_settings(*args, **kwargs):
        raise AssertionError("browse/manual must never read settings/web.search.json")

    monkeypatch.setattr("lingtai.tools.web_search.read_settings", fail_read_settings)

    service_calls: list[str] = []
    original_service_for = manager._service_for

    def spy(name, spec):
        service_calls.append(name)
        return original_service_for(name, spec)

    manager._service_for = spy

    manual = manager.handle({"action": "manual", "input": {}})
    assert manual["action"] == "manual"
    assert manual["current_setting"]["source"] == "not_applicable"

    browsed = manager.handle({
        "action": "browse",
        "input": {
            "url": "https://example.test", "link_ref": None, "cursor": None,
            "extract": None, "max_chars": None,
        },
    })
    assert browsed["status"] == "ok"
    assert browsed["current_setting"]["source"] == "not_applicable"

    assert service_calls == []


@pytest.mark.parametrize(
    "args,expected_action",
    [
        ({"action": "manual", "input": {"bogus": 1}}, "manual"),
        ({"action": "browse", "input": {"bogus": 1}}, "browse"),
    ],
)
def test_browse_and_manual_invalid_argument_paths_never_read_settings(tmp_path, monkeypatch, args, expected_action):
    agent = _Agent(tmp_path)
    manager = setup(agent, search_service=_Search(), browser_port=_Port())
    settings = tmp_path / "settings" / "web.search.json"
    settings.parent.mkdir()
    settings.write_text("{not-json")

    def fail_read_settings(*args, **kwargs):
        raise AssertionError("an invalid-argument path must never read settings/web.search.json")

    monkeypatch.setattr("lingtai.tools.web_search.read_settings", fail_read_settings)

    result = manager.handle(args)
    assert result["status"] == "failed"
    assert result["action"] == expected_action
    assert result["error_code"] == "INVALID_ARGUMENT"
    assert result["current_setting"]["source"] == "not_applicable"
    assert "settings_error" not in result["current_setting"]


def test_oserror_diagnostics_never_echo_an_absolute_settings_path():
    absolute = "/private/secret-agent/settings/web.search.json"
    message = _bounded_error(PermissionError(13, "Permission denied", absolute))
    assert absolute not in message
    assert "settings/web.search.json" in message


def test_lazy_initialization_failure_updates_availability_truth(tmp_path, monkeypatch):
    secret = "DIRECT_SECRET_SENTINEL"

    def fail_factory(*args, **kwargs):
        raise RuntimeError("provider boot failed")

    monkeypatch.setattr("lingtai.services.websearch.create_search_service", fail_factory)
    manager = setup(
        _Agent(tmp_path),
        provider="openai",
        api_key=secret,
        browser_port=_Port(),
    )
    result = manager.handle({"action": "search", "input": {"query": "question"}})
    assert result["error_code"] == "SEARCH_ENGINE_UNAVAILABLE"
    statuses = result["current_setting"]["available_engine_status"]
    assert statuses == {"openai": "initialization_failed"}
    assert secret not in json.dumps(result)


def test_engine_selector_and_default_are_validated_at_composition(tmp_path):
    with pytest.raises(ValueError):
        setup(_Agent(tmp_path / "bad-name"), engines={"bad/name": {"provider": "duckduckgo"}}, browser_port=_Port())
    with pytest.raises(ValueError):
        setup(
            _Agent(tmp_path / "bad-default"),
            engines={"duckduckgo": {"provider": "duckduckgo"}},
            default_engine="gemini",
            browser_port=_Port(),
        )


def test_schema_root_is_closed_action_input_reasoning_summarize(tmp_path):
    from lingtai.tools.web_search import get_schema

    schema = get_schema()
    assert schema["additionalProperties"] is False
    # ``reasoning`` is REQUIRED Host InvocationContext/audit metadata; the
    # family's own get_schema() declares it (and its required-ness) itself —
    # this is not left to Agent schema composition, which only re-injects the
    # identical property text into every tool's ``properties`` and never
    # touches ``required``.
    assert schema["required"] == ["action", "input", "reasoning"]
    assert set(schema["properties"]) == {"action", "input", "reasoning", "summarize"}
    reasoning_prop = schema["properties"]["reasoning"]
    assert reasoning_prop["type"] == "string"
    summarize_prop = schema["properties"]["summarize"]
    assert summarize_prop["type"] == "boolean"
    # No public `summary` alias, and no branch admits `reasoning`/`_reasoning`/
    # `summarize` inside its own input.
    for branch in schema["properties"]["input"]["oneOf"]:
        assert "summary" not in branch["properties"]
        assert "summarize" not in branch["properties"]
        assert "reasoning" not in branch["properties"]
        assert "_reasoning" not in branch["properties"]


def test_summarize_is_stripped_before_dispatch_and_not_leaked_to_search(tmp_path):
    agent = _Agent(tmp_path)
    search = _Search()
    manager = setup(agent, search_service=search, browser_port=_Port())
    result = manager.handle({
        "action": "search", "input": {"query": "question"}, "summarize": False,
    })
    assert result["status"] == "ok"

    captured_args = {}
    original_search = manager._search

    def spy(args, snapshot, diagnostic):
        captured_args.update(args)
        return original_search(args, snapshot, diagnostic)

    manager._search = spy
    manager.handle({"action": "search", "input": {"query": "q2"}, "summarize": True})
    assert "summarize" not in captured_args


def test_summarize_true_reaches_manual_and_browse_without_leaking_into_input(tmp_path):
    agent = _Agent(tmp_path)
    manager = setup(agent, search_service=_Search(), browser_port=_Port())
    manual = manager.handle({"action": "manual", "input": {}, "summarize": True})
    assert manual["action"] == "manual"
    browsed = manager.handle({
        "action": "browse",
        "input": {
            "url": "https://example.test", "link_ref": None, "cursor": None,
            "extract": None, "max_chars": None,
        },
        "summarize": True,
    })
    assert browsed["status"] == "ok"


def test_non_boolean_summarize_fails_loudly(tmp_path):
    agent = _Agent(tmp_path)
    manager = setup(agent, search_service=_Search(), browser_port=_Port())
    for bad in ("true", 1, [], {}):
        result = manager.handle({
            "action": "search", "input": {"query": "q"}, "summarize": bad,
        })
        assert result["status"] == "failed"
        assert result["error_code"] == "INVALID_ARGUMENT"


def test_summarize_absent_is_default_false_and_unaffected(tmp_path):
    agent = _Agent(tmp_path)
    manager = setup(agent, search_service=_Search(), browser_port=_Port())
    result = manager.handle({"action": "search", "input": {"query": "q"}})
    assert result["status"] == "ok"


def test_search_caps_an_unbounded_provider_iterable(tmp_path):
    class GeneratorSearch:
        def search(self, query):
            def results():
                index = 0
                while True:
                    yield {"title": str(index), "url": f"https://example.test/{index}", "snippet": "s"}
                    index += 1
            return results()

    manager = setup(_Agent(tmp_path), search_service=GeneratorSearch(), browser_port=_Port())
    result = manager.handle({"action": "search", "input": {"query": "question"}})
    assert result["status"] == "ok"
    assert result["count"] == 20
    assert len(result["results"]) == 20


class _CompressedPort:
    """Origin that answers 200 text/html with an unnegotiated gzip payload."""

    def resolve(self, hostname: str, *, timeout_s: float):
        return ["93.184.216.34"]

    def request(self, url: str, *, resolved, max_bytes: int, timeout_s: float):
        paragraphs = "".join(
            f"<p>Python 3.{n}.{n % 7} was released on day {n}; download artifact {n * 7919}.</p>"
            for n in range(400)
        )
        html = f"<html><body><main>{paragraphs}</main></body></html>".encode("utf-8")
        return TransportResponse(200, {"content-type": "text/html; charset=utf-8"}, gzip.compress(html), False, url)


def test_undecodable_body_surfaces_as_typed_failure_on_the_public_web_result(tmp_path):
    """Result/wire parity: degraded content is a typed failure, not usable page content."""
    agent = _Agent(tmp_path)
    manager = setup(agent, search_service=_Search(), browser_port=_CompressedPort())
    result = manager.handle(
        {"action": "browse", "input": {"url": "https://public.example/downloads/", "max_chars": 12_000}}
    )
    assert result["status"] == "failed"
    assert result["error_code"] == "NO_TEXT_BLOCKS"
    assert result["stage"] == "extract"
    assert result["http_status"] == 200
    assert result["action"] == "browse"
    assert "blocks" not in result
    assert result["current_setting"]["source"] == "not_applicable"
