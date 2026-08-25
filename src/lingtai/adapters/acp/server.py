"""ACP v1 newline-delimited JSON-RPC adapter over local stdio."""
from __future__ import annotations

import json
import queue
import threading
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, TextIO
from uuid import uuid4

from lingtai.kernel.turns import TurnHandle, TurnOutcome
from lingtai.kernel.execution_workspace import ExecutionWorkspace
from lingtai.services.session_mcp import StdioMCPServerConfig


JSONRPC_VERSION = "2.0"
ACP_PROTOCOL_VERSION = 1

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
SERVER_NOT_INITIALIZED = -32002
SESSION_NOT_FOUND = -32001
SESSION_BUSY = -32000
UNSUPPORTED = -32004


class _RpcError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(slots=True)
class _ActivePrompt:
    request_id: str | int
    session_id: str
    handle: TurnHandle
    thread: threading.Thread | None = None
    terminal_claimed: bool = False


@dataclass(frozen=True, slots=True)
class _OutboundBatch:
    """One FIFO output unit tied to the generation that accepted it."""

    generation: int
    wires: tuple[str, ...]
    active: _ActivePrompt | None = None


def _package_version() -> str:
    try:
        return version("lingtai")
    except PackageNotFoundError:  # source-tree tests without installed metadata
        return "0+unknown"


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant: {value}")


