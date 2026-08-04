"""Shell-language values used by the Bash capability."""
from __future__ import annotations

from dataclasses import dataclass
import enum
import os
import re
from typing import Any


class ShellKind(enum.Enum):
    """Concrete shell family driving spawn argv and model-facing guidance.

    Values double as the durable ``state_key`` strings produced by each
    dialect, so runtime metadata (async job state, tool description) stays a
    single stable vocabulary shared by the classifier and the dialects.
    """

    POSIX = "posix"
    POWERSHELL = "powershell"
    CMD = "cmd"
    GITBASH = "gitbash"
    WSL = "wsl"

    @classmethod
    def coerce(cls, value: object) -> "ShellKind | None":
        """Accept an enum member or a case-insensitive value string.

        Unknown strings return ``None`` so callers can fall back to the
        platform default instead of failing the whole shell setup.
        """
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            try:
                return cls(value.strip().lower())
            except ValueError:
                return None
        return None

    @classmethod
    def from_state_key(cls, key: object) -> "ShellKind | None":
        """Map a dialect ``state_key()`` value back to its kind."""
        return cls.coerce(key)

    @property
    def display_name(self) -> str:
        """Human-readable shell name for the model-facing description."""
        return _DISPLAY_NAMES[self]

    @property
    def sequencing_guidance(self) -> str:
        """Model-facing sentence teaching chaining/sequencing for this shell."""
        return _SEQUENCING_GUIDANCE[self]


# The single spawn-argument authority.  Every shell family maps to exactly one
# argv template here; dialects build invocations through
# ``make_invocation_for_kind`` so the shape can never drift between the
# model-facing description and ``subprocess``.  POSIX keeps the historical
# ``shell=True`` form (empty template, handled in ``make_invocation_for_kind``)
# so the default platform path is byte-for-byte unchanged.
_SPAWN_ARGV_BY_KIND: dict[ShellKind, tuple[str, ...]] = {
    ShellKind.POSIX: (),
    ShellKind.POWERSHELL: ("-NoLogo", "-NoProfile", "-NonInteractive", "-Command"),
    ShellKind.CMD: ("/d", "/s", "/c"),
    ShellKind.GITBASH: ("-lc",),
    ShellKind.WSL: ("-e", "bash", "-lc"),
}

_DISPLAY_NAMES: dict[ShellKind, str] = {
    ShellKind.POSIX: "Bash (POSIX)",
    ShellKind.POWERSHELL: "PowerShell",
    ShellKind.CMD: "cmd.exe",
    ShellKind.GITBASH: "Git Bash",
    ShellKind.WSL: "WSL bash",
}

_SEQUENCING_GUIDANCE: dict[ShellKind, str] = {
    ShellKind.POSIX: (
        "Chain commands with '&&' (run only on success) or ';' (always run); "
        "'||' runs the next command only on failure."
    ),
    ShellKind.POWERSHELL: (
        "Sequence commands with ';' \u2014 '&&' is not supported by Windows "
        "PowerShell 5.1 and is unsafe to assume; separate pipeline stages with '|'."
    ),
    ShellKind.CMD: (
        "Sequence commands with '&' (always) or '&&' (only on success); "
        "cmd.exe has no ';' statement separator."
    ),
    ShellKind.GITBASH: (
        "Git Bash is Bash: chain with '&&' (run only on success) or ';' (always run)."
    ),
    ShellKind.WSL: (
        "WSL runs Bash: chain with '&&' (run only on success) or ';' (always run)."
    ),
}


def make_invocation_for_kind(
    kind: ShellKind, script: str, executable: str | None = None,
) -> "ShellInvocation":
    """Build a spawn form from a ShellKind \u2014 the one spawn-args authority.

    POSIX keeps the historical subprocess ``shell=True`` form so the default
    platform path is byte-for-byte unchanged.  Every other family uses an
    explicit argv template with ``shell=False`` and UTF-8-tolerant text
    decoding, exactly like the PowerShell 7 adapter does today.  cmd.exe
    falls back to ``%COMSPEC%`` (then ``cmd.exe``) when no executable is
    supplied; the other argv families require a discovered executable.
    """
    if kind is ShellKind.POSIX:
        return ShellInvocation(script=script)
    if kind is ShellKind.CMD and executable is None:
        executable = os.environ.get("COMSPEC") or "cmd.exe"
    if executable is None:
        raise ValueError(
            f"{kind.value} spawn form requires a discovered executable"
        )
    return ShellInvocation(
        script=script,
        executable=executable,
        argv=_SPAWN_ARGV_BY_KIND[kind],
        encoding="utf-8",
        errors="replace",
    )


