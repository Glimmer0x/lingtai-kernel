"""Regression tests for Windows console-output decoding (PR #1184 follow-up).

Covers the two review findings fixed here:

1. The OEM fallback must not blanket-decode a whole file: a mostly-valid
   UTF-8 log with one invalid byte run (a native tool that re-enabled the OEM
   codepage, or a torn multibyte character from a read that caught the child
   mid-write) must keep its valid text, with only the invalid bytes replaced.
2. Async read-back restores the universal-newlines translation, so pwsh's
   CRLF-terminated output never leaks stray CR characters.

``decode_windows_output`` is pure Python and platform-independent; the module
imports cleanly without a console or pwsh, so these run on POSIX CI too.
"""
from pathlib import Path
from types import SimpleNamespace

from lingtai.adapters.windows.powershell import decode_windows_output
from lingtai.tools.bash import BashManager, BashPolicy

_UTF8_BOM = b"\xef\xbb\xbf"
_ZH = "\u4e2d\u6587"  # CJK text that whole-file OEM decoding would garble


class TestDecodeWindowsOutput:
    def test_pure_utf8_passthrough(self):
        text = "\u6b22\u8fce\u8f93\u51fa\nsecond line\n"
        assert decode_windows_output(text.encode("utf-8")) == text

    def test_utf8_bom_stripped(self):
        assert decode_windows_output(_UTF8_BOM + b"hello") == "hello"

    def test_sparse_invalid_byte_keeps_utf8_text(self):
        # Review finding 1: one invalid byte run in an otherwise-valid UTF-8
        # log must not re-decode the whole log as OEM.
        data = _ZH.encode("utf-8") + b"\x82tail"
        result = decode_windows_output(data)
        assert _ZH in result
        assert result.endswith("tail")
        assert "\ufffd" in result
        assert "\ufffd" not in result.replace("\ufffd", "", 1)

    def test_oem_line_decoded_among_utf8_lines(self):
        data = _ZH.encode("utf-8") + b"\nMontr\x82al\n"
        result = decode_windows_output(data)
        assert _ZH in result
        assert "Montr\u00e9al" in result

    def test_pure_oem_file_still_decodes(self):
        result = decode_windows_output(b"Montr\x82al \xe9\r\n")
        assert "Montr\u00e9al" in result

    def test_sparse_latin_oem_byte_still_uses_oem(self):
        # A Latin line with one OEM byte is still OEM-decoded (the fallback
        # is per line, not per file).
        assert "\u00e9" in decode_windows_output(b"abc\x82def")

    def test_torn_multibyte_tail_replaced_not_oem(self):
        # Read caught the child mid-write: incomplete 3-byte char at EOF.
        torn = b"abc" + "\u4e2d".encode("utf-8")[:-1]
        assert decode_windows_output(torn) == "abc\ufffd"

    def test_torn_tail_after_utf8_text(self):
        data = _ZH.encode("utf-8") + "\u4e2d".encode("utf-8")[:-1]
        result = decode_windows_output(data)
        assert result.startswith(_ZH)
        assert result.endswith("\ufffd")

    def test_crlf_preserved_at_decode_level(self):
        # The decoder is byte-faithful; newline normalization happens at the
        # read-back boundary (see TestReadLogsNewlineNormalization).
        assert decode_windows_output(b"a\r\nb\r\n") == "a\r\nb\r\n"

    def test_empty_and_newline_only(self):
        assert decode_windows_output(b"") == ""
        assert decode_windows_output(b"\n\n") == "\n\n"


class TestReadLogsNewlineNormalization:
    """Review finding 2: async read-back must not leak CRLF/CR characters."""

    def _manager(self, tmp_path: Path) -> BashManager:
        agent = SimpleNamespace(_notification_store=None)
        return BashManager(
            policy=BashPolicy.yolo(), working_dir=str(tmp_path), agent=agent
        )

    def _write_logs(self, tmp_path: Path, stdout: bytes, stderr: bytes) -> Path:
        job_id = "job-10000000000000000000000000000101"
        job_dir = tmp_path / "system" / "jobs" / job_id
        job_dir.mkdir(parents=True)
        (job_dir / "stdout.log").write_bytes(stdout)
        (job_dir / "stderr.log").write_bytes(stderr)
        return job_dir

    def test_crlf_normalized_in_async_logs(self, tmp_path):
        job_dir = self._write_logs(tmp_path, b"line1\r\nline2\r\n", b"err1\r\n")
        stdout, stderr = self._manager(tmp_path)._read_logs(job_dir)
        assert stdout == "line1\nline2\n"
        assert stderr == "err1\n"
        assert "\r" not in stdout and "\r" not in stderr

    def test_lone_cr_normalized(self, tmp_path):
        # Universal-newlines parity with the historical read_text() decode.
        job_dir = self._write_logs(tmp_path, b"progress\r10%\r100%\n", b"")
        stdout, _ = self._manager(tmp_path)._read_logs(job_dir)
        assert stdout == "progress\n10%\n100%\n"
