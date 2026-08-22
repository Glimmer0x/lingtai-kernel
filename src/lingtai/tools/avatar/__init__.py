"""Avatar capability — spawn independent peer agents (分身).

Shallow (初生): Copy init.json to a new working dir, strip name, launch.
    The avatar gets the same LLM config + capabilities but no identity,
    no pad, no history.  A fresh life — but its own, not yours.

Deep (二重身): Copy identity files (system/), knowledge/, and exports/
    plus init.json to a new dir, strip name + history, launch.
    The avatar is a doppelgänger — same character, pad, knowledge —
    but starts a fresh conversation.

Both modes launch `lingtai-agent run <dir>` as a fully detached process.
The avatar is an independent life — its existence does not depend on yours.

Maintains an append-only ledger (delegates/ledger.jsonl) that records
every spawn event.

Usage (LTP v2 envelope — one action, one strict child input):
    Agent(capabilities=["avatar"])
    # avatar(action="spawn", input={"name": "researcher"}, reasoning="...")
    # avatar(action="spawn", input={"name": "clone", "type": "deep"}, reasoning="...")
    # avatar(action="rules", input={"rules_content": "..."}, reasoning="...")
    # avatar(action="manual", input={}, reasoning="...")

The spawn mission brief is root ``reasoning`` (normalized to ``_reasoning`` by
ToolExecutor), never an ``input`` property — see ``handle()``.

Packaging: this folder is a built-in tool *plugin package*. ``plugin.py`` states
avatar's capability identity, its packaged ``manual/SKILL.md`` skill, its own
declared actions, and the capability declaration the registry must agree with;
``AVATAR_PLUGIN`` appends the reserved ``manual`` action and answers it straight
from that packaged skill, so ``manual`` never routes through ``AvatarManager``
and no manager change can drop or rebind it. Registration, activation,
privilege, and lifecycle stay exactly where they were: ``setup()`` still
performs the one ``add_tool`` call, and ``lingtai.tools.registry`` still owns
capability lookup and boot.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping

from lingtai.kernel.agent_presence import observe_alive as _presence_observe_alive
from lingtai.kernel.i18n import t
from ..tool_family import ChildTool, ToolFamily
from ._launcher import AvatarLaunchReceipt, AvatarLaunchRequest, AvatarLauncherPort
from .plugin import AVATAR_ACTIONS, AVATAR_DESCRIPTION, AVATAR_PLUGIN


def _is_alive(working_dir) -> bool:
    """Foreign-address liveness check via the presence store + Core policy.

    Builds a target-bound POSIX presence adapter for *working_dir* and applies
    the Core freshness/human policy in manifest-first order, replacing the
    former ``handshake.is_alive`` call.
    """
    from lingtai.adapters.posix.agent_presence import PosixAgentPresenceStoreAdapter

    store = PosixAgentPresenceStoreAdapter(working_dir)
    return _presence_observe_alive(store, wall_now=time.time())


# Avatar name doubles as its working-directory basename. Letters (any script,
# including CJK), digits, underscore, and hyphen — no path separators, no
# control chars, no dots. The structural chars are what make this dangerous;
# the script itself is the agent's choice.
_AVATAR_NAME_RE = re.compile(r"^[\w-]+$")  # \w is Unicode-aware in Py3 re
_AVATAR_NAME_MAX_LEN = 64

# Mission quality gate — minimum length below which we treat the mission as a
# probable accidental spawn unless the caller explicitly confirms.
_MISSION_MIN_CHARS = 20

# Suspicious tokens that indicate a debug/test placeholder mission. Compared
# case-insensitively against the trimmed mission (full match) and against the
# first whitespace-delimited token (prefix match like "test something").
_MISSION_SUSPICIOUS = {"test", "debug", "check", "tmp", "temp", "foo", "bar"}


def _mission_looks_unsafe(mission: str) -> tuple[bool, str]:
    """Heuristic mission-quality gate.

    Returns ``(unsafe, reason)``. Used to refuse accidental spawns where the
    mission field is empty, far too short, or matches a debug/test placeholder
    pattern. Caller can override with ``confirm=True``.
    """
    trimmed = (mission or "").strip()
    if not trimmed:
        return True, "mission is empty"
    if len(trimmed) < _MISSION_MIN_CHARS:
        return True, f"mission is very short ({len(trimmed)} chars)"
    lower = trimmed.lower()
    if lower in _MISSION_SUSPICIOUS or lower.startswith(
        tuple(f"{w} " for w in _MISSION_SUSPICIOUS)
    ):
        return True, "mission looks like a debug/test placeholder"
    return False, ""


if TYPE_CHECKING:
    from lingtai.agent import Agent

PROVIDERS = {"providers": [], "default": "builtin"}

# Canonical, strict per-action input schemas. Optionals are expressed as
# nullable required properties because that is what strict OpenAI-style
# validators demand of a closed object; null means "absent" to the action
# implementations (see ``_strip_nulls``).
#
# The spawn mission brief is deliberately NOT a property here: it is root
# ``reasoning``, and nested ``input`` must never carry
# ``reasoning``/``_reasoning``/``summarize``.
_SPAWN_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {
            "type": "string",
            "description": (
                "True name for the avatar. Also the working-directory basename "
                "under .lingtai/. Single segment: letters/digits/underscore/"
                "hyphen, max 64 chars."
            ),
        },
        "type": {
            "type": ["string", "null"],
            "enum": ["shallow", "deep", None],
            "description": (
                "'shallow' (default): blank slate — init.json only. 'deep': "
                "full copy of character, pad, and codex. Null for the default."
            ),
        },
        "comment": {
            "type": ["string", "null"],
            "description": (
                "Persistent system note in the avatar's prompt (survives molt/"
                "refresh/wake). Not inherited. Null or empty unless you have "
                "something the avatar must never forget."
            ),
        },
        "dry_run": {
            "type": ["boolean", "null"],
            "description": (
                "Preview the spawn without creating a process. Use to "
                "sanity-check before committing. Null for the default false."
            ),
        },
        "confirm": {
            "type": ["boolean", "null"],
            "description": (
                "Confirm you have reviewed the mission and intend to spawn. "
                "Required when the mission looks empty/short/test-like. Null "
                "for the default false."
            ),
        },
    },
    "required": ["name", "type", "comment", "dry_run", "confirm"],
    "additionalProperties": False,
}

_RULES_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "rules_content": {
            "type": "string",
            "description": (
                "Plain text, one rule per line. Non-negotiable constraints "
                "distributed to self and all descendants. Requires karma."
            ),
        },
    },
    "required": ["rules_content"],
    "additionalProperties": False,
}

# Avatar's OWN child specs: canonical action name → its own strict input
# schema, in model-facing enum order. The reserved ``manual`` action is
# deliberately absent — ``AVATAR_PLUGIN`` appends it from the packaged
# ``manual/SKILL.md`` and rejects any attempt to declare it here.
_DECLARED_CHILD_SPECS: tuple[tuple[str, dict[str, Any]], ...] = (
    ("spawn", _SPAWN_INPUT_SCHEMA),
    ("rules", _RULES_INPUT_SCHEMA),
)

# The complete child spec — declared actions plus the plugin-appended
# ``manual``, whose input is the one shared ``MANUAL_INPUT_SCHEMA`` object.
# Both the module-level schema-only family and each manager's handler-bound
# family are built from this single source by ``_build_family`` below, so the
# two listings cannot drift apart.
_CHILD_SPECS: tuple[tuple[str, dict[str, Any]], ...] = AVATAR_PLUGIN.child_specs(
    _DECLARED_CHILD_SPECS
)

# Avatar's pinned unknown-action wording, rendered from the plugin's one public
# action list so the error can never name a set of actions the family does not
# actually serve. Renders exactly "'spawn', 'rules', or 'manual'".
_SUPPORTED_ACTIONS_PHRASE = (
    "".join(f"{action!r}, " for action in AVATAR_ACTIONS[:-1])
    + f"or {AVATAR_ACTIONS[-1]!r}"
)


def _build_family(handlers: Mapping[str, Any], agent: "Agent | None") -> ToolFamily:
    """Build avatar's family, binding each declared action to *handlers[name]*.

    Only avatar's own actions are bound here. ``manual`` is appended by
    ``AVATAR_PLUGIN`` and answered from *agent*'s installed
    ``.library/intrinsic/capabilities/avatar/SKILL.md``, with or without a
    manager — it is not in *handlers* and cannot be supplied there. *agent* is
    ``None`` only for the module-level schema-only family, which never
    dispatches. Construction validates the registry, so a duplicate or
    reserved-name collision raises ``ToolFamilyError``/``BuiltinToolPluginError``
    here — at import time for ``_FAMILY`` — rather than shipping silently.
    """
    return AVATAR_PLUGIN.build_family(
        [
            ChildTool(name, schema, handlers[name], title=f"{name} input")
            for name, schema in _DECLARED_CHILD_SPECS
        ],
        agent,
    )


def _unused(_input: Mapping[str, Any]) -> dict[str, Any]:
    raise AssertionError("the module-level schema-only ToolFamily never dispatches")


# Composes the model-facing schema only; ``AvatarManager`` builds its own
# per-instance family with real handlers bound to that instance.
_FAMILY = _build_family({name: _unused for name, _ in _DECLARED_CHILD_SPECS}, None)


def get_description(lang: str = "en") -> str:
    """The model-facing root description, owned by the plugin descriptor."""
    return AVATAR_DESCRIPTION


def get_schema(lang: str = "en") -> dict[str, Any]:
    """Compose the LTP v2 model-facing schema for the single public ``avatar`` tool."""
    return _FAMILY.build_schema()


class AvatarManager:
    """Spawns avatar (分身) peer agents as detached processes.

    Each avatar gets its own working directory with init.json and is
    launched via `lingtai-agent run`.  No in-process references — liveness
    is checked via the filesystem through the agent-presence store.
    """

    def __init__(self, agent: "Agent", launcher: AvatarLauncherPort | None = None):
        self._agent = agent
        if launcher is None:
            from lingtai.adapters.avatar_launcher import select_avatar_launcher
            launcher = select_avatar_launcher()
        self._launcher = launcher
        # The spawn mission brief reaches ``_spawn`` out-of-band via
        # ``self._pending_reasoning``, set by ``handle()`` (see ``handle``).
        # ``manual`` is deliberately absent: the plugin appends and answers it
        # from this agent's installed manual, so no manager binding exists to
        # rebind.
        self._family = _build_family(
            {
                "spawn": self._dispatch_spawn,
                "rules": self._dispatch_rules,
            },
            agent,
        )
        self._pending_reasoning: str | None = None

    # ------------------------------------------------------------------
    # Handler
    # ------------------------------------------------------------------

    def handle(self, args: dict | None) -> dict:
        """Dispatch one action through the family, normalizing avatar's errors.

        Root ``reasoning`` (normalized to ``_reasoning`` by ToolExecutor) is the
        avatar's mission brief and becomes the newborn's first prompt. It is
        envelope metadata, never action input, so it is captured here and handed
        to ``_spawn`` out-of-band rather than smuggled into ``input``, and
        cleared in ``finally`` so a later call cannot inherit a previous call's
        mission.

        Avatar's pre-migration unknown-action envelope is a pinned public
        promise; the generic dispatcher's ``ACTION_REQUIRED`` shape is
        deliberately generic, so it is normalized back here, after dispatch —
        never by changing that dispatcher's own canonical error shape.
        """
        raw = args if isinstance(args, Mapping) else {}
        reasoning = raw.get("_reasoning")
        self._pending_reasoning = reasoning if isinstance(reasoning, str) else None
        try:
            result = self._family.handle(args)
        finally:
            self._pending_reasoning = None
        if result.get("error_code") == "ACTION_REQUIRED":
            action = raw.get("action", "")
            return {
                "error": (
                    f"unknown action: {action!r}, only "
                    f"{_SUPPORTED_ACTIONS_PHRASE} is supported"
                ),
            }
        return result

    @staticmethod
    def _strip_nulls(action_input: Mapping[str, Any]) -> dict[str, Any]:
        # Strict OpenAI schemas express optional fields as required nullable
        # properties. Null means absent to the internal action handlers, so
        # every default below stays exactly the pre-migration default.
        return {key: value for key, value in action_input.items() if value is not None}

    def _dispatch_spawn(self, action_input: Mapping[str, Any]) -> dict:
        return self._spawn(self._strip_nulls(action_input), self._pending_reasoning)

    def _dispatch_rules(self, action_input: Mapping[str, Any]) -> dict:
        return self._rules(self._strip_nulls(action_input))

    def _manual(self) -> dict:
        """The installed avatar-manual result — plugin-owned, no mutation.

        ``Agent._install_intrinsic_manuals`` installs this package's
        ``manual/SKILL.md`` into the agent's ``.library`` catalog like every
        other capability's, so ``AVATAR_PLUGIN`` reports that host-local copy
        through the same shared ``load_installed_manual`` the rest of the
        families use. The packaged file is that copy's source, not the document
        this agent reads.

        This is a read-only convenience for callers holding a manager; the
        public ``manual`` action does **not** come through here. The family's
        ``manual`` child is the plugin's own, so nothing this manager does can
        drop or replace the skill it serves.
        """
        return AVATAR_PLUGIN.manual_payload(self._agent)

    # ------------------------------------------------------------------
    # Ledger (append-only JSONL log of avatar spawn events)
    # ------------------------------------------------------------------

    @property
    def _ledger_path(self) -> Path:
        return self._agent._working_dir / "delegates" / "ledger.jsonl"

    def _append_ledger(self, event: str, name: str, **fields) -> None:
        """Append a single event record to the ledger."""
        self._ledger_path.parent.mkdir(parents=True, exist_ok=True)
        record = {"ts": time.time(), "event": event, "name": name, **fields}
        with open(self._ledger_path, "a") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # ------------------------------------------------------------------
    # Core spawn
    # ------------------------------------------------------------------

    def _spawn(self, args: dict, reasoning: str | None = None) -> dict:
        """Create one avatar. ``reasoning`` is the mission brief from the root
        envelope (``handle()``), not an ``input`` property — it becomes the
        newborn's first prompt and gates the mission-quality check."""
        parent = self._agent
        peer_name = args.get("name")
        avatar_type = args.get("type", "shallow")
        dry_run = bool(args.get("dry_run", False))
        confirm = bool(args.get("confirm", False))

        if peer_name is None:
            return {"error": "name is required — pick a true name (真名) for the 他我 (e.g. 'researcher', '学者')"}

        if avatar_type not in ("shallow", "deep"):
            return {"error": "type must be 'shallow' or 'deep'"}

        # Name doubles as working-dir basename. Enforce a safe, single-segment
        # name so an LLM-chosen string cannot traverse, target absolute paths,
        # or nest avatars inside subfolders (which would desync path-identity
        # from the ledger and mail-routing layer).
        if (
            not isinstance(peer_name, str)
            or not peer_name
            or peer_name in (".", "..")
            or peer_name.startswith(".")
            or len(peer_name) > _AVATAR_NAME_MAX_LEN
            or not _AVATAR_NAME_RE.match(peer_name)
        ):
            return {
                "error": (
                    f"Invalid avatar name '{peer_name}': must be a bare directory "
                    f"name — letters (any script), digits, underscore, or hyphen; "
                    f"no slashes, dots, spaces, or leading '.'; 1-{_AVATAR_NAME_MAX_LEN} chars."
                )
            }

        # Mission-quality gate. The reasoning field becomes the avatar's first
        # prompt, so an empty / very-short / debug-placeholder mission almost
        # always means an accidental spawn (a real incident: an agent batched
        # avatar_spawn into a parallel call with mission "test" and a process
        # was created). Refuse unless the caller explicitly passes confirm=True.
        # The dry-run path is exempt — its whole purpose is preview without
        # commitment, and forcing confirm=True there would defeat that.
        if not dry_run and not confirm:
            unsafe, reason = _mission_looks_unsafe(reasoning or "")
            if unsafe:
                preview_mission = (reasoning or "").strip()
                return {
                    "status": "confirmation_needed",
                    "warning": (
                        f"Mission appears short/test-like ({reason}). "
                        f"Pass confirm=true to proceed, or dry_run=true to preview. "
                        f"Each avatar(action='spawn') call creates an independent process — "
                        f"double-check your reasoning field before retrying."
                    ),
                    "reason": reason,
                    "preview": {
                        "name": peer_name,
                        "type": avatar_type,
                        "mission": preview_mission,
                        "mission_chars": len(preview_mission),
                    },
                }

        # Check if this peer already exists and is live
        for record in self._read_ledger():
            if record.get("name") == peer_name:
                wd = record.get("working_dir", "")
                if wd and _is_alive(wd):
                    return {
                        "status": "already_active",
                        "working_dir": wd,
                        "message": (
                            f"'{peer_name}' is already running. "
                            f"Use mail to communicate, or system intrinsic to manage lifecycle."
                        ),
                    }

        # Parent must have init.json
        parent_init_path = parent._working_dir / "init.json"
        if not parent_init_path.is_file():
            return {"error": "parent has no init.json — cannot spawn avatar"}

        try:
            parent_init = json.loads(parent_init_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            return {"error": f"failed to read parent init.json: {e}"}

        # Dry-run short-circuit. Returns a preview of what would be created,
        # but performs NO filesystem mutation and NO process launch. We've
        # already validated name/type and confirmed parent has a usable
        # init.json, so the preview reflects what a real spawn would do.
        if dry_run:
            avatar_working_dir = parent._working_dir.parent / peer_name
            preview_mission = (reasoning or "").strip()
            unsafe, reason = _mission_looks_unsafe(reasoning or "")
            return {
                "status": "dry_run",
                "preview": {
                    "name": peer_name,
                    "type": avatar_type,
                    "working_dir": str(avatar_working_dir),
                    "address": avatar_working_dir.name,
                    "mission": preview_mission,
                    "mission_chars": len(preview_mission),
                    "mission_unsafe": unsafe,
                    "mission_reason": reason if unsafe else "",
                    "comment": args.get("comment", ""),
                },
                "message": "Dry run — no process spawned, no files written.",
            }

        # Working dir: sibling of parent, named after the avatar. Defense-in-depth
        # scope check — resolve and assert the target's parent equals the network
        # root, so even if peer_name validation is ever loosened, this still
        # prevents writing outside .lingtai/<siblings>/.
        avatar_working_dir = parent._working_dir.parent / peer_name
        network_root = parent._working_dir.parent.resolve()
        try:
            resolved = avatar_working_dir.resolve(strict=False)
        except (OSError, RuntimeError) as e:
            return {"error": f"Cannot resolve avatar path: {e}"}
        if resolved.parent != network_root:
            return {
                "error": (
                    f"Avatar path '{avatar_working_dir}' escapes the network root "
                    f"'{network_root}' — rejected."
                )
            }
        if avatar_working_dir.exists():
            return {"error": f"Directory '{peer_name}' already exists. Choose another name."}

        # Prepare the avatar's working directory
        parent_name = parent.agent_name or parent._working_dir.name

        # Copy init.json and launch lingtai
        if avatar_type == "deep":
            self._prepare_deep(parent._working_dir, avatar_working_dir)
        else:
            avatar_working_dir.mkdir(parents=True, exist_ok=True)

        # Resolve relative file paths to absolute so avatar can find them.
        # Only active prompt-contract file fields are re-rooted: env_file plus
        # the externally changeable prompt surfaces (covenant / base_prompt /
        # comment). Retired override file fields (principle_file / substrate_file
        # / brief_file / procedures_file) are not inherited as live paths.
        for key in ("env_file", "covenant_file",
                    "base_prompt_file", "comment_file"):
            val = parent_init.get(key)
            if val and not os.path.isabs(val):
                resolved = parent._working_dir / val
                if resolved.is_file():
                    parent_init[key] = str(resolved)

        # Inherit parent's venv_path so avatar can find the runtime
        if hasattr(parent, "_venv_path") and parent._venv_path:
            parent_init["venv_path"] = parent._venv_path

        # Clean stale signal files before launch
        for sig in (".suspend", ".sleep", ".interrupt"):
            sig_file = avatar_working_dir / sig
            if sig_file.is_file():
                sig_file.unlink(missing_ok=True)

        # Seed the avatar's first turn with a parent-identity prompt + the
        # caller's reasoning (task brief). Written to the avatar's `.prompt`
        # file — picked up by the kernel's signal-file watcher on first poll
        # and delivered as a one-shot system message (consumed-once via unlink).
        parent_address = parent._working_dir.name
        avatar_lang = parent_init.get("manifest", {}).get("language", "en")
        parent_prompt = t(
            avatar_lang, "avatar.parent_prompt",
            parent_name=parent_name,
            parent_address=parent_address,
        )
        first_prompt = parent_prompt
        if reasoning and reasoning.strip():
            first_prompt = f"{parent_prompt}\n\n{reasoning.strip()}"

        # Write avatar's init.json (modified copy of parent's).
        avatar_comment = args.get("comment", "")
        avatar_init = self._make_avatar_init(
            parent_init, peer_name, comment=avatar_comment,
            parent_working_dir=parent._working_dir,
        )
        (avatar_working_dir / "init.json").write_text(
            json.dumps(avatar_init, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

        # Drop the spawn prompt as a `.prompt` signal file — the avatar's
        # kernel watcher consumes it on first poll and delivers it once.
        (avatar_working_dir / ".prompt").write_text(first_prompt, encoding="utf-8")

        # Launch as detached process and wait briefly for the child to either
        # write its handshake (.agent.heartbeat) or exit. If the child exits
        # before handshaking, the spawn failed — capture stderr, ledger the
        # failure, and return an error to the caller. Without this check the
        # avatar capability returns "ok" the instant a child forks, even if the
        # child crashes 50ms later (e.g. invalid init.json), and the parent's
        # LLM has no idea anything went wrong.
        proc, stderr_path = self._launch(avatar_working_dir)
        pid = proc.pid

        try:
            boot_status, boot_error = self._wait_for_boot(
                avatar_working_dir, proc, stderr_path,
            )
        finally:
            self._launcher.release(proc.handle)

        # Record in ledger — include boot status so post-mortem can distinguish
        # successful spawns from failed ones without re-checking the filesystem.
        ledger_extra = {"boot_status": boot_status}
        if boot_error:
            ledger_extra["boot_error"] = boot_error
        self._append_ledger(
            "avatar", peer_name,
            working_dir=avatar_working_dir.name,
            mission=reasoning or "",
            type=avatar_type,
            pid=pid,
            **ledger_extra,
        )

        if boot_status == "failed":
            return {
                "error": (
                    f"avatar {peer_name!r} failed to boot: {boot_error}. "
                    f"See {stderr_path} for details."
                ),
                "address": avatar_working_dir.name,
                "agent_name": peer_name,
                "pid": pid,
            }

        # Auto-distribute rules to all descendants (including newborn) — read from canonical system/rules.md
        parent_rules_md = parent._working_dir / "system" / "rules.md"
        if parent_rules_md.is_file():
            try:
                rules_content = parent_rules_md.read_text(encoding="utf-8")
            except OSError:
                rules_content = ""
            if rules_content.strip():
                self._distribute_rules_to_descendants(rules_content, parent._working_dir)

        result = {
            "status": "ok",
            "address": avatar_working_dir.name,
            "agent_name": peer_name,
            "type": avatar_type,
            "pid": pid,
        }
        if boot_status == "slow":
            # Process is still alive but didn't finish handshaking in the
            # window — surface a warning so the caller knows to monitor it.
            result["warning"] = (
                f"avatar still booting after {self._BOOT_WAIT_SECS}s — "
                f"check .agent.heartbeat freshness before relying on it"
            )
        return result

    def _wait_for_boot(
        self, working_dir: Path, proc: AvatarLaunchReceipt, stderr_path: Path,
    ) -> tuple[str, str | None]:
        """Wait for the avatar to write .agent.heartbeat or exit.

        Returns (status, error_message):
            - ("ok", None)     — heartbeat appeared before timeout
            - ("failed", msg)  — process exited before handshaking
            - ("slow", None)   — neither happened in BOOT_WAIT_SECS; process
                                 is still alive, caller should monitor
        """
        heartbeat = working_dir / ".agent.heartbeat"
        deadline = time.monotonic() + self._BOOT_WAIT_SECS
        while time.monotonic() < deadline:
            if heartbeat.is_file():
                return ("ok", None)
            rc = self._launcher.poll(proc.handle)
            if rc is not None:
                # Child exited before writing heartbeat. Tail stderr (capped)
                # so the parent's LLM gets a useful, bounded error string.
                stderr_tail = ""
                try:
                    raw = stderr_path.read_bytes()
                    if len(raw) > 2000:
                        raw = b"...[truncated]...\n" + raw[-2000:]
                    stderr_tail = raw.decode("utf-8", errors="replace").strip()
                except OSError:
                    pass
                msg = f"process exited with code {rc}"
                if stderr_tail:
                    msg = f"{msg}: {stderr_tail}"
                return ("failed", msg)
            time.sleep(self._BOOT_POLL_INTERVAL)
        return ("slow", None)

    # ------------------------------------------------------------------
    # Init.json construction
    # ------------------------------------------------------------------

    @staticmethod
    def _make_avatar_init(
        parent_init: dict, name: str, *,
        comment: str = "",
        parent_working_dir: "Path | None" = None,
    ) -> dict:
        """Build avatar's init.json from parent's, setting name.

        The spawn brief (parent identity + reasoning) is delivered out-of-band
        via a `.prompt` signal file dropped in the avatar's working dir by the
        caller — see ``_spawn``. Here we only blank the inherited `lingtai`
        character seed so the schema sees a present-but-empty required field (no
        stale identity carried over). The `.prompt` signal file is a runtime
        text-injection channel and is unrelated to the renamed `lingtai` seed.

        Avatars inherit the parent's `manifest.preset.allowed` list verbatim.
        Entries are stored as path strings; if any are relative, they are
        re-rooted against ``parent_working_dir`` (if given) so the avatar's
        own working dir doesn't change their meaning.
        """
        init = json.loads(json.dumps(parent_init))  # deep copy
        init["manifest"]["agent_name"] = name
        # Blank inherited `lingtai` — schema requires the character seed field to
        # exist, but the avatar starts with no inherited 灵台; its actual first
        # prompt arrives via the `.prompt` signal file (a separate runtime
        # channel, not the `lingtai` seed).
        init["lingtai"] = ""
        init.pop("lingtai_file", None)
        # Avatar has no admin privileges
        init["manifest"]["admin"] = {}
        # Comment is not inherited — parent can set one explicitly for the avatar
        init["comment"] = comment
        init.pop("comment_file", None)
        # Kernel-owned / secretary-owned prompt layers are not inherited as
        # init.json overrides.  Under the init-prompt contract the only external
        # prompt surfaces are base_prompt, covenant, and comment; comment is
        # reset above, while base_prompt and covenant remain inherited.
        for key in (
            "principle", "principle_file",
            "procedures", "procedures_file",
            "substrate", "substrate_file",
            "brief", "brief_file",
        ):
            init.pop(key, None)
        # Addons (IMAP, Telegram) are not inherited — each agent must be
        # explicitly configured to avoid multiple agents polling the same account
        init.pop("addons", None)
        # Re-root any relative paths in preset.{default,active,allowed}
        # against the parent's working dir so they remain valid from the
        # avatar's different working directory. Absolute and ~-prefixed
        # entries pass through unchanged.
        if parent_working_dir is not None:
            preset_block = init["manifest"].get("preset")
            if isinstance(preset_block, dict):
                def _reroot(s: object) -> object:
                    if not isinstance(s, str) or not s:
                        return s
                    p = Path(s).expanduser()
                    if p.is_absolute():
                        return s
                    return str((Path(parent_working_dir) / p).resolve())
                for key in ("default", "active"):
                    if isinstance(preset_block.get(key), str):
                        preset_block[key] = _reroot(preset_block[key])
                allowed = preset_block.get("allowed")
                if isinstance(allowed, list):
                    preset_block["allowed"] = [_reroot(x) for x in allowed]

        # Avatars always spawn on the parent's DEFAULT preset, not its
        # currently-active one. This keeps the avatar's notion of 'default'
        # well-defined as a peer in the network — auto-fallback targets a
        # stable home base, not whatever transient preset the parent happened
        # to be on at spawn time.
        #
        # Strip materialized llm + capabilities unconditionally so the avatar's
        # _read_init re-materializes from the (possibly-rewritten) active on
        # first boot. Letting the existing materialization path do its job
        # is cleaner than manually re-substituting here.
        preset_block = init["manifest"].get("preset")
        if isinstance(preset_block, dict) and preset_block.get("default"):
            preset_block["active"] = preset_block["default"]
            init["manifest"].pop("llm", None)
            init["manifest"].pop("capabilities", None)

        return init

    # ------------------------------------------------------------------
    # Deep copy — 二重身
    # ------------------------------------------------------------------

    @staticmethod
    def _prepare_deep(src: Path, dst: Path) -> None:
        """Copy identity + knowledge from parent, excluding runtime state.

        Guarded: dst must be a direct sibling of src (same parent). This mirrors
        the path-scope assertion in _spawn so the rmtree() calls below cannot
        reach outside the network root even if _prepare_deep is ever called
        from a future, less-validated path.
        """
        src_resolved = src.resolve(strict=False)
        dst_resolved = dst.resolve(strict=False)
        if dst_resolved.parent != src_resolved.parent:
            raise ValueError(
                f"_prepare_deep refused: dst '{dst}' is not a sibling of src '{src}' "
                f"(parents differ: {dst_resolved.parent} vs {src_resolved.parent})"
            )
        dst.mkdir(parents=True, exist_ok=True)

        # system/ (character, pad, covenant, etc.)
        src_system = src / "system"
        if src_system.is_dir():
            dst_system = dst / "system"
            if dst_system.exists():
                shutil.rmtree(dst_system)
            shutil.copytree(src_system, dst_system)

        # knowledge/
        src_knowledge = src / "knowledge"
        if src_knowledge.is_dir():
            dst_knowledge = dst / "knowledge"
            if dst_knowledge.exists():
                shutil.rmtree(dst_knowledge)
            shutil.copytree(src_knowledge, dst_knowledge)

        # exports/
        src_exports = src / "exports"
        if src_exports.is_dir():
            dst_exports = dst / "exports"
            if dst_exports.exists():
                shutil.rmtree(dst_exports)
            shutil.copytree(src_exports, dst_exports)

        # combo.json
        src_combo = src / "combo.json"
        if src_combo.is_file():
            shutil.copy2(src_combo, dst / "combo.json")

        # Explicitly do NOT copy: history/, mailbox/, delegates/,
        # .agent.json, .agent.heartbeat, logs/

    # ------------------------------------------------------------------
    # Process launch
    # ------------------------------------------------------------------

    # Boot verification — how long to wait for the child to write .agent.heartbeat
    # before we conclude it crashed. Healthy boots finish well under 2s on local
    # disk; 5s is generous enough for slow systems to still pass.
    _BOOT_WAIT_SECS = 5.0
    _BOOT_POLL_INTERVAL = 0.1

    def _launch(self, working_dir: Path) -> tuple[AvatarLaunchReceipt, Path]:
        """Launch `lingtai-agent run <dir>` as a fully detached process.

        Captures stderr to ``logs/spawn.stderr`` so a child that exits before
        writing its handshake leaves a usable diagnostic behind. Returns the
        opaque launch receipt (so callers can poll for early exit) plus the
        stderr path.
        """
        from lingtai.venv_resolve import resolve_venv, venv_python

        # Resolve Python from avatar's init.json → global runtime
        init_path = working_dir / "init.json"
        init_data = None
        if init_path.is_file():
            try:
                init_data = json.loads(init_path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                pass
        venv_dir = resolve_venv(init_data)
        python = venv_python(venv_dir)
        cmd = (python, "-m", "lingtai", "run", str(working_dir))

        # Ensure logs/ exists for stderr capture; the kernel also creates this
        # on boot, but we need it before the child has run.
        logs_dir = working_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        stderr_path = logs_dir / "spawn.stderr"
        receipt = self._launcher.launch(
            AvatarLaunchRequest(argv=cmd, stderr_path=stderr_path)
        )
        return receipt, stderr_path

    # ------------------------------------------------------------------
    # Ledger reading
    # ------------------------------------------------------------------

    def _read_ledger(self) -> list[dict]:
        """Read all ledger records."""
        if not self._ledger_path.is_file():
            return []
        records = []
        for line in self._ledger_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return records

    # ------------------------------------------------------------------
    # Rules distribution
    # ------------------------------------------------------------------

    def _rules(self, args: dict) -> dict:
        """Set rules and distribute via .rules signal files to self + descendants.

        Self and descendants are handled uniformly: a `.rules` signal file is
        written to every agent directory in the subtree (including the caller's
        own). Each agent's heartbeat loop (`_check_rules_file`) then consumes
        the signal, diffs it against `system/rules.md`, and refreshes its own
        system prompt if the content changed. The caller's own prompt refresh
        happens on its next heartbeat tick (within ~1s).
        """
        parent = self._agent
        content = args.get("rules_content", "").strip()
        if not content:
            return {"error": "rules_content is required"}

        # Admin check: at least one admin privilege must be truthy
        admin = getattr(parent, "_admin", {}) or {}
        if not any(admin.values()):
            return {"error": "Not authorized — admin privilege required to set rules"}

        # Write .rules signal to self — heartbeat will consume and persist
        try:
            (parent._working_dir / ".rules").write_text(content, encoding="utf-8")
        except OSError as e:
            return {"error": f"failed to write .rules signal: {e}"}

        # Write .rules signal file to all descendants
        distributed = self._distribute_rules_to_descendants(content, parent._working_dir)

        # Include self in the reported distribution for transparency
        return {
            "status": "ok",
            "message": f"Rules set; signal written to self and {len(distributed)} descendant(s).",
            "distributed_to": [parent._working_dir.name] + distributed,
        }

    @staticmethod
    def _walk_avatar_tree(root: Path) -> list[Path]:
        """Recursively collect all descendant working-dir Paths from ledger files.

        Ledger entries store relative names (e.g. 'researcher'); we resolve each
        against the *parent agent's parent directory* since avatars live as
        siblings in .lingtai/. Returns absolute Paths of live descendant dirs.
        """
        from lingtai.kernel.handshake import resolve_address

        visited: set[str] = {str(Path(root))}
        queue: list[Path] = [Path(root)]
        result: list[Path] = []

        while queue:
            current = queue.pop(0)
            ledger_path = current / "delegates" / "ledger.jsonl"
            if not ledger_path.is_file():
                continue
            try:
                lines = ledger_path.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            # Siblings of `current` live in current.parent
            base_dir = current.parent
            for line in lines:
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("event") != "avatar":
                    continue
                wd = record.get("working_dir", "")
                if not wd:
                    continue
                # Resolve relative name to absolute Path
                child_dir = resolve_address(wd, base_dir)
                key = str(child_dir)
                if key in visited:
                    continue
                if not child_dir.is_dir():
                    continue  # dead avatar, directory gone
                visited.add(key)
                result.append(child_dir)
                queue.append(child_dir)

        return result

    def _distribute_rules_to_descendants(self, content: str, root: Path) -> list[str]:
        """Write `.rules` signal file to every descendant in the avatar tree.

        Returns the list of descendant directory names that were successfully written.
        Failures are silently swallowed (caller has no visibility), consistent with
        the best-effort, idempotent design of signal files.
        """
        distributed: list[str] = []
        for child_dir in self._walk_avatar_tree(root):
            try:
                (child_dir / ".rules").write_text(content, encoding="utf-8")
                distributed.append(child_dir.name)
            except OSError:
                pass
        return distributed


def setup(agent: "Agent", **kwargs) -> AvatarManager:
    """Set up the avatar capability on an agent.

    The host still performs mounting: ``registry.setup_capability`` calls this,
    and this calls ``add_tool`` once. What gets mounted — the public tool name
    and the glossary package — comes from ``AVATAR_PLUGIN`` rather than being
    restated here, so the registered tool cannot drift from the descriptor the
    capability declaration is checked against.
    """
    mgr = AvatarManager(agent)
    agent.add_tool(
        AVATAR_PLUGIN.name,
        **AVATAR_PLUGIN.tool_registration(
            schema=get_schema(),
            description=get_description(),
            handler=mgr.handle,
        ),
    )
    return mgr
