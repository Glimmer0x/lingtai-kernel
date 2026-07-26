"""Closed canonical schema and description for the internal ``email`` tool."""
from __future__ import annotations

from typing import Any

from .primitives import mode_field


_ACTIONS = [
    "send", "check", "read", "dismiss", "reply", "reply_all", "search",
    "archive", "delete", "contacts", "add_contact", "remove_contact",
    "edit_contact", "manual",
]


def _closed_input(title: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "title": title,
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _address() -> dict[str, Any]:
    return {
        "oneOf": [
            {"type": "string"},
            {"type": "array", "items": {"type": "string"}},
        ],
        "description": "Bare internal address, or a list of bare internal addresses.",
    }


def _ids() -> dict[str, Any]:
    return {
        "oneOf": [
            {"type": "string"},
            {"type": "array", "items": {"type": "string"}},
        ],
        "description": "One mailbox ID, or a list of mailbox IDs.",
    }


def _filter_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "sort": {
                "type": "string", "enum": ["newest", "oldest"],
                "description": "Result order; newest is the default.",
            },
            "from": {"type": "string", "description": "Case-insensitive sender substring."},
            "subject": {"type": "string", "description": "Case-insensitive subject substring."},
            "contains": {"type": "string", "description": "Case-insensitive body substring."},
            "after": {"type": "string", "description": "ISO 8601 lower time bound."},
            "before": {"type": "string", "description": "ISO 8601 upper time bound."},
            "unread_only": {"type": "boolean", "description": "Only unread messages."},
            "has_attachments": {"type": "boolean", "description": "Only messages with attachments."},
            "truncate": {
                "type": "integer", "default": 500,
                "description": "Preview character limit; zero or a negative value keeps the full body.",
            },
        },
        "required": [],
        "additionalProperties": False,
    }


def get_description(lang: str = "en") -> str:
    return (
        "Internal LingTai email within the .lingtai/ network, never internet email. "
        "The public call is always email(action=..., input={...}); BaseAgent alone "
        "adds optional root reasoning. Actions are send, check, read, dismiss, reply, "
        "reply_all, search, archive, delete, contacts, add_contact, remove_contact, "
        "edit_contact, and manual. Use email(action='manual', input={}) for the "
        "installed read-only email manual. Prefer reply/reply_all on the channel where "
        "mail arrived; use imap for Gmail/Outlook and other real internet email."
    )


def get_schema(lang: str = "en") -> dict[str, Any]:
    """Return the raw closed ``action`` + nested ``input`` contract.

    ``reasoning`` is intentionally absent.  ``BaseAgent`` injects that optional
    root metadata into its provider-facing copy, while the action input branches
    remain owned and closed here.
    """
    common_cc = {"type": "array", "items": {"type": "string"}, "description": "CC addresses."}
    common_bcc = {"type": "array", "items": {"type": "string"}, "description": "BCC addresses."}
    subject = {"type": "string", "description": "Email subject."}
    message = {
        "type": "string",
        "description": "Email body; internal sends reject bodies over 50,000 characters.",
    }
    branches = [
        _closed_input(
            "send input",
            {
                "address": _address(),
                "cc": common_cc,
                "bcc": common_bcc,
                "attachments": {"type": "array", "items": {"type": "string"}, "description": "Attachment paths."},
                "subject": subject,
                "message": message,
                "delay": {"type": "integer", "default": 0, "description": "Delivery delay in seconds."},
                "mode": mode_field(lang),
                "type": {"type": "string", "enum": ["normal"], "default": "normal", "description": "Email type."},
            },
            ["address", "message"],
        ),
        _closed_input(
            "check input",
            {
                "n": {"type": "integer", "default": 10, "description": "Maximum recent messages; non-positive means all."},
                "folder": {"type": "string", "enum": ["inbox", "sent", "archive"], "description": "Folder; default inbox."},
                "filter": {**_filter_schema(), "description": "Optional structured check filters."},
            },
            [],
        ),
        _closed_input("read input", {"email_id": _ids(), "folder": {"type": "string", "enum": ["inbox", "sent", "archive"]}}, ["email_id"]),
        _closed_input("dismiss input", {"email_id": _ids()}, ["email_id"]),
        _closed_input(
            "reply input",
            {"email_id": _ids(), "message": message, "subject": subject, "cc": common_cc, "bcc": common_bcc},
            ["email_id", "message"],
        ),
        _closed_input(
            "reply_all input",
            {"email_id": _ids(), "message": message, "subject": subject, "cc": common_cc, "bcc": common_bcc},
            ["email_id", "message"],
        ),
        _closed_input(
            "search input",
            {
                "query": {"type": "string", "description": "Case-insensitive regular expression."},
                "folder": {"type": "string", "enum": ["inbox", "sent", "archive"], "description": "Folder; default searches inbox and sent."},
            },
            ["query"],
        ),
        _closed_input("archive input", {"email_id": _ids()}, ["email_id"]),
        _closed_input(
            "delete input",
            {"email_id": _ids(), "folder": {"type": "string", "enum": ["inbox", "archive"], "default": "inbox"}},
            ["email_id"],
        ),
        _closed_input("contacts input", {}, []),
        _closed_input("add_contact input", {"address": {"type": "string"}, "name": {"type": "string"}, "note": {"type": "string"}}, ["address", "name"]),
        _closed_input("remove_contact input", {"address": {"type": "string"}}, ["address"]),
        _closed_input("edit_contact input", {"address": {"type": "string"}, "name": {"type": "string"}, "note": {"type": "string"}}, ["address"]),
        _closed_input("manual input", {}, []),
    ]
    return {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": list(_ACTIONS),
                "description": "Required email operation.",
            },
            "input": {
                "type": "object",
                "anyOf": branches,
                "description": "Required strict action-specific email input; no flat aliases.",
            },
        },
        "required": ["action", "input"],
        "additionalProperties": False,
    }
