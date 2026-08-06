"""Unit tests for the shell exit-code interpretation layer (grep/rg no-match).

Port of Hermes' ``_interpret_exit_code``: benign non-zero exit codes are
mapped to a guidance note in the tool result, inspecting only the last
pipeline/compound segment. Presentation-only: ``exit_code`` semantics are
never changed.
"""
import pytest

from lingtai.tools.bash import (
    _augment_command_result,
    _split_on_chain_operators,
    interpret_exit_code,
)

NOTE = "No matches found (not an error)"


class TestShellLastSegmentSelection:
    def test_shell_interpret_last_segment_is_grep_after_andand(self):
        code, note = interpret_exit_code("cmd1 && grep x file", 1)
        assert code == 1
        assert note == NOTE

    def test_shell_interpret_last_segment_is_echo_after_semicolon(self):
        code, note = interpret_exit_code("cmd1 && grep x file; echo done", 1)
        assert code == 1
        assert note is None

    def test_shell_interpret_last_segment_in_pipeline(self):
        code, note = interpret_exit_code("cmd1 | grep x file", 1)
        assert note == NOTE

    def test_shell_interpret_last_segment_after_oror(self):
        code, note = interpret_exit_code("false || rg pattern .", 1)
        assert note == NOTE

    def test_shell_interpret_respects_quotes_while_splitting(self):
        code, note = interpret_exit_code("printf '%s\\n' 'a | b' | grep z", 1)
        assert note == NOTE
        code, note = interpret_exit_code('echo "a; b && c" | grep q', 1)
        assert note == NOTE

    def test_shell_interpret_skips_env_assignment_and_path_prefix(self):
        code, note = interpret_exit_code("GREP_OPTS=-i /usr/bin/grep foo src", 1)
        assert note == NOTE


class TestShellBenignExitCodes:
    @pytest.mark.parametrize("cmd", ["grep", "egrep", "fgrep", "rg", "ag", "ack"])
    def test_shell_interpret_grep_family_exit_1_is_benign(self, cmd):
        code, note = interpret_exit_code(f"{cmd} pattern file.txt", 1)
        assert code == 1
        assert note == NOTE

    def test_shell_interpret_grep_exit_2_is_real_error(self):
        code, note = interpret_exit_code("grep pattern missing.txt", 2)
        assert code == 2
        assert note is None

    def test_shell_interpret_zero_exit_is_unannotated(self):
        code, note = interpret_exit_code("grep pattern file.txt", 0)
        assert code == 0
        assert note is None

    def test_shell_interpret_unknown_command_is_unannotated(self):
        code, note = interpret_exit_code("python3 script.py", 1)
        assert code == 1
        assert note is None

    def test_shell_interpret_grep_not_in_last_segment_is_unannotated(self):
        code, note = interpret_exit_code("grep x file; python3 script.py", 1)
        assert note is None

    def test_shell_interpret_empty_segments_is_unannotated(self):
        code, note = interpret_exit_code("   ", 1)
        assert code == 1
        assert note is None


class TestShellInterpretCommandSubstitutions:
    """A pipe inside $(...)/backticks must never look like the last command.

    MUST-FIX regression for #1186 review finding 1: ``pytest $(git diff
    --name-only | grep test_)`` failing with exit 1 is a *real* failure; it
    must not be annotated "No matches found". Only top-level pipes/chain
    operators select the segment whose exit code the note describes.
    """

    def test_shell_interpret_no_note_when_pipe_inside_dollar_paren(self):
        code, note = interpret_exit_code(
            "pytest $(git diff --name-only | grep test_)", 1
        )
        assert code == 1
        assert note is None

    def test_shell_interpret_no_note_when_pipe_inside_backticks(self):
        code, note = interpret_exit_code(
            "pytest `git diff --name-only | grep test_`", 1
        )
        assert code == 1
        assert note is None

    def test_shell_interpret_note_when_grep_is_last_top_level_segment(self):
        code, note = interpret_exit_code(
            "echo $(date | cut -d' ' -f1) && grep x file", 1
        )
        assert code == 1
        assert note == NOTE

    def test_shell_interpret_no_note_when_substitution_feeds_grep_in_middle(self):
        # grep is inside the substitution, pytest is the last command.
        code, note = interpret_exit_code(
            "pytest $(git diff --name-only | grep test_) | cat", 1
        )
        assert code == 1
        assert note is None


