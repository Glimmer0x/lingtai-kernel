"""Tests for the shell-tool output-hygiene module and its wiring.

Covers the four public helpers in ``lingtai.tools.bash._output_hygiene``
(strip_ansi, escape_controls, strip_shell_startup_noise, truncate_output)
plus the composed ``sanitize_output`` pipeline, and end-to-end assertions
that the hygiene is applied on the ``BashManager`` sync result path.
"""

import pytest

from lingtai.tools.bash import BashManager, BashPolicy
from lingtai.tools.bash._output_hygiene import (
    escape_controls,
    sanitize_output,
    strip_ansi,
    strip_shell_startup_noise,
    truncate_output,
)


class _SyncOnlyAgent:
    """Strict stand-in for manager tests that exercise only synchronous runs."""


# ---------------------------------------------------------------------------
# strip_ansi
# ---------------------------------------------------------------------------

class TestStripAnsi:
    def test_strips_csi_color_codes(self):
        assert strip_ansi("\x1b[31mred\x1b[0m") == "red"
        assert strip_ansi("\x1b[1;32mbold green\x1b[0m") == "bold green"

    def test_strips_csi_with_intermediates_and_private_params(self):
        assert strip_ansi("a\x1b[2Jb") == "ab"          # clear screen
        assert strip_ansi("a\x1b[?25lb") == "ab"        # hide cursor
        assert strip_ansi("a\x1b[38;5;196mb") == "ab"   # 256-color fg

    def test_strips_osc_title_sequences(self):
        assert strip_ansi("\x1b]0;my title\x07content") == "content"
        assert strip_ansi("\x1b]2;path\x1b\\content") == "content"

    def test_strips_single_char_and_charset_escapes(self):
        assert strip_ansi("a\x1b7b\x1b8c") == "abc"    # save/restore cursor
        assert strip_ansi("a\x1bcb") == "ab"           # hard reset
        assert strip_ansi("\x1b(0\x1b)0data") == "data"  # charset designations

    def test_plain_text_passes_through(self):
        assert strip_ansi("hello world\n") == "hello world\n"
        assert strip_ansi("\tindented\r\n") == "\tindented\r\n"

    def test_multiple_sequences_in_one_stream(self):
        text = "\x1b[32mok\x1b[0m \x1b[1mstrong\x1b[0m\n"
        assert strip_ansi(text) == "ok strong\n"


# ---------------------------------------------------------------------------
# escape_controls
# ---------------------------------------------------------------------------

class TestEscapeControls:
    def test_keeps_tab_newline_carriage_return(self):
        text = "a\tb\nc\rd"
        assert escape_controls(text) == text

    def test_escapes_c0_controls(self):
        assert escape_controls("a\x07b") == "a\\x07b"      # bell
        assert escape_controls("a\x00b") == "a\\x00b"      # NUL
        assert escape_controls("a\x08b") == "a\\x08b"      # backspace
        assert escape_controls("a\x0bb") == "a\\x0bb"      # vertical tab
        assert escape_controls("a\x0cb") == "a\\x0cb"      # form feed

    def test_escapes_del(self):
        assert escape_controls("a\x7fb") == "a\\x7fb"

    def test_escapes_c1_controls(self):
        assert escape_controls("a\x85b") == "a\\x85b"      # NEL
        assert escape_controls("a\x9bb") == "a\\x9bb"      # 8-bit CSI
        assert escape_controls("a\x9fb") == "a\\x9fb"

    def test_plain_text_passes_through(self):
        assert escape_controls("plain ascii text") == "plain ascii text"


# ---------------------------------------------------------------------------
# strip_shell_startup_noise
# ---------------------------------------------------------------------------

class TestStripShellStartupNoise:
    def test_drops_bash_job_control_head_lines(self):
        lines = [
            "bash: cannot set terminal process group",
            "bash: no job control in this shell",
            "real output",
        ]
        assert strip_shell_startup_noise(lines) == ["real output"]

    def test_drops_tcsetattr_head_lines(self):
        lines = ["tcsetattr: Inappropriate ioctl for device", "ok"]
        assert strip_shell_startup_noise(lines) == ["ok"]

    def test_preserves_generic_warning_head_lines(self):
        # Regression: git checkout/add stderr on Windows routinely starts with
        # "warning: LF will be replaced by CRLF"; a generic ^warning: pattern
        # would silently delete genuine command output.
        lines = ["warning: LF will be replaced by CRLF", "data"]
        assert strip_shell_startup_noise(lines) == lines

    def test_preserves_head_lines_merely_containing_noise_text(self):
        # Regression: grep output lines start with a filename, not the search
        # string, so they must survive the (line-anchored) noise stripping.
        lines = ["./src:no job control in this shell", "data"]
        assert strip_shell_startup_noise(lines) == lines

    def test_stops_at_first_non_noise_line(self):
        lines = [
            "bash: no job control in this shell",
            "real first",
            "tcsetattr: Inappropriate ioctl for device",
            "tail",
        ]
        assert strip_shell_startup_noise(lines) == [
            "real first",
            "tcsetattr: Inappropriate ioctl for device",
            "tail",
        ]

    def test_clean_head_is_unchanged(self):
        lines = ["hello", "world"]
        assert strip_shell_startup_noise(lines) == ["hello", "world"]

    def test_returns_a_new_list(self):
        lines = ["bash: no job control in this shell"]
        result = strip_shell_startup_noise(lines)
        assert result == []
        assert lines == ["bash: no job control in this shell"]  # input untouched


