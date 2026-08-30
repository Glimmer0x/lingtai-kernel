"""LingTai Cloud Mail MCP server.

Exposes the omnibus ``cloud_mail`` tool (six operational actions plus
owner-only settings and the packaged manual) over MCP/stdio and pushes inbound
mail into the host agent's inbox via LICC. Talks to a self-hosted Cloud Mail
deployment (https://github.com/maillab/cloud-mail) over its REST API using
``httpx``.

Reads multi-account config from a JSON file pointed at by the
``LINGTAI_CLOUD_MAIL_CONFIG`` env var; public settings inventory redacts both
the resolved path and the opaque account-document marker.
"""
from .licc import push_inbox_event
from .server import build_manager, build_server, load_config, serve

__all__ = [
    "serve",
    "build_server",
    "build_manager",
    "load_config",
    "push_inbox_event",
]
