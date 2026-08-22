"""Schema data — canonical per-action ``input`` schemas for the ``email`` family.

This module holds only data: one strict, closed ``input_schema`` per public
``email`` action (:data:`INPUT_SCHEMAS`), the canonical action order
(:data:`ACTION_ORDER`), and the canonical English action prose
(:data:`ACTION_ENUM_DESCRIPTION`).  ``__init__.py`` composes these into the
public model-facing schema via the generic ``ToolFamily`` infra
(``lingtai.tools.tool_family``) — see ``__init__.py::get_schema``.

Why a new module rather than reshaping ``schema.py``: ``schema.py``'s flat
``get_schema()`` is still the *internal* ``EmailManager.handle`` argument
shape (the same seam ``shell`` kept when its ``ShellManager`` stayed flat —
``tools/CONTRACT.md`` "Relationship to current runtime"), and
``tests/test_layers_email.py`` pins several of its facts.  Keeping the
per-action data here means the model-facing composition and the legacy flat
shape have one owner each, and the ledger in the migration report can name
exactly what each file is for.

Field descriptions are reused verbatim from ``schema.py``'s flat properties
wherever the field is the same field, so the migration changes the envelope
and not the prose the model reads.  ``ACTION_ORDER`` is the single source for
the ``action`` enum order, the ``input.oneOf``/``allOf`` branch order, and the
child registration order in ``__init__.py`` — one list, not three.

Optional fields are declared in the provider-compatible nullable
representation (``"type": [..., "null"]`` plus membership in ``required``) per
``tools/CONTRACT.md`` "Envelope": a strict OpenAI schema has no other way to
express an optional field.  ``__init__.py`` strips those nulls back to
*absent* before the pre-existing ``EmailManager`` handlers run, so their
``args.get("folder", "inbox")``-style defaulting — and the difference between
"folder omitted" and "folder null" that ``_read``/``_search`` genuinely
depend on — is preserved exactly.
"""
from __future__ import annotations

from typing import Any

from .primitives import mode_field
# ``MANUAL_INPUT_SCHEMA`` is no longer named here: the reserved branch is
# appended by ``EMAIL_PLUGIN`` from that same canonical literal (see
# ``.._plugin``), which is what makes re-schema-ing it locally impossible.
from .plugin import EMAIL_ACTIONS, EMAIL_DECLARED_ACTIONS, EMAIL_PLUGIN

# The canonical public action order. Identical to the pre-migration flat
# ``schema.py`` ``action`` enum, in the same order, including the reserved
# family-owned ``manual`` last — but composed rather than restated: the package
# declares its own thirteen actions in ``plugin.py`` and ``EMAIL_PLUGIN``
# appends ``manual`` from the plugin-owned skill, so this list cannot lose or
# rebind the reserved action.
DECLARED_ACTIONS: tuple[str, ...] = EMAIL_DECLARED_ACTIONS
ACTION_ORDER: tuple[str, ...] = EMAIL_ACTIONS

# --- Shared field descriptions, verbatim from the pre-migration flat schema ---

_ADDRESS_DESCRIPTION = "Target address(es) for send"
_CC_DESCRIPTION = "CC addresses — visible to all recipients"
_BCC_DESCRIPTION = "BCC addresses — hidden from other recipients"
_ATTACHMENTS_DESCRIPTION = "File paths to attach (for send)"
_SUBJECT_DESCRIPTION = "Email subject line"
_MESSAGE_DESCRIPTION = (
    "Email body (max 50,000 chars; longer internal emails are rejected "
    "because unread bodies are injected in full into persistent "
    "notifications)."
)
_EMAIL_ID_DESCRIPTION = (
    "List of email IDs for read. For reply/reply_all, pass a single-element "
    "list."
)
_N_DESCRIPTION = "Max recent emails to show (for check, default 10)"
_QUERY_DESCRIPTION = "Regex pattern for search (matches from, subject, message)"
_FOLDER_DESCRIPTION = (
    "Folder for check/search/read/delete. Default: inbox for check, both for "
    "search. Note: 'sent' is read-only — delete only works on inbox or "
    "archive."
)
_DELAY_DESCRIPTION = (
    "Delay in seconds before delivery (default: 0). Use for scheduled or "
    "deferred sends."
)
_TYPE_DESCRIPTION = "Email type (for send). Defaults to 'normal'."
_NAME_DESCRIPTION = (
    "Contact's human-readable name (for add_contact, edit_contact)"
)
_NOTE_DESCRIPTION = (
    "Free-text note about the contact (for add_contact, edit_contact)"
)

