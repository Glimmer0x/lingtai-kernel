"""System name actions — the agent's true name and its mutable nickname.

These two handlers moved here verbatim from the former ``psyche`` family
(``psyche(action='name_set'|'name_nickname')``) when ``psyche`` was dissolved:
``context`` took the context lifecycle, and identity naming — which is runtime
state, like every other ``system`` action — came here. The action names,
argument (``content``), success payloads, and error strings are exactly what
they were; only the owning public root changed.

These are NOT init-file editing and NOT the physical agent address/workdir
rename. ``agent.set_name``/``set_nickname`` update live in-memory identity,
persist ``.agent.json``, and rewrite the protected prompt ``identity``
section; the BaseAgent Port owns that implementation and keeps it. Renaming an
agent's address/working directory remains the operator migration workflow
documented in ``system-manual``, and no action here touches it.
"""
from __future__ import annotations


def _name_set(agent, args: dict) -> dict:
    """Set the agent's true name (真名). One-time and immutable thereafter."""
    name = args.get("content", "").strip()
    if not name:
        return {"error": "Name cannot be empty. Provide your chosen name in 'content'."}
    try:
        agent.set_name(name)
    except RuntimeError as e:
        return {"error": str(e)}
    return {"status": "ok", "name": name}


def _name_nickname(agent, args: dict) -> dict:
    """Set or change the agent's nickname (别名). Mutable; empty clears it."""
    nickname = args.get("content", "").strip()
    agent.set_nickname(nickname)
    return {"status": "ok", "nickname": nickname or None}
