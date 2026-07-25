"""Mechanical completeness and documentation-graph checks for the root registry."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import yaml


_REPO = Path(__file__).resolve().parents[1]
_REGISTRY = Path("ENVIRONMENT_VARIABLES.md")
_ROUTER = Path(
    "src/lingtai/intrinsic_skills/system-manual/reference/environment-variables/SKILL.md"
)
_ENV_NAME = re.compile(r"\bLINGTAI_[A-Z0-9_]+\b")
# Include source and test suffixes that can carry executable literals. The
# registry and this test are excluded below so the crawl cannot derive its
# answer from its assertions.
_CODE_SUFFIXES = {
    ".c",
    ".cc",
    ".cpp",
    ".h",
    ".hh",
    ".hpp",
    ".go",
    ".js",
    ".jsx",
    ".m",
    ".ps1",
    ".psm1",
    ".py",
    ".rs",
    ".sh",
    ".ts",
    ".tsx",
}
_EXCLUDED_DIRS = {
    ".git",
    ".hg",
    ".mypy_cache",
    ".pytest_cache",
    ".tox",
    ".venv",
    ".worktrees",
    "__pycache__",
    "build",
    "cache",
    "dist",
    "node_modules",
    "scratch",
    "target",
    "vendor",
    "venv",
    "worktree",
}
_REGISTRY_COLUMNS = [
    "Name",
    "Default",
    "Accepted values",
    "Scope",
    "Read/reload timing",
    "Invalid behavior",
    "Owner",
    "Security",
]


def _frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"missing frontmatter in {path}"
    metadata = yaml.safe_load(text.split("---\n", 2)[1])
    assert isinstance(metadata, dict), path
    return metadata


def _related_files(path: Path) -> set[str]:
    related = _frontmatter(path).get("related_files")
    assert isinstance(related, list) and related, path
    assert len(related) == len(set(related)), path
    return set(related)


def _registry_rows() -> list[tuple[str, ...]]:
    lines = (_REPO / _REGISTRY).read_text(encoding="utf-8").splitlines()
    header_index = next(
        index
        for index, line in enumerate(lines)
        if line.startswith("| Name | Default | Accepted values | Scope |")
    )
    header = tuple(cell.strip() for cell in lines[header_index].strip("|").split("|"))
    assert list(header) == _REGISTRY_COLUMNS

    rows: list[tuple[str, ...]] = []
    for line in lines[header_index + 2 :]:
        if not line.startswith("|"):
            continue
        cells = tuple(cell.strip() for cell in line.strip("|").split("|"))
        if len(cells) == len(_REGISTRY_COLUMNS) and re.fullmatch(
            r"`LINGTAI_[A-Z0-9_]+`", cells[0]
        ):
            rows.append(cells)
    return rows


def _python_string_literals(text: str) -> list[str]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


def _literal_environment_names(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix == ".py":
        values = _python_string_literals(text)
    else:
        values = [
            match.group(1)
            for match in re.finditer(r"[\"'`]([^\"'`\n]*)[\"'`]", text)
        ]
    return set().union(*(set(_ENV_NAME.findall(value)) for value in values))


def _code_sources() -> list[Path]:
    excluded = {_REPO / _REGISTRY, Path(__file__).resolve()}
    return sorted(
        path
        for path in _REPO.rglob("*")
        if path.is_file()
        and path.suffix in _CODE_SUFFIXES
        and path not in excluded
        and not any(part in _EXCLUDED_DIRS for part in path.relative_to(_REPO).parts)
    )


def _nearest_anatomy(source: Path) -> Path:
    for parent in (source.parent, *source.parents):
        candidate = parent / "ANATOMY.md"
        if candidate.exists():
            return candidate
        if parent == _REPO:
            break
    raise AssertionError(f"no owning ANATOMY.md for {source.relative_to(_REPO)}")


def test_registry_is_rooted_fixed_width_and_has_unique_canonical_rows() -> None:
    rows = _registry_rows()
    names = [row[0].strip("`") for row in rows]
    assert rows
    assert len(names) == len(set(names))
    assert all(len(row) == len(_REGISTRY_COLUMNS) for row in rows)


def test_literal_environment_names_are_registered_and_owning_anatomies_are_linked() -> None:
    rows = _registry_rows()
    registry_names = {row[0].strip("`") for row in rows}
    source_names: set[str] = set()
    owning_anatomies: set[str] = set()

    for source in _code_sources():
        names = _literal_environment_names(source)
        if not names:
            continue
        source_names.update(names)
        owning_anatomies.add(str(_nearest_anatomy(source).relative_to(_REPO)))

    assert source_names == registry_names, {
        "unregistered": sorted(source_names - registry_names),
        "unreferenced": sorted(registry_names - source_names),
    }
    registry_related = _related_files(_REPO / _REGISTRY)
    assert owning_anatomies <= registry_related, sorted(owning_anatomies - registry_related)


def test_registry_related_files_exist_and_link_back() -> None:
    registry_related = _related_files(_REPO / _REGISTRY)
    for related in registry_related:
        target = _REPO / related
        assert target.is_file(), related
        assert _REGISTRY.as_posix() in _related_files(target), related

    for root_document in (Path("ANATOMY.md"), Path("CONTRACT.md")):
        assert _REGISTRY.as_posix() in _related_files(_REPO / root_document)
        assert _REGISTRY.as_posix() in (
            (_REPO / root_document).read_text(encoding="utf-8")
        )


def test_nested_environment_skill_is_a_bounded_router() -> None:
    text = (_REPO / _ROUTER).read_text(encoding="utf-8")
    assert len(text.splitlines()) <= 40
    assert not re.search(r"^\|.*\|$", text, flags=re.MULTILINE)
    assert not _ENV_NAME.search(text)
    assert _REGISTRY.as_posix() in _related_files(_REPO / _ROUTER)
    assert "ENVIRONMENT_VARIABLES.md" in text