class AcpStdioServer:
    """One-process, one-session ACP v1 driving adapter.

    The reader remains live while a prompt worker waits on the Core TurnHandle,
    so ``session/cancel`` can request cooperative cancellation of that exact
    turn. Serialized output crosses one bounded FIFO queue; only its disposable
    daemon writer may touch the potentially blocking client stream.
    """

    _OUTBOUND_QUEUE_BATCHES = 64

    def __init__(self, agent, input_stream: TextIO, output_stream: TextIO):
        self._agent = agent
        self._input = input_stream
        self._output = output_stream
        self._state_lock = threading.RLock()
        self._initialized = False
        self._session_id: str | None = None
        self._session_pending = False
        self._execution_workspace: ExecutionWorkspace | None = None
        self._session_mcp_lease = None
        self._active: _ActivePrompt | None = None
        self._closing = False
        self._aborted = False
        self._generation = 0
        self._prompt_threads: set[threading.Thread] = set()
        self._outbound: queue.Queue[_OutboundBatch] = queue.Queue(
            maxsize=self._OUTBOUND_QUEUE_BATCHES
        )
        self._writer = threading.Thread(
            target=self._writer_loop,
            daemon=True,
            name="acp-stdio-writer",
        )
        self._writer.start()

    def serve(self) -> None:
        """Read frames until EOF, close, interrupt, or Agent shutdown.

        Text streams can block indefinitely in ``readline``. A daemon reader owns
        that blocking edge while this coordinator polls the Agent shutdown latch,
        so refresh/stop can release the workdir lease without waiting for a client
        to close stdin. The reader never parses or writes protocol frames.
        """

        incoming: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=64)

        def _read_input() -> None:
            try:
                for raw_line in self._input:
                    incoming.put(("line", raw_line))
            except BaseException as exc:
                incoming.put(("error", exc))
            finally:
                incoming.put(("eof", None))

        reader = threading.Thread(
            target=_read_input,
            daemon=True,
            name="acp-stdio-reader",
        )
        reader.start()
        try:
            while True:
                with self._state_lock:
                    if self._closing:
                        break
                shutdown = getattr(self._agent, "_shutdown", None)
                if shutdown is not None and shutdown.is_set():
                    break
                try:
                    kind, payload = incoming.get(timeout=0.1)
                except queue.Empty:
                    continue
                if kind == "eof":
                    break
                if kind == "error":
                    if isinstance(payload, UnicodeError):
                        self._write_error(None, PARSE_ERROR, "Parse error")
                        break
                    raise payload

                raw_line = payload
                line = raw_line.rstrip("\r\n")
                if not line:
                    continue
                try:
                    message = json.loads(line, parse_constant=_reject_json_constant)
                except (json.JSONDecodeError, ValueError):
                    self._write_error(None, PARSE_ERROR, "Parse error")
                    continue
                self._dispatch(message)
        finally:
            self.close()

    def close(self) -> None:
        """Invalidate queued output, stop accepting work, and cancel the prompt.

        The writer is deliberately never joined: an OS-level stdout write may be
        stuck forever after the client stops reading. Generation invalidation
        makes every batch that has not crossed the writer's start check
        disposable while Agent/lease teardown proceeds independently.
        """

        with self._state_lock:
            if self._closing:
                return
            self._closing = True
            self._generation += 1
            active = self._active
            self._active = None
        if active is not None:
            active.handle.cancel()
        lease = self._session_mcp_lease
        self._session_mcp_lease = None
        if lease is not None:
            lease.close()

    def _abort_transport(self) -> None:
        """Fail every queued batch closed after a fatal framing/write failure."""

        with self._state_lock:
            if self._aborted:
                return
            self._aborted = True
            self._closing = True
            self._generation += 1
            active = self._active
            self._active = None
        if active is not None:
            active.handle.cancel()
        lease = self._session_mcp_lease
        self._session_mcp_lease = None
        if lease is not None:
            lease.close()

    def _dispatch(self, message: Any) -> None:
        if not isinstance(message, dict):
            self._write_error(None, INVALID_REQUEST, "Invalid Request")
            return

        has_id = "id" in message
        request_id = message.get("id")
        method = message.get("method")
        if (
            message.get("jsonrpc") != JSONRPC_VERSION
            or not isinstance(method, str)
            or (has_id and not self._valid_id(request_id))
        ):
            self._write_error(
                request_id if self._valid_id(request_id) else None,
                INVALID_REQUEST,
                "Invalid Request",
            )
            return

        params = message.get("params", {})
        try:
            if method in {"initialize", "session/new", "session/prompt"} and not has_id:
                raise _RpcError(INVALID_REQUEST, f"{method} must be a request")
            if method == "session/cancel" and has_id:
                raise _RpcError(INVALID_REQUEST, "session/cancel must be a notification")

            if method == "initialize":
                result = self._initialize(params)
            elif method == "session/new":
                self._require_initialized()
                result = self._new_session(params)
            elif method == "session/prompt":
                self._require_initialized()
                self._prompt(params, request_id)
                return
            elif method == "session/cancel":
                self._require_initialized()
                result = self._cancel(params)
            else:
                raise _RpcError(METHOD_NOT_FOUND, "Method not found")
        except _RpcError as exc:
            if has_id:
                self._write_error(request_id, exc.code, exc.message)
            return
        except Exception:
            if has_id:
                self._write_error(request_id, INTERNAL_ERROR, "Internal error")
            return

        if has_id:
            self._write_result(request_id, result)

    @staticmethod
    def _valid_id(value: Any) -> bool:
        # ACP's generated request-id shape is integer-or-string. In particular,
        # reject bool (an int subclass), null, and fractional JSON-RPC numbers.
        return isinstance(value, (str, int)) and not isinstance(value, bool)

    @staticmethod
    def _params_object(params: Any) -> dict[str, Any]:
        if not isinstance(params, dict):
            raise _RpcError(INVALID_PARAMS, "params must be an object")
        return params

    def _initialize(self, params: Any) -> dict[str, Any]:
        params = self._params_object(params)
        protocol_version = params.get("protocolVersion")
        if not isinstance(protocol_version, int) or isinstance(protocol_version, bool):
            raise _RpcError(INVALID_PARAMS, "protocolVersion must be an integer")
        with self._state_lock:
            self._initialized = True
        return {
            "protocolVersion": ACP_PROTOCOL_VERSION,
            "agentCapabilities": {},
            "agentInfo": {
                "name": "lingtai",
                "title": "LingTai",
                "version": _package_version(),
            },
            "authMethods": [],
        }

    def _require_initialized(self) -> None:
        with self._state_lock:
            initialized = self._initialized
        if not initialized:
            raise _RpcError(SERVER_NOT_INITIALIZED, "server is not initialized")

    @staticmethod
    def _stdio_mcp_configs(value: Any) -> tuple[StdioMCPServerConfig, ...]:
        if not isinstance(value, list):
            raise _RpcError(INVALID_PARAMS, "mcpServers must be an array")
        configs: list[StdioMCPServerConfig] = []
        names: set[str] = set()
        for item in value:
            if not isinstance(item, dict):
                raise _RpcError(INVALID_PARAMS, "mcpServers entries must be objects")
            if "type" in item:
                raise _RpcError(INVALID_PARAMS, "only stdio MCP servers are supported")
            if set(item) - {"name", "command", "args", "env", "_meta"}:
                raise _RpcError(INVALID_PARAMS, "unknown stdio MCP server field")
            name = item.get("name")
            command = item.get("command")
            args = item.get("args")
            env = item.get("env")
            meta = item.get("_meta")
            if not isinstance(name, str) or not name:
                raise _RpcError(INVALID_PARAMS, "MCP server name must be non-empty")
            if name in names:
                raise _RpcError(INVALID_PARAMS, "duplicate MCP server name")
            if (
                not isinstance(command, str)
                or not command
                or not Path(command).is_absolute()
            ):
                raise _RpcError(INVALID_PARAMS, "MCP command must be an absolute path")
            if not isinstance(args, list) or not all(isinstance(v, str) for v in args):
                raise _RpcError(INVALID_PARAMS, "MCP args must be an array of strings")
            if not isinstance(env, list):
                raise _RpcError(INVALID_PARAMS, "MCP env must be an array")
            if meta is not None and not isinstance(meta, dict):
                raise _RpcError(INVALID_PARAMS, "MCP _meta must be an object or null")
            env_pairs: list[tuple[str, str]] = []
            env_names: set[str] = set()
            for variable in env:
                if not isinstance(variable, dict) or set(variable) - {"name", "value", "_meta"}:
                    raise _RpcError(INVALID_PARAMS, "MCP env entries must be name/value objects")
                key = variable.get("name")
                val = variable.get("value")
                var_meta = variable.get("_meta")
                if not isinstance(key, str) or not key or not isinstance(val, str):
                    raise _RpcError(INVALID_PARAMS, "MCP env names/values must be strings")
                if key in env_names:
                    raise _RpcError(INVALID_PARAMS, "duplicate MCP environment name")
                if var_meta is not None and not isinstance(var_meta, dict):
                    raise _RpcError(INVALID_PARAMS, "MCP env _meta must be an object or null")
                env_names.add(key)
                env_pairs.append((key, val))
            names.add(name)
            configs.append(StdioMCPServerConfig(name, command, tuple(args), tuple(env_pairs)))
        return tuple(configs)

    def _new_session(self, params: Any) -> dict[str, str]:
        params = self._params_object(params)
        cwd = params.get("cwd")
        mcp_servers = params.get("mcpServers")
        if not isinstance(cwd, str) or not cwd or not Path(cwd).is_absolute():
            raise _RpcError(INVALID_PARAMS, "cwd must be an absolute path")
        try:
            resolved_cwd = Path(cwd).resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise _RpcError(INVALID_PARAMS, "cwd must exist") from exc
        if not resolved_cwd.is_dir():
            raise _RpcError(INVALID_PARAMS, "cwd must be a directory")
        configs = self._stdio_mcp_configs(mcp_servers)
        additional_directories = params.get("additionalDirectories")
        if additional_directories not in (None, []):
            raise _RpcError(
                UNSUPPORTED,
                "additionalDirectories are not supported by this local adapter",
            )
        with self._state_lock:
            if self._closing:
                raise _RpcError(UNSUPPORTED, "adapter is closing")
            if self._session_id is not None or self._session_pending:
                raise _RpcError(
                    UNSUPPORTED,
                    "this local adapter supports one session per process",
                )
            self._session_pending = True

        lease = None
        try:
            try:
                lease = self._agent.mount_session_mcp_stdio(configs) if configs else None
            except ValueError as exc:
                raise _RpcError(INVALID_PARAMS, str(exc)) from exc
            except Exception as exc:
                raise _RpcError(INTERNAL_ERROR, "session MCP startup failed") from exc

            workspace = ExecutionWorkspace(resolved_cwd)
            with self._state_lock:
                if self._closing:
                    raise _RpcError(UNSUPPORTED, "adapter is closing")
                self._execution_workspace = workspace
                self._session_mcp_lease = lease
                self._session_id = f"session_{uuid4().hex}"
                return {"sessionId": self._session_id}
        except Exception:
            if lease is not None:
                lease.close()
            raise
        finally:
            with self._state_lock:
                self._session_pending = False

    def _validate_session(self, params: dict[str, Any]) -> str:
        session_id = params.get("sessionId")
        if not isinstance(session_id, str) or not session_id:
            raise _RpcError(INVALID_PARAMS, "sessionId must be a non-empty string")
        with self._state_lock:
            expected = self._session_id
        if expected is None or session_id != expected:
            raise _RpcError(SESSION_NOT_FOUND, "session not found")
        return session_id

    def _prompt(self, params: Any, request_id: str | int) -> None:
        params = self._params_object(params)
        session_id = self._validate_session(params)
        prompt = params.get("prompt")
        if not isinstance(prompt, list) or not prompt:
            raise _RpcError(INVALID_PARAMS, "prompt must be a non-empty array")
        parts: list[str] = []
        for block in prompt:
            if not isinstance(block, dict):
                raise _RpcError(INVALID_PARAMS, "prompt blocks must be objects")
            block_type = block.get("type")
            if block_type == "text":
                text = block.get("text")
                if not isinstance(text, str):
                    raise _RpcError(INVALID_PARAMS, "Text block text must be a string")
                parts.append(text)
                continue
            if block_type == "resource_link":
                uri = block.get("uri")
                name = block.get("name")
                if not isinstance(uri, str) or not uri:
                    raise _RpcError(
                        INVALID_PARAMS,
                        "ResourceLink uri must be a non-empty string",
                    )
                if not isinstance(name, str) or not name:
                    raise _RpcError(
                        INVALID_PARAMS,
                        "ResourceLink name must be a non-empty string",
                    )
                projected: dict[str, Any] = {
                    "type": "resource_link",
                    "uri": uri,
                    "name": name,
                }
                for field_name in ("mimeType", "title", "description"):
                    value = block.get(field_name)
                    if value is not None:
                        if not isinstance(value, str):
                            raise _RpcError(
                                INVALID_PARAMS,
                                f"ResourceLink {field_name} must be a string",
                            )
                        projected[field_name] = value
                size = block.get("size")
                if size is not None:
                    if (
                        not isinstance(size, int)
                        or isinstance(size, bool)
                        or size < 0
                    ):
                        raise _RpcError(
                            INVALID_PARAMS,
                            "ResourceLink size must be a non-negative integer",
                        )
                    projected["size"] = size
                parts.append(
                    "\n\n"
                    + json.dumps(
                        projected,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        allow_nan=False,
                    )
                    + "\n\n"
                )
                continue
            raise _RpcError(
                UNSUPPORTED,
                "this adapter accepts Text and ResourceLink prompt blocks only",
            )
        content = "".join(parts)
        if not content:
            raise _RpcError(INVALID_PARAMS, "prompt content must not be empty")

        with self._state_lock:
            if self._closing:
                raise _RpcError(INTERNAL_ERROR, "server is closing")
            if self._active is not None:
                raise _RpcError(SESSION_BUSY, "session already has an active prompt")
            try:
                handle = self._agent.submit_turn(
                    content,
                    sender="user",
                    correlation_id=f"acp_{uuid4().hex}",
                    execution_workspace=self._execution_workspace,
                )
            except (TypeError, ValueError) as exc:
                raise _RpcError(INVALID_PARAMS, str(exc)) from exc
            except RuntimeError as exc:
                raise _RpcError(INTERNAL_ERROR, "agent cannot accept the turn") from exc
            active = _ActivePrompt(request_id, session_id, handle)
            worker = threading.Thread(
                target=self._await_prompt,
                args=(active,),
                daemon=True,
                name=f"acp-prompt-{handle.correlation_id[-12:]}",
            )
            active.thread = worker
            self._active = active
            self._prompt_threads.add(worker)
            try:
                worker.start()
            except BaseException:
                self._active = None
                self._prompt_threads.discard(worker)
                handle.cancel()
                raise

    def _cancel(self, params: Any) -> None:
        params = self._params_object(params)
        session_id = self._validate_session(params)
        with self._state_lock:
            active = self._active
            if active is not None and active.session_id == session_id:
                # Keep adapter settlement ordering linear: the prompt worker also
                # takes this lock before emitting its terminal response, so a
                # received cancel reaches the Core handle before that response.
                active.handle.cancel()
        return None

    def _await_prompt(self, active: _ActivePrompt) -> None:
        accepted = False
        try:
            result = active.handle.result()
        except Exception:
            result = None
        try:
            with self._state_lock:
                if self._active is not active:
                    return
                if self._closing or self._shutdown_requested():
                    self._active = None
                    return
                # Close/cancel and terminal ownership linearize under one lock.
                # The captured generation is re-checked when the atomic terminal
                # batch enters the queue and before each physical write begins.
                active.terminal_claimed = True
                generation = self._generation

            messages: list[dict[str, Any]] = []
            if result is None or result.outcome is TurnOutcome.FAILED:
                messages.append({
                    "jsonrpc": JSONRPC_VERSION,
                    "id": active.request_id,
                    "error": {
                        "code": INTERNAL_ERROR,
                        "message": "LingTai turn failed",
                    },
                })
            elif result.outcome is TurnOutcome.CANCELLED:
                messages.append({
                    "jsonrpc": JSONRPC_VERSION,
                    "id": active.request_id,
                    "result": {"stopReason": "cancelled"},
                })
            else:
                if result.text:
                    messages.append({
                        "jsonrpc": JSONRPC_VERSION,
                        "method": "session/update",
                        "params": {
                            "sessionId": active.session_id,
                            "update": {
                                "sessionUpdate": "agent_message_chunk",
                                "content": {
                                    "type": "text",
                                    "text": result.text,
                                },
                            },
                        },
                    })
                messages.append({
                    "jsonrpc": JSONRPC_VERSION,
                    "id": active.request_id,
                    "result": {"stopReason": "end_turn"},
                })
            accepted = self._enqueue_messages(
                messages,
                generation=generation,
                active=active,
            )
        except Exception:
            # Serialization is deterministic for the fixed shapes above. If an
            # injected value still surprises us, fail the whole transport closed
            # without a fallback frame or a worker traceback.
            self.close()
        finally:
            thread = threading.current_thread()
            with self._state_lock:
                if not accepted and self._active is active:
                    self._active = None
                self._prompt_threads.discard(thread)

    def _shutdown_requested(self) -> bool:
        shutdown = getattr(self._agent, "_shutdown", None)
        return shutdown is not None and shutdown.is_set()

    def _write_result(self, request_id: Any, result: Any) -> bool:
        return self._enqueue_messages(({
            "jsonrpc": JSONRPC_VERSION,
            "id": request_id,
            "result": result,
        },))

    def _write_error(self, request_id: Any, code: int, message: str) -> bool:
        return self._enqueue_messages(({
            "jsonrpc": JSONRPC_VERSION,
            "id": request_id,
            "error": {"code": code, "message": message},
        },))

    def _write_notification(self, method: str, params: dict[str, Any]) -> bool:
        return self._enqueue_messages(({
            "jsonrpc": JSONRPC_VERSION,
            "method": method,
            "params": params,
        },))

    def _enqueue_messages(
        self,
        messages,
        *,
        generation: int | None = None,
        active: _ActivePrompt | None = None,
    ) -> bool:
        try:
            wires: list[str] = []
            for message in messages:
                wire = json.dumps(
                    message,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    allow_nan=False,
                )
                if "\n" in wire or "\r" in wire:
                    raise ValueError("JSON-RPC frame contains an embedded newline")
                wires.append(wire + "\n")
        except Exception:
            self._abort_transport()
            return False

        active_to_cancel = None
        accepted = True
        with self._state_lock:
            if self._closing or self._shutdown_requested():
                return False
            if generation is None:
                generation = self._generation
            elif generation != self._generation:
                return False
            try:
                self._outbound.put_nowait(
                    _OutboundBatch(generation, tuple(wires), active)
                )
            except queue.Full:
                # A non-reading client may never release the writer. Bound memory
                # and fail the whole transport closed rather than blocking the
                # coordinator or leaking a partial prompt terminal batch.
                accepted = False
                self._aborted = True
                self._closing = True
                self._generation += 1
                active_to_cancel = self._active
                self._active = None
        if active_to_cancel is not None:
            active_to_cancel.handle.cancel()
        return accepted

    def _writer_loop(self) -> None:
        """Serialize queued batches without ever becoming teardown authority."""

        while True:
            try:
                batch = self._outbound.get(timeout=0.1)
            except queue.Empty:
                with self._state_lock:
                    if self._closing:
                        return
                continue
            try:
                for wire in batch.wires:
                    with self._state_lock:
                        if self._aborted or (
                            batch.active is not None
                            and (
                                self._closing
                                or batch.generation != self._generation
                                or self._shutdown_requested()
                            )
                        ):
                            break
                        # This state check is the start linearization point. Close
                        # can invalidate every frame that has not crossed it, but
                        # no Python API can revoke an OS write already in progress.
                    written = self._output.write(wire)
                    if written != len(wire):
                        raise OSError("short ACP stdout write")
                    self._output.flush()
            except Exception:
                self._abort_transport()
                return
            finally:
                with self._state_lock:
                    if batch.active is not None and self._active is batch.active:
                        self._active = None
                self._outbound.task_done()


__all__ = ["ACP_PROTOCOL_VERSION", "AcpStdioServer"]