# The ``filter`` object for ``check``, verbatim from the flat schema's own
# nested ``filter`` property (same properties, same descriptions, same
# ``truncate`` default). ``additionalProperties: False`` is added because a
# migrated family's ``input`` branches are closed all the way down
# (``tools/CONTRACT.md`` "Envelope": "Action branches are closed").
_FILTER_SCHEMA: dict[str, Any] = {
    "type": ["object", "null"],
    "description": (
        "Optional filter object for check. Pass filter={sort, from, subject, "
        "contains, after, before, unread_only, has_attachments, truncate} to "
        "narrow and control results."
    ),
    "properties": {
        "sort": {
            "type": ["string", "null"],
            "enum": ["newest", "oldest", None],
            "description": "'newest' (default) or 'oldest'.",
        },
        "from": {
            "type": ["string", "null"],
            "description": "Filter by sender (case-insensitive substring match).",
        },
        "subject": {
            "type": ["string", "null"],
            "description": "Filter by subject (case-insensitive substring match).",
        },
        "contains": {
            "type": ["string", "null"],
            "description": (
                "Filter by message body content (case-insensitive substring "
                "match)."
            ),
        },
        "after": {
            "type": ["string", "null"],
            "description": (
                "Only show emails after this ISO 8601 timestamp (e.g. "
                "2026-04-01T00:00:00Z)."
            ),
        },
        "before": {
            "type": ["string", "null"],
            "description": "Only show emails before this ISO 8601 timestamp.",
        },
        "unread_only": {
            "type": ["boolean", "null"],
            "description": "Only show unread emails.",
        },
        "has_attachments": {
            "type": ["boolean", "null"],
            "description": "Only show emails that have attachments.",
        },
        "truncate": {
            "type": ["integer", "null"],
            "description": (
                "Max characters for message preview (default 500). Set to 0 "
                "for full message body."
            ),
        },
    },
    "required": [
        "sort", "from", "subject", "contains", "after", "before",
        "unread_only", "has_attachments", "truncate",
    ],
    "additionalProperties": False,
}


def _mode_property() -> dict[str, Any]:
    """``send``'s optional address-mode field, nullable-wrapped.

    Reuses ``primitives.mode_field`` — the one owned definition of this
    field's enum and its long routing description — rather than restating it,
    so the peer/abs guidance cannot drift between the legacy flat schema and
    this one. Only the nullable representation is added on top.
    """
    field = dict(mode_field())
    field["type"] = ["string", "null"]
    field["enum"] = [*field["enum"], None]
    return field


_SEND_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "address": {
            "anyOf": [
                {"type": "string"},
                {"type": "array", "items": {"type": "string"}},
            ],
            "description": _ADDRESS_DESCRIPTION,
        },
        "subject": {"type": ["string", "null"], "description": _SUBJECT_DESCRIPTION},
        "message": {"type": ["string", "null"], "description": _MESSAGE_DESCRIPTION},
        "cc": {
            "type": ["array", "null"],
            "items": {"type": "string"},
            "description": _CC_DESCRIPTION,
        },
        "bcc": {
            "type": ["array", "null"],
            "items": {"type": "string"},
            "description": _BCC_DESCRIPTION,
        },
        "attachments": {
            "type": ["array", "null"],
            "items": {"type": "string"},
            "description": _ATTACHMENTS_DESCRIPTION,
        },
        "delay": {"type": ["integer", "null"], "description": _DELAY_DESCRIPTION},
        "mode": _mode_property(),
        "type": {
            "type": ["string", "null"],
            "enum": ["normal", None],
            "description": _TYPE_DESCRIPTION,
        },
    },
    "required": [
        "address", "subject", "message", "cc", "bcc", "attachments",
        "delay", "mode", "type",
    ],
    "additionalProperties": False,
}