def extract_posix_commands(command: str) -> tuple[str, ...]:
    """Extract command names using the existing POSIX Bash policy rules."""
    flat = re.sub(r"\$\([^)]*\)", lambda m: "; " + m.group()[2:-1] + " ;", command)
    flat = re.sub(r"`[^`]*`", lambda m: "; " + m.group()[1:-1] + " ;", flat)
    parts = re.split(r"\|{1,2}|&&|;|\n", flat)
    commands: list[str] = []
    for part in parts:
        tokens = part.strip().split()
        while tokens and re.fullmatch(r"[A-Za-z_]\w*=\S*", tokens[0]):
            tokens = tokens[1:]
        if tokens:
            commands.append(tokens[0])
    return tuple(commands)


@dataclass(frozen=True)
class ShellInvocation:
    """Serializable shell execution form; no cwd, timeout, or result policy."""

    script: str
    executable: str | None = None
    argv: tuple[str, ...] | None = None
    encoding: str | None = None
    errors: str | None = None
    # When set, ``script`` is NOT placed on the child command line; instead the
    # spawner must write ``stdin_script`` to the child's stdin (UTF-8) before
    # waiting.  ``argv`` then carries the complete command line, whose last
    # element is typically an ASCII-only bootstrap that reads stdin.  This is
    # how PowerShell dialects dodge the Windows command-line code page and the
    # 32,768-character process command-line limit.
    stdin_script: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.script, str) or not self.script.strip():
            raise ValueError("script must be a non-empty string")
        for name in ("executable", "encoding", "errors"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value):
                raise ValueError(f"{name} must be a non-empty string when present")
        if self.stdin_script is not None and (
            not isinstance(self.stdin_script, str) or not self.stdin_script.strip()
        ):
            raise ValueError("stdin_script must be a non-empty string when present")
        if self.argv is None:
            return
        if not isinstance(self.argv, (tuple, list)):
            raise ValueError("argv must be a tuple or list of strings")
        if self.executable is None:
            raise ValueError("argv form requires a non-empty executable")
        if not all(isinstance(item, str) for item in self.argv):
            raise ValueError("argv elements must be strings")
        object.__setattr__(self, "argv", tuple(self.argv))

    def to_dict(self) -> dict[str, Any]:
        value = {
            "script": self.script,
            "executable": self.executable,
            "argv": list(self.argv) if self.argv is not None else None,
            "encoding": self.encoding,
            "errors": self.errors,
        }
        if self.stdin_script is not None:
            value["stdin_script"] = self.stdin_script
        return value

    @classmethod
    def from_dict(cls, value: object) -> "ShellInvocation | None":
        base = {"script", "executable", "argv", "encoding", "errors"}
        optional = {"stdin_script"}
        if (
            not isinstance(value, dict)
            or not base.issubset(value)
            or not set(value).issubset(base | optional)
        ):
            return None
        argv = value.get("argv")
        if argv is not None and (
            not isinstance(argv, (list, tuple)) or not all(isinstance(item, str) for item in argv)
        ):
            return None
        executable = value.get("executable")
        encoding = value.get("encoding")
        errors = value.get("errors")
        stdin_script = value.get("stdin_script")
        if any(
            item is not None and not isinstance(item, str)
            for item in (executable, encoding, errors, stdin_script)
        ):
            return None
        try:
            return cls(
                script=value["script"], executable=executable, argv=argv,
                encoding=encoding, errors=errors, stdin_script=stdin_script,
            )
        except (TypeError, ValueError):
            return None

    def process_args(self) -> tuple[object, dict[str, object]]:
        """Return only dialect process arguments; callers add lifecycle policy."""
        if self.argv is not None:
            args = [self.executable, *self.argv]
            if self.stdin_script is None:
                # Classic argv form: the script is the trailing command argument
                # (for example the payload of ``-Command``).
                args.append(self.script)
            # stdin_script form: ``argv`` already is the complete command line
            # (ending in an ASCII-only bootstrap) and the real script travels
            # through stdin; callers feed ``stdin_script`` before waiting.
            return args, {"shell": False}
        if self.stdin_script is not None:
            # A stdin payload without the argv form has no fixed command line
            # to receive it; fail loudly instead of silently dropping it.
            raise ValueError("stdin_script requires the argv form (non-None argv)")
        kwargs: dict[str, object] = {"shell": True}
        if self.executable is not None:
            kwargs["executable"] = self.executable
        return self.script, kwargs


class ShellDialect:
    """Bash-local port for policy extraction and invocation construction."""

    def extract_commands(self, script: str) -> tuple[str, ...]:
        raise NotImplementedError

    def make_invocation(self, script: str) -> ShellInvocation:
        raise NotImplementedError

    def state_key(self) -> str:
        raise NotImplementedError

    def kind(self) -> ShellKind | None:
        """ShellKind for this dialect, or None for unknown/test dialects."""
        return ShellKind.from_state_key(self.state_key())
