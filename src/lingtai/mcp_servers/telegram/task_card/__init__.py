"""Retained legacy Telegram Task Card package.

The current public model-facing ``task_card`` capability is owned by
``lingtai.tools.task_card``. It produces the channel-neutral
``<workdir>/taskcard/status`` and ``<workdir>/taskcard/taskcard.md`` artifact,
with one intrinsic-owned watch per agent. Telegram only reads that artifact and
projects active, nonempty bodies into its resident programmable slot.

This package remains shipped for historical compatibility and for the
Telegram-side resident/projection Anatomy/Contract. The old controller,
interface, schema helpers, and reverse-channel names are not the active public
ownership path and must not be documented as an endpoint to use.

See ``SKILL.md`` for the retained-legacy/projection notice, ``CONTRACT.md`` for
the Telegram projection promise, and ``ANATOMY.md`` for the current structure.
"""

from __future__ import annotations

from .controller import (
    TaskCardController,
    TaskCardControllerError,
    get_description,
    get_schema,
    setup,
)
from .interface import TelegramTaskCardAgent
from .resident import TaskCardResident

__all__ = [
    "TaskCardController",
    "TaskCardResident",
    "TaskCardControllerError",
    "TelegramTaskCardAgent",
    "get_description",
    "get_schema",
    "setup",
]
