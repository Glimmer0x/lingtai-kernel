"""Retained legacy host-agent interface for the old Telegram controller.

The active public ``task_card`` capability no longer depends on this protocol;
``lingtai.tools.task_card`` owns renderer execution, artifact files, and watch
lifecycle. Telegram's current role is read-only projection of that intrinsic
artifact into the resident programmable slot.

This protocol remains only because the historical controller source remains on
disk. It describes the host surface the retired controller consumed and should
not be treated as a current registration or endpoint contract.
"""

from __future__ import annotations

import os
import threading
from typing import Any, Callable, Protocol


class TelegramTaskCardAgent(Protocol):
    """Historical minimal agent surface consumed by the retired controller.

    The normative current Task Card promise is in
    ``src/lingtai/tools/task_card/CONTRACT.md``.
    """

    #: Absolute agent working directory — renderer-path confinement root and the
    #: subprocess ``cwd`` for every renderer run.
    _working_dir: str | os.PathLike[str]
    #: Historical ``tool_name -> MCP client`` map used by the retired private
    #: Telegram reverse channel.
    _mcp_clients_by_tool: dict[str, Any]
    #: Historical turn-local Telegram route used by the retired controller.
    _telegram_task_card_context: dict | None
    #: Set at agent teardown so watcher loops exit promptly (optional).
    _shutdown: threading.Event

    def add_tool(
        self,
        name: str,
        *,
        schema: dict,
        handler: Callable[[dict], dict],
        description: str = ...,
        glossary_package: Any = ...,
    ) -> Any:
        """Historical registration hook used by the retired controller."""
        ...

    def _enqueue_system_notification(self, **kwargs: Any) -> Any:
        """Publish a deduped durable system-notification wake (optional)."""
        ...