_CHECK_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "folder": {
            "type": ["string", "null"],
            "enum": ["inbox", "sent", "archive", None],
            "description": _FOLDER_DESCRIPTION,
        },
        "n": {"type": ["integer", "null"], "description": _N_DESCRIPTION},
        "filter": _FILTER_SCHEMA,
    },
    "required": ["folder", "n", "filter"],
    "additionalProperties": False,
}

_READ_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "email_id": {
            "type": "array",
            "items": {"type": "string"},
            "description": _EMAIL_ID_DESCRIPTION,
        },
        "folder": {
            "type": ["string", "null"],
            "enum": ["inbox", "sent", "archive", None],
            "description": _FOLDER_DESCRIPTION,
        },
    },
    "required": ["email_id", "folder"],
    "additionalProperties": False,
}

# ``dismiss`` takes no ``folder``: it is inbox-only by construction
# (``manager._dismiss`` resolves each id and treats anything outside the inbox
# as ``already_handled``), so admitting the key would advertise an argument the
# action never reads.
_DISMISS_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "email_id": {
            "type": "array",
            "items": {"type": "string"},
            "description": _EMAIL_ID_DESCRIPTION,
        },
    },
    "required": ["email_id"],
    "additionalProperties": False,
}

# ``reply``/``reply_all`` share a shape: a single-element ``email_id`` list,
# the required body, and the optional subject override plus cc/bcc fan-out.
def _reply_input_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "email_id": {
                "type": "array",
                "items": {"type": "string"},
                "description": _EMAIL_ID_DESCRIPTION,
            },
            "message": {"type": "string", "description": _MESSAGE_DESCRIPTION},
            "subject": {
                "type": ["string", "null"],
                "description": _SUBJECT_DESCRIPTION,
            },
            "cc": {
                "type": ["array", "null"],
                "items": {"type": "string"},
                "description": _CC_DESCRIPTION,
            },
            "bcc": {
                "type": ["array", "null"],
                "items": {"type": "string"},
                "description": _BCC_DESCRIPTION,
            },
        },
        "required": ["email_id", "message", "subject", "cc", "bcc"],
        "additionalProperties": False,
    }


_SEARCH_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": _QUERY_DESCRIPTION},
        "folder": {
            "type": ["string", "null"],
            "enum": ["inbox", "sent", "archive", None],
            "description": _FOLDER_DESCRIPTION,
        },
    },
    "required": ["query", "folder"],
    "additionalProperties": False,
}

# ``archive`` moves inbox mail only — no ``folder`` argument exists in
# ``manager._archive``.
_ARCHIVE_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "email_id": {
            "type": "array",
            "items": {"type": "string"},
            "description": _EMAIL_ID_DESCRIPTION,
        },
    },
    "required": ["email_id"],
    "additionalProperties": False,
}

# ``delete`` accepts only the two writable folders; ``sent`` is read-only and
# ``manager._delete`` rejects it with "Cannot delete from folder: sent". The
# enum here narrows the advertised choice to what the action actually allows,
# while that runtime rejection stays in place for direct/internal callers.
_DELETE_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "email_id": {
            "type": "array",
            "items": {"type": "string"},
            "description": _EMAIL_ID_DESCRIPTION,
        },
        "folder": {
            "type": ["string", "null"],
            "enum": ["inbox", "archive", None],
            "description": _FOLDER_DESCRIPTION,
        },
    },
    "required": ["email_id", "folder"],
    "additionalProperties": False,
}

_CONTACTS_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "required": [],
    "additionalProperties": False,
}