# ---------------------------------------------------------------------------
# truncate_output
# ---------------------------------------------------------------------------

class TestTruncateOutput:
    def test_under_cap_unchanged(self):
        assert truncate_output("short", max_chars=100) == "short"
        # "exactly twenty!" is 15 chars; a cap at 15 must leave it untouched.
        assert truncate_output("exactly twenty!", max_chars=15) == "exactly twenty!"

    def test_over_cap_gets_explicit_marker(self):
        text = "x" * 30
        result = truncate_output(text, max_chars=10)
        assert result == "x" * 10 + "\n... (truncated, 30 chars total)"

    def test_marker_reports_original_length(self):
        result = truncate_output("y" * 5_001, max_chars=5_000)
        assert "... (truncated, 5001 chars total)" in result

    def test_default_max_chars_is_applied(self):
        result = truncate_output("z" * (100_001), max_chars=100_000)
        assert "... (truncated, 100001 chars total)" in result


# ---------------------------------------------------------------------------
# sanitize_output (composed pipeline)
# ---------------------------------------------------------------------------

class TestSanitizeOutput:
    def test_strips_ansi_escapes_controls_and_noise(self):
        text = (
            "\x1b[31m"
            "bash: no job control in this shell\n"
            "payload \x07 bell\n"
        )
        result = sanitize_output(text, max_chars=100_000)
        assert result == "payload \\x07 bell\n"

    def test_ansi_stripped_but_warning_head_lines_preserved(self):
        # ANSI is stripped first; the warning line itself is genuine output
        # and must be preserved, not dropped as startup noise.
        text = "\x1b[33mwarning: thing\x1b[0m\npayload\n"
        assert sanitize_output(text) == "warning: thing\npayload\n"

    def test_truncation_marker_survives_pipeline(self):
        result = sanitize_output("a" * 200, max_chars=50)
        assert result.startswith("a" * 50)
        assert "... (truncated, 200 chars total)" in result

    def test_huge_input_is_pre_capped_before_sanitizing(self):
        # Regression: sanitization must not run full regex passes over the
        # entire untruncated stream; the pre-cap bounds the work and the
        # marker still reports the original size.
        big = "\x07" * 2_000_000
        result = sanitize_output(big, max_chars=100)
        assert "... (truncated, 2000000 chars total)" in result
        assert len(result) < 500

    def test_huge_plain_text_keeps_head_and_reports_size(self):
        big = "a" * 5_000_000
        result = sanitize_output(big, max_chars=100)
        assert result.startswith("a" * 100)
        assert "... (truncated, 5000000 chars total)" in result


# ---------------------------------------------------------------------------
# Wiring: BashManager sync result path applies hygiene
# ---------------------------------------------------------------------------

class TestBashManagerHygiene:
    def _manager(self, **kwargs):
        return BashManager(
            agent=_SyncOnlyAgent(),
            policy=BashPolicy.yolo(),
            working_dir="/tmp",
            **kwargs,
        )

    def test_ansi_codes_are_stripped_from_stdout(self):
        mgr = self._manager()
        result = mgr.handle({"command": "printf '\\033[31mred\\033[0m hello'"})
        assert result["status"] == "ok"
        assert "red hello" in result["stdout"]
        assert "\x1b" not in result["stdout"]

    def test_control_bytes_are_escaped(self):
        mgr = self._manager()
        result = mgr.handle({"command": "printf 'a\\ab'"})
        assert "\\x07" in result["stdout"]
        assert "\x07" not in result["stdout"]

    def test_startup_noise_is_stripped_from_head(self):
        mgr = self._manager()
        result = mgr.handle(
            {"command": "printf 'bash: no job control in this shell\\nreal output\\n'"}
        )
        assert "real output" in result["stdout"]
        assert "no job control" not in result["stdout"]

    def test_warning_head_lines_are_not_stripped(self):
        mgr = self._manager()
        result = mgr.handle(
            {"command": "printf 'warning: LF will be replaced by CRLF\\nreal output\\n'"}
        )
        assert "warning: LF will be replaced by CRLF" in result["stdout"]
        assert "real output" in result["stdout"]

    def test_output_is_capped_with_explicit_marker(self):
        mgr = self._manager(max_output=20)
        result = mgr.handle(
            {"command": "printf '0123456789abcdefghijklmnopqrstuvwxyz'"}
        )
        first_line = result["stdout"].split("\n", 1)[0]
        assert len(first_line) == 20
        # printf output is 36 chars; the marker reports the original size.
        assert "... (truncated, 36 chars total)" in result["stdout"]

    def test_plain_output_passes_through_unchanged(self):
        mgr = self._manager()
        result = mgr.handle({"command": "echo hello"})
        assert result["stdout"].strip() == "hello"
