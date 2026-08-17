"""Docs/routing contract for the DeepSeek Harness daemon-backend submanual.

The DeepSeek Harness child under the daemon CLI-backend router is a small
progressive-disclosure entrypoint: it routes agents to the installed CLI's
live help (via bash) and shows how to translate that help into the generic
``backend_options`` mechanism. It must never grow into a maintained flag
catalog. The generic conversion behavior and the deepseek runner/reserved
flag enforcement themselves are covered by
``tests/test_daemon_backend_options.py`` (see e.g.
``test_deepseek_cmd_appends_backend_argv_before_profile_lock``,
``test_deepseek_rejects_harness_owned_backend_options``,
``test_deepseek_patch_overlay_survives_validation``,
``test_deepseek_ask_is_explicitly_unsupported``) and are not re-tested here.
"""

import re
from pathlib import Path

import yaml

from lingtai.tools.daemon import (
    _BACKEND_ALIASES,
    _DEEPSEEK_RESERVED_BACKEND_FLAGS,
)

ROOT = Path(__file__).resolve().parents[1]
ROUTER = ROOT / "src/lingtai/tools/daemon/manual/reference/cli-backends/SKILL.md"
CHILD = (
    ROOT
    / "src/lingtai/tools/daemon/manual/reference/cli-backends"
    / "reference/backends/deepseek/SKILL.md"
)
CHILD_LOCATION = "reference/backends/deepseek/SKILL.md"


def _frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path} must start with YAML frontmatter"
    _blank, frontmatter, _body = text.split("---", 2)
    return yaml.safe_load(frontmatter) or {}


def _body(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    return text.split("---", 2)[2]


def test_router_has_yaml_catalog_entry_for_deepseek_child():
    text = ROUTER.read_text(encoding="utf-8")
    assert "## Nested reference catalog" in text
    catalog_section = text.split("## Nested reference catalog", 1)[1]
    match = re.search(r"```yaml\n(.*?)```", catalog_section, re.DOTALL)
    assert match, "nested reference catalog must be a fenced YAML block"
    entries = yaml.safe_load(match.group(1))
    deepseek_entries = [e for e in entries if e.get("location") == CHILD_LOCATION]
    assert len(deepseek_entries) == 1
    assert deepseek_entries[0]["name"] == "daemon-backend-deepseek"
    assert deepseek_entries[0]["description"].strip()


def test_router_routing_table_points_to_deepseek_child():
    text = ROUTER.read_text(encoding="utf-8")
    assert "## Routing table" in text
    table_rows = [
        line for line in text.splitlines()
        if line.startswith("|") and CHILD_LOCATION in line
    ]
    assert table_rows, "routing table must map DeepSeek flag needs to the child"


def test_deepseek_child_frontmatter_and_location():
    assert CHILD.is_file()
    meta = _frontmatter(CHILD)
    assert meta["name"] == "daemon-backend-deepseek"
    assert meta["description"].strip()


def test_deepseek_child_routes_to_live_help_and_generic_backend_options():
    body = _body(CHILD)
    # Live installed help is the authority — the child must send agents there.
    assert "dsh --help" in body
    assert "dsh --profile headless --help" in body
    # Translation goes through the existing generic mechanism, and the
    # high-value launcher-overlay example uses the official --patch knob.
    assert "backend_options" in body
    assert '"patch": "./dsh-model.yml"' in body
    # The CLI/provider owns the value vocabulary; no LingTai-side enum.
    assert "not validate, enumerate, or simulate" in body


def test_deepseek_child_names_canonical_id_and_limitations():
    body = _body(CHILD)
    # No alias is registered for deepseek; the child says so explicitly.
    assert "deepseek" not in _BACKEND_ALIASES
    assert "canonical backend name" in body
    # Every source-reserved harness flag is documented, exactly.
    for flag in _DEEPSEEK_RESERVED_BACKEND_FLAGS:
        assert f"`{flag}`" in body, flag
    # Current limitations and env wiring stated as they are implemented.
    assert 'daemon(action="ask", input={"id": ..., "message": ...})' in body
    assert "unsupported" in body
    assert "dsh-home" in body
    assert "DSH_HOME" in body
    assert "DEEPSEEK_API_KEY" in body