class TestShellSplitOnChainOperators:
    def test_shell_split_handles_all_operators(self):
        assert _split_on_chain_operators("a && b || c | d; e") == [
            "a ", " b ", " c ", " d", " e"
        ]

    def test_shell_split_keeps_bare_background_amp_in_segment(self):
        assert _split_on_chain_operators("sleep 5 & echo hi") == ["sleep 5 & echo hi"]

    def test_shell_split_keeps_pipe_amp_operator(self):
        # ``|&`` pipes stdout+stderr and is a two-char operator like ``||``.
        assert _split_on_chain_operators("cmd |& grep x") == ["cmd ", " grep x"]


class TestShellSplitCommandSubstitutions:
    """Operators inside $(...)/backtick substitutions are not chain operators.

    Regression for the MUST-FIX review note on #1186: the pipe inside
    ``pytest $(git diff --name-only | grep test_)`` must never make ``grep``
    look like the last top-level command — only the substitution's *result*
    participates in the outer pipeline.
    """

    def test_shell_split_ignores_pipe_inside_dollar_paren(self):
        assert _split_on_chain_operators(
            "pytest $(git diff --name-only | grep test_)"
        ) == ["pytest $(git diff --name-only | grep test_)"]

    def test_shell_split_ignores_operators_inside_backticks(self):
        assert _split_on_chain_operators(
            "pytest `git diff --name-only | grep test_`"
        ) == ["pytest `git diff --name-only | grep test_`"]

    def test_shell_split_resumes_splitting_after_substitution_closes(self):
        assert _split_on_chain_operators(
            "echo $(date | cut -d' ' -f1) && grep x file"
        ) == ["echo $(date | cut -d' ' -f1) ", " grep x file"]

    def test_shell_split_handles_nested_substitutions(self):
        assert _split_on_chain_operators(
            "echo $(a $(b | c) ) | grep z"
        ) == ["echo $(a $(b | c) ) ", " grep z"]

    def test_shell_split_handles_paren_in_quotes_inside_substitution(self):
        assert _split_on_chain_operators(
            'echo $(printf ")" ) | grep z'
        ) == ['echo $(printf ")" ) ', " grep z"]


class TestShellAugmentBenignNote:
    def test_shell_augment_appends_benign_note_to_warning(self):
        r = _augment_command_result(
            {"status": "ok", "exit_code": 1, "stdout": "", "stderr": ""},
            command="grep pattern file.txt",
        )
        assert r["ok"] is False
        assert r["command_status"] == "failed"
        assert r["exit_code"] == 1
        assert "command exited with code 1" in r["warning"]
        assert NOTE in r["warning"]

    def test_shell_augment_rg_note_via_full_command(self):
        r = _augment_command_result(
            {"status": "done", "exit_code": 1, "stdout": "", "stderr": ""},
            command="rg --files | rg -q pattern; rg -l pattern .",
        )
        assert NOTE in r["warning"]

    def test_shell_augment_real_error_stays_unannotated(self):
        r = _augment_command_result(
            {"status": "ok", "exit_code": 2, "stdout": "", "stderr": "grep: missing: No such file\\n"},
            command="grep pattern missing.txt",
        )
        assert "command exited with code 2" in r["warning"]
        assert NOTE not in r["warning"]

    def test_shell_augment_without_command_keeps_legacy_warning(self):
        r = _augment_command_result(
            {"status": "done", "exit_code": 1, "stdout": "", "stderr": "bad arg\\n"}
        )
        assert r["warning"].startswith("command exited with code 1")
        assert NOTE not in r["warning"]

    def test_shell_augment_no_benign_note_for_substitution_failure(self):
        # MUST-FIX regression: a real pytest failure must not be dismissed as
        # a grep "no matches" even though grep sits on a pipe inside $().
        r = _augment_command_result(
            {
                "status": "ok",
                "exit_code": 1,
                "stdout": "",
                "stderr": "FAILED tests/test_demo.py::test_thing\\n",
            },
            command="pytest $(git diff --name-only | grep test_)",
        )
        assert r["exit_code"] == 1
        assert "command exited with code 1" in r["warning"]
        assert NOTE not in r["warning"]

    def test_shell_augment_keeps_note_for_last_top_level_grep(self):
        r = _augment_command_result(
            {"status": "ok", "exit_code": 1, "stdout": "", "stderr": ""},
            command="echo $(date | cut -d' ' -f1) && grep x file",
        )
        assert NOTE in r["warning"]