_ADD_CONTACT_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "address": {"type": "string", "description": _ADDRESS_DESCRIPTION},
        "name": {"type": "string", "description": _NAME_DESCRIPTION},
        "note": {"type": ["string", "null"], "description": _NOTE_DESCRIPTION},
    },
    "required": ["address", "name", "note"],
    "additionalProperties": False,
}

_REMOVE_CONTACT_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "address": {"type": "string", "description": _ADDRESS_DESCRIPTION},
    },
    "required": ["address"],
    "additionalProperties": False,
}

# ``edit_contact`` distinguishes absent from present for ``name``/``note``
# (``manager._edit_contact`` uses ``if "name" in args``), which the null-strip
# in ``__init__.py`` preserves: a null becomes absent and leaves the stored
# field untouched, exactly as omitting it did pre-migration.
_EDIT_CONTACT_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "address": {"type": "string", "description": _ADDRESS_DESCRIPTION},
        "name": {"type": ["string", "null"], "description": _NAME_DESCRIPTION},
        "note": {"type": ["string", "null"], "description": _NOTE_DESCRIPTION},
    },
    "required": ["address", "name", "note"],
    "additionalProperties": False,
}

#: One strict ``input_schema`` per public action. Email declares only its own
#: thirteen; ``EMAIL_PLUGIN.action_input_schemas`` appends the reserved
#: ``manual`` branch from the exported canonical ``MANUAL_INPUT_SCHEMA`` literal
#: rather than restating it (``tool_family/CONTRACT.md``: families MUST NOT
#: restate it locally), so the schema-only family composed here and the real
#: dispatching family in ``__init__.py`` — which registers the shared
#: ManualTool child — advertise byte-identical ``manual`` input, and a package
#: that tried to re-schema ``manual`` here would raise at import.
INPUT_SCHEMAS: dict[str, dict[str, Any]] = EMAIL_PLUGIN.action_input_schemas({
    "send": _SEND_INPUT_SCHEMA,
    "check": _CHECK_INPUT_SCHEMA,
    "read": _READ_INPUT_SCHEMA,
    "dismiss": _DISMISS_INPUT_SCHEMA,
    "reply": _reply_input_schema(),
    "reply_all": _reply_input_schema(),
    "search": _SEARCH_INPUT_SCHEMA,
    "archive": _ARCHIVE_INPUT_SCHEMA,
    "delete": _DELETE_INPUT_SCHEMA,
    "contacts": _CONTACTS_INPUT_SCHEMA,
    "add_contact": _ADD_CONTACT_INPUT_SCHEMA,
    "remove_contact": _REMOVE_CONTACT_INPUT_SCHEMA,
    "edit_contact": _EDIT_CONTACT_INPUT_SCHEMA,
})

# The canonical ``action`` enum prose. Reuses the pre-migration flat schema's
# own action description verbatim, with the envelope's ``input=`` call form
# substituted for the old flat keyword form, and the ``manual`` sentence
# extended with the family's ``summarize`` guidance profile
# (``tools/CONTRACT.md`` "Dispatch and actions").
ACTION_ENUM_DESCRIPTION = (
    "send: send with optional cc/bcc (requires address, message; message body "
    "max 50,000 chars because unread bodies are injected in full into "
    "persistent notifications). check: list mailbox with preview of each email "
    "(up to 500 chars). read: fetch inbox emails by ID list "
    "(input={'email_id': [id1, id2, ...], ...}) AND marks each as read; "
    "ordinary unread content is already injected in "
    "notification_persistent.email, so prefer dismiss when you only need to "
    "clear handled mail. dismiss: same read-state effect as read but returns "
    "no bodies — preferred after handling content visible in persistent "
    "notification. reply: reply to email (requires email_id, message). "
    "reply_all: reply to all recipients. search: regex search mailbox. "
    "archive/delete: move/remove from inbox or archive. "
    "contacts/add_contact/remove_contact/edit_contact manage contacts. manual "
    "returns the installed email-manual skill without reading or changing "
    "mailbox state."
)
