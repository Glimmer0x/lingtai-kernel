"""ShellKind classifier unit tests (platform simulated via monkeypatch).

Covers the resolution precedence - explicit shell setting, ``LINGTAI_SHELL``
env override, then platform default (POSIX on Unix; PowerShell -> Git Bash
-> cmd.exe on Windows) - plus the model-facing kind metadata.
"""
from __future__ import annotations

import pytest

from lingtai.adapters.shell import resolve_shell_kind
from lingtai.tools.bash._shell_dialect import ShellKind


def test_posix_platform_defaults_to_posix_kind():
    assert resolve_shell_kind(os_name="posix") is ShellKind.POSIX


def test_windows_defaults_to_powershell_when_pwsh_discoverable(monkeypatch):
    monkeypatch.setattr(
        "lingtai.adapters.shell._discover_pwsh",
        lambda: "C:/Program Files/PowerShell/7/pwsh.exe",
    )
    assert resolve_shell_kind(os_name="nt") is ShellKind.POWERSHELL


def test_windows_falls_back_to_git_bash_without_pwsh(monkeypatch):
    monkeypatch.setattr("lingtai.adapters.shell._discover_pwsh", lambda: None)
    monkeypatch.setattr(
        "lingtai.adapters.windows.gitbash.discover_git_bash",
        lambda: r"C:\Program Files\Git\bin\bash.exe",
    )
    assert resolve_shell_kind(os_name="nt") is ShellKind.GITBASH


def test_windows_last_resort_is_cmd(monkeypatch):
    monkeypatch.setattr("lingtai.adapters.shell._discover_pwsh", lambda: None)
    monkeypatch.setattr("lingtai.adapters.windows.gitbash.discover_git_bash", lambda: None)
    assert resolve_shell_kind(os_name="nt") is ShellKind.CMD


def test_windows_never_auto_selects_wsl(monkeypatch):
    # Even with wsl.exe present, the default chain stops at cmd.exe; WSL is
    # opt-in via an explicit override.
    monkeypatch.setattr("lingtai.adapters.shell._discover_pwsh", lambda: None)
    monkeypatch.setattr("lingtai.adapters.windows.gitbash.discover_git_bash", lambda: None)
    monkeypatch.setattr(
        "lingtai.adapters.windows.wsl.discover_wsl",
        lambda: r"C:\Windows\System32\wsl.exe",
    )
    assert resolve_shell_kind(os_name="nt") is ShellKind.CMD


@pytest.mark.parametrize(
    "override, expected",
    [
        ("posix", ShellKind.POSIX),
        ("powershell", ShellKind.POWERSHELL),
        ("cmd", ShellKind.CMD),
        ("gitbash", ShellKind.GITBASH),
        ("wsl", ShellKind.WSL),
    ],
)
def test_env_override_wins_over_platform_default(override, expected):
    assert resolve_shell_kind(
        os_name="posix", env={"LINGTAI_SHELL": override},
    ) is expected


def test_env_override_is_case_insensitive():
    assert resolve_shell_kind(
        os_name="posix", env={"LINGTAI_SHELL": "  CMD  "},
    ) is ShellKind.CMD


def test_shell_setting_beats_env_override():
    # init.json ``manifest.capabilities.shell.shell_kind`` is the most explicit
    # override and wins over the process-wide env var.
    assert resolve_shell_kind(
        os_name="nt", env={"LINGTAI_SHELL": "wsl"}, shell_setting="cmd",
    ) is ShellKind.CMD


def test_shell_setting_accepts_enum_member():
    assert resolve_shell_kind(
        os_name="posix", shell_setting=ShellKind.GITBASH,
    ) is ShellKind.GITBASH


def test_invalid_override_falls_back_to_platform_default(monkeypatch):
    assert resolve_shell_kind(
        os_name="posix", env={"LINGTAI_SHELL": "fish"},
    ) is ShellKind.POSIX
    monkeypatch.setattr("lingtai.adapters.shell._discover_pwsh", lambda: None)
    monkeypatch.setattr("lingtai.adapters.windows.gitbash.discover_git_bash", lambda: None)
    assert resolve_shell_kind(
        os_name="nt", env={"LINGTAI_SHELL": "fish"},
    ) is ShellKind.CMD


def test_unsupported_platform_fails_loud():
    with pytest.raises(NotImplementedError, match="unsupported on platform 'java'"):
        resolve_shell_kind(os_name="java")


def test_coerce_normalizes_members_strings_and_junk():
    assert ShellKind.coerce(ShellKind.CMD) is ShellKind.CMD
    assert ShellKind.coerce("  PowerShell  ") is ShellKind.POWERSHELL
    assert ShellKind.coerce("gitbash") is ShellKind.GITBASH
    assert ShellKind.coerce("fish") is None
    assert ShellKind.coerce(7) is None
    assert ShellKind.coerce(None) is None
    assert ShellKind.coerce("") is None


def test_from_state_key_maps_dialect_keys_and_unknowns():
    assert ShellKind.from_state_key("posix") is ShellKind.POSIX
    assert ShellKind.from_state_key("powershell") is ShellKind.POWERSHELL
    assert ShellKind.from_state_key("test-marker") is None


def test_kind_metadata_is_complete_and_model_facing():
    for kind in ShellKind:
        assert kind.display_name
        assert kind.sequencing_guidance


def test_powershell_guidance_warns_against_and():
    guidance = ShellKind.POWERSHELL.sequencing_guidance
    assert "';'" in guidance
    assert "'&&'" in guidance
    assert "not supported" in guidance


def test_cmd_guidance_uses_ampersand_and_mentions_no_semicolon_separator():
    guidance = ShellKind.CMD.sequencing_guidance
    assert "'&'" in guidance
    assert "'&&'" in guidance
    assert "no ';' statement separator" in guidance


def test_display_names_are_human_readable():
    assert ShellKind.POSIX.display_name == "Bash (POSIX)"
    assert ShellKind.POWERSHELL.display_name == "PowerShell"
    assert ShellKind.CMD.display_name == "cmd.exe"
    assert ShellKind.GITBASH.display_name == "Git Bash"
    assert ShellKind.WSL.display_name == "WSL bash"
